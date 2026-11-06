"""Bounded exact decimal inputs. No physical or authority inference."""
import json
import re
from decimal import Decimal
from fractions import Fraction
from ..contracts import canonical, digest

MAX_BYTES = 1_000_000
MAX_OUTPUT = 8_000_000
NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z')

class Refuse(ValueError):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code

class Lexeme(str):
    """Only the JSON parser may construct this internal numeric token."""

def fields(obj, names):
    if type(obj) is not dict or set(obj) != set(names.split()):
        raise Refuse('INVALID_ARGUMENT', 'exact object fields required: ' + names)

def text(value, limit=256):
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise Refuse('INVALID_ARGUMENT', 'bounded nonempty text required')
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise Refuse('INVALID_ARGUMENT', 'surrogate text is unsupported') from None
    return value

def bounded(value):
    stack = [(value, 0)]; count = 0
    while stack:
        item, depth = stack.pop(); count += 1
        if depth > 32 or count > 50_000:
            raise Refuse('BUDGET_EXCEEDED', 'request depth/node budget')
        if type(item) is dict:
            if len(item) > 50_000: raise Refuse('BUDGET_EXCEEDED', 'object budget')
            for key, val in item.items():
                text(key); stack.append((val, depth + 1))
        elif type(item) is list:
            if len(item) > 50_000: raise Refuse('BUDGET_EXCEEDED', 'array budget')
            stack.extend((x, depth + 1) for x in item)
        elif type(item) is str:
            text(item)
        elif item is not None and type(item) not in (int, float, Decimal, Lexeme):
            raise Refuse('INVALID_ARGUMENT', 'unsupported input type')

def number(value, *, positive=False, maximum=31_557_600):
    if type(value) is Decimal:
        if not value.is_finite(): raise Refuse('INVALID_ARGUMENT', 'finite decimal required')
        parts = value.as_tuple()
        if len(parts.digits) > 24 or abs(parts.exponent) > 36:
            raise Refuse('BUDGET_EXCEEDED', 'decimal coefficient/exponent budget')
        token = str(value)
    elif type(value) is int:
        if value.bit_length() > 160: raise Refuse('BUDGET_EXCEEDED', 'integer digit budget')
        token = str(value)
    elif type(value) is float:
        token = repr(value)
    elif type(value) is Lexeme:
        token = str(value)
    else:
        raise Refuse('INVALID_ARGUMENT', 'numeric token required; strings and booleans are not numbers')
    if len(token) > 48: raise Refuse('BUDGET_EXCEEDED', 'numeric token length budget')
    if not NUMBER.fullmatch(token): raise Refuse('INVALID_ARGUMENT', 'finite JSON decimal grammar required')
    mantissa, *exponents = re.split('[eE]', token)
    exponent = 0
    if exponents:
        raw = exponents[0].lstrip('+-')
        if len(raw) > 2: raise Refuse('BUDGET_EXCEEDED', 'exponent digit budget')
        exponent = int(exponents[0])
        if abs(exponent) > 12: raise Refuse('BUDGET_EXCEEDED', 'exponent magnitude budget')
    digits = mantissa.lstrip('-').replace('.', '').lstrip('0') or '0'
    places = len(mantissa.split('.')[1]) if '.' in mantissa else 0
    if len(digits) > 24 or max(0, places - exponent) > 12:
        raise Refuse('BUDGET_EXCEEDED', 'coefficient/fractional-place budget')
    result = Fraction(token)
    if result < 0 or (positive and result == 0) or result > maximum:
        raise Refuse('INVALID_ARGUMENT', 'numeric value outside physical range')
    return result

def rational(value):
    if abs(value.numerator)>=10**256 or value.denominator>=10**256:
        raise Refuse('BUDGET_EXCEEDED', 'rational size budget')
    return value

def encoded(value):
    if type(value) is Fraction:
        rational(value)
        return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}
    if type(value) is dict: return {k: encoded(v) for k, v in value.items()}
    if type(value) is list: return [encoded(v) for v in value]
    return value

def parse(raw, *, check_bounds=True):
    if len(raw) > MAX_BYTES: raise Refuse('BUDGET_EXCEEDED', 'input byte budget')
    def pairs(items):
        obj = {}
        for k, v in items:
            if k in obj: raise Refuse('INVALID_ARGUMENT', 'duplicate JSON key')
            obj[k] = v
        return obj
    def bad_constant(_): raise Refuse('INVALID_ARGUMENT', 'nonfinite JSON constant')
    try:
        if isinstance(raw, bytes): raw = raw.decode('utf-8')
        obj = json.loads(raw, parse_int=Lexeme, parse_float=Lexeme,
                         parse_constant=bad_constant, object_pairs_hook=pairs)
    except RecursionError:
        raise Refuse('BUDGET_EXCEEDED', 'JSON nesting budget') from None
    except (UnicodeError, json.JSONDecodeError):
        raise Refuse('INVALID_ARGUMENT', 'malformed JSON/UTF-8') from None
    if check_bounds: bounded(obj)
    return obj

def validate(s):
    bounded(s)
    fields(s, 'schema id release_s deadline_s horizon_s work_s interruptions power_kw policy provenance')
    if s['schema'] != 'capacity-orbital/checkpoint-v1': raise Refuse('UNSUPPORTED_SCHEMA', 'unsupported scenario schema')
    ident = text(s['id'], 128)
    fields(s['provenance'], 'kind source licence generated_on')
    for value in s['provenance'].values(): text(value)
    if s['provenance']['kind'] != 'synthetic': raise Refuse('INVALID_ARGUMENT', 'synthetic provenance required')
    out = dict(schema=s['schema'], id=ident, provenance=dict(s['provenance']))
    for key in ('release_s','deadline_s','horizon_s','work_s'):
        out[key] = number(s[key], positive=key in ('work_s','horizon_s'))
    if not out['release_s'] <= out['deadline_s'] <= out['horizon_s'] or out['work_s'] > out['horizon_s']:
        raise Refuse('INVALID_ARGUMENT', 'invalid release/deadline/horizon/work ordering')
    fields(s['power_kw'], 'productive checkpoint restart down')
    out['power_kw'] = {k: number(v, maximum=1_000_000_000) for k,v in s['power_kw'].items()}
    fields(s['policy'], 'version checkpoint_every_work_s checkpoint_duration_s restart_duration_s')
    out['policy'] = {'version': text(s['policy']['version'],128)}
    for key in ('checkpoint_every_work_s','checkpoint_duration_s','restart_duration_s'):
        value = s['policy'][key]
        out['policy'][key] = None if value is None and key == 'checkpoint_every_work_s' else number(value,positive=True)
    intervals = s['interruptions']
    if type(intervals) is not list: raise Refuse('INVALID_ARGUMENT','interruption list required')
    if len(intervals) > 1000: raise Refuse('BUDGET_EXCEEDED','at most 1000 interruption intervals')
    out['interruptions'] = []
    for interval in intervals:
        fields(interval,'start_s end_s')
        a,b = number(interval['start_s']),number(interval['end_s'])
        if not a < b <= out['horizon_s']: raise Refuse('INVALID_ARGUMENT','invalid interruption interval')
        previous = out['interruptions'][-1] if out['interruptions'] else None
        if previous and a < previous['end_s']: raise Refuse('INVALID_ARGUMENT','unsorted or overlapping interruptions')
        if previous and a == previous['end_s']: previous['end_s'] = b
        else: out['interruptions'].append(dict(start_s=a,end_s=b))
    if len(canonical(encoded(out)).encode()) > MAX_BYTES: raise Refuse('BUDGET_EXCEEDED','normalized input byte budget')
    return out

def receipt(result):
    result = encoded(result)
    result['receipt_id'] = digest(result)
    if len(canonical(result).encode()) > MAX_OUTPUT: raise Refuse('BUDGET_EXCEEDED','output byte budget')
    return result
