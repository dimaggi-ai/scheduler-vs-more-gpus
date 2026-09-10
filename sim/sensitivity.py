"""Factorial policy ablation under common jobs/events; simulation, not telemetry."""
import argparse
import dataclasses
import hashlib
import json
from pathlib import Path
import statistics
from simulator import Config, Simulation


def experiment(days=14, seeds=range(12)):
    rows=[]
    for load in (.7,.95,1.2):
        for power in (.6,.75,1.):
            for seed in seeds:
                cfg=Config(horizon_days=days,seed=seed,offered_load=load,
                           power_envelope=True,power_frac=power,failures=True,inf_surges=True)
                for tracking,elasticity in ((False,False),(True,False),(False,True),(True,True)):
                    result=Simulation(cfg,'intent-closed-loop',track_demand=tracking,elasticity=elasticity).run()
                    rows.append(dict(config=dataclasses.asdict(cfg),tracking=tracking,elasticity=elasticity,
                                     evidence_class='simulated',result=result))
    summaries=[]
    for load in (.7,.95,1.2):
        for power in (.6,.75,1.):
            cells={}
            for tracking,elasticity in ((False,False),(True,False),(False,True),(True,True)):
                selected=[r['result']['capacity_realization'] for r in rows if r['config']['offered_load']==load
                          and r['config']['power_frac']==power and r['tracking']==tracking and r['elasticity']==elasticity]
                cells[f'{int(tracking)}{int(elasticity)}']=statistics.mean(selected)
            summaries.append(dict(load=load,power_fraction=power,cells=cells,
                                  interaction=cells['11']-cells['10']-cells['01']+cells['00']))
    return dict(evidence_class='simulated',input_class='scenario',days=days,seeds=list(seeds),
                source_sha256=hashlib.sha256(Path(__file__).with_name('simulator.py').read_bytes()).hexdigest(),
                limitations=['Synthetic workload; ranges are stress scenarios, not empirical confidence bounds.',
                             'Common intent admission/preemption with independently toggled tracking and elasticity.',
                             'Cell 10 is a demand-aware rigid-gang baseline; no Kubernetes/Slurm binary executed.',
                             'Interaction is a difference in capacity fractions, not an independent multiplicative factor.'],
                summaries=summaries,runs=rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path('results/sensitivity.json'))
    args=parser.parse_args()
    result=experiment()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result['summaries'],indent=2))
