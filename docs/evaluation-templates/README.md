# Blank M11 inputs

Copy these to an evaluation directory outside the runtime capture store. Empty strings/nulls/empty lists are placeholders, not measured values. They intentionally fail required-field validation until completed. No real truth, policy choice, timing, price or demo is supplied here.

| File | Fill from |
| --- | --- |
| `truth.json` | Complete independent physical inventory, preselected 20 spine/15 price samples, source availability and tape geometry |
| `policy.json` | Explicit confidence threshold/primary denominator; supported conservative comparison aggregation |
| `config.json` | Actual code/device/model and recognition/calibration/valuation/area settings; no keys |
| `assessment.json` | Post-run independent one-to-one physical matching, title/price-basis judgments, actual timing/cost/stage records and second-country IDs |
| `delivery.json` | Local archive/results paths, hashed architecture/demo/setup/failure evidence, optional real repair/held-out archives/results |
| `*.schema.json` | Exact typed fields, bounds and nested row shapes generated from the implementation |

In truth, `owned` determines scope; independently established `legible` determines the title denominator. `spine_sample`/`price_sample` select samples before predictions. Book author/publisher, orientation, edition evidence and measurement uncertainty can be recorded even when unknown. Original tapes/source screenshots should be linked by the evidence fields; these references are human provenance, not automatically opened or authenticated by the scorer. Use timezone-aware ISO timestamps and centimetres/metres/m² as named.

The configuration snapshot is supplied by the operator; the tool does not automatically prove it was applied at runtime. Hashes bind files and exact content, not independence or physical truth. Demo/root-cause/private-repository assertions require human review.

[Full procedure and scoring conventions](../45-m11-group-review.md).
