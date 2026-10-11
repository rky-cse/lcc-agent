# M04b2 — Assisted registration and association proposals

Status: implemented proposal core; **awaiting user review**. Registration landmark acquisition is still manual. Automatic image-feature registration, live proposal application and capture inventory UI are not implemented. This is a bounded step within M04b, not completion of its continuous physical-sweep acceptance card.

## Architecture and reuse

```text
reviewed M04b1 inventory revision + pinned current M04a detection bundle
  + same-plane/stable-position assertions and annotated view correspondences
  -> validated current-to-anchor projective transform
  -> spatial overlap graph + rectified image appearance checks
  -> matching_result.json and proposed_command.json
  -> explicit review -> existing M04b1 import command
```

`library_claim/matching.py` uses M04a's validated polygons/convex clipping, M04b1's source-bundle integrity and revision checks, FrameStore originals, and Pillow. `planar.fit_homography` now delegates to a reusable four-correspondence `fit_quad_transform`; the M03 metric calculation remains the same rectangle mapping. No extra dependency or reference transport changes. Reference title deduplication is unsuitable for identical physical copies and is not reused.

The proposer never mutates inventory and never emits `new`. Unmatched observations remain unresolved because nonmatch alone cannot establish novelty. Reviewed output uses the existing M04b1 command boundary; normal ledger revision/idempotency/ownership/evidence rules still apply.

## Input and validity

`MatchingRequest` requires sweep, expected revision, future import command ID, exact current detection-result SHA256, nullable registration, and explicit policy. Registration requires anchor frame/hash; four ordered convex current and corresponding anchor corners; at least two distinct independent holdout point pairs with provenance; same physical shelf, coplanar spines, unchanged physical positions and lens validity declarations; and provenance. Coordinate space is original encoded image pixel edges, not preview pixels or metric camera coordinates. All geometry points are finite. Calibration scale is unnecessary here; no dimensions or camera intrinsics are inferred.

Anchor must already be imported for the same shelf/sweep. Both immutable originals are checked, rotated EXIF needs an adapter, and source/anchor cannot be the same frame. Corner support must fit original bounds and meet configured area. Mapping must have no projective horizon within its convex support. Holdouts lie inside support, differ from fit corners/each other by more than configured check tolerance, and meet maximum anchor-pixel error. Reflected corner winding is rejected. Fit corners are operator-selected support boundaries, not necessarily detected book corners; holdouts must be independently annotated, not generated from an estimated transform in real use.

Absent or invalid declared registration produces an unavailable stage and all-unresolved proposals. Current detection integrity errors, stale revisions or reimport attempts fail before output. A missing frame/storage error also stops processing. Assertions and low residuals do not independently prove coplanarity, stable book positions or physical identity; shelves at different depths, changed books or unsupported lens effects require review/recapture.

## Matching algorithm

Current polygons must be wholly inside registration support; no extrapolation. They map into anchor coordinates. Every anchor candidate with polygon IoU above `plausible_iou` contributes an edge, including candidates outside support as ambiguity blockers. Only a single plausible edge with reverse degree one may be accepted. It must refer to an assigned track, have wholly supported anchor geometry, meet `accepted_iou`, have the same detector orientation, and meet appearance error threshold. Competing graph edges remain unresolved even if one has better appearance. Split/merged detections therefore do not get an arbitrary winning match.

Appearance is a 16×32 inset grid of RGB samples, rectified from each source polygon by projective mapping. Mean absolute channel difference is divided by 255. Samples are nearest original pixels; no OCR, title matching, learned descriptor or color normalization. This is a heuristic corroboration, not a probability. Corner-order differences, illumination and tight/cropped spines may cause false rejection. Same-looking replacements at the same location can fool appearance, so stable-position declarations and human review remain necessary.

Uncertain coverage blocks proposals globally. Model review polygons and unresolved regions block intersecting candidates; nonconvex reviewed geometry blocks conservatively instead of entering convex clipping. Non-book exclusions never become tracks. Missing anchor assignments remain unresolved. No track is deleted for being absent from a current view, and ownership does not affect physical matching.

All thresholds are required configuration. Smoke used check error 2 px, support area 10,000 px², plausible IoU 0.1, accepted IoU 0.7 and RGB MAE 0.1. These are synthetic development settings, not measured device operating thresholds or a production accuracy guarantee.

## Output, audit and review

`matching_result.json` includes typed StageResult, registration matrix/check residuals, every comparison/decision/reason, source hashes, baseline inventory hash, full request and unverified/provisional flags. Stage success means proposals computed without unresolved candidates, not verified identity. Unavailable/partial stages preserve explicit reasons. `new_tracks_created` is always zero; total book coverage remains unknown.

`proposal_sha256` hashes canonical result content excluding `stage_result` and the hash field itself. Timing diagnostics do not alter the proposed command on repeated calls against the same baseline. Command provenance references this proposal hash. Keep the matching directory for audit: M04b1 persists the command/hash and imported detection sources, but does not embed the full matching result. A future integrated job adapter must store proposal evidence alongside its automatic association event. Current output is explicitly `requires_review=true`; no unattended mutation adapter exists.

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_matching --output runs/my-m04b2-smoke
.\.venv\Scripts\python.exe -m library_claim.matching --store runs/my-capture --input registration-input.json --bundle runs/my-revisit-detection --output runs/my-match-proposal
# After inspecting/editing association decisions:
.\.venv\Scripts\python.exe -m library_claim.tracking --store runs/my-capture --command runs/my-match-proposal/proposed_command.json --bundle runs/my-revisit-detection --output runs/reviewed-inventory.json
```

Paths are placeholders and output directories must be fresh. CLI first writes results and then the proposed command; interrupted output may be incomplete. Regenerate against the unchanged baseline into a fresh directory. Existing ledger command retries remain idempotent. The synthetic smoke command applies fixture proposals automatically only as part of its separately labeled verification procedure.

## Validation

**181 Python tests passed**, including 18 new matching tests covering shifted revisits, identical copies, horizontal orientation, no proposer mutation, reviewed ledger application, missing registration, failed/reused holdouts, declaration/lens/reflection rejection, no extrapolation, unmatched book handling, split/merge graphs, changed appearance, orientation mismatch, uncertain coverage, overlapping unresolved regions, anchor hash mismatch, stale revision/current hash rejection, inverted policy thresholds, projective mapping/legacy metric equivalence, and stable retry payloads. `git diff --check` passed. Existing Starlette/HTTPX deprecation warning remains. Browser assets were unchanged; JavaScript checks were not repeated.

Actual smoke `runs/m04b2-final-review`: original synthetic shelf contains two identical upright copies and one horizontal book. A projectively warped revisit adds an extra book. Detection polygons and correspondence labels come from the renderer; no provider inference or automatic feature detection is claimed. Three same-book proposals and one unresolved observation matched all four fixture evaluation labels. Fixture truth is saved separately and not supplied to the matcher. Reviewed application retained three tracks and seven observations with one identity review. A separate process reopened the ledger with exact equality. Zero provider calls; total book count null. The saved warped original was visually inspected. Actual shelf precision/recall, identity merge/split accuracy and continuous capture remain unmeasured.

Artifacts: `smoke-summary.json`, `matching_input.json`, `fixture-truth.json`, `proposal/matching_result.json`, `proposal/proposed_command.json`, `restart-snapshot.json`, and original/overlay reports in `anchor/` and `revisit/`.

## Remaining modular work

Automatic landmark acquisition needs a separate validated image-feature adapter and held-out real shelf checks before this can run without annotated correspondences. M04b3 will expose provisional inventory revisions and review state in the capture UI. Provider scheduling and voice-driven recapture remain M06. Real camera/metric calibration questions from earlier modules remain open and do not imply verified camera geometry here.

**Awaiting user review.**
