"""Versioned agent-callable diligence tools, with no execution authority."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from ..contracts import canonical,digest
from .contracts import Refuse,fields,text,parse,MAX_BYTES
from .lifecycle import lifecycle_cost
from .claims import check_claim

REQUEST='capacity-orbital/diligence-request-v1'


def source_manifest():
    root=Path(__file__).resolve().parent
    files=list(root.glob('*.py'))+[root.parent/'contracts.py',root.parent/'output.py']
    return {str(p.relative_to(root.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def tool_manifest():
    return dict(schema='capacity-orbital/diligence-tools-v1',request_schema=REQUEST,
                tools={'lifecycle_cost':'capacity-orbital/lifecycle-v1','check_claim':'capacity-orbital/claim-v1'},
                claim_models=['power','battery','link','thermal'],
                limits=dict(request_bytes=MAX_BYTES,cash_flows=1000,cohorts=200,horizon_years=100),
                authority='screening only; never execution authorization or financial recommendation')


def dispatch(request):
    ident=input_hash=source_hash=None
    try:
        source_hash=digest(source_manifest())
    except OSError:
        return _response(None,None,None,'refused','SOURCE_UNAVAILABLE','source could not be read',None)
    try:
        encoded=canonical(request).encode()
        if len(encoded)>MAX_BYTES:raise Refuse('BUDGET_EXCEEDED','request byte limit exceeded')
        obj=json.loads(encoded)
        input_hash=digest(obj)
        fields(obj,'schema id tool input','request')
        ident=text(obj['id'],'id')
        if obj['schema']!=REQUEST:raise Refuse('UNSUPPORTED_SCHEMA','unsupported request schema')
        if obj['tool']=='lifecycle_cost':result=lifecycle_cost(obj['input'])
        elif obj['tool']=='check_claim':result=check_claim(obj['input'])
        else:raise Refuse('UNKNOWN_TOOL','tool is not in the fixed registry')
        return _response(ident,input_hash,source_hash,'screened',result['reason_code'],'synthetic assumption-bound result',result)
    except OverflowError:
        return _response(ident,input_hash,source_hash,'refused','ARITHMETIC_OVERFLOW','derived arithmetic overflows',None)
    except (ValueError,KeyError,TypeError,RecursionError) as exc:
        return _response(ident,input_hash,source_hash,'refused',getattr(exc,'code','INVALID_ARGUMENT'),str(exc),None)


def dispatch_json(raw):
    try:return dispatch(parse(raw))
    except (ValueError,TypeError,UnicodeError,RecursionError) as exc:
        return _response(None,None,None,'refused',getattr(exc,'code','INVALID_ARGUMENT'),str(exc),None)


def _response(ident,inputs,source,status,code,reason,result):
    obj=dict(schema='capacity-orbital/diligence-response-v1',request_id=ident,input_sha256=inputs,source_sha256=source,
             status=status,reason_code=code,reason=reason,result=result,
             classification='synthetic sensitivity/screening; not investment advice or physical verification',
             authority_disposition='no_authorization_granted',execution_performed=False,promoted=False)
    obj['outcome_sha256']=digest(obj)
    return obj
