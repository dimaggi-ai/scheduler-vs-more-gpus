# Task108 validation receipt

Implementer: codex (generic builder fallback applying reviewed role instructions). Exact parent/base `1aa7364a5b9bc6f818527284f6bb774b4fd831e5`, task106 candidate; this is not accepted composition.

Commands:

- `python3 -m unittest capacity.orbital.test_network capacity.orbital.test_dynamics capacity.orbital.test_orbital -q`: 47 tests passed.
- Existing planning environment Python `-m pytest -q capacity/tests calculator/test_stranded_capacity.py sim/test_sim.py sim/test_validation.py capacity/orbital/test_orbital.py capacity/orbital/test_dynamics.py capacity/orbital/test_network.py`: 127 tests and21 subtests passed in9.18s before two additional network regression tests; the final47-test orbital run includes those additions.
- `python3 -m capacity.orbital.evidence.network.reproduce`: retained source-bound success, outage refusal, corrected durable-storage case, contention, and dynamics success/refusal plus measured scaling. Scaling measures one traced run per workload, excludes CLI/report IO and is not an SLO.

Hand-oracle outcomes: 1 decimal GB/1 Gbps = 8 s; A→B0..8 and B→G10..18 delivers at18 s. Propagation shifts receiver occupancy. Volatile B outage8..10 refuses, explicit durable storage preserves the buffer and permits the corrected candidate. Source/relay/destination buffer limits and shared terminals/physical links are enforced. Refused routes preserve all committed reservations/costs. A two-node1kW fleet over300s with one100s outage integrates500kW-seconds. Four endpoint transfer spans consume32kW-seconds; the same feasible network plan fails a constrained battery scenario.

Pre-freeze defects corrected with regressions: positive transfer durations/propagation below timestamp resolution now refuse rather than report instantaneous positive bytes; identical existing buffer reservations are included instead of accidentally skipped. Initial repeated reservation scans exhausted the200k operation budget for50jobs×2contacts (observed0.0647s,42,472 traced bytes, no output); sorted conflict traversal now completes that case. Larger100/200-job and50×50-contact cases retain explicit budget refusals in scaling.json. No silent partial report is returned on budget failure.

Hosted CI workflow `orbital-network.yml` adds only read-only test execution; actual hosted status is recorded on the PR and is not inferred from local tests. All source inputs are synthetic. No live connections, actual command permissions, flight authority, measured hardware, probabilistic reliability or compliance certification is claimed.

Browser visual QA remains blocked by the existing local-preview security restriction. Static HTML escaping, units and responsive layout are checked; no screenshot or visual-readiness claim. Independent Claude source review, Dmitry isolated failure qualification, Ronnie reproduction and integrated platform acceptance remain open. Timing/cost/human intervention not measured is unknown.
