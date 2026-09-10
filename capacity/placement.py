"""Optional, offline previews using the existing domain packages.

No hardware calls, scheduler bindings or actuation permissions. Geometry and
admission are separate results; this module does not claim to bind an envelope
to a newly allocated rectangle or compose all physical gates.
"""
from __future__ import annotations


def placement_preview(fabric, requests):
    """Try requests in supplied order on a COPY using slicepacker's algorithm.

    This is sequential packing, not a sum of independently placeable jobs.
    Isolation is deliberately not assumed from a tenant label. Callers needing
    isolation must use slicepacker.tenant's domain/policy API instead.
    """
    from slicepacker import NoPlacement

    trial = fabric.copy()
    requests = list(requests)
    ids = [r.job_id for r in requests]
    if any(not jid for jid in ids) or len(set(ids)) != len(ids):
        raise ValueError("requests must have unique nonempty job IDs")
    if set(ids) & trial.allocations.keys():
        raise ValueError("request job ID is already allocated")
    if any(r.tenant for r in requests):
        raise ValueError("tenant isolation is not implemented by this preview; use slicepacker.tenant")
    for rect in trial.allocations.values():
        if rect.ndim != trial.pod.ndim or not rect.fits_in(trial.pod):
            raise ValueError("existing allocation is outside the pod")
    rectangles = list(trial.allocations.values())
    if any(a.overlaps(b) for i, a in enumerate(rectangles) for b in rectangles[i + 1:]):
        raise ValueError("existing allocations overlap")
    for coord in trial.unhealthy:
        if len(coord) != trial.pod.ndim or any(c < 0 or c >= e for c, e in zip(coord, trial.pod.extents)):
            raise ValueError("unhealthy coordinate is outside the pod")
    before = trial.free_chips()
    rows = []
    for request in requests:
        if request.shape is not None and len(request.shape) != trial.pod.ndim:
            raise ValueError("request shape dimensionality differs from pod")
        try:
            rect = trial.place(request)
            rows.append({"job_id": request.job_id, "status": "placeable",
                         "origin": list(rect.origin), "extent": list(rect.extent),
                         "chips": rect.chips})
        except NoPlacement as exc:
            rows.append({"job_id": request.job_id, "status": "unplaceable", "reason": str(exc)})
    return {"evidence_kind": "simulation", "scope": "geometry-only",
            "free_chips_before": before, "free_chips_after": trial.free_chips(),
            "requests": rows, "execution_authorized": False,
            "not_checked": ["Tenant isolation", "Span admission", "Power and cooling admission",
                            "Communication performance", "Concurrent live allocation changes"]}


def admission_preview(envelope, *, plant=None, policy=None):
    """Preserve span-contract's refusals AND missing checks, without acting."""
    from spancontract import validate
    import json

    # NaN can evade numeric comparisons in a caller-constructed dataclass.
    json.dumps(envelope.to_dict(), allow_nan=False)

    verdict = validate(envelope, plant=plant, policy=policy)
    return {"evidence_kind": "contract-check", "decision": verdict.decision.value,
            "reasons": verdict.reasons(), "not_checked": list(verdict.not_checked),
            "passes_supplied_checks": verdict.allowed and not verdict.not_checked,
            "execution_authorized": False}
