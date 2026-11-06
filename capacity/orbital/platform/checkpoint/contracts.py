"""Bounded declarations and separate exact/parent views for mission v2."""
import json
import math
import re
from decimal import Decimal, localcontext
from fractions import Fraction as F
from copy import deepcopy
from ...contracts import canonical, digest
from ...reliability.contracts import Refuse, fields, text, number as replay_number
from ..contracts import validate as parent_validate, ROUTES
from ...diligence.contracts import Refuse as DiligenceRefuse

MAX_INPUT=1_000_000
MAX_REPORT=8_000_000
MAX_VERIFY=10_000_000
GRID=F(1,4096)
NUMBER=re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z')
class Token(str): pass

def bound(value, *, verify=False):
    stack=[(value,0)];count=0;limit=1_000_000 if verify else 50_000
    while stack:
        v,d=stack.pop();count+=1
        if count>limit or d>(64 if verify else 32):raise Refuse('BUDGET_EXCEEDED','depth/node budget')
        if type(v) is dict:
            if len(v)>limit:raise Refuse('BUDGET_EXCEEDED','object budget')
            for k,x in v.items():
                if type(k) is not str:raise Refuse('INVALID_ARGUMENT','string keys required')
                k.encode('utf-8');stack.append((x,d+1))
        elif type(v) is list:
            if len(v)>limit:raise Refuse('BUDGET_EXCEEDED','array budget')
            stack.extend((x,d+1) for x in v)
        elif type(v) is str:v.encode('utf-8')
        elif v is not None and type(v) not in (bool,int,float,Decimal,Token):raise Refuse('INVALID_ARGUMENT','unsupported declaration type')

def token(v):
    if type(v) is int:
        if v.bit_length()>2552:raise Refuse('BUDGET_EXCEEDED','integer coefficient budget')
        s=str(v)
    elif type(v) is Decimal:
        if not v.is_finite():raise Refuse('INVALID_ARGUMENT','finite decimal required')
        t=v.as_tuple()
        if len(t.digits)>768 or abs(t.exponent)>1168:raise Refuse('BUDGET_EXCEEDED','decimal tuple budget')
        s=str(v)
    elif type(v) is float:
        if not math.isfinite(v):raise Refuse('INVALID_ARGUMENT','finite number required')
        s=repr(v)
    elif type(v) is Token:s=str(v)
    else:raise Refuse('INVALID_ARGUMENT','numeric declaration required')
    if len(s)>768:raise Refuse('BUDGET_EXCEEDED','numeric token length')
    if not NUMBER.fullmatch(s):raise Refuse('INVALID_ARGUMENT','JSON decimal grammar required')
    mant,*exp=re.split('[eE]',s)
    if exp and (len(exp[0].lstrip('+-'))>3 or abs(int(exp[0]))>400):raise Refuse('BUDGET_EXCEEDED','numeric exponent budget')
    if len(mant.lstrip('-').replace('.','').lstrip('0') or '0')>768:raise Refuse('BUDGET_EXCEEDED','coefficient budget')
    return s

def rational(v):
    if abs(v.numerator)>=10**1200 or v.denominator>=10**1200:raise Refuse('BUDGET_EXCEEDED','rational digit budget')
    return v

def exact(v):return rational(F(token(v)))

def enc(v):
    if type(v) is F:return dict(numerator=str(rational(v).numerator),denominator=str(v.denominator))
    if type(v) is dict:return {k:enc(x) for k,x in v.items()}
    if type(v) is list:return [enc(x) for x in v]
    return v

def fraction(v):return F(int(v['numerator']),int(v['denominator']))

def normalize(v):
    if type(v) in (int,float,Decimal,Token):return exact(v)
    if type(v) is dict:return {k:normalize(x) for k,x in v.items()}
    if type(v) is list:return [normalize(x) for x in v]
    return v

def view(v,path='mission'):
    if type(v) in (int,float,Decimal,Token):
        s=token(v);r=F(s)
        integer=type(v) is int or (type(v) is Token and not any(c in s for c in '.eE')) or (type(v) is Decimal and r.denominator==1 and path.endswith('horizon_years'))
        f=r.numerator if integer else float(s)
        if (type(f) is float and not math.isfinite(f)) or (r and f==0):raise Refuse('UNSUPPORTED_NUMERIC_DOMAIN',path+': nonfinite/underflow parent view')
        return f
    if type(v) is dict:return {k:view(x,path+'.'+k) for k,x in v.items()}
    if type(v) is list:return [view(x,path+f'[{i}]') for i,x in enumerate(v)]
    return v

def decimal(r):
    # Input denominator divides a power of ten; temporal derived quantities are dyadic.
    with localcontext() as ctx:
        ctx.prec=2500
        out=Decimal(r.numerator)/Decimal(r.denominator)
    if F(out)!=r:raise Refuse('UNSUPPORTED_NUMERIC_DOMAIN','nonterminating exact decimal')
    return out

def selected(v,path,*,time=False,maximum=31_557_600,positive=False):
    r=v if type(v) is F else exact(v)
    if r<0 or r>maximum or (positive and r==0):raise Refuse('INVALID_ARGUMENT',path+': physical range')
    try: replay_number(decimal(r),maximum=maximum,positive=positive)
    except Refuse as e:
        if e.code=='BUDGET_EXCEEDED':raise Refuse('UNSUPPORTED_NUMERIC_DOMAIN',path+': replay decimal grammar') from None
        raise
    if time and (r/GRID).denominator!=1:raise Refuse('UNSUPPORTED_NUMERIC_DOMAIN',path+': requires declared 1/4096-second grid; correction requires explicit new request')
    f=float(r)
    if not math.isfinite(f) or (r and f==0) or (time and F.from_float(f)!=r):raise Refuse('UNSUPPORTED_NUMERIC_DOMAIN',path+': exact temporal/finite resource bridge')
    return decimal(r)

def size(value,maximum,scope):
    if len(canonical(value).encode('utf-8'))+1>maximum:raise Refuse('BUDGET_EXCEEDED',scope+' serialized byte budget')

def parse(raw):
    if isinstance(raw,str):raw=raw.encode('utf-8')
    if len(raw)>MAX_VERIFY:raise Refuse('BUDGET_EXCEEDED','raw request byte budget')
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise Refuse('INVALID_ARGUMENT','duplicate key')
            d[k]=v
        return d
    def num(s):token(Token(s));return Token(s)
    def bad(_):raise Refuse('INVALID_ARGUMENT','nonfinite constant')
    try:v=json.loads(raw.decode('utf-8'),parse_int=num,parse_float=num,parse_constant=bad,object_pairs_hook=pairs)
    except RecursionError:raise Refuse('BUDGET_EXCEEDED','JSON nesting') from None
    except (UnicodeError,json.JSONDecodeError):raise Refuse('INVALID_ARGUMENT','malformed JSON/UTF-8') from None
    verify=type(v) is dict and v.get('tool')=='verify'
    try:
        if len(raw)>(MAX_VERIFY if verify else MAX_INPUT):raise Refuse('BUDGET_EXCEEDED','raw request byte budget')
        try:bound(v,verify=verify)
        except UnicodeError:raise Refuse('INVALID_ARGUMENT','surrogate text') from None
    except Refuse as ex:
        try:ex.request_id=text(v.get('id'),128) if type(v) is dict else None
        except Refuse:ex.request_id=None
        raise
    return v

def normalized(s):
    n=normalize(s)
    # Adjacent outages are semantically one interval; preserve other ordering.
    for node in n['mission']['network']['nodes'].values():
        rows=[]
        for row in node['unavailable']:
            if rows and rows[-1]['end_s']==row['start_s']:rows[-1]['end_s']=row['end_s']
            else:rows.append(dict(row))
        node['unavailable']=rows
    return n

def validate(s,route):
    try:bound(s)
    except UnicodeError:raise Refuse('INVALID_ARGUMENT','surrogate text') from None
    fields(s,'schema id mission replay');text(s['id'],128)
    if s['schema']!='capacity-orbital/checkpoint-mission-v2':raise Refuse('UNSUPPORTED_SCHEMA','unsupported wrapper schema')
    if route not in ROUTES:raise Refuse('INVALID_ARGUMENT','unknown route')
    m=view(s['mission']);e=normalize(s['mission'])
    try:parent_validate(m)
    except DiligenceRefuse as ex:
        mapping={'BUDGET_EXCEEDED':'BUDGET_EXCEEDED','ARITHMETIC_RESOLUTION':'UNSUPPORTED_NUMERIC_DOMAIN','ARITHMETIC_OVERFLOW':'UNSUPPORTED_NUMERIC_DOMAIN','INVALID_ARGUMENT':'INVALID_ARGUMENT','UNSUPPORTED_SCHEMA':'INVALID_ARGUMENT','UNSUPPORTED_CURRENCY':'INVALID_ARGUMENT','UNSUPPORTED_DATA':'INVALID_ARGUMENT'}
        if ex.code not in mapping:raise
        raise Refuse(mapping[ex.code],'inherited lifecycle '+ex.code+': '+str(ex)) from None
    except ValueError as ex:raise Refuse('INVALID_ARGUMENT','inherited validation: '+str(ex)) from None
    if len(m['jobs'])!=1:raise Refuse('UNSUPPORTED_SCOPE','exactly one mission job required')
    fields(s['replay'],'origin destination')
    for role,node in (('origin',m['origin']),('destination',m['destination'])):
        r=s['replay'][role];fields(r,'policy power_kw heat_w provenance')
        fields(r['policy'],'version checkpoint_every_work_s checkpoint_duration_s restart_duration_s');text(r['policy']['version'],128)
        for k,v in r['policy'].items():
            if k!='version' and not (k=='checkpoint_every_work_s' and v is None):selected(v,'replay.'+role+'.policy.'+k,positive=True)
        fields(r['provenance'],'kind source licence generated_on')
        if r['provenance']['kind']!='synthetic':raise Refuse('INVALID_ARGUMENT','synthetic replay required')
        for x in r['provenance'].values():text(x)
        for name in ('power_kw','heat_w'):
            fields(r[name],'productive checkpoint restart down')
            for state,v in r[name].items():selected(v,f'replay.{role}.{name}.{state}',maximum=1e9 if name=='power_kw' else 1e12)
            if exact(r[name]['productive'])!=e['compute'][node][name] or float(exact(r[name]['productive']))!=m['compute'][node][name]:raise Refuse('INVALID_ARGUMENT','productive declaration differs from mission '+name)
        for p in m['dynamics']['nodes'][node]['profiles']:
            if p['background_kw'] or p['background_heat_w']:raise Refuse('UNSUPPORTED_SCOPE','compute-node backgrounds must be zero')
    size(enc(normalized(s)),MAX_INPUT,'normalized scenario')
    return m,e

def finish(report):
    result=enc(report);result['receipt_id']=digest(result);size(result,MAX_REPORT,'report');return result
