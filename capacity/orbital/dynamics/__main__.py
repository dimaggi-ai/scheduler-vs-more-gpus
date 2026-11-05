"""CLI boundary for the pure agent-callable dynamics tool."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from ..__main__ import source_digest as parent_source_digest
from ..contracts import digest,fields
from ..output import publish
from .fixtures import demo
from .kernel import evaluate
from .report import render


def read_json(path):
    # Bounded read rather than stat-only: a changing file cannot defeat the cap.
    with open(path, 'rb') as handle:
        data = handle.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('scenario file exceeds 8 MiB limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def source_digest():
    root=Path(__file__).parent
    return digest({'parent_source':parent_source_digest(),
                   'dynamics':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.py'))}})


def main(argv=None):
    parser=argparse.ArgumentParser(description='Offline synthetic battery/thermal proposal evaluator')
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--demo',choices=('nominal','reserve','thermal','corrected'))
    group.add_argument('--scenario',help='JSON bundle with exact scenario and proposal keys')
    parser.add_argument('--output');parser.add_argument('--html');parser.add_argument('--save-scenario')
    args=parser.parse_args(argv)
    try:
        bundle=read_json(args.scenario) if args.scenario else demo(args.demo)
        fields(bundle,'scenario proposal','bundle')
        result=evaluate(bundle['proposal'],bundle['scenario'],source_sha256=source_digest())
        data=json.dumps(result,indent=2,allow_nan=False)+'\n'
        publish([(args.output,data),(args.html,render(result)),(args.save_scenario,json.dumps(bundle,indent=2,allow_nan=False)+'\n')],args.scenario)
        if not args.output:print(data,end='')
        return 0 if result['admissible'] else 3
    except (ValueError,TypeError,KeyError,OSError,OverflowError,RecursionError) as exc:
        print('REFUSE: '+str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
