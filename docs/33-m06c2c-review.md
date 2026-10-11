# M06c2c — Bounded saved-frame detection jobs

Authorized by “next” after M06c2b. This part adds saved-frame shelf detection to the existing durable queue through explicit CLI/API enrollment. Shelf regions, shelf IDs and validation policy must be provided; nothing chooses or assumes the shelf region. Physical registration, duplicate-copy matching, inventory imports and identity acceptance remain separately reviewed. A browser rectangle-selection/enrollment control is proposed as the next small part.

## Architecture and contracts

`DetectionJob` requires `kind=detection`, a global bounded job ID, bound guided session, expected inventory and reference revisions, and the existing DetectionRequest. Its request pins saved frame ID/SHA256, explicit nonblank shelf ID, original-image pixel rectangle and explicit polygon/overlap policy. All fields are required. Enqueue checks capture binding, current revisions, original integrity, shelf bounds and EXIF-coordinate eligibility. Exact ID retries preserve inputs; changed content cannot replace an existing job.

Reading inputs and stored reading jobs retain their original schema. `parse_job` accepts the explicit detection variant or the original reading variant; unknown kinds fail validation. Both job kinds share the existing 200 retained/20 pending/one globally running worker bounds. Job IDs share one namespace. `--kind detection` processes the oldest queued detection job; the default reading worker skips detection jobs. Either kind blocks another worker while an uncertain running attempt remains. There is no automatic stage chaining or retry.

The detection worker reuses the M04a saved-frame validator, bounded existing Gemini detection transport and detection export. It checks revisions before dispatch, after a live provider call, after export and under the publication writer lock. A later inventory/reference change also makes a completed result project as stale. Provider errors remain explicit unavailable results with unknown counts; local non-convex/ambiguous polygons follow the existing partial-review policy. No physical count is accepted from a successful model response.

Fresh output is checked before any detection provider call. Provider exception text is not journaled. Original, polygons, unresolved regions, detector input/response, overlay and local HTML report reuse the existing evidence bundle. Every published file is hashed and verified by the queue. Results are stored under `STORE/recognition/JOB_ID/`; cancellation/interruption never enables an old attempt to publish or automatically retry.

The existing `detection_result.json` stage keeps its original independent-frame `input_revision=0` and fingerprint format, preserving tracking-bundle compatibility. New `queue_stage.json` contains the full DetectionJob and a typed `queued_shelf_detection` StageResult with the actual pinned inventory revision, original reference, result status/errors and no-inventory-mutation marker. Review the queue eligibility and envelope before using a historical detector bundle. A successful stage still contains provisional proposals; importing it requires the existing explicit reviewed tracking command.

## API and worker operation

POST `/api/guidance/{session}/recognition/detection` accepts DetectionJob and requires body/URL session agreement. Existing exact Host/Origin, 4 KiB control body, body timeout and error boundaries apply. Existing session queue GET and cancellation work for both kinds. Artifact GET additionally permits only `detection_result.json` and `queue_stage.json`; it verifies session and publication hashes. Provider raw responses, SVG and HTML are not exposed through the HTTP artifact route. The local bundle still contains its review report.

The browser queue display identifies job kind and provides detection proposal/pinned-stage JSON links; it never imports a detection. Saved-frame region selection/enrollment remains CLI/API-only for this part. Existing reading enrollment remains unchanged.

```powershell
.\.venv\Scripts\python.exe -B -m library_claim.recognition_jobs --store PATH --enqueue detection-job.json
.\.venv\Scripts\python.exe -B -m library_claim.recognition_jobs --store PATH --kind detection --run-one --response detection-response.json
.\.venv\Scripts\python.exe -B -m scripts.smoke_detection_jobs --output runs/my-detection-queue-smoke
```

Explicit live mode replaces `--response` with the existing `--gemini --free-tier-confirmed --key-file PATH` arguments and allowed model. No paid fallback or automatic retry exists. No key is saved in a job. Live queue detection was tested with mocked provider outcomes only in this part; no actual provider request was made.

## Verification and artifacts

12 new Python checks cover durable completion without registration, pinned queue-stage versus original detector stage, exact retry/changed content, kind routing, required region/policy/shelf and frame/revision guards, correction before/after a provider call, completed reference invalidation, unavailable counts/errors, non-convex partial review, interruption/cancellation, pre-existing output without provider call and HTTP artifact/session/integrity controls. One new Node check verifies detection kind and proposal/envelope links without acceptance.

An initial geometry test constructed its fixture incorrectly and then expected unavailable rather than the detector's intentional partial-review outcome. The fixture and expectation were corrected; the detector policy was preserved. That failed run is not counted as successful validation.

Final full regression: 356 Python tests and 33 Node tests passed. Existing Starlette/HTTPX deprecation warning remains.

Actual synthetic target HTTP/restart/CLI smoke passed in `runs/m06c2c-review`: exact enrollment retry, queued restart, independent detection replay worker, published proposal/envelope retrieval, completed restart, original hash preservation and unchanged inventory. The fixture detected one provisional object while the existing ledger retained its two separately reviewed physical tracks. A later explicit ownership correction made the completed result stale. Provider requests: zero. Artifacts include `smoke-summary.json`, `http-history.json`, replay `response.json`, server log and `setup/store/recognition/shelf-detection/report.html`. The exported bundle also passed the existing tracking load_bundle validator without applying an import, demonstrating schema compatibility. Test servers were stopped. The user-tested reference was not run.

Real shelf detection precision/recall, provider queue invocation, continuous automatic capture, actual-device voice/camera and geometry remain unmeasured. Proposed next part: M06c2d browser saved-frame shelf-region selection and explicit detection enrollment. Automatic same-pass enrollment and reviewed registration need subsequent boundaries.

**Awaiting user review.**
