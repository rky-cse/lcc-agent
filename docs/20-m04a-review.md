# M04a review: one-shelf spine proposals and count

Status on 10 October 2026: implemented under the user's latest "next". Unit/boundary tests, replay smoke and an actual free-tier-key Gemini synthetic-image call passed. Actual shelf precision/recall remain **not measured**. M04b cross-view physical tracking has not started. **Awaiting user review.**

## Outcome and scope

One immutable saved shelf image and an explicit shelf region produce visible book-spine quadrilateral proposals, orientation labels, unresolved regions, an auditable provisional count and unidentified inventory rows. Deterministic local checks reject invalid geometry and flag overlaps instead of guessing which physical copies to merge. A standalone HTML/SVG review overlays every proposal on the exact original.

The selected provider is **Gemini 3.1 Flash-Lite**, accessed via standard-library REST with structured JSON. This is a multimodal proposal adapter, not a trained specialist spine detector or a proven production segmentation dependency. Google documents [image understanding](https://ai.google.dev/gemini-api/docs/image-understanding), [structured outputs](https://ai.google.dev/gemini-api/docs/structured-output), [the REST method](https://ai.google.dev/api/generate-content) and [free-tier eligibility](https://ai.google.dev/gemini-api/docs/pricing). Schema compliance does not establish semantic correctness or coverage.

This part does not implement cross-frame deduplication, live state publication, OCR/title/edition matching, ownership correction, metric calibration or pricing. `books` are M01-shaped unidentified observations for the next module; no full claim packet is exported by M04a. All identity strings are blank and metric/price values unknown. Book observation IDs are not yet physical track IDs. Do not combine per-frame counts into a whole-sweep count.

## Components and reuse

| File | Responsibility |
| --- | --- |
| `library_claim/spine_detection.py` | Typed shelf input/provider proposals; geometry/overlap validation; provisional count/rows; evidence/HTML/SVG export; CLI |
| `library_claim/vision_provider.py` | Fixed-domain authenticated Gemini REST; free-eligible allowlist; schema/finish/size validation; local key loading; sanitized failure/usage |
| `scripts/smoke_detection.py` | Independent synthetic shelf plus deterministic replay or explicit live-provider smoke |
| `scripts/evaluate_detection.py` | Same-frame truth matching by polygon IoU with full denominators and one-to-one assignment |
| `tests/test_spine_detection.py` | 17 geometry/count/evidence/export/evaluation checks |
| `tests/test_vision_provider.py` | 5 mocked request/schema/failure/redaction/key-loading checks |

Reuses the target's immutable `FrameStore`, M01 unidentified `Book` and stage contracts, JSON serializer, and M03 convex-polygon/area helpers. Convex intersection clipping is independently implemented. No upstream reference code/credentials were copied, no reference tests ran, and no extra Python SDK or vision dependency was installed. The existing confirmed free-tier key was read from the reference `.env` only because the user had explicitly authorized its use. The reference files were not modified; keys were never printed or saved in artifacts.

## Input and response contracts

| Input | Required interpretation |
| --- | --- |
| `sweep_id`, `frame_ref`, `frame_sha256` | Saved frame must belong to the sweep and match the declared original hash; store decoding/hash checks run before use |
| `shelf_id` | Explicit single-shelf observation scope, not a model-generated global shelf identity |
| `shelf_region_px` | Caller-selected `(xmin,ymin,xmax,ymax)` on the original encoded image; positive region inside its bounds |
| `policy.min_polygon_area_px2` | Explicit minimum supported proposal area; development fixture uses 100 px² |
| `policy.max_pair_overlap_fraction` | Explicit overlap area divided by the smaller polygon's area; development fixture uses 0.5 |
| `--response` | Offline validated-response replay; useful for regression/saved-provider review, not an inference accuracy test |
| `--gemini` | Explicitly send this saved original to the configured provider; key stays local/server-side |
| `--free-tier-confirmed` | Required caller assertion before live use; an API key alone cannot prove billing tier |
| `--model` | Explicit free-eligible allowlist: default `gemini-3.1-flash-lite`, also `gemini-2.5-flash` and `gemini-3.5-flash-lite`; no automatic model fallback |
| `--key-file` | Optional local `.env` path; otherwise `GEMINI_API_KEY`/`GOOGLE_API_KEY` environment variables. No shell evaluation/interpolation |

Provider response contains `coverage` (`clear`, `uncertain`, `no_visible_books`), at most 256 objects and at most 40 unresolved regions. Each object has `kind` (`book_spine`, `non_book`, `ambiguous`), `orientation` (`upright`, `horizontal`, `diagonal`, `unknown`), four finite normalized `[x,y]` vertices and a bounded reason. All fields are present, extra fields are rejected. The provider is not asked for an aggregate count or bibliographic/metric information.

Coordinates use original-image **edges**, normalized to 0–1000, then mapped by original width/height. A vertex at 1000 maps to the image boundary. This differs from pixel-centre annotation conventions and from M03's spine-axis corner order. Detection polygons cannot be copied directly into M03 measurement inputs without a reviewed coordinate/axis/plane validity adapter. EXIF rotation is rejected pending an explicit adapter; no original reencoding, inferred preview scale or lens correction occurs.

## Processing and count semantics

Every `book_spine` polygon must be convex/ordered, above area policy, inside the selected shelf region and have a known orientation. `non_book` is retained visibly as an excluded model classification, not reclassified by geometry. `ambiguous` and invalid proposals go to review. Adjacent distinct copies remain separate even if their text/appearance is identical. No title-based deduplication exists.

Evaluate all valid proposal pairs before changing statuses. Excessive overlap flags **both** proposals for duplicate/split/merge review; the code neither silently suppresses a smaller candidate nor merges nearby books. This can undercount valid occluding proposals, so publish the ambiguity instead of treating the remaining count as truth. Unresolved region polygons must also be convex/ordered; malformed live geometry yields a typed unavailable result.

`provisional_observed_count` counts accepted proposals. `provisional_shelf_count` is null when coverage is uncertain, unresolved/review cases exist, or coverage contradicts book proposals. Otherwise it equals the accepted proposal count, still with `provisional=true` and `coverage_verified=false`. Neither number proves no missed/hidden copies, and a provisional count is not a guaranteed lower bound because false positives are possible. A valid empty-shelf response can provisionally report zero; provider/network/schema failure reports **null**, never zero.

Same-frame observation IDs derive from frame ID, shelf ID, polygon and orientation. Provider response reordering retains the same spatially sorted rows/IDs. Different frames or changed polygons may have different IDs; M04b must establish physical tracks. Positions are provisional left-to-right, then top-to-bottom for equal left extents; they are not edition/copy identity.

## Provider limits, cost and failure behavior

The adapter makes one request per explicit invocation, uses an API-key header on the fixed Google endpoint, disables redirects and has no retries, search/grounding, paid fallback or billing-setting changes. Original image cap: 10 MiB; response cap: 2 MiB; network socket timeout: 45 seconds; output budget: 8192 tokens. These are engineering limits. The socket timeout is not a strict total wall-clock deadline for a slowly streaming response; a process-wide stage deadline is future scheduling work. Oversized originals stay saved but cannot be sent by this adapter.

Require exactly one candidate with `finishReason=STOP`; blocked/truncated/missing/invalid-schema responses become unavailable. HTTP 429 preserves retryability and any `Retry-After` header, without retrying. HTTP/timeout/input-limit/schema/geometry errors are structured, retained with the source original, and leave count unknown. Bounded HTTP error JSON and successful raw response JSON are saved with explicit key redaction. No request headers/key/full request image payload are logged.

Usage records preserve returned token metadata/model version, request count, elapsed request time and `billing_verified=false`. The account's free tier is the user's confirmed assertion; this module cannot inspect billing. Free-tier terms may permit provider product-improvement use, as documented by Google. Before real provider capture, the product must explain which images leave the device and apply the project's privacy/capture requirements. Only the synthetic shelf image was sent in this part.

Development made two image requests plus one read-only model-list request. The initial `gemini-2.5-flash` call returned **HTTP 404**, even though model listing included that name. No cause beyond the actual HTTP result is claimed. Its unavailable review remains in `runs/m04a-live-smoke/`. After verifying available names/free eligibility, a separate explicit call with `gemini-3.1-flash-lite` succeeded. This was a development selection change, not automatic runtime fallback. No further image calls were made for regression checks.

## Tests and smoke evidence

```powershell
.\.local\reference-env\Scripts\python.exe -B -m unittest discover -s tests
.\.local\reference-env\Scripts\python.exe -B scripts/smoke_detection.py --output runs/m04a-replay-smoke
.\.local\reference-env\Scripts\python.exe -B scripts/smoke_detection.py --gemini --key-file "PATH_TO_LOCAL_ENV" --output runs/m04a-live-review
.\.local\reference-env\Scripts\python.exe -B scripts/evaluate_detection.py --result runs/m04a-live-review/review/detection_result.json --truth runs/m04a-live-review/ground-truth.json --min-iou 0.5 --output runs/m04a-live-review/evaluation.json
```

Full suite: **147 Python tests passed** (125 earlier + 22 new). New checks cover upright/horizontal polygons; excluded bookend labels; adjacent copies; overlapping duplicates; degenerate/tiny/unknown/out-of-region proposals; ambiguous/glared/inconsistent/empty coverage; replay-order stability; original/sweep/region integrity; schema bounds/nonfinite/extra fields; convex overlap; escaped portable review/no overwrite; failure counts unknown; count cancellation exposed by evaluation; provider request/usage/schema/finish handling; rate limit/no retry/key redaction; network failure/allowlist/redirect handling; input cap/key loading. Provider tests use mocks; actual provider execution is the separate smoke below. Prior browser tests were not rerun because browser code is unchanged. Existing Starlette/HTTPX warning remains.

Replay smoke supplies known fixture polygons: **six candidate rows, one excluded bookend**, exact saved original and exported overlay/report. It tests the transport-independent boundary and is explicitly not a detector score.

Actual live smoke gives the provider only a 1920×1080 synthetic shelf graphic, the ROI and instructions. Ground-truth geometry/count is saved separately and is not included in the provider prompt. The graphic has four upright and two horizontal book spines labeled BOOK, plus a bookend; this is an easy synthetic service check, not a substitute for realistic books, dense rows, glare or occlusion.

| Actual live result | Outcome |
| --- | --- |
| Provider/version | `gemini-3.1-flash-lite` |
| Candidate spines | 4 upright + 2 horizontal |
| Bookend | Returned as non-book, excluded |
| Full-denominator one-to-one matches at IoU ≥ 0.5 | 6 true positives, 0 false positives, 0 false negatives |
| Polygon IoU range | Approximately 0.9368–0.9919 |
| Orientation agreement on matched objects | 6/6 |
| Returned usage | 1351 prompt tokens (251 text, 1100 image), 705 output tokens; 2056 total |
| Request elapsed time | Approximately 23.47 s on this account/run |
| Billing | User-confirmed free-tier account; not independently verified |

The evaluation binds truth/result to the same original SHA and finds maximum-cardinality one-to-one matches over polygon IoU. It reports all truth rows, false positives and misses; an equal aggregate count cannot hide one false positive plus one miss. It does not score ignored non-book inventory, real coverage or cross-view tracks. The observed 100% precision/recall applies only to this six-book graphic. Detection thresholds/model/prompt must be calibrated on actual non-evaluation shelves, then frozen for held-out evaluation.

## Review artifacts and operating commands

`runs/m04a-live-review/` contains the synthetic source, source store, typed input, independent truth and evaluation. `review/` contains `original.png`, `detector_response.json`, sanitized `provider_response.json`, `detection_input.json`, `detection_result.json`, `overlay.svg` and `report.html`. `replay-current/` and `replay-evaluation.json` reproduce the saved successful provider polygons with the final local code, without another API call. Its provider label is `offline_replay`; it does not claim a second live inference.

The original synthetic source was visually inspected. Per-polygon matching and escaped SVG/XML/export were tested. Browser rendering of the standalone report was not inspected in this part; the report was opened as a workspace artifact for user review. It embeds the original image, with green candidate, orange review and gray excluded outlines, and all reasons escaped. No model scripts/HTML execute. The HTML and JSON use the same count/proposal values.

For a real saved shelf frame, prepare its request JSON and invoke:

```powershell
python -B -m library_claim.spine_detection --store runs/my-capture --input shelf.json --output runs/my-detection --gemini --free-tier-confirmed
```

Supply a local key through environment variables or `--key-file`. Choose a fresh output each time; existing output is rejected before an API call. The original source hash, response and observation ledger stay auditable. No automatic queue/live UI publication is wired yet. Stage timing now begins before live requests; the first saved live smoke used the earlier postprocessing-only stage timestamp, so its provider elapsed measurement is taken from `usage` rather than that stage duration.

## Remaining gates and review stop

No actual book shelf photo, held-out physical annotations or multi-shelf pass was supplied/tested. Real diagonal/stacked/occluded segmentation and bookend rejection remain unverified despite positive synthetic/unit cases. The brief's count accuracy and high-confidence identification bars remain not measured; identification is not implemented here. Capture/calibration questions from earlier modules remain open.

M04b is the proposed next small part: map overlapping/revisited views into physical tracks, preserve distinct duplicate copies and publish provisional unknown inventory. It requires actual registration/ambiguity handling, not a sum of these per-frame counts. Await user review and the next instruction; do not start it automatically.

**Awaiting user review.**
