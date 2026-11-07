"""Consistency verification, with independent mapping/accounting checks."""
from copy import deepcopy
from fractions import Fraction as F
from ...contracts import digest,canonical
from .contracts import Refuse,bound,size,MAX_REPORT,view,fraction,validate,exact,enc,declaration_bytes

def prepare_report(report):
    """Transport failures refuse; parsed structurally invalid evidence returns None."""
    try:bound(report,verify=True)
    except UnicodeError:raise Refuse('INVALID_ARGUMENT','surrogate report text') from None
    declaration_bytes(report,maximum=MAX_REPORT)
    if type(report) is not dict or report.get('route') not in ('ground','onboard','hybrid'):return None
    for name,kind in (('jobs',list),('stages',list),('proposal',dict),('network',dict),('network_input',dict),('dynamics',dict),('processing_buffers',list),('energy',dict),('cost',dict),('replay_event_map',list),('transfer_event_map',list),('failures',list)):
        if type(report.get(name)) is not kind:return None
    try:result=view(report,'report')
    except Refuse as ex:
        if ex.code=='BUDGET_EXCEEDED':raise
        return None
    size(result,MAX_REPORT,'report');return result

def verify_checkpoint_mission(scenario,report):
    from . import plan_checkpoint_mission,source_digest
    source_digest()
    report=prepare_report(report)
    if report is None:
        return dict(valid=False,errors=['INVALID_EVIDENCE'],source_sha256=source_digest(),execution_performed=False)
    expected=plan_checkpoint_mission(scenario,report['route']);errors=[]
    if canonical(expected)!=canonical(report):errors.append('REPLAY_MISMATCH')
    payload=deepcopy(report);receipt=payload.pop('receipt_id',None)
    if receipt!=digest(payload):errors.append('RECEIPT_MISMATCH')
    # Only traverse shape-validated regenerated structures. Equality above covers
    # all supplied fields; these checks independently enforce mapping relationships.
    m,_=validate(scenario,expected['route']);job=m['jobs'][0];route=expected['route']
    from ...network import dynamics_proposal
    from ...network.planner import storage_ok,Budget,available
    from ...dynamics import evaluate
    from . import call
    required=set();buffers=[]
    if expected['execution_performed'] is not False or expected['promoted'] is not False:errors.append('AUTHORITY_CLAIM')
    if job[route+'_quality']<job['required_quality']:required.add('QUALITY')
    delivered=[j for j in expected['network']['jobs'] if j['status']!='refused']
    for j in expected['network']['jobs']:
        if j['status']=='refused':required.add('NETWORK_'+j['reason_code'])
    stages={s['role']:s for s in expected['stages']}
    roles=(['origin'] if route!='ground' else [])+(['destination'] if delivered and route!='onboard' else [])
    if [s['role'] for s in expected['stages']]!=roles:errors.append('STAGE_COVERAGE')
    transfer_input=deepcopy(m['network']);release=job['release_s']
    if route!='ground':
        origin=stages.get('origin');release=None if origin is None or origin['completion_s'] is None else float(fraction(origin['completion_s']))
    if release is not None:
        transfer_input['jobs'].append(dict(id=job['id'],source=m['origin'],destination=m['destination'],release_s=release,deadline_s=job['deadline_s'],data_gb=job[{'ground':'raw_gb','onboard':'result_gb','hybrid':'compressed_gb'}[route]],allowed_jurisdictions=job['allowed_jurisdictions']))
    if canonical(transfer_input)!=canonical(expected['network_input']):errors.append('TRANSFER_DATA_PRECEDENCE')
    completion=None
    if delivered:
        if route=='onboard':completion=delivered[0]['arrival_s']
        elif 'destination' in stages and stages['destination']['completion_s'] is not None:completion=float(fraction(stages['destination']['completion_s']))
    if expected['jobs'][0]['completion_s']!=completion:errors.append('FINAL_COMPLETION')
    for stage in expected['stages']:
        required.update(stage['failures'])
        role=stage['role'];node=m[role]
        if job['memory_gb']>m['compute'][node]['memory_gb']:required.add('COMPUTE_MEMORY')
        work=job[('onboard_s' if route=='onboard' else 'preprocess_s') if role=='origin' else ('ground_s' if route=='ground' else 'hybrid_ground_s')]
        if work==0 and job['memory_gb']<=m['compute'][node]['memory_gb']:
            terminal=float(fraction(stage['terminal_s']))
            if terminal<=job['deadline_s'] and not available(m['network']['nodes'][node],terminal,terminal):required.add('COMPUTE_UNAVAILABLE')
            if terminal>job['deadline_s']:required.add('DEADLINE')
        if role=='origin':start=job['release_s'];amount=job['raw_gb']
        else:
            if not delivered:errors.append('GROUND_WITHOUT_DELIVERY');continue
            start=delivered[0]['arrival_s'];amount=job['raw_gb' if route=='ground' else 'compressed_gb']
        buffers.append((node,start,float(fraction(stage['terminal_s'])),amount))
    buffer_rows=[dict(node=n,start_s=a,end_s=b,data_gb=q) for n,a,b,q in buffers]
    if canonical(buffer_rows)!=canonical(expected['processing_buffers']):errors.append('PROCESSING_BUFFER_COVERAGE')
    network_buffers=[(r['node'],r['start_s'],r['end_s'],r['data_gb']) for r in expected['network']['buffer_reservations']]
    ok,reason=call('storage',storage_ok,expected['network_input'],buffers,network_buffers,Budget())
    if not ok:required.add('PROCESSING_'+reason)
    physics=call('dynamics',evaluate,expected['proposal'],m['dynamics'],source_sha256=expected['source_sha256'])
    if canonical(physics)!=canonical(expected['dynamics']):errors.append('DYNAMICS_BINDING')
    required.update('DYNAMICS_'+v['code'] for v in physics['violations'])
    actual={f['code'] for f in expected['failures']}
    if not required<=actual:errors.append('FAILURE_COVERAGE')
    if expected['admissible'] != (not expected['failures']):errors.append('ADMISSIBILITY')
    if expected['admissible'] and (expected['jobs'][0]['completion_s'] is None or any(s['conditional'] for s in expected['stages'])):errors.append('INCOMPLETE_ADMISSIBLE')
    original=call('proposal',dynamics_proposal,expected['network_input'],expected['network'],m['authority'],proposal_id=expected['original_proposal_id'])
    transfer_maps=expected['transfer_event_map']
    transfer_events=[e for e in expected['proposal']['events'] if e['kind']=='transfer']
    if len(original['events'])!=len(transfer_maps) or len(transfer_maps)!=len(transfer_events):errors.append('TRANSFER_CARDINALITY')
    if original.get('authority')!=expected['proposal'].get('authority'):errors.append('AUTHORITY_BINDING')
    for i,(event,mp,mapped) in enumerate(zip(original['events'],transfer_maps,transfer_events)):
        ident='transfer-'+digest(dict(index=i,original_event_id=event['id']))
        if mp!=dict(index=i,original_event_id=event['id'],mapped_event_id=ident) or mapped!=dict(event,id=ident):errors.append('TRANSFER_EVENT_BINDING')
    events={e['id']:e for e in expected['proposal']['events']};seen=set()
    energy=F(0)
    for stage in expected['stages']:
        replay=stage['replay']
        if replay is None:continue
        if digest(replay['trace'])!=replay['trace_sha256']:errors.append('TRACE_BINDING')
        if fraction(replay['productive_work_s'])!=sum((fraction(replay[k]) for k in ('lost_work_s','durable_work_s','volatile_work_s')),F(0)):errors.append('WORK_CONSERVATION')
        if len(replay['trace'])!=len(stage['replay_event_map']) or len(replay['trace'])!=len(stage['events']):errors.append('TRACE_CARDINALITY')
        for i,(row,mp,event) in enumerate(zip(replay['trace'],stage['replay_event_map'],stage['events'])):
            wanted_stage='stage-'+digest(dict(wrapper_id=scenario['id'],job_id=job['id'],node=m[stage['role']],stage=stage['role']))
            if stage['stage_id']!=wanted_stage or event['id']!='replay-'+wanted_stage[6:]+'-'+str(i) or event['node']!=m[stage['role']] or event['kind']!='compute' or event['start_s']!=float(fraction(row['start_s'])) or event['end_s']!=float(fraction(row['end_s'])):errors.append('DECLARED_EVENT_MAPPING')
            declarations=scenario['replay'][stage['role']]
            power=exact(declarations['power_kw'][row['state']]);heat=exact(declarations['heat_w'][row['state']])
            if mp['declared_power_kw']!=enc(power) or mp['declared_heat_w']!=enc(heat) or event['power_kw']!=float(power) or event['heat_w']!=float(heat):errors.append('DECLARED_RESOURCE_BINDING')
            if mp['trace_index']!=i or mp['state']!=row['state'] or mp['event_id']!=event['id']:errors.append('TRACE_EVENT_MAPPING')
            if stage['conditional']:
                if event['id'] in events:errors.append('CONDITIONAL_RESOURCE_LEAK')
            else:
                if events.get(event['id'])!=event:errors.append('EVENT_COVERAGE')
                seen.add(event['id']);energy+=fraction(mp['declared_power_kw'])*fraction(row['duration_s'])/3600
    for mp in expected['transfer_event_map']:
        if mp['mapped_event_id']!='transfer-'+digest(dict(index=mp['index'],original_event_id=mp['original_event_id'])):errors.append('TRANSFER_ID_BINDING')
        seen.add(mp['mapped_event_id'])
    if seen!=set(events):errors.append('EVENT_COVERAGE')
    if energy!=fraction(expected['energy']['declared_replay_kwh']):errors.append('ENERGY_CONSERVATION')
    return dict(schema='capacity-orbital/checkpoint-mission-verification-v2',valid=not errors,errors=sorted(set(errors)),input_sha256=expected['input_sha256'],source_sha256=source_digest(),report_receipt_id=receipt,scope='reproducibility and relationships, not authenticity, feasibility or acceptance',execution_performed=False)
