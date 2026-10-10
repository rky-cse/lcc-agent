# M01 — Contracts, totals and minimal export

Status: **implemented; awaiting user review**. Date: 10 October 2026. Authorization: user requested implementation one part at a time and accepted their own reference testing. M02 has not started.

## Outcome

`library_claim/models.py` defines packet input, frame, quote, declared measurement, book/item, room, policy and structured stage-error contracts. `packet.py` checks evidence paths/hashes and references, normalizes unsupported values to unknown with review reasons, computes totals with Decimal, and exports JSON plus HTML and saved evidence. `report.py` renders the serialized packet. `demo.py` and the CLI supply explicitly synthetic review data; `tests/test_packet.py` exercises contracts and export boundaries.

Physical copies retain separate IDs, including duplicate titles. Non-owned inventory is excluded with an audit list. Appraisal books and artwork contribute no automatic price. Missing prices and dimensions remain unknown; an incomplete spine run stays null with a separately labeled measured subtotal. Source dates, conditions and currency must match saved quotes; unsupported conversion is excluded. Output files are protected against overwrite.

## Conventions and implemented boundaries

The current proposal keeps unknown text blank, unknown numbers/timestamps null, required objects present, and ordinary unpriced item status blank with review reasons. A question about these conventions was sent; no specific approval was received. They are visible for review, not inferred from the room or locale. Policy inputs explicitly select currency precision, `sum_spine_thickness` and either `missing_any_component` or `missing_all_components` for excluded-line counting. The demo selects two decimal places and missing-any; production policy remains reviewable. Money uses ROUND_HALF_UP per line before summation, recorded here; JSON emits exact numeric Decimal tokens.

Country/currency are required inputs with uppercase shape validation only. Authoritative ISO lookup and conversation prompts come later. The IN/INR smoke values are fixture settings, not a user-country assumption.

M01 checks declared provenance and saved-file integrity. It cannot establish that a producer's OCR, matching, measurement or quoted source is truthful. Field evidence currently means saved-frame references; claimant/catalogue provenance will be added by their modules. Measurements are supplied records, not measured from camera pixels. Room geometry consistency and calibration accuracy are future checks. No image decoder, capture backend, provider integration, real source adapter, FX conversion or finalization transaction is included. All art remains appraisal-only, including a bare print flag, until verified claimant assertions and comparable rules exist.

Quote snapshots are UTF-8 JSON objects containing the quote metadata (excluding manifest ID/path/hash), exact amount and a readable excerpt. Metadata must match the typed quote; an excerpt must contain its literal numeric price in dot-decimal/comma-thousands notation. This is a narrow snapshot contract, not a general localized-price parser or proof of edition equivalence. Actual source adapters must validate locality/edition/format/fees before producing accepted records in M07/M08. Snapshot fixtures use example.invalid links and synthetic labels.

Export copies saved frame and quote files into the output directory. Reports use escaped text and validated source URLs, and link to evidence, declared measurement records and ownership exclusions. JSON contains the complete metadata. Atomic revision freezing and reliable retry recovery remain M10 work.

## Verification

29 tests passed with Python 3.13.1 and Pydantic 2.14.0 using the existing isolated interpreter. Coverage includes unknown keys, exact decimal rounding/zero, distinct physical copies, duplicate IDs, source/condition/currency/FX exclusions, literal quote snapshots, range validity, art gating, unsupported identity, missing/conflicting measurements, area-unit conversion, safe paths/hash failures, structured stage errors, HTML escaping, portable export after source removal, and overwrite rejection.

The first export test exposed a default Windows text-decoding mismatch; reads now explicitly use UTF-8. A new foreign-measurement guard required removing stale measurements from the empty-inventory test fixture. Both failures are corrected; final suite passes.

Smoke command (fresh output directory):

```powershell
.\.local\reference-env\Scripts\python.exe -B -m library_claim --country IN --currency INR --currency-decimal-places 2 --exclusion-basis missing_any_component --shelf-run-basis sum_spine_thickness --output runs/m01-review-ready
```

Expected and verified synthetic results: 3 owned books, 2 titled / 1 unreadable, new subtotal 10.01, used subtotal 4.10, item range 20.20–30.30; 3 financial exclusions; borrowed book excluded separately. Full shelf run null, measured subtotal 0.02 m. Room dimensions/areas remain null. Packet status partial with review reasons. Temporary inputs are removed after export, demonstrating the exported bundle's independence.

Review artifacts: `runs/m01-review-ready/report.html`, `claim_packet.json`, `frames/fixture.png` and four saved synthetic quotes. These local outputs are ignored by Git. API calls/cost for M01: zero. Reference code is unchanged. The reference's live transport/audio logic remains planned reuse in M06; M01 uses new deterministic contracts because the reference insurance-note totals do not satisfy the library packet schema.

Next proposed part after review: M02a, durable storage of one real high-resolution frame with metadata/hash and reopen validation. **Awaiting user review; no automatic progression.**
