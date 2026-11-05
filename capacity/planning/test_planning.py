"""Contract, independent arithmetic, perturbation and failure-path acceptance."""
import copy
from dataclasses import asdict
import json
import math
from pathlib import Path
import random

import numpy as np
import pytest

from capacity.report import digest
from sim.simulator import Config, Simulation, STEPS_PER_HOUR
from capacity.planning.model import (observe, build_plan, actual_artifact, validate_plan,
                                     validate_actual, forecast, seal, ACCOUNT,
                                     _shares_one_band, horizon_backtest, band_coverage, method_warning)
from capacity.planning.ledger import Ledger
from capacity.planning.__main__ import publish_directory, read_json, main, forecast_skill


@pytest.fixture(scope='module')
def bundle():
    cfg = {'gpus': 128, 'horizon_days': 6, 'inf_base': 32., 'inf_diurnal_amp': 8.,
           'failures': True, 'power_envelope': True, 'seed': 9}
    history = observe({**cfg, 'horizon_days': 3})
    plan = build_plan(cfg, history, 72)
    return history, plan, actual_artifact(plan)


def reseal(data, key):
    return seal({k:v for k,v in data.items() if k != key}, key)


def test_observer_is_inert_and_hourly_totals_conserve():
    cfg = Config(horizon_days=2, failures=True, power_envelope=True, inf_surges=True)
    a, b = Simulation(cfg, 'intent-closed-loop'), Simulation(cfg, 'intent-closed-loop')
    snapshots = []
    assert a.run() == b.run(observer=snapshots.append)
    assert asdict(a.metrics) == asdict(b.metrics)
    rows = observe(asdict(cfg))
    for k in ACCOUNT:
        assert sum(r[k] for r in rows) == pytest.approx(getattr(a.metrics, k))


@pytest.mark.parametrize('hook,value', [('reservations', True), ('reservations', 2.5),
    ('demand_factors', float('nan')), ('capacity_factors', 1.01), ('capacity_factors', -1)])
def test_hooks_refuse_invalid_before_execution(hook, value):
    sim = Simulation(Config(horizon_days=1), 'intent-closed-loop')
    with pytest.raises(ValueError):
        sim.run(**{hook:[value]*sim.cfg.steps})
    assert sim.metrics.total_steps == 0


def test_forecast_does_not_accept_future_or_missing_history(bundle):
    history, plan, _ = bundle
    for bad in (history[:-1], history + [history[-1]], list(reversed(history))):
        with pytest.raises(ValueError):
            build_plan(plan['config'], bad, 72)
    f = forecast(history, 72, 100)
    assert f['history_id'] == digest(history)
    assert max(r['hour'] for r in history) < f['issued_at_hour']


def test_forecast_known_seasonality_beats_last_value():
    history = [{'hour':h, 'inf_demand_gpu_h': float(h % 24)} for h in range(120)]
    f = forecast(history, 120, 168)
    assert [r['demand_gpu_h'] for r in f['rows']] == [float(h % 24) for h in range(120,168)]
    assert f['backtest']['seasonal']['mae_gpu_h'] == 0
    assert f['backtest']['last_value']['mae_gpu_h'] > 0


def test_full_replay_prefix_matches_history(bundle):
    history, plan, _ = bundle
    assert observe(plan['config'])[:72] == history
    for scenario in ('baseline','combined'):
        assert observe(plan['config'],plan=plan,scenario=scenario)[:72] == history


def test_plan_reproducible_and_not_mutated_by_what_if(bundle):
    history, plan, _ = bundle
    before = copy.deepcopy(plan)
    assert build_plan(plan['config'],history,72) == plan
    actual_artifact(plan,'combined')
    assert plan == before


def test_reservation_plan_controls_actual_allocations(bundle):
    _, plan, actual = bundle
    for p,a in zip(plan['rows'],actual['rows']):
        assert a['inf_alloc_gpu_h'] <= p['reservation_gpus'] + 1e-6
    alternative = build_plan(plan['config'],bundle[0],72,bias=.5)
    altered = actual_artifact(alternative)
    assert sum(r['inf_alloc_gpu_h'] for r in altered['rows']) < sum(r['inf_alloc_gpu_h'] for r in actual['rows'])


@pytest.mark.parametrize('mutation', ['hash','duplicate','unknown','unit','nan','negative','overallocate','bool'])
def test_rehashed_bad_actuals_still_refused(bundle, mutation):
    _,plan,original = bundle
    a=copy.deepcopy(original)
    if mutation=='hash': a['rows'][0]['inf_demand_gpu_h'] += 1
    elif mutation=='duplicate': a['rows'].insert(0,copy.deepcopy(a['rows'][0]))
    elif mutation=='unknown': a['surprise']=1
    elif mutation=='unit': a['unit']='TPU-hour'
    elif mutation=='nan': a['rows'][0]['inf_demand_gpu_h']=float('nan')
    elif mutation=='negative': a['rows'][0]['train_productive_gpu_h']=-10000
    elif mutation=='overallocate': a['rows'][0]['train_alloc_gpu_h']=100000
    elif mutation=='bool': a['rows'][0]['hour']=True
    if mutation not in ('hash','nan'): a=reseal(a,'actual_id')
    with pytest.raises(ValueError):validate_actual(plan,a)


def test_plan_digest_and_rehashed_temporal_mismatch(bundle):
    p=copy.deepcopy(bundle[1]);p['cutoff_hour']+=1
    with pytest.raises(ValueError):validate_plan(p)
    with pytest.raises(ValueError):validate_plan(reseal(p,'plan_id'))


def test_sql_independent_arithmetic_and_no_change(bundle):
    # Construct hand-worked homogeneous plan: nominal 128, envelope 100,
    # allocated 20 inference + 60 training, productive 15 + 50 = 65.
    # The plan stays derivable: an all-day cap of 0.78125 x 128 gives envelope
    # 100; ceil(15 x 1.3) = 20; 80 x 0.75 = 60; 60 x (50/60) = 50.
    p=copy.deepcopy(bundle[1])
    p['config'].update(power_envelope=True,power_start_hour=0,power_hours=24,power_frac=.78125)
    p.update(headroom=.3,training_fill_ratio=.75,training_retention_ratio=50/60)
    for r,f in zip(p['rows'],p['forecast']['rows']):
        f.update(demand_gpu_h=15.,lower_gpu_h=15.,upper_gpu_h=15.)
        r.update(envelope_gpu_h=100.,inf_alloc_gpu_h=20.,inf_demand_gpu_h=15.,
                 inf_productive_gpu_h=15.,train_alloc_gpu_h=60.,train_productive_gpu_h=50.,
                 reservation_gpus=20,training_budget_gpu_h=80.,rate_usd_per_allocated_gpu_h=2.)
    p=reseal(p,'plan_id')
    a=copy.deepcopy(bundle[2]);a['plan_id']=p['plan_id']
    a['rows']=[{k:r[k] for k in ('hour',*ACCOUNT,'rate_usd_per_allocated_gpu_h')} for r in p['rows']]
    a=reseal(a,'actual_id')
    with Ledger() as ledger:
        ledger.ingest(p,a)
        assert ledger.report(a['actual_id'])['status']=='no_change'
        # Actual envelope 80, allocations 25 + 45, productivity 20 + 30.
        # Net -15 = availability -20 + idle +10 + reservation 0 + training -5.
        for r in a['rows']:
            r.update(envelope_gpu_h=80.,inf_alloc_gpu_h=25.,inf_demand_gpu_h=20.,
                     inf_productive_gpu_h=20.,train_alloc_gpu_h=45.,train_productive_gpu_h=30.,
                     rate_usd_per_allocated_gpu_h=3.)
        a=reseal(a,'actual_id');ledger.ingest(p,a)
        report=ledger.report(a['actual_id']);r=report['hourly'][0]
        assert r['productive_delta_gpu_h']==-15
        assert r['availability_effect_gpu_h']==-20
        assert r['idle_effect_gpu_h']==10
        assert r['reservation_effect_gpu_h']==0
        assert r['training_loss_effect_gpu_h']==-5
        assert r['demand_error_gpu_h']==5
        assert r['cost_delta_usd']==50 # 70*3 - 80*2
        assert r['allocation_cost_effect_usd']==-20
        assert r['rate_cost_effect_usd']==70
        assert abs(report['summary']['productive_reconciliation_residual_gpu_h'])<1e-7


def test_missing_late_idempotent_and_failed_ingestion(bundle):
    _,p,a=bundle
    partial=copy.deepcopy(a);partial['rows']=partial['rows'][1:];partial=reseal(partial,'actual_id')
    with Ledger() as ledger:
        ledger.ingest(p,partial)
        r=ledger.report(partial['actual_id'])
        assert r['status']=='incomplete' and r['summary'] is None and r['missing_hours']==[72]
        ledger.ingest(p,a);ledger.ingest(p,a)
        assert ledger.db.execute('select count(*) from plans').fetchone()[0]==len(p['rows'])
        assert ledger.db.execute('select count(*) from actuals where actual_id=?',[a['actual_id']]).fetchone()[0]==len(a['rows'])
        assert ledger.report(partial['actual_id'])['status']=='incomplete'
        assert ledger.report(a['actual_id'])['status']=='changed'
        bad=copy.deepcopy(a);bad['rows'][0]['inf_alloc_gpu_h']=1e9;bad=reseal(bad,'actual_id')
        with pytest.raises(ValueError):ledger.ingest(p,bad)
        assert ledger.db.execute('select count(*) from artifacts').fetchone()[0]==3


def test_transaction_rolls_back_mid_ingestion(bundle, monkeypatch):
    _,p,a=bundle
    with Ledger() as ledger:
        original=ledger._insert
        def fail(artifact,kind):
            original(artifact,kind)
            if kind=='actual':raise RuntimeError('injected failure after insert')
        monkeypatch.setattr(ledger,'_insert',fail)
        with pytest.raises(RuntimeError):ledger.ingest(p,a)
        assert ledger.db.execute('select count(*) from artifacts').fetchone()[0]==0
        assert ledger.db.execute('select count(*) from plans').fetchone()[0]==0
        assert ledger.db.execute('select count(*) from actuals').fetchone()[0]==0


def test_price_only_changes_cost_and_outage_reversals_reconcile(bundle):
    _,p,a=bundle
    price=actual_artifact(p,'price_spike')
    for x,y in zip(a['rows'],price['rows']):
        assert {k:x[k] for k in ACCOUNT}=={k:y[k] for k in ACCOUNT}
    outage=actual_artifact(p,'capacity_outage')
    assert all(abs(r['envelope_gpu_h'])<1e-6 for r in outage['rows'] if 108<=r['hour']<114)
    with Ledger() as ledger:
        for candidate in (a,price,outage):ledger.ingest(p,candidate)
        assert ledger.report(price['actual_id'])['summary']['actual_cost_usd']>ledger.report(a['actual_id'])['summary']['actual_cost_usd']
        assert abs(ledger.report(outage['actual_id'])['summary']['productive_reconciliation_residual_gpu_h'])<1e-5


def test_negative_productivity_is_preserved(bundle):
    _,p,a=bundle;a=copy.deepcopy(a)
    a['rows'][0]['train_productive_gpu_h']=-10
    a['rows'][0]['work_lost_gpu_h']=12
    a['rows'][0]['train_alloc_gpu_h']=max(2.,a['rows'][0]['train_alloc_gpu_h'])
    a=reseal(a,'actual_id')
    with Ledger() as ledger:
        ledger.ingest(p,a)
        assert ledger.report(a['actual_id'])['hourly'][0]['work_reversed_gpu_h']==12


def test_output_failure_and_overwrite_protection(tmp_path):
    out=tmp_path/'result'
    with pytest.raises(RuntimeError):
        with publish_directory(out) as stage:
            (stage/'partial').write_text('not complete')
            raise RuntimeError('interrupted')
    assert not out.exists() and not list(tmp_path.iterdir())
    with publish_directory(out) as stage:(stage/'ready').write_text('complete')
    with pytest.raises(ValueError):
        with publish_directory(out):pass
    assert (out/'ready').read_text()=='complete'
    lock=tmp_path/'busy.lock';lock.write_text('')
    with pytest.raises(FileExistsError):
        with publish_directory(tmp_path/'busy'):pass
    assert lock.exists()


def test_cli_invalid_and_duplicate_json(tmp_path,capsys):
    p=tmp_path/'bad.json';p.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError):read_json(p)
    assert main(['demo','--days','3','--history-days','3','--output',str(tmp_path/'out')])==2
    assert json.loads(capsys.readouterr().err)['status']=='invalid'


def test_sql_materialization_corruption_is_refused(bundle):
    _,p,a=bundle
    with Ledger() as ledger:
        ledger.ingest(p,a)
        ledger.db.execute('UPDATE actuals SET rate_usd_per_allocated_gpu_h=99 WHERE hour=72')
        with pytest.raises(ValueError, match='ledger rows differ'):
            ledger.report(a['actual_id'])


def test_empty_observations_never_become_zero_variance(bundle):
    _,p,a=bundle;a=copy.deepcopy(a);a['rows']=[];a=reseal(a,'actual_id')
    with Ledger() as ledger:
        ledger.ingest(p,a);r=ledger.report(a['actual_id'])
        assert r['status']=='incomplete' and r['summary'] is None
        assert all(row['unmet_inference_gpu_h'] is None for row in r['hourly'])


def test_no_change_detects_cancelling_hourly_differences(bundle):
    _,p,a=bundle
    a=copy.deepcopy(a)
    a['rows']=[{k:r[k] for k in ('hour',*ACCOUNT,'rate_usd_per_allocated_gpu_h')} for r in p['rows']]
    a['rows'][0]['rate_usd_per_allocated_gpu_h']+=1
    # Same total cost; hourly rate changes must still be visible.
    w0=a['rows'][0]['inf_alloc_gpu_h']+a['rows'][0]['train_alloc_gpu_h']
    w1=a['rows'][1]['inf_alloc_gpu_h']+a['rows'][1]['train_alloc_gpu_h']
    a['rows'][1]['rate_usd_per_allocated_gpu_h']-=w0/w1
    a=reseal(a,'actual_id')
    with Ledger() as ledger:
        ledger.ingest(p,a);r=ledger.report(a['actual_id'])
        assert r['status']=='changed'
        assert abs(r['summary']['cost_delta_usd'])<1e-8


def test_demo_cli_and_artifact_hashes(tmp_path):
    from capacity.planning.__main__ import demo
    import hashlib
    output=tmp_path/'demo'
    result=demo(output, days=6, history_days=3, seed=2)
    assert result['scenario_states']['missing_event']=='incomplete'
    manifest=read_json(output/'manifest.json')
    assert manifest['complete'] and not manifest['execution_authority']
    for name,sha in manifest['files'].items():
        assert hashlib.sha256((output/name).read_bytes()).hexdigest()==sha
    plan=read_json(output/'allocation-plan.json')
    actual=read_json(output/'actual-baseline.json')
    with Ledger(tmp_path/'fresh.duckdb') as ledger:
        ledger.ingest(plan,actual)
        assert ledger.report(actual['actual_id'])==read_json(output/'variance-baseline.json')
    assert main(['reconcile','--plan',str(output/'allocation-plan.json'),
                 '--actual',str(output/'actual-missing-event.json'),'--ledger',str(tmp_path/'fresh.duckdb')])==3


@pytest.mark.parametrize('seed', [0,1,42])
@pytest.mark.parametrize('policy', ['rigid-fifo','tiered-preemption','intent-closed-loop'])
def test_policy_seed_matrix_and_combined_fault_accounting(seed,policy):
    cfg={'horizon_days':6,'seed':seed,'failures':True,'inf_surges':True,'power_envelope':True}
    history=observe({**cfg,'horizon_days':3},policy=policy)
    plan=build_plan(cfg,history,72,policy=policy)
    actual=actual_artifact(plan,'combined')
    with Ledger() as ledger:
        ledger.ingest(plan,actual);report=ledger.report(actual['actual_id'])
        assert report['status']=='changed'
        assert abs(report['summary']['productive_reconciliation_residual_gpu_h'])<1e-5
        assert abs(report['summary']['cost_reconciliation_residual_usd'])<1e-5
    assert sum(r['envelope_gpu_h'] for r in actual['rows']) < sum(r['envelope_gpu_h'] for r in plan['rows'])


def test_cli_separate_stages(tmp_path):
    from capacity.planning.__main__ import write_json
    cfg={'gpus':128,'horizon_days':3,'inf_base':32.,'inf_diurnal_amp':8.}
    write_json(tmp_path/'history-config.json',cfg)
    assert main(['observe','--config',str(tmp_path/'history-config.json'),'--output',str(tmp_path/'history')])==0
    write_json(tmp_path/'config.json',{**cfg,'horizon_days':6})
    assert main(['plan','--config',str(tmp_path/'config.json'),'--history',str(tmp_path/'history/history.json'),
                 '--cutoff-hour','72','--output',str(tmp_path/'plan')])==0
    assert main(['replay','--plan',str(tmp_path/'plan/allocation-plan.json'),
                 '--scenario','combined','--output',str(tmp_path/'actual')])==0
    assert main(['reconcile','--plan',str(tmp_path/'plan/allocation-plan.json'),
                 '--actual',str(tmp_path/'actual/actual.json'),'--ledger',str(tmp_path/'ledger.duckdb')])==0


def test_complete_horizon_outage_has_undefined_realization_not_divide_by_zero():
    cfg=Config(horizon_days=1)
    sim=Simulation(cfg,'intent-closed-loop')
    result=sim.run(capacity_factors=[0.]*cfg.steps)
    assert result['envelope_gpu_h']==0
    assert result['productive_gpu_h']==0
    assert result['capacity_realization'] is None


def test_replay_reproducibility_and_source_mismatch(bundle):
    _,p,a=bundle
    assert actual_artifact(p)==a
    p=copy.deepcopy(p);p['provenance']['python']='0.0';p=reseal(p,'plan_id')
    with pytest.raises(ValueError,match='matching source and runtime'):
        actual_artifact(p)


def test_history_cannot_mix_nominal_fleets(bundle):
    history,p,_=bundle
    history=copy.deepcopy(history);history[0]['nominal_gpu_h']*=2
    with pytest.raises(ValueError,match='history schema or nominal'):
        build_plan(p['config'],history,72)


def test_original_published_36_run_grid_is_unchanged():
    import csv
    from pathlib import Path
    scenarios={'S1-steady':{},'S2-power':{'power_envelope':True},
               'S3-failures':{'failures':True},
               'S4-full':{'power_envelope':True,'failures':True,'inf_surges':True}}
    path=Path(__file__).resolve().parents[2]/'results/results.csv'
    with path.open() as stream:
        rows=list(csv.DictReader(stream))
    assert len(rows)==36
    for row in rows:
        result=Simulation(Config(horizon_days=30,seed=int(row['seed']),**scenarios[row['scenario']]),row['policy']).run()
        for key,value in result.items():
            expected=row[key] if isinstance(value,str) else float(row[key])
            assert value==expected,(row['scenario'],row['seed'],row['policy'],key)


# Plan derivation (task103). plan_id identifies bytes; it does not
# authenticate them, so every edit below is resealed before validation.
def _shift_band(p, hour_index, delta):
    f = p['forecast']['rows'][hour_index]
    f['upper_gpu_h'] += delta


def _reserve(p, i, delta):
    r = p['rows'][i]
    r['reservation_gpus'] += delta; r['inf_alloc_gpu_h'] += delta
    r['training_budget_gpu_h'] -= delta
    r['inf_productive_gpu_h'] = min(r['inf_demand_gpu_h'], r['reservation_gpus'])


DERIVATION_EDITS = {
    'headroom': lambda p: p.update(headroom=.9),
    'fill_ratio': lambda p: p.update(training_fill_ratio=p['training_fill_ratio'] / 2),
    'retention_ratio': lambda p: p.update(training_retention_ratio=p['training_retention_ratio'] / 2),
    'reservation_one_gpu': lambda p: _reserve(p, 5, -1),
    'train_alloc': lambda p: p['rows'][7].update(train_alloc_gpu_h=p['rows'][7]['train_alloc_gpu_h'] * .9),
    'train_productive': lambda p: p['rows'][7].update(train_productive_gpu_h=p['rows'][7]['train_productive_gpu_h'] * .5),
    'train_productive_tiny': lambda p: p['rows'][7].update(train_productive_gpu_h=p['rows'][7]['train_productive_gpu_h'] - 1e-9),
    'budget_and_envelope': lambda p: p['rows'][3].update(envelope_gpu_h=p['rows'][3]['envelope_gpu_h'] + 1,
                                                         training_budget_gpu_h=p['rows'][3]['training_budget_gpu_h'] + 1),
    'reservation_float': lambda p: p['rows'][2].update(reservation_gpus=float(p['rows'][2]['reservation_gpus'])),
    'rate_one_row': lambda p: p['rows'][4].update(rate_usd_per_allocated_gpu_h=3.),
    'rate_above_builder_ceiling': lambda p: [r.update(rate_usd_per_allocated_gpu_h=1e300) for r in p['rows']],
    'band_one_row': lambda p: _shift_band(p, 6, 1.),
    'band_every_upper': lambda p: [f.update(upper_gpu_h=f['upper_gpu_h'] + 1e6) for f in p['forecast']['rows']],
}


@pytest.mark.parametrize('edit', sorted(DERIVATION_EDITS))
def test_resealed_underivable_plan_is_refused_then_rebuild_recovers(bundle, edit):
    history, plan, _ = bundle
    p = copy.deepcopy(plan); DERIVATION_EDITS[edit](p); p = reseal(p, 'plan_id')
    with pytest.raises(ValueError):
        validate_plan(p)
    # Recovery: the builder's own output for the same inputs validates.
    rebuilt = build_plan(plan['config'], history, plan['cutoff_hour'])
    validate_plan(rebuilt); validate_plan(rebuilt, history=history)
    assert rebuilt == plan


def test_generated_plans_validate_exactly_across_methods_and_settings(bundle):
    history, plan, _ = bundle
    for method in ('seasonal', 'last_value'):
        for bias, headroom in ((0., 0.), (.7, .1), (1., .3), (3, 1)):
            p = json.loads(json.dumps(build_plan(plan['config'], history, 72, method=method,
                                                 bias=bias, headroom=headroom)))
            validate_plan(p); validate_plan(p, history=history)


def test_supplied_history_rederivation_and_its_limits(bundle):
    history, plan, _ = bundle
    validate_plan(plan, history=history)
    # A replaced history_id is invisible without history, refused with it.
    p = copy.deepcopy(plan); p['forecast']['history_id'] = '0' * 64; p = reseal(p, 'plan_id')
    validate_plan(p)
    with pytest.raises(ValueError, match='re-derive'):
        validate_plan(p, history=history)
    # Ratios rebuilt consistently into every row still differ from history.
    p = build_plan(plan['config'], history, 72); p = copy.deepcopy(p)
    p['training_fill_ratio'] = p['training_fill_ratio'] / 2
    for r in p['rows']:
        r['train_alloc_gpu_h'] = r['training_budget_gpu_h'] * p['training_fill_ratio']
        r['train_productive_gpu_h'] = r['train_alloc_gpu_h'] * p['training_retention_ratio']
    p = reseal(p, 'plan_id')
    validate_plan(p)
    with pytest.raises(ValueError, match='ratios'):
        validate_plan(p, history=history)


def test_self_consistent_forged_history_is_not_authenticated(bundle):
    """Negative control: consistency is not authenticity. A plan built from an
    edited history validates against that edited history; only an anchor the
    reader already trusts (here, the original plan_id) tells them apart."""
    history, plan, _ = bundle
    forged = copy.deepcopy(history)
    for row in forged[48:]:
        row['inf_demand_gpu_h'] = min(row['inf_demand_gpu_h'] * 1.5, row['inf_alloc_gpu_h'])
        row['inf_productive_gpu_h'] = min(row['inf_productive_gpu_h'], row['inf_demand_gpu_h'])
    other = build_plan(plan['config'], forged, 72)
    validate_plan(other, history=forged)
    assert other['forecast'] != plan['forecast']
    assert other['plan_id'] != plan['plan_id']
    with pytest.raises(ValueError):
        validate_plan(other, history=history)


def _band_rows(demands, band):
    """Rows exactly as forecast() builds them from point estimates and a band."""
    return [{'hour': h, 'demand_gpu_h': d, 'lower_gpu_h': max(0, d - band), 'upper_gpu_h': d + band}
            for h, d in enumerate(demands)]


def _roundtrip(rows):
    return json.loads(json.dumps(rows))


BAND_DEMANDS = ([0.0, 5e-324, 1e-9, 0.1, 1.0, 3.0, 1e3, 2.0 ** 53 - 1, 1e9, 1e12, 1e15]
                + [math.nextafter(2.0 ** k, 0) for k in range(-20, 50, 7)]
                + [2.0 ** k for k in range(-20, 50, 7)])
BAND_VALUES = [0.0, 5e-324, 1e-15, 1e-9, 0.1, 1.0, 14.000000000003055, 1e3, 1e9, 1e13]


@pytest.mark.parametrize('band', BAND_VALUES)
def test_band_check_accepts_adversarial_valid_forecasts(band):
    """Mixed scales in one forecast, large demand with a tiny band, zero band,
    binade edges and zero-clipped lower bounds all come from one band; the
    check must accept them as floats, NumPy scalars and after a JSON round trip."""
    rows = _band_rows(BAND_DEMANDS, band)
    assert _shares_one_band(rows) and _shares_one_band(_roundtrip(rows))
    assert _shares_one_band(_band_rows([np.float64(d) for d in BAND_DEMANDS], np.float64(band)))


def test_band_check_accepts_random_valid_forecasts():
    rng = random.Random(103)
    for _ in range(3000):
        band = 0.0 if rng.random() < .1 else 10 ** rng.uniform(-15, 13)
        demands = [0.0 if rng.random() < .05 else 10 ** rng.uniform(-9, 15) * rng.choice([1, 1 / 3, math.pi])
                   for _ in range(rng.choice([1, 24, 384]))]
        rows = _band_rows(demands, band)
        assert _shares_one_band(_roundtrip(rows)), (band, demands)


BAND_FORGERIES = {
    'upper_one_row': lambda r: r[5].update(upper_gpu_h=r[5]['upper_gpu_h'] + 1e-9),
    'upper_16_ulps': lambda r: r[5].update(upper_gpu_h=r[5]['upper_gpu_h'] + 16 * math.ulp(r[5]['upper_gpu_h'])),
    'lower_one_row': lambda r: r[5].update(lower_gpu_h=r[5]['lower_gpu_h'] + 1e-9),
    'band_per_row': lambda r: [x.update(upper_gpu_h=x['upper_gpu_h'] + 1e-9 * i) for i, x in enumerate(r)],
    'clipped_when_not': lambda r: r[5].update(lower_gpu_h=0),
    'unclipped_when_clipped': lambda r: r[0].update(lower_gpu_h=1e-9),
}


@pytest.mark.parametrize('name', BAND_FORGERIES)
def test_band_check_refuses_small_inconsistencies(name):
    rows = _band_rows([3.0] + [1000.0 + 7.3 * i for i in range(1, 24)], 14.000000000003055)
    assert _shares_one_band(rows)
    BAND_FORGERIES[name](rows)
    assert not _shares_one_band(_roundtrip(rows))


def _step_history(hours, tail=()):
    """10 GPU-h for the first half of every day and 20 after: the seasonal mean
    of identical days is exact, and last_value at a midnight origin repeats 20."""
    return ([{'hour': h, 'inf_demand_gpu_h': 10.0 if h % 24 < 12 else 20.0} for h in range(hours)]
            + [{'hour': hours + i, 'inf_demand_gpu_h': v} for i, v in enumerate(tail)])


def test_horizon_backtest_matches_hand_oracle():
    # Origins 72 and 96, 24 leads each before cutoff 120: 48 observations.
    # last_value errs by 10 on the 24 morning hours and 0 otherwise.
    hist = _step_history(120)
    lv = horizon_backtest(hist, 120, 24, method='last_value', first_origin=72)
    assert (lv['origins'], lv['first_origin_hour'], lv['last_origin_hour'], lv['lead_range_h'], lv['observations']) == (2, 72, 96, [1, 24], 48)
    assert (lv['mae_gpu_h'], lv['p50_abs_error_gpu_h'], lv['p90_abs_error_gpu_h']) == (5.0, 5.0, 10.0)
    assert lv['scope'].startswith('pooled historical horizons')
    se = horizon_backtest(hist, 120, 24, method='seasonal', first_origin=72)
    assert (se['observations'], se['mae_gpu_h'], se['p90_abs_error_gpu_h']) == (48, 0.0, 0.0)
    # Zero-error comparison: the heuristic never divides and never warns on zero.
    assert method_warning({'seasonal': se, 'last_value': lv}, 'seasonal') is None
    assert '10.0' in method_warning({'seasonal': se, 'last_value': lv}, 'last_value')
    assert method_warning({'seasonal': se, 'last_value': se}, 'last_value') is None
    assert method_warning({'seasonal': se, 'last_value': {'p90_abs_error_gpu_h': None}}, 'seasonal') is None


def test_horizon_backtest_discloses_truncated_horizons_and_insufficient_history():
    hist = _step_history(120)
    full = horizon_backtest(hist, 120, 48, method='last_value', first_origin=72)
    assert (full['lead_range_h'], full['observations']) == ([1, 48], 72)  # leads 48 + 24
    assert full['scope'].startswith('pooled historical horizons')
    short = horizon_backtest(hist, 120, 384, method='last_value', first_origin=72)
    assert (short['requested_horizon_h'], short['lead_range_h'], short['observations']) == (384, [1, 48], 72)
    assert 'truncated' in short['scope'] and 'not validation of the requested 384 h' in short['scope']
    empty = horizon_backtest(hist, 120, 24, method='seasonal')  # first origin 168 >= cutoff
    assert (empty['origins'], empty['observations'], empty['lead_range_h']) == (0, 0, None)
    assert empty['mae_gpu_h'] is empty['p50_abs_error_gpu_h'] is empty['p90_abs_error_gpu_h'] is None
    assert empty['scope'].startswith('insufficient history')


def test_horizon_backtest_ignores_everything_at_or_after_cutoff():
    base = horizon_backtest(_step_history(120), 120, 384, method='seasonal', first_origin=72)
    for tail in ([1e9] * 50, [float('nan'), -5.0, 'not a number']):
        assert horizon_backtest(_step_history(120, tail), 120, 384, method='seasonal', first_origin=72) == base
    earlier = _step_history(120); earlier[100]['inf_demand_gpu_h'] = 99.0
    assert horizon_backtest(earlier, 120, 384, method='seasonal', first_origin=72) != base


@pytest.mark.parametrize('kwargs', [
    {'method': 'arima'}, {'horizon': 0}, {'horizon': 1.5}, {'horizon': True}, {'cutoff': 71},
    {'bias': float('nan')}, {'bias': True}, {'bias': 3.5}, {'first_origin': 71}, {'origin_step': 0},
    {'history': _step_history(119)}, {'history': _step_history(120)[1:]},
    {'history': _step_history(120)[:60] + _step_history(120)[61:62] + _step_history(120)[60:61] + _step_history(120)[62:]},
    {'history': [dict(r, inf_demand_gpu_h=float('inf')) if r['hour'] == 5 else r for r in _step_history(120)]},
])
def test_horizon_backtest_refuses_invalid_domains(kwargs):
    args = {'history': _step_history(120), 'cutoff': 120, 'horizon': 24, 'method': 'seasonal', 'first_origin': 72, **kwargs}
    with pytest.raises(ValueError):
        horizon_backtest(args.pop('history'), args.pop('cutoff'), args.pop('horizon'), **args)


def test_band_coverage_counts_validates_and_nulls_incomplete(bundle):
    history, plan, actual = bundle
    band = {r['hour']: r for r in plan['forecast']['rows']}
    inside = sum(band[r['hour']]['lower_gpu_h'] <= r['inf_demand_gpu_h'] <= band[r['hour']]['upper_gpu_h']
                 for r in actual['rows'])
    c = band_coverage(plan, actual)
    assert (c['expected_hours'], c['observed_hours'], c['hours_inside_band']) == (72, 72, inside)
    assert c['coverage'] == inside / 72 and c['method'] == 'seasonal'
    other = forecast(history, 72, 144, method='last_value')
    assert band_coverage(plan, actual, other)['method'] == 'last_value'
    incomplete = {k: v for k, v in actual.items() if k != 'actual_id'}
    incomplete['rows'] = actual['rows'][1:]
    c = band_coverage(plan, seal(incomplete, 'actual_id'))
    assert (c['observed_hours'], c['hours_inside_band'], c['coverage']) == (71, None, None)
    assert c['scope'].startswith('incomplete')


def _resealed(actual, **changes):
    a = {k: v for k, v in actual.items() if k != 'actual_id'}
    a.update(changes)
    return seal(a, 'actual_id')


def test_band_coverage_refuses_duplicate_unexpected_and_mismatched_inputs(bundle):
    history, plan, actual = bundle
    rows = actual['rows']
    for bad in (_resealed(actual, rows=rows[:1] + rows),
                _resealed(actual, rows=rows[:-1] + [dict(rows[-1], hour=rows[-1]['hour'] + 1)]),
                _resealed(actual, plan_id='0' * 64),
                dict(actual, rows=rows[1:])):  # not resealed
        with pytest.raises(ValueError):
            band_coverage(plan, bad)
    other = forecast(history, 72, 144, method='last_value')
    shifted = forecast(history[:71] + [dict(history[71], inf_demand_gpu_h=history[71]['inf_demand_gpu_h'] + 1)], 72, 144)
    for bad in (shifted, dict(other, rows=other['rows'][:-1]), dict(other, issued_at_hour=71),
                dict(other, rows=[dict(other['rows'][0], lower_gpu_h=other['rows'][0]['upper_gpu_h'] + 1)] + other['rows'][1:])):
        with pytest.raises(ValueError):
            band_coverage(plan, actual, bad)


def test_forecast_skill_reports_comparator_only_with_identical_demand(bundle):
    history, plan, actual = bundle
    twin = actual_artifact(build_plan(plan['config'], history, 72, headroom=.3))
    skill = forecast_skill(history, plan, actual, [twin])
    assert skill['baseline_demand_identical_across_plans'] and skill['plans_compared'] == 2
    assert skill['held_out_coverage']['last_value']['coverage'] is not None
    assert skill['historical_backtest']['seasonal']['observations'] == 0  # 72 h of history: no origin
    for others in ([], [actual_artifact(plan, 'demand_surge')]):
        skill = forecast_skill(history, plan, actual, others)
        assert not skill['baseline_demand_identical_across_plans']
        assert skill['held_out_coverage']['last_value']['coverage'] is None
        assert skill['held_out_coverage']['seasonal']['coverage'] is not None


def test_demo_skill_failure_publishes_nothing_and_rerun_is_identical(tmp_path, monkeypatch):
    import capacity.planning.__main__ as cli
    def broken(*args, **kwargs):
        raise RuntimeError('injected backtest failure')
    monkeypatch.setattr(cli, 'horizon_backtest', broken)
    with pytest.raises(RuntimeError):
        cli.demo(tmp_path / 'failed', days=6, history_days=3, seed=2)
    assert sorted(p.name for p in tmp_path.iterdir()) == []
    monkeypatch.undo()
    first = cli.demo(tmp_path / 'one', days=6, history_days=3, seed=2)
    second = cli.demo(tmp_path / 'two', days=6, history_days=3, seed=2)
    assert first['plan_id'] == second['plan_id']
    assert (tmp_path / 'one/forecast-skill.json').read_bytes() == (tmp_path / 'two/forecast-skill.json').read_bytes()
    assert 'Forecast error over frozen horizons' in (tmp_path / 'one/REPORT.md').read_text()
