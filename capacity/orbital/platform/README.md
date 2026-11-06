# Capacity Orbital mission workspace

One offline, agent-callable synthetic mission journey now composes compute, Netcap contact routing, fleet availability, battery/linear thermal feasibility, assumption-bound diligence and fixed-baseline improvement diagnostics. This is a review candidate, not an accepted production platform or spacecraft controller.

## Start to finish

```
python3 -m capacity.orbital.platform --demo nominal --output /tmp/mission.json --html /tmp/mission.html
python3 -m capacity.orbital.platform --demo battery
python3 -m capacity.orbital.platform --demo corrected
python3 -m capacity.orbital.platform --request capacity/orbital/examples/platform-evaluate.json
python3 -m capacity.orbital.platform --request capacity/orbital/examples/platform-feedback.json
python3 -m unittest capacity.orbital.test_platform -v
```

Use new output paths: shared publishing refuses overwrite, stages output and rolls back only its own files on an ordinary failure. Multi-file process-crash atomicity is not claimed. Exit 0 means at least one predicted feasible policy (or an evaluated tool request), 3 means all mission policies refused, 2 means malformed input/tool or output failure. No execution or payment follows any exit code.

`--mission` reads the strict `capacity-orbital/mission-v1` bundle demonstrated by `platform-nominal.json`. It binds one origin, one ground destination, exactly two compute configurations, a job-free network template, a matching-node/matching-horizon dynamics scenario, caller-declared planning authority and an explicit diligence mission identity. Prices are explicitly USD. Jobs declare raw/result/compressed sizes, four processing durations, memory, release/deadline and route-specific quality with a fixed minimum. Ground quality is a synthetic input assumption, not measured perfect accuracy.

## How the same workload is composed

Each policy is a separate counterfactual preserving every job, price, deadline and quality floor:

- Ground: send raw input through the shared network, then process on ground.
- Onboard: process on the origin, then send results through the shared network.
- Hybrid: preprocess on the origin, send compressed input, then process on ground.

One serial compute lane exists per compute node. Origin processing happens before output is released to networking. Ground processing begins only after all required input bytes arrive. The ground lane uses release/ID job order, not arrival order; this is deliberately conservative and may leave a lane idle rather than optimize ordering. Relay nodes do not compute. Arbitrary distributed compute, multiple origins or migrating jobs are unsupported and refused by the contract.

Network scheduling reuses the existing shared terminal/link/buffer implementation. Additional raw input waits and ground processing retention are explicitly included in the same storage-capacity/lifetime/outage checks. Compute memory limits apply before each stage. Network, processing and transfer energy are not counted twice: transfer events come only from the checked network adapter, compute events from the compiled stage trace, and declared background from the dynamics profile. Users must not put the same job load into the supplied background. Electrical losses do not automatically become heat; heat is explicitly declared.

All events use the same seconds clock. Useful completion is the final required processing/delivery time, not packet arrival. Whole-mission admissibility requires every job's quality/deadline and all required compute, storage, network and dynamic feasibility checks. A rejected proposal can retain diagnostic partial events and estimated costs; these are not executed, billed or accepted. Dynamics may stop at a violation, so proposed-event energy and evaluated-prefix load are deliberately distinct fields. Background and losses mean they need not generally be equal.

The task105 static planner and task107 static evaluator remain available with their original topology limits; they are not silently treated as a fleet scheduler. Their manifest is linked separately. The new coupled evaluator has its own identity and uses actual network/dynamics evidence. Frozen dependencies are recorded in `composition.json`; local source cherry-picks did not merge any upstream PR or default branch.

## Tools, verification and improvement

`platform.tools.dispatch` accepts a strict `capacity-orbital/mission-tool-v1` envelope with ID, fixed tool and exact arguments:

- `compare`: `{mission}` → three coupled policies.
- `verify`: `{mission, report}` → source/input/receipt and independent relationship checks plus deterministic reconstruction.
- `evaluate`: `{suite, baseline, candidates}` → registered ground/onboard/hybrid policies on fixed train/held-out missions.
- `feedback`: `{suite}` → supplied synthetic replay diagnostics and fixed calibration recommendations.

There are no dynamic callbacks, arbitrary commands, file destinations or new permissions in a tool request. Tools are deterministic and side-effect-free; retries recompute rather than invoke execution or bill. `--manifest` exposes the fixed registry and `request.schema.json` describes its envelope. Structured refusals retain validated request ID/hash and stable INVALID_ARGUMENT, UNSUPPORTED_SCHEMA, UNKNOWN_TOOL, BUDGET_EXCEEDED, SOURCE_UNAVAILABLE or SEMANTIC_TOPOLOGY_AMBIGUOUS codes. Oversized responses return a bounded refusal. This interface is stateless: it does not retain request-ID conflict protection across requests; the separate task107 dispatcher provides its own bounded session semantics. This tool boundary does not claim native Tool Guard enforcement, durable production idempotency or actual authorization provisioning. Caller-supplied held/refused/expired authority remains fail-closed in the dynamics result.

Verification independently checks job coverage/quality, input-before-processing and output-before-transfer precedence, durations, useful completion, compute/shared-link/terminal overlap, processing/network storage capacity and outage retention, transfer event power, energy conservation and aggregate costs. It also checks hashes and deterministic replay. Rehashing corrupted relationships does not make them valid. These checks establish consistency, not authenticity: no signing key or real telemetry is provisioned.

Policy evaluation preserves the immutable baseline. Before training ranking, any candidate that loses a baseline-admissible mission is excluded. Training selects by whole-mission failures then partial USD; the frozen winner is evaluated on held-out missions without reselection. It must improve the held-out score and preserve each baseline success. Candidates cannot alter jobs, prices, authority or quality floors. Composition remains single-pass: a processing-buffer or dynamic conflict refuses the proposal rather than rerouting or rescheduling it; the fixed policy evaluator compares only the three declared policies. Duplicate semantic workloads, including reordered jobs/contacts and renamed node, terminal, link and job identifiers, are rejected across the fixed suite. A label-free incidence graph retains roles, physical attributes, jurisdictions, shared-terminal/shared-link relationships and contact direction. Bounded color refinement normalizes referenced identities without using their spelling or insertion order. Unresolved symmetry refuses with SEMANTIC_TOPOLOGY_AMBIGUOUS; refinement is capped at 64 rounds and 500,000 vertex/edge work units, with BUDGET_EXCEEDED on exhaustion. This is a conservative partial canonicalizer, not a general graph-isomorphism or near-copy detector. Symmetric missions may still be planned/compared; only split evaluation and feedback qualification refuse ambiguous identities. This is bounded internal evaluation, not proof of generalization outside supplied synthetic missions.

Feedback records use `capacity-orbital/synthetic-replay-v1` and must say **supplied synthetic replay**. They bind source, mission input, proposal receipt and every job, with completion seconds, event kWh, decimal GB summed across links, and USD. Missing outcomes are refused/unknown, never invented telemetry. The checked-in replay fixtures deliberately perturb predictions; they are not observed hardware measurements. MAE is reported separately in seconds, kWh, GB and USD—never mixed into one weighted unitless score.

Fixed diagnostic calibration candidates are identity, 0.9 and 1.1 multipliers on predicted duration/energy only. Training selects by latency MAE then energy MAE; held-out must improve at least one without worsening either, with no held-out reselection. A worsening held-out fixture is retained. Calibration never changes feasibility limits, authority, prices, deadlines, bytes, a live baseline or acceptance criteria. All outputs say execution=false and promotion=false. Independent review is required before any use beyond diagnostics.

## Diligence and scope boundaries

Each delivered hop derives a link-screen input from its exact bytes, goodput, contact window and transmission duration. Lifecycle sensitivity inputs carry the mission identity but retain their own **year** horizon and USD per useful kW-year units, separate from the mission's seconds and partial operating USD. Lifecycle cost is not added to mission cost and is never labelled a full mission total. Omitted lifecycle input remains unknown. Supplied lifecycle cohorts are an explicit assumption-bound sensitivity, not an automatic extrapolation of a 300-second network trace or financial recommendation. Unsupported claim models remain unknown in the diligence tool.

Limits: 20 jobs, the inherited network/dynamics input and operation caps, six train/held-out missions, three registered route candidates, six feedback missions and 20 records per mission. Tool requests ≤4 MB, responses ≤8 MB; CLI JSON reads ≤8 MiB. Independent verification has a 4 MB report limit. Bounds are not throughput guarantees; measured cases and refusals are retained under `../evidence/platform/`. Pure API serialization of an already allocated caller object occurs outside these byte limits.

Live payload adapters, real Tool Guard enforcement, telemetry calibration, orbital geometry, nonlinear spacecraft thermal qualification, production metering, signatures, automated execution, domain safety and designated release acceptance remain absent or separately gated. Browser visual verification is blocked by the existing local-preview security restriction; static HTML checks do not prove visual readiness. Claude cross-tool review, Dmitry qualification and Ronnie reproduction remain open.

Verification reconstructs the ground-processing lane in release/ID order, including cursor, commissioning and declared availability delays for zero-duration stages that emit no compute event. Completion therefore need not equal data arrival even when processing duration is zero. Malformed report containers and unknown contact references produce a bounded invalid verification result; a successful verify-tool invocation means the diagnostic ran, not that its `valid` field is true. Programmer errors are not broadly converted into valid evidence.

Shared-resource overlap verification uses a per-resource sorted interval sweep with half-open intervals; empty intervals occupy no capacity. Diagnostics are deduplicated as they are collected. Remaining nested relationship checks charge a shared conservative 2,000,000-work-unit budget before traversal; an oversized verification workload returns invalid evidence with a bounded budget diagnostic, rather than completing all requested checks. This is not a total process-memory or wall-time guarantee and may conservatively refuse large valid reports.
