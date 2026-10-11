# Capture and metric measurement design

[M06b](29-m06b-review.md) connects spoken/typed reference proposals to explicit browser review of M06a declarations. A guidance-ID camera link uses the confirmed locale and same session ID; the existing camera page still requests permission explicitly. Manually sending a resized saved-frame preview preserves the verified original. No automatic camera scheduling, geometric validation or metric readiness follows from conversation.

[M06a](28-m06a-review.md) implements the typed reference-intake question and explicit measured/unknown/skip declarations. It asks actual centimetre dimensions, tolerances and provenance without assuming standard object sizes. A ready capture declaration is not geometric calibration; metric readiness stays false. Same-plane reference evidence and verified camera intrinsics remain separate geometry requirements. Spoken intake is pending M06b.

Status: laptop localhost selected; Android remains a later check. No LiDAR; agent asks for reference-object dimensions during calibration. M03a planar spine, M03b1 sparse reconstruction and M03b2 calibrated annotated room dimensions are implemented with synthetic checks. Physical accuracy and actual camera calibration remain unproven. Earlier real camera smoke remained pending. See [M02b](16-m02b-review.md), [M03a](17-m03a-review.md), [M03b1](18-m03b1-review.md) and [M03b2](19-m03b2-review.md).

## One-sweep capture protocol

Preflight occurs before starting the timed pass: verify country/currency, rear camera and microphone, actual stream resolution, storage, provider connection, and the selected scale mechanism. Ask whether there are ownership exclusions and warn that people/private documents must stay out of view. The agent gives short instructions to move across each shelf with overlap, then cover room corners, walls and floor boundaries during the same pass. No separate measurement pass is introduced.

Keep speech short enough to act on: "Slow down on the upper shelf" or "Tilt slightly; there is glare". A quality monitor triggers these from recent saved frames. A room/shelf coverage ledger records observed, partial, poor-quality, excluded and not-observed regions. Unknown total shelf count is explicit; coverage is not proof that hidden shelves/books do not exist. The agent can ask the claimant if another shelving unit is present, but such an assertion is not a visual measurement.

During the pass, capture a legible front view and overlapping translated views as appropriate for the chosen geometry. Horizontal stacks and recesses need close/oblique views without moving books. At completion ask whether all intended shelves were covered, then close capture deliberately. A short in-pass recapture is allowed; pulling books or individual item scans is prohibited.

Save high-resolution keyframes with original coordinates before recognition. Frame selection considers sharpness, glare, coverage novelty and overlap. Numerical thresholds and keyframe rate are configured only after the actual device test; no guessed blur score guarantees readability. A keyframe that will be cited must be acknowledged only after durable storage. Preserve video evidence if required by the selected reconstruction path and available storage.

Ordinary mobile camera access requires a secure browser context; PC `localhost` does not make a phone's LAN HTTP address secure. The first target is laptop localhost. Resolve trusted HTTPS/local forwarding when Android testing is requested, without making it a prerequisite for laptop implementation. [MDN getUserMedia documentation](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).

## Scale alternatives and early gate

For the selected browser/no-LiDAR path, use a known reference on the shelf plane for spine calibration. Whole-room metrics require a connected multiview reconstruction from translated, overlapping views in that same sweep, scaled by an evidenced reference. This is the high-risk M03 experiment, not a promise of successful room measurement. Depth alternatives below remain recorded for design history but are not the implementation path. A reference object must have verified physical dimensions; do not assume the dimensions of an arbitrary object, paper size or unverified printout.

| Path | Evidence required | What it can support | Feasibility decision |
| --- | --- | --- | --- |
| Supported depth/pose capture | Synchronized RGB/depth, intrinsics, transforms, depth confidence and tracking; proven device support | Room plane geometry; RGB-defined spine boundaries mapped to metric shelf plane | Best candidate if hardware/tooling exist; native capture may exceed timebox |
| Known planar marker/shelf measurements | Verified metric dimensions, visible correspondences, same-plane relationship and fit residual | Spine measurements on that calibrated plane | Plausible browser path; not sufficient alone for unrelated room planes |
| Marker + multiview reconstruction | Stable anchor, translated overlapping images, connected camera poses, global scale and reconstruction quality | Potential common room/shelf geometry | High-risk experiment; decide early rather than assume it works |
| Evidenced standard book format | Proven edition/format and documented dimensions | Weak local scale corroboration | Brief allows it; cannot silently infer exact format or guarantee room area |

A measured shelf width alone cannot be converted into room length/width/height with a pixel ratio. A floor marker does not directly scale shelf spines at a different depth. Claimant-supplied known shelf/reference dimensions may be evidenced calibration inputs where allowed; they do not substitute for room boundaries/dimensions derived from the same sweep. Ground-truth room tape measurements are evaluation-only and must not become runtime outputs.

Apple RoomPlan and sceneDepth are conditional options requiring suitable Apple hardware and tooling. ARCore Depth support varies by device, and RGB/depth registration must follow its calibrated mapping. WebXR's specification describes metric depth but does not establish support on the user's browser. Verify each exact capability before choosing it. [Apple RoomPlan](https://developer.apple.com/augmented-reality/roomplan/), [Apple sceneDepth](https://developer.apple.com/documentation/arkit/arconfiguration/framesemantics-swift.struct/scenedepth), [ARCore Depth](https://developers.google.com/ar/develop/java/depth/developer-guide), [WebXR Depth specification](https://www.w3.org/TR/webxr-depth-sensing-1/).

## Planar spine measurement

Detect spine polygons on high-resolution RGB. Correct orientation and lens distortion where calibration is available. Obtain metric correspondences on the actual shelf/spine plane; four or more non-collinear correspondences support a planar homography. Record which correspondence points came from which frame and measured reference. Fit robustly, evaluate residuals and reject degenerate geometry. [OpenCV homography tutorial](https://docs.opencv.org/4.x/d9/dab/tutorial_homography.html).

After rectification, measure height along the spine's long axis and thickness along its short axis, irrespective of upright/flat orientation. Record the polygon, rectification transform, endpoint method, scale tolerance and confidence. Books at notably different depths or with curved/cropped spines need separate validity checks; do not extend one planar calibration beyond its evidence.

A simple ratio `object_cm = reference_cm × object_pixels/reference_pixels` is valid only with controlled perspective and coplanarity. Standard-format corroboration must identify the exact edition/format and preserve source dimensions. Neither an LLM estimate nor a typical book-size prior is an independent measurement.

## Depth/pose measurement

For optical-axis depth with camera intrinsic matrix K, reconstruct a sampled camera point as `P_camera = z K⁻¹[u,v,1]ᵀ`, then transform by `T_world_camera`. Other depth conventions require the appropriate calibrated projection. A dimension is the Euclidean distance between supported 3D endpoints, converted to the required unit.

Fit a shelf plane robustly from valid depth samples and intersect high-resolution RGB boundary rays with that plane. Thin spine edges should not use isolated mixed-depth pixels from adjoining objects. Keep plane residuals, sample counts, tracking quality and depth uncertainty. Lost poses or disconnected coordinate frames cannot be merged as if they share one metric room.

## Room geometry

M03b1 provides optional CPU sparse reconstruction with selected-frame connectivity/quality gates; its coordinates remain in arbitrary units. M03b2 now uses verified fixed pinhole intrinsics, an observed metric reference plus independent check, and developer multiview floor/matching-ceiling corners to measure a confirmed rectangular constant-height room. Synthetic native smoke passed; actual room/device calibration and accuracy remain unverified. Estimated-intrinsic reconstruction cannot produce metric dimensions. How setup obtains actual camera calibration is pending user preference. Sparse connectivity alone cannot establish coverage/accuracy; full areas remain M09.

Detect/fit floor and wall boundaries in the same saved capture. Maintain a closed footprint and measured ceiling heights. Occluded corners, textureless/glossy surfaces and missing ceiling views must remain unresolved rather than be filled from a "normal room" assumption.

For a confirmed rectangle, `floor_area_m2 = length_m × width_m`. With constant height H, gross wall area is `2(length_m + width_m) × H`. For a closed polygon, floor area uses `abs(sum(x_i*y_(i+1) - x_(i+1)*y_i))/2`; gross wall area is perimeter × H only when constant height is supported. Irregular/sloped walls use measured polygons/segments and a height profile. Declare polygon vertex order, coordinate system, closure residual and room-shape interpretation.

For a nonrectangle, proposed required length/width are bounding extents with `dimension_interpretation` and footprint vertices added. Ceiling height is null when a single height would conceal variation; add observed heights. This convention needs approval.

Proposed shelving coverage is the union of shelving front-elevation footprints projected onto each wall and clipped to its boundary. Overlapping shelving cannot be counted twice. It is a separate area and is not automatically subtracted from total wall area. Confirm whether the required wall area is gross or excludes door/window openings; optionally report both when supported.

Convert every supported m² value to ft² using `10.7639104167 ft²/m²`, computed in code. Do not calculate an area from partially unknown dimensions. Report measured partial area separately and make total unknown.

## Shelf run

Three different quantities must not be confused: sum of spine thicknesses, occupied horizontal shelf span and physical usable shelf length. Proposed required `shelf_run_m` is the sum of all physical-book spine thicknesses divided by 100, including horizontal books. Occupied horizontal run and physical shelf length are separate measurements when available. Missing thicknesses mean the full sum is unknown; expose measured subtotal and coverage. Confirm this interpretation before M01/M03.

## Uncertainty and failure gates

M03a's implemented single-frame reference-object adapter is described in [its review record](17-m03a-review.md). It requires developer annotations, explicit physical dimensions/tolerances, same-plane/lens-validity declarations and independent check observations. The user specified agent-led reference-object intake during calibration; M06 will implement that interaction. Its explored perturbation envelope is sensitivity, not a confidence interval. M03b1/M03b2 are implemented with native synthetic smokes; physical room and spine acceptance remain unverified.

Track reference tolerance, corner localization, reprojection error, depth noise, plane-fit residual, pose drift and boundary visibility. A uniform scale error e changes area by `(1+e)^2-1`; a 5% scale error gives 10.25% area error. Hence accurate room area needs tighter scale control than the 15% spine dimension bar.

Publish numerical uncertainty only when it has a defensible computation or empirical calibration. A model's `0.95` statement cannot imply a 95% measurement guarantee. Keep heuristic quality scores labeled as such. Propagate scale/endpoints through dimension and area calculations, and expose completeness independently of confidence.

Reject metric output when scale is absent, correspondences are degenerate, geometry is disconnected, tracking is lost, boundaries are unresolved, or reference/object coplanarity is unsupported. Continue with observed inventory and explicit review reasons; missing measurement is a failure against the measurement pass bar.

Multiview reconstruction needs overlap, translation and texture. A stationary panoramic rotation is insufficient for reliable triangulation; textureless walls and specular surfaces are problematic. This is a design risk supported by capture guidance, not a tested result for this room. [COLMAP tutorial](https://colmap.github.io/tutorial.html).

## M03 feasibility acceptance

Before investing in broader recognition, demonstrate on the actual device: reopen saved readable shelf evidence; recover a scale anchor with provenance; measure held-out spine height/thickness against independent tape/caliper values; obtain a connected room footprint and height from the same sweep; quantify errors and latency. Test another shelf/room configuration rather than calibrating output to one space. If room geometry is not feasible, present that measured limitation and a concrete device/path change for user review. Do not quietly replace measured area with a model estimate.

## M09 implementation update

M09 now implements observed simple planar footprints, floor-normal wall profiles, per-wall projected shelving union, opening union subtraction, m²/ft² and explored pixel/reference sensitivity. Explicit per-run choices handle gross/net area, first-edge-aligned extents versus unknown dimensions, and constant-only versus unknown height. Unobserved boundaries stay unknown; physical coverage and camera/pose uncertainty remain unverified. This path requires reviewer annotations rather than automatic room corners. See [M09 geometry and limitations](43-m09-group-review.md).
