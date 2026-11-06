"""Relationship checks supplement source/input binding and deterministic replay."""
import math
from bisect import bisect_right
from ..contracts import digest,canonical
from .contracts import validate
from .mission import plan_mission,source_digest

def _object(value,label):
    if type(value) is not dict:raise ValueError(label+' must be an object')
    return value

def _rows(value,label):
    if type(value) is not list or any(type(row) is not dict for row in value):raise ValueError(label+' must be an object list')
    return value

def _report_shapes(r):
    _object(r,'report')
    _rows(r['jobs'],'jobs');_rows(r['processing_buffers'],'processing buffers')
    _rows(_object(r['proposal'],'proposal')['events'],'events')
    network=_object(r['network'],'network')
    for job in _rows(network['jobs'],'network jobs'):_rows(job['hops'],'hops')
    for key in ('resource_reservations','buffer_reservations'):_rows(network[key],key)
    _rows(_object(r['network_input'],'network input')['jobs'],'network input jobs')
    nodes=_object(_object(r['dynamics'],'dynamics')['nodes'],'dynamics nodes')
    for state in nodes.values():
        for row in _rows(_object(state,'node state')['intervals'],'intervals'):_object(row['energy'],'energy ledger')
    _object(r['cost'],'cost')

def _ground_schedule(m,route,network_jobs):
    # Reconstruct the ordered compute lane, including eventless zero stages.
    expected={};cursor=0;node=m['network']['nodes'][m['destination']]
    for job in sorted(m['jobs'],key=lambda j:(j['release_s'],j['id'])):
        transfer=network_jobs.get(job['id'])
        if not transfer or transfer['status']!='delivered':continue
        if job['memory_gb']>m['compute'][m['destination']]['memory_gb']:expected[job['id']]=None;continue
        duration=job['ground_s' if route=='ground' else 'hybrid_ground_s']
        start=max(transfer['arrival_s'],cursor,node['commissioned_s'])
        for outage in node['unavailable']:
            if start<outage['end_s'] and start+duration>outage['start_s']:start=outage['end_s']
        end=start+duration
        if duration>0 and end-start<duration:end=math.nextafter(end,math.inf)
        invalid=(not math.isfinite(end) or end>m['network']['horizon_s'] or start<node['commissioned_s'] or end>node['retired_s'] or start>=node['retired_s'] or any((start<o['end_s'] and o['start_s']<end) or (start==end and o['start_s']<=start<o['end_s']) for o in node['unavailable']))
        if invalid:expected[job['id']]=None
        else:expected[job['id']]=end;cursor=end
    return expected

class VerificationBudget(ValueError):pass

def _index(rows,label):
    result={}
    for row in rows:
        ident=row['id']
        if type(ident) is not str or ident in result:raise ValueError(label+' requires unique string IDs')
        result[ident]=row
    return result

def _active_at(rows,times,charge):
    # Preserve original row order in every fsum; never subtract running totals.
    boundaries=[]
    for index,row in enumerate(rows):
        a,b=row['start_s'],row['end_s']
        if type(a) not in (int,float) or type(b) not in (int,float) or not math.isfinite(a) or not math.isfinite(b) or b<a:raise ValueError('invalid indexed interval')
        if b>a:boundaries.extend(((a,1,index),(b,0,index)))
    boundaries.sort();active=set();cursor=0
    for time in times:
        while cursor<len(boundaries) and boundaries[cursor][0]<=time:
            _,kind,index=boundaries[cursor]
            if kind:active.add(index)
            else:active.discard(index)
            cursor+=1
        charge(len(active)+1)
        yield [rows[i] for i in sorted(active)]

def verify_mission(m,r):
    errors=set();work=0
    def charge(amount):
        nonlocal work
        work+=amount
        if work>2_000_000:raise VerificationBudget('verification work budget exceeded')
    try:
        validate(m)
        if len(canonical(r).encode())>4000000:raise ValueError('report exceeds4MB')
        _report_shapes(r)
        contacts={c['id']:c for c in m['network']['contacts']}
        for job in r['network']['jobs']:
            for hop in job['hops']:
                if type(hop.get('contact_id')) is not str or hop['contact_id'] not in contacts:raise ValueError('unknown contact reference')
        if r['input_sha256']!=digest(m):errors.add('INPUT_BINDING')
        if r['source_sha256']!=source_digest():errors.add('SOURCE_BINDING')
        if r['receipt_id']!=digest({k:v for k,v in r.items() if k!='receipt_id'}):errors.add('OUTCOME_BINDING')
        if r['execution_performed'] or r['promoted']:errors.add('AUTHORITY_CLAIM')
        route=r['route'];jobs={j['id']:j for j in m['jobs']};events=r['proposal']['events']
        if route not in ('ground','onboard','hybrid'):raise ValueError('unknown report route')
        outputs=_index(r['jobs'],'output jobs');network_jobs=_index(r['network']['jobs'],'network jobs');transfer_jobs=_index(r['network_input']['jobs'],'transfer jobs');event_ids=_index(events,'events')
        if set(outputs)!=set(jobs):errors.add('JOB_COVERAGE');raise ValueError('output job coverage differs')
        if not set(network_jobs)<=set(jobs) or not set(transfer_jobs)<=set(jobs):raise ValueError('unknown network/transfer job')
        ground_schedule=_ground_schedule(m,route,network_jobs) if route!='onboard' else {}
        for node in m['compute']:
            lane=sorted([e for e in events if e['kind']=='compute' and e['node']==node],key=lambda e:e['start_s'])
            if any(a['end_s']>b['start_s'] for a,b in zip(lane,lane[1:])):errors.add('COMPUTE_OVERLAP')
        for job in r['jobs']:
            j=jobs[job['id']]
            if job['quality']!=j[route+'_quality'] or job['required_quality']!=j['required_quality']:errors.add('QUALITY_RELATIONSHIP')
            if r['admissible'] and (job['completion_s'] is None or job['completion_s']>j['deadline_s'] or job['quality']<j['required_quality']):errors.add('USEFUL_COMPLETION')
            nj=network_jobs.get(j['id'])
            compute=[event_ids[key] for key in (f"compute:{j['id']}:origin",f"compute:{j['id']}:ground") if key in event_ids]
            for e in compute:
                duration=j['onboard_s' if route=='onboard' else 'preprocess_s'] if e['node']==m['origin'] else j['ground_s' if route=='ground' else 'hybrid_ground_s']
                if not math.isclose(e['end_s']-e['start_s'],duration,rel_tol=1e-12,abs_tol=1e-12):errors.add('COMPUTE_DURATION')
                if e['power_kw']!=m['compute'][e['node']]['power_kw'] or e['heat_w']!=m['compute'][e['node']]['heat_w']:errors.add('COMPUTE_POWER')
            if nj and nj['status']=='delivered':
                size=j[{'ground':'raw_gb','onboard':'result_gb','hybrid':'compressed_gb'}[route]]
                previous=j['release_s']
                origin=next((e for e in compute if e['node']==m['origin']),None)
                if origin:previous=origin['end_s']
                for h in nj['hops']:
                    if h['data_gb']!=size or h['start_s']<previous:errors.add('BYTE_PRECEDENCE')
                    previous=h['arrival_s']
                ground=next((e for e in compute if e['node']==m['destination']),None)
                if ground and ground['start_s']<previous:errors.add('PROCESSING_BEFORE_ARRIVAL')
                expected=ground_schedule.get(j['id']) if route!='onboard' else nj['arrival_s']
                if job['completion_s']!=expected:errors.add('FINAL_COMPLETION')
        # Independent shared-resource and storage checks, not merely hashes.
        resources=r['network']['resource_reservations']
        # Sort once per shared resource; retain only its furthest end. Empty
        # half-open intervals occupy no resource and never overlap.
        lanes={}
        for row in resources:
            start,end=row['start_s'],row['end_s']
            if type(start) not in (int,float) or type(end) not in (int,float) or not math.isfinite(start) or not math.isfinite(end) or end<start:raise ValueError('invalid resource interval')
            if end>start:lanes.setdefault(canonical(row['resource']),[]).append((start,end))
        for lane in lanes.values():
            latest=None
            for start,end in sorted(lane):
                if latest is not None and start<latest:errors.add('SHARED_RESOURCE_OVERLAP')
                latest=end if latest is None else max(latest,end)
        all_buffers=r['processing_buffers']+r['network']['buffer_reservations']
        for node,n in m['network']['nodes'].items():
            reservations=[b for b in all_buffers if b['node']==node]
            charge(len(all_buffers))
            times={b[k] for b in reservations for k in ('start_s','end_s')}
            for active in _active_at(reservations,sorted(times),charge):
                used=math.fsum(b['data_gb'] for b in active)
                if used>n['buffer_gb']:errors.add('STORAGE_CAPACITY')
            outage_ends=[o['end_s'] for o in n['unavailable']]
            for b in reservations:
                if b['start_s']<n['commissioned_s'] or b['end_s']>n['retired_s']:errors.add('STORAGE_LIFETIME')
                oi=bisect_right(outage_ends,b['start_s'])
                if not n['preserve_storage'] and oi<len(outage_ends) and n['unavailable'][oi]['start_s']<b['end_s']:errors.add('STORAGE_RETENTION')
        # In a refused report, a storage violation is expected diagnostic evidence,
        # not corruption. Replay below still binds its exact refused disposition.
        if not r['admissible']:
            errors.difference_update(('STORAGE_CAPACITY','STORAGE_LIFETIME','STORAGE_RETENTION'))
        if r['admissible']:
            expected_buffers=[]
            for j in m['jobs']:
                nj=network_jobs[j['id']]
                transfer=transfer_jobs[j['id']]
                out=outputs[j['id']]
                if route!='ground':expected_buffers.append(dict(node=m['origin'],start_s=j['release_s'],end_s=transfer['release_s'],data_gb=j['raw_gb']))
                if route!='onboard':expected_buffers.append(dict(node=m['destination'],start_s=nj['arrival_s'],end_s=out['completion_s'],data_gb=j['raw_gb' if route=='ground' else 'compressed_gb']))
            if sorted(expected_buffers,key=canonical)!=sorted(r['processing_buffers'],key=canonical):errors.add('PROCESSING_BUFFER_RELATIONSHIP')
        for nj in r['network']['jobs']:
            for index,h in enumerate(nj['hops']):
                for role,node,start,end in (('tx',h['source'],h['start_s'],h['tx_end_s']),('rx',h['destination'],h['rx_start_s'],h['arrival_s'])):
                    event=event_ids.get(f"{nj['id']}:{index}:{role}")
                    n=m['network']['nodes'][node]
                    expected=dict(id=f"{nj['id']}:{index}:{role}",node=node,kind='transfer',start_s=start,end_s=end,power_kw=n[role+'_kw'],heat_w=n[role+'_heat_w'])
                    if event!=expected:errors.add('TRANSFER_EVENT_RELATIONSHIP')
        for node,state in r['dynamics']['nodes'].items():
            config=m['dynamics']['nodes'][node]
            rows=sorted(state['intervals'],key=lambda row:row['start_s'])
            profiles=config['profiles'];starts=[p['start_s'] for p in profiles]
            node_events=[e for e in events if e['node']==node]
            for row,active in zip(rows,_active_at(node_events,[r['start_s'] for r in rows],charge)):
                pi=bisect_right(starts,row['start_s'])-1
                if pi<0 or not row['start_s']<profiles[pi]['end_s']:raise ValueError('interval has no profile')
                profile=profiles[pi]
                expected=profile['background_kw']+math.fsum(e['power_kw'] for e in active)
                if not math.isclose(row['load_kw'],expected,rel_tol=1e-12,abs_tol=1e-12):errors.add('POWER_RELATIONSHIP')
                ledger=row['energy'];seconds=row['end_s']-row['start_s']
                if not math.isclose(ledger['load_kwh'],expected*seconds/3600,rel_tol=1e-12,abs_tol=1e-12):errors.add('ENERGY_RELATIONSHIP')
                balance=ledger['initial_kwh']+ledger['solar_kwh']-ledger['load_kwh']-ledger['conversion_loss_kwh']-ledger['curtailed_kwh']-ledger['final_kwh']
                if abs(balance)>1e-9*max(1,abs(ledger['initial_kwh'])):errors.add('ENERGY_CONSERVATION')
        compute_cost=math.fsum((e['end_s']-e['start_s'])*m['compute'][e['node']]['cost_per_s_usd'] for e in events if e['kind']=='compute')
        link_cost=math.fsum(h['data_gb']*contacts[h['contact_id']]['cost_per_gb'] for j in r['network']['jobs'] for h in j['hops'])
        if not math.isclose(r['cost']['partial_operating_usd'],compute_cost+link_cost,rel_tol=1e-12,abs_tol=1e-12):errors.add('COST_RELATIONSHIP')
        if r['admissible'] and (r['failures'] or not r['dynamics']['admissible'] or any(j['status']!='delivered' for j in r['network']['jobs'])):errors.add('ADMISSIBILITY')
        # Full reconstruction catches omissions and unsupported/extra evidence fields.
        if digest(plan_mission(m,route))!=digest(r):errors.add('REPLAY_MISMATCH')
    except VerificationBudget as exc:
        errors.add('VERIFICATION_BUDGET:'+str(exc))
    except (ValueError,TypeError,KeyError,StopIteration,OverflowError,RecursionError) as exc:
        errors.add('MALFORMED_EVIDENCE:'+str(exc)[:500])
    return dict(schema='capacity-orbital/verification-v1',valid=not errors,errors=sorted(set(errors)),classification='offline consistency, not authenticity or acceptance')
