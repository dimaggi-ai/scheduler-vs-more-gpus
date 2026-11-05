"""Bounded label-independent mission fingerprints for split isolation.

This is deliberately a partial graph canonicalizer: color refinement must
uniquely identify every referenced node, terminal and link. Symmetry that it
cannot resolve is refused, never broken using the caller's names and never
expanded into factorial permutation search. It is not a near-copy detector.
"""
from copy import deepcopy
from ..contracts import canonical,digest
from .contracts import validate

MAX_ROUNDS=64
MAX_WORK=500000

class SemanticRefusal(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _strip(value,key=None):
    if isinstance(value,dict):
        return {k:_strip(v,k) for k,v in value.items() if k not in ('id','name','provenance','mission_id')}
    if isinstance(value,list):
        items=[_strip(v) for v in value]
        return sorted(items,key=canonical) if key in ('jobs','contacts','allowed_jurisdictions','terminals','cash_flows','cohorts') else items
    return value


def semantic(mission):
    validate(mission)
    net=mission['network'];base={};neighbors={}
    def vertex(key,attributes):base[key]=digest(attributes);neighbors[key]=[]
    def edge(a,label,b):
        neighbors[a].append((label,b));neighbors[b].append(('reverse:'+label,a))
    for name,n in net['nodes'].items():
        role='origin' if name==mission['origin'] else 'destination' if name==mission['destination'] else 'relay'
        vertex(('node',name),dict(kind='node',role=role,network={k:v for k,v in n.items() if k!='terminals'},dynamics=mission['dynamics']['nodes'][name],compute=mission['compute'].get(name)))
        for terminal in n['terminals']:
            key=('terminal',name,terminal);vertex(key,dict(kind='terminal'));edge(key,'owned-by',('node',name))
    for contact in net['contacts']:
        key=('link',contact['link_id'])
        if key not in base:vertex(key,dict(kind='link'))
    for index,c in enumerate(net['contacts']):
        key=('contact',index)
        vertex(key,dict(kind='contact',attributes={k:v for k,v in c.items() if k not in ('id','link_id','source','destination','source_terminal','destination_terminal')}))
        edge(key,'source-node',('node',c['source']));edge(key,'destination-node',('node',c['destination']))
        edge(key,'source-terminal',('terminal',c['source'],c['source_terminal']))
        edge(key,'destination-terminal',('terminal',c['destination'],c['destination_terminal']))
        edge(key,'shared-link',('link',c['link_id']))
    colors=dict(base);work=0
    for _ in range(MAX_ROUNDS):
        work+=len(base)+sum(len(v) for v in neighbors.values())
        if work>MAX_WORK:raise SemanticRefusal('BUDGET_EXCEEDED','semantic graph work budget exceeded')
        refined={key:digest([colors[key],sorted((label,colors[other]) for label,other in neighbors[key])]) for key in base}
        # Including the previous color makes refinement monotone: equal class
        # counts means the partition stopped splitting (hash collisions aside).
        stable=len(set(refined.values()))==len(set(colors.values()))
        colors=refined
        if stable:break
    else:raise SemanticRefusal('BUDGET_EXCEEDED','semantic refinement round budget exceeded')
    mappings={}
    for kind in ('node','terminal','link'):
        keys=[key for key in base if key[0]==kind]
        if len({colors[k] for k in keys})!=len(keys):
            raise SemanticRefusal('SEMANTIC_TOPOLOGY_AMBIGUOUS','ambiguous semantic topology: unresolved '+kind+' identities; split evaluation refused')
        mappings[kind]={key:kind+'-'+str(index) for index,key in enumerate(sorted(keys,key=lambda k:colors[k]))}
    node_map={name:mappings['node'][('node',name)] for name in net['nodes']}
    out=deepcopy(mission)
    out['origin']=node_map[mission['origin']];out['destination']=node_map[mission['destination']]
    out['compute']={node_map[name]:value for name,value in out['compute'].items()}
    out['dynamics']['nodes']={node_map[name]:value for name,value in out['dynamics']['nodes'].items()}
    out['network']['nodes']={node_map[name]:dict(value,terminals=[mappings['terminal'][('terminal',name,t)] for t in value['terminals']]) for name,value in out['network']['nodes'].items()}
    for contact in out['network']['contacts']:
        source,destination=contact['source'],contact['destination']
        contact['source_terminal']=mappings['terminal'][('terminal',source,contact['source_terminal'])]
        contact['destination_terminal']=mappings['terminal'][('terminal',destination,contact['destination_terminal'])]
        contact['source']=node_map[source];contact['destination']=node_map[destination]
        contact['link_id']=mappings['link'][('link',contact['link_id'])]
    return _strip(out)
