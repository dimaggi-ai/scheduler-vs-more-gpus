"""Bounded synthetic lifecycle API scaling, with exact environment disclosure."""
import json
import platform
import time
import tracemalloc
from ..contracts import canonical
from .api import dispatch
from .fixtures import lifecycle_example,request


def run():
    rows=[];source=None
    for flows,cohorts,years in [(3,1,2),(100,20,20),(1000,200,100)]:
        s=lifecycle_example();s['horizon_years']=years
        s['cash_flows']=[{'id':f'flow-{i}','category':'operation','year':i%years+1,'amount':10,'currency':'USD'} for i in range(flows)]
        s['cohorts']=[{'id':f'cohort-{i}','count':1,'commission_year':0,'retirement_year':years,'capacity_kw':1,'utilization':.5,'availability':.9} for i in range(cohorts)]
        req=request('lifecycle_cost',s,'scaling')
        tracemalloc.start();start=time.perf_counter();result=dispatch(req)
        elapsed=time.perf_counter()-start;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        source=result['source_sha256']
        rows.append({'flows':flows,'cohorts':cohorts,'years':years,'elapsed_s':elapsed,
                     'peak_traced_python_bytes':peak,'request_bytes':len(canonical(req).encode()),
                     'response_bytes':len(canonical(result).encode()),'status':result['status']})
    return {'schema':'capacity-orbital/diligence-scaling-v1','source_sha256':source,
            'environment':{'python':platform.python_version(),'platform':platform.platform()},
            'classification':'single local observation with tracemalloc; not total RSS or production SLO','rows':rows}


if __name__=='__main__':print(json.dumps(run(),indent=2))
