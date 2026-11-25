import copy
import json
import math

import pytest

from capacity.resource_evidence import capacity_check, checkpoint_bound_check
from capacity.resource_evidence_examples import GIB, fixtures, quantity, run_cases


@pytest.mark.parametrize("case", fixtures()["cases"], ids=lambda c: c["id"])
def test_known_answers(case):
    fn = capacity_check if case["kind"] == "capacity" else checkpoint_bound_check
    result = fn(**case["input"])
    assert result["check_state"] == case["expected_check_state"]
    assert result["mutation_request"] is None
    assert result["execution_authorized"] is False
    json.dumps(result, allow_nan=False)


def test_host_arithmetic_and_source_identity():
    case = fixtures()["cases"][0]
    result = capacity_check(**case["input"])
    assert result["required"] == 13*GIB
    assert result["headroom"] == GIB
    assert result["input_states"]["demand/staging"]["source_id"] == "synthetic-fixture"


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, True, "12", -1, 1.5])
def test_invalid_byte_quantities_never_pass_or_leak_nonfinite_json(bad):
    case = copy.deepcopy(fixtures()["cases"][0])
    case["input"]["available"]["value"] = bad
    result = capacity_check(**case["input"])
    assert result["engineering_readiness"] == "refused"
    assert result["check_state"] == "invalid"
    json.dumps(result, allow_nan=False)


def test_gib_cannot_silently_be_treated_as_bytes():
    case = copy.deepcopy(fixtures()["cases"][0])
    case["input"]["available"].update(value=14, unit="GiB")
    assert capacity_check(**case["input"])["check_state"] == "invalid"


def test_unknown_source_and_absent_value_are_missing():
    for edit in ({"source_id": None}, {"value": None}):
        case = copy.deepcopy(fixtures()["cases"][0])
        case["input"]["available"].update(edit)
        assert capacity_check(**case["input"])["engineering_readiness"] == "incomplete"


def test_invalid_and_stale_states_are_both_preserved():
    case = copy.deepcopy(fixtures()["cases"][0])
    case["input"]["available"]["state"] = "stale"
    case["input"]["margin"]["value"] = True
    result = capacity_check(**case["input"])
    assert result["engineering_readiness"] == "refused"
    assert result["input_states"]["available"]["state"] == "stale"
    assert result["input_states"]["margin"]["state"] == "invalid"


def test_total_memory_does_not_add_a_pinned_subset_twice():
    # Total 12 already includes pinned 4. Submit the total once; pinned capacity
    # needs a separate applicable constraint, not addition to total host RAM.
    case = next(c for c in fixtures()["cases"] if c["id"] == "pinned_subset_total")
    result = capacity_check(**case["input"])
    assert result["required"] == 12*GIB
    assert 12*GIB + 4*GIB > result["available"]  # wrong accounting would falsely refuse


def test_aggregate_device_capacity_does_not_override_failed_rank():
    doc = fixtures()
    cases = [c for c in doc["cases"] if c["id"].endswith("imbalance")]
    results = [capacity_check(**c["input"]) for c in cases]
    assert sum(r["required"] for r in results) < sum(r["available"] for r in results)
    assert [r["check_state"] for r in results] == ["fail", "pass"]


def test_checkpoint_lower_bound_never_becomes_save_or_restore_proof():
    for bound, budget in [(2, 3), (2, 2)]:
        result = checkpoint_bound_check(scope_id="shared", lower_bound_s=quantity(bound, "s"), budget_s=quantity(budget, "s"))
        assert result["engineering_readiness"] == "incomplete"
    result = checkpoint_bound_check(scope_id="shared", lower_bound_s=quantity(None, "s", state="missing"), budget_s=quantity(3, "s"))
    assert result["engineering_readiness"] == "incomplete"


def test_fixture_generation_is_deterministic_and_does_not_mutate_inputs():
    first = fixtures()
    snapshot = copy.deepcopy(first)
    assert run_cases(first) == run_cases(fixtures())
    assert first == snapshot


def test_cpu_sum_overflow_is_invalid():
    huge = quantity(1.7e308, "cpu_core")
    result = capacity_check(scope_id="node", resource="cpu", demand_components={"a": huge, "b": huge}, available=huge, margin=quantity(0, "cpu_core"))
    assert result["check_state"] == "invalid"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("field", ["demand", "available"])
def test_cpu_large_integer_mixed_with_float_is_invalid(field):
    demand = quantity(10**400 if field == "demand" else 1., "cpu_core")
    available = quantity(10**400 if field == "available" else 16., "cpu_core")
    result = capacity_check(scope_id="node", resource="cpu", demand_components={"workload": demand},
                            available=available, margin=quantity(.5, "cpu_core"))
    assert result["check_state"] == "invalid"
    assert result["engineering_readiness"] == "refused"
    json.dumps(result, allow_nan=False)


def test_time_large_integer_is_invalid():
    result = checkpoint_bound_check(scope_id="store", lower_bound_s=quantity(10**400, "s"), budget_s=quantity(72., "s"))
    assert result["check_state"] == "invalid"


@pytest.mark.parametrize("margin", [0, .5])
@pytest.mark.parametrize("available", [10**308, 1e308])
def test_finite_integer_cpu_components_cannot_overflow_derived_arithmetic(margin, available):
    result = capacity_check(scope_id="node", resource="cpu",
                            demand_components={k: quantity(10**308, "cpu_core") for k in ("a", "b")},
                            available=quantity(available, "cpu_core"), margin=quantity(margin, "cpu_core"))
    assert result["check_state"] == "invalid"
    assert result["engineering_readiness"] == "refused"
    assert result["required"] is result["headroom"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("small_is_margin", [True, False])
def test_positive_sub_ulp_cpu_requirement_cannot_round_into_a_pass(small_is_margin):
    components = {"base": quantity(1, "cpu_core")}
    if not small_is_margin:
        components["small"] = quantity(2**-54, "cpu_core")
    result = capacity_check(scope_id="node", resource="cpu", demand_components=components,
                            available=quantity(1, "cpu_core"),
                            margin=quantity(2**-54 if small_is_margin else 0, "cpu_core"))
    assert result["check_state"] == "fail"
    assert result["headroom"] == -(2**-54)
    json.dumps(result, allow_nan=False)


def test_mixed_integer_float_cpu_headroom_preserves_integer_shortfall():
    result = capacity_check(scope_id="node", resource="cpu",
                            demand_components={"workload": quantity(2**53 + 1, "cpu_core")},
                            available=quantity(float(2**53), "cpu_core"), margin=quantity(0, "cpu_core"))
    assert result["check_state"] == "fail"
    assert result["required"] == 2**53 + 1
    assert result["headroom"] == -1
