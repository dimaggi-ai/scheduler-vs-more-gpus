"""CLI IO only; reuse the existing non-overwriting output publisher."""
import argparse
import json
from pathlib import Path
import sys
from ..output import publish
from .api import dispatch_json,tool_manifest
from .contracts import MAX_BYTES
from .report import html_report


def main(argv=None):
    p=argparse.ArgumentParser(description='Capacity Orbital synthetic diligence tools')
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--request');group.add_argument('--manifest',action='store_true')
    p.add_argument('--output');p.add_argument('--html')
    args=p.parse_args(argv)
    try:
        if args.manifest:result=tool_manifest()
        else:
            with Path(args.request).open('rb') as f:result=dispatch_json(f.read(MAX_BYTES+1))
        data=json.dumps(result,indent=2,allow_nan=False)+'\n'
        publish([(args.output,data),(args.html,html_report(result))],args.request)
        if not args.output:print(data,end='')
        return 2 if result.get('status')=='refused' else 0
    except (OSError,ValueError,TypeError) as exc:
        print('REFUSE: '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
