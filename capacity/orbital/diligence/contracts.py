"""Strict bounded contracts; caller data never grants authority."""
import json
import math
from ..contracts import canonical, digest

MAX_BYTES = 1_000_000
MAX_FLOWS = 1000
MAX_COHORTS = 200
MAX_YEARS = 100


class Refuse(ValueError):
    def __init__(self, code, reason):
        self.code=code
        super().__init__(reason)


def fields(value, names, label):
    if not isinstance(value,dict) or set(value)!=set(names.split()):
        raise Refuse('INVALID_ARGUMENT',label+': exact fields required: '+names)


def number(value, label, *, minimum=0, maximum=None, positive=False, integer=False):
    try:
        valid=isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    except OverflowError:
        valid=False
    if not valid or value<minimum or (positive and value<=0) or (maximum is not None and value>maximum) or (integer and not isinstance(value,int)):
        raise Refuse('INVALID_ARGUMENT',label+': finite number within declared domain required')
    return value


def text(value,label):
    if not isinstance(value,str) or not value.strip() or len(value)>200:
        raise Refuse('INVALID_ARGUMENT',label+': nonempty text up to 200 characters required')
    return value


def provenance(value):
    fields(value,'kind source licence generated_on','provenance')
    if value['kind']!='synthetic':
        raise Refuse('UNSUPPORTED_DATA','only explicitly synthetic inputs supported')
    for k,v in value.items():text(v,'provenance.'+k)


def parse(raw):
    if len(raw if isinstance(raw,bytes) else raw.encode())>MAX_BYTES:
        raise Refuse('BUDGET_EXCEEDED','request exceeds byte limit')
    def unique(pairs):
        obj={}
        for key,val in pairs:
            if key in obj:raise Refuse('INVALID_ARGUMENT','duplicate JSON key')
            obj[key]=val
        return obj
    def invalid(value):raise Refuse('INVALID_ARGUMENT','nonfinite JSON numbers refused')
    return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)


def finite_result(value):
    if isinstance(value,dict):
        for v in value.values():finite_result(v)
    elif isinstance(value,list):
        for v in value:finite_result(v)
    elif isinstance(value,(int,float)) and not isinstance(value,bool) and not math.isfinite(value):
        raise Refuse('ARITHMETIC_OVERFLOW','derived result is not finite')
    return value
