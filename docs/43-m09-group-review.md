# M09 — Observed room, wall and shelving areas

The entire M09 implementation group is complete for review. The user's `next` authorized this group; the revised workflow requires a stop after the whole module and skips smoke tests. M10 has not started. No browser/device/reference/provider/source smoke test was performed, no paid operation was used, and no secrets were read or copied.

## Scope and components

| Part | Implementation | Result |
| --- | --- | --- |
| M09a | `library_claim/areas.py` | Typed observed surfaces, arbitrary simple planar footprints, piecewise wall tops, explicit interpretation, gross/net areas |
| M09b | Same geometry module | Per-wall projected shelving union, boundary clipping, overlapping opening union, net coverage subtraction |
| M09c | Same module and `area_store.py` | Metric/imperial output, explored sensitivity, partial/unknown fields, durable provenance and revision guards |
| M09d | `server.py`, `web/areas.html`, `areas.mjs`, `areas_core.mjs` | Explicit request/review, archived result reopening/download, sweep/contents binding and same-origin controls |

`tests/test_areas.py`, `tests/test_area_store.py` and `tests/areas_core.test.mjs` cover this group. Existing capture/measurement/packet infrastructure is reused rather than duplicated. The reference app's insurance-policy tools, avatar/sketch paths and in-memory measurements are unnecessary here and are not brought into M09.

## Architecture and trust boundary

Saved frames → M03 reconstruction → M03 original/native-model hash checks → independently verified fixed pinhole camera views → observed point triangulation → independent reference scale/check → floor/wall/shelf polygons → clipped unions/areas → sensitivity gates → durable M09 result.

`room_measurement.verified_model` checks the pinned reconstruction result, saved reconstruction request, connected selected-frame ledger, copied original bytes and all required native model hashes. `calibrated_views` checks the pinned PyCOLMAP environment, camera identity/resolution/orientation, verified fixed intrinsics and posed selected frames. `room_geometry.triangulate` supplies correspondence, pixel bounds, parallax and reprojection checks. These are used directly; existing M03 rectangle-only requests/results continue to work unchanged.

The server accepts only a reconstruction directory **relative to its frame store**, resolved beneath that store. Absolute paths, parent traversal and resolved directory escapes fail. Originals/native artifacts are reverified on saved-result reads. Results are canonical JSON blobs with SHA-256 in the frame-store SQLite database. Different payloads cannot reuse a run ID; exact retries reopen the existing result. Results carry the frozen non-book contents revision and inventory hash. A changed ledger makes the old result stale; a change during computation prevents the result commit. No silent rebase occurs.

Shelving surfaces must name current reviewed `shelving_unit` physical IDs. Every corner must have a saved observation inside that item's reviewed bounds in at least one matching original frame; its 3D position still requires at least two connected observations. This binds the geometry to the reviewed physical object but is not automatic corner identity verification. `shelving_coverage_complete=true` requires all current reviewed shelving units to be represented. Set/component valuation suppression and ownership do not remove physical shelving from the explicitly selected `all_reviewed_physical_shelving` area basis.

## Geometry and explicit conventions

- A floor is an ordered, closed simple polygon, with no repeated first vertex, missing point references, zero edges, self intersections or self touching. It must be planar within the entered metric tolerance. Concave footprints are supported. The floor area is its shoelace area; no hidden rectangle is fitted.
- A local floor frame uses the first floor edge as the first axis. `dimensions=first_edge_aligned_bounding_extents` yields extents in that frame; `unknown` leaves length/width null. This is a per-run decision, not approval of a global nonrectangle convention.
- Each floor edge identifies one wall index. A wall polygon starts with the two corresponding ordered floor corners, then follows the observed top from the far end back to the near end. Tops may have intermediate vertices, slopes and varying heights. Wall elevations must lie in the plane spanned by that edge and the floor normal. This supports planar upright wall faces, not arbitrary tilted/curved walls, nonplanar floors, multiple disconnected rooms or floor holes.
- Heights are distances normal to the measured floor plane. `height=constant_only` publishes one height only when every wall is present and the observed top-height spread fits the entered plane tolerance. Varying heights remain in `height_samples_m`, and the scalar stays null. `unknown` always leaves scalar height null. No gravity sensor or typical ceiling height is assumed.
- `wall_area_basis=gross` uses wall-face polygons; `net` removes the union of observed opening polygons clipped to each wall. Overlapping openings are deducted once. Net totals require `openings_complete=true`. Opening vertices outside the wall beyond the declared metric tolerance fail; small tolerance-scale boundary deviations are clipped and their area is reported in `opening_clipping_m2`.
- Shelving fronts must be planar and parallel to their declared wall within the entered tolerance. Their maximum orthogonal distance from the wall is explicitly bounded by `max_wall_projection_distance_m`. Orthogonal projection onto the wall yields a front-elevation polygon, which is clipped to the wall. Intersections and overlapping faces are unioned once. On the net basis, opening unions are removed from that coverage. Shelving never automatically reduces wall area.
- The polygon union uses a vertical sweep divided at every vertex and segment intersection. Within each slab, the selected cross-section length is linear, so its midpoint integral gives the area. This handles concave boundaries and crossed edges between distinct polygons without a new external geometry dependency. Invalid individual polygons fail.

Coordinate/plane thresholds are required reviewed inputs. They are engineering acceptance gates, not validated accuracy/confidence thresholds. Metric reference and scale-check endpoints are separate from all surface points, and the check cannot reuse the fitted anchor pair. No model/catalogue dimensions are substituted for observed geometry.

## Output, coverage and uncertainty

`room` retains the M01 fields: length/width/height, floor/wall/shelved-wall m², scale method and null confidence. `measurements` provides packet-compatible evidence for each known room field, including frame references and input/reconstruction hashes. M09 does not assemble or finalize an integrated claim packet.

`geometry.area_units` provides m² and ft² for full area fields. `partial` and `partial_area_units` expose measured subtotals separately, never as complete room totals. The conversion uses exactly 0.3048 metres per international foot; square metres divide by 0.3048². Computation uses floating-point geometry and Decimal conversion/half-even rounding to six decimal places. Display precision is not physical measurement precision.

Complete floor area requires the reviewed closed-floor completeness declaration. Full wall area also requires one measured wall per footprint edge, and net results require opening completeness. Full shelving area additionally requires shelving completeness and representation of all current reviewed physical shelving IDs. An empty reviewed shelving inventory may yield zero only with that explicit completeness declaration. Missing geometry produces null, with known floor/subtotals retained when possible. Invalid calibration, correspondences or geometry yields an archived `unavailable` result with null room fields; reconstruction/ledger integrity failures abort instead of publishing trusted results.

`sensitivity` and `partial_sensitivity` explore reference length ± its entered uncertainty, then each observed pixel coordinate ± its entered corner tolerance one at a time, including anchor endpoint movement. Every trial recomputes the geometry and unions. Known-field null transitions, invalid trial geometry, excessive relative changes and a zero-to-positive transition beyond computational precision fail. Full area envelopes also have metric/imperial unit projections. These are explored envelopes, **not confidence intervals or guaranteed error bounds**. Camera pose/intrinsic uncertainty, simultaneous errors, reference misidentification and incorrect correspondence assertions remain outside this exploration.

`status` is `success` when all three area totals are known, `partial` when some are unknown, and `unavailable` for measurement failure. `stale` and `usable_for_current_inventory` are recalculated on read. `coverage.physical_room_coverage_verified=false` and `packet_ready=false` remain explicit even for a successful computational result.

## Operating the module

1. Restart the existing local server with its usual configuration to load M09, keeping the same frame store. Capture and reviewed physical contents are prerequisites. No provider is needed for M09 computation.
2. Produce a qualified M03 reconstruction from selected originals in that same sweep, with independently verified fixed camera calibration. Set its output inside `<store>/models/<bundle>`, or copy the existing verified reconstruction directory there without changing its metadata/artifacts. Do not generate a new model merely to open the review page.
3. Open `/areas`, enter the saved sweep ID and load its current contents revision. Choose **Prepare a request template**. The template deliberately leaves evidence and interpretation gates unset; required choices cannot silently default.
4. Fill the request using the structures below. Enter the SHA-256 of the exact `reconstruction_result.json` bytes and `reconstruction_path=models/<bundle>`. Match the loaded contents revision. Annotate encoded original pixel coordinates, not scaled preview coordinates. Review all completeness declarations, plane/projection tolerances and sensitivity gates.
5. Calculate explicitly. Review status, unknown fields, source references and downloaded detailed geometry/sensitivity. Reopen a saved run ID after restart to inspect the same archived result. Corrections require a new run ID and the current contents revision.

Point format:

```json
{"id":"floor0","observations":[{"frame_ref":"frame-FIRST","pixel":[310,700]},{"frame_ref":"frame-SECOND","pixel":[285,690]}],"corner_tolerance_px":0.5,"provenance":"Reviewer identified the same visible floor corner in both originals"}
```

Wall/opening format (the corner IDs must already exist in `points`):

```json
{"id":"wall0","wall_index":0,"corners":["floor0","floor1","top1","top0"],"provenance":"Observed floor edge and matching wall top"}
```

Shelving format:

```json
{"id":"shelf-front","item_id":"reviewed-shelf-ID","wall_index":0,"corners":["shelf0","shelf1","shelf2","shelf3"],"provenance":"Observed front face of the reviewed physical shelving unit"}
```

The complete, generated input contract is available read-only at `/api/areas/schema`. Reference/check formats reuse M03 contracts. Geometry policy retains the M03 triangulation, reprojection, independent-scale-check and sensitivity gates; M03's rectangle-only relative shape threshold is replaced by the explicit M09 metric plane/projection tolerances. The width/height of a reference object must be supplied and independently measured by the user; neither the page nor the calculation assigns standard-object dimensions.

Equivalent CLI (paths are examples to replace with this server's actual store and reviewed input):

```powershell
.local/reference-env/Scripts/python.exe -B -m library_claim.area_store --store runs/capture/store --input runs/reviewed-area-request.json --output runs/reviewed-area-result.json
```

The CLI uses the same store/gates and refuses to overwrite an existing output file. HTTP writes retain the existing origin/host/body-size guards and a shared local computation slot; visiting the page, loading the schema or reopening results does not schedule recognition, reconstruction or provider calls.

## Verification and limitations

Automated checks cover independent 3×4×2.6 m rectangle truth, trapezoid and concave L-room truth, a sloped and intermediate-vertex ceiling, absent floor/wall/completeness, explicit unknown interpretations, exact international-foot conversion, overlapping/clipped shelf faces, overlapping openings, net shelf subtraction, invalid polygons/planes/scale/sensitivity, reviewed shelving completeness/identity bounds, original model tampering, archived-result tampering, restart/exact replay, changed-payload rejection, stale contents, safe paths, HTTP scope/origin and browser request/unknown presentation logic.

Verification results: **527 full Python regressions passed** (170.594 seconds), followed by **32 focused M09 Python checks passed** after the final area/schema refinements. **66 Node tests passed**, including three new M09 cases. Both new browser modules passed syntax checks and git diff whitespace checks passed. The existing Starlette/HTTPX deprecation warning remains. Further smoke tests were skipped at the user's request. Tests use controlled synthetic observations; native-pose loading is mocked in persistence/HTTP fixtures while the existing M03 integrity gate is exercised against fixture originals and hashed mock native bytes. No real-room detection, physical calibration acquisition, actual tape comparison, browser visual check, provider/source coverage, held-out error ≤15% or physical timing claim follows from these tests. Automatic room/shelf corner acquisition remains unimplemented; this is reviewed annotated geometry.

**Awaiting user review. Next authorized module after approval: M10 final packet integration.**
