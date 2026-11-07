"""Strict inert JSON transport; no interpretation of paths in tool payloads."""
import json
import math
from ..contracts import canonical

INNER=1_000_000
REPORT=8_000_000
BUNDLE=10_000_000
TOOL=21_000_000

class Refuse(ValueError):
    def __init__(self,code,reason):super().__init__(reason);self.code=code

def fields(value,names):
    if type(value) is not dict or set(value)!=set(names.split()):raise Refuse('INVALID_ARGUMENT','exact fields required: '+names)

def text(value,limit=None):
    if type(value) is not str or (limit is not None and (not value.strip() or len(value)>limit)):raise Refuse('INVALID_ARGUMENT','bounded text required')
    try:value.encode('utf-8')
    except UnicodeError:raise Refuse('INVALID_ARGUMENT','invalid Unicode text') from None
    return value

def raw(value,limit):
    if type(value) is str:
        # UTF-8 cannot be shorter than its Python character count.
        if len(value)>limit:raise Refuse('BUDGET_EXCEEDED','raw byte budget')
        try:data=value.encode('utf-8')
        except UnicodeError:raise Refuse('INVALID_ARGUMENT','invalid UTF-8 text') from None
    elif type(value) is bytes:data=value
    else:raise Refuse('INVALID_ARGUMENT','JSON text or UTF-8 bytes required')
    if len(data)>limit:raise Refuse('BUDGET_EXCEEDED','raw byte budget')
    return data

def bounded(value):
    stack=[(value,0)];count=0
    while stack:
        item,depth=stack.pop();count+=1
        if count>1_000_000 or depth>64:raise Refuse('BUDGET_EXCEEDED','JSON depth/node budget')
        if type(item) is dict:
            if len(item)>1_000_000:raise Refuse('BUDGET_EXCEEDED','object budget')
            for k,v in item.items():text(k);stack.append((v,depth+1))
        elif type(item) is list:
            if len(item)>1_000_000:raise Refuse('BUDGET_EXCEEDED','list budget')
            stack.extend((v,depth+1) for v in item)
        elif type(item) is str:text(item)
        elif type(item) is float:
            if not math.isfinite(item):raise Refuse('INVALID_ARGUMENT','nonfinite JSON number')
        elif type(item) is int:
            if item.bit_length()>2552:raise Refuse('BUDGET_EXCEEDED','numeric coefficient budget')
        elif item is not None and type(item) is not bool:raise Refuse('INVALID_ARGUMENT','unsupported JSON type')

def wire(value,limit):
    bounded(value)
    data=canonical(value)+'\n'
    raw(data,limit)
    return data

def parse(value,limit,*,canonical_outer=False):
    data=raw(value,limit)
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise Refuse('INVALID_ARGUMENT','duplicate JSON key')
            result[k]=v
        return result
    from ..platform.checkpoint.contracts import token,Token,Refuse as CheckpointRefuse
    numeric_count=0
    def number(s):
        nonlocal numeric_count
        numeric_count+=1
        if numeric_count>1_000_000:raise Refuse('BUDGET_EXCEEDED','numeric node budget before conversion')
        # json.loads already enforces the integer grammar. These short literals
        # cannot exceed the shared lexical/coefficient/exponent bounds.
        if len(s)<=16 and not any(c in s for c in '.eE'):return int(s)
        try:token(Token(s))
        except CheckpointRefuse as ex:raise Refuse(ex.code,str(ex)) from None
        result=float(s) if any(c in s for c in '.eE') else int(s)
        if type(result) is float and not math.isfinite(result):raise Refuse('INVALID_ARGUMENT','nonfinite outer JSON number')
        return result
    def bad(_):raise Refuse('INVALID_ARGUMENT','nonfinite JSON constant')
    try:result=json.loads(data.decode('utf-8'),object_pairs_hook=pairs,parse_int=number,parse_float=number,parse_constant=bad)
    except RecursionError:raise Refuse('BUDGET_EXCEEDED','JSON nesting budget') from None
    except (UnicodeError,json.JSONDecodeError):raise Refuse('INVALID_ARGUMENT','malformed JSON/UTF-8') from None
    bounded(result)
    encoded=wire(result,limit)
    if canonical_outer and data!=encoded.encode('utf-8'):raise Refuse('NONCANONICAL_JSON','bundle must be compact sorted canonical JSON with one newline')
    return result

def pin(value,optional=True):
    if value is None and optional:return
    if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise Refuse('INVALID_ARGUMENT','expected SHA-256 must be null or lowercase 64hex')
