# Capacity planning that can account for its mistakes

A useful capacity plan must survive contact with demand, failures and constraints.
This module connects demand forecasting, frozen allocation reservations, existing
scheduler policies and SQL variance review into one reproducible experiment.
It makes planning assumptions and deviations inspectable instead of hiding them
inside a utilization headline.

**Scope: an offline, synthetic engineering example.** It forecasts aggregate
inference demand; training allocation and retention use historical fill/progress
ratios. It does not forecast training-job arrivals or demonstrate a live fleet,
production savings, real hardware fitness or execution authority.

## Reproduce the full 30-day loop

Python 3.12 is the tested interpreter. From the repository root:

```sh
python3 -m venv /tmp/capacity-plan-venv
/tmp/capacity-plan-venv/bin/pip install -r capacity/planning/requirements.txt pytest
/tmp/capacity-plan-venv/bin/python -m pytest capacity/planning/test_planning.py -q
/tmp/capacity-plan-venv/bin/python -m capacity.planning demo --output /tmp/capacity-plan-30d
```

The first 14 days are history. A plan is frozen at hour 336, before any of the
remaining 16 days are generated for replay. The warm-up remains identical across
scenarios. The existing simulator executes the future reservations and supplies
observations; its original default policies and published experiments are unchanged.

Outputs include `history.json`, `forecast.json`, `allocation-plan.json`, scenario
actuals and variance JSON, `ledger.duckdb`, `comparison.json`, `REPORT.md` and a
completion manifest with file hashes. Output directories are never overwritten.
A failed build leaves no completed bundle. A hard process termination may leave
an unpublished staging directory and `.lock`; inspect these before removing a
stale lock. The lock serializes cooperating publishers, not arbitrary writers.

## Separate lifecycle commands

`observe --config history-config.json --output history-output` generates hourly
synthetic observations. Set its configuration `horizon_days` to the history length.
The future config must use the same scenario settings with a longer horizon.

```sh
python -m capacity.planning plan --config future-config.json \
  --history history-output/history.json --cutoff-hour 336 --output frozen-plan
python -m capacity.planning replay --plan frozen-plan/allocation-plan.json \
  --scenario combined --output replay-output
python -m capacity.planning reconcile --plan frozen-plan/allocation-plan.json \
  --actual replay-output/actual.json --ledger review.duckdb
```

All commands also expose `--help`. `plan` supports `--method seasonal|last_value`,
`--headroom`, `--bias`, `--rate` and the existing `--policy` names. Its hourly
inference reservation overrides that policy's inference reservation during the
future window; training admission, resize and preemption remain owned by the
existing simulator. Thus it is a **frozen-reservation variant**, not an unchanged
execution of the named policy. Intra-hour inference demand still varies.

`reconcile` prints an explicit result: `changed`, `no_change`, `incomplete`, or an
`invalid` error. Exit codes are 0 for valid complete results, 3 for incomplete
actuals and 2 for invalid inputs. A complete demo succeeds even though its
intentional missing-event example is incomplete.

## What-if scenarios

| Case | Intervention after the cutoff | Question |
|---|---|---|
| baseline | Original synthetic events | How far does the frozen plan drift? |
| demand_surge | Demand ×1.6 during hours +24 through +48 | How much inference demand goes unserved? |
| capacity_outage | Usable capacity zero during hours +36 through +42 | Do allocation and loss accounts remain consistent under complete scarcity? |
| price_spike | Allocated-GPU-hour tariff ×3 during hours +24 through +48 | Can cost change without a compute change? |
| combined | All three interventions | Does the joint result reconcile without adding overlapping effects? |
| forecast_underestimate | Separate plan with point forecasts ×0.7 | Does apparent training gain come at inference's expense? |
| higher_headroom | Separate plan with 30% rather than 10% headroom | What is the reservation-versus-demand-service tradeoff? |
| missing_event | Remove the first actual hour | Does incomplete evidence suppress totals? |

Windows are half-open. An outage is an imposed capacity ceiling, not a simulated
physical diagnosis. Higher-level failure mechanisms retain the simulator's
existing assumptions. The demo requires at least three future days so every
intervention window is exercised. No intervention changes pre-cutoff history.
`comparison.json` compares alternative plans against the same baseline scenario;
ordinary variance reports compare actuals against each scenario's own plan.

## Forecast and allocation contracts

- Seasonal baseline: average the last three observed occurrences of each hour of
  day. Last-value persistence is the comparator. Neither sees future actuals.
- Rolling one-step MAE is reported for both methods. The 90th-percentile absolute
  rolling residual supplies a descriptive band, **not calibrated confidence**.
  This is not a backtest of a 16-day fixed-origin forecast. Bias perturbation does
  not retrain the historical baseline or establish interval coverage.
- Planned supply uses declared power windows; future stochastic failures are
  unknown. Inference gets forecast plus headroom, capped at supply. Remaining
  training budget is distinct from expected allocation (historical fill ratio)
  and expected productive progress (historical retention ratio).
- The plan's content hash binds config, history hash, forecasts, reservations,
  identity, rates and source/runtime provenance. Revisions create new plan IDs;
  they do not overwrite a previous plan. Hashes identify bytes, not trustworthy
  authors, observed truth or execution approval.
- Versioned [plan](schemas/plan.schema.json) and [actual](schemas/actual.schema.json)
  schemas fix units, workload/hardware identity and the synthetic evidence label.
  Replay requires matching sources and Python/NumPy versions. Reports also record
  the analysis implementation and DuckDB version. No private paths are required.

## SQL, data quality and variance semantics

[`sql/schema.sql`](sql/schema.sql) stores immutable artifact payloads and uniquely
keyed hourly records. Ingestion validates schemas, identities, finiteness,
capacity bounds and content hashes before a transaction. Retrying an identical
artifact is idempotent. Late observations require a new complete snapshot; the
previous incomplete snapshot stays available. Duplicate, unordered and
out-of-window hours are refused. Direct row corruption is detected against the
stored artifact before reporting. DuckDB is a single-process analytical ledger;
this is not a concurrent fleet event-ingestion service.

[`sql/quality.sql`](sql/quality.sql) checks relational completeness.
[`sql/variance.sql`](sql/variance.sql) performs the actual analytical joins and
attribution; SQL is not a decorative export of Python totals.

The additive identity is:

```
productive = nominal - unavailable - idle - inference reservation waste
             - training overhead/discarded progress
```

The report attributes productive delta to changes in those buckets. Demand error
is shown separately: adding it as another loss would double count. These are
accounting effects, not causal explanations or independent failure mechanisms.

Costs are **synthetic USD per allocated GPU-hour**, with:

```
cost delta = (actual allocation - planned allocation) × planned rate
             + actual allocation × (actual rate - planned rate)
```

This convention assigns the interaction to the rate effect. It is not energy
spend, TCO, revenue or savings versus a clairvoyant oracle. Missing observations
produce null aggregate totals, never a fabricated zero. Equal aggregate totals
alone do not earn `no_change`: cancelling hourly changes remain visible.

Failures can reverse previously credited training progress, including progress
from before the frozen window. Hourly **net** training productivity may therefore
be negative. `work_lost_gpu_h` records the reversal separately and allows checks
on gross new progress. Clipping negative net progress would falsify conservation.

## Interoperability and deliberately unchecked constraints

The module extends `sim.simulator.Simulation` through optional observation,
reservation and scenario-factor hooks. It imports existing configuration
validation rather than introducing another scheduler. Existing capacity replay,
placement and admission APIs remain usable alongside it.

Aggregate hourly quantities cannot truthfully populate a per-job `span-contract`
envelope or a compute-power migration decision. Geometry, topology, thermal,
host/I/O, tenancy and operator permission remain **unchecked**, explicitly in the
report. Use [`capacity.placement`](../placement.py) for an actual supplied job
and plant; its verdict does not certify this fleet projection. Likewise,
compute-power's useful-GPU-hour/migration economics cannot be silently substituted
for this allocated-GPU-hour tariff. A future measured integration needs aligned
job identity, observation windows, units and calibrated cost inputs first.

Do not multiply network efficiency or detailed reliability factors into this
ledger: their loss boundaries overlap with the simulator's progress accounting.
No new generic controller, duplicated physics model or execution permission is
introduced by this module.

## Verification and measured limits

```sh
python -m pytest capacity/planning/test_planning.py -q
python -m capacity.planning.benchmark > /tmp/capacity-planning-benchmark.json
```

Tests use independent hand calculations for variance, exercise all three policies
across multiple seeds, check no-lookahead history boundaries, price-only changes,
full capacity loss, altered/rehashed inputs, missing and late observations,
transaction rollback, direct ledger corruption and interrupted/duplicate output
publication. The original simulator's defaults are checked unchanged with and
without observation enabled.

The bounded benchmark records replay, ingestion and checked-report times at 7,
30 and 90 simulated days, with process peak RSS and source hashes. It is one
local trial per size, not a distributed throughput or production latency claim.
The CLI retains the existing 366-day replay bound. Hourly aggregation keeps the
ledger proportional to the time horizon; job-level event analytics and real
telemetry ingestion are separate work.
