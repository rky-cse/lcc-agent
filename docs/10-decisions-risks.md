# Decision register and risks

Status as of 10 October 2026: documentation exists; implementation is unauthorized. A recommendation below is not an assumption about the user's environment or an approved decision. User answers update this register before affected work starts.

## Confirmed constraints

| Decision | Evidence |
| --- | --- |
| Documentation only now | Explicit user instruction |
| Implement one small part, test/smoke test, stop for review | Explicit user instruction; next part needs next instruction |
| Reference source path | Explicit user-provided local path |
| Assignment requirements/pass bars | Attached brief preserved in docs |
| Current workspace has no tracked application files | Initial inspection/git listing |
| Current reference backend is not successfully run by this session | Startup failed: missing uvicorn; JS tests pass separately |

## Blocking questions already sent to user

| ID | Question | Blocks |
| --- | --- | --- |
| D01 | Exact capture phone/device, OS/browser; expected unseen-room device; is native capture acceptable? | M00/M02/M03 runtime/geometry choice |
| D02 | Available LiDAR/depth, visible measured reference object or verified shelf dimensions; may references be placed before pass? | M03 metric path; truthful room measurement promise |
| D03 | Main country/currency and second country/currency | M00 source coverage, M07 pricing |
| D04 | Provider/API access and permitted spend limit | M00 live baseline, model choice, source adapters |
| D05 | Available ≥60-book/2-shelf/8-item enclosed room and person collecting independent truth | M00/M11 full evaluation |
| D06 | Brief received time/deadline and successful prior reference run, if any | Schedule and reference prerequisite |
| D07 | Gross or net wall area; shelving union interpretation; meaning of shelf run | M01/M03/M09 totals/geometry contracts |
| D08 | Appraisal value threshold; tax/delivery policy | M07 published valuation |

These questions are pending, not answered by elapsed time. Work on independent documentation can finish while they remain open. No dependent implementation may silently assume answers.

## Further choices to settle before their module

| ID | Proposed choice / unresolved point | Required resolution |
| --- | --- | --- |
| D09 | Numeric unknown=`null`, strings blank, all keys retained | Confirm contract interpretation in M01 |
| D10 | Ordinary unpriced item: required status blank + extension, or additional enum | Resolve minimal-schema gap in M01; no price invented |
| D11 | `excluded_from_totals` counts distinct lines missing any applicable valuation; component counts added | Confirm semantics in M01 |
| D12 | Nonrectangle length/width are bounding extents; variable height expressed separately | Confirm in M03/M09 |
| D13 | Used condition assumption; active asking-price versus sold-value source basis | Confirm before selecting M07 sources |
| D14 | Price sample: 15 books with both new/used; confident-wrong denominator; per-sample/aggregate pass conventions | Freeze evaluation protocol before tuning |
| D15 | Expected spine/voice languages | Select/test OCR/provider in M05/M06 |
| D16 | Lightweight FastAPI/plain JS, local SQLite/files, bounded async workers; omit ADK core | Architecture recommendation subject to review |
| D17 | HTML readable report first | Brief allows PDF or HTML; proposal avoids unnecessary PDF work; confirm if PDF required |
| D18 | Local retention duration, evidence provider transfer and demo/upload destination | Set before real capture/export/sharing |
| D19 | Catalogue/retailer/search/FX adapters and exact versioned models | Choose after locale/access proof; documentation mentions candidates only |
| D20 | Confidence, quality thresholds, range aggregation and source freshness | Tune only on calibration data; freeze before evaluation |

Some choices can be resolved from the brief itself (for example, HTML is allowed and prices cannot come from memory). Environment facts and business/evaluation conventions cannot. Keep proposals visible until reviewed; do not use the instruction in the brief to "assume and move on" to override the user's "ask if there is confusion."

## Risk register

| Risk | Evidence / impact | Mitigation and stop gate |
| --- | --- | --- |
| RISK01 — Room metric geometry on ordinary phone | RGB with no scale/connected geometry cannot establish room areas; likely largest pass-bar risk | D01/D02 and early M03 actual-device experiment; change path with user review if unsupported |
| RISK02 — Geometry consumes timebox | Native depth or robust reconstruction may exceed 15–20 engineering hours | Prove minimal room/height path early; do not promise budget until measured |
| RISK03 — Thin/stacked spine segmentation | Generic vision models may miss or merge tightly packed physical copies | High-resolution evidence, shelf coordinates, explicit merge/split review and full-count truth |
| RISK04 — Confident wrong title/edition | Catalogue prior can overrule weak visible text, attaching wrong price | OCR/field evidence, reject contradictions, separate work/edition, blanks and fixed confidence policy |
| RISK05 — Physical new/used price coverage | Locale APIs/site access/used copies may be missing; e-books and asking prices differ | Early real source preflight per locale, adapters and typed unavailable outcomes |
| RISK06 — Frame traceability loss | Reference state/evidence in RAM; low-resolution preview only | Durable immutable evidence and restart/open smoke test before model pipeline |
| RISK07 — Duplicate counts / hidden omissions | Shelf revisits and identical titles; aggregate error can cancel | Physical tracks, coverage ledger, precision/recall and merges/splits in evaluation |
| RISK08 — Stale corrections/exports | Async jobs/transport can lose turns or apply older revision | Event persistence, dirty-revision loop, invalidation and freeze barrier |
| RISK09 — Live time/session limits | Default provider session may end during <3-minute sweep | Compression/resumption for chosen provider; >3-minute device smoke; state independent of model |
| RISK10 — Packet versus demo timing | Separate 3-minute/5-minute maxima exceed 6-minute demo | Measure stricter integrated timing; single take with full packet |
| RISK11 — Truth availability | Coding agent cannot measure/capture physical room | Arrange user annotation/permission before tuning; no fabricated truth |
| RISK12 — Review calendar time | Module approvals consume unknown 48-hour window | Clarify received time and reserve review time; estimates explicitly conditional |
| RISK13 — Cost/rate ceilings | Parallel vision/lookup may exceed spend/quota or delay finalization | Actual usage ledger, bounded work, source rate limits, user-set cap |
| RISK14 — Contract ambiguity | Nulls, unpriced-item status, shelf run and area convention undefined | Explicit D07/D09–D14 decision before those modules |

## Deferred work

Authentication platform, insurer databases, hosted deployment, polished visual design, avatars, generated damage illustrations, scratch training, multi-room merging, condition grading, independent model checker, smart glasses and floor-plan sketch are not on the core implementation path. Reconsider only after scored capabilities are measured and the user asks.

## Decision update format

Record ID, exact user answer/approved choice, date, rationale, affected documents/contracts/modules and whether it supersedes an earlier decision. Record measured preflight outcomes independently of user preferences. A failed capability test can invalidate a proposed path even if that path was initially preferred.
