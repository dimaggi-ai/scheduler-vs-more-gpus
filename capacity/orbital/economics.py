"""Partial synthetic cost model: compute time, compute electricity and transfer GB only. Pure; no IO."""
import math


def compute_cost_usd(node, duration_s, energy_kwh):
    return duration_s / 3600 * node['compute_usd_per_hour'] + energy_kwh * node['electricity_usd_per_kwh']


def transfer_cost_usd(contact, gb):
    return gb * contact['usd_per_gb']


def summarize(outcomes):
    count = sum(r['status'] == 'planned' for r in outcomes)
    cost = sum(r['cost_usd'] for r in outcomes)
    if not all(math.isfinite(v) for v in (cost, sum(r['energy_kwh'] for r in outcomes), sum(r['downlink_gb'] for r in outcomes))):
        raise ValueError('aggregate result is not finite')
    return dict(
        planned=count, refused=len(outcomes)-count, downlink_gb=sum(r['downlink_gb'] for r in outcomes),
        energy_kwh=sum(r['energy_kwh'] for r in outcomes), cost_usd=cost,
        cost_per_planned_result_usd=cost/count if count else None)
