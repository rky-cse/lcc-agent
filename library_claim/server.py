"""M02b local capture server. No provider credentials or model calls."""

import argparse
import asyncio
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .capture_session import CaptureSessions
from .capture_store import CaptureInput, FrameStore
from .models import Contract
from .tracking import TrackStore


class StartInput(Contract):
    start_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    country: str
    currency: str


class EndInput(Contract):
    end_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    capture_gaps: int = Field(ge=0)


def create_app(root: Path, origins: set[str], *, synthetic: bool = False) -> FastAPI:
    if not origins or any(urlsplit(x).scheme not in {"http", "https"} or not urlsplit(x).netloc
                          or urlsplit(x).path for x in origins):
        raise ValueError("configure exact HTTP(S) origins without trailing slash")
    hosts = {urlsplit(x).netloc for x in origins}
    sessions = CaptureSessions(FrameStore(root))
    inventory = TrackStore(sessions.store)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sessions = sessions
    slots = asyncio.Semaphore(2)
    web = Path(__file__).with_name("web")

    async def control_body(request, model):
        data = bytearray()
        try:
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > 4096:
                        raise HTTPException(413, "Control body limit exceeded")
                    data.extend(chunk)
            return model.model_validate_json(data)
        except (ValidationError, ValueError) as error:
            raise HTTPException(422, "Invalid control request") from error
        except TimeoutError as error:
            raise HTTPException(408, "Control request timeout") from error

    @app.middleware("http")
    async def boundaries(request, call_next):
        if request.headers.get("host") not in hosts:
            return JSONResponse({"detail": "Host is not configured"}, status_code=403)
        if request.method not in {"GET", "HEAD"} and request.headers.get("origin") not in origins:
            return JSONResponse({"detail": "Origin is not configured"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob:; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(OSError)
    @app.exception_handler(sqlite3.Error)
    async def storage_failure(request, error):
        return JSONResponse({"detail": "Storage failed; frame was not acknowledged. Retry the same upload ID."}, status_code=503)

    @app.get("/")
    def index():
        return FileResponse(web / "index.html")

    @app.get("/assets/{name}")
    def asset(name: str):
        if name not in {"app.mjs", "queue.mjs", "inventory.mjs", "style.css"}:
            raise HTTPException(404)
        return FileResponse(web / name, media_type="text/javascript" if name.endswith(".mjs") else "text/css")

    @app.get("/api/health")
    def health():
        return {"module": "M02b", "provider_calls": False, "synthetic_capture_mode": synthetic, "limits": sessions.store.limits.model_dump()}

    @app.post("/api/sweeps")
    async def start(request: Request):
        body = await control_body(request, StartInput)
        try:
            return await run_in_threadpool(sessions.start, body.country, body.currency, body.start_id)
        except ValidationError as error:
            raise HTTPException(422, "Country/currency must be uppercase 2/3-letter codes") from error

    @app.get("/api/sweeps/{sweep_id}")
    def snapshot(sweep_id: str):
        return sessions.snapshot(sweep_id)

    @app.post("/api/sweeps/{sweep_id}/frames")
    async def upload(sweep_id: str, request: Request, upload_id: str, captured_at: str, media_sequence: int):
        try:
            capture = CaptureInput(sweep_id=sweep_id, upload_id=upload_id, captured_at=captured_at,
                                   media_sequence=media_sequence, source="browser_camera", synthetic=synthetic)
        except ValidationError as error:
            raise HTTPException(422, "Invalid capture metadata") from error
        if request.headers.get("content-type") not in {"image/jpeg", "image/png"}:
            raise HTTPException(415, "JPEG/PNG required")
        if slots.locked():
            raise HTTPException(429, "Upload capacity busy; retry same ID")
        async with slots:
            limit = sessions.store.limits.max_bytes
            body = bytearray()
            try:
                async with asyncio.timeout(20):
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > limit:
                            raise HTTPException(413, "Image byte limit exceeded")
                        body.extend(chunk)
            except TimeoutError as error:
                raise HTTPException(408, "Upload timed out; retry same ID") from error
            return await run_in_threadpool(sessions.upload, capture, bytes(body))

    @app.post("/api/sweeps/{sweep_id}/end")
    async def end(sweep_id: str, request: Request):
        body = await control_body(request, EndInput)
        return await run_in_threadpool(sessions.end, sweep_id, body.end_id, body.capture_gaps)

    @app.get("/api/sweeps/{sweep_id}/manifest")
    def manifest(sweep_id: str):
        return sessions.snapshot(sweep_id)

    @app.get("/api/frames/{frame_id}")
    def original(frame_id: str):
        record = sessions.store.get(frame_id)
        data = sessions.store.read(frame_id)
        return Response(data, media_type=record.mime_type, headers={"ETag": f'"{record.sha256}"'})

    @app.get("/api/sweeps/{sweep_id}/inventory")
    def inventory_view(sweep_id: str, offset: int = 0, limit: int = 50):
        if offset < 0 or not 1 <= limit <= 100:
            raise HTTPException(422, "Invalid inventory page")
        capture = sessions.snapshot(sweep_id)
        snapshot = inventory.snapshot(sweep_id)
        tracks = {t["id"]: t for t in snapshot["tracks"]}
        observations = {o["id"]: o for o in snapshot["observations"]}
        rows = []
        for book in snapshot["books"]:
            track = tracks[book["id"]]
            rows.append(dict(kind="book", id=book["id"], shelf=book["shelf"], owned=book["owned"],
                title=book["title"], status=book["status"], frame_ref=book["frame_ref"],
                observation_count=len(track["observations"]), reason=("Reviewed edition record; binding claimant-declared" if (track.get("bibliography") or {}).get("accepted_edition_id")
                    else "Reviewed work; owned-copy edition unresolved" if track.get("bibliography") else "Physical track; identification pending")))
        for index, review in enumerate(snapshot["review_queue"]):
            obs = observations.get(review.get("observation_id"))
            rows.append(dict(kind="review", id=review.get("observation_id", f"review-{index}"),
                shelf=obs["shelf_id"] if obs else "", owned=None, title="", status="unresolved",
                frame_ref=review["frame_ref"], observation_count=None, reason=review["reason"]))
        return dict(schema_version="1.0", sweep_id=sweep_id, revision=snapshot["revision"],
            capture_status=capture["status"], provisional=True, coverage_verified=False, total_book_count=None,
            assigned_track_count=snapshot["assigned_track_count"], owned_assigned_track_count=snapshot["owned_assigned_track_count"],
            review_count=len(snapshot["review_queue"]), detection_import_count=len(snapshot["detection_sources"]),
            page_offset=offset, page_limit=limit, total_rows=len(rows), rows=rows[offset:offset+limit])

    @app.get("/api/sweeps/{sweep_id}/inventory/export")
    def inventory_export(sweep_id: str):
        sessions.snapshot(sweep_id)
        return JSONResponse(inventory.snapshot(sweep_id), headers={"Content-Disposition": 'attachment; filename="provisional-inventory.json"'})

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4180)
    parser.add_argument("--origin", action="append")
    parser.add_argument("--synthetic", action="store_true", help="Label all incoming frames synthetic for fixture smoke checks")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not args.origin:
        parser.error("non-loopback bind requires explicit trusted --origin configuration")
    origins = set(args.origin or [f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}"])
    uvicorn.run(create_app(args.store, origins, synthetic=args.synthetic), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
