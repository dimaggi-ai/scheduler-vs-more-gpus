"""Reproducible bounded scaling probe; measurements are not flight or production claims."""
import json
import platform
import time
import tracemalloc
from .adapters import synthetic
from .planner import compare


def run():
    measurements=[]
    for jobs,adapter in ((10,'continuous'),(100,'continuous'),(1000,'continuous'),(10000,'continuous'),(10,'intermittent'),(100,'intermittent'),(1000,'intermittent'),(10000,'intermittent')):
        scenario=synthetic(adapter,jobs)
        tracemalloc.start()
        start=time.perf_counter()
        result=compare(scenario)
        elapsed=time.perf_counter()-start
        _,peak=tracemalloc.get_traced_memory()
        tracemalloc.stop()
        measurements.append(dict(jobs=jobs,contacts=len(scenario['contacts']),routes=3,seconds=round(elapsed,6),peak_bytes=peak,
                                 planned=[r['summary']['planned'] for r in result['comparisons']]))
    return dict(python=platform.python_version(),platform=platform.platform(),
                scope='Two fixed compute nodes; continuous and intermittent contacts. Serial greedy planner, not distributed execution.',
                measurements=measurements)


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
