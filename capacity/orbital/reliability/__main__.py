import argparse
from .api import dispatch
from .contracts import parse,Refuse,MAX_BYTES
from ..contracts import canonical
from ..output import publish

def refusal(code,reason,ident=None,input_hash=None,source_hash=None):
    print(canonical(dict(schema='capacity-orbital/checkpoint-tool-result-v1',status='refused',id=ident,input_sha256=input_hash,source_sha256=source_hash,code=code,reason=reason,execution_performed=False)))
    return 2

def main(argv=None):
    p=argparse.ArgumentParser(description='Exact synthetic payload checkpoint replay')
    p.add_argument('--request',required=True);p.add_argument('--output');args=p.parse_args(argv)
    try:
        with open(args.request,'rb') as f:raw_input=f.read(MAX_BYTES+1)
    except OSError:
        return refusal('OUTPUT_ERROR','input unreadable; use readable input')
    try:request=parse(raw_input,check_bounds=False)
    except Refuse as exc:return refusal(exc.code,str(exc))
    # Dispatch validates identity before bounded traversal; programmer failures propagate.
    result=dispatch(request);raw=canonical(result)+'\n'
    try:publish([(args.output,raw)],args.request)
    except (OSError,ValueError):
        return refusal('OUTPUT_ERROR','output publication failed; choose a fresh writable path',result['id'],result['input_sha256'],result['source_sha256'])
    if not args.output:print(raw,end='')
    return 2 if result['status']=='refused' else 0
if __name__=='__main__':raise SystemExit(main())
