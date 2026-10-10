"""Actual HTTP upload + server restart using explicitly synthetic image data."""

import argparse
import hashlib
import io
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise FileExistsError("choose a fresh smoke directory")
    root.mkdir(parents=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    command = [sys.executable, "-B", "-m", "library_claim.server", "--store", str(root / "store"),
               "--port", str(port), "--synthetic"]
    log = (root / "server.log").open("w", encoding="utf-8")
    process = None

    def boot():
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError("smoke server exited; see server.log")
                try:
                    response = httpx.get(origin + "/api/health", timeout=.5)
                    if response.status_code == 200:
                        return child
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            raise RuntimeError("server startup timed out")
        except BaseException:
            child.terminate(); child.wait(timeout=5); raise

    try:
        process = boot()
        with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=30) as client:
            start_body = {"start_id": "b" * 32, "country": "IN", "currency": "INR"}
            response = client.post("/api/sweeps", json=start_body); response.raise_for_status()
            sweep_id = response.json()["id"]
            expected = {}
            for sequence, format in enumerate(["JPEG", "PNG"]):
                image = Image.new("RGB", (1920, 1080), "#e2eaf1")
                ImageDraw.Draw(image).text((40, 40), f"SYNTHETIC HTTP FIXTURE {sequence} - not a camera frame", fill="black")
                sink = io.BytesIO(); image.save(sink, format=format); data = sink.getvalue()
                response = client.post(f"/api/sweeps/{sweep_id}/frames", params={"upload_id": f"fixture-{sequence}",
                    "captured_at": "2026-10-10T00:00:00Z", "media_sequence": sequence}, content=data,
                    headers={"Content-Type": "image/jpeg" if format == "JPEG" else "image/png"})
                response.raise_for_status(); ack = response.json()
                assert ack["durable"] and ack["frame"]["synthetic"]
                expected[ack["frame"]["id"]] = data
            response = client.post(f"/api/sweeps/{sweep_id}/end", json={"end_id": "smoke-end", "capture_gaps": 0})
            response.raise_for_status(); closed = response.json()
            assert closed["status"] == "closed" and closed["transport_complete"]
        process.terminate(); process.wait(timeout=5); process = boot()
        with httpx.Client(base_url=origin, timeout=30) as client:
            response = client.get(f"/api/sweeps/{sweep_id}"); response.raise_for_status()
            reopened = response.json(); assert reopened == closed
            for frame in reopened["frames"]:
                response = client.get(f"/api/frames/{frame['id']}"); response.raise_for_status()
                assert response.content == expected[frame["id"]]
                assert hashlib.sha256(response.content).hexdigest() == frame["sha256"]
        artifact = root / "http-restart-smoke.json"
        artifact.write_text(json.dumps({"synthetic": True, "scope": "HTTP lifecycle, not real camera",
                                        "restart_verified": True, "snapshot": reopened}, indent=2) + "\n", encoding="utf-8")
        print(f"Synthetic HTTP restart smoke passed: {artifact}")
    finally:
        if process is not None and process.poll() is None:
            process.terminate(); process.wait(timeout=5)
        log.close()


if __name__ == "__main__":
    main()
