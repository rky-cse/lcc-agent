# M02a — Durable single-frame evidence

Status: **storage implementation and synthetic smoke passed; real-photo smoke pending; awaiting review**. Date: 10 October 2026. Authorized by the user's "next" after M01. M02b has not started.

## Implemented scope

`library_claim/capture_store.py` provides validated capture inputs, decoded image metadata, immutable original files and an authoritative SQLite manifest. `library_claim/capture.py` imports one file, reopens a stored frame or exports a per-sweep manifest snapshot. `scripts/smoke_capture.py` drives import/reopen in different Python processes. `tests/test_capture_store.py` adds 20 checks. Requirements add Pillow 12.3.0, pinned to the version installed and exercised with Python 3.13.1; Python 3.12+ remains the declared package requirement, not a claim that each version was tested.

The component is ready for a later HTTP upload adapter; this part has no browser camera UI, server route, live preview, upload queue, blur/glare score, model request, crop extraction or recognition. Country/currency remain M01 sweep settings and future conversation prompts; they are not inferred by image storage.

## Storage and acknowledgment contract

Capture input requires sweep ID, upload ID, media sequence, caller-supplied timezone-aware capture timestamp, source and a synthetic flag. Sweep/upload IDs are bounded ASCII tokens. Frame ID is derived deterministically from the sweep/upload pair, not image content: retries keep one ID; distinct captures of identical pixels keep separate IDs. Actual capture time is never inferred from import time or filesystem modification time. Received time is independently recorded in UTC. EXIF capture time/GPS/device data are not used as assertions; original bytes retain their original embedded metadata locally.

Only single-frame JPEG/PNG data are accepted. Decode selects those formats, checks dimensions, verifies the image and reopens for full pixel loading. Filename extensions are not trusted. Default engineering limits: 32 MiB encoded, 40 million pixels, shortest edge at least 720 px and longest at least 1280 px. These limits are configurable through `StorageLimits`, not accuracy guarantees; low-resolution evidence is rejected rather than upscaled. Format/pixel-limit checks follow the [Pillow image API](https://pillow.readthedocs.io/en/stable/reference/Image.html) and [security guidance](https://pillow.readthedocs.io/en/stable/handbook/security.html).

The original is preserved exactly without resizing, rotation or JPEG recompression. Encoded width/height and EXIF orientation are recorded; display dimensions swap for orientations 5–8. A missing orientation remains null. Any future crop/measurement coordinates must specify encoded-versus-oriented space and use the recorded transform.

Saved metadata contains ID/path, SHA-256, byte size, dimensions/display dimensions, MIME, orientation, capture/receipt timestamps and input identifiers. `StoredFrame.packet_evidence()` produces the M01-compatible frame manifest entry without discarding the richer stored capture record.

Writes acquire an SQLite immediate transaction, flush/fsync a temporary original, atomically rename it, then insert metadata and commit with SQLite FULL synchronization. Return occurs only after commit. A crash between file rename and metadata commit may leave an unacknowledged orphan; an identical retry verifies/reuses it. Conflicting original data are never silently replaced. Committed retries compare both bytes/hash and capture metadata, then recheck the saved original. Storage failures return an error; no record is acknowledged. Concurrent identical retries commit one record.

Reads validate expected ID/path, hash, byte size and decoded metadata. Missing or tampered evidence produces an error rather than a success. Paths are resolved within the store root; external symlink/junction escapes are rejected by the same containment check. Original files are immutable through this API; manual file/database edits are unsupported and detected where integrity checks apply.

SQLite `manifest.sqlite3` is authoritative. JSON snapshots are per-sweep inspection/export caches and can lag newer writes; they are not the final frozen claim manifest. Live backup must use SQLite's backup facilities or close writers before copying the database/WAL. Process-restart persistence is verified; sudden hardware failure, filesystem corruption, storage-device flush guarantees and automatic orphan garbage collection are not tested. Final packet freezing/recovery is M10 work.

## Verification and smoke

Full suite: **49 passed** (29 M01 + 20 M02a). New checks cover original-byte preservation, JPEG/PNG decoding, EXIF orientation, invalid/truncated/undersized/wrong-format/animated input, byte/pixel/bomb limits, retry conflicts, distinct captures, sweep isolation, ordered snapshots, missing/tampered data, corrupted dimensions, file/flush/database failures, orphan recovery, concurrent writers, timezone/path-input validation, separate-process CLI reopen and M01 integration.

The first run exposed two test-side SQLite connections left open during Windows temporary-directory cleanup. They now close explicitly; all final tests pass. Production store connections also close explicitly.

Synthetic smoke command:

```powershell
.\.local\reference-env\Scripts\python.exe -B scripts/smoke_capture.py --output runs/m02a-synthetic-smoke
```

Passed: a labeled 2048 × 1536 synthetic PNG was imported; that process exited; a different interpreter reopened and decoded it. Metadata/hash matched, and stored bytes exactly matched the original. Artifact: `runs/m02a-synthetic-smoke/reopened-frame.json`; originals and SQLite/JSON manifests are alongside it. This is a storage/restart check, not a real shelf capture or HTTP-server restart.

Real-photo smoke remains pending. The user was asked for the full local path to one original shelf/room JPEG or PNG. Once supplied, use its actual known capture timestamp with timezone, import it, reopen in a new process and inspect the saved original/dimensions/hash. No existing private photo was searched for or used implicitly. This part's real-image acceptance bar is not yet reported as passed.

## Reuse and next boundary

Read-only reference inspection found frame bytes/photos held in session memory and decoded into export ZIPs. That behavior does not supply durable restart storage, decoded metadata or transactional acknowledgment, so M02a adds this narrow component without copying unrelated claim-agent, avatar or sketch code. Reference transport/audio remain planned reuse in M06. No reference source or key was modified; no reference tests or provider calls ran in this part.

Next proposed subpart after review is M02b: browser camera keyframes and bounded upload/preview queues, using this store. Actual device/browser details and secure camera access are resolved there. **Stopped at M02a; awaiting review and real-photo smoke input.**
