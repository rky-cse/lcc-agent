# Ground truth, tests and honest evaluation

Status: evaluation protocol and blank templates only. No capture, measured accuracy, ground-truth sheet or real claim packet has been produced.

## Independent truth before tuning

The user must arrange a permitted enclosed room with at least 60 books, two shelving units and eight non-book items. Before tuning thresholds/models, annotate the complete physical inventory and tape measurements independently of system predictions. Assign stable truth IDs by shelf/row/position, including duplicate copies and horizontal stacks. Store annotation date, annotator, method, units and uncertainty. Record ownership exclusions separately.

For every human-legible spine record visible title/author/publisher, legibility and why any field is not readable. Independent annotations from permitted viewing positions establish legibility before the system run; missed shelves, absent frames or blur in the system's failed capture cannot redefine those spines as human-unreadable or shrink the title denominator. Do not credit the system with metadata only obtained by pulling books out. Establish the exact evaluation legibility rule before running and keep disagreements visible. Book counts include unreadable visible copies. Ground truth does not become a runtime catalogue, price list or room-dimension constant.

Choose 20 spine samples before inspecting prediction errors. Spread them across shelves, heights, thin/thick spines, upright/flat/stacked orientation and lighting; measure height and thickness independently. Choose 15 price-check books before observing model success. Propose checking both replacement and used for all 15, recording missing-market availability rather than selecting only books with easy prices. Confirm sample/aggregation conventions in the decision register.

Tape-measure the footprint, wall segments, ceiling height/profile, openings and shelf front elevations under the same approved area convention. A nonrectangle requires measured segment/polygon geometry. Count/classify every in-scope non-book and define sets/components consistently. An approximate non-book material/model truth is unknown when the human also cannot establish it.

## Dataset separation

Maintain capture calibration/development material separately from the final evaluation run. Freeze truth and config before the final sweep. Keep truth input files outside production lookup paths. Evaluate a changed or held-out shelf/room to check generalization; never tune room outputs to the tape values. Any fix after evaluating a run is disclosed, with a fresh held-out confirmation as well as before/after results on the failed case.

Failure cases remain in every full-run denominator. Do not exclude glare, unreadable spines, missed shelves, missing prices or geometry failures just because a stage did not return a value. Truth annotations may mark human-unreadable spines out of the title denominator, but they remain in physical book count.

## Metrics and proposed pass interpretation

| Measure | Calculation / reporting | Pass bar |
| --- | --- | --- |
| Book count | `abs(predicted_count - true_count)/true_count`; also physical-track precision/recall, missed books, false positives, false merges/splits | ≤5% count error |
| Correct title rate | Correct work-title physical instances / all human-legible physical instances; wrong edition does not count as supported edition | ≥70% |
| Confident wrong | Report both wrong high-confidence identities / all high-confidence identities and / all human-legible instances; confidence threshold frozen before evaluation | ≤3%; primary denominator awaits confirmation |
| Spine height/thickness | For each of 20 samples and each dimension: absolute relative error; missing/nonfinite output is a failed sample. Report within-bar count, mean/median/max | ≤15%; proposed conservative reading: all sampled dimensions within bar, awaiting aggregation confirmation |
| Book price | For 15 prespecified books, each available new/used component's error against same source type, edition/equivalent, condition, locale and fees basis; missing predictions and unavailable truth separately reported | ≤25%; aggregation convention pending |
| Non-books | True items found AND correctly categorized / all ground-truth non-books; also false positives and category confusion | ≥80% |
| Floor area | `abs(predicted_area - taped_area)/taped_area`; unknown output is failure | ≤10% |
| Wall area | Same relative error using approved gross/net convention | ≤15% |
| Packet latency | Monotonic validated JSON+report-ready time minus sweep-ended time; include retrieval, retries and export | <300 seconds |

A count close to truth can conceal offsetting misses and false positives; publish track matching in addition to the required count error. A system that identifies no titles has no confidently wrong output but still fails identification coverage; report empty denominators as undefined, never as perfect accuracy.

Use one-to-one physical matching: shelf/row and evidence position identify truth/prediction pairs, not fuzzy title matching that can map two copies to one. Preserve each unmatched truth/prediction. Publish raw sample rows so an adjuster/reviewer can reproduce aggregates.

## Blank ground-truth sheet specification

The eventual deliverable can be a workbook or documented tabular files. This step only specifies its tables; it does not create synthetic completed truth.

| Table | Columns |
| --- | --- |
| Run metadata | Sweep ID, capture/date/device, frozen config/version, annotator, truth freeze time, area/fees/condition conventions |
| All books | Truth ID, shelf/row/position/orientation, owned, human-legible, visible title/author/publisher/edition evidence, matched predicted ID, predicted fields/confidence/status, correct/wrong/missing, frame/crop |
| Spine sample (20) | Truth ID, measured height/thickness cm, instrument/tolerance, predicted height/thickness, method/calibration, two errors, within15 flags, missing reason |
| Price sample (15 books) | Truth ID, valuation component, source type, physical edition/equivalent, condition, country/currency, hand-checked amount, URL/retrieval time, fees, predicted amount/source/date, error, missing reason |
| Non-books | Truth ID, category/material/model where known, set/component convention, matched predicted ID, found/category correctness, false positives, source frame |
| Room | Shape/vertices/segments/heights/openings/shelf footprints, tape method/tolerance, ground-truth area, prediction, error, calibration |
| Second locale (same10) | Physical ID, unchanged identity, country/currency, new/used quotes/source/date/condition, local/converted/unavailable, FX record |
| Results | Numerator/denominator/error/coverage per pass bar, threshold/config, pass/fail/not-measured and evidence |
| Cost/latency | Stage/job, queued/start/end, usage/unit/rate/date, actual/estimated cost, retry counts, total critical path |

## Test layers

| Layer | What it proves | What it does not prove |
| --- | --- | --- |
| Deterministic unit/contract checks | Nulls, arithmetic, matching policy, geometrical transformations, revision/idempotency, gates | Real-world detector/OCR accuracy or source coverage |
| Adapter fixture tests | Response parsing, malformed data, timeouts/rate limits and rejection rules | Actual provider/model behavior |
| Online source smoke | Real retrieval, country/currency/physical format, literal quote traceability | All-room price accuracy |
| Device smoke | Permissions, legible saved evidence, audible voice, interruption, capture timing, calibration access | Final full-room pass bars |
| Integrated short sweep | Live updates, correction propagation, exports, reference resolution, failure isolation | Full required scenario performance |
| Final real sweep | Whole-run accuracy, cost, latency and deliverables | Generalization unless held-out test also done |

Only add tests that enforce material behavior/integrity, not ones that mirror implementation details or snapshots of visual polish. When relevant tests pass, continue to review; rerun/broaden only for changes, failures or unresolved concerns.

## Failure experiments

Exercise blur/glare, revisit/overlap, horizontal stacks, duplicate titles, hidden corners, no calibration, provider outage, pricing-source outage, slow uploads, signed-book correction, shelf ownership exclusion and disconnect while a correction is being spoken. For each, record actual behavior, expected integrity outcome, affected rows and whether recovery happened inside the continuous pass.

Rank actual errors by impact on count/value/area and claim trust. Select three worst errors after the run. For at least one, identify a root cause, apply a scoped user-authorized fix and measure change, including any regression. "Use a better model" without an observed mechanism/measurement is not a root-cause analysis.

## Result status

| Required measure | Current result |
| --- | --- |
| Count, title, dimensions, prices, non-books, floor/wall areas, time to packet | Not measured: implementation/capture not authorized yet |
| Reference JavaScript regressions | 18 passed |
| Reference avatar-player tests | 7 passed; avatar omitted from target core |
| Reference Python/live smoke | Not verified: backend startup blocked by missing dependencies |

Reference test passes must never be entered as assignment accuracy results.
