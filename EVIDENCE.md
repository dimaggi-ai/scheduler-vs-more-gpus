# Evidence and provenance

Run from this repository root:

```sh
python tools/validate_evidence.py evidence.json
```

The manifest covers selected consequential inputs, headline results and contract
limitations, not incidental constants. Classifications apply to results separately
from inputs. A simulated result stays simulated even with calibrated inputs.

Local sources and artifacts are SHA-256 bound. A source change must trigger a
review of the dependent claims and regeneration before updating its hash. Do not
refresh hashes just to silence CI. Referenced source ledgers retain citation and
reuse qualifications; structural validation is not independent source verification.

The validator is a byte-identical vendored copy of research/evidence/validate.py,
so CI works without fetching an unpinned second repository. The research portfolio
check tests copy parity. Synchronize copies when changing the convention.

Qualitative contracts use a statement rather than manufacturing numerical results.
Numeric valid_bounds are basic sanity limits, not empirically supported ranges.

## Forecast → frozen allocation → variance example

The [planning lifecycle](capacity/planning/README.md) adds synthetic hourly
observations, transparent inference-demand baselines, frozen reservations and SQL
accounting. `python -m capacity.planning demo --output /tmp/capacity-plan-review`
creates source-hashed plans, actuals, variance reports and a completion manifest.

Forecast residual bands are descriptive; rolling one-step errors do not validate
a multi-day fixed-origin forecast. Training uses historical fill and retention
ratios, not a job-arrival forecast. Costs use a declared synthetic allocated-GPU-hour
tariff. Scenario differences and accounting decompositions are not production
savings, causal attribution, operator acceptance or authorization. Local benchmark
results must retain their source/runtime record and tested hourly record counts.
