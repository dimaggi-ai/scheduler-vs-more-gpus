"""Generate only synthetic offline predictions and explicitly synthetic replay."""
import json,time,tracemalloc,platform
from pathlib import Path
from capacity.orbital.platform.fixtures import demo,suite,feedback_suite
from capacity.orbital.platform import compare_mission,verify_mission,evaluate_policies
from capacity.orbital.platform.feedback import assess_feedback
from capacity.orbital.platform.mission import source_digest
from capacity.orbital.platform.report import render
root=Path(__file__).parent
for kind in ('nominal','battery','corrected','network-loss','late','held'):
    mission=demo(kind);result=compare_mission(mission)
    Path('capacity/orbital/examples/platform-'+kind+'.json').write_text(json.dumps(mission,indent=2)+'\n')
    (root/(kind+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    (root/(kind+'-verification.json')).write_text(json.dumps([verify_mission(mission,r) for r in result['comparisons']],indent=2)+'\n')
    if kind=='nominal':(root/'nominal.html').write_text(render(result))
request=dict(schema='capacity-orbital/mission-tool-v1',id='fixed-policy-evaluation',tool='evaluate',arguments=dict(suite=suite(),baseline='ground',candidates=['onboard','hybrid']))
Path('capacity/orbital/examples/platform-evaluate.json').write_text(json.dumps(request,indent=2)+'\n')
(root/'policy-evaluation.json').write_text(json.dumps(evaluate_policies(**request['arguments']),indent=2)+'\n')
for worsening in (False,True):
    value=feedback_suite(worsening)
    request=dict(schema='capacity-orbital/mission-tool-v1',id='synthetic-feedback',tool='feedback',arguments=dict(suite=value))
    name='feedback-worsening' if worsening else 'feedback'
    Path('capacity/orbital/examples/platform-'+name+'.json').write_text(json.dumps(request,indent=2)+'\n')
    (root/(name+'.json')).write_text(json.dumps(assess_feedback(value),indent=2)+'\n')
rows=[]
for count in (1,5,10,20):
    m=demo();template=m['jobs'][0];m['jobs']=[dict(template,id=f'job-{i:02d}',deadline_s=290,raw_gb=.2,result_gb=.01,compressed_gb=.05,ground_s=2,onboard_s=1,preprocess_s=.5,hybrid_ground_s=1) for i in range(count)]
    tracemalloc.start();start=time.perf_counter();error=None;result=None
    try:result=compare_mission(m)
    except ValueError as exc:error=str(exc)
    elapsed=time.perf_counter()-start;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    rows.append(dict(jobs=count,nodes=3,contacts=2,seconds=elapsed,peak_traced_bytes=peak,refusal=error,admissible_routes=[r['route'] for r in result['comparisons'] if r['admissible']] if result else None))
(root/'scaling.json').write_text(json.dumps(dict(source_sha256=source_digest(),python=platform.python_version(),platform=platform.platform(),workload='one traced compare call per size; includes source hashing and diligence, excludes CLI/HTML IO',measurements=rows),indent=2)+'\n')
print(json.dumps(rows))
