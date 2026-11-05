"""Bounded synthetic network contract; seconds and decimal GB/Gbps."""
from ..contracts import fields,number,text
SCHEMA='capacity-orbital/network-v1'

def validate(s):
    fields(s,'schema name horizon_s provenance nodes contacts jobs','network scenario')
    if s['schema']!=SCHEMA:raise ValueError('unsupported network schema')
    text(s['name'],'name');h=number(s,'horizon_s',positive=True,upper=31557600)
    fields(s['provenance'],'kind source licence generated_on','provenance')
    if s['provenance']['kind']!='synthetic':raise ValueError('synthetic provenance required')
    for k,v in s['provenance'].items():text(v,k)
    if not isinstance(s['nodes'],dict) or not 1<=len(s['nodes'])<=32:raise ValueError('nodes requires 1..32 records')
    for name,n in s['nodes'].items():
        text(name,'node');fields(n,'jurisdiction buffer_gb commissioned_s retired_s unavailable preserve_storage capacity_kw terminals tx_kw rx_kw tx_heat_w rx_heat_w','node')
        text(n['jurisdiction'],'jurisdiction')
        for k in ('buffer_gb','commissioned_s','retired_s','capacity_kw','tx_kw','rx_kw','tx_heat_w','rx_heat_w'):number(n,k)
        if not 0<=n['commissioned_s']<n['retired_s']<=h:raise ValueError('invalid commissioning/retirement')
        if type(n['preserve_storage']) is not bool:raise ValueError('preserve_storage must be boolean')
        if not isinstance(n['terminals'],list) or not 1<=len(n['terminals'])<=16:raise ValueError('1..16 terminal IDs required')
        for t in n['terminals']:text(t,'terminal')
        if len(set(n['terminals']))!=len(n['terminals']):raise ValueError('duplicate terminal')
        if not isinstance(n['unavailable'],list) or len(n['unavailable'])>100:raise ValueError('unavailable intervals must be bounded list')
        last=n['commissioned_s']
        for r in n['unavailable']:
            fields(r,'start_s end_s','unavailable');number(r,'start_s');number(r,'end_s')
            if not last<=r['start_s']<r['end_s']<=n['retired_s']:raise ValueError('invalid unavailable intervals')
            last=r['end_s']
    if not isinstance(s['contacts'],list) or len(s['contacts'])>500:raise ValueError('at most500 contacts')
    ids=set();links={}
    for c in s['contacts']:
        fields(c,'id link_id source destination source_terminal destination_terminal start_s end_s goodput_gbps propagation_s cost_per_gb','contact')
        for k in ('id','link_id'):text(c[k],k)
        if c['id'] in ids:raise ValueError('duplicate contact id')
        ids.add(c['id'])
        for side in ('source','destination'):
            if not isinstance(c[side],str) or c[side] not in s['nodes']:raise ValueError('unknown contact node')
            if c[side+'_terminal'] not in s['nodes'][c[side]]['terminals']:raise ValueError('unknown terminal')
        if c['source']==c['destination']:raise ValueError('self contact forbidden')
        endpoints=frozenset((c['source'],c['destination']))
        if c['link_id'] in links and links[c['link_id']]!=endpoints:raise ValueError('link identity reused across different endpoints')
        links[c['link_id']]=endpoints
        for k in ('start_s','end_s','goodput_gbps','propagation_s','cost_per_gb'):number(c,k,positive=k=='goodput_gbps')
        if not c['start_s']<c['end_s']<=h:raise ValueError('invalid contact window')
    if not isinstance(s['jobs'],list) or len(s['jobs'])>200:raise ValueError('at most200 jobs')
    ids=set()
    for j in s['jobs']:
        fields(j,'id source destination release_s deadline_s data_gb allowed_jurisdictions','job')
        text(j['id'],'jobid')
        if j['id'] in ids:raise ValueError('duplicate jobid')
        ids.add(j['id'])
        for k in ('source','destination'):
            if not isinstance(j[k],str) or j[k] not in s['nodes']:raise ValueError('unknown job node')
        for k in ('release_s','deadline_s','data_gb'):number(j,k)
        if not j['release_s']<=j['deadline_s']<=h:raise ValueError('invalid job interval')
        if not isinstance(j['allowed_jurisdictions'],list) or not 1<=len(j['allowed_jurisdictions'])<=32:raise ValueError('allowed jurisdictions required')
        for value in j['allowed_jurisdictions']:text(value,'jurisdiction')
    return s
