# M03b2 review: calibrated metric room feasibility

Status on 10 October 2026: implemented under the user's latest "next", within M03b2 only. Synthetic geometry, integrity/export tests and actual native calibrated-reconstruction smoke pass. Physical room accuracy is **not measured**. M04 has not started. **Awaiting user review.**

## Outcome and important finding

This step uses a qualified connected M03b1 model, an independently verified fixed pinhole calibration, developer-annotated multiview points and an independently measured reference length to recover a rectangular footprint's length/width and constant ceiling height. A second reference dimension independently checks scale. Missing/unsupported inputs preserve null room dimensions with review reasons. Full floor/wall/shelving areas remain M09 work.

Inspection of the previous M03b1 synthetic run found a critical limitation: its estimated focal length was approximately **2305.81 px**, versus the renderer's **1200 px**, even with low reprojection error. This is actual evidence that the prior connected sparse model was insufficient for trustworthy metric geometry. M03b2 therefore refuses metric output from estimated/refined intrinsics. It does not fix scale ambiguity with a guessed focal length or a typical room size.

M03b1 now accepts an optional `PinholeCalibration`. With it, the worker uses `PINHOLE` and freezes focal length, principal point and extra parameters in bundle adjustment and pose refinement. Without it, the existing estimated `SIMPLE_RADIAL` path remains useful for connectivity and still cannot supply metric room output. Original saved request fingerprints are checked from their saved schema representation, so adding an optional field does not invalidate old review bundles. See [COLMAP's calibration/fixed-intrinsic guidance](https://colmap.github.io/faq.html) and [model pose/output conventions](https://colmap.github.io/format.html).

The user specified agent-led reference-object intake during calibration. M06 must collect actual reference identity, independently measured dimensions/tolerances and suitable observations. Camera calibration is a separate setup prerequisite: a question was sent asking whether to guide the user through calibration before the timed sweep or use a supplied profile. That preference remains pending at this review. No camera profile for the actual laptop/phone was invented. Guided calibration is not implemented here.

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `reconstruction.py`, `reconstruction_worker.py` | Optional verified pinhole input; known-intrinsic extraction with refinement disabled; calibration validity/resolution checks |
| `room_geometry.py` | Typed observations/reference/check/boundaries/policy; multiray triangulation; metric scaling; rectangular/constant-height tests; explored sensitivity |
| `room_measurement.py` | Reconstruction/frame/model integrity, native pose/intrinsic verification, typed stage and M01 packet/evidence export; CLI |
| `tests/test_room_geometry.py` | 15 independently defined geometry and invalidity checks |
| `tests/test_room_measurement.py` | 8 integrity/export/unknown-boundary checks |
| `scripts/smoke_room.py` | Native fixed-intrinsic image reconstruction, observed-point measurement, portable packet and independent synthetic error table |

Reuses the project's frame store, stage/measurement/room contracts, packet audit/export and M03b1 native reconstruction. Pure measurement geometry uses standard-library vector math and a pivoted 3×3 solve; optional pinned PyCOLMAP/NumPy remains needed to read/reconstruct native models. No new dependencies, reference-source copies, reference tests, Gemini/Groq calls or provider costs were introduced.

## Runtime contract

All geometry inputs are explicit. Example request: `runs/m03b2-final-review/room-input.json`; calibrated reconstruction request: `reconstruction-input.json`. These are synthetic fixtures, not real camera calibration or reference dimensions.

| Input | Meaning and gate |
| --- | --- |
| Pinhole `width`, `height`, `fx`, `fy`, `cx`, `cy` | Independent intrinsic calibration for the actual encoded resolution, same camera/zoom. Positive finite focal lengths; principal point in bounds |
| Calibration coordinate space | `colmap_encoded_pixels`: top-left image edge origin; first pixel centre `(0.5,0.5)`. Convert an OpenCV pixel-centre principal point by adding 0.5; do not silently mix conventions |
| Calibration verification/provenance/lens status | Affirmative independent-calibration assertion, nonblank provenance and corrected/negligible-lens assertion. This code does not acquire/calibrate a real camera or correct its images |
| `sweep_id`, `reconstruction_result_sha256` | Pins the same sweep and exact result bytes. Stored request fingerprint, selected original frames and required native model files are verified |
| `points` | Unique IDs, 2–12 distinct registered-frame observations each, up to 20 points total. Explicit pixel tolerances and nonblank correspondence provenance |
| Annotation coordinate/source | Only `colmap_encoded_pixels` / `developer_annotated`; no detector, preview-coordinate inference or EXIF adapter |
| `anchor` | Optional; when present, described reference object, two distinct observed endpoints, independently verified positive measured length in metres, tolerance smaller than length, and provenance |
| `scale_check` | Optional; acceptance requires another independently verified positive measured reference dimension, two existing endpoints and provenance. It cannot reuse the same fitted endpoint pair |
| Reference versus boundaries | Reference/check endpoint IDs must be separate from room boundary IDs; evaluation tape dimensions cannot be supplied as room-edge scale inputs |
| `floor_corners` | Four distinct observed IDs, ordered around a visible confirmed rectangular floor. First edge defines `length_m`, next defines `width_m`; no assumption that length is the larger dimension |
| `ceiling_corners` | Four matching observed IDs directly above corresponding floor corners; not an arbitrary ceiling plane |
| Rectangle/height confirmation/provenance | Explicit observed rectangular footprint and constant-height assertion. Absent/unconfirmed/nonrectangular/sloped/incomplete cases are unavailable in this narrow adapter |
| `policy` | Explicit minimum point triangulation angle, maximum point reprojection error, relative scale-check error, shape error and explored sensitivity. All are required development choices |

This shape restriction is an adapter acceptance condition, not an assumption that the user's actual room is rectangular. The app must ask or reject when the real geometry does not meet it. Nonrectangular/sloped/full-area interpretations remain M09 decisions.

## Calculation and integrity

Verify the reconstruction result SHA, saved request fingerprint, sweep, full selected-frame ledger, original-image hashes, synthetic label and M03b1 single-component quality gate. Require all five native binary files (`cameras`, `images`, `points3D`, `frames`, `rigs`) in the hash ledger and validate their bytes within the reconstruction directory. Parse the pinned native model, require every selected view to have a pose, and verify `PINHOLE` parameters/resolution against the supplied fixed calibration. Estimated intrinsics, unexpected camera/zoom/resolution/orientation or native calibration mismatch cannot produce room metrics.

For each point, unproject its observations into world rays with the calibrated camera and saved world-to-camera pose. Minimize the sum of squared perpendicular ray distances by solving `sum(I-ddᵀ) X = sum((I-ddᵀ) C)`. Reject singular/low-parallax input, unregistered views, out-of-bounds points, negative camera depth and excessive maximum per-view reprojection error. The maximum ray-pair angle is a quality gate, not confidence.

Compute metres/model-unit as known reference length divided by its triangulated endpoint distance. Compare the second known reference dimension after scaling; reject a failed check. Reference width can fit scale and reference height can serve as the independent check, provided it is independently measured. A good check does not prove absence of all model distortions elsewhere in the room.

Check floor right angles, opposite edges and coplanarity. Derive the floor normal and require matching ceiling vectors along it, positive heights and height agreement. Average opposite floor edges and four supported heights. Never move observed points onto a perfect rectangle to force a pass.

Explore reference-length tolerance extremes and each observed pixel coordinate's tolerance one at a time, recomputing affected points, anchor scale and room dimensions. Reject excessive relative movement. Save the explored dimension envelope with `confidence_bound=false`. **It excludes simultaneous pixel errors, intrinsic uncertainty, camera-pose uncertainty and calibration-model bias. It is neither a full worst-case interval nor a physical accuracy guarantee.** Output at 0.001 m is computational presentation precision, not promised millimetre accuracy.

## Results, packet and failures

Accepted dimensions produce three M01 `MeasurementEvidence` entries for room length/width/height, with saved frame references, scale method, input/reconstruction hashes and derivation. `room_input.json` retains annotations/reference/check/policy; `room_result.json` retains matrix-derived camera views, full reconstruction request/calibration, native artifact ledger, points, diagnostics, scale/check, sensitivity, stage and evidence. These saved views/input allow review of the dimension calculation. The native reconstruction files remain in the sibling `reconstruction/` directory rather than being copied into the portable packet.

`claim_packet.json`, `report.html` and original `frames/` are exported by M01, from the same accepted values. Bibliography/prices/items are not fabricated. Floor, wall and shelved-wall areas remain null. Complete room reporting is M09, and complete pipeline integration is M10. Retain the entire smoke directory for native reconstruction reproducibility, since the packet alone does not contain the binary model/database.

Missing calibration/reference/check/boundaries or invalid point/shape/sensitivity produces an unavailable metric stage, empty metric evidence and null dimensions with review errors. This adapter uses all-or-unknown feasibility semantics rather than publishing a partially validated room. Integrity/hash/sweep/native-ledger failures abort before export. Output directories cannot be overwritten. A late I/O failure can leave a partial export; atomic finalization is still M10 work. Hashes establish consistency with saved bytes, not a signed attestation against a person rewriting all local ledgers.

## Verification and artifacts

```powershell
.\.local\reference-env\Scripts\python.exe -B -m unittest discover -s tests
.\.local\reference-env\Scripts\python.exe -B scripts/smoke_room.py --output runs/m03b2-final-review
```

Full suite: **125 Python tests passed** (102 earlier + 23 new). Checks include independent point/room recovery; translation/arbitrary-scale invariance; absent/unverified reference; independent check absence/reuse/error; singular/low-parallax/incorrect/out-of-bounds/unregistered observations; missing boundaries/assertions; nonrectangle/varying/lateral ceiling; sensitivity; invalid schema; exact packet/evidence agreement and original portability; estimated intrinsics; changed result/request/model/original hashes; unqualified/incomplete model ledger; no overwrite. Integrity/export tests mock the native pose loader for the controlled boundary fixture; the smoke uses the actual native model. Existing Starlette/HTTPX warning remains. Unchanged browser Node tests were not repeated.

The actual smoke renders five independently specified synthetic textured views with visible reference and room-corner wireframes. It gives the reconstruction only images and the independently specified pinhole intrinsics; no poses, matches, room dimensions or prebuilt model are supplied. It annotates rendered marker centres and uses only a **1 m reference width** and **0.5 m reference height check** at runtime. The known room dimensions/scene/camera truth are saved separately for evaluation and never read by the measurement CLI.

| Dimension | Synthetic truth | Raw recovered value | Packet value |
| --- | --- | --- | --- |
| First floor edge | 3 m | 3.0001011 m | 3.000 m |
| Next floor edge | 4 m | 4.0001676 m | 4.000 m |
| Constant height | 2.6 m | 2.6000719 m | 2.600 m |

Each raw relative error is below 0.005%; the smoke's development assertion is below 2%. The independent reference-height relative error was approximately 0.000444%. Native reconstruction worker elapsed approximately **14.72 seconds** for this fixture/machine, excluding total smoke setup/export time. No physical-room latency or accuracy claim follows from those figures. Exact values can vary slightly between native runs.

Review artifacts in `runs/m03b2-final-review/`:

- `store/`, `reconstruction-input.json`, `reconstruction/`: exact synthetic originals, calibrated request, actual CPU-native models/database/log/diagnostics.
- `room-input.json`, `ground-truth.json`, `smoke-errors.json`: runtime annotations/reference inputs, separate evaluation truth and exported-dimension error table.
- `packet/room_input.json`, `packet/room_result.json`, `packet/claim_packet.json`, `packet/report.html`, `packet/frames/`: portable frame/packet review plus detailed calculation evidence.

One synthetic original frame was visually inspected; its labeled reference points and corner wireframes are visible. Report/packet and original-byte agreement were checked programmatically. Browser rendering of the report was not newly smoke-tested. No real camera, room or lens-calibration profile was used.

## Remaining gate and review stop

Camera-calibration acquisition preference is pending. Neither guided camera calibration nor a physical calibrated device has been demonstrated. Actual acceptance still requires a real same-sweep reference/room capture, independent held-out spine/room tape truth, per-dimension/area error and end-to-end timing. Both the spine ≤15% and room-area ≤15% brief bars remain **not measured**. Full areas are not implemented in this part. An actual second/held-out room configuration is also pending.

M03a/M03b now have narrow synthetic feasibility implementations, with physical acceptance still open. M04a one-shelf detection/counting is the proposed next modular part after user review. Do not represent the project as physically validated or proceed automatically. If the selected device cannot supply calibrated connected geometry, record that limitation and review a path change rather than invent measurements.

**Awaiting user review.**

