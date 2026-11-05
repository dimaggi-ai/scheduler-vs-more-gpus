"""Portable synthetic evidence; consistency does not establish authenticity."""
import hashlib,json
from pathlib import Path
from copy import deepcopy
from ..contracts import digest
from ..platform import compare_mission,verify_mission
from ..platform.mission import source_digest as platform_source
MAX_BYTES=8*1024*1024
SCHEMA='capacity-orbital/evidence-bundle-v1'

def bounded(value):
    stack=[(value,0)];count=0
    while stack:
        item,depth=stack.pop();count+=1
        if depth>64 or count>200000:raise ValueError('JSON depth/node budget exceeded')
        if type(item) is dict:
            if any(type(k) is not str for k in item):raise ValueError('non-string object key')
            stack.extend((v,depth+1) for v in item.values())
        elif type(item) is list:stack.extend((v,depth+1) for v in item)
        elif item is not None and type(item) not in (str,int,float,bool):raise ValueError('unsupported JSON type')
    if len(json.dumps(value,allow_nan=False).encode())>MAX_BYTES:raise ValueError('JSON byte budget exceeded')

def source_digest():
    return digest(dict(capacity_package=hashlib.sha256((Path(__file__).resolve().parents[2]/'__init__.py').read_bytes()).hexdigest(),platform=platform_source(),bundle={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))}))

def export_bundle(mission):
    bounded(mission)
    comparison=compare_mission(mission)
    content=dict(schema=SCHEMA,classification='synthetic planning evidence; not execution, authentication or acceptance',mission=deepcopy(mission),comparison=comparison,input_sha256=digest(mission),platform_source_sha256=platform_source(),bundle_source_sha256=source_digest())
    envelope=dict(content=content,sha256=digest(content));bounded(envelope)
    checked=verify_bundle(envelope)
    if not checked['valid']:raise ValueError('export consistency check failed: '+','.join(checked['errors']))
    return envelope

def verify_bundle(bundle,expected_sha256=None):
    try:
        bounded(bundle)
        if type(bundle) is not dict or set(bundle)!={'content','sha256'}:raise ValueError('invalid envelope fields')
        c=bundle['content']
        if type(c) is not dict or set(c)!={'schema','classification','mission','comparison','input_sha256','platform_source_sha256','bundle_source_sha256'}:raise ValueError('invalid content fields')
        if c['schema']!=SCHEMA:raise ValueError('unsupported schema')
        if c['classification']!='synthetic planning evidence; not execution, authentication or acceptance':raise ValueError('classification differs')
        if digest(c)!=bundle['sha256']:raise ValueError('content digest differs')
        if expected_sha256 is not None and expected_sha256!=bundle['sha256']:raise ValueError('external expected digest differs')
        if c['platform_source_sha256']!=platform_source() or c['bundle_source_sha256']!=source_digest():raise ValueError('source binding differs')
        if c['input_sha256']!=digest(c['mission']):raise ValueError('input binding differs')
        comparison=c['comparison']
        if type(comparison) is not dict or type(comparison.get('comparisons')) is not list:raise ValueError('comparison shape differs')
        if len(comparison['comparisons'])!=3 or [r['route'] for r in comparison['comparisons']]!=['ground','onboard','hybrid']:raise ValueError('route coverage differs')
        for report in comparison['comparisons']:
            if not verify_mission(c['mission'],report)['valid']:raise ValueError('report relationship verification failed')
        if digest(comparison)!=digest(compare_mission(c['mission'])):raise ValueError('comparison replay differs')
        return dict(schema='capacity-orbital/bundle-verification-v1',valid=True,errors=[],sha256=bundle['sha256'],admissible_routes=[r['route'] for r in comparison['comparisons'] if r['admissible']],authenticity_verified=False,execution_performed=False)
    except (ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError,RecursionError,RuntimeError,OSError) as exc:
        return dict(schema='capacity-orbital/bundle-verification-v1',valid=False,errors=[str(exc)[:200]],authenticity_verified=False,execution_performed=False)
