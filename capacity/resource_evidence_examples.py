"""Deterministic synthetic contract cases; no physical or operator data generator."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from capacity.resource_evidence import capacity_check, checkpoint_bound_check

GIB = 2**30
NETCAP_PIN = "3047ddb4f11e65c46b5bcab6f7674dd9fb3900e4"


def quantity(value, unit="byte", *, state="known", source="synthetic-fixture"):
    return {"value": value, "unit": unit, "state": state, "source_id": source,
            "evidence_class": "synthetic_contract_fixture"}


def fixtures():
    rows = []

    def add(name, resource, components, available, margin, expected, split="development"):
        unit = "cpu_core" if resource == "cpu" else "byte"
        rows.append({"id": name, "split": split, "kind": "capacity",
                     "input": {"scope_id": "synthetic/" + name, "resource": resource,
                         "demand_components": {k: quantity(v, unit) for k, v in components.items()},
                         "available": quantity(available, unit), "margin": quantity(margin, unit)},
                     "expected_check_state": expected})

    add("host_fits", "host_memory", {"training": 8*GIB, "staging": 4*GIB}, 14*GIB, GIB, "pass")
    add("host_shortfall", "host_memory", {"training": 8*GIB, "staging": 4*GIB}, 10*GIB, 0, "fail")
    add("cpu_shortfall", "cpu", {"total_profiled_cpu": 2.5}, 2, 0, "fail")
    add("exact_capacity", "host_memory", {"total_peak": 12*GIB}, 12*GIB, 0, "pass")
    add("unknown_margin", "host_memory", {"total_peak": 12*GIB}, 16*GIB, None, "missing")
    rows[-1]["input"]["margin"]["state"] = "missing"
    add("stale_capacity", "host_memory", {"total_peak": 12*GIB}, 16*GIB, 0, "stale")
    rows[-1]["input"]["available"]["state"] = "stale"
    add("missing_gpu_peak", "gpu_memory", {"observed_peak": None}, 80_000_000_000, 0, "missing")
    rows[-1]["input"]["demand_components"]["observed_peak"]["state"] = "missing"
    add("shared_storage_overbook", "storage", {"job_a_increment": 6*GIB, "job_b_increment": 6*GIB}, 10*GIB, 0, "fail")
    add("storage_increment_only", "storage", {"new_checkpoint_peak_increment": 2*GIB}, 4*GIB, 0, "pass")
    add("pinned_subset_total", "host_memory", {"total_peak_including_pinned": 12*GIB}, 14*GIB, 0, "pass", "held_out_acceptance")
    add("pinned_subset_limit", "pinned_host_memory", {"pinned_subset": 4*GIB}, 3*GIB, 0, "fail", "held_out_acceptance")
    add("device_a_imbalance", "gpu_memory", {"rank_a_peak": 9*GIB}, 8*GIB, 0, "fail", "held_out_acceptance")
    add("device_b_imbalance", "gpu_memory", {"rank_b_peak": GIB}, 8*GIB, 0, "pass", "held_out_acceptance")
    for name, bound, budget, expected in [("checkpoint_bound_refuses", 2, 1, "fail"),
                                         ("checkpoint_bound_insufficient", 2, 3, "not_run"),
                                         ("checkpoint_bound_equal_insufficient", 2, 2, "not_run")]:
        rows.append({"id": name, "split": "development", "kind": "checkpoint_bound",
                     "input": {"scope_id": "synthetic/shared-store", "lower_bound_s": quantity(bound, "s"),
                               "budget_s": quantity(budget, "s")}, "expected_check_state": expected})
    return {"schema_version": "resource-evidence-fixtures/v0.1", "evidence_class": "synthetic_contract_fixture",
            "seed": None, "generator": "explicit deterministic arithmetic; no random draws",
            "splits": {"development": "named inequalities and unknowns", "tuning": "empty; no fitting",
                       "held_out_acceptance": "distinct subset/imbalance families frozen before first test; exposed regression after use, no physical independence claim"},
            "cases": rows}


def run_cases(document):
    output = []
    for case in document["cases"]:
        fn = capacity_check if case["kind"] == "capacity" else checkpoint_bound_check
        result = fn(**case["input"])
        if result["check_state"] != case["expected_check_state"]:
            raise AssertionError(case["id"])
        output.append({"case_id": case["id"], "result": result})
    return output


def joined_resource_probes(netcap_root):
    """Existing model constants, with explicitly conditional arithmetic only."""
    commit = subprocess.check_output(["git", "-C", str(netcap_root), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(netcap_root), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
    if commit != NETCAP_PIN or dirty:
        raise ValueError("netcap probes require unchanged audited source")
    sys.path.insert(0, str(netcap_root / "src"))
    from netcap.config import load_scenario, replace_nested
    from netcap.performance import memory_per_accelerator_gb
    from netcap.regimes import checkpoint_state_bytes
    scenario = load_scenario(netcap_root / "configs/scenarios/reference_405b_16k.yaml")
    scenario = replace_nested(scenario, **{"parallelism.dp": 1, "parallelism.pp": 16,
                                         "model.seq_len": 8192, "topology.net_efficiency": .65})
    state_gb, activation_gb = memory_per_accelerator_gb(scenario)
    checkpoint_bytes = checkpoint_state_bytes(scenario)
    return {"evidence_class": "synthetic_model", "netcap_commit": commit,
            "rough_device_memory_GB": {"state": state_gb, "activation": activation_gb},
            "checkpoint_estimated_bytes": checkpoint_bytes,
            "assumed_joined_write_stall_s": 72,
            "conditional_minimum_payload_bytes_s_for_72s": checkpoint_bytes / 72,
            "conditional_even_shard_staging_bytes_per_node": checkpoint_bytes / 16,
            "conditional_staging_node_count": 16,
            "conditional_three_concurrent_jobs_payload_bytes_s_for_72s": 3 * checkpoint_bytes / 72,
            "operator_host_memory_bytes": None, "operator_storage_bytes_s": None,
            "assumptions": ["Existing n_params*14 checkpoint recipe, not measured serialized bytes.",
                "72s is the existing recovery model's assumed stall, not an observed durable save.",
                "Rate arithmetic assumes all estimated payload transfers inside 72s with no other overhead.",
                "Staging arithmetic is hypothetical full CPU staging, equal 16-node shards, one in-flight checkpoint.",
                "Three concurrent full writes on one storage scope is a stress case, not an event in the joined simulator.",
                "No actual I/O service rate, CPU/RAM bound, storage implementation or checkpoint restore is known."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--netcap-root", required=True, type=Path)
    args = parser.parse_args()
    document = fixtures()
    report = {"fixtures": document, "results": run_cases(document),
              "joined_resource_probes": joined_resource_probes(args.netcap_root.resolve()),
              "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                [Path(__file__), Path(__file__).with_name("resource_evidence.py")]}}
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"cases": len(report["results"]), "probes": report["joined_resource_probes"]}, indent=2))


if __name__ == "__main__":
    main()
