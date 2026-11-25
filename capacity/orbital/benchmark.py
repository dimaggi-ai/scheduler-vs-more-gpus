"""Reproducible bounded scaling probe; measurements are not flight or production claims."""
import json
import platform
import time
import tracemalloc
from .__main__ import source_digest
from .adapters import synthetic
from .evidence_record import BENCHMARK_SCHEMA, evidence_labels
from .planner import compare

SIZES = ((10,'continuous'),(100,'continuous'),(1000,'continuous'),(10000,'continuous'),(10,'intermittent'),(100,'intermittent'),(1000,'intermittent'),(10000,'intermittent'))


def run(sizes=SIZES):
    source=source_digest()
    measurements=[]
    for jobs,adapter in sizes:
        scenario=synthetic(adapter,jobs)
        tracemalloc.start()
        start=time.perf_counter()
        result=compare(scenario,source_sha256=source)
        elapsed=time.perf_counter()-start
        _,peak=tracemalloc.get_traced_memory()
        tracemalloc.stop()
        measurements.append(dict(jobs=jobs,contacts=len(scenario['contacts']),routes=3,seconds=round(elapsed,6),peak_bytes=peak,
                                 planned=[r['summary']['planned'] for r in result['comparisons']],
                                 adapter=adapter,input_sha256=result['input_sha256']))
    return dict(schema=BENCHMARK_SCHEMA,
                classification='single-run timing and traced Python peak memory on one host; not a production or flight benchmark',
                **evidence_labels(source),
                python=platform.python_version(),platform=platform.platform(),
                scope='Two fixed compute nodes; continuous and intermittent contacts. Serial greedy planner, not distributed execution.',
                measurements=measurements)


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
