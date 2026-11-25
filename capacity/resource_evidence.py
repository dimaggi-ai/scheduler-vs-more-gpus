"""Small, offline resource predicates for a supplied batch placement.

This is Maggie's domain reference, not admission control or a telemetry adapter.
It cannot establish freshness, authenticity, allocation or whole-job readiness.
No operator quantities, resource margins or distributions are defaulted.
"""
from __future__ import annotations

import math
from fractions import Fraction

UNITS = {"cpu": "cpu_core", "host_memory": "byte", "pinned_host_memory": "byte",
         "gpu_memory": "byte", "storage": "byte"}
INPUT_STATES = {"known", "missing", "stale", "not_run", "invalid"}
EVIDENCE_CLASSES = {"synthetic_model", "synthetic_contract_fixture", "lab_observed", "operator_observed"}


def _derived_number(value):
    """Render an exact result without overflowing or erasing a nonzero value."""
    number = value.numerator if value.denominator == 1 else float(value)
    if not math.isfinite(number) or (value and number == 0):
        raise OverflowError("derived quantity exceeds finite nonzero representation")
    return number


def _quantity(raw, unit):
    if not isinstance(raw, dict) or set(raw) != {"value", "unit", "state", "source_id", "evidence_class"}:
        return "invalid", "quantity requires value, unit, state, source_id and evidence_class"
    if not isinstance(raw["evidence_class"], str) or raw["evidence_class"] not in EVIDENCE_CLASSES:
        return "invalid", "unsupported evidence class"
    if raw["unit"] != unit:
        return "invalid", "unit differs; conversion must be explicit upstream"
    state = raw["state"]
    if not isinstance(state, str) or state not in INPUT_STATES:
        return "invalid", "unknown evidence state"
    value = raw["value"]
    if value is not None:
        kinds = (int,) if unit == "byte" else (int, float)
        if type(value) not in kinds or (type(value) is float and not math.isfinite(value)) or value < 0:
            return "invalid", "quantity must be finite nonnegative; bytes must be integers; bool is not a quantity"
        if unit != "byte":
            try:
                representable = math.isfinite(value)
            except OverflowError:
                representable = False
            if not representable:
                return "invalid", "CPU/time quantity exceeds finite numeric representation"
    if state != "known":
        return state, "input evidence does not establish a usable quantity"
    if value is None:
        return "missing", "known label has no value"
    if not isinstance(raw["source_id"], str) or not raw["source_id"].strip():
        return "missing", "known value has no source identity"
    return "known", "supplied value and source only; freshness/authenticity not verified here"


def _inputs(quantities, unit):
    states = {key: dict(zip(("state", "reason"), _quantity(q, unit))) for key, q in quantities.items()}
    for key, q in quantities.items():
        for field in ("source_id", "evidence_class"):
            states[key][field] = q.get(field) if isinstance(q, dict) and isinstance(q.get(field), str) else None
    bad = [entry["state"] for entry in states.values() if entry["state"] != "known"]
    readiness = "refused" if "invalid" in bad else ("incomplete" if bad else None)
    return states, readiness


def _base(scope_id, resource):
    if not isinstance(scope_id, str) or not scope_id.strip():
        raise ValueError("an explicit node/device/storage-domain scope_id is required")
    return {"schema_version": "resource-evidence-check/v0.1", "scope_id": scope_id,
            "resource": resource, "evidence_kind": "offline_derived_check",
            "execution_authorized": False, "mutation_request": None}


def _blocked_state(states):
    for state in ("invalid", "missing", "stale", "not_run"):
        if any(entry["state"] == state for entry in states.values()):
            return state
    raise ValueError("no blocking input state")


def capacity_check(*, scope_id, resource, demand_components, available, margin):
    """Compare disjoint peak components + explicit margin to residual capacity.

    Supply a separate check for each bound node/device/storage domain. Available
    means residual usable capacity AFTER existing commitments/system reservations;
    margin is additional workload uncertainty, not those same reservations again.
    Unknown values or margin cannot pass. Caller owns complete placement coverage.
    """
    if not isinstance(resource, str) or resource not in UNITS:
        raise ValueError("unsupported resource")
    if (not isinstance(demand_components, dict) or not demand_components
            or any(not isinstance(k, str) or not k.strip() for k in demand_components)):
        raise ValueError("nonempty, uniquely named disjoint demand components required")
    unit = UNITS[resource]
    result = _base(scope_id, resource)
    quantities = {"demand/" + k: q for k, q in demand_components.items()}
    quantities.update(available=available, margin=margin)
    states, readiness = _inputs(quantities, unit)
    result.update(unit=unit, input_states=states, required=None, available=None, headroom=None)
    if readiness:
        result.update(engineering_readiness=readiness, check_state=_blocked_state(states))
        return result
    required_exact = sum(Fraction(q["value"]) for q in demand_components.values()) + Fraction(margin["value"])
    headroom_exact = Fraction(available["value"]) - required_exact
    try:
        required = required_exact.numerator if unit == "byte" else _derived_number(required_exact)
        headroom = headroom_exact.numerator if unit == "byte" else _derived_number(headroom_exact)
    except OverflowError:
        result.update(engineering_readiness="refused", check_state="invalid",
                      reason="derived arithmetic overflow or underflow")
        return result
    passed = headroom_exact >= 0
    result.update(required=required, available=available["value"], headroom=headroom,
                  engineering_readiness="feasible_within_supplied_capacity" if passed else "refused",
                  check_state="pass" if passed else "fail")
    return result


def checkpoint_bound_check(*, scope_id, lower_bound_s, budget_s):
    """A transfer lower bound can reject a deadline but cannot prove it achievable.

    Reuse netcap.regimes.circuit_lower_bound_s for its circuit model, or supply
    another explicitly justified bound. A benchmark mean is not an upper bound
    on rate and does not automatically establish a physical time lower bound.
    """
    result = _base(scope_id, "checkpoint_duration")
    states, readiness = _inputs({"lower_bound": lower_bound_s, "budget": budget_s}, "s")
    result.update(unit="s", input_states=states, lower_bound_s=None, budget_s=None)
    if readiness:
        result.update(engineering_readiness=readiness, check_state=_blocked_state(states))
        return result
    bound, budget = lower_bound_s["value"], budget_s["value"]
    failed = bound > budget
    result.update(lower_bound_s=bound, budget_s=budget,
                  engineering_readiness="refused" if failed else "incomplete",
                  check_state="fail" if failed else "not_run",
                  reason="even optimistic transfer exceeds budget" if failed else
                  "bound does not prove staging, contention, durable commit or restore completion")
    return result
