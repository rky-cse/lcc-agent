# Identification and source-backed valuation

Implemented boundaries: [M05a crop/literal text](24-m05a-review.md), [M05b1 work candidates](25-m05b1-review.md), [M05b2 reviewed work](26-m05b2-review.md) and [M05b3 edition review](27-m05b3-review.md). Crops/regions trace to exact originals. Only explicit reviewer commands accept supported work/edition records on physical tracks. Edition acceptance requires a confirmed visible ISBN and consistent work/title/catalogue physical format plus a declared binding. Visible metadata and claimant assertions retain separate provenance; confidence/prices remain unknown. Synthetic reading/review smoke and public retrieval checks passed their narrow boundaries; the real edition record's missing format correctly blocked acceptance. Production language coverage and actual shelf/edition precision remain unverified.

Status: M04a uses Gemini 3.1 Flash-Lite to propose individual spine polygons from one saved shelf image, with local validation and provisional count/review. Live synthetic smoke passed, actual-shelf accuracy unverified. Physical tracking, assisted matching, saved-crop reading, work/edition candidates and explicit review are implemented. Automatic landmark acquisition, integrated recognition, real edition-format coverage, locale sources and price policies remain pending. See [M04a](20-m04a-review.md) and subsequent review records.

## Physical detection before identity

1. Identify shelf units/rows and persist their spatial IDs across views.
2. Propose book spine polygons using a pretrained detector/segmenter and, if helpful, classical shelf/spine boundaries. Evaluate candidates on the actual capture before selecting a dependency. General object detection does not prove reliable individual-spine segmentation.
3. Include upright, diagonal, flat and stacked orientations. Preserve sharp observations and uncertain splits/merges. Fully occluded books cannot be inferred as individual seen copies.
4. Map observations into stable shelf coordinates using validated image registration or poses. Match physical position, outline, visual appearance and temporal overlap. Do not deduplicate by title, author or ISBN.
5. Maintain a physical track with all observations, selected representative frame and uncertainty. Duplicate copies remain distinct; repeated views of one copy merge.

A multimodal model's aggregate count can flag disagreement, but final count must be auditable against physical tracks. Bookends, decorative spine-like strips, multi-volume sets, tightly touching books and horizontal piles need explicit regression cases. An unresolved count/segmentation region stays visible in review; no invented hidden copies to improve the count.

## Spine reading and catalogue resolution

Read only what is legible in a saved spine crop. OCR produces text spans with coordinates, orientation and confidence; a vision model may help read/structure that same crop, returning field evidence and blanks. Rotate vertical/horizontal text as needed. Agreement across independent views supports a field; disagreement remains a review reason. Enhancement is a derived image with a recorded transform, not permission to fabricate lettering.

Search catalogue candidates from supported title/author/publisher fragments. Preserve search parameters and responses. Match visible text, language, author, volume number, physical format and edition indicators. A first search result is a candidate, not proof. Reject contradictions and retain multiple plausible candidates when evidence cannot distinguish them.

Work identity and edition identity are separate decisions. A correct title does not prove edition, year, binding or ISBN. Spine-visible metadata or explicit claimant assertion can support edition claims, with provenance; claimant "first edition" is an assertion needing review/appraisal, not independent authentication. Unreadable spines stay `unidentified`; dimensions/count are independent of OCR success.

Candidate catalogue providers: Open Library exposes work and edition records; Google Books supports bibliographic lookup. Do not borrow a likely edition's ISBN merely because a title matches. [Open Library Search](https://openlibrary.org/dev/docs/api/search), [Open Library Books API](https://openlibrary.org/dev/docs/api/books), [Google Books API](https://developers.google.com/books/docs/v1/using).

Configure language support after the user identifies the spine languages. Set confidence thresholds using frozen calibration data, then report high-confidence precision on held-out data. Confidence combines visible-text support, catalogue contradictions/agreement and edition specificity, not model certainty alone. Do not raise identification coverage by relaxing the confidently-wrong gate after seeing the evaluation set.

## Valuation is retrieval, matching and arithmetic

The model may propose searches and explain equivalence. A source adapter retrieves actual pages/API responses and extracts literal quoted prices into validated quote records. A retrieval timestamp and URL alone do not support an amount that is absent from the retrieved evidence. Search snippets, product recommendations and model memory are not published quote evidence.

Primary/second country and available search/retailer access must be confirmed before selecting adapters. Verify usable coverage for both new physical replacements and used physical books early. Retain a readable permitted source response or quote excerpt containing the literal price and matching metadata, plus its hash, so a reviewer can reconstruct the selection even if a listing changes later. A hash alone is insufficient; inability to obtain auditable quote evidence produces unknown/review. Record retrieval failure/rate limits honestly.

| Valuation | Eligible source/match | Unknown/failure behavior |
| --- | --- | --- |
| Book replacement | In-stock local new physical edition or clearly disclosed current equivalent physical edition/format | No valid equivalent/source → no amount |
| Book used | Sourced local physical used copy matching work/edition sufficiently; declared comparable condition | Insufficient copy/condition match → unavailable or review |
| Non-book exact | Legible model or strongly supported identical product, local available quote | Unproven identity cannot become exact model pricing |
| Non-book range | Multiple defensible local comparables with material/size/function match and explicit aggregation | Weak category-only extremes cannot produce a range |
| Foreign fallback | Actual foreign physical quote + supported dated FX + explicit foreign-market label | Missing quote or FX pair/date → no conversion |
| Appraisal | No auto-published amount; evidence and specialist review reason only | Indicative retrieval may trigger appraisal but is not a claim valuation |

Used asking prices and completed-sale evidence represent different things. The source type must be disclosed and matched to hand-checked ground truth; whether asking prices satisfy the intended used-value policy is an open question. If only one legitimate used quote is available, publish that quote basis and lower coverage/confidence rather than invent a depreciation formula.

Google Books `saleInfo` concerns the Google eBookstore and includes an `isEbook` flag; it cannot be adopted as physical-book replacement pricing. [Google Books Volume contract](https://developers.google.com/books/docs/v1/reference/volumes). eBay is a conditional option for physical listings; production access and marketplace coverage must be verified, and sandbox data cannot establish market value. [eBay production requirements](https://developer.ebay.com/api-docs/buy/static/buy-requirements.html), [eBay Browse search](https://developer.ebay.com/develop/api/buy/browse_api/item_summary/search-filters).

Cache catalogue and price retrievals with source-specific freshness and rate limits. Open Library documents an identified-client rate limit; identify the application and enforce it rather than launching unrestricted parallel search. [Open Library API usage](https://openlibrary.org/developers/api).

## Price policy and FX

Preserve source country, original currency/amount, condition, physical format, availability and fees. Main amounts are in sweep currency only. Every quote states condition: "new" for a replacement where appropriate; used condition is a confirmed default or observed/declared condition, never silently assumed. Tax/shipping/import treatment needs user confirmation and is consistent between automated and hand-checked comparisons.

Foreign fallback first documents that configured local searches produced no eligible result. Fetch a dated FX record, store effective date and retrieval time, apply `target_amount = original_amount × rate` using Decimal, round by the approved currency policy and label converted. A candidate FX service is Frankfurter, subject to currency coverage/access verification. A converted foreign quote remains a foreign-market estimate. [Frankfurter documentation](https://frankfurter.dev/).

For a sourced range, define selection and aggregation before evaluation: exact model uses low=high; an equivalent range uses defensible accepted comparables, with minimum/maximum or another approved robust rule stated explicitly. Outliers, irrelevant luxury variants and damaged/parts-only listings cannot inflate or deflate the range. No range policy is finalized here.

## Appraisal and non-book rules

Rare, signed, antiquarian, first-edition claims and supported values above a configured threshold trigger review before valuation publication. Threshold currency/amount is unresolved. Visible signals are tentative; inability to authenticate is itself a reason. A claimant correction such as "it is signed" immediately revokes prior automated prices and invalidates totals.

Art/portraits default to appraisal. Ask "Is that an original or a print?" If unanswered/original, retain appraisal status. Explicit print assertion can permit a sourced equivalent print/frame quote with that rationale; it does not establish the artist/model/design. Do not auto-price unknown collectibles.

Track shelving units, furniture, coffee equipment, lamps, rugs, electronics, framed art and decor as physical items. Record material/brand/model only when visible or asserted with a source. Approximate non-book dimensions still need a method and uncertainty; unseen depth stays unknown. Duplicate views merge spatially. Define component versus set counting before ground-truth annotation (for example, table/chairs and framed print/frame).

## Second-country demonstration

Select 10 identified physical tracks before repricing. Preserve their evidence, work/edition IDs and appraisal policy. Run valuation independently with the second country/currency/source settings and retain both result sets. Report local/converted/unavailable components and condition/fees basis. Never simply relabel the first country's numbers or use FX when a valid configured local quote is available. Missing second-country values remain visible and indicate insufficient coverage.

## Required checks

Contract/unit tests cover unreadable text, ambiguous catalogue editions, contradictory metadata, duplicate copies, title correction invalidation, e-book/wrong-format/wrong-currency/out-of-stock quotes, no literal source amount, missing dates, missing FX, unsupported currencies, signed correction, print/original gating, stale jobs, source outages and range bounds. Online smoke checks open actual source evidence, verify physical format/country/currency and compare at least one new/used component manually. Fixtures test logic; they do not prove live source coverage.
