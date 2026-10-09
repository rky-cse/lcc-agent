# Requirements and scope

Status: proposed design, 10 October 2026. Source of requirements: [the original brief](00-original-brief.md). The user's current instruction limits work to documentation, architecture and planning. Implementation is prohibited until explicitly requested, and must proceed one small module at a time with user review between modules.

## Outcome and interaction

One claimant, one enclosed room, one continuous pass. The claimant may pause or revisit a specific shelf/corner while the same pass is active. The system must not require individual book photos, ISBN typing, barcode scanning or book removal. Voice must work both ways during capture; corrections must affect the inventory. A video uploaded after capture with retrospective narration does not satisfy the requirement.

At session start confirm country and currency. Explain the sweep in one or two sentences. During capture show provisional inventory rows and request slower movement, a closer view or a short factual clarification when evidence is insufficient. After the sweep, finish outstanding jobs, read a summary and expose the packet within five minutes. Unknowns remain visible and enter review.

## Requirement matrix

| ID | Required behavior | Evidence of completion | Planned modules |
| --- | --- | --- | --- |
| R01 | Live browser/phone audio input/output and camera | Real device test and unedited demo with audible voice | M00, M02, M06 |
| R02 | Detect blur, glare, occlusion and missed coverage in time to recover | Saved quality events tied to frames and in-pass recapture | M02, M04, M06 |
| R03 | Inventory updates during sweep; claimant interrupts/corrects | Timestamped UI events and correction history | M04, M05, M06, M10 |
| R04 | Count upright, flat and stacked physical books | Full shelf inventory; copies are distinct | M04, M11 |
| R05 | Read visible spine title/author/publisher; resolve work/edition only with evidence | OCR/crops, candidate records and field evidence | M05 |
| R06 | Unreadable books retained with dimensions when measurable | Unidentified rows with no invented title | M03, M04, M05 |
| R07 | Spine height/thickness cm and shelf run m; explained metric scale | Calibration and deterministic derivation per dimension | M03, M04 |
| R08 | Local new/equivalent replacement and used values per identified book | Retrievable physical-book source, timestamp, condition, currency | M07 |
| R09 | Converted foreign prices labeled; unavailable prices excluded | FX evidence and component-level exclusion reasons | M01, M07, M10 |
| R10 | Rare/signed/antiquarian/high-value books routed to appraisal | Rules and review entries; no automatic valuation | M05, M07 |
| R11 | Same 10 physical books priced for second country | Two locale runs preserving identity/evidence IDs | M07, M11 |
| R12 | All visible non-book categories, materials, dimensions, legible brands | Physical-item tracks with images and unknown fields | M08 |
| R13 | Local sourced non-book price or sourced range | Matched listings, explicit comparable basis | M07, M08 |
| R14 | Art defaults to appraisal; ask whether original/print | Claimant answer with turn reference and valuation gate | M06, M08 |
| R15 | Room length/width/height, floor/wall/shelved wall area; m² and ft² | Same-sweep geometry, uncertainty and wall/shelf records | M03, M09 |
| R16 | Handle nonrectangular shape explicitly | Polygon/segments and documented dimension convention | M09 |
| R17 | One JSON and readable PDF or HTML per sweep | Export generated from the same frozen packet | M01, M10 |
| R18 | Every doubtful line in review; all figures traceable | Referential checks for frames, calibrations and prices | M01, M10 |
| R19 | Totals computed from lines in code | Deterministic arithmetic and reproducible export | M01, M10 |
| R20 | Independent ground truth before tuning; honest full-run reporting | Frozen truth records, comparison sheet and failures | M00, M11 |
| R21 | Cost per sweep and latency per stage | Actual usage ledger and monotonic timers | All implemented stages, M11 |
| R22 | README runnable in <15 min, .env.example, no secrets | Clean setup rehearsal on target OS | M00, M11 |
| R23 | Read and run reference before new code; document reuse | Reference live baseline record and reuse ledger | M00 |

## Measured pass bars

| Measure | Brief's pass bar |
| --- | --- |
| Physical book count | Relative absolute error ≤5% of true count |
| Title identification | ≥70% of human-legible spines correct; confidently wrong ≤3% |
| Spine dimensions | Within 15% on 20 hand-measured spines |
| Book prices | Within 25% on 15 hand-checked books using the same source type |
| Non-book detection/category | ≥80% of true items found with correct category |
| Floor area | Within 10% of tape ground truth |
| Wall area | Within 15% of tape ground truth |
| End-to-packet latency | <300 seconds after sweep end |

The brief does not define some aggregate/error denominators. [Evaluation](08-evaluation.md) proposes explicit, conservative reporting and records these as open conventions. No current result is claimed.

## Deliverables and responsibility

| Deliverable | Content | Responsibility |
| --- | --- | --- |
| Private repository | Explained code, reproducible setup, model/library disclosure, .env.example | Implementation after authorization; user supplies destination/share instruction |
| Demo | Single unedited take ≤6 min; sweep, voice, live inventory, packet | User performs real physical capture; system supports recording/output |
| Claim artifacts | JSON, readable report and all referenced saved frames from demo | Export module |
| Ground truth/results sheet | ≥60 books, ≥2 shelving units, ≥8 non-books; all legible titles; 20 measured spines; 15 checked prices; tape-measured room | User independently measures physical space; evaluation module compares |
| Architecture note | One-page diagram, model roles, scale, price origins | Current proposed note; finalize after actual implementation |
| Failure log | Three worst actual errors, root causes, measured fix, cost and stage latency | Populate only from observed implementation/run evidence |

Physical room access, permission, tape measurements and an unedited real demo cannot be supplied by a coding agent from this repository. They are dependencies to arrange with the user, not completed tasks.

## Scope boundaries

Build the six scored capabilities. Keep auth systems, insurer policy databases, deployment infrastructure, generated damage sketches, live avatars, fine-tuning and visual polish outside the core. Maintain only basic session isolation, safe output and secret handling needed for a local demo. Stretch goals remain deferred until core requirements work and the user requests them.

The brief's 48-hour wall clock and 15–20-hour work estimate are recorded constraints; their start time and remaining time are unknown. Review pauses consume calendar time. We must clarify the deadline and measurement feasibility before presenting any schedule as achievable.
