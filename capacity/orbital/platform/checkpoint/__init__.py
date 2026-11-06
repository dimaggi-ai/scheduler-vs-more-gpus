"""Synthetic checkpoint-aware mission planning. No execution or promotion."""
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
import hashlib
import math
from ...contracts import digest,canonical
from ...network import plan_network,dynamics_proposal
from ...network.planner import available,storage_ok,Budget,BudgetError
from ...dynamics import evaluate
from ...reliability import evaluate_checkpoint_policy
from ..mission import source_digest as parent_source_digest
from .contracts import (Refuse,validate,normalized,enc,fraction,selected,decimal,exact,
                        GRID,finish,MAX_REPORT,size)

PARENT_SOURCE='dc7420c8d4be3466d1036eadf39206567d37d2b0bc11ddd8d9f3c00040e0593e'
NUMERIC={
 'network':{'nonfinite derived network arithmetic','positive transfer duration below numeric resolution','positive transfer/propagation below timestamp resolution'},
 'dynamics':{'nonfinite or undefined derived arithmetic','nonfinite derived state'},
}
BUDGETS={'proposal':{'dynamics adapter event budget exceeds10000'},'dynamics':{'shared-clock node/interval budget exceeds 100000','active-event arithmetic budget exceeds 1000000'}}

# Explicit reviewed inventory: globs additionally bind newly present source files,
# but can never silently erase a required cached module from the source receipt.
REQUIRED_SOURCE = tuple("""
__init__.py
orbital/__init__.py
orbital/__main__.py
orbital/adapters.py
orbital/agentic/__init__.py
orbital/agentic/__main__.py
orbital/agentic/benchmark.py
orbital/agentic/contracts.py
orbital/agentic/dispatcher.py
orbital/agentic/evaluation.py
orbital/agentic/request.schema.json
orbital/benchmark.py
orbital/contacts.py
orbital/contracts.py
orbital/diligence/__init__.py
orbital/diligence/__main__.py
orbital/diligence/api.py
orbital/diligence/benchmark.py
orbital/diligence/claims.py
orbital/diligence/contracts.py
orbital/diligence/fixtures.py
orbital/diligence/lifecycle.py
orbital/diligence/report.py
orbital/dynamics/__init__.py
orbital/dynamics/__main__.py
orbital/dynamics/contracts.py
orbital/dynamics/fixtures.py
orbital/dynamics/kernel.py
orbital/dynamics/physics.py
orbital/dynamics/report.py
orbital/network/__init__.py
orbital/network/__main__.py
orbital/network/adapter.py
orbital/network/contracts.py
orbital/network/fixtures.py
orbital/network/planner.py
orbital/network/report.py
orbital/output.py
orbital/planner.py
orbital/platform/__init__.py
orbital/platform/__main__.py
orbital/platform/checkpoint/__init__.py
orbital/platform/checkpoint/__main__.py
orbital/platform/checkpoint/contracts.py
orbital/platform/checkpoint/fixtures.py
orbital/platform/checkpoint/tools.py
orbital/platform/checkpoint/verify.py
orbital/platform/composition.json
orbital/platform/contracts.py
orbital/platform/diligence.py
orbital/platform/evaluation.py
orbital/platform/feedback.py
orbital/platform/fixtures.py
orbital/platform/mission.py
orbital/platform/report.py
orbital/platform/request.schema.json
orbital/platform/semantic.py
orbital/platform/tools.py
orbital/platform/verify.py
orbital/reliability/__init__.py
orbital/reliability/__main__.py
orbital/reliability/api.py
orbital/reliability/contracts.py
orbital/reliability/fixtures.py
orbital/report.py
orbital/resources.py
""".split())

def source_digest():
    root=Path(__file__).resolve().parents[2]
    paths={root.parent/name for name in REQUIRED_SOURCE}
    paths.update(p for p in root.glob('*.py') if not p.name.startswith('test_'))
    for folder in ('platform','network','dynamics','diligence','agentic','reliability','platform/checkpoint'):
        paths.update(p for p in (root/folder).glob('*.py') if not p.name.startswith('test_'))
        paths.update((root/folder).glob('*.json'))
    try:
        return digest({str(p.relative_to(root.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)})
    except OSError:
        raise Refuse('SOURCE_UNAVAILABLE','required local source missing or unreadable') from None

def call(scope,fn,*args,**kwargs):
    try:return fn(*args,**kwargs)
    except BudgetError as ex:
        if scope not in ('network','storage','proposal'):raise
        raise Refuse('BUDGET_EXCEEDED',scope+': '+str(ex)) from None
    except ValueError as ex:
        if str(ex) in BUDGETS.get(scope,set()):raise Refuse('BUDGET_EXCEEDED',scope+': '+str(ex)) from None
        if str(ex) in NUMERIC.get(scope,set()):raise Refuse('UNSUPPORTED_NUMERIC_DOMAIN',scope+': '+str(ex)) from None
        raise

def preflight(s,m,e,route):
    job=e['jobs'][0];specs=[]
    if route!='ground':specs.append(('origin','onboard_s' if route=='onboard' else 'preprocess_s'))
    if route!='onboard':specs.append(('destination','ground_s' if route=='ground' else 'hybrid_ground_s'))
    for role,workfield in specs:
        work=job[workfield]
        if work>31_557_600:raise Refuse('INVALID_ARGUMENT','mission.jobs[0].'+workfield+': work range')
        if not work:continue
        node=m[role];n=e['network']['nodes'][node];r=s['replay'][role]
        quantities={'work_s':work,'horizon_s':max(e['network']['horizon_s'],work),'deadline_s':min(job['deadline_s'],n['retired_s'])}
        if role=='origin':quantities['release_s']=max(job['release_s'],n['commissioned_s'])
        for k,v in quantities.items():selected(v,'replay.'+role+'.'+k,time=True)
        for k,v in r['policy'].items():
            if k!='version' and v is not None:selected(v,'replay.'+role+'.policy.'+k,time=True,positive=True)
        for i,o in enumerate(n['unavailable']):
            for k,v in o.items():selected(v,f'replay.{role}.interruptions[{i}].{k}',time=True)
        for name in ('power_kw','heat_w'):
            selected(e['compute'][node][name],f'mission.compute.{node}.{name}',maximum=1e9 if name=='power_kw' else 1e12)
    return specs

def _stage(s,m,e,role,workfield,arrival):
    job=m['jobs'][0];ej=e['jobs'][0];node=m[role];n=m['network']['nodes'][node];en=e['network']['nodes'][node];decl=s['replay'][role]
    stage_id='stage-'+digest(dict(wrapper_id=s['id'],job_id=job['id'],node=node,stage=role))
    work=ej[workfield];failures=[];replay=None;rows=[];mapping=[];conditional=False
    # Parent arrival and availability semantics are intentionally separate from exact declarations.
    a=max(arrival,n['commissioned_s']);ar=F.from_float(a) if type(a) is float else F(a)
    release=ar
    if work and role=='destination':release=((ar/GRID).__ceil__())*GRID
    elif role=='origin':release=max(ej['release_s'],en['commissioned_s'])
    delay=release-ar if role=='destination' and work else F(0)
    end=release;completion=None
    if job['memory_gb']>m['compute'][node]['memory_gb']:failures.append('COMPUTE_MEMORY')
    elif float(release)>=n['retired_s']:failures.append('COMPUTE_UNAVAILABLE')
    elif float(release)>job['deadline_s']:failures.append('DEADLINE')
    elif not work:
        if role=='origin':
            for o in n['unavailable']:
                if o['start_s']<=float(end)<o['end_s']:end=F.from_float(o['end_s']) if type(o['end_s']) is float else F(o['end_s'])
        if float(end)>job['deadline_s']:failures.append('DEADLINE')
        if not available(n,float(end),float(end)):failures.append('COMPUTE_UNAVAILABLE')
        if not failures:completion=end
    else:
        deadline=min(ej['deadline_s'],en['retired_s'])
        replay_input=dict(schema='capacity-orbital/checkpoint-v1',id=stage_id,release_s=selected(release,role+'.derived_release_s',time=True),deadline_s=selected(deadline,role+'.deadline_s',time=True),horizon_s=selected(max(e['network']['horizon_s'],work),role+'.validation_horizon_s',time=True),work_s=selected(work,role+'.work_s',time=True),interruptions=[{k:selected(v,role+'.interruptions.'+k,time=True) for k,v in o.items()} for o in en['unavailable']],policy={k:(v if k=='version' or v is None else selected(v,role+'.policy.'+k,time=True,positive=True)) for k,v in decl['policy'].items()},power_kw={k:selected(v,role+'.power_kw.'+k,maximum=1e9) for k,v in decl['power_kw'].items()},provenance=deepcopy(decl['provenance']))
        replay=evaluate_checkpoint_policy(replay_input);end=fraction(replay['stop_s'])
        conditional=not n['preserve_storage'] and any(float(release)<o['end_s'] and float(end)>o['start_s'] for o in n['unavailable'])
        if conditional:failures.extend(['CHECKPOINT_STORAGE_UNPRESERVED','PROCESSING_STORAGE_RETENTION'])
        if replay['status']!='completed':
            if end>=ej['deadline_s']:failures.append('DEADLINE')
            if end>=en['retired_s']:failures.append('COMPUTE_UNAVAILABLE')
        elif not conditional:completion=fraction(replay['completion_s'])
        for i,row in enumerate(replay['trace']):
            start,stop,dt=(fraction(row[k]) for k in ('start_s','end_s','duration_s'))
            fs,fe,fd=(float(selected(v,f'{role}.trace[{i}].{k}',time=True)) for k,v in (('start',start),('end',stop),('duration',dt)))
            if F.from_float(fe-fs)!=dt:raise Refuse('UNSUPPORTED_NUMERIC_DOMAIN',role+': float event subtraction differs from exact duration')
            state=row['state'];power=exact(decl['power_kw'][state]);heat=exact(decl['heat_w'][state]);ident='replay-'+stage_id[6:]+'-'+str(i)
            rows.append(dict(id=ident,node=node,kind='compute',start_s=fs,end_s=fe,power_kw=float(power),heat_w=float(heat)))
            mapping.append(dict(event_id=ident,stage_id=stage_id,trace_index=i,state=state,declared_power_kw=enc(power),declared_heat_w=enc(heat),mapped_power_kw=float(power),mapped_heat_w=float(heat)))
    result=dict(stage_id=stage_id,node=node,role=role,scope='conditional durability diagnostic; entire stage excluded from realized resources' if conditional else 'realized synthetic prediction',conditional=conditional,failures=failures,completion_s=completion,terminal_s=end,delivered_arrival_s=arrival if role=='destination' else None,delivered_arrival_exact_s=(F.from_float(arrival) if type(arrival) is float else F(arrival)) if role=='destination' else None,replay_release_s=release,quantization_delay_s=delay,replay=replay,events=rows,replay_event_map=mapping)
    return result

def plan_checkpoint_mission(scenario,route):
    source=source_digest()
    m,e=validate(scenario,route);preflight(scenario,m,e,route)
    if parent_source_digest()!=PARENT_SOURCE:raise Refuse('SOURCE_MISMATCH','parent source differs from reviewed composition')
    input_hash=digest(enc(normalized(scenario)));job=m['jobs'][0];fail=[];buffers=[];stages=[];events=[];maps=[]
    def add(stage):
        stages.append(stage)
        fail.extend(dict(job=job['id'],code=c) for c in stage['failures'])
        if not stage['conditional']:events.extend(stage['events']);maps.extend(stage['replay_event_map'])
    if job[route+'_quality']<job['required_quality']:fail.append(dict(job=job['id'],code='QUALITY'))
    release=job['release_s'];net=deepcopy(m['network'])
    if route!='ground':
        stage=_stage(scenario,m,e,'origin','onboard_s' if route=='onboard' else 'preprocess_s',release);add(stage)
        buffers.append((m['origin'],release,float(stage['terminal_s']),job['raw_gb']))
        release=float(stage['completion_s']) if stage['completion_s'] is not None else None
    if release is not None:
        net['jobs'].append(dict(id=job['id'],source=m['origin'],destination=m['destination'],release_s=release,deadline_s=job['deadline_s'],data_gb=job[{'ground':'raw_gb','onboard':'result_gb','hybrid':'compressed_gb'}[route]],allowed_jurisdictions=job['allowed_jurisdictions']))
    network=call('network',plan_network,net,source_sha256=source)
    # Reproduction happens before ID mapping; no original non-ID field is altered.
    original=call('proposal',dynamics_proposal,net,network,m['authority'],proposal_id='network-checkpoint-view')
    proposal=deepcopy(original);proposal['id']='proposal-'+digest(dict(wrapper_input_sha256=input_hash,route=route));transfer_map=[]
    for i,event in enumerate(proposal['events']):
        old=event['id'];event['id']='transfer-'+digest(dict(index=i,original_event_id=old));transfer_map.append(dict(index=i,original_event_id=old,mapped_event_id=event['id']))
    completion=None
    if network['jobs']:
        nj=network['jobs'][0]
        if nj['status']=='refused':fail.append(dict(job=job['id'],code='NETWORK_'+nj['reason_code']))
        else:
            completion=nj['arrival_s']
            if route!='onboard':
                stage=_stage(scenario,m,e,'destination','ground_s' if route=='ground' else 'hybrid_ground_s',completion);add(stage)
                buffers.append((m['destination'],completion,float(stage['terminal_s']),job['raw_gb' if route=='ground' else 'compressed_gb']))
                completion=float(stage['completion_s']) if stage['completion_s'] is not None else None
    nb=[(r['node'],r['start_s'],r['end_s'],r['data_gb']) for r in network['buffer_reservations']]
    ok,reason=call('storage',storage_ok,net,buffers,nb,Budget())
    if not ok:fail.append(dict(job=None,code='PROCESSING_'+reason))
    if len(events)+len(proposal['events'])>10000:raise Refuse('BUDGET_EXCEEDED','combined event budget exceeds 10000')
    allids=[x['id'] for x in proposal['events']+events]
    if len(allids)!=len(set(allids)):raise RuntimeError('mapped event ID collision')
    # Compute and transfer event intervals on one node must not overlap.
    for event in events:
        if any(t['node']==event['node'] and max(t['start_s'],event['start_s'])<min(t['end_s'],event['end_s']) for t in proposal['events']):raise RuntimeError('replay/transfer overlap invariant')
    proposal['events'].extend(events)
    physics=call('dynamics',evaluate,proposal,m['dynamics'],source_sha256=source)
    fail.extend(dict(job=None,code='DYNAMICS_'+v['code']) for v in physics['violations'])
    declared=F(0);mapped=F(0);cost=F(0)
    for stage in stages:
        if stage['conditional'] or stage['replay'] is None:continue
        report=stage['replay'];stage_energy=F(0)
        for row,event,mp in zip(report['trace'],stage['events'],stage['replay_event_map']):
            dt=fraction(row['duration_s']);stage_energy+=fraction(mp['declared_power_kw'])*dt/3600
            mapped+=F.from_float(event['power_kw'])*F.from_float(event['end_s']-event['start_s'])/3600
        if stage_energy!=fraction(report['total_energy_kwh']):raise RuntimeError('declared replay energy conservation failure')
        declared+=stage_energy
        busy=sum((fraction(report['durations_s'][k]) for k in ('productive','checkpoint','restart')),F(0))
        cost+=e['compute'][stage['node']]['cost_per_s_usd']*busy
    proposed=math.fsum((v['end_s']-v['start_s'])*v['power_kw']/3600 for v in proposal['events'])
    try:operating=math.fsum((float(cost),network['estimated_cost']))
    except OverflowError:raise Refuse('UNSUPPORTED_NUMERIC_DOMAIN','derived operating cost overflow') from None
    if not all(math.isfinite(x) for x in (proposed,operating)):raise Refuse('UNSUPPORTED_NUMERIC_DOMAIN','derived resource/cost float overflow')
    from ..diligence import screen
    result=dict(schema='capacity-orbital/checkpoint-mission-report-v2',scenario_id=scenario['id'],input_sha256=input_hash,parent_view_sha256=digest(m),parent_source_sha256=PARENT_SOURCE,source_sha256=source,route=route,admissible=not fail,failures=fail,jobs=[dict(id=job['id'],completion_s=completion,quality=job[route+'_quality'],required_quality=job['required_quality'])],stages=stages,network_input=net,network=network,proposal=proposal,original_proposal_id=original['id'],transfer_event_map=transfer_map,replay_event_map=maps,dynamics=physics,processing_buffers=[dict(node=n,start_s=a,end_s=b,data_gb=v) for n,a,b,v in buffers],energy=dict(declared_replay_kwh=declared,mapped_replay_kwh=mapped,signed_conversion_difference_kwh=mapped-declared,proposed_event_kwh=proposed,scope='conditional stages entirely excluded; mapped parent float whole-proposal prediction, not measured energy; dynamics may evaluate only prefix'),cost=dict(compute_exact_usd=cost,network_approximate_usd=network['estimated_cost'],partial_operating_usd=operating,scope='mixed precision synthetic USD; down unbilled; no billing'),diligence=screen(m,network),classification='synthetic conditional mission prediction; no geometry, checkpoint image bytes or execution',execution_performed=False,promoted=False)
    return finish(result)

def compare_checkpoint_missions(baseline,candidate,route,expected_baseline_sha256):
    source_digest()
    from ...reliability import _pin
    _pin(expected_baseline_sha256);validate(baseline,route);validate(candidate,route)
    a,b=normalized(baseline),normalized(candidate)
    if digest(enc(a))!=expected_baseline_sha256:raise Refuse('BASELINE_BINDING','baseline differs from supplied scenario digest')
    def fixed(s):
        v=deepcopy(s);v.pop('id');v['mission'].pop('id');v['mission']['diligence'].pop('mission_id')
        for k in ('network','dynamics'):
            for p in ('name','provenance'):v['mission'][k].pop(p)
        for r in v['replay'].values():
            r.pop('provenance');r['policy'].pop('version');r['policy'].pop('checkpoint_every_work_s')
        return enc(v)
    if canonical(fixed(a))!=canonical(fixed(b)):raise Refuse('BASELINE_MISMATCH','fixed mission assumptions differ')
    reports=[]
    for name,s in (('baseline',baseline),('candidate',candidate)):
        try:reports.append(plan_checkpoint_mission(s,route))
        except Refuse as ex:
            if ex.code=='BUDGET_EXCEEDED':raise Refuse(ex.code,name+' full report: '+str(ex)) from None
            raise
    ar,br=reports
    def summary(r):return {k:r[k] for k in ('receipt_id','input_sha256','source_sha256','parent_view_sha256','admissible','failures','jobs','energy','cost')}
    outcome=('both_admissible' if br['admissible'] else 'regression') if ar['admissible'] else ('candidate_admissible_baseline_failed' if br['admissible'] else 'both_inadmissible')
    ac=ar['jobs'][0]['completion_s'];bc=br['jobs'][0]['completion_s']
    return finish(dict(schema='capacity-orbital/checkpoint-mission-comparison-v2',baseline=summary(ar),candidate=summary(br),outcome=outcome,deltas=dict(completion_s=bc-ac if ac is not None and bc is not None else None,compute_exact_usd=fraction(br['cost']['compute_exact_usd'])-fraction(ar['cost']['compute_exact_usd']),declared_replay_kwh=fraction(br['energy']['declared_replay_kwh'])-fraction(ar['energy']['declared_replay_kwh'])),delta_scope='candidate minus baseline; incomplete-work-sensitive diagnostics',baseline_binding='matched caller supplied digest; approval origin not established',input_sha256=digest(dict(baseline=enc(a),candidate=enc(b),route=route,expected_baseline_sha256=expected_baseline_sha256)),source_sha256=source_digest(),execution_performed=False,promoted=False))

from .verify import verify_checkpoint_mission
