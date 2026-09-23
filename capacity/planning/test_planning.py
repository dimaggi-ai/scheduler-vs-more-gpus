"""Contract, independent arithmetic, perturbation and failure-path acceptance."""
import copy
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from capacity.report import digest
from sim.simulator import Config, Simulation, STEPS_PER_HOUR
from capacity.planning.model import (observe, build_plan, actual_artifact, validate_plan,
                                     validate_actual, forecast, seal, ACCOUNT)
from capacity.planning.ledger import Ledger
from capacity.planning.__main__ import publish_directory, read_json, main


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
    p=copy.deepcopy(bundle[1])
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
