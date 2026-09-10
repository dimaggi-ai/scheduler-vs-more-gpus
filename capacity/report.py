"""Versioned simulator reports; no universal GPU-equivalence conversion.

The scheduler's progress accounting is not netcap's communication-exclusive
productive time. Workload projections require an explicit rate in units per
scheduler-productive GPU-hour and remain scenario estimates, not measurements.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
import platform
from pathlib import Path

import numpy as np

from sim.simulator import Config, Simulation, NODE_GPUS

VERSION = "scheduler-capacity/v1"
POLICIES = ("rigid-fifo", "tiered-preemption", "intent-closed-loop")
ASSUMPTIONS = [
    "Synthetic workload; five-minute steps; abstract placement; single tenant.",
    "Training progress scales linearly with allocated GPUs; resize pays overhead.",
    "Inference is aggregate demand, not measured request latency or token goodput.",
    "Graceful preemption preserves work without charging a checkpoint-write stop.",
    "Network and detailed reliability penalties are not composed into this ledger.",
]


def number(value, name, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def config_from_dict(raw):
    if not isinstance(raw, dict):
        raise ValueError("config must be an object")
    defaults = asdict(Config())
    unknown = raw.keys() - defaults.keys()
    if unknown:
        raise ValueError(f"unknown config fields: {sorted(unknown)}")
    values = defaults | raw
    for name, default in defaults.items():
        value = values[name]
        if type(default) is bool:
            if type(value) is not bool:
                raise ValueError(f"{name} must be boolean")
        elif type(default) is int:
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        else:
            number(value, name)
    if values["gpus"] < NODE_GPUS or values["gpus"] % NODE_GPUS:
        raise ValueError(f"gpus must be a positive multiple of {NODE_GPUS}")
    if not 1 <= values["horizon_days"] <= 366:
        raise ValueError("horizon_days must be between 1 and 366 for this replay interface")
    if not 0 < values["power_frac"] <= 1:
        raise ValueError("power_frac must be in (0, 1]")
    if values["power_envelope"] and int(values["gpus"] * values["power_frac"]) == 0:
        raise ValueError("power envelope must leave at least one GPU in this replay interface")
    if values["failures_per_1000_node_days"] >= 288000:
        raise ValueError("failure rate must yield a per-step probability below one")
    if values["power_start_hour"] >= 24 or not 0 <= values["power_hours"] <= 24:
        raise ValueError("invalid daily power window")
    if values["power_start_hour"] + values["power_hours"] > 24:
        raise ValueError("the simulator does not implement a midnight-wrapping power window")
    if values["inf_base"] + values["inf_diurnal_amp"] >= values["gpus"]:
        raise ValueError("base plus diurnal inference must leave training capacity")
    return Config(**values)


def workload_projection(profiles, m):
    if not isinstance(profiles, dict) or profiles.keys() - {"training", "inference"}:
        raise ValueError("workloads must map training/inference to explicit calibrations")
    hours = {"training": m.train_productive_gpu_h, "inference": m.inf_productive_gpu_h}
    required = {"workload_id", "hardware_id", "model_id", "protocol_id", "unit",
                "units_per_productive_gpu_h", "evidence_kind", "source", "assumptions"}
    out = {}
    for kind, profile in profiles.items():
        if not isinstance(profile, dict) or set(profile) != required:
            raise ValueError(f"{kind}: calibration must contain exactly {sorted(required)}")
        for key in required - {"units_per_productive_gpu_h", "assumptions"}:
            if not isinstance(profile[key], str) or not profile[key].strip():
                raise ValueError(f"{kind}.{key} must be nonempty text")
        if profile["evidence_kind"] not in ("synthetic", "benchmark", "observed"):
            raise ValueError("calibration evidence_kind must be synthetic, benchmark or observed")
        assumptions = profile["assumptions"]
        if not isinstance(assumptions, list) or not assumptions or any(
                not isinstance(a, str) or not a.strip() for a in assumptions):
            raise ValueError("calibration assumptions must be a nonempty list of text")
        rate = number(profile["units_per_productive_gpu_h"], "calibration rate", positive=True)
        quantity = hours[kind] * rate
        number(quantity, "projected quantity")
        out[kind] = {"calibration": profile, "calibration_id": digest(profile),
                     "projected_units": quantity, "evidence_kind": "simulation"}
    return out


def replay(raw_config, policy, workloads=None):
    cfg = config_from_dict(raw_config)
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {POLICIES}")
    sim = Simulation(cfg, policy)
    sim.run()
    m = sim.metrics  # unrounded source accounting, not rounded headline CSVs
    productive = m.train_productive_gpu_h + m.inf_productive_gpu_h
    buckets = {
        "productive": productive,
        "unavailable": m.nominal_gpu_h - m.envelope_gpu_h,
        "idle": m.envelope_gpu_h - m.inf_alloc_gpu_h - m.train_alloc_gpu_h,
        "inference_reservation": m.inf_alloc_gpu_h - m.inf_productive_gpu_h,
        "training_overhead_and_discarded": m.train_alloc_gpu_h - m.train_productive_gpu_h,
    }
    for key, value in buckets.items():
        if not math.isfinite(value) or value < -1e-6:
            raise ValueError(f"simulator returned invalid bucket {key}: {value}")
        buckets[key] = max(0.0, value)
    if not math.isclose(sum(buckets.values()), m.nominal_gpu_h, rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError("capacity accounting does not conserve nominal GPU-hours")
    source = Path(__file__).resolve().parents[1] / "sim" / "simulator.py"
    provenance = {"simulator_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "interface_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "runtime": {"python": platform.python_version(), "numpy": np.__version__},
                  "config": asdict(cfg), "policy": policy}
    projections = workload_projection(workloads if workloads is not None else {}, m)
    return {
        "schema_version": VERSION, "evidence_kind": "simulation",
        "run_id": digest({"provenance": provenance, "workloads": projections}),
        "provenance": provenance, "unit": "GPU-hour",
        "window_hours": cfg.horizon_days * 24,
        "nominal_gpu_h": m.nominal_gpu_h, "envelope_gpu_h": m.envelope_gpu_h,
        "productive_by_workload_gpu_h": {"training": m.train_productive_gpu_h,
                                        "inference": m.inf_productive_gpu_h},
        "buckets_gpu_h": buckets,
        "productive_fraction_of_nominal": productive / m.nominal_gpu_h,
        "productive_fraction_of_envelope": productive / m.envelope_gpu_h if m.envelope_gpu_h else None,
        "workloads": projections, "assumptions": ASSUMPTIONS,
    }


def compare(baseline, candidate):
    """Compare policy runs on identical input/model/calibration; never mix ledgers."""
    for report in (baseline, candidate):
        validate_report(report)
        if report.get("schema_version") != VERSION or report.get("evidence_kind") != "simulation":
            raise ValueError("comparison requires scheduler-capacity/v1 simulation reports")
        p = report["provenance"]
        if report["run_id"] != digest({"provenance": p, "workloads": report["workloads"]}):
            raise ValueError("run identity does not match provenance")
        for key in ("config", "simulator_sha256", "interface_sha256", "runtime"):
            if p[key] != baseline["provenance"][key]:
                raise ValueError(f"incomparable runs: {key} differs")
    keys = set(baseline["workloads"])
    if keys != set(candidate["workloads"]):
        raise ValueError("workload sets differ")
    deltas = {}
    for key in keys:
        a, b = baseline["workloads"][key], candidate["workloads"][key]
        if a["calibration"] != b["calibration"]:
            raise ValueError(f"incomparable {key} calibration")
        deltas[key] = {"unit": a["calibration"]["unit"],
                       "delta_projected_units": b["projected_units"] - a["projected_units"]}
    return {"evidence_kind": "simulation", "baseline_run_id": baseline["run_id"],
            "candidate_run_id": candidate["run_id"],
            "delta_productive_gpu_h": candidate["buckets_gpu_h"]["productive"] - baseline["buckets_gpu_h"]["productive"],
            "workloads": deltas}


def validate_report(report):
    """Validate the wire schema and accounting identities before comparison.

    Source hashes identify inputs/code; they are not signatures or evidence
    that an external sender actually ran that implementation.
    """
    import jsonschema
    schema = json.loads(Path(__file__).with_name("report.schema.json").read_text())
    try:
        jsonschema.validate(report, schema)
        canonical(report)
    except (jsonschema.ValidationError, ValueError) as exc:
        raise ValueError(f"invalid capacity report: {exc}") from exc
    config = config_from_dict(report["provenance"]["config"])
    if asdict(config) != report["provenance"]["config"]:
        raise ValueError("report config must include all simulator defaults")
    nominal = report["nominal_gpu_h"]
    envelope = report["envelope_gpu_h"]
    buckets = report["buckets_gpu_h"]
    close = lambda a, b: math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)
    if not close(report["window_hours"], config.horizon_days * 24) or not close(nominal, config.gpus * report["window_hours"]):
        raise ValueError("report window/nominal differs from config")
    if envelope > nominal or not close(sum(buckets.values()), nominal):
        raise ValueError("invalid capacity accounting")
    if not close(buckets["unavailable"], nominal - envelope):
        raise ValueError("unavailable bucket differs from nominal minus envelope")
    productive = buckets["productive"]
    credits = report["productive_by_workload_gpu_h"]
    if not close(sum(credits.values()), productive):
        raise ValueError("workload credits disagree with productive accounting")
    if not close(report["productive_fraction_of_nominal"], productive / nominal):
        raise ValueError("nominal ratio disagrees with accounting")
    ratio = report["productive_fraction_of_envelope"]
    if (envelope == 0 and ratio is not None) or (envelope > 0 and (ratio is None or not close(ratio, productive / envelope))):
        raise ValueError("envelope ratio disagrees with accounting")
    for kind, projected in report["workloads"].items():
        if projected["calibration_id"] != digest(projected["calibration"]):
            raise ValueError("calibration identity mismatch")
        expected = credits[kind] * projected["calibration"]["units_per_productive_gpu_h"]
        if not close(projected["projected_units"], expected):
            raise ValueError("workload projection disagrees with rate and credited GPU-hours")
    return report
