"""Training selection and held-out assessment against immutable replay inputs.

The evaluator is explicitly the v1 static planner. A future dynamics adapter must
be a reviewed code change with a new evaluator identity, never a JSON callback.
"""
import copy
import math
from ..contracts import digest
from ..planner import plan_route
from .contracts import validate_suite, validate_routes

EVALUATOR = 'capacity-orbital/static-planner-v1'


def quantile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def assess(entries, route, source_sha256):
    outcomes, latencies, qualities, minimums, successful = [], [], [], [], []
    totals = dict(jobs=0, planned=0, refused=0, late=0, quality_failing=0,
                  cost_usd=0.0, energy_kwh=0.0, downlink_gb=0.0)
    for entry in entries:
        scenario = entry['scenario']
        report = plan_route(scenario, route, source_sha256=source_sha256)
        released = {j['id']: j['release_s'] for j in scenario['jobs']}
        for row in report['jobs']:
            totals['jobs'] += 1
            if row['status'] == 'planned':
                late = row['completion_s'] > row['deadline_s']
                bad_quality = row['quality'] < row['required_quality']
                totals['late'] += int(late)
                totals['quality_failing'] += int(bad_quality)
                if not late and not bad_quality:
                    totals['planned'] += 1
                    successful.append([entry['id'], row['job_id']])
                    latencies.append(row['completion_s'] - released[row['job_id']])
                    qualities.append(row['quality'])
                    minimums.append(row['required_quality'])
            else:
                totals['refused'] += 1
            for key in ('cost_usd', 'energy_kwh', 'downlink_gb'):
                totals[key] += row[key]
        outcomes.append({'scenario_id': entry['id'], 'input_sha256': digest(scenario),
                         'outcome_sha256': digest(report), 'report': report})
    totals['failed'] = totals['jobs'] - totals['planned']
    totals['cost_per_planned_result_usd'] = totals['cost_usd'] / totals['planned'] if totals['planned'] else None
    totals['latency_p50_s'] = quantile(latencies, .5)
    totals['latency_p95_s'] = quantile(latencies, .95)
    totals['quality_min'] = min(qualities) if qualities else None
    totals['required_quality_min'] = min(minimums) if minimums else None
    totals['required_quality_max'] = max(minimums) if minimums else None
    if any(not math.isfinite(v) for v in totals.values() if isinstance(v, (int, float))):
        raise ValueError('aggregate evaluation score is not finite')
    return {'route': route, 'metrics': totals, 'successful_jobs': successful, 'outcomes': outcomes}


def evaluate(suite, baseline, candidates, source_sha256):
    suite = copy.deepcopy(validate_suite(suite))
    validate_routes(baseline, candidates)
    suite_hash = digest(suite)
    # Registry order makes selection invariant to caller-supplied candidate ordering.
    routes = sorted(set(candidates) | {baseline})
    training = {r: assess(suite['train'], r, source_sha256) for r in routes}
    baseline_jobs = set(map(tuple, training[baseline]['successful_jobs']))
    eligible = [r for r in routes if baseline_jobs <= set(map(tuple, training[r]['successful_jobs']))]
    excluded = [r for r in routes if r not in eligible]
    minimum_failures = min(training[r]['metrics']['failed'] for r in eligible)
    contenders = [r for r in eligible if training[r]['metrics']['failed'] == minimum_failures]
    cheapest = min(training[r]['metrics']['cost_usd'] for r in contenders)
    contenders = [r for r in contenders if training[r]['metrics']['cost_usd'] <= cheapest + suite['cost_tolerance_usd']]
    selected = baseline if baseline in contenders else contenders[0]
    # Selection is now fixed. Held-out observations cannot change the winner.
    heldout = {r: assess(suite['heldout'], r, source_sha256) for r in sorted({baseline, selected})}
    base = heldout[baseline]
    candidate = heldout[selected]
    b, c = base['metrics'], candidate['metrics']
    preserved = set(map(tuple, base['successful_jobs'])) <= set(map(tuple, candidate['successful_jobs']))
    tolerance = suite['cost_tolerance_usd']
    if not preserved or c['failed'] > b['failed']:
        disposition, reason = 'regression', 'candidate loses baseline useful outcomes'
    elif c['failed'] < b['failed']:
        disposition, reason = 'improvement', 'fewer failed jobs with baseline useful outcomes preserved'
    elif c['cost_usd'] < b['cost_usd'] - tolerance and c['planned']:
        disposition, reason = 'improvement', 'lower partial cost at equal useful output and unchanged quality requirements'
    elif c['cost_usd'] > b['cost_usd'] + tolerance:
        disposition, reason = 'regression', 'higher partial cost at equal useful output'
    else:
        disposition, reason = 'no_improvement', 'no eligible difference beyond fixed tolerances'
    return {
        'schema': 'capacity-orbital/evaluation-result-v1', 'evaluator': EVALUATOR,
        'classification': 'synthetic replay proposals; not measured execution or production improvement',
        'source_sha256': source_sha256, 'suite_sha256': suite_hash,
        'specification': {k: suite[k] for k in ('schema', 'objective', 'cost_tolerance_usd')},
        'baseline': baseline, 'candidates': sorted(candidates), 'selected_on_train': selected,
        'training': training, 'heldout': heldout,
        'training_excluded_for_lost_baseline_outcomes': excluded,
        'heldout_disposition': disposition, 'reason': reason,
        'recommendation': 'independent_review' if disposition == 'improvement' else 'retain_baseline',
        'active_policy': baseline, 'promoted': False,
        'stopping_condition': 'all_candidates_evaluated',
        'assumptions': [
            'Only registered whole-scenario ground/onboard/hybrid policies; no per-job optimizer.',
            'Same immutable scenarios, quality requirements, prices and constraints for every route.',
            'Ground quality 1.0 is an assumed reference, not measured perfect accuracy; retained quality differs by route.',
            'Cost is partial planning cost, not lifecycle TCO; refused plans are not failed physical executions.',
            'Training selects the candidate; held-out assessment never reselects it or promotes it.',
            'Local content hashes are provenance bindings, not signatures or Tool Guard authorization.',
            'Static planner only; task106 dynamic-state composition is not implemented or claimed.'],
    }
