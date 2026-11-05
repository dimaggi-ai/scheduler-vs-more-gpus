# Capacity Orbital — coupled-state feasibility (synthetic research tool)

This module evaluates battery and temperature feasibility on one shared interval clock. It is an agent-callable planning tool, not satellite control, actual permission enforcement, a validated spacecraft digital twin, or acceptance of a product. It is stacked on the unaccepted task105 planner source.

## Run and integrate

```
python3 -m capacity.orbital.dynamics --demo nominal --output /tmp/orbital-dynamics.json --html /tmp/orbital-dynamics.html
python3 -m capacity.orbital.dynamics --demo reserve
python3 -m capacity.orbital.dynamics --demo corrected
python3 -m unittest capacity.orbital.test_dynamics -v
```

Exit 0 means predicted feasibility; exit 3 is a valid held/refused diagnostic report; exit 2 is malformed input or output failure. Existing output files are not overwritten. The inherited publisher stages files and rolls back its own published files on ordinary failure, preserving foreign files; multi-file delivery is not process-crash atomic. Choose new output paths for a retry. Browser rendering is not yet verified: the desktop browser blocked local preview. Static checks verify escaping, units and responsive CSS only.

`evaluate(proposal, scenario, source_sha256=None)` returns a new `capacity-orbital/dynamics-report-v1` object without changing inputs. Missing source digest is explicitly unbound; CLI hashes the imported parent module source and all dynamics Python sources. Receipts bind the validated input, predicted outcome, event-derived ledger and code digest. A caller-supplied digest is a claim, not a signature. No observed outcome or billing is implied.

The JSON input is a bundle with exactly `scenario` and `proposal`; see `../examples/dynamics-nominal.json`. Scenario schema is `capacity-orbital/dynamics-v1`, with explicit seconds, kWh, kW, W, K, J/K and W/K field suffixes. Nodes declare initial battery and temperature **at t=0**. Profiles must cover [0,horizon] contiguously. Proposal `at_s` is the planning request time on that same clock, not a new initial-state epoch; events cannot precede it. Authority has `disposition` (allowed/refused/held), `valid_from_s`, `expires_s` and scope `synthetic-evaluation`. Missing, expired, future or nonallowed authority fails closed. This is only a caller-supplied planning capability, not proof of real authorization. No authority is expanded and no policy is promoted.

Stable physical refusal codes are `BATTERY_RESERVE`, `DISCHARGE_POWER_LIMIT`, `THERMAL_LIMIT`; authority codes start `AUTHORITY_`. Each node stops at its first crossing, preserving a diagnostic prefix; a refused proposal never commits scheduler state. Input structure/domain or arithmetic overflow raises ValueError rather than producing a plausible report. This v1 evaluator does not automatically generate events from the placement planner; an adapter must explicitly map those events in a later reviewed increment.

## Physics and conservation

Within each shared constant-input interval:

- Bus load = declared background + all active compute and transfer event power. Solar first supplies bus load. Excess can charge subject to the **bus-input** charge limit and efficiency, then capacity; the rest is curtailed.
- A deficit is subject to the **bus-output** discharge limit; battery withdrawal is bus deficit divided by discharge efficiency. Conversion losses are included in the kWh ledger. Initial + solar − load − loss − curtailed = final, checked with a reported floating-point tolerance.
- Temperature follows `C dT/dt = Q − G(T − Tsink)` analytically; G=0 uses a linear branch. Q is the separately declared background and event heat. Conversion losses, solar absorption and electrical waste heat are **not automatically converted into Q**. Users must explicitly represent them. This is a linear lumped model, not a nonlinear radiative-equilibrium model.
- The global boundary union covers every node profile and event. Exact analytic threshold times avoid missing a violation between sample endpoints. Equality at reserve/thermal limit is allowed; numerical crossing tolerances are 1 ns and 1e-9 K.

Synthetic solar/sink/load profiles are assumptions, not ephemeris, geometry, measured hardware, radiation qualification or mission data. No clinical, defence or financial safety claim follows. Nonlinear radiators, degradation, storage recovery, communications and service quality require later modules and independent validation.

## Bounds and reproducibility

At most 128 nodes, 10,000 total profiles and 10,000 events, horizon ≤31,557,600 seconds; CLI files ≤8 MiB. Shared clock × nodes is capped at 100,000. Active event summation work is capped at 1,000,000 terms. Event sums are recomputed with `math.fsum` at boundaries so a small ongoing load survives removal of a much larger event. This deliberate bound avoids an unbounded overlapping-event quadratic workload. Validation caps are not performance promises. Floating-point values with extreme scale separation still have ordinary double-precision limitations.

Tests include independent battery/thermal hand calculations, segmentation, simultaneous transfer heat, remaining-load cancellation, overflow, authority, deterministic receipts, and CLI refusal/recovery. Local timing/memory observations are in `../evidence/dynamics/scaling.json`; they are neither SLOs nor hardware comparisons. Hosted coverage is provided by the added `Orbital coupled-state contracts` CI step once this branch's workflow run succeeds. Peer review and designated acceptance remain open.
