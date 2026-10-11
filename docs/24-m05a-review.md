# M05a — Saved spine crop and visible text

Implemented; **awaiting user review**. Literal visible-text extraction only. Catalogue/work/edition acceptance remains M05b.

## Architecture and reuse

```text
M04b1 observation + inventory revision + original SHA256
 -> verified original/polygon -> derived perspective crop and transform
 -> bounded Gemini transcription or saved-response replay
 -> unverified text spans in crop/original coordinates + JSON/HTML review
```

`spine_reading.py` reuses FrameStore originals, TrackStore observations/revisions, planar geometry, Pillow and StageResult. `vision_provider.py` factors the existing bounded transport into `request_structured`; M04a keeps its original prompt/schema and delegates to it. No extra dependency, SDK or catalogue service. Reference descriptive/title inference is unsuitable for supported spine text and is not reused. Its earlier authorized `.env` key was read privately for target synthetic calls; reference files/credentials were unchanged and no reference tests ran.

## Input and crop

`ReadingRequest` requires sweep, expected revision, observation ID and exact frame SHA256. Observation must exist in that sweep, including unresolved physical identities. Validate original integrity, revision, hash, bounded convex polygon and EXIF coordinate compatibility before a call. Crops with either mean opposing edge length below 8 source pixels are rejected; this is not a calibrated readability threshold.

Raster dimensions derive from mean opposing edge lengths, rounded to integers and capped at 1024 pixels on the long side. No deliberate upscaling, inferred rotation or lettering enhancement. Pillow RGB conversion and bicubic projective resampling create `crop.png`; the original is copied unchanged. Corner ordering follows the saved observation and can impair reading when inconsistent. Vertical/diagonal text is read in the existing crop orientation, preserving region coordinates.

Metadata records original frame/hash, observation/current track association, synthetic flag, polygon, crop size/hash, crop-to-original 3×3 matrix and transform description. Coordinate space is original encoded pixel edges, not metric coordinates. Derived crop never replaces original evidence. Each text span records its crop polygon and projected original polygon, source hashes, literal text, tentative role and `verified=false`.

## Response and unknown semantics

`ReadingResponse` requires legibility (`readable`, `partial`, `unreadable`), spans and uncertainty. At most 80 spans; each requires nonblank literal text (≤500 characters), four finite convex nonzero normalized crop corners, orientation and tentative role (`title`, `author`, `publisher`, `edition`, `isbn`, `volume`, `other`, `unknown`). Unknown keys/model numerical confidence are rejected. Unreadable requires no spans; readable/partial require spans. Partial/unreadable requires a reason.

Prompt instructions: exact visible lettering/case/script; no completion, hidden-letter restoration, remembered title/author or inferred ISBN/edition; no external lookup; partial literal fragments allowed; printed instructions treated as text. These instructions cannot independently verify model compliance. Output explicitly retains `transcription_verified=false`, `calibrated_confidence=null`, `accepted_identity=null`, `inventory_mutated=false`. Role labels never populate Book identity. Stage success means a schema-valid readable response, not verified transcription/identity. Valid partial/unreadable results are partial; unavailable provider results have response null and explicit error.

No multiview consensus, catalogue resolution, ISBN/edition acceptance, production language configuration, inventory identity update or pricing occurs. Unicode has a fixture check only. M05b must distinguish work/edition claims and preserve contradictions/unknowns.

## Provider and failure boundaries

Shared transport retains fixed Gemini endpoint, existing model allowlist, key header, redirect refusal, 10 MiB image/2 MiB response bounds, 45-second socket timeout, strict finish/schema validation, redacted raw response/usage, one request and no automatic retry/fallback. Only the crop is sent. Default Gemini 3.1 Flash-Lite is unchanged. CLI requires free-tier confirmation; billing is not independently verified.

Quota/network/invalid response exports unavailable with original/crop retained. Inventory is rechecked after the call; concurrent correction rejects stale export without mutation. Discarded stale-call usage/raw diagnostics are not durable in this CLI; integrated job audit is later M06/M10 work. Crop/input/storage errors stop processing without fabricated output. Fresh directories prevent overwriting evidence. Filesystem failure may leave incomplete files; rerun into a fresh directory. No reading HTTP endpoint or camera scheduling is introduced.

## Run and artifacts

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_reading --output runs/my-reading-smoke
.\.venv\Scripts\python.exe -m library_claim.spine_reading --store runs/my-reading-smoke/store --input runs/my-reading-smoke/legible-input.json --response runs/my-reading-smoke/legible-response.json --output runs/my-reading-replay
# Optional live target call using an authorized local free-tier key:
.\.venv\Scripts\python.exe -m library_claim.spine_reading --store runs/my-reading-smoke/store --input runs/my-reading-smoke/legible-input.json --gemini --key-file C:\path\local.env --free-tier-confirmed --output runs/my-reading-live
```

Use the project environment and fresh outputs. Key path is a placeholder; never paste keys into chat. Offline smoke generates labeled synthetic spines and imports known observations; no detector inference/provider call. Real reading requires a real saved observation/frame hash/current revision.

Exports include unchanged original, crop, `reading_result.json`, optional sanitized `provider_response.json`, and `report.html`. HTML embeds crop/region overlay, escaped literal text/roles and unknown identity, and links to original/evidence JSON. This is a reading bundle, not final claim export.

## Tests and observed smoke

**195 Python tests passed**, including nine new reading tests covering crop transform/hash/original preservation/no upscaling; source spans without mutation; unreadable/partial/Unicode fragments; contradictory legibility/invalid regions/extra confidence; wrong sweep/observation/hash/revision; fresh outputs/HTML escaping; provider failure with retained evidence; shared transport payload/usage under mock; and concurrent correction rejection. Existing M04a provider tests pass after refactoring. Existing Starlette/HTTPX deprecation warning remains. Browser assets unchanged; no JavaScript/browser rerun for this module.

Two actual Gemini calls on synthetic 280×680 crops in `runs/m05a-review`. Visually inspected legible crop contained `RIVER ATLAS`, `MAYA SEN`, `NORTH PRESS`, `VOL 2`: all four returned exactly, with fixture-matching tentative roles. Blank returned `unreadable`/zero spans. Accepted identities stayed null; both Books remained unidentified at revision 1; original hashes matched. No catalogue/pricing calls.

Legible: 12.806 seconds, 1,271 input + 398 output = 1,669 tokens. Blank: 12.874 seconds, 1,271 input + 43 output = 1,314 tokens. Total two requests/2,983 reported tokens, model version `gemini-3.1-flash-lite`. Free-tier account user-confirmed; billing/cost not independently verified.

This is one easy drawn spine plus a blank, not actual shelf OCR accuracy, glare/occlusion/vertical-print robustness or multilingual device evaluation. Region coordinates were not independently scored. Real mixed-legibility evaluation remains pending.

Review `smoke-summary.json`, `fixture-truth.json`, `legible-live/reading_result.json`, `blank-live/reading_result.json`, their originals/crops/reports and saved-response examples. Final renderer replays both actual live responses locally in `legible-live-replay/` and `blank-live-replay/`; these are offline replays, not additional inference. Original/JSON navigation links were added after the live runs and are present in current replay reports.

## Next boundary

M05b: catalogue candidates, work/edition separation, contradiction gates and explicit unknowns. M04 automatic landmark acquisition, integrated recognition jobs, real metric calibration and continuous physical-sweep acceptance remain pending; this step does not waive them.

**Awaiting user review.**
