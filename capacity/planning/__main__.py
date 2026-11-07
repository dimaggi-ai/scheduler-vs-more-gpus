"""python -m capacity.planning demo --output /new/directory"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

import duckdb

from .model import (build_plan, observe, actual_artifact, seal, SCENARIOS, provenance, forecast,
                    horizon_backtest, band_coverage, method_warning)
from .ledger import Ledger


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


@contextmanager
def publish_directory(destination):
    """Serialize publishers; incomplete work is never presented as a final bundle."""
    destination = Path(destination).absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.with_name(destination.name + '.lock')
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    stage = None
    try:
        if destination.exists():
            raise ValueError('output already exists; choose a new directory')
        stage = Path(tempfile.mkdtemp(prefix='.' + destination.name + '-', dir=destination.parent))
        yield stage
        if destination.exists():
            raise ValueError('output appeared during build; refusing replacement')
        stage.rename(destination)
        stage = None
    finally:
        if stage is not None:
            shutil.rmtree(stage)
        lock.unlink()


def markdown(reports, plan, skill):
    lines = ['# Forecast, allocation and variance review', '',
             '**Synthetic engineering evidence. No execution authority.**', '',
             f"Frozen plan: `{plan['plan_id']}`. Issued at elapsed hour {plan['cutoff_hour']}.",
             'Workload: aggregate inference and training on abstract homogeneous GPUs.', '',
             '| Scenario | State | Productive difference (GPU-h) | Demand error (GPU-h) | Cost difference (USD) |',
             '|---|---|---:|---:|---:|']
    for label, report in reports.items():
        s = report['summary']
        vals = [f'{s[k]:,.2f}' if s is not None else 'unknown' for k in ('productive_delta_gpu_h','demand_error_gpu_h','cost_delta_usd')]
        lines.append(f"| {label} | {report['status']} | {' | '.join(vals)} |")
    lines += ['', 'Differences compare each scenario with its own frozen plan. They are not production savings.',
              'The forecast-underestimate and higher-headroom cases use separate plans; see comparison.json for paired baseline replay differences.',
              'Lost training progress is charged when it is reversed, including progress earned before the planning window.',
              'SQL loss buckets reconcile exactly; forecast error is a separate diagnostic, not another additive loss.',
              'Costs use a declared synthetic allocated-GPU-hour tariff. No electricity, TCO or business-value claim is made.', '',
              '## Forecast backtest', '',
              'Rolling one-step errors on history; these do not validate the full frozen forecast horizon.', '']
    for method, result in plan['forecast']['backtest'].items():
        lines.append(f"- {method}: MAE {result['mae_gpu_h']:.3f} GPU-h over {result['observations']} origins.")
    lines += skill_markdown(skill)
    lines += ['', '## Unchecked domain constraints', '',
              'This replay does not establish topology, thermal, host/I/O, tenancy, live admission or real hardware feasibility.',
              'Existing capacity.placement previews remain the domain interfaces; aggregate hours do not supply a valid per-job admission envelope.',
              'No physical-loss factors are multiplied into this ledger, because their accounting boundaries overlap.', '']
    return '\n'.join(lines)


def number(value, digits=1, suffix=''):
    return 'null' if value is None else f'{value:,.{digits}f}{suffix}'


def skill_markdown(skill):
    lines = ['', '## Forecast error over frozen horizons', '',
             'Measurement only: forecasts, bands and reservations are unchanged. Historical backtests pool',
             'every lead available before the cutoff from origins inside history; held-out coverage uses the',
             'baseline replay after the cutoff. These are synthetic frequencies, not calibrated coverage.', '',
             '| Method | Origins | Leads (h) | Observations | Historical p90 error (GPU-h) | Held-out hours in band | Held-out coverage |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for method, b in skill['historical_backtest'].items():
        c = skill['held_out_coverage'][method]
        leads = 'none' if b['lead_range_h'] is None else f"{b['lead_range_h'][0]}-{b['lead_range_h'][1]}"
        inside = 'null' if c['hours_inside_band'] is None else f"{c['hours_inside_band']} of {c['expected_hours']}"
        lines.append(f"| {method} | {b['origins']} | {leads} | {b['observations']} | {number(b['p90_abs_error_gpu_h'])} | "
                     f"{inside} | {number(None if c['coverage'] is None else 100 * c['coverage'], 1, '%')} |")
    chosen = skill['chosen_method']
    lines += ['', f"Scope: {skill['historical_backtest'][chosen]['scope']}.",
              f"The frozen plan forecasts {skill['requested_horizon_h']} h ahead.",
              f"Warning: {skill['method_warning']}." if skill['method_warning'] else
              "No method warning. The heuristic warns when the chosen method's historical p90 error is at least twice another's; it is not a significance test."]
    return lines


def forecast_skill(history, plan, baseline, other_baselines):
    """Historical frozen-horizon error and baseline held-out band coverage for
    the plan's method and its comparator.

    The comparator has no replay of its own; its band is measured against the
    demand observed under this plan's baseline replay. That is reported only
    when the other plans' baseline replays observed exactly the same demand,
    and is null otherwise.
    """
    f = plan['forecast']
    cutoff, horizon = f['issued_at_hour'], len(plan['rows'])
    methods = [f['method']] + [m for m in ('seasonal', 'last_value') if m != f['method']]
    backtests = {m: horizon_backtest(history, cutoff, horizon, method=m, bias=f['bias']) for m in methods}
    demand = [r['inf_demand_gpu_h'] for r in baseline['rows']]
    same_demand = bool(other_baselines) and all(
        a['scenario'] == 'baseline' and [r['inf_demand_gpu_h'] for r in a['rows']] == demand for a in other_baselines)
    coverage = {f['method']: band_coverage(plan, baseline)}
    for m in methods[1:]:
        coverage[m] = band_coverage(plan, baseline, forecast(history, cutoff, cutoff + horizon, method=m, bias=f['bias']))
        if not same_demand:
            coverage[m].update(hours_inside_band=None, coverage=None,
                               scope='not computed: observed demand differed between plans')
    return {'schema': 'capacity-forecast-skill/v1', 'evidence_kind': 'synthetic', 'plan_id': plan['plan_id'],
            'chosen_method': f['method'], 'requested_horizon_h': horizon,
            'historical_backtest': backtests, 'held_out_coverage': coverage,
            'method_warning': method_warning(backtests, f['method']),
            'baseline_demand_identical_across_plans': same_demand, 'plans_compared': 1 + len(other_baselines),
            'interpretation': 'measurement only; no method selection, band change or calibrated coverage claim'}


def demo(destination, *, days=30, history_days=14, seed=42):
    if type(days) is not int or type(history_days) is not int or history_days < 3 or days < history_days + 3:
        raise ValueError('demo requires >=3 history days and >=3 future days for all what-if windows')
    config = {'gpus': 1024, 'horizon_days': days, 'seed': seed, 'inf_surges': True,
              'failures': True, 'power_envelope': True}
    started = time.perf_counter()
    # No held-out records are even generated for the forecasting step.
    history = observe({**config, 'horizon_days': history_days})
    plan = build_plan(config, history, history_days * 24)
    with publish_directory(destination) as stage:
        write_json(stage / 'history.json', history)
        write_json(stage / 'allocation-plan.json', plan)
        write_json(stage / 'forecast.json', plan['forecast'])
        reports, actuals = {}, {}
        with Ledger(stage / 'ledger.duckdb') as ledger:
            for scenario in SCENARIOS:
                actual = actual_artifact(plan, scenario)
                ledger.ingest(plan, actual)
                report = ledger.report(actual['actual_id'])
                reports[scenario], actuals[scenario] = report, actual
                write_json(stage / f'actual-{scenario}.json', actual)
                write_json(stage / f'variance-{scenario}.json', report)
            # Missing observations are an explicit non-result, not zero drift.
            incomplete = {k:v for k,v in actuals['baseline'].items() if k != 'actual_id'}
            incomplete['rows'] = incomplete['rows'][1:]
            incomplete = seal(incomplete, 'actual_id')
            ledger.ingest(plan, incomplete)
            reports['missing_event'] = ledger.report(incomplete['actual_id'])
            write_json(stage / 'actual-missing-event.json', incomplete)
            write_json(stage / 'variance-missing-event.json', reports['missing_event'])
            comparisons, alternatives = {}, []
            for name, parameters in [('forecast_underestimate', {'bias': .7}), ('higher_headroom', {'headroom': .3})]:
                alternative = build_plan(config, history, history_days * 24, **parameters)
                actual = actual_artifact(alternative)
                alternatives.append(actual)
                ledger.ingest(alternative, actual)
                reports[name] = ledger.report(actual['actual_id'])
                write_json(stage / f'plan-{name}.json', alternative)
                write_json(stage / f'actual-{name}.json', actual)
                write_json(stage / f'variance-{name}.json', reports[name])
                s, b = reports[name]['summary'], reports['baseline']['summary']
                comparisons[name] = {'baseline_plan_id': plan['plan_id'], 'candidate_plan_id': alternative['plan_id'],
                    'parameters_changed': parameters,
                    'actual_productive_delta_gpu_h': s['actual_productive_gpu_h'] - b['actual_productive_gpu_h'],
                    'actual_cost_delta_usd': s['actual_cost_usd'] - b['actual_cost_usd'],
                    'unmet_inference_delta_gpu_h': s['unmet_inference_gpu_h'] - b['unmet_inference_gpu_h'],
                    'evidence_kind': 'synthetic', 'interpretation': 'paired synthetic replay; tradeoffs, not a universal winner'}
            write_json(stage / 'comparison.json', comparisons)
            skill = forecast_skill(history, plan, actuals['baseline'], alternatives)
            write_json(stage / 'forecast-skill.json', skill)
        (stage / 'REPORT.md').write_text(markdown(reports, plan, skill))
        manifest = {'schema': 'capacity-bundle/v1', 'complete': True, 'evidence_kind': 'synthetic',
                    'execution_authority': False, 'plan_id': plan['plan_id'], 'provenance': provenance(),
                    'duckdb': duckdb.__version__, 'elapsed_seconds': time.perf_counter() - started,
                    'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(stage.iterdir()) if p.is_file()}}
        write_json(stage / 'manifest.json', manifest)
    return {'output': str(Path(destination).absolute()), 'plan_id': plan['plan_id'],
            'scenario_states': {k:v['status'] for k,v in reports.items()}}


def main(argv=None):
    p = argparse.ArgumentParser(description='Offline synthetic capacity planning; no cluster access')
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('demo')
    d.add_argument('--output', required=True, type=Path)
    d.add_argument('--days', type=int, default=30)
    d.add_argument('--history-days', type=int, default=14)
    d.add_argument('--seed', type=int, default=42)
    r = sub.add_parser('reconcile')
    r.add_argument('--plan', required=True, type=Path)
    r.add_argument('--actual', required=True, type=Path)
    r.add_argument('--ledger', required=True, type=Path)
    o = sub.add_parser('observe')
    o.add_argument('--config', required=True, type=Path)
    o.add_argument('--output', required=True, type=Path)
    o.add_argument('--policy', default='intent-closed-loop')
    b = sub.add_parser('plan')
    b.add_argument('--config', required=True, type=Path)
    b.add_argument('--history', required=True, type=Path)
    b.add_argument('--cutoff-hour', required=True, type=int)
    b.add_argument('--output', required=True, type=Path)
    b.add_argument('--method', choices=['seasonal','last_value'], default='seasonal')
    b.add_argument('--bias', type=float, default=1.)
    b.add_argument('--headroom', type=float, default=.1)
    b.add_argument('--rate', type=float, default=2.)
    b.add_argument('--policy', default='intent-closed-loop')
    s = sub.add_parser('replay')
    s.add_argument('--plan', required=True, type=Path)
    s.add_argument('--scenario', choices=SCENARIOS, default='baseline')
    s.add_argument('--output', required=True, type=Path)
    args = p.parse_args(argv)
    try:
        if args.command == 'demo':
            result = demo(args.output, days=args.days, history_days=args.history_days, seed=args.seed)
        elif args.command == 'observe':
            records = observe(read_json(args.config), policy=args.policy)
            with publish_directory(args.output) as stage:
                write_json(stage / 'history.json', records)
            result = {'output': str(args.output), 'evidence_kind': 'synthetic', 'hours': len(records)}
        elif args.command == 'plan':
            plan = build_plan(read_json(args.config), read_json(args.history), args.cutoff_hour,
                              method=args.method, bias=args.bias, headroom=args.headroom,
                              rate=args.rate, policy=args.policy)
            with publish_directory(args.output) as stage:
                write_json(stage / 'allocation-plan.json', plan)
                write_json(stage / 'forecast.json', plan['forecast'])
            result = {'output': str(args.output), 'plan_id': plan['plan_id']}
        elif args.command == 'replay':
            actual = actual_artifact(read_json(args.plan), args.scenario)
            with publish_directory(args.output) as stage:
                write_json(stage / 'actual.json', actual)
            result = {'output': str(args.output), 'actual_id': actual['actual_id']}
        else:
            plan, actual = read_json(args.plan), read_json(args.actual)
            with Ledger(args.ledger) as ledger:
                ledger.ingest(plan, actual)
                result = ledger.report(actual['actual_id'])
        print(json.dumps(result, indent=2, allow_nan=False))
        return 3 if result.get('status') == 'incomplete' else 0
    except (ValueError, KeyError, TypeError, OSError, duckdb.Error) as exc:
        print(json.dumps({'status': 'invalid', 'error': str(exc), 'execution_authority': False}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
