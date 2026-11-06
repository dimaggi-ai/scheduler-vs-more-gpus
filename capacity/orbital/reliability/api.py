"""Bounded stateless agent seam; no automatic action or promotion."""
from ..contracts import canonical,digest
from .contracts import bounded,fields,text,validate,encoded,Refuse,MAX_BYTES,MAX_OUTPUT
from . import evaluate_checkpoint_policy,compare_checkpoint_policies,source_digest,_pin

def dispatch(request):
    ident=input_hash=source=None
    try:
        if type(request) is dict:
            try:ident=text(request.get('id'),128)
            except Refuse:pass
        bounded(request);fields(request,'schema id tool input');text(request['id'],128)
        if request['schema']!='capacity-orbital/checkpoint-tool-v1':raise Refuse('UNSUPPORTED_SCHEMA','unsupported tool schema')
        tool=request['tool'];data=request['input']
        if tool=='evaluate': normalized=encoded(validate(data))
        elif tool=='compare':
            if type(data) is not dict:raise Refuse('INVALID_ARGUMENT','compare object required')
            _pin(data.get('expected_baseline_sha256'))
            fields(data,'baseline candidate expected_baseline_sha256')
            normalized=dict(baseline=encoded(validate(data['baseline'])),candidate=encoded(validate(data['candidate'])),expected_baseline_sha256=data['expected_baseline_sha256'])
        else:raise Refuse('UNKNOWN_TOOL','tools: evaluate, compare')
        envelope=dict(request,input=normalized)
        if len(canonical(envelope).encode())>MAX_BYTES:raise Refuse('BUDGET_EXCEEDED','normalized request byte budget')
        input_hash=digest(envelope)
        try:source=source_digest()
        except OSError:raise Refuse('SOURCE_UNAVAILABLE','source files unavailable') from None
        result=evaluate_checkpoint_policy(data) if tool=='evaluate' else compare_checkpoint_policies(data['baseline'],data['candidate'],data['expected_baseline_sha256'])
        response=dict(schema='capacity-orbital/checkpoint-tool-result-v1',id=ident,status='ok',input_sha256=input_hash,source_sha256=source,result=result,execution_performed=False)
        if len(canonical(response).encode())>MAX_OUTPUT:raise Refuse('BUDGET_EXCEEDED','response byte budget')
        return response
    except Refuse as exc:
        return dict(schema='capacity-orbital/checkpoint-tool-result-v1',id=ident,status='refused',input_sha256=input_hash,source_sha256=source,code=exc.code,reason=str(exc),execution_performed=False)
    except RecursionError:
        return dict(schema='capacity-orbital/checkpoint-tool-result-v1',id=ident,status='refused',input_sha256=input_hash,source_sha256=source,code='BUDGET_EXCEEDED',reason='nesting budget',execution_performed=False)
    except OSError:
        return dict(schema='capacity-orbital/checkpoint-tool-result-v1',id=ident,status='refused',input_sha256=input_hash,source_sha256=source,code='SOURCE_UNAVAILABLE',reason='source files unavailable',execution_performed=False)
