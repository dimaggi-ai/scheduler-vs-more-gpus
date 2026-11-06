"""Exact synthetic checkpoint replay, without execution or inferred fault rates."""
from fractions import Fraction as F
from pathlib import Path
from copy import deepcopy
import hashlib
from ..contracts import digest
from .contracts import validate, encoded, rational, receipt, Refuse

MAX_INTERVALS = 10_000

def source_digest():
    root = Path(__file__).resolve().parents[1]
    paths = list((root/'reliability').glob('*.py')) + [root/'contracts.py',root/'output.py',root/'__init__.py',root.parent/'__init__.py']
    return digest({str(p.relative_to(root.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)})

def _evaluate(s):
    t=s['release_s']; deadline=s['deadline_s']; required=s['work_s']; policy=s['policy']
    durable=volatile=lost=F(0); durations={k:F(0) for k in s['power_kw']}; trace=[]
    outages=s['interruptions']; i=0
    while i<len(outages) and outages[i]['end_s']<=t:i+=1
    down=i<len(outages) and outages[i]['start_s']<=t<outages[i]['end_s']
    state='down' if down else 'productive'; remaining=F(0)
    while t<deadline:
        if len(trace)>=MAX_INTERVALS:raise Refuse('BUDGET_EXCEEDED','trace interval budget')
        before=dict(durable_work_s=durable,volatile_work_s=volatile,lost_work_s=lost)
        if state=='down': natural=outages[i]['end_s']
        elif state in ('checkpoint','restart'):natural=rational(t+remaining)
        else:
            need=required-durable-volatile
            interval=policy['checkpoint_every_work_s']
            productive_target=need if interval is None else min(need,interval-volatile)
            natural=rational(t+productive_target)
        next_outage=outages[i]['start_s'] if i<len(outages) and state!='down' else None
        end=min(natural,deadline,next_outage) if next_outage is not None else min(natural,deadline)
        dt=rational(end-t)
        if dt<=0:raise RuntimeError('nonpositive event advance')
        durations[state]=rational(durations[state]+dt)
        if state=='productive':volatile=rational(volatile+dt)
        elif state in ('checkpoint','restart'):remaining=rational(remaining-dt)
        prior_state=state;t=end;reasons=[]
        # Complete work and durable checkpoint/restart boundaries before a fault.
        complete=durable+volatile==required
        if complete:
            durable=required;volatile=F(0);reasons.append('job_completed')
        else:
            if state=='checkpoint' and remaining==0:
                durable=rational(durable+volatile);volatile=F(0);state='productive';reasons.append('checkpoint_committed')
            elif state=='restart' and remaining==0:
                state='productive';reasons.append('restart_completed')
            if prior_state=='down' and t==outages[i]['end_s']:
                i+=1;state='restart';remaining=policy['restart_duration_s'];reasons.append('outage_ended')
            elif i<len(outages) and t==outages[i]['start_s']:
                lost=rational(lost+volatile);volatile=F(0);state='down';remaining=F(0);reasons.append('outage_started')
            if t==deadline:reasons.append('deadline_reached')
            elif state=='productive' and policy['checkpoint_every_work_s'] is not None and volatile==policy['checkpoint_every_work_s']:
                state='checkpoint';remaining=policy['checkpoint_duration_s'];reasons.append('checkpoint_started')
        energy=rational(s['power_kw'][prior_state]*dt/F(3600))
        trace.append(dict(state=prior_state,start_s=t-dt,end_s=t,duration_s=dt,energy_kwh=energy,progress_before=before,progress_after=dict(durable_work_s=durable,volatile_work_s=volatile,lost_work_s=lost),reasons=reasons))
        if durations['productive']!=lost+durable+volatile:raise RuntimeError('work conservation failure')
        if complete:break
    energy={k:rational(durations[k]*s['power_kw'][k]/F(3600)) for k in durations}
    result=dict(schema='capacity-orbital/checkpoint-result-v1',status='completed' if durable==required else 'deadline_exceeded',classification='deterministic synthetic replay; not observed telemetry',input_sha256=digest(encoded(s)),source_sha256=source_digest(),policy_version=policy['version'],stop_s=t,completion_s=t if durable==required else None,required_work_s=required,durable_work_s=durable,volatile_work_s=volatile,lost_work_s=lost,productive_work_s=durations['productive'],durations_s=durations,energy_kwh=energy,total_energy_kwh=rational(sum(energy.values(),F(0))),trace=trace,trace_sha256=digest(encoded(trace)),execution_performed=False,promoted=False)
    if sum(durations.values(),F(0))!=t-s['release_s']:raise RuntimeError('duration conservation failure')
    return receipt(result)

def evaluate_checkpoint_policy(scenario):
    return _evaluate(validate(scenario))

def _pin(value):
    if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise Refuse('BASELINE_BINDING','required lowercase SHA-256 baseline digest')

def _fraction(value):return F(int(value['numerator']),int(value['denominator']))

def compare_checkpoint_policies(baseline,candidate,expected_baseline_sha256):
    _pin(expected_baseline_sha256)
    a,b=validate(baseline),validate(candidate)
    if digest(encoded(a))!=expected_baseline_sha256:raise Refuse('BASELINE_BINDING','baseline differs from supplied digest')
    def fixed(s):
        value=deepcopy(s)
        for key in ('id','provenance'):value.pop(key)
        for key in ('version','checkpoint_every_work_s'):value['policy'].pop(key)
        return value
    if fixed(a)!=fixed(b):raise Refuse('BASELINE_MISMATCH','only checkpoint interval and descriptive fields may vary')
    ar,br=_evaluate(a),_evaluate(b)
    ac=ar['status']=='completed';bc=br['status']=='completed'
    outcome=('both_completed' if bc else 'regression') if ac else ('candidate_completed_baseline_missed' if bc else 'both_missed')
    deltas={key:rational(_fraction(br[key])-_fraction(ar[key])) for key in ('stop_s','total_energy_kwh','lost_work_s','durable_work_s')}
    deltas['completion_s']=rational(_fraction(br['completion_s'])-_fraction(ar['completion_s'])) if ac and bc else None
    return receipt(dict(schema='capacity-orbital/checkpoint-comparison-v1',outcome=outcome,baseline={k:v for k,v in ar.items() if k!='trace'},candidate={k:v for k,v in br.items() if k!='trace'},deltas=deltas,evidence_scope='one declared timeline',recommendation='diagnostic only; held-out evaluation and independent acceptance required',delta_scope='candidate minus baseline; incomplete-work-sensitive descriptive values',baseline_binding='baseline matched supplied digest',input_sha256=digest(dict(baseline=encoded(a),candidate=encoded(b),expected_baseline_sha256=expected_baseline_sha256)),source_sha256=source_digest(),execution_performed=False,promoted=False))
