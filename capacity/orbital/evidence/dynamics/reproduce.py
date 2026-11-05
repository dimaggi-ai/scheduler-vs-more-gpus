"""Run from repository root; replaces only this module's generated evidence."""
import json
import platform
import time
import tracemalloc
from pathlib import Path
from capacity.orbital.dynamics.fixtures import demo
from capacity.orbital.dynamics import evaluate
from capacity.orbital.dynamics.__main__ import source_digest
from capacity.orbital.dynamics.report import render

root=Path(__file__).parent
source=source_digest()
for kind in ('nominal','reserve','thermal','corrected'):
    bundle=demo(kind)
    result=evaluate(bundle['proposal'],bundle['scenario'],source_sha256=source)
    (root/(kind+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    if kind=='nominal':(root/'nominal.html').write_text(render(result))
rows=[]
for count in (10,100,1000,10000):
    bundle=demo('nominal');scenario=bundle['scenario'];proposal=bundle['proposal']
    node=next(iter(scenario['nodes']));config=scenario['nodes'][node]
    scenario['horizon_s']=count
    config['profiles']=[dict(start_s=0,end_s=count,solar_kw=0,background_kw=0,background_heat_w=0,sink_k=300)]
    proposal['authority']['expires_s']=count
    proposal['events']=[dict(id=str(i),node=node,kind='compute',start_s=i,end_s=i+1,power_kw=.01,heat_w=1) for i in range(count)]
    tracemalloc.start();start=time.perf_counter()
    result=evaluate(proposal,scenario,source_sha256=source)
    elapsed=time.perf_counter()-start;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    rows.append(dict(events=count,seconds=elapsed,peak_traced_bytes=peak,admissible=result['admissible'],intervals=len(result['nodes'][node]['intervals'])))
(root/'scaling.json').write_text(json.dumps(dict(python=platform.python_version(),platform=platform.platform(),source_sha256=source,workload='one node, nonoverlapping one-second events; one traced run each; excludes HTML and CLI file IO',measurements=rows),indent=2)+'\n')
print(source)
