"""Declared transfer events only: no hidden background/duplicate energy injection."""
from ..contracts import digest
from .planner import plan_network

def dynamics_proposal(scenario,report,authority,*,proposal_id='network-transfer-evaluation'):
    """Recompute/bind the planning report before exporting its delivered transfers.

    Source provenance is a caller claim. Report tampering refuses; actual authority
    is still evaluated by dynamics, never provisioned or broadened here.
    """
    expected=plan_network(scenario,source_sha256=report.get('source_sha256'))
    if digest(expected)!=digest(report):raise ValueError('network report does not reproduce from scenario')
    events=[]
    for j in report['jobs']:
        for index,h in enumerate(j['hops']):
            for role,node,start,end in (('tx',h['source'],h['start_s'],h['tx_end_s']),('rx',h['destination'],h['rx_start_s'],h['arrival_s'])):
                n=scenario['nodes'][node]
                events.append(dict(id=f"{j['id']}:{index}:{role}",node=node,kind='transfer',start_s=start,end_s=end,power_kw=n[role+'_kw'],heat_w=n[role+'_heat_w']))
    if len(events)>10000:raise ValueError('dynamics adapter event budget exceeds10000')
    proposal=dict(schema='capacity-orbital/proposal-v1',id=proposal_id,at_s=0,events=events)
    if authority is not None:
        proposal['authority']=dict(authority)
    return proposal
