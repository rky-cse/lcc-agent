# M11 — evaluation and delivery tooling

**Software complete for review; physical deliverables pending.** The latest “next” authorized the entire M11 group. Smoke testing remains disabled. This group makes no actual-room accuracy, cost, latency or demo claim and performs no external submission.

## Implementation

M11a freezes independent truth, explicit evaluation policy and a supplied runtime configuration with annotation/freeze timestamps and a content hash. Freeze must precede capture. Hashes bind inputs; human independence and the actually applied configuration require review. Keep truth outside the runtime store and freeze it before tuning the final room.

M11b reads M10 ZIPs without extracting paths. It bounds compressed/expanded size, rejects unsafe/duplicate paths, verifies the exact manifest/file set and frame hashes, audits packet arithmetic and JSON/report/summary agreement, and re-parses selected book/item quotes and FX from saved sources and frozen candidates. It makes no network request. It does not independently repeat native reconstruction or establish physical accuracy.

M11c requires reviewed one-to-one physical matching by shelf/row/position and frame evidence. Titles are not used for fuzzy matching. Every matched emitted title needs an independent correctness judgment. Misses and extra predictions stay visible, with explicit reviewer observations of false merges/splits. Unmatched high-confidence titles receive no correctness credit and conservatively enter wrong/unverified high-confidence output.

M11d exports full-denominator metrics, individual sample rows and explicit availability. Cost/timing comes only from supplied records. M11e checks the same ten physical books' second-country M07 rows already preserved by M10. M11f checks local delivery evidence, three distinct observed failure IDs and before/after/held-out comparisons. No files are uploaded, repositories shared or email sent.

## Components and reuse

`library_claim/evaluation.py`: typed truth/policy/matching/telemetry, freeze, archive validation, scoring and JSON/CSV/HTML output. `library_claim/delivery.py`: asset, demo/setup, failure-analysis and repair checks. `tests/test_evaluation.py`: material integrity/scoring tests. `docs/evaluation-templates/`: blank inputs and JSON Schemas. Blank templates deliberately require completion before freeze/evaluation.

Reused M01 Decimal JSON and typed boundaries, M07/M08 literal quote/FX validation, M10 independent totals and report/summary rendering. The existing `scripts/evaluate_detection.py` remains a one-frame IoU diagnostic. No new dependency or production lookup of evaluation truth was added. The reference was not retested.

## Run the evaluator

1. Arrange a permitted enclosed room with ≥60 owned books, ≥2 shelving units and ≥8 owned non-book items. Independently annotate every physical copy, legibility and visible title/author/publisher. Include unreadable copies and horizontal stacks in count. Record exclusions and consistent set/component conventions.
2. Copy templates outside the runtime frame store. Fill exactly 20 prespecified spine samples with positive height/thickness measurements, uncertainty and evidence. Select 15 price books with explicit new/used availability, source type, condition, locale, fees and independent source evidence. Record taped areas under the same gross/net convention and link the full taped geometry in room evidence. Do not reduce samples after seeing errors.
3. Fill `policy.json` with a confidence threshold and primary denominator (`high_confidence` or `human_legible`). Both denominators are reported. The supported conservative aggregations require all 40 spine comparisons and all 30 available price comparisons within bar. Unavailable truth prevents a complete price pass. No confidence threshold or primary denominator is silently selected.
4. Fill `config.json` with actual code revision, device/resolution/zoom/intrinsics, model roles and recognition/calibration/valuation/area settings. Include no credentials. Freeze before final capture:

```powershell
python -B -m library_claim.evaluation freeze --truth <truth.json> --policy <policy.json> --config <config.json> --output <frozen-truth.json>
```

5. When ready, perform the real continuous sweep, end capture, finish explicit review and download the immutable `/packet` ZIP. Record actual monotonic sweep-start/end and validated JSON+report-ready events using one clock domain, including retrieval, retries and export. Packet duration defaults and wall-clock freeze time are not latency evidence. Preserve usage/billing and stage logs; missing free-tier accounting remains unknown.
6. Populate `assessment.json` after independent physical matching. `truth_sha256` is the frozen payload hash. `packet_sha256` is SHA-256 of M01 `json_text(packet).encode('utf-8')`, without newline and preserving key order; this equals M10 `result_sha256`. Timing must refer to that same hash. Review must follow capture. Price-basis confirmations attest matching edition/equivalent, source type, condition, locale and fees; the scorer additionally compares literal source type/condition/currency/fees. Incompatible comparisons get no credit.
7. Select the saved M07 second-country run during M10 finalization. Set `second_locale_country` and exactly ten `second_locale_book_ids` in the assessment. The evaluator re-parses their archived offers/FX; absent prices remain unavailable. Alternatively, an independently produced `--second-archive` can retain the sweep/identity while changing country. Do not select both mechanisms.

```powershell
python -B -m library_claim.evaluation evaluate --archive <packet.zip> --frozen-truth <frozen-truth.json> --assessment <assessment.json> --output <fresh-results-directory>
```

Outputs: `results.json`, `evaluation.html`, bound truth/review, books/dimensions/prices/items/stages/second-locale CSVs and an evaluation manifest. CSV formula prefixes are made literal. JSON is authoritative for exact precision and nested provenance. Empty tables say not measured. Synthetic/undersized scenarios remain ineligible for assignment acceptance even when computed fixture metrics pass.

## Metric conventions

| Measure | Interpretation |
| --- | --- |
| Count | Absolute relative error ≤5%; also physical precision/recall, unmatched truth/predictions and merges/splits. Empty truth count is undefined. |
| Titles | Correct physical work titles / all independently human-legible spines ≥70%. Missed shelves/blur cannot shrink the denominator. |
| Confident wrong | Both wrong/unverified high-confidence titles / high-confidence outputs and / human-legible truth, with ≤3% bar; selected primary governs the principal result. Missing confidence is not calibrated confidence; empty high-confidence denominator is undefined. |
| Spines | Exactly 20 samples × two dimensions; every error ≤15%. Missing output fails; incomplete sample cannot pass. Mean/median/max and raw rows are retained. |
| Prices | Exactly 15 samples × new/used; every comparable available error ≤25%. Missing/incompatible prediction fails; unavailable truth stays separate and prevents a full pass. |
| Non-books | Found AND exactly correctly categorized / all in-scope items ≥80%; retain false positives/category pairs. Use the production category vocabulary. |
| Areas | Floor error ≤10%, wall error ≤15%; wall gross/net must match. Missing output against known truth fails. |
| Timing | Packet-ready minus sweep-end <300 s; sweep target <180 s, both strict. Missing monotonic evidence is not measured; parallel stage durations are not a critical-path sum. |
| Cost | Separate actual and estimated totals per currency. Partial/estimated/empty accounting cannot be complete actual sweep cost. Never infer zero from free tier. |

## Check delivery and observed repair

Fill `delivery.json` using its schema. Paths resolve relative to that file; SHA-256 binds local assets. The checker revalidates packet/evaluation metrics. Architecture is the actual implemented one-page note. Demo needs a real file, duration ≤360 s, exact sweep/packet hashes and named review of single take, audible voice, continuous sweep, live inventory and visible final packet. These are reviewer assertions, not automatic video analysis. Setup needs a successful timed clean environment <900 s and saved log. Missing demo/setup stays not measured.

Rank the three worst actual errors by count/value/area/trust impact. Supply their generated `E...` IDs, root causes, tried changes, evidence and two-week remedies. Invented/repeated IDs are rejected. A user-authorized repair needs a fresh after sweep of the failed dataset and a different held-out dataset/sweep. Supply manifested before/after/held-out result directories, `after_archive`, `heldout_archive` and the metric. The checker independently recomputes their metrics/eligibility from bound truth and actual packet archives; rewritten result summaries cannot establish a repair pass. It reports statuses and metrics that regress from pass to fail. Only fail→pass plus a held-out pass is a recorded repair pass. Root causes/causality remain human review. Hashes are integrity bindings, not external signed attestations.

```powershell
python -B -m library_claim.delivery --input <delivery.json> --output <fresh-delivery-directory>
```

Outputs: `delivery.json` with six-deliverable statuses/assets/cost/stage latency/repair, and `failure-log.md` with supplied observed analysis. Repository private access is an assertion; no remote permissions check is implied. Archive integrity does not certify physical accuracy.

## Verification and limits

Automated verification: **577 full Python regressions passed** in 184.074 seconds, including the initial 26 M11 checks. After final repair/size refinements, **28 expanded M11 checks passed** in 6.509 seconds. **68 Node tests passed**. Whitespace checks passed. Existing Starlette/HTTPX deprecation and Git line-ending warnings remain. Blank input/schema generation was an artifact creation step, not a smoke run. No server/browser/provider/source smoke test, device call or clean setup rehearsal was performed. Offline test source adapters used controlled fixtures; actual production sweep cost remains not measured.

Still pending: full-room truth, real demo/archive, actual timing/cost, sourced second locale, three worst room errors, measured repair/held-out sweep and timed clean setup. Explicit physical reviews, developer geometry annotations, camera-calibration acquisition and automatic room boundaries remain prototype limitations. M11 tooling does not certify the original brief as passed.

**Awaiting user review.**
