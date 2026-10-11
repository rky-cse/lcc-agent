# M05b2 — Reviewed work identity and separate edition metadata

Authorized by the user's **next** after M05b1. This part implements explicit bibliographic decisions on individual physical tracks, persistence, correction and audit exports. It does not automatically accept catalogue candidates or prove a catalogue edition. Full edition-record matching remains a separate small part, M05b3; capture/voice recognition scheduling remains M06.

## Architecture

`pinned M05b1 bundle + explicit reviewer command → recompute reading/catalogue evidence → confirm target physical track and literal spans → revision-guarded SQLite transaction → reviewed Book projection + audit event + immutable artifact archive → inventory API/report`.

`library_claim/identity.py` owns typed commands, metadata provenance, candidate verification, acceptance/rejection/clear transactions, evidence export and CLI. It uses the existing FrameStore and physical ledger rather than a second inventory. `tracking.py` verifies saved identity artifact hashes and projects reviewed identity into Book fields. `server.py` now describes reviewed work rows as having unresolved owned-copy editions, rather than claiming their identification is pending. No browser asset, dependency or reference source changed.

## Command contract and decisions

`IdentityCommand` requires command ID, sweep ID, expected revision, physical track ID, action, explicit reviewer/reason, span confirmations, metadata decisions and an explicit appraisal flag. Catalogue hash and canonical work ID are required for work acceptance/rejection and absent for clearing. Extra fields, duplicate confirmations, duplicate metadata field decisions and blank reviewer/reason are rejected.

Actions:

- `accept_work`: choose exactly one returned `supported_candidate`, even when multiple supported works exist. Confirm exactly the selected title/author spans and any used visible metadata spans. Partial/contradicted/missing-author candidates cannot be overridden by this API; correct the evidence and regenerate candidates first. Choosing a candidate requires an explicit review command; rank never chooses it.
- `reject_work`: record the rejected returned work ID. Rejecting the currently accepted work clears its entire identity. Rejecting another candidate retains the accepted work. No confirmations/metadata/appraisal flag are accepted on rejection.
- `clear_identity`: explicitly retract all bibliographic values and appraisal status. It requires no catalogue bundle and preserves physical track, observations, original evidence and ownership.

Acceptance replaces the whole previous bibliographic record. Missing metadata in the new command stays blank; it is not copied from an earlier work or assertion. The audit event preserves previous/new identity and reason. Reaccepting a previously rejected work is possible only through a new explicit valid acceptance command and removes that work from the current rejection list.

Book `identified` means reviewed work identity, as specified in the existing contracts. It does not establish the owned edition. Title/author preserve the selected visible literal strings rather than importing unobserved author names or a catalogue-normalized title. Work ID and richer provenance live on the track's `bibliography` extension; edition/ISBN/publisher start blank. Calibrated confidence remains null.

## Edition metadata and assertions

Up to three metadata decisions can supply `edition`, `publisher`, `isbn`:

| Source | Required evidence | Stored meaning |
| --- | --- | --- |
| `visible_text` | Same observation's saved span, matching tentative role, exact literal value, explicit span confirmation | Reviewer-confirmed visible metadata; no catalogue edition identity |
| `claimant_assertion` | Literal claimant statement, value and explicit reviewer decision; no fabricated span | Recorded assertion requiring verification; no independent authentication |

ISBN normalization removes only whitespace/hyphens and uppercases X. It accepts checksum-valid ASCII ISBN-10 or 978/979 ISBN-13. A valid checksum is a syntax check, not proof that this book owns that ISBN. Visible ISBN text must match the supplied ISBN under that normalization; a printed label or incomplete fragment requires corrected reading rather than invented completion. No ISBN comes from work edition count or another candidate's metadata.

`accepted_edition_id` always stays null. `edition_status` is `unresolved`, `visible_metadata_confirmed` or `claimant_asserted_metadata`; the latter takes precedence when any supplied metadata is asserted. Accepted tracks remain in review for owned-copy edition identity, with a claimant-verification reason where appropriate.

The command has an explicit appraisal flag. English wording `first edition`, `1st edition`, `signed`, `rare`, or `antiquarian` in edition/assertion text requires it to be true; this is a narrow guard, not a complete multilingual rarity detector or authentication system. Flagged Books are `needs_appraisal`, retain supported work identity and have unknown prices. Other languages/signals require the later guidance/appraisal policy to request appropriate review. A monetary appraisal threshold is still unresolved and no price is published here.

Visible metadata records actual frame provenance. Claimant metadata has an empty `field_evidence` frame list and separate assertion provenance on the track. M01's final packet builder currently requires saved-frame references for text and therefore cannot carry these assertion fields automatically; M10 must deliberately extend packet provenance before integrating asserted metadata. This intermediate inventory/report is not a finalized claim packet.

## Integrity, persistence and corrections

Work decisions require the exact source catalogue-result hash and input revision. The module regenerates reading spans/crop, parses the exact saved search response, recomputes all candidates/count/completeness/query/outcome and checks the stage fingerprint. The reading observation must belong to the target physical track in the same sweep. Unreturned work IDs and work projections edited even with a newly supplied file hash are rejected.

After evidence validation, `BEGIN IMMEDIATE` rereads/verifies the ledger and checks revision again. A concurrent ownership/identity change prevents acceptance. Decisions, artifact bytes and audit event commit together; projection failure rolls back. Artifact archive keys are SHA-256 in a new `identity_artifacts` SQLite table. Reading/crop/catalogue files are retained independently of temporary source directories; originals stay in FrameStore. Snapshot and later mutations verify archived hashes and original-frame integrity.

Command IDs share the physical ledger's per-sweep namespace. Exact retries return the current verified snapshot without adding a revision, including after restart or removal of the input bundle. Reusing an ID with another payload is rejected. A new stale command fails. After a revision change, a new work decision requires refreshed reading/catalogue input; historical evidence remains in the audit archive.

Events include typed `bibliographic_review` StageResult (acceptance partial because edition remains unresolved), command fingerprint, reviewer/reason, previous/new identity, artifact filename-to-hash map and invalidation markers for edition/pricing/totals. This module has no price/totals cache to revoke: both price components remain unknown in the projected Book. Future consumers must observe ledger revision and these markers before publishing dependent results.

The database is the authoritative local state, not a provider-authenticated signature or an adversary-proof audit log. Source validation establishes consistency and physical association; it cannot establish that an OCR response is true without the explicit review. The CLI writes its output after committing the ledger; if output writing fails, an exact retry safely recovers a snapshot. Evidence export can leave a partial directory on an I/O failure; persistent database bytes remain available for a fresh export.

## Usage and review artifacts

```powershell
python -m scripts.smoke_identity --output runs/my-identity-smoke
python -m library_claim.identity --store STORE --command REVIEW_COMMAND_JSON --bundle M05B1_BUNDLE --output FRESH_INVENTORY_JSON
```

For `clear_identity`, omit `--bundle`. Do not run saved synthetic review commands against actual books. The smoke script uses invented catalogue IDs and fixture reviewer/claimant statements; it does not make decisions on a user's real shelf.

`IdentityStore.export_evidence(sweep_id, fresh_directory)` produces `inventory.json`, portable original frames with `frame-manifest.json`, exact archived bytes named by hash, `artifact-manifest.json` with artifact roles, and `report.html`. The report distinguishes visible and asserted metadata, labels synthetic frames and catalogue replay source, displays unresolved catalogue edition/confidence/prices and links originals/audit evidence. Synthetic/source labels are also retained on accepted track bibliography. All external/model/claimant text is escaped.

## Validation and observed smoke

**235 Python tests passed in 34.546 seconds**, including twenty-two new identity tests covering explicit choice of the second ambiguous candidate; work-only unknowns; restart/exact retry without original bundle; command-ID collision; stale/cross-track/cross-sweep decisions; contradicted/unreturned candidates; required confirmations; rejection; ownership/physical-observation preservation on clear; rejection of current/other work; literal ISBN/publisher/edition; missing/contradictory visible metadata; asserted first-edition appraisal; ISBN/schema validity; re-pinned candidate/raw-response tampering; archived corruption; transaction rollback; exact portable export; concurrent correction rejection; and replacement without metadata borrowing. The existing Starlette/HTTPX deprecation warning remains. Browser assets are unchanged; HTTP integration was verified by the actual smoke rather than a JavaScript rerun.

Actual CLI and local HTTP smoke in `runs/m05b2-review-verified`: a drawn spine and known reading replay fed an ambiguous offline catalogue. Reviewer selected the second invented work, with an explicit synthetic signed/first-edition assertion. Revision 1 → 2, Book became `needs_appraisal`, work identity was reviewed, asserted edition was labeled and catalogue edition/ISBN/confidence/prices stayed unknown. Exact CLI retry with a missing bundle stayed revision 2. The inventory HTTP endpoint returned the reviewed title/status and unresolved-edition reason. Original bytes matched; an actual server restart returned an identical inventory response. A separate clear command advanced to revision 3 and restored unidentified/blank bibliography while preserving one physical track and all observations. HTTP full export matched the corrected ledger. The temporary server was stopped. After adding explicit synthetic/catalogue-source labels, all 22 identity tests and the full CLI/HTTP smoke were rerun and passed.

See `identity-smoke-summary.json`, `accept-command.json`, `accept-inventory.json`, `http-accepted.json`, `clear-command.json`, `clear-inventory.json`, `http-corrected.json`, `accepted-evidence/report.html` and the evidence manifests. No external API/Gemini requests, reference tests or dependency installs occurred. This verifies transaction/CLI/API behavior on synthetic evidence, not real-book recognition precision, authentic edition detection, actual claimant correctness or continuous voice/camera operation.

## Next boundary

M05b3: catalogue edition-record acquisition and matching against explicit owned-copy evidence, with physical-format/work-link/ISBN contradiction checks and unknown fallback. Existing reviewed metadata must not become an accepted catalogue edition without that evidence. M06 then connects guided evidence acquisition, country/currency setup, reference-object calibration, speech and recognition jobs. These parts require another instruction; actual shelves and geometry acceptance remain pending.

**Awaiting user review.**
