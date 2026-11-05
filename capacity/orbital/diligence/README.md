# Capacity Orbital diligence

Original standard-library software for two agent-callable tools:

- **`lifecycle_cost`**: discounted lifecycle expenditure and useful fleet capacity.
- **`check_claim`**: assumption-bound power, battery, link and steady-state thermal consistency.

Both tools use explicitly synthetic inputs. They do not verify a vendor, recommend
an investment, authorize actions, execute workloads or certify hardware. Unknown
physics or missing assumptions produce **unknown**, not a favourable result.

## Run or call directly

```sh
python3 -m capacity.orbital.diligence --manifest
python3 -m capacity.orbital.diligence --request capacity/orbital/examples/diligence-lifecycle.json
python3 -m capacity.orbital.diligence --request capacity/orbital/examples/diligence-thermal.json \
  --output /tmp/new-thermal.json --html /tmp/new-thermal.html
python3 -m unittest capacity.orbital.test_diligence -v
python3 -m capacity.orbital.diligence.benchmark
```

```python
from capacity.orbital.diligence.api import dispatch
from capacity.orbital.diligence.fixtures import lifecycle_example, request
response = dispatch(request('lifecycle_cost', lifecycle_example(), 'diligence-1'))
assert response['execution_performed'] is False
```

Requests have exactly `schema`, `id`, `tool`, `input`. Schema is
`capacity-orbital/diligence-request-v1`; unknown tools, fields and versions refuse.
`dispatch_json` also rejects duplicate keys and nonfinite JSON numbers. The API
is stateless: request IDs are trace labels, not durable idempotency records.
Corrected inputs may reuse a label but receive a different input/outcome digest.
Identical inputs and source produce identical outputs. No JSON callback, file
path, arbitrary code, authority token or network destination is accepted.

A response binds canonical input, source and outcome hashes. The source manifest
covers this package plus the imported base contracts/output helper. Hashes are
not signatures or trusted attestation. Caller parameter provenance is preserved,
not independently authenticated. `authority_disposition` always states that no
authorization is granted; `promoted` and `execution_performed` are always false.
Integration with task107 is a future reviewed composition step; its source and
that of task106/task108 were not modified.

## Lifecycle contract and mathematics

`capacity-orbital/lifecycle-v1` has exactly the fields in the lifecycle example.
One currency is declared using an uppercase three-letter unit, with all cash
flows in that same currency. v1 does not establish ISO validity or convert
currencies. Mixed currencies, supplied exchange-rate fields, live rates and
conversion without provenance all refuse rather than silently mixing money.

Positive cash flows are **expenditure**. `residual` is a nonpositive credit. Each
flow has a unique ID, category, year offset, signed amount and currency.
Supported categories are development, payload, platform, launch, insurance,
operation, replacement, disposal, residual, downlink_marginal and
downlink_allocated. The initial development amount can be at year0; future
milestones carry their own explicit time. Debt proceeds, principal, interest and
revenue are unsupported. The supplied discount rate is already the capital-cost
assumption, so financing flows cannot be added and counted a second time.

At rate `r`, an amount at time `t` is multiplied by `(1+r)^(-t)`. Cash-flow times
are explicit, bounded year offsets. A cohort has count, commissioning,
retirement, per-node kW, utilization and availability. In annual bucket `(y-1,y]`,
useful kW-years are:

```
max(0, min(y, retirement) - max(y-1, commissioning))
    * count * capacity_kw * utilization * availability
```

Each bucket's output is discounted at its year-end using the **same discount
function and time origin** as cash flows. This declares an annual output-credit
convention: partial-year output is credited at the end of the containing year,
not continuously. No output is attributed before commissioning or after
retirement. Replacement cohorts do not exist until explicitly commissioned.
Utilization/availability are supplied constants; no survival distribution is
invented or inferred from a terrestrial statistic.

The ratio is discounted expenditure / discounted useful kW-years. Undiscounted
figures are retained separately. Zero useful output gives `ZERO_USEFUL_OUTPUT`
and a null unit cost. Negative net costs from declared residual credits retain their cash-flow totals
but return `unknown/NET_CREDIT_REVIEW` and a null unit cost. They cannot be used
to claim that lower utilization improves economics. No profit, viability or
suitability conclusion follows from residual assumptions.

**Hand oracle:** $1,000 at year0 plus $100 at years1and2, at10%, has present cost
$1,173.553719. One useful kW-year at each year-end has discounted output1.735537,
so the ratio is $676.190476 per discounted useful kW-year. Halving utilization
halves that denominator and doubles the ratio without changing cost.

Prepaid/allocated downlink expense is separate from incremental marginal
expense. A prepaid operator can have positive allocated expenditure and zero
marginal expense. Callers must not enter the same invoice under both categories;
the software cannot establish invoice authenticity or identify semantic copies
with different IDs. The model provides no automatic savings/profit claim.

Bounds:1MB/request;1–100integer horizon years;1–1000cash flows;0–200cohorts;
1–1,000,000nodes/cohort; rate0–1; utilization/availability0–1. Counts and byte caps
apply together. All values and derived outputs must be finite. Positive cash flows, useful capacity
or transfer durations that underflow supported numeric resolution refuse. Fractions of a
year are supported for flows and cohort commissioning/retirement. No inflation,
tax, financing structure or stochastic uncertainty is inferred.

## Claim contract and interpretation

`capacity-orbital/claim-v1` has `schema`, `name`, `kind`, `parameters`, `provenance`.
A supported model requires the parameters below. Missing or null assumptions
return `unknown/MISSING_ASSUMPTIONS`; invalid present values still refuse, even
if another assumption is missing. Unknown parameters refuse. Inputs must be
nonnegative, with strictly positive denominators/efficiencies and fractions≤1.

| Kind | Required assumptions and equation |
|---|---|
| power | generation_kw, auxiliary_kw, compute_kw, conversion_efficiency. Available compute power = generation × efficiency − auxiliary. |
| battery | initial_kwh, reserve_kwh, load_kw, discharge_efficiency, claimed_duration_h. Available duration = (initial − reserve) × efficiency / load. Initial energy below reserve is inconsistent. |
| link | data_gb, goodput_gbps, window_s, claimed_duration_s. Decimal GB ×8/Gbps = seconds; both contact and claimed duration must accommodate it. |
| thermal | heat_w, temperature_k, sink_temperature_k, emissivity, fin_efficiency, absorbed_flux_w_m2, area_m2, area_basis, view_factor. A panel_footprint additionally requires emitting_faces (1or2); emitting area must not repeat faces. |

Thermal screen uses original Stefan–Boltzmann arithmetic:

```
A_emitting * (sigma * emissivity * fin_efficiency * view_factor
              * (T^4 - T_sink^4) - absorbed_flux_w_m2)
```

`A_emitting` is the declared total emitting area, or explicitly supplied panel
footprint × emitting_faces. Absorbed flux is per emitting area. Sigma is
5.670374419e-8W m^-2K^-4. This uniform, steady model omits transient heat storage,
coolant resistance/pump limits, geometry detail and actual mission exposure.
Panel footprint without face count remains unknown. Large absorbed flux can
produce negative net rejection and an inconsistent screen; it is never clamped
into favourable cooling. Unsupported radiation or transient qualification is
unknown, never certified.

Independent hand values: battery1kWh/reserve0.2/load0.8/efficiency1 gives1hour;
1decimalGB at1Gbps needs8seconds;1m² emitting at300K to0K with all factors1
rejects459.300327939W before absorbed flux. These are mathematical test inputs,
not plausible vendor designs or material-property measurements.

`consistent` means only that demand fits the supplied model. `inconsistent`
means an insufficient mathematical envelope. `unknown` means the selected model
or assumptions cannot decide. `refused` means malformed, unsupported-contract,
over-budget or nonfinite input/output. None is technical acceptance.

## Outputs, evidence and next integration

CLI JSON and escaped responsive HTML use the existing non-overwriting publisher.
Choose new output paths. JSON records predictions, assumptions, reason codes,
provenance and model identity. Refused requests exit2; screened unknown results
exit0 with their unknown status intact. An OS error prints REFUSE and exits2.
Output publication is not claimed crash-atomic across multiple files.

`../evidence/diligence/` retains tests, source-bound examples and bounded scaling.
The test-only workflow runs inherited planner/dynamics plus diligence tests.
No software install, external AI service, paid data, security change or network
operation is added. Parameters alternatives are caller-authored sensitivities,
not automatic calibration or candidate promotion.

Future composition must map actual fleet/dynamics/network outcomes into these
contracts and independently reconcile the denominators, cost scope and source
pins. Live telemetry, radiation/thermal-vacuum validation, vendor qualification,
Tool Guard runtime integration and financial decisions are not provided by this
screen. Claude reviews exact source; Dmitry accepts technical work and Ronnie
reproduces independently before release.
