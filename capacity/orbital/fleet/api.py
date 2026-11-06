"""Stateless agent boundary; no permissions or baseline mutation."""
from . import evaluate,compare,project_economics,source_digest
from ..contracts import digest
from ..diligence.contracts import fields,Refuse,MAX_BYTES,text
import json

def dispatch(request):
    ident=None;input_hash=None;source=None
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
        text(request['id'],'request id');ident=request['id'];input_hash=digest(request);source=source_digest()
        if request['schema']!='capacity-orbital/fleet-tool-v1':raise Refuse('UNSUPPORTED_SCHEMA','unsupported tool schema')
        tool=request['tool'];data=request['input']
        if tool=='evaluate':result=evaluate(data)
        elif tool=='compare':
            if type(data) is not dict or set(data) not in ({'baseline','candidate'},{'baseline','candidate','expected_baseline_sha256'}):raise Refuse('INVALID_ARGUMENT','comparison exact fields required')
            if 'expected_baseline_sha256' in data and data['expected_baseline_sha256'] is None:raise Refuse('BASELINE_BINDING','explicit baseline digest must not be null')
            result=compare(data['baseline'],data['candidate'],data.get('expected_baseline_sha256'))
        elif tool=='economics':fields(data,'scenario template','economics');result=project_economics(data['scenario'],data['template'])
        else:raise Refuse('UNKNOWN_TOOL','tools: evaluate, compare, economics')
        return dict(schema='capacity-orbital/fleet-tool-result-v1',id=request['id'],status='completed',input_sha256=input_hash,source_sha256=source,result=result,execution_performed=False)
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,OSError) as exc:
        return dict(schema='capacity-orbital/fleet-tool-result-v1',status='refused',id=ident,input_sha256=input_hash,source_sha256=source,code=getattr(exc,'code','INVALID_ARGUMENT'),reason=str(exc)[:200],execution_performed=False)
