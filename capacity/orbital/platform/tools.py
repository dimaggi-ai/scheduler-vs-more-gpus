"""Fixed planning-tool registry, no callbacks, dynamic code or actual execution."""
from copy import deepcopy
from ..contracts import fields,digest,canonical,text
from .mission import compare_mission,source_digest
from .verify import verify_mission
from .evaluation import evaluate_policies
from .feedback import assess_feedback

def dispatch(request):
    try:
        if len(canonical(request).encode())>4000000:raise ValueError('request exceeds4MB')
        fields(request,'schema id tool arguments','mission request')
        if request['schema']!='capacity-orbital/mission-tool-v1':raise ValueError('unsupported tool schema')
        text(request['id'],'request ID')
        args=request['arguments']
        if request['tool']=='compare':
            fields(args,'mission','compare args');result=compare_mission(args['mission'])
        elif request['tool']=='verify':
            fields(args,'mission report','verify args');result=verify_mission(args['mission'],args['report'])
        elif request['tool']=='evaluate':
            fields(args,'suite baseline candidates','evaluate args');result=evaluate_policies(args['suite'],args['baseline'],args['candidates'])
        elif request['tool']=='feedback':
            fields(args,'suite','feedback args');result=assess_feedback(args['suite'])
        else:raise ValueError('unknown fixed tool')
        response=dict(schema='capacity-orbital/mission-tool-result-v1',request_id=request['id'],request_sha256=digest(request),source_sha256=source_digest(),status='evaluated',result=result,execution_performed=False,promoted=False)
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError) as exc:
        response=dict(schema='capacity-orbital/mission-tool-result-v1',status='refused',reason=str(exc),execution_performed=False,promoted=False)
    response['receipt_id']=digest(response)
    if len(canonical(response).encode())>8000000:raise ValueError('response exceeds8MB')
    return response
