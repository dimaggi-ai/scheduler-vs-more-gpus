"""Portable selected-route checkpoint evidence. No execution or authenticity claim."""
import hashlib
import json
from pathlib import Path
from ..contracts import digest
from .contracts import Refuse,fields,raw,parse,wire,text,pin,INNER,REPORT,BUNDLE

SCHEMA='capacity-orbital/checkpoint-evidence-bundle-v1'
CLASSIFICATION='selected-route synthetic checkpoint evidence; consistency not authenticity or acceptance'
CHECKPOINT_SOURCE='78bc6436df27b94a15c1b93a2a296f183f32449be091e9bdcf00dd2d4ac2b958'

def required_sources():
    root=Path(__file__).resolve().parents[1];capacity=root.parent
    try:
        def inventory(path):
            data=path.read_bytes()
            if len(data)>100_000:raise Refuse('SOURCE_UNAVAILABLE','source inventory byte budget')
            return json.loads(data)
        own=inventory(Path(__file__).resolve().parent/'source_inventory.json')
        parent=inventory(root/'platform/checkpoint/source_inventory.json')
        for names in (own,parent):
            if type(names) is not list or not names or len(names)>1000 or any(type(p) is not str or not p or '\x00' in p or Path(p).is_absolute() or '..' in Path(p).parts for p in names):raise Refuse('SOURCE_UNAVAILABLE','invalid source inventory')
        for name in own+parent:name.encode('utf-8')
        return capacity,{capacity/p for p in own+parent}
    except (OSError,UnicodeError,ValueError,RecursionError):raise Refuse('SOURCE_UNAVAILABLE','required source inventory missing/unreadable') from None

def source_digest():
    capacity,required=required_sources()
    paths=required|set(Path(__file__).resolve().parent.glob('*.py'))|set(Path(__file__).resolve().parent.glob('*.json'))
    try:hashes={str(p.relative_to(capacity)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    except OSError:raise Refuse('SOURCE_UNAVAILABLE','required source missing/unreadable') from None
    from ..platform.checkpoint import source_digest as checkpoint_source
    from ..platform.checkpoint.contracts import Refuse as CRefuse
    try:actual=checkpoint_source()
    except CRefuse as ex:raise Refuse(ex.code,str(ex)) from None
    if actual!=CHECKPOINT_SOURCE:raise Refuse('SOURCE_MISMATCH','checkpoint dependency differs from pinned source')
    return digest(dict(files=hashes,checkpoint_source_sha256=actual))

def plan_request(request_json):
    data=raw(request_json,INNER)
    try:original=data.decode('utf-8')
    except UnicodeError:raise Refuse('INVALID_ARGUMENT','malformed inner UTF-8') from None
    from ..platform.checkpoint.contracts import parse as checkpoint_parse,Refuse as CRefuse
    try:request=checkpoint_parse(data)
    except CRefuse as ex:raise Refuse(ex.code,str(ex)) from None
    fields(request,'schema id tool input');text(request['id'],128)
    if request['schema']!='capacity-orbital/checkpoint-mission-tool-v2':raise Refuse('UNSUPPORTED_SCHEMA','expected checkpoint plan tool schema')
    if request['tool']!='plan':raise Refuse('UNSUPPORTED_TOOL','only selected-route plan requests can be bundled')
    fields(request['input'],'scenario route')
    if request['input']['route'] not in ('ground','onboard','hybrid'):raise Refuse('INVALID_ARGUMENT','unknown selected route')
    return original,request

def export_checkpoint_bundle(request_json):
    data=raw(request_json,INNER)
    source=source_digest();original,request=plan_request(data)
    from ..platform.checkpoint.tools import dispatch
    response=dispatch(request)
    if response['status']!='ok':raise Refuse(response['code'],response['reason'])
    report=response['result'];wire(report,REPORT)
    content=dict(schema=SCHEMA,request_json=original,report=report,scenario_sha256=report['input_sha256'],checkpoint_source_sha256=CHECKPOINT_SOURCE,bundle_source_sha256=source,classification=CLASSIFICATION,execution_performed=False,authenticity_established=False)
    envelope=dict(content=content,sha256=digest(content))
    return dict(bundle_json=wire(envelope,BUNDLE),sha256=envelope['sha256'])

def verify_checkpoint_bundle(envelope_json,expected_sha256=None):
    data=raw(envelope_json,BUNDLE)
    source=source_digest();pin(expected_sha256)
    envelope=parse(data,BUNDLE,canonical_outer=True);fields(envelope,'content sha256')
    content=envelope['content'];fields(content,'schema request_json report scenario_sha256 checkpoint_source_sha256 bundle_source_sha256 classification execution_performed authenticity_established')
    if content['schema']!=SCHEMA:raise Refuse('UNSUPPORTED_SCHEMA','unsupported bundle schema')
    text(content['request_json']);original,request=plan_request(content['request_json']);wire(content['report'],REPORT)
    errors=[];computed=digest(content)
    if envelope['sha256']!=computed:errors.append('CONTENT_HASH')
    if expected_sha256 is not None and expected_sha256!=computed:errors.append('EXPECTED_PIN')
    if content['classification']!=CLASSIFICATION or content['execution_performed'] is not False or content['authenticity_established'] is not False:errors.append('CLASSIFICATION_OR_AUTHORITY')
    if content['bundle_source_sha256']!=source or content['checkpoint_source_sha256']!=CHECKPOINT_SOURCE:errors.append('SOURCE_BINDING')
    report=content['report']
    if type(report) is not dict:errors.append('REPORT_SHAPE')
    else:
        if report.get('input_sha256')!=content['scenario_sha256']:errors.append('SCENARIO_BINDING')
        if report.get('source_sha256')!=CHECKPOINT_SOURCE:errors.append('REPORT_SOURCE')
        if report.get('route')!=request['input']['route']:errors.append('SELECTED_ROUTE')
        from ..platform.checkpoint import verify_checkpoint_mission
        from ..platform.checkpoint.contracts import Refuse as CRefuse
        try:checked=verify_checkpoint_mission(request['input']['scenario'],report)
        except CRefuse as ex:raise Refuse(ex.code,str(ex)) from None
        if not checked['valid']:errors.extend('REPORT_'+e for e in checked['errors'])
    errors=sorted(set(str(e)[:256] for e in errors))[:64]
    return dict(valid=not errors,errors=errors,admissible=report['admissible'] if not errors else None,binding_mode='expected-pin' if expected_sha256 is not None else 'self-consistent',authenticity_established=False,execution_performed=False)
