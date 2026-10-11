# Library Contents Claim Agent

M11 evaluation and delivery tooling is implemented: frozen independent truth/config, full-denominator scoring, source-audited archive checks, comparison tables and local demo/setup/failure/repair checks. Real-room accuracy, demo, timing/cost and clean setup remain unmeasured. [M11 guide](docs/45-m11-group-review.md) · [Blank inputs](docs/evaluation-templates/) · [Implemented architecture](docs/11-architecture-note.md).

The original plan ends at M11. No planned module is unstarted, but physical acceptance and two documented geometry acquisition gaps remain. [Completion status and remaining work](docs/46-project-completion-status.md).

## Current local setup

Python 3.12+ is required; workspace checks use Python 3.13. Node is needed only for browser regression tests. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
# Optional native reconstruction for room geometry:
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-reconstruction.txt
.\.venv\Scripts\python.exe -B -m library_claim.server --store runs/my-library --port 4186 --voice --recognition --free-tier-confirmed
```

Copy `.env.example` to a local `.env` and fill either `GEMINI_API_KEY` or `GOOGLE_API_KEY` with your confirmed free-tier Gemini key before explicit activation. The server automatically reads a local `.env`; use `--key-file PATH` to override it. Keys stay on the server; no paid fallback or Groq adapter is implemented. Open `http://127.0.0.1:4186/sweep` on the laptop. Enter country/currency and actual reference dimensions, allow camera/microphone, bind capture and approve the shelf plan/budget. `/recognition` provides physical/identity review, `/contents` non-books, `/valuation` reviewed source candidates and `/areas` qualified geometry. End capture, then `/packet` freezes/exports. Exact inputs/operations are in the M06–M10 guides below.

This prototype requires explicit review and geometry annotations. Unattended room sweeps and Android HTTPS access are unverified. Geometry needs independently verified intrinsics/reference scale and observed corners; tape evaluation truth cannot replace runtime inputs. Clean installation under 15 minutes has not been rehearsed. Offline evaluation needs no model key/provider call.

## Models, sources and tools

Configured code: `gemini-3.8-live` for voice; default `gemini-3.1-flash-lite` for saved-frame detection/reading/non-book proposals, with an explicit vision allowlist. These names describe implementation, not guaranteed account availability/quota. Groq is not integrated. Open Library/Google Books supply bibliographic candidates; reviewed retailer JSON-LD offers and saved dated FX supply money. Python/FastAPI/Pydantic/Pillow/NumPy, optional PyCOLMAP and Google GenAI SDK are pinned in requirements. No model was trained/fine-tuned. Codex assisted design, code and automated tests. [Reference kept/changed/removed](docs/06-reference-audit.md).

Older module notes below preserve review history. Current status is M11 software ready for review; required physical evaluation and delivery evidence remain pending.

M10 final packet integration is implemented for review: closed-capture drain/deadline barrier, immutable snapshots, saved-source/FX/total audit and portable JSON/report/evidence/summary ZIP. Open /packet on the local server after restarting it. Packets remain partial because physical coverage and accuracy are unverified. See [M10 group review](docs/44-m10-group-review.md).

M09 room and shelving areas is implemented for review: observed irregular footprints, sloped wall profiles, explicit gross/net interpretation, clipped shelving unions, m²/ft², sensitivity and durable evidence. Open /areas on the local server. Physical accuracy remains unverified; smoke tests were skipped. See [M09 group review](docs/43-m09-group-review.md).

M08 non-book contents is implemented for review: provisional saved-frame detection, reviewed physical objects/sets, evidenced dimensions and literal exact/range/appraisal valuation. Open /contents on the local server. No smoke tests or real-provider/source calls were run. See [M08 group review](docs/42-m08-group-review.md).

M07 book valuation is implemented for review: source-backed physical offers, explicit condition/appraisal policies, dated Decimal FX and independent two-country ten-track results. Open /valuation on the local server. Source coverage and final claim packet integration remain unverified; no smoke tests were run. See [M07 group review](docs/41-m07-group-review.md).

**Status: M11 software group complete for review. Voice/camera, reviewed inventory/valuation/areas, immutable packet and offline evaluation/delivery tools are implemented. Physical evaluation, demo and measured repair remain pending. Smoke tests remain skipped at your request.**

This project will guide a policyholder through one continuous voice-and-camera sweep of a home library, build a live inventory, and produce an evidence-backed contents claim packet. The brief requires book counting and identification, metric measurements, local book and non-book valuations, room areas, and an honest evaluation against independently collected ground truth.

Implemented modules provide packet/evidence/export, durable browser capture, annotated geometry, physical tracking and assisted matching, visible-text extraction, reviewed work/edition identity, guided setup/evidence questions, optional live voice and explicit correction execution. A bounded reading queue is available through explicit browser enrollment and an independent CLI worker; saved-frame detection jobs can be explicitly enrolled by browser shelf-region selection or CLI/API. Explicitly enabled, budgeted recognition coordination is implemented; source-backed book valuation is implemented; reviewed full room areas are implemented; immutable final packet integration is implemented; physical evaluation remains pending. Physical accuracy is not yet validated.

## Read the design

| Document | Purpose |
| --- | --- |
| [Original brief](docs/00-original-brief.md) | Complete supplied requirements, preserved for traceability |
| [Requirements and scope](docs/01-requirements.md) | Pass bars, deliverables, constraints and ownership |
| [Architecture](docs/02-architecture.md) | Pipeline, boundaries, runtime, state and failure handling |
| [Contracts and packet](docs/03-contracts.md) | Stage outputs, required packet fields, provenance and totals |
| [Capture and measurement](docs/04-capture-measurement.md) | One-sweep interaction, scale options, geometry and uncertainty |
| [Identification and valuation](docs/05-identification-valuation.md) | Detection, physical-copy matching, catalogue evidence and price sources |
| [Reference audit](docs/06-reference-audit.md) | Inspected code, reuse decisions and actual execution results |
| [Modular implementation plan](docs/07-implementation-plan.md) | Small work packages with tests, smoke checks and review stops |
| [Evaluation and ground truth](docs/08-evaluation.md) | Sampling, formulas, full denominators and result templates |
| [Operation and delivery](docs/09-operations-delivery.md) | Setup plan, cost/latency, evidence handling and submission checklist |
| [Decisions and risks](docs/10-decisions-risks.md) | Questions awaiting answers, proposed decisions and feasibility risks |
| [One-page architecture note](docs/11-architecture-note.md) | Concise proposed design for the eventual submission |
| [Failure log template](docs/12-failure-log.md) | Actual failures to record after implementation and real capture |
| [M00 preflight results](docs/13-m00-preflight.md) | Isolated reference environment, 55 Python tests, startup/endpoint smoke and remaining live prerequisites |
| [M01 review record](docs/14-m01-review.md) | Implemented boundaries, tests, synthetic smoke and review artifacts |
| [M02a review record](docs/15-m02a-review.md) | Durable original-frame storage, restart checks and pending real-photo smoke |
| [M02b review record](docs/16-m02b-review.md) | Browser capture, bounded queues, HTTP lifecycle/restart and camera smoke limitation |
| [M03a review record](docs/17-m03a-review.md) | Annotated planar calibration, geometry gates, synthetic smoke and physical-test limitation |
| [M03b1 review record](docs/18-m03b1-review.md) | CPU multiview reconstruction, full selected-view connectivity gates and metric-room limitation |
| [M03b2 review record](docs/19-m03b2-review.md) | Fixed camera calibration, reference scaling, observed room corners/height and integrity/export checks |
| [M04a review record](docs/20-m04a-review.md) | Single-shelf polygons/count, live-provider smoke, unknown/review semantics and actual-shelf limitation |
| [M04b–M05 review records](docs/27-m05b3-review.md) | Latest edition-review boundary; links to prior tracking, reading and identity work |
| [M06a review record](docs/28-m06a-review.md) | Locale/reference questions, evidence requests, correction proposals and HTTP/restart verification |
| [M06b review record](docs/29-m06b-review.md) | Optional voice, reviewed spoken answers, interruptions/reconnect, live smoke and device-test limits |
| [M06c1 review record](docs/30-m06c1-review.md) | Reviewed physical-copy corrections, verified receipts, interruption recovery and portable evidence |
| [M06c2a review record](docs/31-m06c2a-review.md) | Durable bounded reading queue, independent worker, revision invalidation and restart |
| [M06c2b review record](docs/32-m06c2b-review.md) | Explicit browser enrollment, queue status/cancellation, artifact review and HTTP/restart smoke |
| [M06c2c review record](docs/33-m06c2c-review.md) | Saved-frame detection queue, explicit shelf regions, revision guards and independent worker |
| [M06c2d review record](docs/34-m06c2d-review.md) | Browser shelf-region selection, original-pixel guards and explicit detection enrollment |
| [M06c2e review record](docs/35-m06c2e-review.md) | Explicit physical-copy registration, atomic dependency guard and verified ledger receipts |
| [M06c2f review record](docs/36-m06c2f-review.md) | One unresolved physical observation, explicit resolution and verified historical receipts |
| [M06c2g1 review record](docs/37-m06c2g1-review.md) | Exact-job CLI dispatch, terminal lookup and retained worker slot |
| [M06c2g2 review record](docs/38-m06c2g2-review.md) | Opt-in HTTP dispatch, managed child lifetime and ownership-checked recovery |
| [M06c2g3 review record](docs/39-m06c2g3-review.md) | Explicit browser Run, scoped readiness, manual completion refresh and restart smoke |
| [M06 complete group review](docs/40-m06-group-review.md) | Continuous recognition, combined voice/camera, progress/quality guidance and shelf/appraisal corrections |
| [M07 complete group review](docs/41-m07-group-review.md) | Retailer evidence, condition/locality/appraisal policies, dated FX and independent ten-track country comparison |
| [M08 complete group review](docs/42-m08-group-review.md) | Non-book physical ledger, provisional detection, grouping, art/dimensions and exact/range source-backed prices |
| [M09 complete group review](docs/43-m09-group-review.md) | Observed room/wall/shelving polygons, explicit interpretations, m²/ft², uncertainty and durable review |
| [M10 complete group review](docs/44-m10-group-review.md) | Consistent freeze, independent price/FX/totals audit, immutable packet/report/summary and portable ZIP |

## Current verification

Reference inspected at `E:\awesome_llm_apps\awesome-llm-apps\voice_ai_agents\insurance_claim_live_agent_team`, repository revision `4bf51ab704fb2c5b3803cd5191b30d7dcdb51dc2`. On 10 October 2026, its existing JavaScript tests passed: 18 client regressions and 7 avatar-player tests. They use mocks and do not validate real camera, microphone, model access or measurement accuracy.

The user confirmed they tested the reference and instructed us to proceed without further reference testing. That baseline is accepted. Historical checks are recorded in M00; target phone/camera behavior will be verified in the capture module.

M01 verification: 29 unit/contract/export tests pass. The synthetic CLI produces a partial packet with saved evidence and an HTML report from the same serialized values. No real capture or price quote is claimed by that fixture.

Latest automated verification: all 577 Python regressions passed, followed by all 28 expanded M11 focused checks after final repair/size refinements. All 68 Node tests passed. No M11 smoke tests or live provider/source calls were run. M06 adds budget/inputs/restart/drain, image correspondence, literal art, atomic shelf ownership and unverified appraisal checks. Further smoke tests are disabled by user instruction. M06c1's synthetic HTTP/restart/CLI/browser smoke verifies reviewed target-only mutation and recovery after an inventory commit lost its acknowledgment. Earlier voice/provider, detection, tracking, reading and identity checks passed their documented boundaries. Actual microphone barge-in, three-minute conversation, real photo/camera/calibration and physical accuracy gates remain open; reviewed areas are implemented in M09; physical room acceptance remains unverified.

## Run the complete M06 group

Start the server with `--voice --recognition --free-tier-confirmed --key-file PATH_TO_LOCAL_ENV`, then open `/sweep`. Complete locale/reference intake, start and bind camera capture, review the shelf region/policy and request budget, then explicitly start recognition. Camera and microphone panels stay on one page. Pause between shelves; End sweep closes camera intake and drains already prepared recognition jobs. Physical/identity review remains explicit. See [complete operation and limitations](docs/40-m06-group-review.md).

## Run M06c2g3

Open `/recognition` with a bound guided session. Inspect configured mode/readiness, then click Run for one saved queued job. Refresh evidence and job status to inspect completion; this clears an unsaved shelf selection. Unknown, disabled or busy status disables Run. See [browser review and smoke](docs/39-m06c2g3-review.md).

## Run M06c2g2

Enable server dispatch explicitly with `--recognition --free-tier-confirmed` and local credentials, or use `--synthetic --recognition-replay PATH` for validated synthetic fixtures. POST only a saved `job_id` to `/api/guidance/{session}/recognition/dispatch`; 202 acknowledges an owned task, not completion. See [worker lifetime and smoke](docs/38-m06c2g2-review.md). Synthetic smoke: `python -B -m scripts.smoke_dispatch_http --output runs/my-http-dispatch`.

## Run M06c2g1

Dispatch exactly one saved recognition job with `python -B -m library_claim.recognition_jobs --store STORE --run-one --job-id ID --response RESPONSE.json`. Kind is inferred; other queued jobs remain untouched. Live mode retains explicit free-tier confirmation and local credentials. See [review and recovery limits](docs/37-m06c2g1-review.md). Synthetic smoke: `python -B -m scripts.smoke_selected_dispatch --output runs/my-selected-dispatch`.

## Run M06c2f

Open an unresolved observation’s Resolve physical observation link from `/recognition`. Compare original evidence, then explicitly choose a new copy or an existing physical copy. Leave without applying when ambiguous. See [review and smoke](docs/36-m06c2f-review.md). Synthetic smoke: `python -B -m scripts.smoke_resolution --output runs/my-resolution-smoke`.

## Run M06c2e

Open a detection’s Review physical registration link from `/recognition`. Compare originals and decide every candidate as new, same physical copy or unresolved with provenance before applying. See [review and smoke](docs/35-m06c2e-review.md). Synthetic smoke: `python -B -m scripts.smoke_registration --output runs/my-registration-smoke`.

## Run M06c2d

Open `/recognition` on the target server and select a saved frame from a bound guided session. Draw or enter the shelf rectangle, provide shelf ID and proposal-review limits, then explicitly queue detection. A separate CLI worker processes it. See [review and browser smoke](docs/34-m06c2d-review.md).

## Run M06c2c

See [detection job contracts and review](docs/33-m06c2c-review.md). Enroll an explicit saved-frame/shelf-region job through CLI/API, then run one worker with `--kind detection`. Synthetic smoke: `python -B -m scripts.smoke_detection_jobs --output runs/my-detection-queue-smoke`. Proposals do not register physical copies automatically.

## Run M06c2b

Start the target server, then open `/recognition`. Use a bound guided session ID to select saved observations and queue readings. The separate CLI worker processes them. See [HTTP contracts and review record](docs/32-m06c2b-review.md). Synthetic smoke: `python -B -m scripts.smoke_recognition_http --output runs/my-browser-reading-smoke`.

## Run M06c2a

See [queue contracts, worker operation and review record](docs/31-m06c2a-review.md). Run the synthetic independent-process smoke with `python -B -m scripts.smoke_recognition_jobs --output runs/my-reading-queue-smoke` in the configured environment. This queues saved observations; it does not start camera inference or accept identity.

## Run M06c1

```powershell
.\.venv\Scripts\python.exe -B scripts/smoke_corrections.py --output runs/my-correction-smoke
```

No provider key is needed. The voice page's Book corrections panel reviews exact physical targets, applies through the existing audited stores and displays verified outcomes. [Review and limits](docs/30-m06c1-review.md) · [Portable synthetic report](runs/m06c1-review-final/portable-review/report.html).

## Run M06b

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
.\.venv\Scripts\python.exe -B -m library_claim.server --store runs/my-live-library --port 4186 --voice --free-tier-confirmed --key-file E:\awesome_llm_apps\awesome-llm-apps\voice_ai_agents\insurance_claim_live_agent_team\.env
```

Open [voice guidance](http://127.0.0.1:4186/voice). The key stays on the server; no paid fallback is configured. Voice is disabled by default. See [review, smoke artifacts and limitations](docs/29-m06b-review.md). The temporary review server uses a fixture provider, not Gemini; use the command above in your chosen environment for actual voice.

## Run M06a

```powershell
.\.venv\Scripts\python.exe -B scripts/smoke_guidance.py --output runs/my-guidance-smoke
```

No provider key is needed. Choose a fresh output directory. See [contracts and limits](docs/28-m06a-review.md), or inspect the existing [synthetic review report](runs/m06a-review/review/report.html) and [HTTP dialogue](runs/m06a-review/dialogue.json). Voice, geometric calibration and correction execution are separate steps.

## Run M04a

```powershell
.\.venv\Scripts\python.exe -B scripts/smoke_detection.py --output runs/my-detection-replay
.\.venv\Scripts\python.exe -B -m library_claim.spine_detection --store runs/my-capture --input shelf.json --output runs/my-shelf-review --gemini --free-tier-confirmed
```

The first command is an offline boundary replay, not model inference. The second sends the saved original to Gemini and requires your explicit shelf/frame/hash/region/policy JSON plus a local `GEMINI_API_KEY`/`GOOGLE_API_KEY` (or `--key-file`). The default model is Gemini 3.1 Flash-Lite; no paid fallback or automatic retry occurs. See [the exact contract and limits](docs/20-m04a-review.md). Counts stay provisional; failures are unknown, and overlaps/unresolved coverage remain reviewable. Keys never enter the browser or review artifacts. Open the output's `report.html` for polygons/reasons. Choose fresh output directories.

## Run M03b2

```powershell
.\.venv\Scripts\python.exe -B scripts/smoke_room.py --output runs/my-room-smoke
.\.venv\Scripts\python.exe -B -m library_claim.room_measurement --store runs/my-capture --reconstruction runs/my-reconstruction --input room.json --output runs/my-room-packet --country IN --currency INR --currency-decimal-places 2 --exclusion-basis missing_any_component
```

Install the optional reconstruction requirements first. The second command needs your calibrated reconstruction, reference/check dimensions and observed corner JSON; see [the exact contract](docs/19-m03b2-review.md). IN/INR are explicit example inputs. An estimated-intrinsic M03b1 model cannot supply metric output. Camera calibration must be independently verified for the device/zoom/resolution; how the app obtains that profile is pending user preference. No model estimate, normal-room assumption or evaluation tape dimensions substitute for the runtime reference. The smoke's calibration/dimensions are synthetic only.

## Run M03b1

```powershell
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-reconstruction.txt
.\.venv\Scripts\python.exe -B scripts/smoke_reconstruction.py --output runs/my-reconstruction-smoke
.\.venv\Scripts\python.exe -B -m library_claim.reconstruction --store runs/my-capture --input reconstruction.json --output runs/my-reconstruction
```

This optional CPU module requires pinned PyCOLMAP/NumPy; the base app does not. Supply 3–12 saved-frame IDs from one sweep, a fixed-camera/zoom assertion and explicit runtime/quality policy. See [the input and review record](docs/18-m03b1-review.md). The example smoke uses only synthetic images. A connected sparse result is in arbitrary units and cannot produce metric room dimensions yet. Choose fresh output directories.

## Run M03a

```powershell
.\.venv\Scripts\python.exe -B scripts/smoke_planar.py --output runs/my-planar-smoke
.\.venv\Scripts\python.exe -B -m library_claim.measurement --store runs/my-capture --input calibration.json --output runs/my-measurement --country IN --currency INR --currency-decimal-places 2 --exclusion-basis missing_any_component
```

The second command requires your saved-frame calibration/annotation JSON, described in [M03a's record](docs/17-m03a-review.md). Country/currency are explicit example inputs. Do not use synthetic reference dimensions for real evidence. The agent will ask for the actual reference object and independently measured dimensions during calibration; that conversational flow is planned for M06. This part supplies the deterministic calculator and review CLI, without an API key or additional dependencies. A saved, labeled example is in `runs/m03a-planar-smoke/input.json`.

## Run M01

Requires Python 3.12+ and the pinned Pydantic dependency. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B -m library_claim --country IN --currency INR --currency-decimal-places 2 --exclusion-basis missing_any_component --shelf-run-basis sum_spine_thickness --output runs/my-m01-review
```

IN/INR are explicit synthetic example inputs, not application defaults. Choose a fresh output directory each time. Open its `report.html`; JSON, frames and quotes remain usable after temporary fixture cleanup. Current workspace checks used `.local/reference-env/Scripts/python.exe`. M01 uses Pydantic; M02a adds pinned Pillow. No API key is needed for either module.

## Run M02b

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
node --test tests/capture_queue.test.mjs
.\.venv\Scripts\python.exe -B scripts/smoke_capture_http.py --output runs/my-http-smoke
.\.venv\Scripts\python.exe -B -m library_claim.server --store runs/my-camera --port 4180
```

Open [the capture page](http://127.0.0.1:4180/), enter country/currency, allow camera access and show a shelf/room briefly. Use Pause to stop the camera while uploads continue; End sweep drains uploads before closing. Network failures retain queued frames and expose Retry uploads. A full queue omits new selections with an explicit gap count. Saved evidence links reopen exact uploaded bytes; the manifest remains available after restart with the same store directory. Restart the server with that directory to recover state.

M02b requires FastAPI/Uvicorn; HTTPX is test/smoke-only. `--synthetic` labels incoming images for fixture tests. Leave it off for real camera use. The default server binds only localhost and runs one worker. Actual Android trusted-HTTPS access is a future device check; no phone access was tested. No Gemini/Groq key is needed in M02b.

## Run M02a

Install the updated `requirements.txt` in your environment. Run the synthetic restart check:

```powershell
.\.venv\Scripts\python.exe -B scripts/smoke_capture.py --output runs/my-m02a-smoke
```

For a real original JPEG/PNG, use the import CLI with your file, sweep/upload IDs, media sequence and known capture timestamp (ISO 8601 with timezone):

```powershell
.\.venv\Scripts\python.exe -B -m library_claim.capture --store runs/my-capture ingest --file "C:\path\original.jpg" --sweep-id my-sweep --upload-id original-1 --captured-at "2026-10-10T15:00:00+05:30" --media-sequence 0
.\.venv\Scripts\python.exe -B -m library_claim.capture --store runs/my-capture reopen --frame-id FRAME_ID_FROM_IMPORT
.\.venv\Scripts\python.exe -B -m library_claim.capture --store runs/my-capture manifest --sweep-id my-sweep
```

The path and timestamp above are placeholders to replace, not a statement about an actual photo. Reuse an upload ID only for an exact retry; a new physical capture gets a new upload ID. Original bytes remain under `frames/`; SQLite is the authoritative manifest, and per-sweep JSON snapshots are available for inspection. Default acceptance limits and crash boundaries are in the M02a record.

## Historical review workflow

Current step ready for review: [M05b3 owned-copy edition review](docs/27-m05b3-review.md). Bounded edition lookup checks reviewed visible ISBN, work/title, explicit binding and supplied metadata; acceptance/rejection/clear commands persist with provenance. Full suite: 257 Python tests passed. Synthetic CLI/HTTP restart/clear smoke passed. One live record lacked physical format and remained unaccepted; cached replay made zero requests. Run `python -m scripts.smoke_edition --output runs/my-edition-smoke`. Review `runs/m05b3-review-final/accepted-evidence/report.html` and `runs/m05b3-review/edition-final-cache/report.html`. Guided session setup is next; real shelf accuracy and live recognition remain pending. Implementation stops here for review.

Previous review step: [M05b2 work identity](docs/26-m05b2-review.md). Explicit work acceptance/rejection/clearing and visible/asserted metadata provenance persist on physical tracks. Its smoke command is `python -m scripts.smoke_identity --output runs/my-identity-smoke`.

Previous catalogue step: [M05b1 work candidates](docs/25-m05b1-review.md). One public lookup preserved ambiguity; persisted cache replay made zero calls. Offline smoke: `python -m scripts.smoke_catalogue --output runs/my-catalogue-smoke`.

Previous reading step: [M05a saved spine reading](docs/24-m05a-review.md). Literal unverified text comes from a traceable crop; inventory identities stay unknown. Offline fixture/replay: `python -m scripts.smoke_reading --output runs/my-reading-smoke`.

Previous step: [M04b3 capture inventory viewer](docs/23-m04b3-review.md). The capture page displays imported tracks/review rows, original evidence and unknown totals, polls revisions independently, and reopens saved sweeps without camera access. Review server used [local synthetic inventory](http://127.0.0.1:4183/), saved sweep ID `cccccccccccccccccccccccccccccccc`. Real camera recognition and automatic landmark acquisition remain pending.

Earlier matching step: [M04b2 assisted registration/matching](docs/22-m04b2-review.md). Run `python -m scripts.smoke_matching --output runs/my-matching-smoke` in the project environment. It proposes conservative revisit links using annotated correspondences; unmatched observations remain unresolved. Automatic landmark detection remains pending; the capture inventory viewer is now implemented in M04b3.

The user controls implementation. [M04b1's physical identity ledger](docs/21-m04b1-review.md) persists reviewed revisits, distinct copies, unresolved identity and ownership corrections. Its offline CLI/restart check is `python -m scripts.smoke_tracking --output runs/my-tracking-smoke`. M04b2's assisted matching core is now implemented as described above; automatic landmark acquisition and capture inventory UI still need further implementation. Actual reference dimensions are collected during calibration, camera-profile acquisition remains to resolve, and physical acceptance requires independent ground truth.

Start review with [the open decisions](docs/10-decisions-risks.md) and [the module plan](docs/07-implementation-plan.md). The largest unresolved technical choice is how the capture device supplies trustworthy metric scale and room geometry.
