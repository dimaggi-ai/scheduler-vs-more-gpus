"""Offline JSON transport with no-overwrite publication."""
import argparse
from pathlib import Path
from ...contracts import canonical
from ...output import publish
from .contracts import parse,Refuse,MAX_VERIFY
from .tools import dispatch,refusal

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--output');args=parser.parse_args()
    try:
        with open(args.request,'rb') as f:raw=f.read(MAX_VERIFY+1)
        request=parse(raw);result=dispatch(request)
    except Refuse as ex:result=refusal(ex.code,str(ex),getattr(ex,'request_id',None))
    except OSError:result=refusal('IO_ERROR','request could not be read')
    data=canonical(result)+'\n'
    if args.output and result['status']=='ok':
        try:publish([(Path(args.output),data)],input_path=args.request)
        except (OSError,ValueError):
            result=refusal('IO_ERROR','fresh output could not be published',result['id'],result['input_sha256'],result['source_sha256']);data=canonical(result)+'\n'
    print(data,end='');return 0 if result['status']=='ok' else 2
if __name__=='__main__':raise SystemExit(main())
