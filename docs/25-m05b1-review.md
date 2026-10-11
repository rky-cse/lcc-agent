# M05b1 — Evidence-bound catalogue work candidates

Authorized by the user's latest **next**, after M05a. This is the first small part of M05b: retrieve and evaluate work candidates from saved literal spine text. It exports proposals for review. It does not accept an identity, choose an owned edition, fill ISBNs, obtain prices, or schedule live capture jobs. M05b2 requires the next user instruction.

## Architecture and interfaces

`FrameStore + reviewed observation → verified M05a reading bundle → selected title/author span IDs → quoted catalogue query → bounded work records → conservative candidate dispositions → portable review bundle`.

`library_claim/catalogue.py` owns request validation, reading-bundle verification, a small Open Library HTTP adapter, persistent cache/cooldown, comparison and export. The existing `spine_reading.text_evidence()` function now supplies the same deterministic span projection to both reading export and catalogue verification. No new dependency was installed. Browser/server interfaces are unchanged.

`CatalogueRequest` requires the exact reading-result SHA-256, ordered title/author span ID lists (up to eight each, no duplicates across lists), and explicit candidate limit 1–10. IDs must exist in the source reading and have the corresponding tentative role; roles remain unverified model/replay labels. Title fragments and author fragments are joined in the selected order. No title selected or an unavailable/unreadable reading produces an unavailable stage with zero HTTP calls. A title without author may be queried, but cannot become a supported candidate.

Before querying, the module checks source result hash/size, current sweep revision, observation/original hash, exact original bytes, regenerated crop bytes/metadata, reading stage identity/job fingerprint/legibility status, and regenerated literal spans/regions. It retains validated evidence bytes in memory for export, so edits to input bundle files during a network wait cannot replace exported evidence. After lookup it checks revision again. A correction during a request rejects stale export; a successful response may remain in the query cache. The checks establish internal provenance consistency, not that the transcription is true or that a local file is cryptographically authenticated by a provider.

Only a fixed HTTPS search endpoint is used. Quoted Solr title/author values escape quotes and backslashes. Requests ask for work key, title, author names and edition count; limit/offset are explicit. Schema accepts only work keys `OL…W` or `/works/OL…W`, bounded titles/author arrays, nonnegative counts, start zero and distinct work keys. Unrelated remote fields are ignored; exact raw response bytes are saved. Edition keys are rejected in this work-search adapter.

## Identity and ambiguity policy

Comparison applies Unicode NFKC, case folding, punctuation-to-space and whitespace collapse. It retains numbers, accents and words such as articles. There is no fuzzy similarity score, popularity/rank selection or identification confidence.

- Exact title plus a selected exact author with fully readable text and no volume issue yields `supported_candidate`; this is still unverified evidence requiring review.
- Different titles, conflicting supplied author records, or explicit conflicting volume numbers are `contradicted` under this exact-literal policy. Partial author fragments can therefore be rejected; no fuzzy recovery is claimed.
- Missing catalogue/visible author, partial reading or visible volume absent from the work title yields `needs_review`.
- Multiple supported work records produce `ambiguous`; every returned record and rejection reason remains visible. One supported record is only a candidate. Zero results is `no_match`; service failure is `unavailable`, not zero books.

Search completion is true only when the service explicitly reports an exact count and the returned count equals it. A bounded first page cannot establish global uniqueness. Edition count is descriptive work metadata; publisher/edition/ISBN/format/printing are not verified against a work record. Accepted work/edition IDs and calibrated confidence always remain null, `edition_status` is unresolved, and the ledger is unchanged.

Open Library search returns works by default; its edition-search result is not proof of the physical copy. The implementation deliberately consumes work fields only. [Official Search API](https://openlibrary.org/dev/docs/api/search).

## HTTP, caching and failure boundaries

One call per export at most, no automatic retry or redirect, a 20-second socket timeout and response byte cap of 2 MiB. The socket timeout is not a strict whole-request deadline. Successful responses cache for 24 hours by exact query URL in the existing store SQLite database, preserving raw bytes and UTC retrieval timestamp. Cache entries are validated again before use. Cache-only execution works across CLI/process restart without network access.

A SQLite transaction reserves at least 1.2 seconds between request starts per store, across processes using that store. An early call returns a retryable local cooldown without sleeping/sending. HTTP 429 adds a minimum 60-second cooldown; numeric Retry-After is bounded to 60–3600 seconds, date-form headers fall back to 60. Selected transient 5xx/network failures are retryable but not retried automatically. Malformed live responses become unavailable with a generic diagnostic; invalid offline fixtures raise for correction. No API key is required or sent.

Open Library documents one request/second for non-identified clients and a higher allowance for fully identified clients, and recommends caching/human-directed lookups. This prototype supplies an application User-Agent but no invented contact address, and uses the lower allowance. Production multi-store/global scheduling, operator contact identification, catalogue reconciliation and service suitability require a later integration decision; the per-store gate is not an application-wide limit. [Official API usage guidance](https://openlibrary.org/developers/api).

## Export and commands

Each fresh output directory contains `catalogue_result.json`, the exact pinned `reading_result.json`, exact crop/original bytes, `catalogue_response.json` when available, and `report.html`. The report escapes remote/model text, shows all returned records/reasons/count/completeness and links candidate works and evidence JSON. These are intermediate review bundles, not a finalized claim packet.

```powershell
python -m scripts.smoke_catalogue --output runs/my-catalogue-smoke
python -m library_claim.catalogue --store runs/my-catalogue-smoke/store --input runs/my-catalogue-smoke/catalogue-input.json --reading runs/my-catalogue-smoke/reading-replay --output runs/my-catalogue-smoke/live --open-library
```

For an offline replay replace `--open-library` with `--response PATH_TO_SAVED_SEARCH_JSON`. Repeating the exact live request into a fresh directory can use the persisted cache. Do not reuse an output directory. The title/author must derive from selected saved spans, not newly guessed bibliographic facts.

## Tests and observed smoke

**213 Python tests passed in 27.813 seconds**, including eighteen new tests covering supported work without identity mutation; wrong first author; multiple matches/truncation; missing author; partial text; volume uncertainty; unreadable/no request; no match; evidence hash/crop/role tampering; stale revision; malformed schema/edition keys/duplicate counts; correction during lookup; HTML escaping; re-pinned inconsistent stage; normalization/query quoting; exact cache after client restart; 429 cooldown/no retry; and malformed live-response handling. Existing Starlette/HTTPX deprecation warning remains. Browser assets are unchanged; no JavaScript/browser regression rerun was required for this CLI-only part.

`runs/m05b1-review-ready/` contains a drawn 1600×900 spine, known literal reading replay (`PRIDE AND PREJUDICE`, `JANE AUSTEN`), original/crop evidence and offline wrong-first/ambiguous/no-match cases. Detection and reading are labeled fixture/replay, not inference. Invented offline work IDs do not represent catalogue facts. All three offline assertions passed; ledger stays revision 1, unidentified and unpriced.

One restricted network attempt failed and was exported as unavailable. The required permission-backed retry made **one successful public catalogue request**, sending title/author only, no images or credentials. It returned five of 346 reported search results: two exact title/author works plus three title contradictions. Outcome **ambiguous**, incomplete search, all accepted identities null. Query took 1.794 seconds. The two matching work IDs were `/works/OL66554W` and `/works/OL15165350W`; no first-ranked identity was accepted.

The same CLI in a new process exported `catalogue-cache-restart` with **zero requests**, a cache hit, identical raw response SHA-256 and original retrieval timestamp. Original reading pin and unchanged revision/unidentified ledger passed verification. The final evidence-copy implementation also replayed the saved actual service response offline into `catalogue-final-replay`, with unchanged ambiguity and zero requests. See `smoke-summary.json`, `catalogue-live-allowed/report.html`, `catalogue-cache-restart/catalogue_result.json`, and the offline case reports. No Gemini calls, extra dependencies or reference tests ran. Real shelf transcription/catalogue precision and owned-copy edition coverage remain unmeasured.

The first offline smoke fixture was rejected for a sub-minimum resolution; the fixture was corrected to 1600×900, preserving the production evidence minimum. Its incomplete attempt remains in `runs/m05b1-review`; valid artifacts are in `runs/m05b1-review-ready`.

## Next boundary

M05b2: explicit reviewed acceptance/rejection and edition evidence, with revision/provenance contracts, conservative unknowns and persistence tests. This must not equate work identity with owned-copy edition identity. M06 recognition/voice integration, M07 pricing, automatic landmark acquisition and real physical acceptance remain pending.

**Awaiting user review.**
