# Modular implementation and review plan

M11 software group is ready for review: frozen truth/config, full-denominator scoring, archive/source audit, second locale and local delivery/failure/repair checks. Physical truth, demo, actual timing/cost, held-out repair and clean setup remain pending. Smoke tests remain skipped. See [M11 guide](45-m11-group-review.md). Earlier module entries preserve their historical review boundaries.

Latest workflow: finish all subparts of the authorized top-level module, then stop for review. Do not run smoke tests from M06 group onward; keep automated verification. M07a–M07c implementation is now covered in [M07 group review](41-m07-group-review.md). Real-source/physical acceptance remains unverified.

**Current review boundary: M11 tooling.** No module after M11 is defined. There are zero unstarted planned modules, while M11 physical acceptance/delivery and the documented M03/M09 calibration/boundary acquisition gaps remain open. See [completion status and next-step choices](46-project-completion-status.md). Smoke tests remain disabled.

## Working agreement

User workflow updated during M06: complete all subparts of the authorized top-level module before stopping for review. Continue targeted automated checks and documentation, but do not run smoke tests. Historical smoke results remain historical; untested real-device/provider/physical gates stay marked unverified. No automatic progression to another top-level module, paid sweep, commit, push or deployment is authorized.

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

M02b implementation record: [browser and HTTP capture](16-m02b-review.md). At that review, 61 Python/9 JavaScript tests and synthetic HTTP/server-restart smoke passed. Laptop localhost was selected by the user. Actual camera request timed out pending permission/device response; no real shelf capture pass is claimed.

Tests: decode/size rejection, stable IDs, duplicate upload idempotency, restart persistence, acknowledged frame durability, path safety, queue bounds, reset/reconnect generation. Smoke: a short continuous target-phone capture with a shelf and wall; open saved originals/crops and verify actual resolution/timestamps. Inventory recognition is not included yet.

### M03 — Metric feasibility and spine dimensions

M03a: [planar spine measurement](17-m03a-review.md). Physical ≤15% accuracy is not measured; agent-led intake is M06. M03b1: [CPU sparse connectivity](18-m03b1-review.md). M03b2: [fixed calibration/reference scale/observed room dimensions](19-m03b2-review.md), implemented with synthetic native smoke. The previous estimated focal length was biased despite low residual, so verified fixed intrinsics are required for metric output. Camera-profile acquisition preference and actual-device validation remain pending. Full room areas stay M09; each subpart stops separately.

M03a: implement one selected scale adapter and measure a few held-out spine polygons from evidence. Use explicitly developer-annotated polygons as labeled feasibility inputs at this stage, because automatic detection is not implemented until M04; these annotations are not production detections or an end-to-end accuracy claim. M03b: demonstrate connected room geometry/height from that same capture path. This proves feasibility; complete room report remains M09. Never implement all alternative scale paths speculatively.

Tests: known synthetic geometry/transforms, cm/m conversion, reference uncertainty, degenerate homography, off-plane invalidity, missing scale, depth registration/pose validity if used. Smoke: actual same-sweep measurements compared to independent measured spines and room dimensions, with raw evidence and error table. Failure is a review stop with evidence and options, not permission to invent dimensions.

### M04 — Detection, count and physical tracking

M04a: [one-shelf proposals and count](20-m04a-review.md), implemented with Gemini 3.1 Flash-Lite and local geometry/overlap validation. One live synthetic image passed; no actual-shelf accuracy claim. Counts/coverage remain provisional; per-frame observations are not physical tracks. M04b1: [reviewed association ledger](21-m04b1-review.md), implemented with offline CLI/restart smoke. M04b2 automatic registration/matching and M04b3 capture inventory UI remain separate review steps. Per-frame counts must never be summed into sweep inventory.

M04a: detected polygons and counts on one shelf, including flat/stacked cases. M04b: merge overlapping/revisited views and preserve distinct duplicate copies; publish provisional unknown inventory during capture.

M04b3: [capture inventory viewer](23-m04b3-review.md), implemented with read-only paginated HTTP projection, independent revision polling, saved-sweep reopening and provisional full-ledger export. Synthetic HTTP/restart and actual browser update/disconnect/recovery checks passed. Camera recognition scheduling, automatic landmark acquisition and real physical-sweep acceptance remain outstanding.

M04b2 proposal core: [assisted registration and conservative matching](22-m04b2-review.md), implemented with a perspective-warped synthetic smoke. It validates annotated correspondences and proposes one-to-one spatial/appearance links without mutation or automatic new tracks. Automatic landmark acquisition remains a separate follow-up; M04b3 viewer is implemented above. This does not meet the real continuous-sweep acceptance bar yet.

Tests: revisits do not double-count, duplicate titles do not merge, bookend false positives, split/merge ambiguity, ownership exclusion, horizontal orientation and deterministic track IDs. Smoke: two shelves in a continuous pass with a revisit; annotate every physical detection and miss. Compare full counts, precision/recall and merges/splits; report unresolved regions. Do not tune on held-out evaluation truth.

### M05 — OCR and catalogue resolution

M05a: saved-crop visible text extraction; M05b1: catalogue candidate retrieval/evaluation; M05b2: explicit reviewed work acceptance/rejection/clear and separately sourced edition metadata; M05b3: catalogue edition-record matching and acceptance against owned-copy evidence. The edition portion is split for a separate review boundary. Calibrated acceptance policy requires real evaluation data and is not claimed by literal candidate comparisons or human review.

M05a: [traceable crop and literal visible text](24-m05a-review.md), implemented with unverified regions/role labels and explicit unknown identity. Two live synthetic calls passed; original/ledger integrity and shared provider regressions passed. No catalogue or identity/price mutation; actual shelf reading accuracy remains unmeasured.

M05b1: [evidence-bound work candidates](25-m05b1-review.md), implemented with pinned reading/crop integrity, exact-literal contradiction gates, ambiguity/completeness reporting and persistent bounded lookup/cache. One public lookup retained two matching works and rejected three different titles; cache restart made no HTTP request. This candidate-export stage does not accept work/edition/ISBN, calibrated confidence or ledger mutation. Explicit work acceptance follows in M05b2 below.

M05b2: [reviewed work identity](26-m05b2-review.md), implemented with physical-track/source guards, explicit literal confirmation, visible/asserted metadata provenance, durable artifacts and atomic corrections. Actual synthetic CLI/HTTP restart/correction smoke passed. This work-review stage does not choose a catalogue edition, calibrated confidence or pricing; explicit edition review follows below.

M05b3: [owned-copy edition review](27-m05b3-review.md), implemented with bounded record retrieval, shared cache/gate, archived visible ISBN, work/title/binding/metadata gates and explicit acceptance/rejection/clear. Synthetic CLI/HTTP restart/clear passed; a live missing-format record remained unaccepted. No price, printing/signature authentication or unseen metadata inferred. Full M05 real-shelf acceptance and held-out identity precision remain unverified.

Tests: unreadable/no-title result, ambiguous editions, wrong author/publisher, volume number, unsupported ISBN, multiple languages as applicable, correction invalidation, source provenance. Smoke: mixed legible/unreadable real spines; open crop→observed text→candidate→accepted fields. No pricing in this module.

### M06 — Live sweep agent

M06a: [guided conversation/session state](28-m06a-review.md), implemented with typed country/currency and reference declarations, same-pass ISBN/binding questions and correction proposals. Reference geometry and command execution are not implied by intake. Synthetic HTTP/restart/CLI smoke passed; actual speech/device checks remain pending.

M06b: [provider voice/media transport](29-m06b-review.md), implemented with reviewed spoken-answer proposals, AudioWorklet/PCM, playback interruption, explicit reconnect and durable journal. Controlled interruption/restart and short real provider resumption passed; actual microphone, Android and three-minute acceptance remain open validation items. Preview is manually selected saved evidence; automatic video scheduling is not implemented.

M06c is split into separate review boundaries. M06c1: [audited correction execution/acknowledgment](30-m06c1-review.md), implemented with explicit physical review, durable prepared requests, exact retry and verified receipts. It schedules no recognition, metric or valuation jobs.

M06c2a: [durable reading queue](31-m06c2a-review.md), implemented with explicit pinned observations, independent CLI workers, bounded claims and reviewable hash-verified results. Synthetic process/restart smoke passed. M06c2b: [explicit HTTP/browser queue enrollment and review](32-m06c2b-review.md), implemented with saved physical evidence, current pins, cancellation and published artifact links; HTTP/restart/browser smoke passed. M06c2c: [bounded saved-frame detection jobs](33-m06c2c-review.md), implemented with explicit shelf-region/policy inputs, queue stage revision pins and independent kind-selected workers. HTTP/restart smoke passed without inventory registration. M06c2d: [browser saved-frame region selection and explicit detection enrollment](34-m06c2d-review.md), implemented with original-pixel mapping, decoded-dimension and generation guards; browser/worker/restart smoke passed. M06c2e: [queued-detection physical registration review](35-m06c2e-review.md), implemented with explicit per-candidate decisions, transactional dependency guards and verified ledger receipts; HTTP/restart/browser smoke passed. M06c2f: [reviewed unresolved-observation resolution](36-m06c2f-review.md), implemented with single explicit new/same decisions, archived-evidence verification and audited resolve receipts. M06c2g is split: [M06c2g1 exact-job CLI dispatch](37-m06c2g1-review.md) implements single selected reading/detection attempts and retained cancellation slots. [M06c2g2 opt-in server dispatch](38-m06c2g2-review.md) implements configured local free-tier/replay activation and owned child lifetime with token-guarded recovery. [M06c2g3 browser dispatch/status controls](39-m06c2g3-review.md) implements explicit saved-job Run actions, scoped readiness and manual completion refresh; browser/restart smoke passed. M06c2h read-only progress and M06c3 budgeted automatic scheduling are implemented in the group review. M06d/e adds automatic image correspondence acquisition and saved preview/progress scheduling, while physical identity acceptance remains explicit review. Recognition drain and coverage readiness remain separate from M10 packet closure. Reference/inventory dependency invalidations must be consumed without silent rebasing. The user subsequently authorized completion of the remaining M06 group without subpart stops and disabled further smoke testing; automated checks and the grouped review apply. See [M06 group implementation](40-m06-group-review.md).

Adapt reference transport/playback and replace policy tools with validated sweep commands. Guide quality/coverage, ask the art question, update rows, accept ownership/edition corrections, persist unfinished turns and keep jobs off the audio loop. Provider extension/resumption must support >3-minute audio/video interaction; test explicit end-sweep versus disconnect.

Tests: interruption clears audio; stale connection/job events ignored; ambiguous correction asks for target; completed-call replay idempotent; revisions arriving during sends are processed; provider/media formats valid; pending turn retained on disconnect. Smoke: real phone voice+camera, poor shelf recapture, interruption, duplicate-copy correction, excluded shelf and reconnect. Measure prompt/action delay and verify inventory change timestamps. Retain no avatar/sketch dependency.

### M07 — Book valuation and second country

M07a: one source adapter with literal quote/provenance and replacement/used eligibility. M07b: locality/equivalence/condition rules, appraisal and FX. M07c: same 10 books repriced for the second locale. User reviews the complete M07 group before proceeding. The smoke checklist below is historical acceptance planning, skipped under the current user instruction.

Tests: source amount absent, wrong format/edition/country/currency, out-of-stock listing, unsupported FX, range/rounding, locale cache isolation, signed/rare revocation, price timeout and no-source exclusions. Smoke: open actual price sources for a small known set; hand-check new and used separately, with dates/condition/fees. Two-country smoke preserves identity and explains every local/converted/unavailable result. Do not expand to all books until source coverage is demonstrated.

### M08 — Non-book contents

M08a: classification/tracking/evidenced materials/model/dimensions. M08b: exact comparable/range adapters and art/unknown price handling after contract decision.

Tests: repeated view dedup, furniture sets/components, hidden depth, unreadable brand, original/unanswered/print gating and valid sourced ranges. Smoke: the actual ≥8-item room list; compare found/correct categories, false positives and each quote basis. Unknown ordinary-item prices follow the approved semantics.

### M09 — Room and shelving areas

Implemented as the complete M09 group; see [review and operating guide](43-m09-group-review.md). Reuses M03 calibration, triangulation and native model integrity plus M08 physical shelving identities. Build full footprint/wall/shelf union calculations using M03's proven inputs. Rectangles, nonrectangles and varying heights have explicit interpretations. Add m²/ft² and uncertainty/coverage.

Tests: rectangle, closed polygon, sloped/variable wall treatment, invalid polygon/missing corner, overlap-clipped shelving union, deterministic square-foot conversion and gross/net convention. Smoke: taped real room comparison from the same inventory sweep, plus a changed/held-out geometry case. All inputs trace to frames/calibrations; missing geometry stays unknown.

### M10 — Final packet integration

Implemented as the complete M10 group; see [review and operating guide](44-m10-group-review.md). Add deadline/drain barrier, freeze consistent revision, independent deterministic audit, complete review queue, portable evidence/quote manifest, report and spoken summary from the same JSON. Late jobs cannot mutate completed artifacts.

Tests: correction invalidates pending valuation, export during pending work, deadline partial packet, restart/open references, lost provider, duplicate callback, invalid line excluded, exact JSON/report/summary agreement. Smoke: continuous sweep to exported packet; open every `frame_ref` and check each monetary source. Measure sweep-end→validated JSON/report-ready time; do not declare pass if a partial/invalid file merely appeared.

### M11 — Honest evaluation and delivery

Implemented tooling as the full M11 group. [M11 commands and physical evidence gate](45-m11-group-review.md). The physical experiment and deliverables below remain pending user-arranged evidence. The historical smoke checklist is skipped under the current instruction.

Freeze configuration and truth; run the full actual room. Produce the comparison sheet, individual sample errors, coverage, actual cost/latency, three worst errors and one measured repair. Re-run a fresh held-out sweep after repair. Record an unedited ≤6-minute demo from capture start through the packet. Rehearse setup under 15 minutes; update README/reuse note/model disclosure.

Smoke: full mandatory scenario, same 10 books in second locale, clean setup and opening all deliverables. Every brief pass bar is pass/fail/not-measured with evidence. Nothing is submitted/shared externally until the user asks for that action.

## Per-module review record

At completion record: authorized scope; files/components changed; reused upstream logic; behavior demonstrated; exact checks and actual outcomes; smoke artifact paths; known defects/unverified boundaries; cost incurred; proposed next module. The record ends with **awaiting user review**. A module that misses its acceptance bar is revised on request or explicitly accepted with a documented limitation; never presented as passed.
