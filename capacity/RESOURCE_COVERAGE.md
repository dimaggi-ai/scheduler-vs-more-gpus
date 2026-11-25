# Explicit resource requirement coverage

Maggie's domain reference, 19 September 2026. The existing `capacity_check`
evaluates one resource/scope. `resource_coverage.evaluate_coverage` now evaluates
an explicit required set and preserves omissions. It does not discover a real
placement, collect evidence, implement the application or grant permission.

`manifest` is either null (missing) or `resource-requirements/v0.1-proposed` with
exact fields `schema_version`, `manifest_id`, `profile_id`, `workload_id`,
`config_id`, `requirements`. Each requirement contains `scope_id`, `resource`
and nonempty unique `component_ids`. IDs are nonempty strings without surrounding
whitespace. Resource enums and canonical units reuse `resource_evidence.UNITS`.
Scope IDs must be namespace-qualified in a real bound profile; tiny fixture IDs
are only synthetic. A shared storage capacity appears once in the manifest.

`bundle` is null or `resource-evidence-bundle/v0.1-proposed` with those same four
binding IDs and a `checks` list. Every check has the existing scalar input fields:
`scope_id`, `resource`, `demand_components`, `available`, `margin`. Binding IDs
must match exactly; duplicate/undeclared scopes or components are invalid.
No copy of the capacity predicate or numeric rules is implemented.

Omitted checks/components give incomplete coverage, never zero demand. Present
invalid input refuses even when components are missing. A supplied partial demand
can refuse if that lower bound already exceeds capacity; a partial pass cannot
pass the full requirement. Pinned subsets are evaluated separately from host total.
The same lower-bound rule applies to omitted components and explicit missing
values, including an unknown margin. Only known current components/capacity are
used. Zero for an unknown nonnegative component/margin is explicitly labeled as
a mathematical lower bound in the separate proof; actual evidence remains missing.
Missing/stale/not-run available capacity cannot support that proof. A bound that
fits never fills missing evidence or passes readiness.
No capacities are summed across nodes/devices. Disjointness/containment is a
reviewed manifest obligation, not something component names can establish.

Coverage and readiness are distinct: a structurally complete set can contain stale
data or a physical shortfall; a refusal can coexist with missing scopes. Output
`resource_readiness` is `incomplete`, `refused`, or
`feasible_within_declared_resource_checks`. The last means every declared scalar
predicate passed, not that the manifest contains every real requirement. A trusted,
independently reviewed workload/topology manifest must establish that. Changing
or weakening that manifest changes the comparison/profile and requires review.

`not_checked` retains actual topology/completeness, source authenticity/freshness,
geometry/plant/isolation, storage locality/checkpoint service, calibration and
policy gaps. `execution_authorized` is always false; `mutation_request` is null.
This reference cannot replace target-profile binding at the governed boundary.
Structural invalidity raises `ValueError`; ordinary absence returns explicit
incomplete output. It is a proposed reference interface, not a released wire API.

`python -m capacity.coverage_examples` emits ten deterministic synthetic cases,
with explicit units, IDs and exposure partition. No random generator, model fit,
operator quantities or new physical assumptions are introduced. The two-node
fixture is an arithmetic example, not a claimed placement of the 405B model.
Tuning and protected holdout sets are empty; exposed acceptance is regression
evidence. Run `python -m pytest capacity/tests/test_resource_coverage.py -q`.
