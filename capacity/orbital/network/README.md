# Netcap Orbital — synthetic contact and fleet planning

This bounded module adds shared contact routing to Capacity Orbital. It is a pure agent-callable tool for supplied synthetic networks, not a live satellite network, orbital propagator, flight controller, compliance decision or qualified hardware model. It is stacked on the unaccepted task106 candidate. Names follow the existing Capacity/Netcap family; no existing product is renamed.

```
python3 -m capacity.orbital.network --demo relay --output /tmp/network.json --html /tmp/network.html
python3 -m capacity.orbital.network --demo outage
python3 -m capacity.orbital.network --demo corrected
python3 -m unittest capacity.orbital.test_network -v
```

Exit 0: all jobs have predicted delivery. Exit 3: at least one job refused, with a valid diagnostic report. Exit 2: malformed/unsupported input, arithmetic or operation-budget refusal, or output failure. The shared safe publisher never overwrites existing output; ordinary multi-output failures roll back only its own created files. Process-crash atomic delivery is not claimed. CLI input uses the existing bounded 8 MiB JSON reader; no network calls or downloads occur.

## Contract and routing

`plan_network(scenario, source_sha256=None)` accepts `capacity-orbital/network-v1`; examples are in `../examples/network-*.json`. Every node has identity, jurisdiction, buffer in decimal GB, commissioning/retirement, declared unavailable intervals, an explicit durable-storage flag, available capacity in kW, terminal identities and declared transmit/receive electrical power and heat. Directed contact records name endpoint terminals, shared physical link identity, transmit window, goodput in Gbps, propagation in seconds and cost per GB in the caller's one consistent input currency. Different links may share a terminal; the same link ID may describe only the same endpoint pair.

Jobs specify release/deadline, decimal GB, endpoints and allowed node jurisdictions. These are planning filters, **not regulatory certification**. Provenance is explicitly synthetic. No geometry, optical weather, interference or measured reliability is derived from these fields.

Jobs are considered by `(release_s, id)`. For each, a bounded earliest-arrival search explores simple paths with deterministic contact ordering. It schedules the earliest conflict-free opportunity for each contact, and reserves a completed path only after all hops and buffers fit. No job splitting, compression, retransmission, coding or partial delivery is modeled. The policy is greedy across jobs and may conservatively refuse a feasible route: it does not deliberately delay a feasible hop to seek a later buffer opportunity, revisit nodes, optimize global throughput or retry previously refused jobs. No optimality claim. Positive transfers or propagation below floating-point timestamp resolution are refused; completion is rounded outward where necessary and resource conflicts are rechecked.

One decimal GB at one Gbps takes eight seconds. A hop transmits on `[t,t+d)` and receives on `[t+propagation,t+d+propagation)`. The contact's transmit window must contain the entire transmission; receive node availability and the scenario horizon must also contain the delayed reception. All bytes must arrive before onward transmission. The physical link is reserved for the transmission, each endpoint terminal for its respective actual transmit/receive span. Power/heat uses those same spans; propagation time itself does not invent extra radio energy.

Buffers conservatively reserve the **full** job size: source from release through transmit completion; relay from first incoming receive start through onward transmit completion; destination from receive start through final arrival. This over-reserves partial-stream occupancy by design. Same-node jobs are delivered locally only if size fits their source buffer; zero-GB jobs are explicit no-payload delivery at release with no contact, energy, buffer occupancy or connectivity claim, but still require endpoint availability/jurisdiction. Final delivery consumes data outside this bounded model; indefinite destination retention is not claimed.

A buffer must remain commissioned and not retired for its full interval. Volatile storage cannot cross any unavailable interval; `preserve_storage=true` explicitly allows retention during an outage, but never communication during it. Availability intervals and resource reservations are half-open. A transfer completing exactly at retirement is permitted; one starting at retirement is not. Replacement is another commissioning record, never inferred instant repair. Fleet availability integrates commissioned capacity minus supplied outages in kW-seconds, not a probabilistic reliability estimate or lifetime finance forecast.

Refused trials consume no shared resources or cost. Reason codes include `NO_PATH`, `CONTACT_CAPACITY`, `NODE_UNAVAILABLE`, `STORAGE_RETENTION`, `BUFFER_CAPACITY`, `JURISDICTION`, `DEADLINE`. A reason identifies an encountered deterministic obstacle, not proof that every possible alternative has that obstacle. All estimates are predictions, not execution billing.

## Dynamics and agentic integration

`dynamics_proposal(scenario, report, authority)` reproduces the network result before exporting events. Mutated reports refuse. It emits one transmit and one receive event for each delivered hop, retaining declared kW and W. It adds no background load and does not silently turn electrical power into heat. The caller must supply a compatible dynamics scenario with the same node IDs/timeline and **exclude duplicate transfer energy from its background**. Caller-supplied authority is copied as a planning declaration; absent/held/expired authority remains fail-closed in the existing dynamics evaluator. The adapter does not provision or broaden permissions.

The example proves a network-only success can fail battery feasibility. The adapter is not a combined scheduler retry loop: a physical refusal must be fed into an explicit new candidate and independently evaluated. Observe/propose/evaluate is supported; actual execution, automatic acceptance and policy promotion are outside this module.

Input/source/outcome digests and receipts are reproducible claims, not signatures. CLI source hashing includes the network module and inherited dynamics/parent source dependencies. An API call without a source hash remains explicitly unbound. The HTML is an escaped projection of the same report. Local visual browser verification is blocked by the existing browser security policy; static checks alone do not establish visual readiness.

## Resource bounds and remaining gates

Maximum 32 nodes, 16 terminals/node, 100 outages/node, 500 contacts, 200 jobs and 31,557,600 s horizon. Search is capped at 200,000 counted operations and 10,000 queued path candidates; simple paths cap hop count at nodes−1. Reports contain at most 6,200 hops, 18,600 resource reservations and 6,400 buffer reservations from these cardinality caps. The adapter caps its exported events at 10,000 (stricter than maximal report cardinality). Budget exhaustion raises a clean refusal rather than a partial success report. These caps bound accepted work, not promise every cardinality combination is schedulable within budget. Pure API caller allocation/parsing occurs outside these budgets.

`../evidence/network/` retains successful, refused, corrected and dynamics-integrated examples, measured job/contact/node workloads, source hashes and test commands. Cost, timing and intervention fields not measured remain unknown. Hosted CI adds a dedicated test-only workflow; local success is distinct from its hosted result. Claude source review, Dmitry isolated fault qualification and Ronnie reproduction remain open. This module does not complete full-platform economics, assurance, guarded execution or mission qualification.
