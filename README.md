# Library Contents Claim Agent

**Status: M04a one-shelf spine proposals/count implemented for review. Live Gemini synthetic smoke passed; real-shelf accuracy remains unverified. M04b has not started.**

This project will guide a policyholder through one continuous voice-and-camera sweep of a home library, build a live inventory, and produce an evidence-backed contents claim packet. The brief requires book counting and identification, metric measurements, local book and non-book valuations, room areas, and an honest evaluation against independently collected ground truth.

Implemented modules provide packet/evidence/export, durable browser capture, annotated planar and calibrated room geometry, plus single-shelf model spine proposals with local validation/review. Live voice, cross-view physical tracking, title/edition identification, full room areas and price adapters remain planned. Physical accuracy is not yet validated.

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

## Current verification

Reference inspected at `E:\awesome_llm_apps\awesome-llm-apps\voice_ai_agents\insurance_claim_live_agent_team`, repository revision `4bf51ab704fb2c5b3803cd5191b30d7dcdb51dc2`. On 10 October 2026, its existing JavaScript tests passed: 18 client regressions and 7 avatar-player tests. They use mocks and do not validate real camera, microphone, model access or measurement accuracy.

The user confirmed they tested the reference and instructed us to proceed without further reference testing. That baseline is accepted. Historical checks are recorded in M00; target phone/camera behavior will be verified in the capture module.

M01 verification: 29 unit/contract/export tests pass. The synthetic CLI produces a partial packet with saved evidence and an HTML report from the same serialized values. No real capture or price quote is claimed by that fixture.

Current full Python suite: 147 tests pass. M04a's live Gemini 3.1 Flash-Lite synthetic smoke detects six spine proposals (four upright/two horizontal), excludes a bookend and matches all six truth polygons at IoU ≥ 0.5. Actual shelves remain untested. Earlier synthetic geometry/backend/capture smokes passed. Real photo/camera/calibration and physical accuracy gates remain open; complete areas are M09 work. The unchanged browser module previously passed nine Node tests.

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

## Review workflow

Current step ready for review: [M05b3 owned-copy edition review](docs/27-m05b3-review.md). Bounded edition lookup checks reviewed visible ISBN, work/title, explicit binding and supplied metadata; acceptance/rejection/clear commands persist with provenance. Full suite: 257 Python tests passed. Synthetic CLI/HTTP restart/clear smoke passed. One live record lacked physical format and remained unaccepted; cached replay made zero requests. Run `python -m scripts.smoke_edition --output runs/my-edition-smoke`. Review `runs/m05b3-review-final/accepted-evidence/report.html` and `runs/m05b3-review/edition-final-cache/report.html`. Guided session setup is next; real shelf accuracy and live recognition remain pending. Implementation stops here for review.

Previous review step: [M05b2 work identity](docs/26-m05b2-review.md). Explicit work acceptance/rejection/clearing and visible/asserted metadata provenance persist on physical tracks. Its smoke command is `python -m scripts.smoke_identity --output runs/my-identity-smoke`.

Previous catalogue step: [M05b1 work candidates](docs/25-m05b1-review.md). One public lookup preserved ambiguity; persisted cache replay made zero calls. Offline smoke: `python -m scripts.smoke_catalogue --output runs/my-catalogue-smoke`.

Previous reading step: [M05a saved spine reading](docs/24-m05a-review.md). Literal unverified text comes from a traceable crop; inventory identities stay unknown. Offline fixture/replay: `python -m scripts.smoke_reading --output runs/my-reading-smoke`.

Previous step: [M04b3 capture inventory viewer](docs/23-m04b3-review.md). The capture page displays imported tracks/review rows, original evidence and unknown totals, polls revisions independently, and reopens saved sweeps without camera access. Review server used [local synthetic inventory](http://127.0.0.1:4183/), saved sweep ID `cccccccccccccccccccccccccccccccc`. Real camera recognition and automatic landmark acquisition remain pending.

Earlier matching step: [M04b2 assisted registration/matching](docs/22-m04b2-review.md). Run `python -m scripts.smoke_matching --output runs/my-matching-smoke` in the project environment. It proposes conservative revisit links using annotated correspondences; unmatched observations remain unresolved. Automatic landmark detection remains pending; the capture inventory viewer is now implemented in M04b3.

The user controls implementation. [M04b1's physical identity ledger](docs/21-m04b1-review.md) persists reviewed revisits, distinct copies, unresolved identity and ownership corrections. Its offline CLI/restart check is `python -m scripts.smoke_tracking --output runs/my-tracking-smoke`. M04b2's assisted matching core is now implemented as described above; automatic landmark acquisition and capture inventory UI still need further implementation. Actual reference dimensions are collected during calibration, camera-profile acquisition remains to resolve, and physical acceptance requires independent ground truth.

Start review with [the open decisions](docs/10-decisions-risks.md) and [the module plan](docs/07-implementation-plan.md). The largest unresolved technical choice is how the capture device supplies trustworthy metric scale and room geometry.
