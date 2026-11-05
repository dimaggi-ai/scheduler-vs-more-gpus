"""Pure bounded greedy simple-path store-and-forward, no optimality guarantee."""
import heapq
import math
from ..contracts import digest
from ..dynamics.contracts import source_hash
from .contracts import validate

class BudgetError(ValueError):pass

class Budget:
    def __init__(self):self.operations=0
    def tick(self,n=1):
        self.operations+=n
        if self.operations>200000:raise BudgetError('network operation budget exceeds200000')

def finite(value):
    if not math.isfinite(value):raise ValueError('nonfinite derived network arithmetic')
    return value

def overlaps(a,b,c,d):return a<d and c<b

def available(n,start,end):
    if start<n['commissioned_s'] or end>n['retired_s'] or start>=n['retired_s']:return False
    return not any(overlaps(start,end,r['start_s'],r['end_s']) or start==end and r['start_s']<=start<r['end_s'] for r in n['unavailable'])

def retained(n,start,end):
    return start>=n['commissioned_s'] and end<=n['retired_s'] and (n['preserve_storage'] or available(n,start,end))

def reservations(hops):
    result=[]
    for hop in hops:
        for resource,start,end in ((('link',hop['link_id']),hop['start_s'],hop['tx_end_s']),
             (('terminal',hop['source'],hop['source_terminal']),hop['start_s'],hop['tx_end_s']),
             (('terminal',hop['destination'],hop['destination_terminal']),hop['rx_start_s'],hop['arrival_s'])):
            result.append((resource,start,end))
    return result

def buffers(job,hops):
    if not hops:return []
    result=[(job['source'],job['release_s'],hops[0]['tx_end_s'],job['data_gb'])]
    for i,hop in enumerate(hops):
        end=hops[i+1]['tx_end_s'] if i+1<len(hops) else hop['arrival_s']
        result.append((hop['destination'],hop['rx_start_s'],end,job['data_gb']))
    return result

def storage_ok(s,trial,existing,budget):
    for index,(node,start,end,size) in enumerate(trial):
        n=s['nodes'][node]
        if not retained(n,start,end):return False,'STORAGE_RETENTION'
        if size>n['buffer_gb']:return False,'BUFFER_CAPACITY'
        intersecting=[];boundaries={start,end}
        for other_index,(other,a,b,v) in enumerate(existing+trial):
            budget.tick()
            if other_index==len(existing)+index:continue
            if other==node and overlaps(start,end,a,b):
                intersecting.append((a,b,v));boundaries.update((max(start,a),min(end,b)))
        for time in sorted(boundaries):
            if time==end:continue
            budget.tick(len(intersecting))
            used=finite(math.fsum([size]+[v for a,b,v in intersecting if a<=time<b]))
            if used>n['buffer_gb']:return False,'BUFFER_CAPACITY'
    return True,None

def schedule(s,c,arrival,size,existing,budget):
    duration=finite(size*8/c['goodput_gbps']);prop=c['propagation_s']
    if duration<=0:raise ValueError('positive transfer duration below numeric resolution')
    start=max(arrival,c['start_s']);nodes=s['nodes'];blocks=[]
    for name,offset in ((c['source'],0),(c['destination'],prop)):
        n=nodes[name];start=max(start,n['commissioned_s']-offset)
        for outage in n['unavailable']:
            budget.tick();blocks.append((outage['start_s']-offset,outage['end_s']-offset))
    keys={('link',c['link_id']):0,('terminal',c['source'],c['source_terminal']):0,('terminal',c['destination'],c['destination_terminal']):prop}
    for resource,x,y in existing:
        budget.tick()
        if resource in keys:
            offset=keys[resource];blocks.append((x-offset,y-offset))
    for x,y in sorted(blocks):
        budget.tick()
        if start<y and finite(start+duration)>x:start=y
    end=finite(start+duration);rx=finite(start+prop);arr=finite(end+prop)
    if end<=start or arr<=rx or prop>0 and (rx<=start or arr<=end):
        raise ValueError('positive transfer/propagation below timestamp resolution')
    # Round completion outward where addition lost a fraction of duration.
    if end-start<duration:end=math.nextafter(end,math.inf)
    if rx-start<prop:rx=math.nextafter(rx,math.inf)
    arr=max(arr,finite(rx+duration))
    if arr-rx<duration:arr=math.nextafter(arr,math.inf)
    if arr-end<prop:arr=math.nextafter(arr,math.inf)
    finite(end);finite(rx);finite(arr)
    if end>c['end_s'] or arr>s['horizon_s']:return None,'CONTACT_CAPACITY'
    if not available(nodes[c['source']],start,end) or not available(nodes[c['destination']],rx,arr):return None,'NODE_UNAVAILABLE'
    # Outward rounding may touch a reservation: conservatively refuse, never overlap.
    wanted=[(('link',c['link_id']),start,end),(('terminal',c['source'],c['source_terminal']),start,end),(('terminal',c['destination'],c['destination_terminal']),rx,arr)]
    for key,a,b in wanted:
        for resource,x,y in existing:
            budget.tick()
            if key==resource and overlaps(a,b,x,y):return None,'CONTACT_CAPACITY'
    return dict(contact_id=c['id'],link_id=c['link_id'],source=c['source'],destination=c['destination'],source_terminal=c['source_terminal'],destination_terminal=c['destination_terminal'],start_s=start,tx_end_s=end,rx_start_s=rx,arrival_s=arr,data_gb=size,cost=finite(size*c['cost_per_gb'])),None

def route(s,j,existing,stored,budget):
    allowed=j['allowed_jurisdictions'];nodes=s['nodes']
    if any(nodes[j[k]]['jurisdiction'] not in allowed for k in ('source','destination')):return None,'JURISDICTION'
    if not available(nodes[j['source']],j['release_s'],j['release_s']):return None,'NODE_UNAVAILABLE'
    if j['data_gb']==0 or j['source']==j['destination']:
        if not available(nodes[j['destination']],j['release_s'],j['release_s']):return None,'NODE_UNAVAILABLE'
        if j['data_gb']>nodes[j['source']]['buffer_gb']:return None,'BUFFER_CAPACITY'
        return [],None
    serial=0;queue=[(j['release_s'],serial,j['source'],[],(j['source'],))];reasons=set()
    while queue:
        budget.tick();arrival,_,node,hops,visited=heapq.heappop(queue)
        if node==j['destination']:return hops,None
        for c in sorted(s['contacts'],key=lambda x:(x['start_s'],x['id'])):
            budget.tick()
            if c['source']!=node or c['destination'] in visited:continue
            if nodes[c['destination']]['jurisdiction'] not in allowed:reasons.add('JURISDICTION');continue
            hop,reason=schedule(s,c,arrival,j['data_gb'],existing+reservations(hops),budget)
            if hop is None:reasons.add(reason);continue
            if hop['arrival_s']>j['deadline_s']:reasons.add('DEADLINE');continue
            candidate=hops+[hop];ok,reason=storage_ok(s,buffers(j,candidate),stored,budget)
            if not ok:reasons.add(reason);continue
            serial+=1;heapq.heappush(queue,(hop['arrival_s'],serial,c['destination'],candidate,visited+(c['destination'],)))
            if len(queue)>10000:raise BudgetError('network route frontier exceeds10000')
    return None, next((code for code in ('STORAGE_RETENTION','BUFFER_CAPACITY','DEADLINE','NODE_UNAVAILABLE','JURISDICTION','CONTACT_CAPACITY') if code in reasons),'NO_PATH')

def plan_network(scenario,*,source_sha256=None):
    try:return _plan(scenario,source_sha256)
    except (OverflowError,ZeroDivisionError) as exc:raise ValueError('nonfinite derived network arithmetic') from exc

def _plan(s,source):
    validate(s);source_hash(source);budget=Budget();reserved=[];stored=[];jobs=[];costs=[]
    for j in sorted(s['jobs'],key=lambda x:(x['release_s'],x['id'])):
        hops,reason=route(s,j,reserved,stored,budget)
        if hops is None:jobs.append(dict(id=j['id'],status='refused',reason_code=reason,hops=[],estimated_cost=0));continue
        reserved.extend(reservations(hops));stored.extend(buffers(j,hops))
        cost=finite(math.fsum(h['cost'] for h in hops));costs.append(cost)
        jobs.append(dict(id=j['id'],status='delivered',reason_code=None,hops=hops,arrival_s=hops[-1]['arrival_s'] if hops else j['release_s'],estimated_cost=cost))
    fleet={}
    for name,n in sorted(s['nodes'].items()):
        seconds=n['retired_s']-n['commissioned_s']-math.fsum(x['end_s']-x['start_s'] for x in n['unavailable'])
        fleet[name]=dict(available_seconds=seconds,available_capacity_kw_seconds=finite(seconds*n['capacity_kw']))
    result=dict(schema='capacity-orbital/network-report-v1',input_sha256=digest(s),source_sha256=source,classification='synthetic predicted store-and-forward; no execution or compliance certification',policy='greedy earliest-arrival simple paths; jobs ordered by release and ID',jobs=jobs,fleet=fleet,available_capacity_kw_seconds=finite(math.fsum(n['available_capacity_kw_seconds'] for n in fleet.values())),estimated_cost=finite(math.fsum(costs)),resource_reservations=[dict(resource=list(k),start_s=a,end_s=b) for k,a,b in reserved],buffer_reservations=[dict(node=n,start_s=a,end_s=b,data_gb=v) for n,a,b,v in stored],operations=budget.operations)
    result['receipt_id']=digest(result);return result
