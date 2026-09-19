from copy import deepcopy
import json
import math

import pytest

from capacity.coverage_examples import example, fixtures, run_cases
from capacity.resource_coverage import evaluate_coverage


@pytest.mark.parametrize("case", fixtures(), ids=lambda row: row["id"])
def test_expected_coverage_cases(case):
    result = evaluate_coverage(**case["input"])
    assert result["resource_readiness"] == case["expected_resource_readiness"]
    assert result["mutation_request"] is None and result["execution_authorized"] is False
    assert result["not_checked"]
    json.dumps(result, allow_nan=False)


def test_each_scope_is_required_and_shared_storage_appears_once():
    args = example()
    assert len(args["bundle"]["checks"]) == 8
    for index in range(8):
        candidate = deepcopy(args)
        removed = candidate["bundle"]["checks"].pop(index)
        result = evaluate_coverage(**candidate)
        assert result["coverage"] == "incomplete"
        assert result["missing_requirements"] == [{"scope_id": removed["scope_id"], "resource": removed["resource"], "kind": "missing_check"}]
    assert len([r for r in evaluate_coverage(**args)["checks"] if r["resource"] == "storage"]) == 1


def test_refusal_does_not_hide_missing_scope():
    args = example()
    args["bundle"]["checks"][4]["available"]["value"] = 1
    args["bundle"]["checks"].pop(5)
    result = evaluate_coverage(**args)
    assert result["resource_readiness"] == "refused"
    assert result["coverage"] == "incomplete"
    assert any(row["check_state"] == "fail" for row in result["checks"])
    assert any(row["check_state"] == "missing" for row in result["checks"])


@pytest.mark.parametrize("binding", ["manifest_id", "profile_id", "workload_id", "config_id"])
def test_binding_mismatch_is_invalid(binding):
    args = example()
    args["bundle"][binding] = "different"
    with pytest.raises(ValueError, match="bindings differ"):
        evaluate_coverage(**args)


@pytest.mark.parametrize("mutation", [
    lambda p: p["manifest"]["requirements"].append(deepcopy(p["manifest"]["requirements"][0])),
    lambda p: p["bundle"]["checks"].append(deepcopy(p["bundle"]["checks"][0])),
    lambda p: p["manifest"]["requirements"][0]["component_ids"].append("runtime"),
    lambda p: p["bundle"]["checks"][0].update(scope_id="unknown-node"),
    lambda p: p["bundle"]["checks"][0]["demand_components"].update(undeclared={}),
    lambda p: p["manifest"].update(requirements=[]),
    lambda p: p["manifest"]["requirements"][0].update(resource=True),
    lambda p: p["manifest"]["requirements"][0].update(component_ids=[[]]),
    lambda p: p["bundle"].update(extra="unknown"),
])
def test_structural_contradictions_cannot_be_silently_dropped(mutation):
    args = example()
    mutation(args)
    with pytest.raises(ValueError):
        evaluate_coverage(**args)


@pytest.mark.parametrize("invalid", [math.nan, math.inf, True, "1"])
def test_missing_components_cannot_hide_invalid_capacity(invalid):
    args = example()
    args["bundle"]["checks"][1]["demand_components"] = {}
    args["bundle"]["checks"][1]["available"]["value"] = invalid
    result = evaluate_coverage(**args)
    assert result["resource_readiness"] == "refused"
    assert result["coverage"] == "incomplete"
    assert result["checks"][1]["check_state"] == "invalid"


def test_resource_failure_is_not_missing_coverage_and_stale_is_not_omission():
    args = example()
    args["bundle"]["checks"][1]["available"]["value"] = 5
    result = evaluate_coverage(**args)
    assert result["coverage"] == "complete" and result["resource_readiness"] == "refused"
    args["bundle"]["checks"][1]["available"]["state"] = "stale"
    result = evaluate_coverage(**args)
    assert result["coverage"] == "complete" and result["resource_readiness"] == "incomplete"


def test_partial_lower_bound_cannot_pass_complete_component_set():
    args = example()
    args["bundle"]["checks"][1]["demand_components"].pop("staging")
    result = evaluate_coverage(**args)
    assert result["checks"][1]["known_components_lower_bound"]["check_state"] == "pass"
    assert result["checks"][1]["check_state"] == "missing"
    assert result["resource_readiness"] == "incomplete"


@pytest.mark.parametrize("component_omitted", [True, False])
@pytest.mark.parametrize("unknown_margin", [True, False])
def test_known_shortfall_survives_both_absence_representations(component_omitted, unknown_margin):
    args = example()
    row = args["bundle"]["checks"][1]
    row["available"]["value"] = 7
    if component_omitted:
        del row["demand_components"]["staging"]
    else:
        row["demand_components"]["staging"].update(value=None, state="missing")
    if unknown_margin:
        row["margin"].update(value=None, state="missing")
    result = evaluate_coverage(**args)
    assert result["resource_readiness"] == "refused"
    assert result["checks"][1]["known_components_lower_bound"]["required"] == 8
    assert result["checks"][1]["input_states"]["demand/training"]["state"] == "known"
    # This mathematical zero bound never fills the missing original evidence.
    if unknown_margin:
        assert result["checks"][1]["input_states"]["margin"]["state"] == "missing"


@pytest.mark.parametrize("state", ["missing", "stale", "not_run"])
def test_unusable_capacity_cannot_support_shortfall_bound(state):
    args = example()
    row = args["bundle"]["checks"][1]
    row["available"].update(value=0, state=state)
    row["demand_components"].pop("staging")
    result = evaluate_coverage(**args)
    assert result["resource_readiness"] == "incomplete"
    assert "known_components_lower_bound" not in result["checks"][1]


def test_deterministic_cases():
    assert run_cases() == run_cases()
    json.dumps(run_cases(), allow_nan=False)
