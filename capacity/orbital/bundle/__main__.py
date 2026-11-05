"""Offline portable evidence export and verification."""
import argparse,json,sys
from . import export_bundle,verify_bundle,MAX_BYTES
from ..output import publish

def read_json(path):
    with open(path,'rb') as handle:data=handle.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:raise ValueError('input exceeds8MiB')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    return json.loads(data,object_pairs_hook=unique)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    export=sub.add_parser('export');export.add_argument('--mission',required=True);export.add_argument('--output',required=True)
    verify=sub.add_parser('verify');verify.add_argument('--bundle',required=True);verify.add_argument('--expected-sha256')
    args=p.parse_args(argv)
    try:
        if args.command=='export':
            result=export_bundle(read_json(args.mission));publish([(args.output,json.dumps(result,allow_nan=False)+'\n')],args.mission)
            print(json.dumps(dict(status='exported',sha256=result['sha256'],execution_performed=False)));return 0
        result=verify_bundle(read_json(args.bundle),args.expected_sha256);print(json.dumps(result));return 0 if result['valid'] else 2
    except (ValueError,TypeError,KeyError,OSError,OverflowError,RecursionError) as exc:
        print(json.dumps(dict(status='refused',reason=str(exc)[:200],execution_performed=False)));return 2
if __name__=='__main__':raise SystemExit(main())
