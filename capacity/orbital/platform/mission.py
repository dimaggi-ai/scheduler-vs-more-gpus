"""Coupled mission orchestration; frozen network/dynamics perform resource evaluation."""
from copy import deepcopy
import math
from ..contracts import digest
from ..network import plan_network,dynamics_proposal
from ..network.planner import available,storage_ok,Budget
from ..dynamics import evaluate
from .contracts import validate,ROUTES

def finite(x):
    if not math.isfinite(x):raise ValueError('nonfinite mission arithmetic')
    return x

def source_digest():
    import hashlib
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    paths=list(root.glob('*.py'))
    for folder in ('agentic','dynamics','network','diligence','platform'):
        paths.extend((root/folder).glob('*.py'))
        paths.extend((root/folder).glob('*.json'))
    return digest({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths) if not p.name.startswith('test_')})

def compute(m,node,job,stage,release,duration,cursors,events,failures):
    n=m['network']['nodes'][node];c=m['compute'][node]
    if job['memory_gb']>c['memory_gb']:
        failures.append(dict(job=job['id'],code='COMPUTE_MEMORY'));return None
    start=max(release,cursors[node],n['commissioned_s'])
    for outage in n['unavailable']:
        if start<outage['end_s'] and start+duration>outage['start_s']:start=outage['end_s']
    end=finite(start+duration)
    if duration>0 and end<=start:raise ValueError('compute duration below timestamp resolution')
    if duration>0 and end-start<duration:end=math.nextafter(end,math.inf)
    if end>m['network']['horizon_s'] or not available(n,start,end):
        failures.append(dict(job=job['id'],code='COMPUTE_UNAVAILABLE'));return None
    if duration>0:
        events.append(dict(id=f"compute:{job['id']}:{stage}",node=node,kind='compute',start_s=start,end_s=end,power_kw=c['power_kw'],heat_w=c['heat_w']))
    cursors[node]=end
    return start,end

def plan_mission(m,route):
    validate(m)
    if route not in ROUTES:raise ValueError('unknown registered mission policy')
    source=source_digest();events=[];failures=[];buffers=[];cursors={n:0 for n in m['compute']};pre={}
    net=deepcopy(m['network']);origin=m['origin'];ground=m['destination'];jobs=sorted(m['jobs'],key=lambda j:(j['release_s'],j['id']))
    for j in jobs:
        quality=j[route+'_quality']
        if quality<j['required_quality']:failures.append(dict(job=j['id'],code='QUALITY'))
        release=j['release_s']
        if route!='ground':
            result=compute(m,origin,j,'origin',release,j['onboard_s' if route=='onboard' else 'preprocess_s'],cursors,events,failures)
            if result is None:continue
            start,release=result
            buffers.append((origin,j['release_s'],release,j['raw_gb']))
        pre[j['id']]=release
        if release>j['deadline_s']:
            failures.append(dict(job=j['id'],code='DEADLINE'));continue
        size=j[{'ground':'raw_gb','onboard':'result_gb','hybrid':'compressed_gb'}[route]]
        net['jobs'].append(dict(id=j['id'],source=origin,destination=ground,release_s=release,deadline_s=j['deadline_s'],data_gb=size,allowed_jurisdictions=j['allowed_jurisdictions']))
    network=plan_network(net,source_sha256=source)
    proposal=dynamics_proposal(net,network,m['authority'],proposal_id=m['id']+':'+route)
    outcome=[];by_id={j['id']:j for j in network['jobs']}
    for j in jobs:
        nj=by_id.get(j['id']);completion=None
        if nj is None:pass
        elif nj['status']=='refused':failures.append(dict(job=j['id'],code='NETWORK_'+nj['reason_code']))
        else:
            arrival=nj['arrival_s'];completion=arrival
            if route!='onboard':
                result=compute(m,ground,j,'ground',arrival,j['ground_s' if route=='ground' else 'hybrid_ground_s'],cursors,events,failures)
                if result is None:completion=None
                else:
                    _,completion=result
                    buffers.append((ground,arrival,completion,j['raw_gb' if route=='ground' else 'compressed_gb']))
            if completion is not None and completion>j['deadline_s']:failures.append(dict(job=j['id'],code='DEADLINE'))
        outcome.append(dict(id=j['id'],completion_s=completion,quality=j[route+'_quality'],required_quality=j['required_quality'],deadline_s=j['deadline_s']))
    network_buffers=[(r['node'],r['start_s'],r['end_s'],r['data_gb']) for r in network['buffer_reservations']]
    ok,reason=storage_ok(net,buffers,network_buffers,Budget())
    if not ok:failures.append(dict(job=None,code='PROCESSING_'+reason))
    proposal['events'].extend(events)
    physics=evaluate(proposal,m['dynamics'],source_sha256=source)
    for v in physics['violations']:failures.append(dict(job=None,code='DYNAMICS_'+v['code']))
    compute_cost=finite(math.fsum((e['end_s']-e['start_s'])*m['compute'][e['node']]['cost_per_s_usd'] for e in events))
    event_energy=finite(math.fsum((e['end_s']-e['start_s'])*e['power_kw']/3600 for e in proposal['events']))
    available_energy=finite(math.fsum(row['energy']['load_kwh'] for n in physics['nodes'].values() for row in n['intervals']))
    result=dict(schema='capacity-orbital/mission-report-v1',mission_id=m['id'],route=route,input_sha256=digest(m),source_sha256=source,classification='synthetic coupled prediction; no execution or billing',execution_performed=False,promoted=False,admissible=not failures,failures=failures,jobs=outcome,network_input=net,network=network,proposal=proposal,dynamics=physics,processing_buffers=[dict(node=n,start_s=a,end_s=b,data_gb=v) for n,a,b,v in buffers],cost=dict(currency='USD',compute_usd=compute_cost,network_usd=network['estimated_cost'],partial_operating_usd=finite(compute_cost+network['estimated_cost']),lifecycle_total_usd=None),energy=dict(proposed_event_kwh=event_energy,evaluated_prefix_load_kwh=available_energy),capabilities=dict(topology='single origin compute, single ground compute, optional relay nodes',live_execution=False,orbital_geometry=False,real_tool_guard=False,production_metering=False,lifecycle_economics='pending separate diligence binding'))
    from .diligence import screen
    result['diligence']=screen(m,network)
    result['capabilities']['lifecycle_economics']='separate explicitly linked sensitivity; not mission total' if m['diligence']['lifecycle'] else 'unknown'
    result['receipt_id']=digest(result);return result

def compare_mission(m):
    results=[plan_mission(m,r) for r in ROUTES]
    return dict(schema='capacity-orbital/mission-comparison-v1',input_sha256=digest(m),source_sha256=source_digest(),evaluator='coupled-mission-v1 (distinct from static agentic evaluator)',comparisons=results,execution_performed=False,promoted=False)
