from ..contracts import fields,number,text
from ..network.contracts import validate as network_validate
from ..dynamics.contracts import validate as dynamics_validate
ROUTES=('ground','onboard','hybrid')

def validate(m):
    fields(m,'schema id origin destination currency jobs compute network dynamics authority diligence','mission')
    if m['schema']!='capacity-orbital/mission-v1':raise ValueError('unsupported mission schema')
    text(m['id'],'mission ID')
    if m['currency']!='USD':raise ValueError('only explicit USD prices supported')
    fields(m['diligence'],'mission_id lifecycle','diligence binding')
    if m['diligence']['mission_id']!=m['id']:raise ValueError('diligence mission identity mismatch')
    if m['diligence']['lifecycle'] is not None:
        from ..diligence.lifecycle import lifecycle_cost
        lifecycle_cost(m['diligence']['lifecycle'])
    network_validate(m['network'])
    if m['network']['jobs']:raise ValueError('network template must have empty jobs')
    for key in ('origin','destination'):
        if not isinstance(m[key],str) or m[key] not in m['network']['nodes']:raise ValueError('unknown mission endpoint')
    if m['origin']==m['destination']:raise ValueError('distinct origin/ground required')
    if not isinstance(m['compute'],dict) or set(m['compute'])!={m['origin'],m['destination']}:raise ValueError('exactly origin and ground compute supported')
    for n in m['compute'].values():
        fields(n,'memory_gb power_kw heat_w cost_per_s_usd','compute node')
        for key in n:number(n,key)
    p=dict(schema='capacity-orbital/proposal-v1',id='validate',at_s=0,events=[],authority=m['authority'])
    dynamics_validate(m['dynamics'],p)
    if set(m['dynamics']['nodes'])!=set(m['network']['nodes']) or m['dynamics']['horizon_s']!=m['network']['horizon_s']:raise ValueError('network/dynamics node IDs and horizon must match exactly')
    if not isinstance(m['jobs'],list) or not 1<=len(m['jobs'])<=20:raise ValueError('1..20 jobs required')
    ids=set()
    for j in m['jobs']:
        fields(j,'id release_s deadline_s raw_gb result_gb compressed_gb memory_gb required_quality ground_quality onboard_quality hybrid_quality ground_s onboard_s preprocess_s hybrid_ground_s allowed_jurisdictions','mission job')
        text(j['id'],'job ID')
        if j['id'] in ids:raise ValueError('duplicate job ID')
        ids.add(j['id'])
        for k in j:
            if k not in ('id','allowed_jurisdictions'):number(j,k,upper=1 if 'quality' in k else None)
        if not j['release_s']<=j['deadline_s']<=m['network']['horizon_s']:raise ValueError('invalid mission job times')
        if not isinstance(j['allowed_jurisdictions'],list) or not j['allowed_jurisdictions']:raise ValueError('allowed jurisdictions required')
        for value in j['allowed_jurisdictions']:text(value,'jurisdiction')
    return m
