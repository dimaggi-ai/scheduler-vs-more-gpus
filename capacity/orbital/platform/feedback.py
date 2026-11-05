"""Synthetic replay diagnostics, fixed calibration candidates, never live learning."""
import math
from ..contracts import digest,fields,number,text
from .verify import verify_mission
from .evaluation import semantic
from .mission import source_digest
CANDIDATES={'identity':1.0,'scale_090':.9,'scale_110':1.1}

def predictions(m,r,jid):
    job=next(j for j in m['jobs'] if j['id']==jid)
    out=next(j for j in r['jobs'] if j['id']==jid)
    nj=next(j for j in r['network']['jobs'] if j['id']==jid)
    ids={f'compute:{jid}:origin',f'compute:{jid}:ground'}
    for i,_ in enumerate(nj['hops']):ids.update((f'{jid}:{i}:tx',f'{jid}:{i}:rx'))
    events=[e for e in r['proposal']['events'] if e['id'] in ids]
    return dict(duration_s=out['completion_s']-job['release_s'],energy_kwh=math.fsum((e['end_s']-e['start_s'])*e['power_kw']/3600 for e in events),link_gb=math.fsum(h['data_gb'] for h in nj['hops']),cost_usd=nj['estimated_cost']+math.fsum((e['end_s']-e['start_s'])*m['compute'][e['node']]['cost_per_s_usd'] for e in events if e['kind']=='compute'))

def validate_entry(entry):
    fields(entry,'mission report records','feedback entry');m=entry['mission'];r=entry['report']
    checked=verify_mission(m,r)
    if not checked['valid'] or not r['admissible']:raise ValueError('feedback requires verified feasible prediction')
    records=entry['records']
    if not isinstance(records,list) or not records or len(records)>20:raise ValueError('1..20 replay records required')
    ids=set();pairs=[];jobs={j['id']:j for j in m['jobs']}
    for rec in records:
        fields(rec,'schema id classification mission_input_sha256 source_sha256 proposal_receipt_id job_id completion_s energy_kwh link_gb cost_usd','replay record')
        if rec['schema']!='capacity-orbital/synthetic-replay-v1' or rec['classification']!='supplied synthetic replay':raise ValueError('only explicitly supplied synthetic replay supported')
        text(rec['id'],'record ID')
        if rec['id'] in ids or rec['job_id'] in [x[0] for x in pairs]:raise ValueError('duplicate replay record/job')
        ids.add(rec['id'])
        if rec['mission_input_sha256']!=digest(m) or rec['source_sha256']!=source_digest() or rec['proposal_receipt_id']!=r['receipt_id']:raise ValueError('replay binding mismatch')
        if rec['job_id'] not in jobs:raise ValueError('unknown replay job')
        for key in ('completion_s','energy_kwh','link_gb','cost_usd'):number(rec,key)
        release=jobs[rec['job_id']]['release_s']
        if rec['completion_s']<release:raise ValueError('replay completion precedes release')
        observed=dict(duration_s=rec['completion_s']-release,energy_kwh=rec['energy_kwh'],link_gb=rec['link_gb'],cost_usd=rec['cost_usd'])
        pairs.append((rec['job_id'],predictions(m,r,rec['job_id']),observed))
    if {x[0] for x in pairs}!=set(jobs):raise ValueError('replay must cover every mission job; missing outcomes remain unknown')
    return pairs

def metrics(pairs,factor):
    result={}
    for key in ('duration_s','energy_kwh','link_gb','cost_usd'):
        scale=factor if key in ('duration_s','energy_kwh') else 1
        values=[abs(pred[key]*scale-replay[key]) for _,pred,replay in pairs]
        value=math.fsum(values)/len(values)
        if not math.isfinite(value):raise ValueError('nonfinite feedback metric')
        result[key+'_mae']=value
    return result

def assess_feedback(suite):
    fields(suite,'schema train heldout','feedback suite')
    if suite['schema']!='capacity-orbital/feedback-suite-v1':raise ValueError('unsupported feedback schema')
    pairs={};logs={};seen=set();count=0
    for split in ('train','heldout'):
        entries=suite[split]
        if not isinstance(entries,list) or not entries:raise ValueError('train and heldout feedback required')
        count+=len(entries)
        if count>6:raise ValueError('at most6 replay missions')
        pairs[split]=[];logs[split]=[]
        for entry in entries:
            group=validate_entry(entry);key=digest(semantic(entry['mission']))
            if key in seen:raise ValueError('feedback workload leakage across partitions')
            seen.add(key);pairs[split].extend(group)
            logs[split].append(dict(mission_id=entry['mission']['id'],mission_input_sha256=digest(entry['mission']),source_sha256=entry['report']['source_sha256'],proposal_receipt_id=entry['report']['receipt_id'],classification='supplied synthetic replay',jobs=[dict(job_id=jid,record_id=next(r['id'] for r in entry['records'] if r['job_id']==jid),prediction=pred,replay=replay,baseline_residual={metric:pred[metric]-replay[metric] for metric in pred}) for jid,pred,replay in group]))
    results={split:{name:metrics(pairs[split],factor) for name,factor in CANDIDATES.items()} for split in pairs}
    selected=min(CANDIDATES,key=lambda name:(results['train'][name]['duration_s_mae'],results['train'][name]['energy_kwh_mae'],list(CANDIDATES).index(name)))
    base=results['heldout']['identity'];candidate=results['heldout'][selected]
    keys=('duration_s_mae','energy_kwh_mae')
    improves=all(candidate[k]<=base[k] for k in keys) and any(candidate[k]<base[k] for k in keys)
    return dict(schema='capacity-orbital/feedback-result-v1',classification='supplied synthetic replay diagnostics, not measured telemetry',source_sha256=source_digest(),suite_sha256=digest(suite),baseline='identity',registered_candidates=dict(CANDIDATES),selected_on_train=selected,recommendation=selected if improves else None,prediction_outcome_log=logs,metrics=results,metric_units=dict(duration_s_mae='seconds',energy_kwh_mae='kWh',link_gb_mae='decimal GB summed across hops',cost_usd_mae='USD'),stop_reason='fixed candidates evaluated; no heldout reselection',changes_feasibility=False,changes_prices=False,execution_performed=False,promoted=False)
