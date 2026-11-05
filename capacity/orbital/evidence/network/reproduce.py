"""Run from repository root; retained synthetic scenarios and measured limits."""
import json
import platform
import time
import tracemalloc
from pathlib import Path
from capacity.orbital.network import plan_network,dynamics_proposal
from capacity.orbital.network.fixtures import demo,dynamics_fixture
from capacity.orbital.network.__main__ import source_digest
from capacity.orbital.network.report import render
from capacity.orbital.dynamics import evaluate
from capacity.orbital.dynamics.__main__ import source_digest as physical_source
root=Path(__file__).parent;source=source_digest()
for kind in ('relay','outage','corrected','contention'):
    scenario=demo(kind);result=plan_network(scenario,source_sha256=source)
    Path('capacity/orbital/examples/network-'+kind+'.json').write_text(json.dumps(scenario,indent=2)+'\n')
    (root/(kind+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    if kind=='relay':(root/'relay.html').write_text(render(result))
scenario=demo();network=plan_network(scenario,source_sha256=source)
proposal=dynamics_proposal(scenario,network,dict(disposition='allowed',valid_from_s=0,expires_s=300,scope='synthetic-evaluation'))
for constrained in (False,True):
    result=evaluate(proposal,dynamics_fixture(scenario,constrained),source_sha256=physical_source())
    (root/('physical-refusal.json' if constrained else 'physical-success.json')).write_text(json.dumps(result,indent=2)+'\n')
rows=[]
for count,contacts in ((10,2),(50,2),(100,2),(200,2),(50,50)):
    s=demo();s['contacts']=[dict(s['contacts'][0],id='contact-'+str(i),link_id='AB',end_s=300) for i in range(contacts)]
    s['jobs']=[dict(s['jobs'][0],id=f'job-{i:03d}',destination='B',data_gb=.01,deadline_s=300) for i in range(count)]
    for n in s['nodes'].values():n['buffer_gb']=100
    tracemalloc.start();start=time.perf_counter();error=None;result=None
    try:result=plan_network(s,source_sha256=source)
    except ValueError as exc:error=str(exc)
    elapsed=time.perf_counter()-start;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    rows.append(dict(jobs=count,contacts=contacts,nodes=len(s['nodes']),seconds=elapsed,peak_traced_bytes=peak,refusal=error,operations=result['operations'] if result else None,delivered=sum(j['status']=='delivered' for j in result['jobs']) if result else None))
(root/'scaling.json').write_text(json.dumps(dict(python=platform.python_version(),platform=platform.platform(),source_sha256=source,workload='single physical link and shared terminal; one traced run, excludes CLI/HTML IO',measurements=rows),indent=2)+'\n')
print(json.dumps(rows))
