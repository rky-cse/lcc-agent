# M03a review: annotated planar spine measurement

Status on 10 October 2026: implemented within the user's latest "next" authorization. Synthetic geometry and saved-frame/CLI/packet smoke passed. Physical dimension accuracy remains **not measured**. M03b connected room geometry has not started. Awaiting user review.

## Outcome and scope

This part converts explicitly developer-annotated spine corners into centimetres using a rectangular reference object on the same plane and in the same saved frame. It supports upright and horizontal spines through explicit corner ordering. It emits M01-compatible measurement evidence, a structured stage result, unknown/review findings, a portable JSON/HTML packet and SVG annotation overlays. No automatic detection, voice intake, camera UI annotation tool, room reconstruction or model call was added.

The user clarified: **the agent asks the user for the reference object during calibration**. The actual object is a runtime input, rather than a project-wide selected object. M06 must ask for the object's identity, independently measured width/height, measurement tolerances and placement beside the spines on the same plane. It must request a usable view and independent check observations, ask again if ambiguous, and keep dimensions unknown until supported. Object identity alone is insufficient: no assumed credit-card, paper-sheet or book dimensions. This CLI implements the calculation boundary that future intake will call; it does not claim to implement the conversational agent.

## Files and boundaries

| File | Responsibility |
| --- | --- |
| `library_claim/planar.py` | Typed reference/annotation/policy input; normalized projective solve; region/rectangle checks; sensitivity exploration |
| `library_claim/measurement.py` | Saved-frame/hash/sweep verification; calibration gates; per-spine results; M01 evidence/export; overlay and CLI |
| `tests/test_planar_measurement.py` | 21 geometry, invalidity, provenance, replay and portable-export checks |
| `scripts/smoke_planar.py` | Independently specified synthetic scene; saved-frame ingest; separate interpreter CLI; final packet assertions |

The reusable local components are M02a's immutable `FrameStore` and M01's contracts, numeric JSON serializer, evidence audit, aggregation and export. The reference app has no trustworthy planar measurement adapter to copy. No upstream source, credentials or reference tests were added/run in this part. The normalized solver uses Python's standard library; no OpenCV/NumPy runtime dependency was introduced. The plane restriction follows the [OpenCV homography explanation](https://docs.opencv.org/4.13.0/d9/dab/tutorial_homography.html).

## Input contract

The exact example is `runs/m03a-planar-review/input.json`; it is explicitly synthetic. All following policy/calibration values must be supplied. The example values are engineering test inputs and are not calibrated production thresholds.

| Input | Interpretation |
| --- | --- |
| `sweep_id`, spine IDs, `frame_ref` | Saved frames must belong to that sweep; spine IDs must be unique and cannot be `room` |
| `reference` | May be null; null yields unknown dimensions and review entries, without metric evidence |
| `frame_sha256` | Must match the saved original; hashes/decoded originals are verified by the store before calculation |
| `width_cm`, `height_cm` | Positive finite independently measured reference dimensions |
| `width_uncertainty_cm`, `height_uncertainty_cm` | Nonnegative tolerances smaller than their dimensions; zero is an explicit caller assertion, never inferred |
| `dimensions_verified`, `dimension_provenance` | Required affirmative assertion/nonblank provenance; caller declaration is retained, not treated as an automatic physical verification |
| Reference `corners_px` | Four ordered encoded-pixel corners corresponding to physical `(0,0),(width,0),(width,height),(0,height)` |
| `coordinate_space` | Only `encoded_pixels`; no implicit preview-to-original conversion |
| `corner_tolerance_px` | Explicit per-reference/per-spine corner localization tolerance |
| `plane_id`, spine `coplanarity_confirmed`, provenance | Must agree and be affirmatively declared; different depths cannot share this calibration |
| `lens_status`, `lens_provenance` | Caller declares corrected or independently verified negligible distortion; `unknown` is unavailable. This module does not estimate/correct distortion |
| `valid_region_px`, provenance | Ordered convex polygon where the caller asserts the same-plane/lens assumptions hold; not inferred to be the whole image |
| `check_points` | At least one independently observed pixel↔known-plane-centimetre point, not a fitted corner, within the region. A centre mark with independently known position is one possible input; using the image midpoint under perspective is invalid |
| Spine `corners_px` | `q0→q1` is thickness; `q1→q2` is height, including horizontal books. Four corners required |
| `annotation_source` | Only `developer_annotated`, visibly labeled in output; does not establish a production detection/count |
| `policy` | Minimum reference pixel area, maximum independent check error (cm), opposite-edge disagreement, corner cosine and relative explored sensitivity |

Encoded and displayed image coordinates differ for EXIF-rotated photos. M03a rejects a calibration on orientations other than absent/1 until an explicit coordinate adapter is implemented. Originals are never silently rotated or rewritten.

## Calculation and failure behavior

Normalize the four source/destination points, solve the eight homography equations with partial pivoting, and denormalize the resulting pixel-to-centimetre matrix. Reject degenerate/ill-conditioned geometry. Check that the declared convex region does not cross the projective horizon. A four-corner fit is exact by construction and cannot establish accuracy, so require an independent check and compare its metric mapping error with the supplied policy.

For each spine, enforce same frame, same declared plane, bounds/region and confirmed coplanarity. Map the corners, verify opposite-edge agreement and approximate right angles, then average the two height edges and two thickness edges. A single-frame homography is never transferred to another camera view. Missing/invalid physical assumptions preserve that spine in the output with null dimensions, a review finding and a structured `measurement_unavailable` stage error for `spine_dimensions`. Accepted and unavailable spines can coexist in a partial stage. Missing frames, tampered originals, reference-hash mismatch and wrong sweep fail the invocation before export.

The sensitivity exploration tests the four combinations of reference-dimension tolerance extremes and one coordinate perturbation at a time for each reference/spine corner. Report the minimum/maximum explored height/thickness and reject when the maximum relative movement exceeds policy. **This is not a combined worst-case interval, confidence bound or physical accuracy guarantee**; simultaneous pixel errors, distorted lenses and off-plane geometry can exceed it. No 95% confidence is implied. Output at 0.001 cm is computational presentation precision; real accuracy must be independently measured.

The output records the input SHA-256, algorithm version, matrix, check diagnostics, per-spine results, sensitivity label, frame evidence IDs, stage timing, warnings, errors and M01 measurement records. Full calibration assertions/annotations are saved in `measurement_input.json`. Fingerprinted evidence IDs and values replay deterministically; wall-clock stage timestamps vary. Changing any input changes the fingerprint. Packet bibliography/prices and room metrics stay unknown; measured spines do not imply identified titles or a complete inventory.

## Verification evidence

Executed with `.local/reference-env/Scripts/python.exe`:

```powershell
.\.local\reference-env\Scripts\python.exe -B -m unittest discover -s tests
.\.local\reference-env\Scripts\python.exe -B scripts/smoke_planar.py --output runs/m03a-planar-review
```

Full Python suite: **82 passed**, comprising 61 prior checks and 21 M03a checks. The prior unchanged browser module had 9 passing Node tests; these were not rerun for Python-only changes. The existing Starlette/HTTPX test-client deprecation warning remains, without test failures.

M03a checks cover independently defined affine/perspective geometry, horizontal axes, missing reference, unverified dimensions/lens/plane, independent-check absence/corner reuse/error, off-plane partial output, missing/tampered/wrong-sweep/hash evidence, cross-frame transfer, bounds/region, degenerate/tiny reference, self-intersecting region, projective horizon, EXIF orientation, nonrectangular spine, high sensitivity, analytic dimension-tolerance envelopes, invalid schema inputs, stable evidence replay and portable export/no overwrite. Export assertions verify numeric dimensions, blank title, unknown price, centimetre-to-metre aggregation, exact original bytes and valid escaped SVG XML.

Synthetic smoke saves a 1920×1080 PNG projected by an independently specified forward camera, exits the measuring interpreter, then inspects the exported artifact:

| Synthetic object | Ground-truth height × thickness | Actual result |
| --- | --- | --- |
| Upright | 23 × 2.5 cm | 23.000 × 2.500 cm |
| Horizontal | 22 × 3 cm | 22.000 × 3.000 cm |
| Declared off-plane | No supported metric truth | Both null; review retained |

Three rows remain in the packet. Full shelf run is null because one thickness is unknown; measured subtotal is 0.055 m. No priced lines are present. Original bytes are preserved in the portable packet. The original synthetic scene was visually inspected; overlay XML/escaping were checked, but browser rendering of the SVG overlay was not verified.

Artifacts under `runs/m03a-planar-review/`:

- `synthetic-scene.png`, `ground-truth.json`, `input.json` and `store/`: labeled synthetic source, independently defined scene and durable original.
- `packet/measurement_input.json`, `packet/measurement_result.json`: calculation inputs, diagnostics and results.
- `packet/claim_packet.json`, `packet/report.html`, `packet/frames/`: M01 portable export with numeric/unknown semantics.
- `packet/overlay-*.svg`: original image embedded with green reference/orange developer annotation outlines and measured/unavailable labels.

No API calls or provider charges were incurred. Run artifacts are ignored by Git; smoke scripts reproduce them. Choose a fresh directory, since export never overwrites a previous review bundle. Extra diagnostic/overlay writes occur after the M01 export; a late I/O failure can leave a partial bundle. Transactional finalization remains M10 work.

## Remaining acceptance gates and next review

No physical reference object, same-plane photo, independently measured spine truth or lens-validity evidence was supplied. The user's response establishes agent-led runtime intake; it does not supply physical measurements. The brief's ≤15% spine error requirement remains **not measured**. A real smoke must retain original frames, calibration observations, independently measured upright/horizontal spines, per-dimension relative errors and all rejected examples. Tune thresholds on calibration data, then assess separate held-out examples.

M02a actual original-photo smoke and M02b real camera smoke remain unverified. This calculator does not establish connected room geometry or transfer scale across frames. M03b is the proposed next small part, after user review and explicit authorization. If ordinary RGB capture cannot establish connected metric room geometry, document that failure and review options before M09 rather than invent dimensions.

**Awaiting user review.**
