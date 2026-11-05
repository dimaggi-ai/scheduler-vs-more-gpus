"""Stateless agent boundary; no permissions or baseline mutation."""
from . import evaluate,compare,project_economics
from ..diligence.contracts import fields,Refuse,parse,MAX_BYTES
import json

def dispatch(request):
    try:
        # Iterative traversal bounds caller objects before JSON encoding.
        stack=[(request,0)];count=0
        while stack:
            value,depth=stack.pop();count+=1
            if depth>32 or count>50000:raise Refuse('BUDGET_EXCEEDED','request depth/node limit')
            if type(value) is dict:stack.extend((v,depth+1) for v in value.values())
            elif type(value) is list:stack.extend((v,depth+1) for v in value)
        if len(json.dumps(request,allow_nan=False).encode())>MAX_BYTES:raise Refuse('BUDGET_EXCEEDED','request byte limit')
        fields(request,'schema id tool input','request')
        if request['schema']!='capacity-orbital/fleet-tool-v1':raise Refuse('UNSUPPORTED_SCHEMA','unsupported tool schema')
        from ..diligence.contracts import text
        text(request['id'],'request id');tool=request['tool'];data=request['input']
        if tool=='evaluate':result=evaluate(data)
        elif tool=='compare':fields(data,'baseline candidate','comparison');result=compare(data['baseline'],data['candidate'])
        elif tool=='economics':fields(data,'scenario template','economics');result=project_economics(data['scenario'],data['template'])
        else:raise Refuse('UNKNOWN_TOOL','tools: evaluate, compare, economics')
        return dict(schema='capacity-orbital/fleet-tool-result-v1',id=request['id'],status='completed',result=result,execution_performed=False)
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,OSError) as exc:
        return dict(schema='capacity-orbital/fleet-tool-result-v1',status='refused',code=getattr(exc,'code','INVALID_ARGUMENT'),reason=str(exc)[:200],execution_performed=False)
