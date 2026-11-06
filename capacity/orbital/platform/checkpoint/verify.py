"""Consistency verification, with independent mapping/accounting checks."""
from copy import deepcopy
from fractions import Fraction as F
from ...contracts import digest,canonical
from .contracts import Refuse,bound,size,MAX_REPORT,view,fraction

def verify_checkpoint_mission(scenario,report):
    from . import plan_checkpoint_mission,source_digest
    source_digest()
    try:
        bound(report,verify=True);report=view(report,'report');size(report,MAX_REPORT,'report')
    except (Refuse,UnicodeError) as ex:
        return dict(valid=False,errors=['INVALID_EVIDENCE: '+str(ex)],source_sha256=source_digest(),execution_performed=False)
    if type(report) is not dict or report.get('route') not in ('ground','onboard','hybrid'):
        return dict(valid=False,errors=['INVALID_EVIDENCE'],source_sha256=source_digest(),execution_performed=False)
    expected=plan_checkpoint_mission(scenario,report['route']);errors=[]
    if canonical(expected)!=canonical(report):errors.append('REPLAY_MISMATCH')
    payload=deepcopy(report);receipt=payload.pop('receipt_id',None)
    if receipt!=digest(payload):errors.append('RECEIPT_MISMATCH')
    # Only traverse shape-validated regenerated structures. Equality above covers
    # all supplied fields; these checks independently enforce mapping relationships.
    events={e['id']:e for e in expected['proposal']['events']};seen=set()
    energy=F(0)
    for stage in expected['stages']:
        replay=stage['replay']
        if replay is None:continue
        if digest(replay['trace'])!=replay['trace_sha256']:errors.append('TRACE_BINDING')
        if fraction(replay['productive_work_s'])!=sum((fraction(replay[k]) for k in ('lost_work_s','durable_work_s','volatile_work_s')),F(0)):errors.append('WORK_CONSERVATION')
        for i,(row,mp,event) in enumerate(zip(replay['trace'],stage['replay_event_map'],stage['events'])):
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
