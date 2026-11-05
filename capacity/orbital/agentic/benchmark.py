"""Observed bounded-suite cost, not a hardware workload performance claim."""
import json
import platform
import time
import tracemalloc
from ..adapters import synthetic
from ..contracts import canonical
from . import REQUEST_SCHEMA
from .contracts import SUITE_SCHEMA
from .dispatcher import Dispatcher, source_digest


def run():
    rows=[]
    for count,jobs in [(2,1),(10,10),(20,50)]:
        entries=[]
        for i in range(count):
            s=synthetic('intermittent',jobs)
            # Preserve validation bounds while making each workload semantically distinct.
            for job in s['jobs']:
                job['raw_gb'] += i/100
            entries.append(dict(id=f'scenario-{i}',scenario=s))
        suite=dict(schema=SUITE_SCHEMA,objective='failures_then_cost',cost_tolerance_usd=1e-9,
                   train=entries[:count//2],heldout=entries[count//2:])
        req=dict(schema=REQUEST_SCHEMA,id='scaling',tool='evaluate',arguments=dict(suite=suite,baseline='ground',candidates=['onboard','hybrid']))
        tracemalloc.start(); start=time.perf_counter()
        result=Dispatcher().dispatch(req)
        elapsed=time.perf_counter()-start
        _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        rows.append(dict(scenarios=count,jobs_per_scenario=jobs,total_jobs=count*jobs,
                         request_bytes=len(canonical(req).encode()),response_bytes=len(canonical(result).encode()),
                         elapsed_s=elapsed,peak_traced_python_bytes=peak,status=result['status']))
    return dict(schema='capacity-orbital/agentic-scaling-v1',source_sha256=source_digest(),
                environment=dict(python=platform.python_version(),platform=platform.platform()),
                classification='single local observation with tracemalloc; not total process memory or production SLO',rows=rows)


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
