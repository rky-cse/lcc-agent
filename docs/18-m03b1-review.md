# M03b1 review: saved-sweep sparse reconstruction

Status on 10 October 2026: implemented under the user's latest "next". M03b was split to keep each review small. This part implements CPU sparse reconstruction and connectedness checks only. M03b2 scale recovery and room-boundary/height feasibility has not started. **Awaiting user review.**

## Outcome and boundary

Selected immutable frames from one sweep are handed to an isolated PyCOLMAP worker. It extracts/matches features and estimates camera intrinsics, poses and sparse 3D points from the actual image bytes. It records whether every selected frame registers into one component with sufficient support, reprojection quality and triangulation angle. It never accepts just the largest component while hiding unregistered views.

A successful result is `connected_provisional`: all reconstruction coordinates remain in arbitrary units. The result explicitly sets `measurement_status` to `unavailable`, and every room dimension/area remains null. A successful `sparse_reconstruction` stage means the connectivity gate passed, not that the room measurement acceptance bar passed. Estimated intrinsics, sparse feature support and selected-view connectivity do not establish full-room coverage, lens calibration, physical accuracy or a metric anchor. Reference dimensions, actual room shape and wall conventions were not assumed.

The split follows the existing design's RGB multiview path. [COLMAP's tutorial](https://colmap.github.io/tutorial.html) describes overlapping translated views, sparse reconstruction and estimated cameras; it also cautions against textureless/specular surfaces and rotation-only capture. The official [PyCOLMAP documentation](https://colmap.github.io/pycolmap/index.html) provides the CPU Python interface and Windows wheel installation. Actual API signatures/options were inspected in the pinned installed version before implementing the adapter.

## Files and dependencies

| File | Responsibility |
| --- | --- |
| `library_claim/reconstruction.py` | Typed request/policy, immutable-frame handoff, deadline, stage/results and connectivity gate |
| `library_claim/reconstruction_worker.py` | Optional native feature extraction/matching/mapping, model persistence and diagnostics |
| `requirements-reconstruction.txt` | Optional pinned PyCOLMAP/NumPy runtime |
| `pyproject.toml` | Optional `reconstruction` extra; base dependencies unchanged |
| `tests/test_reconstruction.py` | 20 handoff/gate/lifecycle/error tests |
| `scripts/smoke_reconstruction.py` | Actual CPU image-to-model, textureless and deadline smoke modes |

Installed into `.local/reference-env`, the existing isolated development environment: **PyCOLMAP 4.2.1 and NumPy 2.5.3**, using binary wheels. The initial package-index lookup hit the network sandbox; the lookup/install succeeded through the required escalated command flow. `pip check` reports no broken requirements. Neither optional library is imported by the base app/capture/planar module. No reference app tests were run, and no model API or key is used.

This part reuses this project's `FrameStore`, typed stage/room contracts and numeric JSON serializer. It adds an established reconstruction backend instead of copying reference claims or implementing an unverified solver from scratch. No upstream reference code/credentials were copied. PyCOLMAP/NumPy license notices are distributed with their installed packages; any eventual redistributed package must retain applicable notices.

## Input, processing and acceptance policy

An exact synthetic request is `runs/m03b1-textured-smoke/input.json`.

| Input | Required meaning |
| --- | --- |
| `sweep_id` | All selected stored frames must belong to this sweep |
| `frame_refs` | 3–12 distinct saved capture IDs. Their originals are reopened/rehashed. At least three byte-distinct images are required |
| `same_camera_and_zoom_confirmed` | Affirmative caller assertion that the selected views share one camera/fixed zoom; not automatically inferred |
| `camera_provenance` | Nonblank basis for that assertion |
| `policy.max_runtime_seconds` | Explicit worker deadline, 1–180 seconds, including startup/feature/matching/mapping/diagnostics |
| `policy.min_points3d` | Minimum reconstructed support count |
| `policy.max_median_reprojection_error_px` | Maximum median per-point native reprojection error in original encoded-pixel coordinates |
| `policy.min_median_triangulation_angle_deg` | Minimum median of each point's largest observed ray-pair angle; heuristic depth-support gate, not uncertainty |

The smoke's thresholds (120 seconds, 100 points, 2 pixels, 2 degrees) are labeled development inputs, not empirically calibrated production thresholds. The three-frame minimum is necessary for this adapter; it does not guarantee a reconstructible or complete room.

Different encoded resolutions, EXIF rotation and unconfirmed camera/zoom yield an unavailable result before invoking the backend. Orientation/variable-camera adapters are deferred. Equal-sized frames and fixed zoom alone cannot verify intrinsics or lens behavior.

The worker uses one shared `SIMPLE_RADIAL` camera, estimates intrinsics, performs CPU SIFT/exhaustive matching and incremental sparse mapping. It uses two threads, a 1600-pixel extraction limit, up to 4096 features per image, deterministic mapping seed 0, minimum model size 3, at most four candidate models and native geometric initialization defaults. The input copies retain exact original bytes/resolution; extraction resizing is an internal feature-processing setting. Native defaults were not tuned to the synthetic truth. Dense depth/meshing, metric scaling, automatic room-boundary annotation and packet integration are outside this part.

The native library runs in a child interpreter, with `shell=False`. The outer subprocess deadline kills/waits for the worker if it exceeds the budget; native crashes/nonzero exits produce a failed stage and retained log. A backend timeout is a failure, not a successful partial room. Missing optional environment produces an unavailable stage. The application does not call this synchronous CLI from an HTTP/audio handler; asynchronous scheduling remains future integration work.

## Outputs and failure semantics

| Artifact | Contents |
| --- | --- |
| `request.json` | Exact request, policy and camera assertion |
| `frames.json` | Saved-frame mapping, hashes, sequence, capture time and synthetic labels |
| `images/` | Exact saved originals under stable hash-derived names |
| `features.db` | Native feature/match database when processing ran |
| `backend.log` | Worker startup/native processing/error output |
| `sparse/<component>/` | Native binary and text reconstruction files; result ledger hashes persisted files |
| `worker-result.json` | Backend/library versions, CPU settings, registered names, point count, median diagnostics and camera centres in arbitrary units |
| `reconstruction_result.json` | Fingerprint, structured stage timing/warnings/errors, provisional/unavailable/failed status, native summary, artifact hashes and null room metrics |

Missing/tampered/wrong-sweep evidence fails before the geometry job is exported. Valid evidence with missing support, multiple components, any unregistered selected frame or failed diagnostic gates yields `unavailable`, retaining the selected frame ledger. Malformed/missing/oversized worker summary, crash or timeout yields `failed`. Candidate files left by failed/timed-out work are diagnostic remnants, not accepted geometry. Export refuses an existing output directory. A filesystem failure during output can leave an incomplete directory; atomic finalization remains M10 work.

## Tests and actual smoke evidence

```powershell
.\.local\reference-env\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-reconstruction.txt
.\.local\reference-env\Scripts\python.exe -B -m unittest discover -s tests
.\.local\reference-env\Scripts\python.exe -B scripts/smoke_reconstruction.py --output runs/m03b1-textured-smoke
.\.local\reference-env\Scripts\python.exe -B scripts/smoke_reconstruction.py --blank --output runs/m03b1-textureless-smoke
.\.local\reference-env\Scripts\python.exe -B scripts/smoke_reconstruction.py --expect-timeout --output runs/m03b1-timeout-smoke
```

Full Python suite: **102 passed** (82 previous + 20 M03b1). Tests cover provisional/metric-null semantics; exact immutable handoff; no/multiple components; missing/duplicate/foreign registrations; insufficient support; reprojection/low-parallax/nonfinite gates; camera assertion/resolution/orientation; absent backend; duplicate bytes; timeout/crash/malformed summary; wrong sweep; tampered original; fresh-output requirement; bounded schema. These unit tests mock the native worker only to exercise lifecycle/error boundaries; they do not establish native reconstruction accuracy. The existing Starlette/HTTPX test warning remains. Browser code is unchanged; its previously passing nine Node tests were not rerun.

Three actual CPU-native CLI smoke runs passed:

| Synthetic input | Actual backend/result | Metric claims |
| --- | --- | --- |
| Five translated pinhole views of independently generated textured patches at varied depths | One component, all 5 images registered, 4066 sparse points, median reprojection error 0.1974 px, median maximum ray-pair angle 10.6119°, worker elapsed 14.83 s | All room dimensions/areas null |
| Three byte-distinct textureless images | No model, `unavailable`; saved evidence retained | All room dimensions/areas null |
| Textured fixture with 1-second deadline | Actual worker terminated; `failed` / `backend_timeout`; output/log retained | All room dimensions/areas null |

The textured fixture supplies only saved PNG images to the backend, without known poses, correspondences or a prebuilt reconstruction. The analytic scene and camera truth are saved separately in `ground-truth.json` and never read by the worker. This smoke validates real feature/matching/mapping execution and connectivity, not metric room recovery or comparison against the brief's accuracy bars. The timeout smoke expects this fixture to exceed one second on the test machine; a much faster future machine may need a separate deadline fixture.

Artifacts are in the three `runs/m03b1-*-smoke/` directories, each with `input.json`, independent synthetic truth, `store/` and `reconstruction/`. They are Git-ignored and reproducible. The positive run saved 10 hashed binary/text model files. A successful rerun may differ slightly due to native numerical/thread behavior despite the fixed seed; timing is specific to this machine and dataset.

No Gemini/Groq calls, uploads to providers or provider charges were incurred. No physical camera or actual room was tested. The earlier real capture/calibration gates remain pending. Rotation-only failure is covered by a low-triangulation diagnostic unit test; an actual rotation-only camera dataset has not been tested.

## Review stop and next small part

M03b1 now supplies a concrete reconstruction boundary for M03b2. The next part must recover an evidenced metric anchor in this same reconstruction, validate its scale independently, and map observed room corners/height with uncertainty/completeness checks. It must reject disconnected/unsupported boundaries and must not inject evaluation tape dimensions as runtime geometry. The user's specified agent-led reference-object/dimension intake remains M06 integration work.

M03b's physical acceptance gate still requires actual translated overlapping views from the selected device, a verified same-sweep anchor, observed room boundaries/height, independent ground truth, error/latency results and a held-out case. Synthetic connectedness cannot satisfy that gate. If the path fails on the actual room, record the failure and review capture/path options rather than infer a typical room.

**Awaiting user review. M03b2 and M04 have not started.**
