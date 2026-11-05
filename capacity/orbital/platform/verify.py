"""Relationship checks supplement source/input binding and deterministic replay."""
import math
from ..contracts import digest,canonical
from .contracts import validate
from .mission import plan_mission,source_digest

def verify_mission(m,r):
    errors=[]
    try:
        validate(m)
        if len(canonical(r).encode())>4000000:raise ValueError('report exceeds4MB')
        if r['input_sha256']!=digest(m):errors.append('INPUT_BINDING')
        if r['source_sha256']!=source_digest():errors.append('SOURCE_BINDING')
        if r['receipt_id']!=digest({k:v for k,v in r.items() if k!='receipt_id'}):errors.append('OUTCOME_BINDING')
        if r['execution_performed'] or r['promoted']:errors.append('AUTHORITY_CLAIM')
        route=r['route'];jobs={j['id']:j for j in m['jobs']};events=r['proposal']['events']
        if set(x['id'] for x in r['jobs'])!=set(jobs) or len(r['jobs'])!=len(jobs):errors.append('JOB_COVERAGE')
        for node in m['compute']:
            lane=sorted([e for e in events if e['kind']=='compute' and e['node']==node],key=lambda e:e['start_s'])
            if any(a['end_s']>b['start_s'] for a,b in zip(lane,lane[1:])):errors.append('COMPUTE_OVERLAP')
        for job in r['jobs']:
            j=jobs[job['id']]
            if job['quality']!=j[route+'_quality'] or job['required_quality']!=j['required_quality']:errors.append('QUALITY_RELATIONSHIP')
            if r['admissible'] and (job['completion_s'] is None or job['completion_s']>j['deadline_s'] or job['quality']<j['required_quality']):errors.append('USEFUL_COMPLETION')
            nj=next((x for x in r['network']['jobs'] if x['id']==j['id']),None)
            compute=[e for e in events if e['id'] in (f"compute:{j['id']}:origin",f"compute:{j['id']}:ground")]
            for e in compute:
                duration=j['onboard_s' if route=='onboard' else 'preprocess_s'] if e['node']==m['origin'] else j['ground_s' if route=='ground' else 'hybrid_ground_s']
                if not math.isclose(e['end_s']-e['start_s'],duration,rel_tol=1e-12,abs_tol=1e-12):errors.append('COMPUTE_DURATION')
                if e['power_kw']!=m['compute'][e['node']]['power_kw'] or e['heat_w']!=m['compute'][e['node']]['heat_w']:errors.append('COMPUTE_POWER')
            if nj and nj['status']=='delivered':
                size=j[{'ground':'raw_gb','onboard':'result_gb','hybrid':'compressed_gb'}[route]]
                previous=j['release_s']
                origin=next((e for e in compute if e['node']==m['origin']),None)
                if origin:previous=origin['end_s']
                for h in nj['hops']:
                    if h['data_gb']!=size or h['start_s']<previous:errors.append('BYTE_PRECEDENCE')
                    previous=h['arrival_s']
                ground=next((e for e in compute if e['node']==m['destination']),None)
                if ground and ground['start_s']<previous:errors.append('PROCESSING_BEFORE_ARRIVAL')
                expected=ground['end_s'] if ground else previous
                if job['completion_s'] is not None and job['completion_s']!=expected:errors.append('FINAL_COMPLETION')
        # Independent shared-resource and storage checks, not merely hashes.
        resources=r['network']['resource_reservations']
        for i,a in enumerate(resources):
            for b in resources[i+1:]:
                if a['resource']==b['resource'] and a['start_s']<b['end_s'] and b['start_s']<a['end_s']:errors.append('SHARED_RESOURCE_OVERLAP')
        all_buffers=r['processing_buffers']+r['network']['buffer_reservations']
        for node,n in m['network']['nodes'].items():
            reservations=[b for b in all_buffers if b['node']==node]
            times={b[k] for b in reservations for k in ('start_s','end_s')}
            for time in times:
                used=math.fsum(b['data_gb'] for b in reservations if b['start_s']<=time<b['end_s'])
                if used>n['buffer_gb']:errors.append('STORAGE_CAPACITY')
            for b in reservations:
                if b['start_s']<n['commissioned_s'] or b['end_s']>n['retired_s']:errors.append('STORAGE_LIFETIME')
                if not n['preserve_storage'] and any(b['start_s']<o['end_s'] and o['start_s']<b['end_s'] for o in n['unavailable']):errors.append('STORAGE_RETENTION')
        # In a refused report, a storage violation is expected diagnostic evidence,
        # not corruption. Replay below still binds its exact refused disposition.
        if not r['admissible']:
            errors=[e for e in errors if e not in ('STORAGE_CAPACITY','STORAGE_LIFETIME','STORAGE_RETENTION')]
        if r['admissible']:
            expected_buffers=[]
            for j in m['jobs']:
                nj=next(x for x in r['network']['jobs'] if x['id']==j['id'])
                transfer=next(x for x in r['network_input']['jobs'] if x['id']==j['id'])
                out=next(x for x in r['jobs'] if x['id']==j['id'])
                if route!='ground':expected_buffers.append(dict(node=m['origin'],start_s=j['release_s'],end_s=transfer['release_s'],data_gb=j['raw_gb']))
                if route!='onboard':expected_buffers.append(dict(node=m['destination'],start_s=nj['arrival_s'],end_s=out['completion_s'],data_gb=j['raw_gb' if route=='ground' else 'compressed_gb']))
            if sorted(expected_buffers,key=canonical)!=sorted(r['processing_buffers'],key=canonical):errors.append('PROCESSING_BUFFER_RELATIONSHIP')
        for nj in r['network']['jobs']:
            for index,h in enumerate(nj['hops']):
                for role,node,start,end in (('tx',h['source'],h['start_s'],h['tx_end_s']),('rx',h['destination'],h['rx_start_s'],h['arrival_s'])):
                    event=next((x for x in events if x['id']==f"{nj['id']}:{index}:{role}"),None)
                    n=m['network']['nodes'][node]
                    expected=dict(id=f"{nj['id']}:{index}:{role}",node=node,kind='transfer',start_s=start,end_s=end,power_kw=n[role+'_kw'],heat_w=n[role+'_heat_w'])
                    if event!=expected:errors.append('TRANSFER_EVENT_RELATIONSHIP')
        for node,state in r['dynamics']['nodes'].items():
            config=m['dynamics']['nodes'][node]
            for row in state['intervals']:
                profile=next(p for p in config['profiles'] if p['start_s']<=row['start_s']<p['end_s'])
                active=[e for e in events if e['node']==node and e['start_s']<=row['start_s']<e['end_s']]
                expected=profile['background_kw']+math.fsum(e['power_kw'] for e in active)
                if not math.isclose(row['load_kw'],expected,rel_tol=1e-12,abs_tol=1e-12):errors.append('POWER_RELATIONSHIP')
                ledger=row['energy'];seconds=row['end_s']-row['start_s']
                if not math.isclose(ledger['load_kwh'],expected*seconds/3600,rel_tol=1e-12,abs_tol=1e-12):errors.append('ENERGY_RELATIONSHIP')
                balance=ledger['initial_kwh']+ledger['solar_kwh']-ledger['load_kwh']-ledger['conversion_loss_kwh']-ledger['curtailed_kwh']-ledger['final_kwh']
                if abs(balance)>1e-9*max(1,abs(ledger['initial_kwh'])):errors.append('ENERGY_CONSERVATION')
        compute_cost=math.fsum((e['end_s']-e['start_s'])*m['compute'][e['node']]['cost_per_s_usd'] for e in events if e['kind']=='compute')
        link_cost=math.fsum(h['data_gb']*next(c['cost_per_gb'] for c in m['network']['contacts'] if c['id']==h['contact_id']) for j in r['network']['jobs'] for h in j['hops'])
        if not math.isclose(r['cost']['partial_operating_usd'],compute_cost+link_cost,rel_tol=1e-12,abs_tol=1e-12):errors.append('COST_RELATIONSHIP')
        if r['admissible'] and (r['failures'] or not r['dynamics']['admissible'] or any(j['status']!='delivered' for j in r['network']['jobs'])):errors.append('ADMISSIBILITY')
        # Full reconstruction catches omissions and unsupported/extra evidence fields.
        if digest(plan_mission(m,route))!=digest(r):errors.append('REPLAY_MISMATCH')
    except (ValueError,TypeError,KeyError,StopIteration,OverflowError) as exc:
        errors.append('MALFORMED_EVIDENCE:'+str(exc))
    return dict(schema='capacity-orbital/verification-v1',valid=not errors,errors=sorted(set(errors)),classification='offline consistency, not authenticity or acceptance')
