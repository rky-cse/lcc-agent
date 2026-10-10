# M05b3 — Catalogue editions matched to owned-copy evidence

Authorized by the user's **next** after M05b2. This part retrieves bounded edition records, evaluates them against the reviewed work/visible ISBN and explicit binding declaration, and persists explicit edition acceptance/rejection/clearing. It does not authenticate a printing, signature, rarity claim or condition, determine prices, or connect camera/voice recognition. Real physical book acceptance remains unverified.

## Architecture and reuse

`M05b2 reviewed physical track + archived confirmed visible ISBN + binding declaration → fixed Open Library edition endpoint → bounded record validation → contradiction/unknown gates → candidate report → explicit revision-guarded edition decision → audited ledger/API/export`.

`library_claim/edition.py` owns requests, record parsing, owned-ISBN validation, matching, lookup export, edition commands/transactions and CLI. `CatalogueClient._fetch()` now shares the existing HTTP transport, cache and per-store rate gate across search and edition adapters. Each public adapter restricts its endpoints. No SDK or dependency added. The physical ledger, evidence archive, Book projection and packet semantics are reused. Inventory server/report text now distinguishes reviewed work from reviewed catalogue edition. Browser assets and reference source/credentials are unchanged.

## Input and owned-copy proof

`EditionRequest` requires sweep ID, expected revision, physical track ID, explicit optional edition ID, limit 1–10, `owned_physical_format` and a literal `format_statement`. Supported binding declarations are hardcover/paperback; other_print/unknown remain unresolved. There is no binding default or inference from title, device or ISBN. Later M06 guidance must ask the claimant for the binding and request a readable ISBN observation when needed.

The track must already have a reviewed work. The ISBN must come from M05b2 `visible_text` metadata, with a confirmed saved span. The module reopens the archived reading associated with the original work-review command and verifies that span's role, normalized checksum-valid ISBN and physical track. FrameStore originals and all archived evidence hashes are verified by ledger snapshot. A claimant-only ISBN, missing ISBN or unconfirmed text cannot enable lookup/acceptance; unavailable output records zero requests. No likely edition supplies an ISBN to the physical Book.

Binding remains a claimant declaration even after review. Matching a catalogue record to a reviewed visible identifier is an explicit acceptance policy, not independent physical authentication. Existing appraisal status is preserved. Catalogue data and local audit hashes are not provider signatures or an adversary-proof proof of truth.

## Retrieval contract

- Explicit candidate ID: `https://openlibrary.org/books/OL…M.json`. The returned key must equal the requested ID. An ID is a lookup proposal, never proof of the copy.
- No candidate ID: `https://openlibrary.org/works/OL…W/editions.json?limit=N&offset=0`. One bounded first page only; no automatic pagination. Preserve advertised count/completeness and all returned records.

Open Library documents both edition JSON and work-editions endpoints, with works collecting related editions. This adapter uses these current endpoints rather than the legacy generic book API or automatic ISBN redirects. [Official Books API documentation](https://openlibrary.org/dev/docs/api/books).

Required remote fields are edition key and title. Optional bounded fields are work references, ISBN-10/13 arrays, physical_format, publisher array and edition_name. Unrelated remote fields are ignored but exact raw response bytes are retained. Bad object shape, edition keys, duplicate edition records, excessive page length or invalid page counts fail schema validation. Invalid ISBN strings inside otherwise valid records remain visible as review reasons and cannot support acceptance.

The shared transport permits one request per lookup, no redirect or automatic retry, 20-second socket timeout and 2 MiB response cap. The timeout is not a total elapsed-time deadline. Valid raw responses cache for 24 hours by exact URL and retain UTC retrieval time. Search/edition request starts share the persistent 1.2-second per-store reservation and 429 cooldown; a local cooldown sends zero requests. Successful cached raw records can still produce needs_review. Parser failures, outages and quotas are unavailable, not zero editions. Cache-only restart works without network access.

The app uses the lower non-identified allowance; no contact address is invented. Production coordination across separate stores/contact identity remains unresolved. [Official API usage guidance](https://openlibrary.org/developers/api).

## Conservative comparison

A supported record requires all of the following:

1. Exactly one work reference matching the currently reviewed work, and normalized title equality.
2. The reviewed visible ISBN appears exactly after whitespace/hyphen removal and checksum validation. ISBN-10/13 conversion is not implemented; equivalent alternate-only identifiers can remain unresolved/rejected under this narrow policy.
3. Catalogue physical format is in the supported print vocabulary and agrees with the explicitly declared hardcover/paperback copy. Hardcover/hardback and several paperback/softcover spellings are normalized. Digital, audio, electronic and Kindle wording is ineligible. Missing/unsupported format is needs_review, never presumed print.
4. Any already supplied publisher/edition statement agrees with the literal catalogue values under conservative normalization. Missing catalogue fields are review reasons; differing supplied fields are contradictions.

Missing work link, missing/unusable catalogue ISBN, invalid catalogue ISBN entries, unknown binding and absent matching metadata produce needs_review. Differing work/title/ISBN/binding/publisher/edition or digital format produce contradicted. Multiple supported records remain ambiguous, including duplicate-ISBN catalogue records. Explicit review can choose among returned supported candidates; first rank and edition popularity never choose one. A bounded page cannot establish global uniqueness. No translation/subtitle/fuzzy or publisher-imprint inference is claimed.

## Review, corrections and output

`EditionCommand` requires command/sweep/track IDs, expected revision, action, explicit reviewer/reason and pinned result hash/edition ID for acceptance/rejection. Clear requires neither bundle nor edition ID. Extra fields and blank review rationale are rejected.

Before mutation the module revalidates current context and recomputes records, candidate dispositions, counts, completeness, query, work-review linkage and stage fingerprint from the exact saved response. Unsupported/unreturned editions, cross-track/sweep or stale sources are rejected. An atomic transaction checks revision again, preserves old/new identity, archives result/response bytes and records a typed edition-review stage and price/totals invalidation markers. A concurrent correction prevents commit.

Acceptance stores `accepted_edition_id`, `edition_status=catalogue_matched_reviewed`, reviewer command, source bundle hash and separate binding declaration provenance. It preserves existing literal Book title/author/ISBN/edition/publisher, ownership and appraisal status; it does **not** fill unseen edition/publisher/printing details from the record. No calibrated confidence or price appears.

Rejecting the current accepted edition clears that edition; rejecting another record preserves it. `clear_edition` restores pre-acceptance metadata status and leaves reviewed work/visible ISBN/observations/ownership/appraisal intact. Clearing/replacing work identity through M05b2 also removes edition acceptance. Reacceptance can remove a previous edition rejection only through another explicit supported decision. Command IDs share the sweep ledger namespace; exact retries survive process restart/removal of the original bundle without a new revision, while changed payloads under the same ID fail.

Lookup bundles contain `edition_result.json`, exact `edition_response.json` when available and escaped `report.html`, including remote matching fields, literal binding declaration, source, synthetic label, count/completeness and unknowns. The reviewed ISBN observation is traced by work-review command to the existing ledger archive; it is not duplicated in this lookup bundle. The inherited `EditionStore.export_evidence()` creates a portable full reviewed inventory/report with originals, reading/work/edition artifacts and hash-role manifests. This remains an intermediate inventory; M10 final-packet provenance integration is pending.

```powershell
python -m scripts.smoke_edition --output runs/my-edition-smoke
python -m library_claim.edition lookup --store STORE --input EDITION_REQUEST_JSON --output FRESH_DIRECTORY --response SAVED_EDITION_JSON
python -m library_claim.edition review --store STORE --input EDITION_COMMAND_JSON --bundle LOOKUP_DIRECTORY --output FRESH_INVENTORY_JSON
```

Use `--open-library` instead of `--response` for a live lookup. Omit `--bundle` on clear. A direct lookup consumes an edition object; a work-page lookup consumes `{size, entries}`. Synthetic smoke commands/IDs/claimant statements are fixtures, not instructions to decide a user's actual books.

## Validation and observed smoke

The full regression suite passed **257 Python tests**, including 22 new edition tests covering reviewed visible ISBN, zero-call claimant-only ISBN, work/title/ISBN/binding/digital contradictions, missing fields/invalid ISBNs, publisher/edition uncertainty, bounded-page ambiguity, explicit acceptance without metadata borrowing, unsupported/unreturned editions, exact retry/restart, clear/work invalidation, stale/cross-target inputs, re-pinned projection/raw response tampering, schema/count/duplicates/endpoint restrictions, shared cache/gate, service failures, archive corruption, escaping, rejection, lookup/review races and appraisal retention. Existing Starlette/HTTPX deprecation warning remains. Final missing-field and report checks were also rerun in the edition tests; browser assets are unchanged.

`runs/m05b3-review-final` contains the final synthetic CLI/local HTTP smoke. A visually inspected drawn spine has `FANTASTIC MR FOX`, `ROALD DAHL`, `9780140328721`. Detection/reading/work response and declared binding are known fixtures, not provider inference or ground truth for a real book. A controlled edition record yields supported_candidate without mutation. Explicit review advances revision 2 → 3 and accepts its catalogue edition ID; publisher/edition strings stay blank, prices unknown. Exact CLI retry with a missing bundle stays revision 3. An actual server restart returns identical inventory; clear advances to revision 4 while preserving work, visible ISBN, physical observations and original bytes. The temporary server was stopped. Earlier M05b2 CLI/HTTP clearing was rerun successfully in `runs/m05b3-identity-regression` after server/report changes.

One restricted live network attempt failed. The permission-backed retry made **one successful public request** to the documented `/books/OL7353617M.json` endpoint, sending only that ID, no image/key/personal information. It returned matching work `/works/OL45804W`, title and ISBN, but **omitted physical_format**. Outcome needs_review; explicit acceptance was blocked without a ledger change. The module did not infer paperback from the ISBN or fixture statement. Request took 1.136 seconds.

`runs/m05b3-review/edition-cache-restart` and `edition-final-cache` reused that exact response with zero requests, identical SHA-256 and retrieval timestamp. The latter contains the final report renderer. `smoke-summary.json` records the live reason, usage, hash/cache checks and blocked acceptance. Offline acceptance verifies logic only; the live smoke verifies retrieval and a missing-data rejection path, not successful real-edition acceptance. Real shelf ISBN acquisition, useful catalogue physical-format coverage, held-out identity accuracy and print/signature authentication remain unverified.

The initial direct unit fixture omitted parser-supplied defaults and was corrected to exercise normalized records; production parsing was unchanged. No Gemini calls, reference tests, SDK installs or pricing calls ran.

## Next review boundary

M06 is split next: first implement guided conversation/session state for country/currency, reference-object calibration, unreadable-spine/ISBN/binding recapture requests and corrections; then connect live voice/media transport in a separately tested part. Model/key setup follows existing free-tier authorization, but actual device/provider behavior requires its own smoke. Remaining automatic landmark acquisition, real geometry, complete room capture and real mixed-legibility M05 acceptance are not waived.

**Awaiting user review.**
