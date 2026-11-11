"""Offline coverage of an explicit, domain-reviewed resource requirement set.

Uses existing scalar predicates; does not infer a topology or discover omitted
requirements in the manifest itself. A manifest is supplied domain input, not
authorization. No application, scheduler adapter, observation or effect exists.
"""
from __future__ import annotations

from capacity.resource_evidence import UNITS, _inputs, capacity_check

BINDING = {"manifest_id", "profile_id", "workload_id", "config_id"}


def _object(value, fields, label):
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"{label} requires exactly {sorted(fields)}")


def _id(value, label):
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{label} must be nonempty text without outer whitespace")


def _key(entry):
    _id(entry["scope_id"], "scope_id")
    if type(entry["resource"]) is not str or entry["resource"] not in UNITS:
        raise ValueError("unsupported resource")
    return entry["scope_id"], entry["resource"]


def _shortfall_bound(entry, states):
    """A bound may prove failure, never success; preserve actual missing inputs.

    Zero here is a mathematical lower bound from the nonnegative domain, not an
    invented observation or default workload margin. Unusable capacity provides
    no upper bound, so stale/missing availability cannot support this proof.
    """
    if states["available"]["state"] != "known":
        return None
    zero = {"value": 0, "unit": UNITS[entry["resource"]], "state": "known",
            "source_id": "derived/nonnegative-domain-lower-bound",
            "evidence_class": "synthetic_model"}
    components = {name: q for name, q in entry["demand_components"].items()
                  if states["demand/" + name]["state"] == "known"}
    if not components:
        components = {"nonnegative_domain_lower_bound": zero}
    margin = entry["margin"] if states["margin"]["state"] == "known" else zero
    bound = capacity_check(scope_id=entry["scope_id"], resource=entry["resource"],
                           demand_components=components, available=entry["available"], margin=margin)
    bound["meaning"] = "Lower bound only; omitted/unknown requirements remain unknown. A pass cannot establish fit."
    return bound


def evaluate_coverage(manifest, bundle):
    """Evaluate all supplied scalar checks and preserve omitted requirements.

    Null manifest/bundle means missing evidence. Structural contradictions
    (duplicates, undeclared scopes/components or different binding) raise
    ValueError. Missing components are not zero. Supplied components may prove a
    shortfall as a lower bound, but cannot pass an incomplete component set.
    A failed check still refuses the aggregate when other scopes are missing.
    """
    result = {"schema_version": "resource-coverage/v0.1-proposed",
              "evidence_class": "offline_derived_check", "coverage": "incomplete",
              "resource_readiness": "incomplete", "binding": None,
              "checks": [], "missing_requirements": [],
              "execution_authorized": False, "mutation_request": None,
              "not_checked": ["manifest completeness against actual workload and topology",
                              "source authenticity and live freshness", "geometry, plant and isolation",
                              "storage access/locality and checkpoint write/restore service",
                              "calibration, baseline, policy and permission"]}
    if manifest is None:
        result["missing_requirements"] = [{"kind": "manifest"}]
        return result
    _object(manifest, BINDING | {"schema_version", "requirements"}, "manifest")
    if manifest["schema_version"] != "resource-requirements/v0.1-proposed":
        raise ValueError("unsupported manifest version")
    for name in BINDING:
        _id(manifest[name], name)
    result["binding"] = {name: manifest[name] for name in sorted(BINDING)}
    if type(manifest["requirements"]) is not list or not manifest["requirements"]:
        raise ValueError("manifest requires a nonempty explicit requirement set")
    required = {}
    for entry in manifest["requirements"]:
        _object(entry, {"scope_id", "resource", "component_ids"}, "requirement")
        key = _key(entry)
        components = entry["component_ids"]
        if type(components) is not list or not components:
            raise ValueError("each requirement needs explicit disjoint component IDs")
        for name in components:
            _id(name, "component_id")
        if key in required or len(set(components)) != len(components):
            raise ValueError("duplicate requirement or component; shared capacity is declared once")
        required[key] = components
    supplied = {}
    if bundle is not None:
        _object(bundle, BINDING | {"schema_version", "checks"}, "bundle")
        if bundle["schema_version"] != "resource-evidence-bundle/v0.1-proposed":
            raise ValueError("unsupported bundle version")
        if any(type(bundle[name]) is not str or bundle[name] != manifest[name] for name in BINDING):
            raise ValueError("bundle and manifest bindings differ")
        if type(bundle["checks"]) is not list:
            raise ValueError("checks must be a list")
        for entry in bundle["checks"]:
            _object(entry, {"scope_id", "resource", "demand_components", "available", "margin"}, "check")
            key = _key(entry)
            if key not in required or key in supplied:
                raise ValueError("undeclared or duplicate scope/resource check")
            if type(entry["demand_components"]) is not dict:
                raise ValueError("demand_components must be a map")
            if any(type(name) is not str or name not in required[key] for name in entry["demand_components"]):
                raise ValueError("undeclared component; revise the domain manifest before comparing")
            supplied[key] = entry
    for (scope, resource), components in required.items():
        key = scope, resource
        if key not in supplied:
            gap = {"scope_id": scope, "resource": resource, "kind": "missing_check"}
            result["missing_requirements"].append(gap)
            result["checks"].append({**gap, "check_state": "missing"})
            continue
        entry = supplied[key]
        missing = [name for name in components if name not in entry["demand_components"]]
        if missing:
            gap = {"scope_id": scope, "resource": resource, "kind": "missing_components", "component_ids": missing}
            result["missing_requirements"].append(gap)
            quantities = {"demand/" + name: q for name, q in entry["demand_components"].items()}
            quantities.update(available=entry["available"], margin=entry["margin"])
            states, readiness = _inputs(quantities, UNITS[resource])
            row = {**gap, "check_state": "invalid" if readiness == "refused" else "missing", "input_states": states}
            if readiness != "refused":
                partial = _shortfall_bound(entry, states)
                if partial is not None:
                    row["known_components_lower_bound"] = partial
                    if partial["check_state"] in {"fail", "invalid"}:
                        row["check_state"] = partial["check_state"]
            result["checks"].append(row)
            continue
        row = capacity_check(**entry)
        if row["engineering_readiness"] == "incomplete":
            partial = _shortfall_bound(entry, row["input_states"])
            if partial is not None:
                row["known_components_lower_bound"] = partial
                if partial["check_state"] in {"fail", "invalid"}:
                    row.update(check_state=partial["check_state"], engineering_readiness="refused")
        result["checks"].append(row)
    states = [row["check_state"] for row in result["checks"]]
    # Coverage and feasibility are independent: a complete record set can fail
    # capacity, and a refused resource can coexist with missing scope evidence.
    result["coverage"] = "complete" if not result["missing_requirements"] else "incomplete"
    result["resource_readiness"] = (
        "refused" if any(state in {"fail", "invalid"} for state in states)
        else "incomplete" if any(state != "pass" for state in states)
        else "feasible_within_declared_resource_checks")
    return result
