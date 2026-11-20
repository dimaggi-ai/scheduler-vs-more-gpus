"""Pure deterministic route comparison; no IO or hidden global state."""
import math
from .contracts import validate, digest
from .contacts import transfer
from .resources import Refusal, compute, empty_state, trial
from . import VERSION

ROUTES = ('ground', 'onboard', 'hybrid')


def plan_route(scenario, route, *, source_sha256=None):
    validate(scenario)
    _validate_source(source_sha256)
    return _plan_route(scenario, route, source_sha256)


def _validate_source(value):
    if value is not None and (not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError('source_sha256 must be lowercase hex SHA-256 or None (unbound API call)')


def receipt_id(input_sha256, source_sha256, row, events):
    return digest({'schema': 'capacity-orbital/receipt-v2', 'input_sha256': input_sha256,
                   'source_sha256': source_sha256, 'version': VERSION,
                   'outcome': {k: v for k, v in row.items() if k != 'receipt_id'}, 'events': events})


def _plan_route(scenario, route, source_sha256):
    if route not in ROUTES:
        raise ValueError('unsupported route')
    source_hash = digest(scenario)
    state = empty_state(scenario)
    outcomes = []
    for j in sorted(scenario['jobs'], key=lambda j: (j['release_s'], j['id'])):
        candidate = trial(state)
        before = len(candidate['events'])
        quality = 1.0 if route == 'ground' else j[route + '_quality']
        row = dict(job_id=j['id'], route=route, deadline_s=j['deadline_s'], required_quality=j['required_quality'], quality=quality,
                   status='refused', reason=None, completion_s=None, downlink_gb=0.0, energy_kwh=0.0, cost_usd=0.0, receipt_id=None)
        try:
            if quality < j['required_quality']:
                raise Refusal('retained quality below requirement')
            t = j['release_s']
            if route == 'ground':
                t = transfer(scenario, candidate, j, t, j['raw_gb'])
                t = compute(scenario, candidate, j, 'ground', t, j['ground_s'])
            elif route == 'onboard':
                t = compute(scenario, candidate, j, 'orbital', t, j['onboard_s'])
                t = transfer(scenario, candidate, j, t, j['result_gb'])
            else:
                t = compute(scenario, candidate, j, 'orbital', t, j['preprocess_s'])
                t = transfer(scenario, candidate, j, t, j['compressed_gb'])
                t = compute(scenario, candidate, j, 'ground', t, j['hybrid_ground_s'])
            events = candidate['events'][before:]
            energy = sum(e.get('energy_kwh', 0) for e in events)
            cost = sum(e['cost_usd'] for e in events)
            if not all(math.isfinite(v) for v in (t, energy, cost)):
                raise ValueError('derived result is not finite')
            row.update(status='planned', completion_s=t, downlink_gb=sum(e.get('gb', 0) for e in events),
                       energy_kwh=energy, cost_usd=cost)
            row['receipt_id'] = receipt_id(source_hash, source_sha256, row, events)
            for index, end in candidate['contact_updates'].items():
                candidate['contacts'][index] = end
            state['events'].extend(candidate['events'])
            candidate['events'] = state['events']
            state = candidate
        except Refusal as exc:
            row['reason'] = str(exc)
        outcomes.append(row)
    count = sum(r['status'] == 'planned' for r in outcomes)
    cost = sum(r['cost_usd'] for r in outcomes)
    if not all(math.isfinite(v) for v in (cost, sum(r['energy_kwh'] for r in outcomes), sum(r['downlink_gb'] for r in outcomes))):
        raise ValueError('aggregate result is not finite')
    return dict(route=route, jobs=outcomes, events=state['events'], summary=dict(
        planned=count, refused=len(outcomes)-count, downlink_gb=sum(r['downlink_gb'] for r in outcomes),
        energy_kwh=sum(r['energy_kwh'] for r in outcomes), cost_usd=cost,
        cost_per_planned_result_usd=cost/count if count else None))


def compare(scenario, *, source_sha256=None):
    validate(scenario)
    _validate_source(source_sha256)
    return dict(schema='capacity-orbital/report-v1', version=VERSION, name=scenario['name'],
                input_sha256=digest(scenario), source_sha256=source_sha256,
                receipt_schema='capacity-orbital/receipt-v2',
                source_binding='caller-supplied' if source_sha256 else 'unbound: no code digest supplied',
                provenance=scenario['provenance'],
                classification='synthetic offline plan; not measured execution or flight qualification',
                assumptions=['All jobs originate in space and results terminate on the ground.',
                             'Ground quality 1.0 is a synthetic reference assumption, not measured perfect AI accuracy.',
                             'Each route is a separate counterfactual with the same workload and resource inputs.',
                             'One serial compute lane per node; one shared downlink terminal.',
                             'One assumed job power_kw applies on both nodes; hardware-specific power profiles are not modeled.',
                             'Release-time then job-id greedy planning; no optimality guarantee.',
                             'Static power and heat rejection envelopes, total compute-energy budgets; no orbital/thermal dynamics.',
                             'Transfer energy, lifecycle capex, qualification, radiation and unplanned runtime failures excluded.',
                             'Refused plans reserve nothing; no claim that failed execution is free.',
                             'Receipts are deterministic planning IDs, not signatures or production metering.'],
                comparisons=[_plan_route(scenario, r, source_sha256) for r in ROUTES])
