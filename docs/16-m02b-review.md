# M02b — Browser camera capture and upload queues

Status: **implemented; automated/HTTP smoke passed; real camera smoke pending; awaiting review**. Date: 10 October 2026. Authorized by "next" after M02a. The user selected laptop browser on localhost. M03 has not started.

## Outcome and files

`server.py` exposes a one-worker FastAPI capture API and serves `web/index.html`, `style.css`, `app.mjs`, `queue.mjs`. `capture_session.py` persists sweep lifecycle and basic quality hints in M02a's SQLite store. The UI asks for explicit country/currency, requests video only, captures at the actual stream dimensions, shows durable saved-frame acknowledgements and links to exact evidence plus manifest. There is no live voice, recognition, calibration or valuation in this part.

Dependencies add pinned FastAPI 0.141.1 and Uvicorn 0.54.0 already present in the isolated environment. HTTPX 0.28.1 is in `requirements-dev.txt` for tests/smoke only. Web assets are included in package data. No provider credentials, SDK calls or paid services are used.

## Implemented behavior

Camera requests prefer 1920 × 1080 and rear-facing when available; the actual negotiated dimensions are checked against M02a's minimum. No upscale is used. Each selection draws native video pixels into a canvas and encodes JPEG at quality .92; these are the original uploaded keyframe bytes, not a raw sensor image or an untouched phone JPEG. A separate 320-pixel JPEG preview slot (.6 quality) replaces only preview data. Actual media frame timestamps/intrinsics/video recording are not provided; timestamps are browser wall-clock selection times with independent backend receipt times.

Default sample interval is 1.5 seconds. Evidence FIFO allows 4 blobs / 24 MiB including the upload in progress, with one client upload at a time. Queue overflow rejects the new selection and counts a capture gap. Failed/timeout uploads pause and retain the exact blob, ID and metadata for manual retry. The camera/preview stay independent of a blocked upload. Requests have bounded timeouts; a pending permission request returns control after 20 seconds. A late/cancelled stream releases all tracks. Unexpected camera end or hiding the page pauses capture and records a gap; resume is explicit.

Pause stops camera tracks and retains queued work. End waits for any encoding and drains uploads before posting the end command. A paused queue prevents a false end success. The user may explicitly discard unresolved queued frames and end with gap accounting; committed frames found in the server snapshot are preserved/count as saved. This is not M10 final packet freezing or a promise that a three-minute sweep covers the whole room.

Start IDs, upload IDs and end IDs are replayable. Start replay preserves the sweep and checks locale; frame retries reuse M02a's ID and bytes; duplicate media sequence under a different ID is rejected. Close rejects new frames but permits exact replay of a committed frame when an acknowledgement was lost. End replay must match its original ID/gap count. `transport_complete` means at least one selected frame saved and no reported transport gaps; it does not establish readable books, full room coverage or assignment success.

The browser stores sweep/sequence/pending-ID metadata locally for reload recovery. A server snapshot restores acknowledged frames; vanished, unacknowledged queued/encoding IDs become explicit capture gaps. Blob data are in bounded page memory, not IndexedDB: unsent bytes do not survive page closure. A before-unload warning is best effort. Browser storage being disabled/cleared, multiple tabs writing the same recovery key, camera acquisition races beyond the isolated generation checks, and a full actual-browser disconnect/reload scenario remain device-smoke concerns. Do not claim durable unsent client uploads.

Quality hints use a grayscale thumbnail up to 160 × 160: Laplacian variance below 30 suggests blur; pixels at least 250 comprising over .15 of the thumbnail suggest glare. Thresholds are explicit uncalibrated engineering defaults, not book readability, confidence or an art/material classifier. Hints are persisted separately from immutable originals, and quality failure never revokes a durable frame acknowledgement. No metric dimensions are generated.

## HTTP boundaries

Default bind: 127.0.0.1:4180. Exact Host/Origin configuration gates requests; mutations require an accepted Origin. No wildcard CORS. Control bodies are capped at 4 KiB with 10-second reads. Image bodies are streamed with 32 MiB cap / 20-second read deadline; two simultaneous upload slots bound ingestion, and excess returns 429 for retry. Image/storage work runs in a thread pool. Use one Uvicorn worker; lifecycle locking is per process. Multiple-worker support and authentication/deployment are not implemented.

Original GET verifies saved integrity and returns decoded-content MIME. Manifests include frames, saved quality hints and lifecycle state. No-store/CSP/nosniff headers are set. This is a local development app, not an insurer service or a public deployment. A non-loopback bind requires explicit origins; actual trusted Android HTTPS configuration is not tested. [Camera secure-context requirement](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia) and [FastAPI request stream boundary](https://fastapi.tiangolo.com/reference/request/) informed the adapter.

Server `--synthetic` forces fixture labels and exposes a banner/health flag; it is omitted on the user's laptop-review server. Test locale IN/INR was entered explicitly for UI/fixture checks, never inferred as the user's country and not a production default.

## Checks and observed smoke

**61 Python tests passed**: prior 49 plus 12 server checks for assets/health, Host/Origin/control limits, start replay/conflict, locale/timestamps, durable upload and new-app reopen, persisted hints/original retrieval, upload replay/sequence conflicts, end/new-frame boundary, partial/empty captures, invalid image exclusions, missing IDs, streamed byte limit and synthetic labeling. The existing Starlette TestClient/HTTPX deprecation warning is recorded; tests pass, and no dependency churn was introduced just to silence it.

**9 Node tests passed**: FIFO/count/byte bounds including in-flight memory, overlarge rejection, paused exact-object retry after lost acknowledgement, independent/latest preview, stale generation rejection, explicit discard, camera timeout with late-track cleanup, cancelled-camera cleanup and successful current stream. Node 22.13.0 used. JS syntax checks passed.

Actual HTTP/server-restart smoke (synthetic inputs):

```powershell
.\.local\reference-env\Scripts\python.exe -B scripts/smoke_capture_http.py --output runs/m02b-http-smoke
```

Passed: actual Uvicorn process startup, two 1920 × 1080 JPEG/PNG fixture uploads, durable responses/quality hints, close, process termination/restart with the same store, matching lifecycle/metadata and byte-for-byte originals/hash checks. Artifact: `runs/m02b-http-smoke/http-restart-smoke.json`, store/frames/manifest and server log. All these HTTP fixture images are explicitly synthetic; this is not a camera sweep.

Browser smoke: page/assets rendered in the in-app browser; country/currency controls, camera status and disabled/enabled buttons inspected. An initial request stayed pending indefinitely, exposing missing permission timeout handling; the timeout/late-release helper and three tests were added. With the revised code, the request timed out visibly after 20 seconds, Start was enabled again, and 0 saved frames were shown. Screenshot: `runs/m02b-http-smoke/camera-timeout.jpg`. No camera frame was received; no microphone was requested. Actual shelf/room capture, frame readability, pause/resume/interruption, browser disconnect/reload and changed lighting remain **unverified** until camera permission/device response succeeds. M02a's original-photo smoke also remains pending.

The review server is running at [localhost:4180](http://127.0.0.1:4180/) with store `runs/m02b-laptop`. It is a current development process, not an installed background service. The older reference port 4177 is not used by the target app. The user can allow the local page's camera permission and perform a short sweep; do not report real-device success based on fixture tests.

## Reuse, limits and stop

Reference camera lifecycle/canvas extraction patterns informed the independent implementation; reference preview/downscale/base64 transport does not serve as claim evidence. [Reuse ledger](06-reference-audit.md) records the distinction. Policy/ADK/avatar/sketch dependencies remain omitted. No reference tests, source changes, key reads or model calls ran in M02b.

No packet is finalized, no measurement generated and no accuracy/latency pass bar claimed. Next proposed part after review is M03a, a narrowly selected reference-plane scale/measurement feasibility experiment. It needs actual readable saved evidence and verified reference-object dimensions. **Stopped at M02b; awaiting review and real-camera smoke.**
