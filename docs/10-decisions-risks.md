# Decision register and risks

Latest review: M10 whole implementation group. Finalization deadlines, saved run selection, aggregation and archive budget are explicit inputs. Completed archives stay immutable; corrections need a new run. Global geometry conventions, real coverage/accuracy and timing remain unverified. M11 evaluation remains pending. See [M10 group review](44-m10-group-review.md).

Latest review: M07 implementation group. Whole-module delivery and no-smoke workflow supersede the earlier per-subpart/smoke instructions below. Required per-run inputs resolve locale, used-price basis/condition, source review, appraisal thresholds, precision, rounding, fees and FX freshness without global assumptions. Strict metadata/source coverage and real valuation acceptance remain unverified. See [M07 group review](41-m07-group-review.md).

**Latest review: M06 group.** User authorized all remaining M06 subparts together and disabled further smoke tests. Automatic registration suggestions remain unaccepted; shelf ownership is reviewed, special-copy claims require appraisal. Combined Android, microphone and live latency behavior remains unverified. M07–M10 still supply valuation, areas and final packet closure. See [group review](40-m06-group-review.md).

**Latest review: M06c2g1.** Cancellation cannot undo a submitted provider request. Active cancelled records retain the dispatch slot across restarts. Recovery requires operator confirmation that the old process has exited; no automatic lease expiry, retry or process-liveness detector is added. Cross-store quota scheduling and live latency remain unverified. See [review record](37-m06c2g1-review.md).

**Latest review: M06c2f.** M06c2f resolves exactly one explicit unresolved observation per review. New copies use the existing included ownership default; same-copy links preserve existing ownership/identity. Anonymous reviewer declarations and real physical association accuracy remain limitations. Ambiguity stays unresolved by leaving without applying. See [review record](36-m06c2f-review.md).

Latest authorized boundary: [M06c2e explicit physical registration](35-m06c2e-review.md). Full regression 372 Python/45 Node; synthetic HTTP/restart and isolated browser review passed. Reference/inventory guards run in the import transaction and exact retries recover commit-before-ack failures. Human same-copy review remains uncalibrated; automatic correspondence/capture and real-device accuracy remain pending.

Latest boundary, completed 11 October 2026: [M06c2d browser shelf-region selection](34-m06c2d-review.md). Full suite 359 Python/40 Node passed; browser enrollment, replay worker and completed-result restart passed with zero provider calls. Android/touch, real shelf accuracy and live queue calls remain unmeasured. Physical registration review is proposed next; no automatic progression authorized.

Latest authorized boundary: [M06c2c saved-frame detection queue](33-m06c2c-review.md). 12 new Python checks, one Node check and synthetic HTTP/CLI/restart smoke passed; full suite 356 Python/33 Node. No live provider call or physical count accuracy claimed. Explicit browser region selection is next proposed boundary; automatic registration/capture remain later work.

Latest boundary: [M06c2b browser reading enrollment/review](32-m06c2b-review.md), authorized by “next”. HTTP/CLI/restart/browser smoke passed with zero provider requests; final suite 344 Python/32 Node. An initial voice cleanup race was repaired with explicit storage-thread draining and a regression check. Detection jobs and automatic capture scheduling remain follow-ups; physical accuracy remains unmeasured.

Latest authorized boundary: [M06c2a durable reading queue](31-m06c2a-review.md). 15 new checks and synthetic independent-process smoke passed; full suite 337 Python/27 Node. CLI-only enrollment/worker; HTTP/browser enrollment and detection/automatic camera scheduling remain follow-ups. No live queue/provider or physical reading accuracy claim.

Status as of 10 October 2026: latest "next" authorized M06c1. Reviewed target-only correction execution/acknowledgment passed 22 new Python tests and synthetic HTTP/restart/CLI/browser smoke, including recovery after commit before acknowledgment. Full suite: 322 Python/27 Node tests passed. Recognition scheduling, real microphone/three-minute voice acceptance, physical capture/geometry and camera-profile acquisition preference remain pending. The user-tested reference baseline is accepted without further testing.

## Confirmed constraints

| Decision | Evidence |
| --- | --- |
| Initial step was documentation only; M01 implementation now authorized | Initial instruction followed by explicit request to implement one part at a time |
| Implement one small part, test/smoke test, stop for review | Explicit user instruction; next part needs next instruction |
| Reference source path | Explicit user-provided local path |
| Assignment requirements/pass bars | Attached brief preserved in docs |
| Current workspace has no tracked application files | Initial inspection/git listing |
| Reference automated baseline now runs in isolated Windows environment | M00: 55 Python tests, pip check and startup/HTTP/session/empty-packet smoke passed; actual voice/camera/provider interaction remains pending |
| Target capture is an Android phone or laptop browser; no LiDAR | User selected laptop browser on localhost for the first camera smoke |
| A reference object may establish metric scale; agent asks during calibration | User explicitly allowed this and specified agent-led intake; actual object and verified dimensions are runtime inputs |
| Use free-tier provider access only; Gemini or Groq available as options | User offers free-version keys; no paid-tier use authorized |
| Country/currency must be asked at conversation start | Explicit user clarification; locale remains a per-sweep setting |
| User will arrange the books / physical capture | Explicit user clarification; mandatory room/item counts and independent truth still to confirm when arranged |

## Blocking questions already sent to user

| ID | Question | Blocks |
| --- | --- | --- |
| D01 | User selected laptop browser on localhost for M02b smoke. In-app browser UI tested; camera response timed out pending permission/device response. Physical camera make/model remains unknown; Android HTTPS remains a later check | Actual camera smoke; future Android route |
| D02 | No LiDAR; reference object allowed. M06a asks for object/dimensions/tolerances/provenance; M06b proposes spoken answers for explicit review. These declarations do not establish metric readiness. M03a still requires same-plane annotations and an independent check point; no physical inputs supplied yet. Real microphone intake remains unverified | Physical calibration smoke, M03b room feasibility and device acceptance |
| D21 | M03b2 requires independently verified fixed camera intrinsics; estimated focal length was biased in the previous synthetic run. Asked whether setup should guide calibration or accept a supplied profile. Answer pending; no real profile/calibration workflow exists yet | Actual metric room smoke and calibration setup integration |
| D03 | Answered behavior: agent asks country/currency at the start of each conversation; no country is hardcoded. Actual demo and second-country test inputs can be supplied when running | M00 locale source coverage smoke, M07 two-locale demonstration |
| D04 | Free tier only. User confirms the existing Gemini key is free tier and authorizes use. M06b's optional reviewed Gemini Live model passed a short target smoke; no paid fallback or automatic retry. The application cannot inspect billing tier and requires an explicit configuration flag. Groq remains an allowed alternative, not an implemented fallback | Provider quota coverage and real-device voice acceptance |
| D05 | Partially answered: user will arrange books. Confirm mandatory room/shelf/non-book counts and independent ground truth when ready | M11 physical evaluation; not a blocker for synthetic contract work |
| D06 | Latest user says the reference is already tested and no further reference testing is needed. Baseline accepted. Actual submission deadline remains unknown | Calendar schedule; target device checks in future modules |
| D07 | Gross or net wall area; shelving union interpretation; meaning of shelf run | M01/M03/M09 totals/geometry contracts |
| D08 | Appraisal value threshold; tax/delivery policy | M07 published valuation |

Answered constraints above supersede the original unanswered questions. Remaining details are pending, not answered by elapsed time. Work on independent tasks can continue; no dependent implementation may silently assume missing facts. A dynamic locale requirement does not remove the need for actual locale inputs during source/evaluation tests.

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

## M11 evaluation decisions and remaining evidence

M11 supports explicit conservative all-comparison spine scoring and all-available-comparison price scoring, with incomplete/unavailable truth unable to produce a full pass. A supplied policy must choose the confidence threshold and primary wrong-confidence denominator; both denominators are reported. This is a supported implementation convention, not an assertion that the user approved a particular threshold/denominator. No actual evaluation policy was frozen in this group. Physical truth/archive availability remains unresolved. Full-room accuracy, demo, measured repair/held-out run, production cost/timing and clean setup are not measured. See [M11 review](45-m11-group-review.md).
