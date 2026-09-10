"""Finite burst-shape/SLO sweep, not an open-loop sustainable-arrival-rate claim."""
import json
from pathlib import Path
from .inference import Hardware,Request,simulate


def experiment():
    rows=[]
    for hw in (Hardware('scenario-compute-rich',200e12,80e9,1e12),Hardware('scenario-bandwidth-rich',100e12,80e9,2e12)):
        for length,output in ((128,128),(2048,128),(8192,32)):
            for concurrency in (1,8,32):
                for cache in (0,.5):
                    req=[Request(i*.001,length,output,int(length*cache)) for i in range(concurrency)]
                    for policy in ('decode-first','prefill-first'):
                        rows.append(dict(input_length=length,output_length=output,concurrency=concurrency,
                                         cache_fraction=cache,result=simulate(req,hw,policy=policy)))
    return dict(evidence_class='simulated',input_class='scenario',runs=rows,
                baseline='Identical requests and memory/SLO envelope across scheduling policies and hardware scenarios',
                limitation='No serving trace calibration; hypothetical hardware classes, not vendor rankings. Cache fraction is assumed, not a demonstrated routing gain.')


if __name__=='__main__':
    result=experiment();p=Path('results/inference-scenarios.json');p.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(f'{len(result["runs"])} inference scenario comparisons written to {p}')
