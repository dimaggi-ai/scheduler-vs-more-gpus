"""Explicit mission-linked screening; lifecycle units/horizon stay separate."""
from ..contracts import digest
from ..diligence.api import dispatch,REQUEST
from ..agentic.dispatcher import manifest as static_manifest

def screen(m,network):
    linked=m['diligence'];lifecycle=None
    if linked['lifecycle'] is not None:
        lifecycle=dispatch(dict(schema=REQUEST,id=m['id']+':lifecycle',tool='lifecycle_cost',input=linked['lifecycle']))
    contacts={c['id']:c for c in m['network']['contacts']};claims=[]
    for j in network['jobs']:
        for index,h in enumerate(j['hops']):
            c=contacts[h['contact_id']]
            claim=dict(schema='capacity-orbital/claim-v1',name='Derived synthetic contact arithmetic',kind='link',parameters=dict(data_gb=h['data_gb'],goodput_gbps=c['goodput_gbps'],window_s=c['end_s']-c['start_s'],claimed_duration_s=h['tx_end_s']-h['start_s']),provenance=m['network']['provenance'])
            claims.append(dispatch(dict(schema=REQUEST,id=j['id']+':'+str(index),tool='check_claim',input=claim)))
    return dict(mission_id=m['id'],mission_input_sha256=digest(m),network_receipt_id=network['receipt_id'],lifecycle=lifecycle,lifecycle_status='separate sensitivity' if lifecycle else 'unknown: no lifecycle input',lifecycle_horizon_years=linked['lifecycle']['horizon_years'] if linked['lifecycle'] else None,mission_horizon_s=m['network']['horizon_s'],mission_cost_combined_with_lifecycle=False,contact_claims=claims,static_agent_tools=static_manifest(),limitations=['Lifecycle USD/kW-year sensitivity is not the mission partial operating USD or a mission total.','Static agentic evaluator remains available separately; it does not gate this coupled mission evaluator.'])
