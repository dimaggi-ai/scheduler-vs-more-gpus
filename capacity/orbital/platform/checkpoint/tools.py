"""Stateless agent boundary. Refused requests do not execute or promote."""
from ...contracts import digest
from .contracts import (Refuse,fields,text,bound,normalize,enc,view,size,
                        MAX_INPUT,MAX_VERIFY,MAX_REPORT,declaration_bytes)
from . import plan_checkpoint_mission,compare_checkpoint_missions,verify_checkpoint_mission,source_digest

def refusal(code,reason,ident=None,input_hash=None,source=None):
    return dict(schema='capacity-orbital/checkpoint-mission-tool-result-v2',id=ident,status='refused',code=code,reason=reason,input_sha256=input_hash,source_sha256=source,execution_performed=False)

def dispatch(request):
    ident=ih=source=None
    try:
        if type(request) is dict:
            try:ident=text(request.get('id'),128)
            except Refuse:pass
        verify=type(request) is dict and request.get('tool')=='verify'
        if verify and type(request.get('input')) is dict and 'scenario' in request['input']:
            bound(request['input']['scenario']);declaration_bytes(request['input']['scenario'])
        bound(request,verify=verify);fields(request,'schema id tool input');text(request['id'],128)
        if request['schema']!='capacity-orbital/checkpoint-mission-tool-v2':raise Refuse('UNSUPPORTED_SCHEMA','unsupported tool schema')
        tool=request['tool'];data=request['input']
        if tool=='plan':fields(data,'scenario route')
        elif tool=='compare':fields(data,'baseline candidate route expected_baseline_sha256')
        elif tool=='verify':fields(data,'scenario report')
        else:raise Refuse('UNKNOWN_TOOL','tools: plan, compare, verify')
        # The report carries ordinary parent float JSON, not exact declaration tokens.
        if verify:
            bound(data['scenario']);declaration_bytes(data['scenario'])
        normalized=enc(normalize({k:v for k,v in request.items() if k!='input'}))
        if verify:
            bound(data['scenario'])
            scenario_view=enc(normalize(data['scenario']));size(scenario_view,MAX_INPUT,'verify scenario')
            from .verify import prepare_report
            report_view=prepare_report(data['report'])
            if report_view is None:
                source=source_digest()
                return dict(schema='capacity-orbital/checkpoint-mission-tool-result-v2',id=ident,status='ok',input_sha256=None,source_sha256=source,result=dict(valid=False,errors=['INVALID_EVIDENCE'],source_sha256=source,execution_performed=False),execution_performed=False)
            normalized['input']=dict(scenario=scenario_view,report=report_view)
        else:normalized['input']=enc(normalize(data))
        size(normalized,MAX_VERIFY if verify else MAX_INPUT,'normalized request');ih=digest(normalized);source=source_digest()
        if tool=='plan':result=plan_checkpoint_mission(data['scenario'],data['route'])
        elif tool=='compare':result=compare_checkpoint_missions(data['baseline'],data['candidate'],data['route'],data['expected_baseline_sha256'])
        else:result=verify_checkpoint_mission(data['scenario'],data['report'])
        response=dict(schema='capacity-orbital/checkpoint-mission-tool-result-v2',id=ident,status='ok',input_sha256=ih,source_sha256=source,result=result,execution_performed=False)
        size(response,MAX_VERIFY if verify else MAX_REPORT,'output');return response
    except Refuse as ex:return refusal(ex.code,str(ex),ident,ih,source)
    except UnicodeError:return refusal('INVALID_ARGUMENT','surrogate text',ident,ih,source)
    except RecursionError:return refusal('BUDGET_EXCEEDED','nesting budget',ident,ih,source)
    except OSError:return refusal('SOURCE_UNAVAILABLE','required source unavailable',ident,ih,source)
