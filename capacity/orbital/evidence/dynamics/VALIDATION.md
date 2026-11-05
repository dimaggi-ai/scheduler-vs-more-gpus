# Task106 validation receipt

Builder: Codex generic subagent with reviewed DIMAGGI builder role instructions. Base is task105 source `4d80c164c336ba2e1bb1cb00c8208a5ad0061384`; this is a stacked research increment, not accepted composition. Inputs are explicitly synthetic. Timing/cost and human intervention not measured are unknown.

Local checks:

- `python3 -m unittest capacity.orbital.test_dynamics capacity.orbital.test_orbital -q`: 32 tests passed.
- Existing planning environment Python: `-m pytest -q capacity/tests calculator/test_stranded_capacity.py sim/test_sim.py sim/test_validation.py capacity/orbital/test_orbital.py capacity/orbital/test_dynamics.py`: 114 passed, 21 subtests passed (8.72 s observed test-run duration).
- After bounded-read/report-only corrections, dynamics suite reran: 11 passed.
- `python3 -m capacity.orbital.evidence.dynamics.reproduce`: writes four bound JSON journeys, nominal HTML and measured scaling, retaining refused reserve/thermal cases alongside corrected and nominal cases.
- Source digest in every generated report covers parent runtime Python modules plus dynamics Python modules. Receipt binds result and input; git revision is supplied by the PR, independent of this self-contained source digest.

Independent arithmetic tests assert .9/.4 kWh nominal states, 720 s reserve crossing, .32 kWh stored from charge surplus, 1 kWh withdrawal for .9 kWh delivered at .9 efficiency, 306.321205588 K at 100 s and 69.314718056 s thermal crossing, and 2 K adiabatic heating. Further tests cover immutable deterministic evaluation, shared-clock segmentation, transfer-only heat, overlapping events, cancellation of a 1e16 kW event without losing a remaining 1 kW event, conversion/curtailment conservation, authority refusal, malformed/overflow input and CLI failure/recovery.

Hosted CI: the branch adds `Orbital coupled-state contracts` with `python3 -m unittest capacity.orbital.test_dynamics -v`; actual hosted result remains pending until the new PR run completes. Existing CI must not be described as already testing this increment.

Visual browser verification is blocked by the desktop browser's local preview security restriction. No alternate browser/server workaround or screenshot claim. Static HTML tests verify escaping and source binding; report source includes responsive layout, unit labels and table header scope. Manual visual review remains open.

Claude cross-tool review, Dmitry physical-model acceptance, Ronnie reproduction, and integration with future platform modules remain open. This report does not establish flight readiness, actual authority enforcement, automatic electrical/thermal coupling or hardware performance.
