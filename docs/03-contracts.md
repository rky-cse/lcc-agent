# Contracts, evidence and claim packet

Status: M01 implements the packet input models, stage envelope, deterministic totals and minimal export in `library_claim/`. The richer producer contracts below remain the architecture for later modules. See [M01 review](14-m01-review.md) for exact implemented boundaries. Reporting conventions are explicit packet policy inputs; the synthetic example does not select the user's country or production geometry policy.

[M05b2](26-m05b2-review.md) now implements `IdentityCommand`/`MetadataDecision`, reviewed work projection and separate track-level `bibliography.field_provenance`. Work review events carry a typed StageResult and artifact hashes. Book `identified` can have unknown edition/ISBN; assertions remain distinct from visible evidence. Catalogue edition IDs stay null. M01 final-packet assertion provenance integration remains M10; it currently removes text fields lacking saved-frame references.

[M05b3](27-m05b3-review.md) adds `EditionRequest`/`EditionCommand`, bounded edition records and explicit edition acceptance/rejection/clear. Supported edition acceptance can set the track's `accepted_edition_id`; it leaves Book metadata/price fields unchanged and retains binding as a separate claimant declaration. Typed lookup/review stages, source hashes, revision guards and dependency invalidation accompany mutations. Unaccepted/missing/conflicting editions remain unknown.

## Common rules

Every stage returns a typed result with `schema_version`, `sweep_id`, `job_id`, `input_revision`, `stage`, `status`, `started_at`, `finished_at`, `evidence_refs`, `warnings` and `errors`. Terminal stage states are success, partial, unavailable or failed. Each error has a machine-readable code, human reason, retryability and affected entity/field. A failed stage is not an empty success.

Proposed unknown representation: required strings are `""`, required numbers are `null`, required objects remain present with unknown children, and lists are `[]`. Zero is a known measurement or a computed sum, never a placeholder for missing evidence. Boolean `converted=false` means no conversion was performed; an absent amount still needs a valuation status. Do not use `exclude_none=True` on final export.

All metric values must be finite, nonnegative and unit-labeled by schema. Confidence is `[0,1]` or unknown; model self-reported certainty is not a calibrated probability. Store confidence components and acceptance reasons separately. Country/currency are explicit ISO codes; no locale inferred from the laptop timezone. Timestamps use ISO 8601 with offset or UTC; durations use a monotonic clock. Field provenance distinguishes visual observation, claimant assertion, catalogue metadata, source quotation and deterministic derivation.

## Stage outputs

| Contract | Required content | Consumer |
| --- | --- | --- |
| Sweep configuration | Device/browser, country/currency, source policies, scale policy, appraisal threshold, model/adapter versions | Every worker |
| Frame record | Stable frame ID, sweep/media sequence, exposure/media time where available, received time, path, hash, width/height, orientation, camera settings, quality scores | Detection, OCR, geometry, report |
| Crop record | Original frame ID/hash, polygon in original coordinates, pixel transform/rotation, saved crop path | OCR, catalogue resolution, review |
| Calibration record | Method, metric anchor and provenance, units/tolerance, plane or intrinsics/pose, reprojection/fit residual, validity region, version | Measurement |
| Physical detection | Track ID, book/item, shelf/row, orientation, polygon observations, tracking decision, ownership inclusion | Identification, measurement, live UI |
| Identification result | Visible text spans and confidence; candidate catalogue records; accepted work/edition or unresolved reason; evidence per field | Valuation, packet |
| Measurement result | Entity/room reference, metric fields or unknowns, derivation formula, calibration and frame IDs, uncertainty, validity checks | Packet |
| Quote record | Source/provider, URL, retrieval time, readable permitted response/quote excerpt plus hash, literal observed amount/currency, source country, physical format, condition, stock/availability, seller/fees where present | Valuation |
| Valuation result | Entity, replacement/used/range components, selected quote IDs, equivalence rationale, FX reference, rounding and exclusions | Totals, report |
| Correction record | Turn ID, explicit claimant text, target ID(s), field/action, old/new value, assertion status, revision and invalidated dependencies | Coordinator/review |
| Review finding | Stable finding ID, ref ID, reason code/text, affected field, evidence, proposed next action, resolution state | UI/report |
| Frozen packet | Required contract plus evidence/configuration/revision/coverage metadata | JSON, report, summary, evaluation |

Raw model responses may be stored for debugging with secrets removed, but only validated stage results can alter inventory.

## Required output fields

| Object | Required keys | Meaning |
| --- | --- | --- |
| Packet root | `sweep`, `room`, `books`, `items`, `totals`, `review_queue` | All six required top-level objects/collections remain present |
| `sweep` | `id`, `captured_at`, `device`, `duration_s`, `country`, `currency` | One actual capture; captured_at is sweep start, duration is capture start to end |
| `room` | `length_m`, `width_m`, `height_m`, `floor_area_m2`, `wall_area_m2`, `shelved_wall_area_m2`, `scale_method`, `confidence` | Evidenced geometry; unknown fields remain unknown |
| Each `books[]` line | `id`, `shelf`, `position`, `frame_ref`, `status`, `title`, `author`, `edition`, `isbn`, `spine_height_cm`, `spine_thickness_cm`, `id_confidence`, `replacement_cost`, `used_value` | One physical book, not one unique title |
| Book `replacement_cost` | `amount`, `source`, `url`, `retrieved_at`, `converted` | New physical or sourced equivalent cost in sweep currency |
| Book `used_value` | `amount`, `source`, `url`, `retrieved_at`, `condition_assumed` | Supported used-market estimate in sweep currency |
| Each `items[]` line | `id`, `category`, `description`, `brand_model`, `frame_ref`, `dimensions_cm`, `status`, `replacement_cost`, `confidence` | One physical non-book item |
| Item `dimensions_cm` | `w`, `h`, `d` | Measured/estimated with explicit method, or unknown |
| Item `replacement_cost` | `low`, `high`, `source`, `url`, `retrieved_at` | Exact supported amount has low=high; comparable range preserves sources |
| `totals` | `book_count`, `books_identified`, `books_unidentified`, `shelf_run_m`, `books_replacement_cost`, `books_used_value`, `items_replacement_cost_low`, `items_replacement_cost_high`, `excluded_from_totals` | Deterministic aggregation under an approved policy |
| Each `review_queue[]` entry | `ref_id`, `reason` | Every uncertain line/room measure/stage has traceable review reasons |

Book status keeps the supplied values `identified`, `unidentified`, `needs_appraisal`. `identified` means supported work identity; edition/ISBN can still be unknown. Appraisal books retain supported identity and a separate `identification_status` extension. Counts therefore cannot be derived solely from the primary status.

Item status keeps `priced`, `range`, `needs_appraisal`. The brief has no ordinary-unpriced state. Proposed resolution: keep the required status key blank under the brief's empty-field rule, with `valuation_status=unavailable` and an explicit review reason; an alternative is authorizing an `unpriced` enum extension. This is an open decision, not silently finalized. Art defaults to `needs_appraisal` until an explicit print assertion permits comparable pricing.

## Necessary extensions

| Extension | Why it is needed |
| --- | --- |
| `schema_version`, `packet_revision`, `input_revision`, stage terminal states and `packet_status` | Distinguish schema revisions, pending work and final/partial output |
| `evidence_manifest`, `field_provenance`, `calibrations`, `quote_manifest` | Trace every filled field and number to actual inputs |
| `room.floor_area_ft2`, `room.wall_area_ft2`, `room.shelved_wall_area_ft2` | Brief requires square feet but supplied minimal schema only names m² |
| Room footprint, wall polygons, height profile, geometry convention and dimension interpretation | Handle nonrectangle/uneven height without applying rectangle formula incorrectly |
| Per-dimension uncertainty, completeness and measurement method | Missing/weak scale must remain visible |
| `publisher`, visible text, work/edition candidate IDs, `identification_status` | Brief asks for publisher where visible and conditional edition resolution |
| Per-price condition, physical format, quote basis, source country/currency/amount, fees policy, valuation status/reason | Minimal required price objects omit some integrity requirements |
| `used_value.converted`, FX provider/date/rate/source/destination/rounding metadata | Foreign used values need the same disclosure as replacement values |
| Comparable quote IDs for ranges and equivalence rationale | One required URL cannot explain a multisource range |
| Ownership exclusion ledger, missing component counts and valuation coverage | Avoid suggesting partial totals are the value of every item |
| `shelf_run_measured_m`, missing-spine-measurement count, occupied horizontal run and physical shelf length where measured | Separate alternative shelf-run interpretations and partial coverage |
| Cost/usage and latency ledger | Required failure/cost analysis |

The report is rendered from the frozen JSON. It may add formatting and readable explanations but may not independently generate item identities, measurements, valuations or totals. Include evidence thumbnails/links, calibration descriptions, price links/dates/condition and all review reasons.

## Traceability and invariants

Every final inventory line needs a real `frame_ref`: a stable evidence ID resolved by the bundle manifest to a saved image. The report offers a relative portable path and capture timestamp. Extra crop references resolve to an original frame and transform; a timestamp alone is insufficient if no playable saved recording is delivered. Never point at an expiring provider upload or RAM-only data URL.

Every financial component with an amount must have a retrievable source and retrieval date, supported matching basis, condition, currency and eligibility status. The amount must occur in readable captured source evidence or be a deterministic disclosed conversion/aggregation of such amounts; a hash alone is not price evidence. Retain a permitted excerpt with the amount and relevant matching metadata. If auditable quote evidence cannot be obtained, leave the valuation unknown/reviewed. Every dimension links to endpoints/polygon, calibration and computation. Every computed total has eligible line IDs and a rules version.

Validation must reject duplicate physical IDs; invalid/unresolvable paths; values outside constraints; unresolved currencies; contradictory status/amounts; low>high ranges; appraisal amounts; missing source evidence; missing required keys; and revision mismatch. Invalid rows remain in the audit state as reviewed failures and cannot enter eligible totals.

## Totals policy proposal

| Total | Computation and completeness |
| --- | --- |
| `book_count` | Count included physical book tracks; exclude explicitly not-owned entities but retain ownership audit |
| `books_identified` | Count included tracks with supported work identity, including identified appraisal copies |
| `books_unidentified` | Remaining included tracks; assert identified + unidentified = book_count |
| `shelf_run_m` | Proposed sum of all included spine thicknesses /100; if any required thickness is unknown, full total is null and measured subtotal/coverage is reported separately |
| `books_replacement_cost` | Sum eligible replacement components only in sweep currency |
| `books_used_value` | Independently sum eligible used components only in sweep currency |
| Item low/high totals | Independently sum eligible line bounds; exact amounts contribute equally |
| `excluded_from_totals` | Proposed count of distinct included lines missing at least one applicable monetary component, including appraisal/unpriced lines; count each once |

The exclusion definition and shelf-run interpretation require user confirmation. Add explicit component-level priced/unpriced/appraisal counts so the aggregate is understandable. Ownership exclusions are separate. Do not estimate an unidentified book's value, add appraisal indicative quotes, double-count overlapping tracks, or treat replacement+used as a combined claim value.

Money uses Decimal or integer minor units and a documented currency rounding policy. Round component amounts under that policy before summing; preserve original quote values and intermediate FX precision. A zero sum with no eligible lines is shown as "no priced lines" with coverage, not as proof of zero contents value. Count totals are exact integers; dimensions retain an appropriate precision linked to uncertainty.

## Interface proposal

M03a now produces `MeasurementEvidence` for accepted annotated spine dimensions from a verified saved-frame reference. Full typed calibration inputs, diagnostics and structured unavailable errors remain in separate saved measurement JSON files. M01 continues to audit evidence/value agreement; physical geometry validity is the M03a boundary. Bibliographic/price/room unknowns are preserved. See [M03a contract and review](17-m03a-review.md).

Keep backend endpoints small: create/read sweep, upload saved evidence, read state/events, finish capture, obtain packet/report/evidence bundle and explicitly delete local run data. A WebSocket carries audio, conversational preview, turns, validated tool requests and ordered UI events. Evidence bytes should use a separate bounded upload path so they cannot starve audio. These are interface intents; concrete routes and payload schemas are implemented only in their authorized module.

Important planned contract cases: all-unknown packet, partially priced book, identified work with unknown edition, unreadable spine with valid dimensions, signed-book correction, art unanswered/print/original, ordinary unpriced item, mixed currency, missing FX, repeated shelf observation, duplicate callback, stale revision, missing frame, incomplete geometry and stage deadline. Fixtures are explicitly synthetic and never presented as ground-truth results.
