# Modular implementation and review plan

**M02b is authorized by the user's "next" after M02a's review stop.** M01 contracts/export and M02a storage are implemented. M02b adds the local HTTP server, browser camera capture and bounded queues. Automated and synthetic HTTP/restart smoke passed; real laptop camera access remains unverified because the request stayed pending. M03 onward requires another instruction after review. The user-tested reference baseline is accepted; no further reference tests are required. Each part ends with its actual checks, limitations and a review stop.

## Working agreement

For each module: confirm named scope from the user's instruction; resolve questions that block that module; implement the smallest complete outcome; run meaningful contract/unit checks; run its smoke test on real boundaries where available; update docs and the reuse ledger; show what changed, test evidence, limitations and the artifact; stop. A fixture-only check is labeled as such. If a required real-device/API test cannot run, report it as unverified rather than passed.

If a module is too large to review in one sitting, split it into its numbered subparts. Each subpart is a separate user authorization/review boundary. Fixes remain within the authorized part. No automatic progression, background implementation, dependency installation or real paid sweep is authorized by this document.

## Sequence and dependencies

| Module | Independently reviewable outcome | Dependency | Planning estimate |
| --- | --- | --- | --- |
| M00 | Existing reference live baseline, device/source preflight and frozen ground-truth plan; no new application code | User answers/environment | 1 h |
| M01 | Required packet contracts, unknown semantics, line-derived totals, basic JSON/HTML export | M00, contract decisions | 1.5 h |
| M02 | Durable same-sweep capture evidence and replayable state | M01, device/path decision | 1.5 h |
| M03 | Narrow metric-scale/room feasibility and spine measurement | M02, scale decision | 2 h |
| M04 | Physical spine detection/counting/tracking with live unknown rows | M02; M03 registration where used | 2 h |
| M05 | Spine reading and conservative work/edition identification | M04 | 1.5 h |
| M06 | Live voice guidance, interruptions and corrections on real device | M00, M02, M04/M05 events | 1.5 h |
| M07 | Source-backed book pricing, FX, appraisal and second locale | M01, M05, locale/access decisions | 2 h |
| M08 | Physical non-book inventory and sourced exact/range/appraisal output | M02, M03, M07 adapters | 1.5 h |
| M09 | Complete room/wall/shelving geometry output | M03 successful feasibility, M08 shelving footprints, M04 registration if reused; area conventions | 1.5 h |
| M10 | Finalization barrier, full traceability audit and integrated packet/summary | M01–M09 | 1.5 h |
| M11 | Real evaluation, one measured fix, unedited demo and submission artifacts | M10, independent ground truth | 2 h |

Baseline total: 19.5 engineering hours. It is a budget allocation, not a guarantee. It excludes user physical annotation, review pauses, credential approval, installation delays and native-platform setup. M03 is a stop gate: a geometry path requiring extensive native or reconstruction work may invalidate this budget. The 48-hour start/deadline remains unknown. Keep a scope contingency discussion visible; do not drop a scored requirement silently.

## Module acceptance cards

### M00 — Existing app and prerequisites

Current disposition: user-tested reference baseline accepted. The original preflight checklist below is historical planning, not a prerequisite blocking M01. Actual target capture and measurement validation remain in M02/M03; real source coverage remains in M07.

Outcome: run the existing reference end to end before new app code. Select/verify an appropriate existing or newly authorized dependency environment without touching reference credentials/source. Confirm phone/OS/browser, secure camera access, provider model access, permitted cost, primary/second locale, candidate physical new/used sources and metric hardware/anchor path. Arrange independently collected truth before tuning.

Checks: existing Python/JavaScript reference regressions with versions recorded. Smoke: real microphone, camera, barge-in, evidence capture and downloadable reference packet; record what was observed and what remains unavailable. Prove phone-route HTTP/WebSocket host, client and origin compatibility: the reference rejects non-loopback connections independently of camera HTTPS permissions. Preflight source smoke: at least one real new and used physical-book quote in each intended locale, or an explicitly reported access/coverage failure. No target source code here. Stop for review of the baseline and chosen constraints.

### M01 — Contracts, totals and minimal export

Scope: implement stage/packet models, required keys, explicit unknowns, integrity eligibility, currency arithmetic and review findings. Add a plain report rendered from a packet, independent of live capture. Fixtures stay labeled synthetic.

Meaningful tests: unknown values preserve keys; true zero remains zero; duplicate IDs rejected; identified/appraisal counts reconcile; missing sources/FX/appraisal amounts excluded; range bounds valid; monetary rounding deterministic; report numbers equal JSON; missing measurement yields incomplete shelf run. Smoke: export a synthetic mixed-status packet and open JSON/HTML to inspect unknowns and exclusion coverage. Stop before capture work.

### M02 — Capture and evidence

M02a: save one actual high-resolution frame with ID, metadata/hash and manifest; reopen it after backend restart. M02b: continuous camera keyframes, separate preview/upload queues, basic blur/glare signals, ordered UI state and capture start/end. Each subpart is separately reviewable.

M02a implementation record: [durable store and CLI](15-m02a-review.md). Synthetic separate-process restart smoke passed; actual original-photo smoke remains pending. The file-import CLI is the current boundary; browser transport and a running HTTP backend are M02b work.

M02b implementation record: [browser and HTTP capture](16-m02b-review.md). 61 Python/9 JavaScript tests and synthetic HTTP/server-restart smoke passed. Laptop localhost was selected by the user. Actual camera request timed out pending permission/device response; no real shelf capture pass is claimed. M03 measurement is not implemented.

Tests: decode/size rejection, stable IDs, duplicate upload idempotency, restart persistence, acknowledged frame durability, path safety, queue bounds, reset/reconnect generation. Smoke: a short continuous target-phone capture with a shelf and wall; open saved originals/crops and verify actual resolution/timestamps. Inventory recognition is not included yet.

### M03 — Metric feasibility and spine dimensions

M03a: implement one selected scale adapter and measure a few held-out spine polygons from evidence. Use explicitly developer-annotated polygons as labeled feasibility inputs at this stage, because automatic detection is not implemented until M04; these annotations are not production detections or an end-to-end accuracy claim. M03b: demonstrate connected room geometry/height from that same capture path. This proves feasibility; complete room report remains M09. Never implement all alternative scale paths speculatively.

Tests: known synthetic geometry/transforms, cm/m conversion, reference uncertainty, degenerate homography, off-plane invalidity, missing scale, depth registration/pose validity if used. Smoke: actual same-sweep measurements compared to independent measured spines and room dimensions, with raw evidence and error table. Failure is a review stop with evidence and options, not permission to invent dimensions.

### M04 — Detection, count and physical tracking

M04a: detected polygons and counts on one shelf, including flat/stacked cases. M04b: merge overlapping/revisited views and preserve distinct duplicate copies; publish provisional unknown inventory during capture.

Tests: revisits do not double-count, duplicate titles do not merge, bookend false positives, split/merge ambiguity, ownership exclusion, horizontal orientation and deterministic track IDs. Smoke: two shelves in a continuous pass with a revisit; annotate every physical detection and miss. Compare full counts, precision/recall and merges/splits; report unresolved regions. Do not tune on held-out evaluation truth.

### M05 — OCR and catalogue resolution

M05a: saved-crop visible text extraction; M05b: catalogue candidate/match logic with work/edition distinction and calibrated acceptance policy.

Tests: unreadable/no-title result, ambiguous editions, wrong author/publisher, volume number, unsupported ISBN, multiple languages as applicable, correction invalidation, source provenance. Smoke: mixed legible/unreadable real spines; open crop→observed text→candidate→accepted fields. No pricing in this module.

### M06 — Live sweep agent

Adapt reference transport/playback and replace policy tools with validated sweep commands. Guide quality/coverage, ask the art question, update rows, accept ownership/edition corrections, persist unfinished turns and keep jobs off the audio loop. Provider extension/resumption must support >3-minute audio/video interaction; test explicit end-sweep versus disconnect.

Tests: interruption clears audio; stale connection/job events ignored; ambiguous correction asks for target; completed-call replay idempotent; revisions arriving during sends are processed; provider/media formats valid; pending turn retained on disconnect. Smoke: real phone voice+camera, poor shelf recapture, interruption, duplicate-copy correction, excluded shelf and reconnect. Measure prompt/action delay and verify inventory change timestamps. Retain no avatar/sketch dependency.

### M07 — Book valuation and second country

M07a: one source adapter with literal quote/provenance and replacement/used eligibility. M07b: locality/equivalence/condition rules, appraisal and FX. M07c: same 10 books repriced for the second locale. User reviews each before proceeding.

Tests: source amount absent, wrong format/edition/country/currency, out-of-stock listing, unsupported FX, range/rounding, locale cache isolation, signed/rare revocation, price timeout and no-source exclusions. Smoke: open actual price sources for a small known set; hand-check new and used separately, with dates/condition/fees. Two-country smoke preserves identity and explains every local/converted/unavailable result. Do not expand to all books until source coverage is demonstrated.

### M08 — Non-book contents

M08a: classification/tracking/evidenced materials/model/dimensions. M08b: exact comparable/range adapters and art/unknown price handling after contract decision.

Tests: repeated view dedup, furniture sets/components, hidden depth, unreadable brand, original/unanswered/print gating and valid sourced ranges. Smoke: the actual ≥8-item room list; compare found/correct categories, false positives and each quote basis. Unknown ordinary-item prices follow the approved semantics.

### M09 — Room and shelving areas

Build full footprint/wall/shelf union calculations using M03's proven inputs. Rectangles, nonrectangles and varying heights have explicit interpretations. Add m²/ft² and uncertainty/coverage.

Tests: rectangle, closed polygon, sloped/variable wall treatment, invalid polygon/missing corner, overlap-clipped shelving union, deterministic square-foot conversion and gross/net convention. Smoke: taped real room comparison from the same inventory sweep, plus a changed/held-out geometry case. All inputs trace to frames/calibrations; missing geometry stays unknown.

### M10 — Final packet integration

Add deadline/drain barrier, freeze consistent revision, independent deterministic audit, complete review queue, portable evidence/quote manifest, report and spoken summary from the same JSON. Late jobs cannot mutate completed artifacts.

Tests: correction invalidates pending valuation, export during pending work, deadline partial packet, restart/open references, lost provider, duplicate callback, invalid line excluded, exact JSON/report/summary agreement. Smoke: continuous sweep to exported packet; open every `frame_ref` and check each monetary source. Measure sweep-end→validated JSON/report-ready time; do not declare pass if a partial/invalid file merely appeared.

### M11 — Honest evaluation and delivery

Freeze configuration and truth; run the full actual room. Produce the comparison sheet, individual sample errors, coverage, actual cost/latency, three worst errors and one measured repair. Re-run a fresh held-out sweep after repair. Record an unedited ≤6-minute demo from capture start through the packet. Rehearse setup under 15 minutes; update README/reuse note/model disclosure.

Smoke: full mandatory scenario, same 10 books in second locale, clean setup and opening all deliverables. Every brief pass bar is pass/fail/not-measured with evidence. Nothing is submitted/shared externally until the user asks for that action.

## Per-module review record

At completion record: authorized scope; files/components changed; reused upstream logic; behavior demonstrated; exact checks and actual outcomes; smoke artifact paths; known defects/unverified boundaries; cost incurred; proposed next module. The record ends with **awaiting user review**. A module that misses its acceptance bar is revised on request or explicitly accepted with a documented limitation; never presented as passed.
