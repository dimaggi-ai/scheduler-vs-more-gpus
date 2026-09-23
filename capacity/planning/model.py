"""Deterministic synthetic observation and planning, with no execution authority."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import math
import platform

import numpy as np

from capacity.report import digest, config_from_dict, POLICIES
from sim.simulator import Simulation, STEPS_PER_HOUR, power_cap_fraction

VERSION = 'capacity-plan/v1'
ACTUAL_VERSION = 'capacity-actual/v1'
ACCOUNT = ('nominal_gpu_h', 'envelope_gpu_h', 'inf_alloc_gpu_h',
           'inf_productive_gpu_h', 'inf_demand_gpu_h', 'train_alloc_gpu_h',
           'train_productive_gpu_h', 'work_lost_gpu_h')
SCENARIOS = ('baseline', 'demand_surge', 'capacity_outage', 'price_spike', 'combined')


def provenance():
    root = Path(__file__).resolve().parents[2]
    files = sorted(p for p in (root / 'capacity/planning').rglob('*')
                   if p.suffix in ('.py', '.sql', '.json') and not p.name.startswith('test_'))
    files += [root / 'sim/simulator.py', root / 'capacity/report.py']
    return {'python': platform.python_version(), 'numpy': np.__version__,
            'source_hashes': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in files}}


def seal(data, key):
    return {**data, key: digest(data)}


def checked_number(value, name, low=0, high=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < low or (high is not None and value > high):
        raise ValueError(f'{name}: finite number in permitted range required')
    return value


def observe(raw_config, *, policy='intent-closed-loop', plan=None, scenario='baseline'):
    """One hourly event stream; original job and random-event generators are reused.

    Warm-up is identical in every scenario. Perturbations begin in the held-out
    period and do not advance random generators, keeping paired replay inputs.
    """
    cfg = config_from_dict(raw_config)
    if policy not in POLICIES or scenario not in SCENARIOS:
        raise ValueError('unknown policy or scenario')
    reservations = demand = caps = None
    cutoff = cfg.horizon_days * 24
    if plan is not None:
        validate_plan(plan)
        if plan['config'] != asdict(cfg) or policy != plan['policy']:
            raise ValueError('plan/config/policy mismatch')
        if plan['provenance'] != provenance():
            raise ValueError('replay requires matching source and runtime provenance')
        cutoff = plan['cutoff_hour']
        by_hour = {r['hour']: r for r in plan['rows']}
        reservations = [None if t // STEPS_PER_HOUR < cutoff else
                        by_hour[t // STEPS_PER_HOUR]['reservation_gpus'] for t in range(cfg.steps)]
        demand = [1.0] * cfg.steps
        caps = [1.0] * cfg.steps
        # Fixed relative windows, recorded in the returned actual artifact.
        for t in range(cfg.steps):
            relative = t / STEPS_PER_HOUR - cutoff
            if scenario in ('demand_surge', 'combined') and 24 <= relative < 48:
                demand[t] = 1.6
            if scenario in ('capacity_outage', 'combined') and 36 <= relative < 42:
                caps[t] = 0.0
    elif scenario != 'baseline':
        raise ValueError('what-if replay requires a frozen plan')
    rows, previous = [], {k: 0.0 for k in ACCOUNT}

    def emit(snapshot):
        if (snapshot['step'] + 1) % STEPS_PER_HOUR:
            return
        hour = snapshot['step'] // STEPS_PER_HOUR
        row = {'hour': hour, **{k: snapshot[k] - previous[k] for k in ACCOUNT}}
        rows.append(row)
        previous.update({k: snapshot[k] for k in ACCOUNT})

    sim = Simulation(cfg, policy)
    sim.run(observer=emit, reservations=reservations, demand_factors=demand, capacity_factors=caps)
    return rows


def forecast(history, cutoff, end, *, method='seasonal', bias=1.0):
    """Only the prefix supplied by the caller is visible to the forecaster.

    Seasonal point estimate: mean of up to three preceding matching hours.
    Bounds use the empirical 90th percentile absolute rolling error. They are
    descriptive residual bands, not a promised prediction-interval coverage.
    """
    if type(cutoff) is not int or type(end) is not int or cutoff < 72 or end <= cutoff:
        raise ValueError('at least 72 complete historical hours and a future window required')
    if (len(history) != cutoff or any(type(r['hour']) is not int for r in history)
            or [r['hour'] for r in history] != list(range(cutoff))):
        raise ValueError('history must be exactly the contiguous prefix before cutoff')
    if method not in ('seasonal', 'last_value'):
        raise ValueError('unknown forecast method')
    checked_number(bias, 'forecast bias', high=3)
    values = [checked_number(r['inf_demand_gpu_h'], 'historical demand') for r in history]

    def point(t, available, which):
        if which == 'last_value':
            return available[-1]
        candidates = [available[i] for i in range(t % 24, len(available), 24)][-3:]
        return sum(candidates) / len(candidates)

    errors = {m: [] for m in ('seasonal', 'last_value')}
    # Rolling one-step validation using ONLY prefix observations at each origin.
    for t in range(48, cutoff):
        for m in errors:
            errors[m].append(abs(values[t] - point(t, values[:t], m)))
    band = float(np.quantile(errors[method], 0.90))
    rows = []
    for h in range(cutoff, end):
        estimate = point(h, values, method) * bias
        rows.append({'hour': h, 'demand_gpu_h': estimate,
                     'lower_gpu_h': max(0, estimate - band), 'upper_gpu_h': estimate + band})
    return {'method': method, 'bias': bias, 'issued_at_hour': cutoff,
            'history_id': digest(history), 'rows': rows,
            'backtest': {m: {'mae_gpu_h': sum(e) / len(e), 'observations': len(e)} for m, e in errors.items()},
            'interval_kind': 'empirical rolling absolute-error band; no coverage guarantee',
            'backtest_scope': 'one-step rolling; not validation of the full frozen forecast horizon'}


def build_plan(raw_config, history, cutoff, *, method='seasonal', bias=1.0,
               headroom=0.10, rate=2.0, policy='intent-closed-loop'):
    cfg = config_from_dict(raw_config)
    if policy not in POLICIES:
        raise ValueError('unknown policy')
    checked_number(headroom, 'headroom', high=1)
    checked_number(rate, 'rate', high=1000000)
    f = forecast(history, cutoff, cfg.horizon_days * 24, method=method, bias=bias)
    for row in history:
        if set(row) != {'hour', *ACCOUNT} or abs(row['nominal_gpu_h'] - cfg.gpus) > 1e-5:
            raise ValueError('history schema or nominal capacity mismatch')
        validate_account(row)
    allocated = sum(r['train_alloc_gpu_h'] for r in history)
    train_ratio = max(0, min(1, sum(r['train_productive_gpu_h'] for r in history) / max(allocated, 1e-12)))
    remaining = sum(max(0, r['envelope_gpu_h'] - r['inf_alloc_gpu_h']) for r in history)
    fill_ratio = min(1, allocated / max(remaining, 1e-12))
    rows = []
    for prediction in f['rows']:
        h = prediction['hour']
        # Supply policy is announced configuration; future stochastic failures are unknown.
        envelope = sum(int(cfg.gpus * power_cap_fraction(cfg, h * STEPS_PER_HOUR + t))
                       for t in range(STEPS_PER_HOUR)) / STEPS_PER_HOUR
        reservation = min(math.floor(envelope), math.ceil(prediction['demand_gpu_h'] * (1 + headroom)))
        train_budget = envelope - reservation
        train_alloc = train_budget * fill_ratio
        rows.append({'hour': h, 'reservation_gpus': reservation,
                     'training_budget_gpu_h': train_budget,
                     'nominal_gpu_h': float(cfg.gpus), 'envelope_gpu_h': envelope,
                     'inf_demand_gpu_h': prediction['demand_gpu_h'],
                     'inf_alloc_gpu_h': float(reservation),
                     'inf_productive_gpu_h': min(prediction['demand_gpu_h'], reservation),
                     'train_alloc_gpu_h': train_alloc,
                     'train_productive_gpu_h': train_alloc * train_ratio,
                     'work_lost_gpu_h': 0.0, 'rate_usd_per_allocated_gpu_h': rate})
    plan = seal({'schema': VERSION, 'evidence_kind': 'synthetic',
                 'workload_id': 'aggregate-inference-and-training/v1',
                 'hardware_id': 'abstract-homogeneous-gpu/v1', 'unit': 'GPU-hour',
                 'clock': 'elapsed simulation hours; half-open hourly windows',
                 'config': asdict(cfg), 'policy': policy, 'cutoff_hour': cutoff,
                 'provenance': provenance(), 'forecast': f, 'headroom': headroom,
                 'training_fill_ratio': fill_ratio, 'training_retention_ratio': train_ratio,
                 'cost_basis': 'synthetic USD per allocated GPU-hour; not energy or TCO',
                 'rows': rows}, 'plan_id')
    validate_plan(plan)
    return plan


def validate_account(row):
    for k in ACCOUNT:
        checked_number(row[k], k, low=-1e15 if k == 'train_productive_gpu_h' else -1e-6)
    n, e, ia, ip, d, ta, tp, lost = (row[k] for k in ACCOUNT)
    eps = 1e-5
    if e > n + eps or ia + ta > e + eps or ip > min(d, ia) + eps or tp + lost > ta + eps or tp + lost < -eps:
        raise ValueError('invalid capacity accounting or unexplained negative productivity')


def validate_plan(plan):
    from .schema import validate_artifact
    validate_artifact(plan, 'plan')
    if plan['plan_id'] != digest({k: v for k, v in plan.items() if k != 'plan_id'}):
        raise ValueError('plan digest mismatch')
    cfg = config_from_dict(plan['config'])
    start, end = plan['cutoff_hour'], cfg.horizon_days * 24
    if [r['hour'] for r in plan['rows']] != list(range(start, end)):
        raise ValueError('plan requires exact contiguous future hours')
    f = plan['forecast']
    if f['issued_at_hour'] != start or [r['hour'] for r in f['rows']] != list(range(start, end)):
        raise ValueError('forecast/plan temporal mismatch')
    for row, prediction in zip(plan['rows'], f['rows']):
        validate_account(row)
        if row['nominal_gpu_h'] != cfg.gpus or row['inf_demand_gpu_h'] != prediction['demand_gpu_h']:
            raise ValueError('plan identity or forecast mismatch')
        if not prediction['lower_gpu_h'] <= prediction['demand_gpu_h'] <= prediction['upper_gpu_h']:
            raise ValueError('invalid forecast bounds')
        if row['train_alloc_gpu_h'] > row['training_budget_gpu_h'] + 1e-5:
            raise ValueError('training allocation exceeds budget')
        if row['reservation_gpus'] != row['inf_alloc_gpu_h'] or abs(row['training_budget_gpu_h'] + row['inf_alloc_gpu_h'] - row['envelope_gpu_h']) > 1e-5:
            raise ValueError('allocation budget mismatch')


def actual_artifact(plan, scenario='baseline'):
    rows = observe(plan['config'], policy=plan['policy'], plan=plan, scenario=scenario)[plan['cutoff_hour']:]
    planned = {r['hour']: r for r in plan['rows']}
    for row in rows:
        relative = row['hour'] - plan['cutoff_hour']
        rate = planned[row['hour']]['rate_usd_per_allocated_gpu_h']
        row['rate_usd_per_allocated_gpu_h'] = rate * (3 if scenario in ('price_spike', 'combined') and 24 <= relative < 48 else 1)
    return seal({'schema': ACTUAL_VERSION, 'plan_id': plan['plan_id'], 'scenario': scenario,
                 **{k: plan[k] for k in ('evidence_kind', 'workload_id', 'hardware_id', 'unit', 'clock', 'provenance')},
                 'interventions': {'demand_factor': 1.6 if scenario in ('demand_surge', 'combined') else 1,
                                   'demand_window_after_cutoff': [24, 48],
                                   'capacity_factor': 0 if scenario in ('capacity_outage', 'combined') else 1,
                                   'capacity_window_after_cutoff': [36, 42],
                                   'rate_factor': 3 if scenario in ('price_spike', 'combined') else 1,
                                   'rate_window_after_cutoff': [24, 48]},
                 'rows': rows}, 'actual_id')


def validate_actual(plan, actual):
    from .schema import validate_artifact
    validate_plan(plan)
    validate_artifact(actual, 'actual')
    if actual['actual_id'] != digest({k: v for k, v in actual.items() if k != 'actual_id'}):
        raise ValueError('actual digest mismatch')
    if actual['plan_id'] != plan['plan_id'] or any(actual[k] != plan[k] for k in ('evidence_kind', 'workload_id', 'hardware_id', 'unit', 'clock', 'provenance')):
        raise ValueError('actual/plan identity or provenance mismatch')
    hours = [r['hour'] for r in actual['rows']]
    if hours != sorted(set(hours)) or not set(hours) <= {r['hour'] for r in plan['rows']}:
        raise ValueError('duplicate, unordered or out-of-window actual events')
    for row in actual['rows']:
        validate_account(row)
        if abs(row['nominal_gpu_h'] - plan['config']['gpus']) > 1e-5:
            raise ValueError('actual nominal capacity mismatch')
