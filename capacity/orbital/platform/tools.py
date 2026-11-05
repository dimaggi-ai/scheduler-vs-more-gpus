"""Stateless deterministic planning registry; no callbacks or actual execution."""
from ..contracts import fields,digest,canonical,text
from .mission import compare_mission,source_digest
from .verify import verify_mission
from .evaluation import evaluate_policies
from .feedback import assess_feedback

class Refusal(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def manifest():
    return dict(schema='capacity-orbital/mission-tool-manifest-v1',request_schema='capacity-orbital/mission-tool-v1',request_schema_file='request.schema.json',tools={'compare':['mission'],'verify':['mission','report'],'evaluate':['suite','baseline','candidates'],'feedback':['suite']},request_bytes=4000000,response_bytes=8000000,refusal_codes=['INVALID_ARGUMENT','UNSUPPORTED_SCHEMA','UNKNOWN_TOOL','BUDGET_EXCEEDED','SOURCE_UNAVAILABLE'],semantics='stateless deterministic recomputation; IDs correlate requests but have no persisted uniqueness/conflict protection',source_sha256=source_digest(),authority='synthetic planning only; no permissions provisioned',execution_performed=False,promoted=False)


def dispatch(request):
    request_id=request_hash=source=None
    try:
        if len(canonical(request).encode())>4000000:raise Refusal('BUDGET_EXCEEDED','request exceeds4MB')
        fields(request,'schema id tool arguments','mission request')
        text(request['id'],'request ID');request_id=request['id'];request_hash=digest(request)
        if request['schema']!='capacity-orbital/mission-tool-v1':raise Refusal('UNSUPPORTED_SCHEMA','unsupported tool schema')
        source=source_digest();args=request['arguments']
        if request['tool']=='compare':
            fields(args,'mission','compare args');result=compare_mission(args['mission'])
        elif request['tool']=='verify':
            fields(args,'mission report','verify args');result=verify_mission(args['mission'],args['report'])
        elif request['tool']=='evaluate':
            fields(args,'suite baseline candidates','evaluate args');result=evaluate_policies(args['suite'],args['baseline'],args['candidates'])
        elif request['tool']=='feedback':
            fields(args,'suite','feedback args');result=assess_feedback(args['suite'])
        else:raise Refusal('UNKNOWN_TOOL','unknown fixed tool')
        response=dict(schema='capacity-orbital/mission-tool-result-v1',request_id=request_id,request_sha256=request_hash,source_sha256=source,status='evaluated',code='EVALUATED',result=result,execution_performed=False,promoted=False)
        if len(canonical(response).encode())+100>8000000:raise Refusal('BUDGET_EXCEEDED','response exceeds8MB')
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,OSError) as exc:
        code='SOURCE_UNAVAILABLE' if isinstance(exc,OSError) else getattr(exc,'code','INVALID_ARGUMENT')
        if 'budget' in str(exc).lower() or 'exceeds' in str(exc).lower() and 'MB' in str(exc):code='BUDGET_EXCEEDED'
        response=dict(schema='capacity-orbital/mission-tool-result-v1',request_id=request_id,request_sha256=request_hash,source_sha256=source,status='refused',code=code,reason=str(exc)[:1000],execution_performed=False,promoted=False)
    response['receipt_id']=digest(response)
    return response
