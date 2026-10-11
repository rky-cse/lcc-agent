# M10 — Immutable final packet integration

The whole M10 group is implemented for review. The user authorized M10 with `next` while M09 was being completed. No subpart review stops or smoke tests were performed. M11 evaluation/delivery has not started. No reference app test, browser/device smoke, network source/provider call, paid action, key read, deployment or commit was performed for M10.

## Components and reuse

| Part | Component | Behavior |
| --- | --- | --- |
| M10a | `finalization.py` | Closed-capture/drain/deadline barrier, revision pins, transactional immutable freeze, resumable publication |
| M10b | `final_audit.py` | Saved-source reparsing, independent Decimal FX/line/range/count audit, deterministic spoken summary |
| M10c | `finalization.py`, `report.py` | One serialized packet, HTML report, summary and portable ZIP with original/source/model/artifact manifests |
| M10d | `server.py`, `web/packet.html`, `packet.mjs`, `packet_core.mjs` | Explicit review/finalize/retry/reopen/download and browser speech action |

M01's typed packet, structural evidence checks, unknown handling, physical ownership filtering, report escaping and exact Decimal JSON encoder are reused. M03 planar measurement is reused for reviewed book dimensions and recomputation of M08 dimension proofs. M04/M05 physical tracks and identity artifacts, M06 capture/guidance/recognition state, M07 retailer/FX snapshots, M08 grouping/art/item snapshots and M09 verified geometry are integrated. The reference app's insurance-policy tools and ephemeral state remain unnecessary.

The M01 draft builder retains its original strict price validation. M10 first builds an evidence-checked unpriced base, then attaches only independently rechecked M07/M08 quotes. This avoids pretending that a converted target amount is a literal retailer price or manufacturing a source excerpt to satisfy M01's earlier boundary. Original source amounts and separate dated FX remain visible in the final quote manifest.

## State machine and consistent freeze

`FinalizationRequest` pins sweep ID, final run ID, book/contents revisions, timezone-aware absolute deadline, selected saved book/item valuation runs, optional saved area run, optional reviewed planar book measurements, aggregation policy and an explicit uncompressed archive byte budget. No locale or pricing convention defaults are chosen. The full generated schema is exposed at `/api/finalization/schema`.

Capture must already be explicitly ended. The deadline cannot precede capture end. A live queued/running recognition job, retained worker slot or selected running valuation causes `waiting_for_drain` before that deadline. An exact POST retry rechecks the barrier; reads do not run work. At/after the deadline, unfinished selected work is excluded and recorded in a partial snapshot. Interrupted/expired/stale/unselected valuation results never supply money. In-process HTTP valuation and finalization share one computation slot; concurrent HTTP computation receives an explicit retry response.

SQLite `BEGIN IMMEDIATE` prevents other store mutations from committing while capture, physical inventories, selected results, originals, identity/contents/recognition artifacts and guidance are checked and archived. Frozen inputs and content blobs commit together as `frozen`. Publication then consumes those blobs, without source/provider calls and without relying on later live state. A crash before freeze commit publishes nothing; a crash after freeze can resume the exact request using the same frozen inputs. A changed request cannot reuse the same final run ID. A corrected revision needs a fresh run ID.

Publication atomically commits the packet, report, summary and manifest with `published`. Later jobs/corrections can update live inventory but cannot change the completed archive. This does not cancel provider attempts already in progress or prevent further user corrections; their results belong to a later packet. Published reads are historical and do not silently refresh quotations. Quote freshness is evaluated at freeze time, not relabeled as current indefinitely.

## Evidence and valuation audit

Every saved frame is copied as its original bytes into the immutable archive, retaining its frame path/hash. Accepted identity artifacts and all same-sweep M08 artifacts are retained, including historical proposals; proposals lacking physical acceptance produce review findings rather than extra item counts. Completed recognition artifacts are hash-checked and archived. Selected valuation results/requests are in `frozen-inputs.json`, and their original retailer/FX bytes are in `sources/<sha256>.txt`.

Known book dimensions require same-sweep M03 planar annotations inside an observation already assigned to that physical track. Duplicate accepted measurement IDs fail. M08 item dimension proofs are recomputed from their archived commands and checked against current proof values before use. Hidden depth remains null. Measurements for ownership/group-suppressed non-book entities remain in archived upstream proofs rather than being attached to missing packet rows.

Selected M09 originals/request/result/frame ledger and the qualified native model's five required binary files are copied into `geometry/`, including `geometry/images/` so the model's original-file ledger remains portable. Unrelated model/log/environment files are omitted. Stale/unavailable room geometry contributes null room fields and review findings. Known partial geometry can contribute its supported fields. M09's precise metric/imperial projection is retained.

For each eligible price, the audit reparses the archived retailer JSON-LD using its reviewed M07/M08 candidate and frozen physical identity. Parsed amount/currency/condition/availability/product/match provenance must agree with the selected quote. Wrong locale, expired inputs, unresolved identity, ownership exclusions, appraisal and unsupported source conditions cannot silently supply money.

FX is independently recomputed from the archived currency pair, positive literal rate and dated observation within the entered date window. Future FX request dates fail. Foreign markets require explicit fallback authorization, including foreign offers with the same currency. Local offers cannot be relabeled into another currency. Target currency, conversion flag and policy rounding must match the recomputed target amount. Packet decimal places must agree with selected market policy.

Book replacement and used values remain independent components. Item exact-model quotes and comparable min/max ranges are independently checked against their basis, required comparable/host coverage and duplicate comparable identity. Group-suppressed components/parents are excluded from billable rows according to the M08 choice; they remain listed under `group_exclusions`. Nonowned book/item rows remain under `ownership_exclusions`. Original/unanswered art remains appraisal-only; reviewed prints can be priced using eligible M08 evidence.

Totals are recomputed from eligible owned rows using Decimal, never copied from stage totals. A separate audit recomputes counts, identified/unidentified counts, thickness-based shelf run, replacement/used subtotals, item bounds and the explicitly chosen exclusion denominator. Finalization HTTP JSON uses the exact Decimal serializer, preserving the archived monetary numeric tokens. Every known price must resolve to matching final quote evidence and currency/type; appraisal amounts and invalid ranges fail. Physical duplicate copies remain separate inventory rows and may legitimately share one deduplicated quote source.

## Output and review semantics

The ZIP contains:

- `claim_packet.json`: full minimal packet fields plus immutable finalization, coverage, group exclusions, geometry detail and audit metadata.
- `report.html`: escaped readable book/item/room/totals/review output and clickable saved originals/quotes.
- `spoken-summary.txt`: deterministic text generated from the same serialized packet.
- `frozen-inputs.json`: exact selected stage snapshots, requests, revisions, guided questions and deadline state.
- `artifact-manifest.json`: SHA-256, size and relative path for every other archive file; its own hash is excluded to avoid recursion.
- `frames/`, `sources/`, `artifacts/`, and optional `geometry/`: original evidence and upstream proofs.

Reads verify saved blob hashes, the manifest's exact file set/hash/size, packet/HTML/summary agreement, and the independent numeric/quote audit. ZIP entries have fixed timestamps/order for deterministic repeated downloads. Archive paths are portable and checked; no arbitrary server filesystem path is exposed. The entered byte limit bounds uncompressed evidence plus generated output, with a hard supported ceiling of 128 MiB; ZIP container overhead is not included. Oversized input/output fails explicitly without silently dropping evidence. A frozen run exceeding its budget needs a new run ID/budget or reduced explicit selection.

`packet_ready=true` means a verified archive has been published. It does **not** establish physical coverage, accuracy, a complete inventory or insurer acceptance. Packet status stays **partial** because those physical gates remain unverified; the JSON, HTML and spoken summary disclose that. `book_count` is the count of reviewed owned physical tracks, not an assertion that hidden/unresolved books were counted. Unknown/unpriced/appraisal lines remain visible; zero monetary subtotals may mean no eligible priced lines.

Review findings include unresolved physical observations/identity/edition, unknown measurements/prices, missing/invalid room fields, transport gaps, failed/stale/pending jobs, unanswered guided evidence requests, pending corrections, historical unaccepted non-book proposals, stale/expired/unfinished valuations and deadline exclusions. Selection does not automatically accept catalogue identity, detection proposals or ownership corrections.

## Operating guide

1. Restart the existing server with its usual configuration and the same frame store to load M10. Finish/close the sweep from `/sweep`.
2. Complete the desired inventory/identity/measurement/valuation reviews. Saved partial results are allowed; missing evidence remains in the packet review queue. Do not call providers solely to open this page.
3. Open `/packet`, load current revisions and choose **Prepare finalization request**. Enter a timezone-aware absolute deadline, selected saved run IDs, decimal places, `missing_any_component` or `missing_all_components`, and the byte budget. Keep `sum_spine_thickness` as the declared shelf-run basis. Leave unavailable stage selections empty/null; do not invent IDs or dimensions.
4. Optional `book_measurements` use M03 `MeasurementRequest` objects with current physical track IDs and original-frame annotations. They are validated/recomputed at freeze. M08 dimensions and M09 measurements are carried from their checked saved runs.
5. Choose **Freeze and publish reviewed packet**. If waiting, retry the same request after work drains or the entered deadline passes. The page does not start hidden background workers or auto-resubmit writes.
6. Reopen the saved final run ID after restart. Download the ZIP, extract it, and open `report.html`; its relative links resolve within the extracted archive. The page displays the saved summary and can read that exact text aloud on explicit request using the browser's configured speech voice. Device voice availability/quality and local versus remote voice behavior remain untested.
7. After any later correction, generate a fresh final run ID with current revisions/selected results. Keep earlier archives for comparison.

CLI uses the same gates and produces a fresh ZIP path:

```powershell
.local/reference-env/Scripts/python.exe -B -m library_claim.finalization --store runs/capture/store --input runs/reviewed-finalization.json --output runs/delivery/claim-packet.zip
```

Replace example paths with the actual store and reviewed request. Existing output files are not overwritten. A waiting CLI run reports its state and produces no archive; run the identical request again once its barrier permits publication. `/api/sweeps/<sweep>/finalizations/<run>` reopens metadata/JSON; `/archive` downloads the ZIP; `/summary` returns archived summary text. Existing same-origin/host and bounded body guards apply to writes. Reads perform integrity checks only.

## Validation and limits

Tests cover capture-end/deadline/revision gates, recognition drain/deadline and selected running valuation barriers, empty/unpriced/expired output, frozen publication recovery after interruption, exact replay, changed payload/revision rejection, independence from later live originals/corrections, saved-result/artifact/manifest agreement, deterministic ZIP and source links, source-backed book/item repricing without HTTP, literal dated FX/rounding/pair/flag failures, foreign same-currency rejection, monetary tampering, owned/unowned rows, unsafe measurement identity, recomputed M08 dimensions/hidden depth, portable M09 model/evidence/imperial integration, API scope/origin/schema and browser request/status logic.

Verification: **548 full Python regressions passed** (190.911 seconds), followed by **24 expanded M10 focused Python checks passed** after final integration refinements. **All 68 Node tests passed**. New browser modules passed syntax checks, CLI help loaded, and diff whitespace checks passed. The focused suite additionally verifies distinct physical duplicate copies sharing one quote source and redacted finalization storage errors. Existing Starlette/HTTPX warnings are unchanged. These are synthetic controlled tests, with native geometry parsing mocked in reused M09 boundary fixtures. They do not demonstrate real camera/microphone/voice playback, full physical-sweep accuracy, source-market coverage, calibrated confidence, actual 5-minute finalization or final demo acceptance. Native pose/calibration/reference prerequisites and annotated geometry remain M09's documented limits.

The drain deadline controls whether unfinished work is included; it is not a measured processing timeout. Freeze holds a SQLite writer reservation during evidence checks/copying, and the implementation retains bounded archive content in memory/SQLite. Large real-capture latency and storage behavior remain unmeasured. Recognition must be explicitly scheduled elsewhere; finalization never starts source lookup or model calls. No actual insurer submission, share link or deployment is performed.

**Awaiting user review. Next module after authorization: M11 honest physical evaluation and delivery.**
