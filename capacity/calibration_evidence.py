"""Offline comparison of one prediction with one explicitly matched observation.

This arithmetic reference does not calibrate a model, authenticate observations,
or establish resource fit. In particular, an even-shard estimate and a worst-rank
peak are different statistics and cannot be compared through this function.
"""
from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction
import math
import re

CONTEXT_FIELDS = ("workload_id", "config_id", "hardware_id", "topology_id",
                  "scope_id", "metric", "statistic", "protocol_id")
RECORD_FIELDS = {"context", "value", "unit", "state", "source_id", "evidence_class",
                 "measurement_start_utc", "observed_at_utc", "valid_until_utc"}
STATES = {"known", "missing", "stale", "not_run", "invalid"}
UNITS = {"byte", "s", "cpu_core"}


def _derived_number(value):
    """Render an exact result without overflowing or erasing a nonzero value."""
    number = value.numerator if value.denominator == 1 else float(value)
    if not math.isfinite(number) or (value and number == 0):
        raise OverflowError("derived quantity exceeds finite nonzero representation")
    return number


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
        raise ValueError("UTC timestamp requires RFC3339 Z form with at most six fractional digits")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.utcoffset().total_seconds() != 0:
        raise ValueError("UTC timestamp required")
    return parsed.astimezone(timezone.utc)


def _record(record, *, prediction, now):
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
        return "invalid", "record fields differ from reference contract"
    context = record["context"]
    if not isinstance(context, dict) or set(context) != set(CONTEXT_FIELDS):
        return "invalid", "context fields differ from reference contract"
    if any(v is not None and (not isinstance(v, str) or not v.strip()) for v in context.values()):
        return "invalid", "context identity must be a nonempty string or null"
    state, value, unit = record["state"], record["value"], record["unit"]
    if not isinstance(state, str) or state not in STATES:
        return "invalid", "unknown input state"
    if not isinstance(unit, str) or unit not in UNITS:
        return "invalid", "unsupported unit; explicit conversion required upstream"
    if value is not None and (not _finite(value) or (unit == "byte" and type(value) is not int)):
        return "invalid", "finite nonnegative quantities required; byte values must be integers"
    classes = {"synthetic_model"} if prediction else {"synthetic_contract_fixture", "lab_observed", "operator_observed"}
    if not isinstance(record["evidence_class"], str) or record["evidence_class"] not in classes:
        return "invalid", "evidence class cannot serve this role"
    dates = [record[k] for k in ("measurement_start_utc", "observed_at_utc", "valid_until_utc")]
    if prediction and any(v is not None for v in dates):
        return "invalid", "immutable model prediction uses source identity, not observation freshness"
    if record["source_id"] is not None and (not isinstance(record["source_id"], str) or not record["source_id"].strip()):
        return "invalid", "source identity must be nonempty or null"
    if state != "known":
        return state, "supplied evidence state blocks comparison"
    if value is None or record["source_id"] is None or any(v is None for v in context.values()):
        return "missing", "quantity, source or context identity missing"
    if not prediction:
        if any(v is None for v in dates):
            return "missing", "observation window or explicit validity missing"
        try:
            start, end, until = map(_utc, dates)
        except (ValueError, TypeError, OverflowError):
            return "invalid", "malformed observation timestamp"
        if start > end or end >= until or end > now:
            return "invalid", "observation/validity ordering is invalid or observation is in the future"
        if now >= until:
            return "stale", "observation expired at or before comparison time"
    return "known", "supplied evidence only; identity, coverage and truth require independent review"


def compare_pair(*, prediction, observation, absolute_tolerance, as_of_utc):
    """Observation minus prediction, with explicit same-unit absolute tolerance.

    Tolerance must be declared before inspecting the observation. This function
    cannot verify that chronology or decide the tolerance. Relative absolute error
    uses observation as denominator; it is null for an observed zero. No fitted
    multiplier or resource margin is emitted. Unknown input is never zero.
    """
    now = _utc(as_of_utc)
    result = {"schema_version": "calibration-evidence/v0.1-proposed",
              "comparison": "not_evaluated", "assessment": "incomplete",
              "evidence_class": "offline_derived_check", "as_of_utc": as_of_utc,
              "signed_error": None, "absolute_error": None, "relative_absolute_error": None,
              "execution_authorized": False, "mutation_request": None}
    states = {}
    for name, record in (("prediction", prediction), ("observation", observation)):
        state, reason = _record(record, prediction=name == "prediction", now=now)
        states[name] = {"state": state, "reason": reason,
                        "source_id": record.get("source_id") if isinstance(record, dict) and isinstance(record.get("source_id"), str) else None}
    result["input_states"] = states
    if (not isinstance(absolute_tolerance, dict) or set(absolute_tolerance) != {"value", "unit", "source_id"}
            or not isinstance(absolute_tolerance.get("unit"), str) or absolute_tolerance["unit"] not in UNITS
            or (absolute_tolerance["value"] is not None and not _finite(absolute_tolerance["value"]))
            or (absolute_tolerance["unit"] == "byte" and absolute_tolerance["value"] is not None
                and type(absolute_tolerance["value"]) is not int)):
        result.update(assessment="invalid", reason="malformed absolute tolerance")
        return result
    if any(row["state"] == "invalid" for row in states.values()):
        result.update(assessment="invalid", reason="invalid input")
        return result
    if any(row["state"] != "known" for row in states.values()):
        return result
    if absolute_tolerance["value"] is None or absolute_tolerance["source_id"] is None:
        result.update(reason="explicit predeclared tolerance and its source are required")
        return result
    if not isinstance(absolute_tolerance["source_id"], str) or not absolute_tolerance["source_id"].strip():
        result.update(assessment="invalid", reason="tolerance source must be a nonempty string")
        return result
    differences = [key for key in CONTEXT_FIELDS if prediction["context"][key] != observation["context"][key]]
    if prediction["unit"] != observation["unit"] or prediction["unit"] != absolute_tolerance["unit"]:
        differences.append("unit")
    if differences:
        result.update(comparison="incomparable", assessment="incomparable", differing_fields=differences)
        return result
    observed = Fraction(observation["value"])
    error_exact = observed - Fraction(prediction["value"])
    absolute_exact = abs(error_exact)
    try:
        error = _derived_number(error_exact)
        absolute = _derived_number(absolute_exact)
        relative = _derived_number(absolute_exact / observed) if observed else None
    except OverflowError:
        result.update(assessment="invalid", reason="error arithmetic overflow or underflow")
        return result
    result.update(comparison="comparable", assessment="within_supplied_tolerance" if absolute_exact <= Fraction(absolute_tolerance["value"]) else "outside_supplied_tolerance",
                  unit=prediction["unit"], signed_error=error, absolute_error=absolute,
                  relative_absolute_error=relative, context=dict(prediction["context"]),
                  prediction_class=prediction["evidence_class"], observation_class=observation["evidence_class"],
                  absolute_tolerance=dict(absolute_tolerance))
    return result
