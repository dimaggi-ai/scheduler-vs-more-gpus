import argparse
import hashlib
import json
from pathlib import Path
import sys
from ..contracts import digest
from ..output import publish
from ..dynamics.__main__ import read_json,source_digest as dynamics_source_digest
from .planner import plan_network
from .fixtures import demo
from .report import render

def source_digest():
    return digest(dict(dependencies=dynamics_source_digest(),network={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))}))

def main(argv=None):
    p=argparse.ArgumentParser(description='Offline synthetic Netcap Orbital planner')
    g=p.add_mutually_exclusive_group(required=True);g.add_argument('--demo',choices=('relay','outage','corrected','contention'));g.add_argument('--scenario')
    p.add_argument('--output');p.add_argument('--html');a=p.parse_args(argv)
    try:
        s=read_json(a.scenario) if a.scenario else demo(a.demo)
        r=plan_network(s,source_sha256=source_digest());data=json.dumps(r,indent=2,allow_nan=False)+'\n'
        publish([(a.output,data),(a.html,render(r))],a.scenario)
        if not a.output:print(data,end='')
        return 3 if any(j['status']=='refused' for j in r['jobs']) else 0
    except (ValueError,TypeError,KeyError,OSError,OverflowError,RecursionError) as exc:
        print('REFUSE: '+str(exc),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
