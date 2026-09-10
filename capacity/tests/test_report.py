import copy
import json
from pathlib import Path

import pytest

from capacity.report import replay, compare, config_from_dict, validate_report, digest
from capacity.__main__ import main


@pytest.fixture(scope="module")
def scenario():
    return json.loads((Path(__file__).parents[2] / "examples/capacity-replay.json").read_text())


@pytest.fixture(scope="module")
def report(scenario):
    return replay(scenario["config"], scenario["policy"], scenario["workloads"])


def test_repeatable_and_conserved(report, scenario):
    assert report == replay(scenario["config"], scenario["policy"], scenario["workloads"])
    validate_report(report)
    assert sum(report["buckets_gpu_h"].values()) == pytest.approx(report["nominal_gpu_h"])
    assert report["productive_fraction_of_nominal"] < report["productive_fraction_of_envelope"]
    assert report["workloads"]["inference"]["evidence_kind"] == "simulation"


def test_no_workload_rate_is_invented(scenario):
    assert replay(scenario["config"], scenario["policy"])["workloads"] == {}


def test_same_baseline_delta_is_zero(report):
    result = compare(report, report)
    assert result["delta_productive_gpu_h"] == 0
    assert result["workloads"]["inference"]["delta_projected_units"] == 0


def test_policy_comparison(report, scenario):
    baseline = replay(scenario["config"], "rigid-fifo", scenario["workloads"])
    result = compare(baseline, report)
    assert result["evidence_kind"] == "simulation"
    assert result["delta_productive_gpu_h"] == pytest.approx(
        report["buckets_gpu_h"]["productive"] - baseline["buckets_gpu_h"]["productive"])


@pytest.mark.parametrize("overrides", [
    {"horizon_days": 0}, {"gpus": 7}, {"gpus": True}, {"seed": -1},
    {"power_frac": 0}, {"power_frac": 1.1}, {"offered_load": float("nan")},
    {"inf_base": 1100}, {"power_start_hour": 23}, {"failures": "false"},
    {"unknown": 1}, {"inf_base": float("inf")}, {"horizon_days": 1.5},
])
def test_bad_configs(overrides):
    with pytest.raises(ValueError):
        config_from_dict(overrides)


@pytest.mark.parametrize("field,value", [("unit", ""), ("units_per_productive_gpu_h", -1),
                                      ("units_per_productive_gpu_h", True), ("assumptions", [])])
def test_bad_calibration(scenario, field, value):
    scn = copy.deepcopy(scenario)
    scn["workloads"]["inference"][field] = value
    with pytest.raises(ValueError):
        replay(scn["config"], scn["policy"], scn["workloads"])


def test_different_seed_or_calibration_refused(report, scenario):
    with pytest.raises(ValueError, match="config differs"):
        compare(report, replay(scenario["config"] | {"seed": 123}, scenario["policy"], scenario["workloads"]))
    profiles = copy.deepcopy(scenario["workloads"])
    profiles["inference"]["protocol_id"] = "different-latency-slo"
    with pytest.raises(ValueError, match="calibration"):
        compare(report, replay(scenario["config"], scenario["policy"], profiles))


@pytest.mark.parametrize("field,value", [("schema_version", "netcap/v1"),
                                      ("nominal_gpu_h", 1), ("unit", "GPU-second"),
                                      ("envelope_gpu_h", float("nan"))])
def test_corrupt_report_refused(report, field, value):
    bad = copy.deepcopy(report)
    bad[field] = value
    with pytest.raises(ValueError):
        compare(report, bad)


def test_cli_invalid_path(capsys):
    assert main(["replay", "does-not-exist.json"]) == 2
    assert "capacity:" in capsys.readouterr().err


def test_projection_must_match_workload_credit_even_if_rehashed(report):
    bad = copy.deepcopy(report)
    bad["workloads"]["inference"]["projected_units"] *= 2
    bad["run_id"] = digest({"provenance": bad["provenance"], "workloads": bad["workloads"]})
    with pytest.raises(ValueError, match="projection disagrees"):
        compare(report, bad)


def test_invalid_failure_probability_and_zero_power_capacity():
    for cfg in ({"failures_per_1000_node_days": 288000},
                {"gpus": 8, "inf_base": 0, "inf_diurnal_amp": 0,
                 "power_envelope": True, "power_frac": 0.01}):
        with pytest.raises(ValueError):
            config_from_dict(cfg)


def test_cli_example(scenario, capsys):
    path = Path(__file__).parents[2] / "examples/capacity-replay.json"
    assert main(["replay", str(path)]) == 0
    validate_report(json.loads(capsys.readouterr().out))
