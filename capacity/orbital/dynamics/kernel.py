"""One shared scenario clock, pure evaluation and immutable diagnostic ledgers."""
import math
from ..contracts import digest
from .contracts import validate, source_hash, finite
from .physics import temperature, thermal_crossing, battery


def _authority(p):
    a=p.get('authority')
    if a is None:return 'held','AUTHORITY_MISSING'
    if a['disposition']!='allowed':return a['disposition'],'AUTHORITY_'+a['disposition'].upper()
    if p['at_s'] < a['valid_from_s']:return 'held','AUTHORITY_NOT_YET_VALID'
    if p['at_s'] >= a['expires_s'] or any(e['end_s']>a['expires_s'] for e in p['events']):
        return 'refused','AUTHORITY_EXPIRED'
    return 'allowed',None


def evaluate(proposal,scenario,*,source_sha256=None):
    """Strict pure agent-callable entry point; invalid numeric derivations refuse."""
    try:
        return _evaluate(proposal,scenario,source_sha256=source_sha256)
    except (OverflowError,ZeroDivisionError) as exc:
        raise ValueError('nonfinite or undefined derived arithmetic') from exc


def _evaluate(proposal,scenario,*,source_sha256=None):
    """Evaluate a synthetic proposal; never actuate, promote policy or mutate inputs.

    All nodes share the union of profile/event boundaries. Diagnostic evolution
    stops each node at its first violation; no state is committed to a scheduler.
    Invalid structure raises ValueError. Infeasible/unauthorized plans return
    admissible=False and stable reason codes. No actual Tool Guard claim.
    """
    validate(scenario,proposal);source_hash(source_sha256)
    disposition,reason=_authority(proposal)
    result=dict(schema='capacity-orbital/dynamics-report-v1',proposal_id=proposal['id'],
                input_sha256=digest({'scenario':scenario,'proposal':proposal}),source_sha256=source_sha256,
                source_binding='caller-supplied' if source_sha256 else 'unbound',
                classification='synthetic predicted feasibility; no observed or executed outcomes',
                authority={'disposition':disposition,'reason_code':reason,'enforcement':'caller-supplied planning capability; not actual Tool Guard enforcement'},
                admissible=False,nodes={},violations=[],receipt_id=None)
    if reason:
        result['violations'].append({'code':reason,'node':None,'at_s':proposal['at_s']})
        return _receipt(result)
    boundaries={0,scenario['horizon_s']}
    changes={name:{} for name in scenario['nodes']}
    for node in scenario['nodes'].values():
        for p in node['profiles']:boundaries.update((p['start_s'],p['end_s']))
    for e in proposal['events']:
        boundaries.update((e['start_s'],e['end_s']))
        for time,sign in ((e['start_s'],1),(e['end_s'],-1)):
            changes[e['node']].setdefault(time,[]).append((sign,e['id'],e['power_kw'],e['heat_w']))
    clock=sorted(boundaries)
    # Cross-product is explicit and bounded; do not accept unbounded report size.
    if len(clock)*len(scenario['nodes'])>100000:
        raise ValueError('shared-clock node/interval budget exceeds 100000')
    arithmetic_work=0
    for name,n in sorted(scenario['nodes'].items()):
        energy=n['battery']['initial_kwh'];temp=n['thermal']['initial_k'];profile_index=0
        active={}
        ledger=[];violations=[]
        for start,end in zip(clock,clock[1:]):
            for sign,event_id,power,heat_w in changes[name].get(start,[]):
                if sign>0:active[event_id]=(power,heat_w)
                else:active.pop(event_id)
            arithmetic_work+=len(active)
            if arithmetic_work>1000000:
                raise ValueError('active-event arithmetic budget exceeds 1000000')
            event_power=math.fsum(value[0] for value in active.values())
            event_heat=math.fsum(value[1] for value in active.values())
            while n['profiles'][profile_index]['end_s']<=start:profile_index+=1
            p=n['profiles'][profile_index];b=n['battery'];t=n['thermal']
            load=p['background_kw']+event_power;heat=p['background_heat_w']+event_heat
            finite(load,heat)
            duration=end-start;limit=duration;crossings=[]
            deficit=max(0,load-p['solar_kw'])
            if deficit>b['max_discharge_kw']:
                crossings.append((0.0,'DISCHARGE_POWER_LIMIT'))
            if deficit>0:
                reserve_time=max(0,(energy-b['reserve_kwh'])*3600*b['discharge_efficiency']/deficit)
                if reserve_time<duration-1e-9:crossings.append((reserve_time,'BATTERY_RESERVE'))
            next_temp=temperature(temp,p['sink_k'],heat,t['conductance_w_per_k'],t['heat_capacity_j_per_k'],duration)
            if next_temp>t['maximum_k']+1e-9:
                when=thermal_crossing(temp,t['maximum_k'],p['sink_k'],heat,t['conductance_w_per_k'],t['heat_capacity_j_per_k'])
                crossings.append((when,'THERMAL_LIMIT'))
            if crossings:limit=min(duration,min(x[0] for x in crossings))
            state=battery(energy,p['solar_kw'],load,b,limit)
            final_temp=temperature(temp,p['sink_k'],heat,t['conductance_w_per_k'],t['heat_capacity_j_per_k'],limit)
            ledger.append(dict(start_s=start,end_s=start+limit,planned_end_s=end,solar_kw=p['solar_kw'],
                               load_kw=load,heat_w=heat,initial_k=temp,final_k=final_temp,energy=state))
            energy=state['final_kwh'];temp=final_temp
            if crossings:
                violations=[dict(code=code,node=name,at_s=start+time) for time,code in crossings if abs(time-limit)<=1e-7]
                break
        result['nodes'][name]=dict(completed_horizon=not violations,evaluated_until_s=ledger[-1]['end_s'],
                                  final_kwh=energy,final_k=temp,intervals=ledger)
        result['violations'].extend(violations)
    result['violations'].sort(key=lambda x:(x['at_s'],x['node'] or '',x['code']))
    result['admissible']=not result['violations']
    return _receipt(result)


def _receipt(result):
    result['receipt_id']=digest({k:v for k,v in result.items() if k!='receipt_id'})
    return result
