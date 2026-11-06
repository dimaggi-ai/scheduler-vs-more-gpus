import argparse
from .api import dispatch
from .contracts import parse,Refuse,MAX_BYTES
from ..contracts import canonical
from ..output import publish

def main(argv=None):
    p=argparse.ArgumentParser(description='Exact synthetic payload checkpoint replay')
    p.add_argument('--request',required=True);p.add_argument('--output');args=p.parse_args(argv)
    try:
        with open(args.request,'rb') as f:request=parse(f.read(MAX_BYTES+1))
        result=dispatch(request);raw=canonical(result)+'\n'
        publish([(args.output,raw)],args.request)
        if not args.output:print(raw,end='')
        return 2 if result['status']=='refused' else 0
    except Refuse as exc:
        print(canonical(dict(schema='capacity-orbital/checkpoint-tool-result-v1',status='refused',id=None,input_sha256=None,source_sha256=None,code=exc.code,reason=str(exc),execution_performed=False)));return 2
    except (OSError,ValueError):
        print(canonical(dict(schema='capacity-orbital/checkpoint-tool-result-v1',status='refused',id=None,input_sha256=None,source_sha256=None,code='OUTPUT_ERROR',reason='input/output failed; use readable input and fresh writable output',execution_performed=False)));return 2
if __name__=='__main__':raise SystemExit(main())
