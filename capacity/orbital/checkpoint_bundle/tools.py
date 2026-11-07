"""Bounded path-free stateless agent tools."""
from .contracts import Refuse,fields,text,bounded,wire,parse,raw,TOOL
from . import export_checkpoint_bundle,verify_checkpoint_bundle,source_digest
SCHEMA='capacity-orbital/checkpoint-bundle-tool-result-v1'

def refusal(code,reason,ident=None):
    return dict(schema=SCHEMA,id=ident,status='refused',code=code,reason=str(reason)[:512],execution_performed=False)

def dispatch(request):
    ident=None
    try:
        if type(request) is dict:
            try:ident=text(request.get('id'),128)
            except Refuse:pass
        bounded(request);wire(request,TOOL);fields(request,'schema id tool input');text(request['id'],128)
        if request['schema']!='capacity-orbital/checkpoint-bundle-tool-v1':raise Refuse('UNSUPPORTED_SCHEMA','unsupported tool schema')
        data=request['input']
        if request['tool']=='export':
            fields(data,'request_json');text(data['request_json']);result=export_checkpoint_bundle(data['request_json'])
        elif request['tool']=='verify':
            fields(data,'bundle_json expected_sha256');text(data['bundle_json']);result=verify_checkpoint_bundle(data['bundle_json'],data['expected_sha256'])
        else:raise Refuse('UNSUPPORTED_TOOL','tools: export, verify')
        response=dict(schema=SCHEMA,id=ident,status='ok',result=result,execution_performed=False)
        wire(response,TOOL);return response
    except Refuse as ex:return refusal(ex.code,str(ex),ident)

def dispatch_json(request_json):
    try:
        data=raw(request_json,TOOL)
        source_digest()
        return dispatch(parse(data,TOOL))
    except Refuse as ex:return refusal(ex.code,str(ex))
