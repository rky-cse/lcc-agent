# Reference app audit and reuse ledger

Inspected on 10 October 2026. Reference root: `E:\awesome_llm_apps\awesome-llm-apps\voice_ai_agents\insurance_claim_live_agent_team`. Parent repository revision: `4bf51ab704fb2c5b3803cd5191b30d7dcdb51dc2`. No reference files were modified or copied into application code. `.env` credentials were not inspected.

## What the reference actually supplies

FastAPI backend, browser camera/microphone transport, Gemini live conversation, transcripts, nonblocking tools, notebook updates and ZIP export. Its ADK graph normalizes insurance narratives, applies policy/intake rules and produces an adjuster handoff. It does not implement book detection/counting, spine measurement, room geometry, catalogue matching, local price retrieval or the assignment's packet contract.

The audit distinguishes observed source behavior from executed results. Source analysis below identifies design limitations; it is not a claim that every race was reproduced at runtime.

## Initial documentation-stage execution record

The following table preserves the initial results. After the user's "next" instruction, M00 installed an isolated environment, passed 55 Python tests and dependency checks, and passed startup/HTTP/session/empty-packet smoke checks. Real voice/camera/provider behavior remains pending. [Current M00 verification](13-m00-preflight.md).

| Check | Actual outcome |
| --- | --- |
| `node tests/client-regressions.cjs` from reference tests | Passed: 18 mocked client regression tests |
| `node tests/avatar-player.cjs` | Passed: 7 mocked avatar-player tests |
| Python dependency discovery | Active Python 3.13.1 has no FastAPI, uvicorn, Pydantic, Google package namespace or HTTPX |
| `python -B -m uvicorn live_demo.server:app --host 127.0.0.1 --port 4177` | Failed before server startup: `No module named uvicorn` |
| Supplied virtual environment | `venv/pyvenv.cfg` points to `/usr/bin/python3.12`, Linux version 3.12.3; no Windows `venv/Scripts` |
| Python regression suite | Not run: dependency environment unavailable |
| Browser + microphone + camera + live provider | Not run; no successful reference live baseline recorded |

JavaScript tests use controlled browser/device stubs and model fixtures. They do not prove real-device audio, camera readability, provider availability or any assignment accuracy. The failed startup is not a successful reference run. M00 must satisfy the brief's read-and-run prerequisite before new application code. No package installations or paid provider calls were made in this documentation step.

## Keep/adapt/remove

All locations are relative to the reference root and refer to the inspected snapshot.

| Code / location | Decision | Required adaptation |
| --- | --- | --- |
| `live_demo/server.py:836` live WebSocket bridge | Adapt | Extract transport, inventory jobs and persistence into separate components; typed media/tool contracts |
| `server.py:235` turn IDs/dedup | Keep mechanism | Sweep/event sequence and persistence; preserve partial corrections |
| `server.py:552` revision lock/cache | Adapt | Track input/processed revisions separately; drain dirty revisions until current |
| `server.py:866` tracked background tasks | Adapt | Identification, measurement and price workers; bounded concurrency and completed-job ledger |
| `server.py:1088` interruption-first handling | Keep mechanism | Negotiated media formats, cancel playback and reject canceled output |
| `live_demo/app.js:381` shared connect/generation guard | Keep mechanism | Reconnect authoritative sweep snapshot and sequenced events |
| `app.js:562` media cleanup | Keep mechanism | Own camera/mic/worklet/timers; explicit end-sweep distinct from abrupt disconnect |
| `server.py:724` frozen exact frame + independent verification | Adapt | Save all selected evidence durably, pass explicit frame IDs, retain crops/geometry |
| `server.py:711` explicit camera state | Keep mechanism | Camera availability is transport truth, not a claimant statement |
| `server.py:690` packet download | Adapt | Revision barrier, required JSON + HTML and portable evidence manifest |
| `app.js:95` text escaping | Keep mechanism | Escape all source/model/claimant text and unsafe URL output |
| `schemas.py` Pydantic boundaries / `FactSource` idea | Adapt concept | New inventory contracts, field-level visual/catalogue/price/calibration provenance |
| `agent.py` deterministic rule nodes | Adapt pattern | Ordinary testable workers; no need to transplant the full ADK policy graph |
| `policy_directory.py`, `policies.py` insurance rules | Remove from core | Replace with inventory/appraisal/valuation integrity rules |
| `schemas.py` claim types, coverage, fraud/intake routing, USD loss field | Remove from core | Assignment has different entities, currencies and pass bars |
| `live_tools.py` claim instructions/tools | Replace | Short capture guidance, corrections, art question and safe evidence jobs |
| `app.js:54` claim labels / notebook checklist / route stamp | Replace | Physical inventory, shelf/room coverage, stage status, review counts |
| `avatar.js`, avatar auth/transport/tests | Omit from core | Test results recorded as reference baseline only |
| `server.py:757` incident sketches/image generation | Omit from core | Generated illustrations cannot be measurement or photographic evidence |
| `examples.py`, mock policies and sample identities | Omit from runtime | New synthetic fixtures explicitly marked as synthetic |
| Existing CSS/HTML | Reuse minimal layout where useful | Keep functional camera/inventory/voice controls; no visual-polish work |

No source file is approved for blind wholesale copying. At implementation time record copied/adapted functions, upstream path/revision, local destination and why each change was needed. Remove dead imports/helpers after checking callers, not by name alone.

## Limitations to correct

| Source evidence | Implication for target |
| --- | --- |
| `app.js:26`, `623`: 1 FPS, width 512, JPEG quality 0.6; camera ideal 640×480 | Preview may be insufficient for thin spines; test and add independent high-resolution evidence path |
| `server.py:162`, `192`, `633`: session/evidence in RAM; cleanup removes them | Restart/expiry breaks traceability; durable frames/manifest/state required |
| `server.py:600`: 20-photo cap; occasional model-selected pinning | Cannot rely on pinboard for full inventory; evidence selection/retention becomes application-owned |
| `app.js:381`, `server.py:1009`, `1125`: explicit close flush differs from socket disconnect | Partial speech/corrections can be lost; persist partial turns and explicit finalize semantics |
| `server.py:691`, `812`: download reads cached workflow | Packet can be stale; processed revision and finalization barrier required |
| `server.py:895`: coalescing suppresses update while task sends | A newer revision can remain dirty; coordinator loop must recheck after sends |
| `server.py:956`: tool IDs removed after completion | Completed duplicate calls can rerun paid work/save duplicates; completed ledger required |
| `server.py:729`: pins latest frame rather than observation-selected frame | Exact frame verification is useful, but explicit frame/time association is still needed |
| `server.py:730`: timestamp is pin time | Separate exposure/media, received, saved and analysis times |
| `app.js:543`, `623`: sends without bufferedAmount guard | Bound queues, prioritize audio/control and drop only superseded previews |
| `app.js:542`, `635`, `657`: ScriptProcessor/resampler and fixed playback format | Extract/validate audio adapter; worklet proposed; real-device interruption test required |
| `server.py:974`: reconnect seeds transcript | Must restore coverage, exclusions and inventory, independent of conversational context |
| `server.py:673`, `659`: fixed cookie lifetime vs activity TTL | Keep ownership usable over run/export/reconnect; avoid a full auth project |
| `server.py:1055`: JPEG prefix validation | Decode and check byte/dimension limits before accepting evidence |
| `server.py:615`, `838`: HTTP/WebSocket require loopback host AND loopback client plus accepted origin | A phone using the PC LAN address is denied; verify/configure the authorized development route for both transports, independently of HTTPS camera permissions |
| `server.py:624`: API body cap 16 KB; live-message cap 800000 bytes | New high-resolution evidence upload needs its own explicit validated byte/pixel limits and transport; do not carry these caps blindly |
| `agent.py` serialization excluding None | Cannot drop required unknown packet fields |
| Legacy truthiness-to-empty conversion | A real zero must not become unknown; explicit null handling required |

## Tests worth adapting

Port only tests for retained mechanisms: turn identity, speech segmentation, interruption order, reconnect/generation rejection, device cleanup, exact frozen frame, stale frame rejection, explicit camera state, revision rerun, nonblocking media, reset cancellation and exported exact bytes. Remove policy, insurer-routing, damage-sketch and avatar-specific cases from the target's core suite.

Add cases for abrupt disconnect during correction, revision arriving during state send, replayed completed calls, restart then reopening every frame, export with pending stage, slow-network backpressure, shelf revisits, legitimate duplicate copies, unreadable identity, ownership exclusion, missing prices/FX, appraisal revocation and report/JSON arithmetic agreement. Reference fixtures alone do not replace real sweep smoke tests.

## Snapshot fingerprints

| File | SHA-256 |
| --- | --- |
| `live_demo/server.py` | `B82B03A0FF4967AD4790EE5BEB39D4A97872D69214AD21383B26B94EB81CEC1B` |
| `live_demo/app.js` | `78115227D4C6D41D75C85685A334AF6DCB8878AD94DF4797B965D55B9FF46382` |
| `live_demo/live_tools.py` | `4D91CFB81C422193843554F85E919107A563928DA8956AE30E1F1F86DBE94503` |
| `agent.py` | `51E5CEF915D930388E10C6FF9237EA74A450529B169BF45305E4C062D288DD38` |
| `schemas.py` | `B5D0ADE6B0118083026EFBA5A0B6746B5F2F2377AF5E51CB5A94D8BBE9C7D609` |

The parent reference repository contains an Apache-2.0 LICENSE. When adapting source, preserve its license/attribution and modification notices, check any applicable NOTICE and third-party component terms, and disclose used models/libraries. This step did not copy application source or reference credentials.

## M02b reuse update

Read-only inspection of `live_demo/app.js` camera lifecycle and `sendFrame` informed the target's pending-start guard, generation checks, track cleanup and canvas-based frame extraction. The target implements these standard API patterns independently in `web/app.mjs`/`queue.mjs`, with dedicated regression checks. It replaces the reference's 640 × 480 preference/downscaled base64 WebSocket previews with native-stream-resolution JPEG evidence blobs, a bounded HTTP FIFO and an independent 320-pixel latest-preview slot. Preview data cannot replace acknowledged evidence. Policy intake, ADK agents, avatar, audio and sketch code/dependencies were not added to M02b; voice transport remains deferred to M06. Reference files/credentials are unchanged, and no reference tests ran in this part.

## M03a reuse update

The reference provides no validated metric planar adapter. M03a reuses this project's M02a immutable originals/store and M01 evidence/packet/export boundaries; the normalized homography calculation is independently implemented with standard-library math. No upstream source or dependency was copied, no API key was needed and no reference tests were run. Voice/provider reuse remains M06 work.

## M03b1 reuse update

No reference sparse reconstruction code exists to reuse. The target reuses its own immutable evidence, stage/room contracts and serializer, then invokes optional pinned PyCOLMAP/NumPy in an isolated CPU worker. No reference app source/credentials changed or tests ran. Provider/policy/avatar dependencies remain absent from this part; metric anchor/boundary recovery is deferred to M03b2.

## M03b2 reuse update

Reuses target M03b1 native models/poses, M02 originals and M01 dimension evidence/export. Adds fixed-intrinsic support and independently implemented ray/shape/scale calculations. No upstream reference implementation, API key or additional dependency was copied. No reference tests ran; actual-native synthetic room smoke runs only the target.

## M04a reuse update

Reuses target immutable originals, M01 unidentified rows/stages/serializer and M03 polygon helpers. The reference has no validated single-spine detector; a small independent Gemini REST adapter replaces reliance on its aggregate count. No reference code/SDK dependencies were copied or tests run. The reference `.env` key was read privately for target synthetic smoke under the user's earlier authorization, without modifying/copying credentials. All polygons/counts remain provisional pending actual-shelf evaluation.

## M05a reuse update

Reuses target FrameStore, reviewed observations, projective geometry, stage contracts and Gemini transport. Shared structured-image requests preserve M04a behavior. No new reference source/SDK/catalogue dependency copied. Two target synthetic crop calls used the earlier authorized key read locally; reference files/credentials unchanged and no reference tests ran. Visible text remains unverified and cannot establish identity or prices in this module.

## M05b1 reuse update

Reuses target original/observation integrity, M05a crop/span projection, M01 stage contracts and serializer, and the no-redirect HTTP handler. Adds a narrow independent work-search/cache/comparison adapter against official Open Library documentation; no validated reference catalogue implementation was available to reuse. No reference source, credentials or SDK dependencies copied or modified; no reference tests ran. One successful public lookup plus a cache-only process restart used no Gemini key. Work/edition acceptance remains a later review boundary.

## M05b2 reuse update

Reuses target physical inventory transactions/command fingerprints, M05a evidence validation, M05b1 candidate recomputation, Book/StageResult contracts and read-only inventory HTTP projection. Adds explicit bibliographic review and separate visible/asserted metadata rather than adopting reference model-generated identity. No reference code, credentials, network call, SDK or dependency added. Actual synthetic CLI/HTTP/restart/correction smoke runs only the target. Catalogue edition validation remains M05b3.

## M05b3 reuse update

Reuses target work review/visible ISBN archive, physical inventory transactions, stage contracts, provenance/export and bounded catalogue transport/cache. Search/edition adapters share the existing persistent request gate rather than adding a separate rate limiter. Adds narrowly validated edition records, comparison and explicit review; no reference edition logic was available to reuse. One successful public edition lookup used no key/image; no reference tests, credential reads, SDK/dependency installs or reference source changes ran. Missing live physical-format data remained unresolved rather than inferred.
