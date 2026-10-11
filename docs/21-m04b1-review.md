# M04b1 — Reviewed physical identity ledger

Status: implemented; **awaiting user review**. M04b is split into M04b1 (durable association core), M04b2 (registration and conservative automatic association), and M04b3 (capture inventory UI). Only M04b1 is implemented here.

## Scope and architecture

M04a produces frame-local observations. This module turns explicitly reviewed observations into physical-book tracks without summing frame counts or merging by title. Each accepted observation receives exactly one `new`, `same`, or `unresolved` decision. `new` declares a distinct copy; `same` references an existing track; `unresolved` creates no track. Required provenance records reviewer assertions, not computer-vision findings. Automatic matching and user-facing review controls remain later work.

```text
FrameStore originals + pinned M04a bundle
  -> local detection recomputation / integrity validation
  -> association command with expected inventory revision
  -> SQLite transaction: sources, observations, tracks, audit event
  -> provisional inventory JSON snapshot
```

`library_claim/tracking.py` reuses FrameStore's database and original integrity checks, M04a geometry validation, M01 Book and JSON serialization. Reference title/description deduplication is unsuitable for physical copies and is not reused. No new dependency or provider request is required.

## Contracts and rules

`TrackingCommand` requires `command_id`, `sweep_id`, `expected_revision`, `operation`, `detection_result_sha256`, `decisions`, `track_id`, `owned`, and `provenance`. Nullable fields must still be present. Unknown keys are rejected.

- `import`: SHA256 of the exact `detection_result.json` bytes; bundle directory supplied separately; exactly one decision per validated candidate; top-level `track_id`/`owned` null. Complete detection input, response, result and result hash are retained in SQLite.
- `resolve`: previously unresolved observations become `new` or `same`; result hash null and no bundle.
- `ownership`: existing track and explicit boolean, no decisions/bundle/hash. Excluded tracks and evidence remain in the ledger.

Each decision requires `observation_id`, `action`, `track_id` (nonnull only for `same`), and `provenance`. Target IDs come from the prior inventory snapshot. Deterministic track IDs hash the sweep and first observation. Adjacent copies remain separate regardless of shared title. Orientation/polygons stay in observations; identity, dimensions and prices remain unknown in Book rows. Initial ownership follows the existing M01 `owned=true` convention and supports explicit correction; images do not establish ownership.

Imports validate original sweep/hash/ROI/orientation, typed stage metadata, stage evidence and input fingerprint. Successful/partial results are recomputed from their saved response and compared with saved output. Unavailable stages retain errors rather than asserting an empty shelf. SHA256 pins contents; it does not prove provider authorship. Review provenance is auditable, not an independently verified identity certificate.

Each frame/shelf imports once. Reanalysis/replacement is unsupported until invalidation semantics exist. Identical command-ID retries are idempotent, including retries using the original revision. Changed content under the same ID fails. New commands require current revision; stale decisions fail. One transaction commits all changes or none. Two detections from one frame cannot join a single track. Cross-shelf joins require a future relocation operation. Corrections can resolve unresolved observations or change ownership; merging/splitting existing tracks and clearing detector uncertainty are not implemented.

The snapshot contains `books`, `tracks`, `observations`, `detection_sources`, `events`, `review_queue`, `assigned_track_count` and `owned_assigned_track_count`. Counts describe assigned tracks only. `total_book_count` stays null and `coverage_verified` false even when detector coverage is clear. Detector ambiguity, unresolved regions, uncertain coverage, unavailable stages and unresolved identities remain review entries. No full shelf/sweep coverage is inferred.

Original integrity is checked before mutation and on restart/snapshot. Temporary detection directories may be removed after import; FrameStore originals must remain. Snapshot JSON references originals and is not the portable final packet. The ledger is limited to 10,000 events and observations per sweep and retains full source responses: suitable for the initial small room, not a large-library database design. Each local artifact is capped at 2 MiB after reading; bundle files are trusted operator-selected local inputs, not HTTP uploads. SQLite originals/events are local files, not a tamper-proof audit service.

## Run and review

From the repository root, using the project environment:

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_tracking --output runs/my-m04b1-smoke
.\.venv\Scripts\python.exe -m library_claim.tracking --store runs/my-m04b1-smoke/store --sweep-id tracking-smoke --output runs/reopened-inventory.json
```

Choose fresh output paths. Smoke saves complete command JSON examples. To import a real reviewed M04a bundle:

```powershell
.\.venv\Scripts\python.exe -m library_claim.tracking --store runs/my-capture --command reviewed-command.json --bundle runs/my-detection --output runs/inventory-revision-1.json
```

Read candidate observation IDs, calculate the result-file SHA256, and supply explicit decisions. Example paths do not indicate real captures. SQLite commits before the convenience snapshot is written. If writing the snapshot fails, replay the exact command with a fresh output path to recover without adding a revision. There is no inventory HTTP endpoint or camera-page inventory UI in this subpart.

## Validation and actual outcomes

**163 Python tests passed**, including 16 new tracking tests: revisits/restart; distinct copies/horizontal orientation; unknown fields; unresolved then resolved; ownership exclusion; idempotency/conflicts; stale revisions; same-frame many-to-one and cross-shelf rejection; missing decisions/unknown targets; cross-sweep/reimport rejection; artifact/response/original tampering; split/merge reviews; uncertain coverage; unavailable detection; invalid command shapes. Existing Starlette/HTTPX deprecation warning remains. Browser assets are unchanged, so existing JavaScript checks were not rerun.

Offline CLI smoke: `runs/m04b1-review`. Every command ran in a separate Python process; a final new process reopened SQLite. Two labeled synthetic shelves yielded four tracks. A shifted shelf-A revisit linked two observations back to their tracks and left an extra observation unresolved: still four tracks and one identity review. Explicitly resolving it as new produced five tracks. Ownership exclusion retained five tracks and four owned tracks. Seven observations, five revisions, and exact reopened snapshot equality. Total count stayed null. **Zero provider calls.**

Artifacts: `smoke-summary.json`, `restart-snapshot.json`, five `*-command.json` files, and shelf/revisit `report.html` pages containing original images and labeled polygons. Fixture labels intentionally include repeated titles.

This smoke uses drawn images and explicit associations. It does not demonstrate automatic registration, real detector/identity accuracy, laptop camera access, live inventory updates or a continuous physical shelf sweep. Those acceptance checks remain outstanding.

## Next review boundary

M04b2 must validate same-shelf registration, conservative one-to-one matching, and ambiguity handling, with merges/splits evaluated against independently labeled observations. M04b3 will publish revisions to the capture UI and test stale/reconnect behavior. Neither is implemented here. OCR remains M05. Verified camera-profile acquisition and real capture/geometry acceptance remain unresolved from earlier modules.

**Awaiting user review.**
