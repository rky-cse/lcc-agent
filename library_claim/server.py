"""Local capture/guidance server; optional explicitly enabled Gemini voice."""

import argparse
import asyncio
import sqlite3
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .capture_session import CaptureSessions
from .capture_store import CaptureInput, FrameStore
from .models import Contract
from .tracking import TrackStore
from .guidance import GuidanceStore,GuidanceCommand
from .live_voice import VoiceHub
from .correction_execution import CorrectionExecutor,CorrectionExecution
from .recognition_jobs import RecognitionQueue,ReadingJob,DetectionJob
from .registration_review import RegistrationReviewer,RegistrationReview
from .resolution_review import ResolutionReviewer,ResolutionReview
from .recognition_dispatch import RecognitionDispatcher,DispatchConfig
from .vision_provider import ALLOWED_MODELS
from .sweep_runtime import SweepRuntime,SweepPlan
from .valuation import ValuationStore,ValuationRequest
from .contents import ContentsStore,ContentsCommand
from .contents_pricing import ContentsPricing,ItemValuationRequest


class StartInput(Contract):
    start_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    country: str
    currency: str


class EndInput(Contract):
    end_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    capture_gaps: int = Field(ge=0)


class GuidanceStart(Contract):
    session_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class VoiceDismiss(Contract):
    call_id: str = Field(min_length=1,max_length=128)


class RecognitionCancel(Contract):
    job_id: str = Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')


def create_app(root: Path, origins: set[str], *, synthetic: bool = False, voice_provider=None,recognition_config=None) -> FastAPI:
    if not origins or any(urlsplit(x).scheme not in {"http", "https"} or not urlsplit(x).netloc
                          or urlsplit(x).path for x in origins):
        raise ValueError("configure exact HTTP(S) origins without trailing slash")
    hosts = {urlsplit(x).netloc for x in origins}
    sessions = CaptureSessions(FrameStore(root))
    inventory = TrackStore(sessions.store)
    valuations = ValuationStore(sessions.store)
    contents = ContentsStore(sessions.store)
    contents_prices = ContentsPricing(sessions.store)
    valuation_slot = asyncio.Semaphore(1)
    guidance = GuidanceStore(sessions.store)
    recognition=RecognitionQueue(sessions.store)
    dispatcher=RecognitionDispatcher(recognition,recognition_config,synthetic=synthetic)
    sweep_runtime=SweepRuntime(recognition,dispatcher)
    @asynccontextmanager
    async def lifespan(app):
        try:yield
        finally:
            await sweep_runtime.shutdown()
            await dispatcher.shutdown()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None,lifespan=lifespan)
    app.state.sessions = sessions
    app.state.valuations = valuations
    app.state.contents = contents
    app.state.contents_prices = contents_prices
    app.state.guidance = guidance
    voice = VoiceHub(guidance,voice_provider)
    app.state.voice = voice
    corrections=CorrectionExecutor(guidance)
    app.state.corrections=corrections
    app.state.recognition=recognition
    app.state.dispatcher=dispatcher
    app.state.sweep_runtime=sweep_runtime
    registration=RegistrationReviewer(recognition)
    app.state.registration=registration
    resolution=ResolutionReviewer(guidance)
    app.state.resolution=resolution
    slots = asyncio.Semaphore(2)
    web = Path(__file__).with_name("web")

    async def control_body(request, model, max_bytes=4096):
        data = bytearray()
        try:
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > max_bytes:
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
        ancestors="'self'" if request.url.path in {'/','/voice'} else "'none'"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob:; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors "+ancestors
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

    @app.get('/voice')
    def voice_page():
        return FileResponse(web / 'voice.html')

    @app.get('/recognition')
    def recognition_page():
        return FileResponse(web / 'recognition.html')

    @app.get('/sweep')
    def sweep_page():return FileResponse(web/'sweep.html')

    @app.get('/valuation')
    def valuation_page():return FileResponse(web/'valuation.html')

    @app.get('/contents')
    def contents_page():return FileResponse(web/'contents.html')

    @app.get('/api/sweeps/{sweep_id}/contents')
    def contents_view(sweep_id: str):
        sessions.snapshot(sweep_id)
        return contents.snapshot(sweep_id)

    @app.post('/api/sweeps/{sweep_id}/contents')
    async def contents_command(sweep_id: str,request: Request):
        body=await control_body(request,ContentsCommand,max_bytes=128*1024)
        if body.sweep_id!=sweep_id:raise HTTPException(422,'Contents sweep differs from URL')
        await run_in_threadpool(sessions.snapshot,sweep_id)
        return await run_in_threadpool(contents.apply,body)

    @app.get('/api/sweeps/{sweep_id}/contents/artifacts/{digest}')
    def contents_artifact(sweep_id: str,digest: str):
        sessions.snapshot(sweep_id)
        raw=contents.artifact(digest)
        artifact=json.loads(raw)
        target=artifact.get('request',artifact.get('command',{})).get('sweep_id')
        if target!=sweep_id:raise HTTPException(404,'Artifact is outside this sweep')
        return Response(raw,media_type='application/json')

    @app.post('/api/sweeps/{sweep_id}/contents/valuations')
    async def contents_valuation(sweep_id: str,request: Request):
        body=await control_body(request,ItemValuationRequest,max_bytes=128*1024)
        if body.sweep_id!=sweep_id:raise HTTPException(422,'Contents valuation differs from URL')
        capture=await run_in_threadpool(sessions.snapshot,sweep_id)
        if (body.market.country,body.market.currency)!=(capture['country'],capture['currency']):raise HTTPException(422,'Contents market must match captured country/currency')
        if valuation_slot.locked():raise HTTPException(409,'A valuation is active; retry explicitly after completion')
        async with valuation_slot:return await run_in_threadpool(contents_prices.run,body)

    @app.get('/api/sweeps/{sweep_id}/contents/valuations/{run_id}')
    def contents_valuation_result(sweep_id: str,run_id: str):
        sessions.snapshot(sweep_id)
        return contents_prices.get(run_id,sweep_id)

    @app.get('/api/sweeps/{sweep_id}/contents/valuations/{run_id}/evidence/{digest}')
    def contents_quote_evidence(sweep_id: str,run_id: str,digest: str):
        result=contents_prices.get(run_id,sweep_id)
        if digest not in result.get('evidence_sha256',[]):raise HTTPException(404,'Evidence is outside this run')
        return Response(contents_prices.evidence(digest),media_type='text/plain',headers={'Content-Disposition':'attachment; filename="item-source.txt"'})

    @app.post('/api/sweeps/{sweep_id}/valuations')
    async def valuation_run(sweep_id: str,request: Request):
        body=await control_body(request,ValuationRequest,max_bytes=128*1024)
        if body.sweep_id!=sweep_id:raise HTTPException(422,'Valuation sweep differs from URL')
        capture=await run_in_threadpool(sessions.snapshot,sweep_id)
        if (body.markets[0].country,body.markets[0].currency)!=(capture['country'],capture['currency']):
            raise HTTPException(422,'Primary valuation market must match capture country and currency')
        if valuation_slot.locked():raise HTTPException(409,'A valuation is active; retry explicitly after it completes')
        async with valuation_slot:
            return await run_in_threadpool(valuations.run,body)

    @app.get('/api/sweeps/{sweep_id}/valuations/{run_id}')
    def valuation_result(sweep_id: str,run_id: str):
        sessions.snapshot(sweep_id)
        return valuations.get(run_id,sweep_id)

    @app.get('/api/sweeps/{sweep_id}/valuations/{run_id}/evidence/{digest}')
    def valuation_evidence(sweep_id: str,run_id: str,digest: str):
        result=valuations.get(run_id,sweep_id)
        if digest not in result.get('evidence_sha256',[]):raise HTTPException(404,'Evidence is outside this run')
        return Response(valuations.evidence(digest),media_type='text/plain',
                        headers={'Content-Disposition':'attachment; filename="source-evidence.txt"'})

    @app.get('/api/guidance/{session_id}/sweep')
    def sweep_state(session_id: str):return sweep_runtime.snapshot(session_id)

    @app.post('/api/guidance/{session_id}/sweep/start')
    async def sweep_start(session_id: str,request: Request):
        plan=await control_body(request,SweepPlan)
        return await sweep_runtime.start(session_id,plan)

    @app.post('/api/guidance/{session_id}/sweep/pause')
    async def sweep_pause(session_id: str,request: Request):
        body=await control_body(request,GuidanceStart)
        if body.session_id!=session_id:raise HTTPException(422,'Session differs')
        return await sweep_runtime.pause(session_id)

    @app.post('/api/guidance/{session_id}/sweep/cancel')
    async def sweep_cancel(session_id: str,request: Request):
        body=await control_body(request,GuidanceStart)
        if body.session_id!=session_id:raise HTTPException(422,'Session differs')
        return await sweep_runtime.cancel_pending(session_id)

    @app.get('/api/guidance/{session_id}/recognition')
    def recognition_view(session_id: str, offset: int=0, limit: int=50, frame_offset: int=0, frame_limit: int=50):
        if offset<0 or not 1<=limit<=100 or frame_offset<0 or not 1<=frame_limit<=100:raise HTTPException(422,'Invalid evidence page')
        state=guidance.snapshot(session_id)
        if state['phase']!='capture_bound':raise HTTPException(409,'Bind a capture before enrolling reading jobs')
        snapshot=inventory.snapshot(session_id)
        observations=snapshot['observations']
        frames=sessions.store.manifest(session_id)['frames']
        return dict(session_id=session_id,inventory_revision=snapshot['revision'],reference_revision=state['reference_revision'],
            observations=observations[offset:offset+limit],total_observations=len(observations),offset=offset,limit=limit,
            frames=[{key:frame[key] for key in ('id','sha256','width','height','exif_orientation','synthetic')} for frame in frames[frame_offset:frame_offset+frame_limit]],
            total_frames=len(frames),frame_offset=frame_offset,frame_limit=frame_limit,
            jobs=recognition.list(session_id),worker_mode='explicit_server' if dispatcher.config else 'explicit_cli',inventory_mutated=False)

    @app.get('/api/guidance/{session_id}/recognition/dispatch')
    async def recognition_dispatch_state(session_id: str):
        await run_in_threadpool(guidance.snapshot,session_id)
        states=await run_in_threadpool(recognition.list)
        return dict(dispatcher.snapshot(session_id),worker_busy=any(s['status']=='running' or s.get('worker_active',False) for s in states))

    @app.post('/api/guidance/{session_id}/recognition/dispatch')
    async def recognition_dispatch(session_id: str,request: Request):
        body=await control_body(request,RecognitionCancel)
        result=await dispatcher.dispatch(session_id,body.job_id)
        return JSONResponse(result,status_code=202 if result['accepted'] else 200)

    @app.post('/api/guidance/{session_id}/recognition')
    async def recognition_enqueue(session_id: str, request: Request):
        body=await control_body(request,ReadingJob)
        if body.session_id!=session_id:raise HTTPException(422,'Reading session differs from URL')
        return await run_in_threadpool(recognition.enqueue,body)

    @app.post('/api/guidance/{session_id}/recognition/cancel')
    async def recognition_cancel(session_id: str, request: Request):
        body=await control_body(request,RecognitionCancel)
        job=await run_in_threadpool(recognition.get,body.job_id)
        if job['input']['session_id']!=session_id:raise HTTPException(404,'Unknown job in this session')
        return await run_in_threadpool(recognition.cancel,body.job_id)

    @app.post('/api/guidance/{session_id}/recognition/detection')
    async def detection_enqueue(session_id: str, request: Request):
        body=await control_body(request,DetectionJob)
        if body.session_id!=session_id:raise HTTPException(422,'Detection session differs from URL')
        return await run_in_threadpool(recognition.enqueue,body)

    @app.get('/api/guidance/{session_id}/recognition/{job_id}/{name}')
    def recognition_artifact(session_id: str, job_id: str, name: str):
        if name not in {'reading_result.json','crop.png','detection_result.json','queue_stage.json'}:raise HTTPException(404)
        job=recognition.get(job_id)
        if job['input']['session_id']!=session_id:raise HTTPException(404,'Unknown job in this session')
        if name not in job['artifacts']:raise HTTPException(409,'No published reading artifact')
        # Re-read and compare the returned bytes as well as the full publication manifest.
        from .tracking import digest
        data=(recognition._directory(job_id)/name).read_bytes()
        if digest(data)!=job['artifacts'][name]:raise HTTPException(409,'Reading artifact changed')
        return Response(data,media_type='application/json' if name.endswith('.json') else 'image/png')

    @app.get('/api/guidance/{session_id}/registration/{job_id}')
    def registration_view(session_id: str,job_id: str):
        return registration.snapshot(session_id,job_id)

    @app.post('/api/guidance/{session_id}/registration/{job_id}')
    async def registration_apply(session_id: str,job_id: str,request: Request):
        body=await control_body(request,RegistrationReview,max_bytes=600*1024)
        if body.session_id!=session_id or body.job_id!=job_id:raise HTTPException(422,'Registration target differs from URL')
        return await run_in_threadpool(registration.apply,body)

    @app.get('/api/guidance/{session_id}/resolution/{observation_id}')
    def resolution_view(session_id: str,observation_id: str):
        return resolution.snapshot(session_id,observation_id)

    @app.post('/api/guidance/{session_id}/resolution/{observation_id}')
    async def resolution_apply(session_id: str,observation_id: str,request: Request):
        body=await control_body(request,ResolutionReview,max_bytes=16*1024)
        if body.session_id!=session_id or body.decisions[0].observation_id!=observation_id:
            raise HTTPException(422,'Resolution target differs from URL')
        return await run_in_threadpool(resolution.apply,body)

    @app.get('/resolution')
    def resolution_page():
        return FileResponse(web/'resolution.html')

    @app.websocket('/ws/voice/{session_id}')
    async def voice_socket(socket: WebSocket, session_id: str):
        if socket.headers.get('host') not in hosts or socket.headers.get('origin') not in origins:
            await socket.close(code=1008);return
        await voice.serve(socket,session_id)

    @app.get('/api/guidance/{session_id}/voice')
    def voice_state(session_id: str):
        guidance.snapshot(session_id)
        return voice.journal.snapshot(session_id)

    @app.post('/api/guidance/{session_id}/voice/dismiss')
    async def voice_dismiss(session_id: str, request: Request):
        body=await control_body(request,VoiceDismiss)
        await run_in_threadpool(guidance.snapshot,session_id)
        return await run_in_threadpool(voice.journal.update,session_id,'dismissed',dict(call_id=body.call_id))

    @app.post("/api/guidance")
    async def guidance_start(request: Request):
        body=await control_body(request,GuidanceStart)
        return await run_in_threadpool(guidance.start,body.session_id)

    @app.get("/api/guidance/{session_id}")
    def guidance_view(session_id: str):
        return guidance.snapshot(session_id)

    @app.post("/api/guidance/{session_id}/turns")
    async def guidance_turn(session_id: str, request: Request):
        body=await control_body(request,GuidanceCommand)
        if body.session_id!=session_id: raise HTTPException(422,"Guidance target differs from URL")
        return await run_in_threadpool(guidance.apply,body)

    @app.get('/api/guidance/{session_id}/corrections')
    def correction_receipts(session_id: str):
        return corrections.snapshot(session_id)

    @app.post('/api/guidance/{session_id}/corrections')
    async def correction_execute(session_id: str, request: Request):
        body=await control_body(request,CorrectionExecution)
        if body.session_id!=session_id:raise HTTPException(422,'Correction session differs from URL')
        return await run_in_threadpool(corrections.execute,body)

    @app.get("/assets/{name}")
    def asset(name: str):
        if name not in {"app.mjs", "queue.mjs", "inventory.mjs", "style.css", "voice.mjs", "voice_core.mjs", "pcm-worklet.mjs", "corrections.mjs", "recognition.mjs", "recognition_page.mjs", "shelf_selector.mjs", "registration.mjs", "registration_page.mjs", "resolution.mjs", "resolution_page.mjs", "valuation.mjs", "contents.mjs", "contents_core.mjs"}:
            raise HTTPException(404)
        return FileResponse(web / name, media_type="text/javascript" if name.endswith(".mjs") else "text/css")

    @app.get("/api/health")
    def health():
        return {"module": "M08", "contents": "reviewed_physical_ledger", "valuation": "explicit_source_review", "recognition_worker": "explicit_server" if dispatcher.config else "explicit_cli", "provider_calls": voice_provider is not None or bool(dispatcher.config and dispatcher.config.key), "voice_enabled": voice_provider is not None, "synthetic_capture_mode": synthetic, "limits": sessions.store.limits.model_dump()}

    @app.get('/registration')
    def registration_page():
        return FileResponse(web/'registration.html')

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
    parser.add_argument('--voice',action='store_true',help='Enable Gemini Live; requires explicitly confirmed free-tier access')
    parser.add_argument('--free-tier-confirmed',action='store_true')
    parser.add_argument('--key-file',type=Path,help='Read key locally; never sent to browser')
    recognition_mode=parser.add_mutually_exclusive_group()
    recognition_mode.add_argument('--recognition',action='store_true',help='Enable explicit Gemini recognition dispatch')
    recognition_mode.add_argument('--recognition-replay',type=Path,help='Synthetic-only local reading/detection response JSON mapping')
    parser.add_argument('--recognition-model',choices=ALLOWED_MODELS,default='gemini-3.1-flash-lite')
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not args.origin:
        parser.error("non-loopback bind requires explicit trusted --origin configuration")
    origins = set(args.origin or [f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}"])
    provider=None;recognition_config=None
    if args.recognition and not args.free_tier_confirmed:
        parser.error('recognition requires --free-tier-confirmed; no paid fallback')
    if args.recognition_replay and not args.synthetic:
        parser.error('recognition replay requires --synthetic')
    if args.recognition:
        from .vision_provider import read_key
        recognition_config=DispatchConfig(key=read_key(args.key_file),free_tier_confirmed=True,model=args.recognition_model)
    elif args.recognition_replay:
        if args.recognition_replay.stat().st_size>2*1024*1024:parser.error('recognition replay exceeds 2 MiB')
        recognition_config=DispatchConfig(replay=json.loads(args.recognition_replay.read_text(encoding='utf-8')))
    if args.voice:
        if not args.free_tier_confirmed: parser.error('voice requires --free-tier-confirmed; no paid fallback')
        from .live_voice import GeminiLive
        from .vision_provider import read_key
        provider=GeminiLive(read_key(args.key_file))
    uvicorn.run(create_app(args.store, origins, synthetic=args.synthetic,voice_provider=provider,recognition_config=recognition_config), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
