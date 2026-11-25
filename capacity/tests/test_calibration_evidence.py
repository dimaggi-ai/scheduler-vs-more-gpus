import json
import math

import pytest

from capacity.calibration_evidence import compare_pair, CONTEXT_FIELDS
from capacity.calibration_examples import example_pair, fixtures, run_cases


@pytest.mark.parametrize("case", fixtures(), ids=lambda c: c["id"])
def test_known_answers(case):
    result = compare_pair(**case["input"])
    assert result["assessment"] == case["expected_assessment"]
    assert result["execution_authorized"] is False
    assert result["mutation_request"] is None
    if result["comparison"] != "comparable":
        assert result["absolute_error"] is None
    json.dumps(result, allow_nan=False)


def test_independent_error_arithmetic_and_zero():
    args = example_pair()
    result = compare_pair(**args)
    assert result["signed_error"] == 10
    assert result["absolute_error"] == 10
    assert result["relative_absolute_error"] == pytest.approx(1 / 11)
    args["observation"]["value"] = 0
    result = compare_pair(**args)
    assert result["signed_error"] == -100
    assert result["relative_absolute_error"] is None
    args["prediction"]["value"] = 0
    result = compare_pair(**args)
    assert result["assessment"] == "within_supplied_tolerance"
    assert result["relative_absolute_error"] is None


@pytest.mark.parametrize("field", CONTEXT_FIELDS)
def test_every_context_binding_is_required(field):
    args = example_pair()
    args["observation"]["context"][field] = "different"
    result = compare_pair(**args)
    assert result["comparison"] == "incomparable"
    assert result["differing_fields"] == [field]
    args["prediction"]["context"][field] = None
    args["observation"]["context"][field] = None
    assert compare_pair(**args)["assessment"] == "incomplete"


@pytest.mark.parametrize("value", [True, "110", -1, math.nan, math.inf, -math.inf, 1.5, 10**400])
@pytest.mark.parametrize("role", ["prediction", "observation", "absolute_tolerance"])
def test_numeric_boundaries(value, role):
    args = example_pair()
    args[role]["value"] = value
    assert compare_pair(**args)["assessment"] == "invalid"


@pytest.mark.parametrize("changes", [
    {"observed_at_utc": "2026-09-19"}, {"observed_at_utc": "2026-09-19T12:00:00"},
    {"measurement_start_utc": "2026-09-19T12:00:01Z"},
    {"valid_until_utc": "2026-09-19T12:00:00Z"}, {"evidence_class": "synthetic_model"},
    {"state": "pass"}, {"extra": "unexpected"}, {"source_id": []},
])
def test_invalid_record(changes):
    args = example_pair()
    args["observation"].update(changes)
    assert compare_pair(**args)["assessment"] == "invalid"


def test_observation_without_validity_is_missing():
    args = example_pair()
    args["observation"]["valid_until_utc"] = None
    assert compare_pair(**args)["input_states"]["observation"]["state"] == "missing"


def test_deterministic_serializable_cases():
    assert run_cases() == run_cases()
    json.dumps(run_cases(), allow_nan=False)


def test_fractional_cpu_is_valid_and_cannot_overflow_ratio():
    args = example_pair()
    for role in ("prediction", "observation", "absolute_tolerance"):
        args[role]["unit"] = "cpu_core"
    for role in ("prediction", "observation"):
        args[role]["context"]["metric"] = "host_cpu_usage"
    args["prediction"]["value"] = 0.25
    args["observation"]["value"] = 0.5
    args["absolute_tolerance"]["value"] = 0.25
    assert compare_pair(**args)["signed_error"] == 0.25
    args["prediction"]["value"] = 1e308
    args["observation"]["value"] = 1e-308
    assert compare_pair(**args)["assessment"] == "invalid"


def test_submicrosecond_timestamp_is_rejected_instead_of_truncated():
    args = example_pair()
    args["observation"]["observed_at_utc"] = "2026-09-19T12:00:00.0000009Z"
    args["as_of_utc"] = "2026-09-19T12:00:00.000000Z"
    assert compare_pair(**args)["assessment"] == "invalid"
    args["as_of_utc"] = "2026-09-19T12:00:00.0000001Z"
    with pytest.raises(ValueError, match="six fractional digits"):
        compare_pair(**args)


def test_supported_microsecond_boundary_preserves_future_detection():
    args = example_pair()
    args["observation"]["observed_at_utc"] = "2026-09-19T12:00:00.000002Z"
    args["as_of_utc"] = "2026-09-19T12:00:00.000001Z"
    assert compare_pair(**args)["assessment"] == "invalid"
    args["as_of_utc"] = "2026-09-19T12:00:00.000002Z"
    assert compare_pair(**args)["assessment"] == "within_supplied_tolerance"


@pytest.mark.parametrize("prediction,observation,error", [
    (2**53 + 1, float(2**53), -1),
    (float(2**53), 2**53 + 1, 1),
])
def test_mixed_integer_float_error_cannot_round_into_zero(prediction, observation, error):
    args = example_pair()
    for role in ("prediction", "observation", "absolute_tolerance"):
        args[role]["unit"] = "s"
    args["prediction"]["value"] = prediction
    args["observation"]["value"] = observation
    args["absolute_tolerance"]["value"] = 0
    result = compare_pair(**args)
    assert result["assessment"] == "outside_supplied_tolerance"
    assert result["signed_error"] == error
    assert result["absolute_error"] == 1
    assert result["relative_absolute_error"] > 0
    json.dumps(result, allow_nan=False)


def test_tolerance_uses_exact_error_even_when_display_rounds_to_tolerance():
    args = example_pair()
    for role in ("prediction", "observation", "absolute_tolerance"):
        args[role]["unit"] = "s"
    args["prediction"]["value"] = .5
    args["observation"]["value"] = 2**53 + 1
    args["absolute_tolerance"]["value"] = 2**53
    result = compare_pair(**args)
    assert result["assessment"] == "outside_supplied_tolerance"
    assert result["absolute_error"] == args["absolute_tolerance"]["value"]


def test_small_relative_error_remains_nonzero_at_largest_accepted_integer_scale():
    args = example_pair()
    largest_finite_integer = int(float.fromhex("0x1.fffffffffffffp+1023"))
    args["prediction"]["value"] = largest_finite_integer - 1
    args["observation"]["value"] = largest_finite_integer
    args["absolute_tolerance"]["value"] = 0
    result = compare_pair(**args)
    assert result["assessment"] == "outside_supplied_tolerance"
    assert result["signed_error"] == 1
    assert 0 < result["relative_absolute_error"] < float.fromhex("0x1p-1022")
    json.dumps(result, allow_nan=False)
