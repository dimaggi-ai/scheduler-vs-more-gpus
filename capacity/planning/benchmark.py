"""Bounded single-process measurements; no production-scale inference.

Run: python -m capacity.planning.benchmark > benchmark.json
"""
import json
import resource
import sys
import time
from .model import observe, build_plan, actual_artifact, provenance
from .ledger import Ledger


def main():
    results=[]
    for days in (7,30,90):
        cfg={'horizon_days':days,'gpus':1024,'failures':True,'inf_surges':True,'power_envelope':True}
        start=time.perf_counter()
        history=observe({**cfg,'horizon_days':3})
        plan=build_plan(cfg,history,72)
        actual=actual_artifact(plan)
        replay_seconds=time.perf_counter()-start
        with Ledger() as ledger:
            start=time.perf_counter();ledger.ingest(plan,actual)
            ingest_seconds=time.perf_counter()-start
            start=time.perf_counter();report=ledger.report(actual['actual_id'])
            query_seconds=time.perf_counter()-start
        results.append({'simulation_days':days,'future_hourly_records':len(actual['rows']),
                        'replay_seconds':replay_seconds,'ingest_seconds':ingest_seconds,
                        'checked_report_seconds':query_seconds,'status':report['status']})
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps({'evidence_kind':'local-benchmark','provenance':provenance(),'results':results,
                      'process_peak_rss_bytes':peak if sys.platform=='darwin' else peak*1024,
                      'limits':'Single process and one trial per size; includes warm-up. No distributed scaling claim.'},indent=2))


if __name__=='__main__':main()
