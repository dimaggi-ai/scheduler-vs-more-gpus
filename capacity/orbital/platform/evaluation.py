import math
from ..contracts import digest,fields,canonical
from .contracts import ROUTES,validate
from .mission import plan_mission,source_digest

from .semantic import semantic

def evaluate_policies(suite,baseline,candidates):
    fields(suite,'schema train heldout','mission suite')
    if suite['schema']!='capacity-orbital/mission-suite-v1':raise ValueError('unsupported suite')
    if baseline not in ROUTES or not isinstance(candidates,list) or not 1<=len(candidates)<=3 or any(c not in ROUTES for c in candidates) or len(set(candidates))!=len(candidates):raise ValueError('registered route policies only')
    seen=set();total=0
    for split in ('train','heldout'):
        if not isinstance(suite[split],list) or not suite[split]:raise ValueError('train and heldout required')
        total+=len(suite[split])
        if total>6:raise ValueError('at most6 missions')
        for m in suite[split]:
            validate(m);fingerprint=digest(semantic(m))
            if fingerprint in seen:raise ValueError('duplicate workload across fixed suite')
            seen.add(fingerprint)
    rows={};policies=list(dict.fromkeys([baseline]+candidates))
    for split in ('train','heldout'):
        rows[split]={}
        for p in policies:
            results=[plan_mission(m,p) for m in suite[split]]
            total_cost=math.fsum(r['cost']['partial_operating_usd'] for r in results if r['admissible'])
            if not math.isfinite(total_cost):raise ValueError('nonfinite suite cost')
            rows[split][p]=dict(score=[sum(not r['admissible'] for r in results),total_cost],admissible=[r['admissible'] for r in results],receipts=[r['receipt_id'] for r in results])
    eligible=[p for p in policies if all(not a or b for a,b in zip(rows['train'][baseline]['admissible'],rows['train'][p]['admissible']))]
    rejected=[p for p in policies if p not in eligible]
    selected=min(eligible,key=lambda p:(rows['train'][p]['score'],policies.index(p)))
    held=rows['heldout'];improved=held[selected]['score']<held[baseline]['score'] and all(not a or b for a,b in zip(held[baseline]['admissible'],held[selected]['admissible']))
    return dict(schema='capacity-orbital/mission-evaluation-v1',evaluator='coupled-mission-v1',static_evaluator='task107 remains separate and unchanged',source_sha256=source_digest(),suite_sha256=digest(suite),baseline=baseline,candidates=candidates,rejected_training_regressions=rejected,selected_on_train=selected,recommendation=selected if improved and selected!=baseline else None,results=rows,objective='whole-mission failures then partial operating USD',stop_reason='fixed candidate budget exhausted',promoted=False,execution_performed=False)
