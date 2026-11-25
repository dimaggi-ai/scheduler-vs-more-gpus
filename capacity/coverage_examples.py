"""Deterministic scope-coverage cases; no operator placement or measurements."""
from copy import deepcopy
import json

from capacity.resource_coverage import evaluate_coverage
from capacity.resource_evidence_examples import quantity


def example():
    binding = {"manifest_id": "synthetic-manifest-0", "profile_id": "synthetic-coverage-profile-0",
               "workload_id": "synthetic-batch-0", "config_id": "synthetic-config-0"}
    requirements = []
    checks = []
    # Explicit scopes are the input; these tiny values are arithmetic fixtures,
    # not a mapping from the selected 405B model to a real two-node placement.
    for scope, resource, components, available in [
        ("node-a", "cpu", {"runtime": 1}, 2), ("node-a", "host_memory", {"training": 8, "staging": 2}, 12),
        ("node-b", "cpu", {"runtime": 1}, 2), ("node-b", "host_memory", {"total_peak": 10}, 12),
        ("gpu-a", "gpu_memory", {"rank_peak": 8}, 10), ("gpu-b", "gpu_memory", {"rank_peak": 8}, 10),
        ("shared-storage", "storage", {"data_increment": 2, "checkpoint_increment": 4}, 8),
        ("node-a", "pinned_host_memory", {"pinned_subset": 2}, 3),
    ]:
        requirements.append({"scope_id": scope, "resource": resource, "component_ids": list(components)})
        unit = "cpu_core" if resource == "cpu" else "byte"
        checks.append({"scope_id": scope, "resource": resource,
                       "demand_components": {k: quantity(v, unit) for k, v in components.items()},
                       "available": quantity(available, unit), "margin": quantity(0, unit)})
    return {"manifest": {**binding, "schema_version": "resource-requirements/v0.1-proposed", "requirements": requirements},
            "bundle": {**binding, "schema_version": "resource-evidence-bundle/v0.1-proposed", "checks": checks}}


def fixtures():
    rows = []
    def add(name, mutate, expected, split="development"):
        args = example()
        mutate(args)
        rows.append({"id": name, "split": split, "input": args, "expected_resource_readiness": expected})
    add("all-declared-resources-fit", lambda p: None, "feasible_within_declared_resource_checks")
    add("missing-manifest", lambda p: p.update(manifest=None), "incomplete")
    add("missing-bundle", lambda p: p.update(bundle=None), "incomplete")
    add("omitted-device", lambda p: p["bundle"]["checks"].pop(5), "incomplete")
    add("omitted-node-resource", lambda p: p["bundle"]["checks"].pop(3), "incomplete")
    add("omitted-staging-component", lambda p: p["bundle"]["checks"][1]["demand_components"].pop("staging"), "incomplete")
    add("shortfall-with-other-device-missing", lambda p: (p["bundle"]["checks"][4]["available"].update(value=7), p["bundle"]["checks"].pop(5)), "refused", "exposed_acceptance")
    add("stale-shared-storage", lambda p: p["bundle"]["checks"][6]["available"].update(state="stale"), "incomplete", "exposed_acceptance")
    add("partial-components-already-exceed-capacity", lambda p: (p["bundle"]["checks"][1]["demand_components"].pop("staging"), p["bundle"]["checks"][1]["available"].update(value=7)), "refused", "exposed_acceptance")
    add("pinned-subset-shortfall", lambda p: p["bundle"]["checks"][7]["available"].update(value=1), "refused", "exposed_acceptance")
    return rows


def run_cases():
    results = []
    for case in fixtures():
        result = evaluate_coverage(**case["input"])
        if result["resource_readiness"] != case["expected_resource_readiness"]:
            raise AssertionError(case["id"])
        results.append({**case, "result": result})
    return {"schema_version": "resource-coverage-cases/v0.1", "evidence_class": "synthetic_contract_fixture",
            "seed": None, "generation": "explicit arithmetic cases; no random data or operator values",
            "tuning": [], "held_out": [], "cases": results}


if __name__ == "__main__":
    print(json.dumps(run_cases(), indent=2, sort_keys=True, allow_nan=False))
