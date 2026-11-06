import argparse,json
from .api import dispatch
from ..diligence.contracts import parse,MAX_BYTES
from ..output import publish

def main(argv=None):
    p=argparse.ArgumentParser(description='Offline synthetic fleet survival sensitivity');p.add_argument('--request',required=True);p.add_argument('--output');args=p.parse_args(argv)
    try:
        with open(args.request,'rb') as f:request=parse(f.read(MAX_BYTES+1))
        result=dispatch(request);raw=json.dumps(result,allow_nan=False)+'\n'
        publish([(args.output,raw)],args.request)
        if not args.output:print(raw,end='')
        return 0 if result['status']=='completed' else 2
    except (ValueError,TypeError,OSError,OverflowError,RecursionError) as exc:
        print(json.dumps(dict(status='refused',code=getattr(exc,'code','INVALID_ARGUMENT'),reason=str(exc)[:200],execution_performed=False)));return 2
if __name__=='__main__':raise SystemExit(main())
