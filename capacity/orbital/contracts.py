"""Strict v1 data contract. Units are encoded in field names; no implicit defaults."""
import hashlib
import json
import math

SCHEMA = 'capacity-orbital/scenario-v1'
MAX_JOBS = 10000
MAX_CONTACTS = 10000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def number(obj, key, *, positive=False, upper=None):
    v = obj.get(key)
    try:
        finite = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f'{key}: finite number required')
    if v < 0 or (positive and v == 0) or (upper is not None and v > upper):
        raise ValueError(f'{key}: outside permitted range')
    return v


def fields(obj, expected, label):
    if not isinstance(obj, dict) or set(obj) != set(expected.split()):
        raise ValueError(f'{label}: exact fields required: {expected}')


def text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f'{label}: nonempty text up to 200 characters required')


def validate(s):
    fields(s, 'schema name horizon_s provenance nodes contacts jobs', 'scenario')
    if s['schema'] != SCHEMA:
        raise ValueError('unsupported schema')
    text(s['name'], 'name')
    horizon = number(s, 'horizon_s', positive=True, upper=31557600)
    fields(s['provenance'], 'kind source licence generated_on', 'provenance')
    if s['provenance']['kind'] != 'synthetic':
        raise ValueError('v1 supports explicitly synthetic scenarios only')
    for key, value in s['provenance'].items():
        text(value, 'provenance.' + key)
    fields(s['nodes'], 'orbital ground', 'nodes')
    for name, node in s['nodes'].items():
        fields(node, 'memory_gb max_power_kw max_heat_kw energy_budget_kwh compute_usd_per_hour electricity_usd_per_kwh', name)
        for key in node:
            number(node, key, positive=key in ('memory_gb', 'max_power_kw', 'max_heat_kw'))
    if not isinstance(s['contacts'], list) or len(s['contacts']) > MAX_CONTACTS:
        raise ValueError('contacts: bounded list required')
    end = 0
    ids = set()
    for c in s['contacts']:
        fields(c, 'id start_s end_s goodput_gbps usd_per_gb', 'contact')
        text(c['id'], 'contact.id')
        if c['id'] in ids:
            raise ValueError('duplicate contact id')
        ids.add(c['id'])
        a = number(c, 'start_s', upper=horizon)
        b = number(c, 'end_s', positive=True, upper=horizon)
        number(c, 'goodput_gbps', positive=True)
        number(c, 'usd_per_gb')
        if b <= a or a < end:
            raise ValueError('contacts must be ordered, nonoverlapping, positive windows for one shared terminal')
        end = b
    if not isinstance(s['jobs'], list) or not 0 < len(s['jobs']) <= MAX_JOBS:
        raise ValueError('jobs: nonempty bounded list required')
    ids = set()
    for j in s['jobs']:
        fields(j, 'id release_s deadline_s raw_gb result_gb compressed_gb memory_gb power_kw ground_s onboard_s preprocess_s hybrid_ground_s required_quality onboard_quality hybrid_quality', 'job')
        text(j['id'], 'job.id')
        if j['id'] in ids:
            raise ValueError('duplicate job id')
        ids.add(j['id'])
        for key in j.keys() - {'id'}:
            number(j, key, positive=key in ('raw_gb', 'memory_gb', 'power_kw', 'ground_s', 'onboard_s', 'preprocess_s', 'hybrid_ground_s'), upper=1 if 'quality' in key else None)
        if not 0 <= j['release_s'] < j['deadline_s'] <= horizon:
            raise ValueError('release < deadline <= horizon required')
        if not j['result_gb'] <= j['compressed_gb'] <= j['raw_gb']:
            raise ValueError('result <= compressed <= raw GB required')
    # Refuse overflow in derived quantities, before planning or JSON output.
    try:
        slowest = min((c['goodput_gbps'] for c in s['contacts']), default=None)
        for j in s['jobs']:
            for duration in ('ground_s', 'onboard_s', 'preprocess_s', 'hybrid_ground_s'):
                if not math.isfinite(j['power_kw'] * j[duration]):
                    raise ValueError('derived energy overflows')
            if slowest is not None and not math.isfinite(j['raw_gb'] * 8 / slowest):
                raise ValueError('derived transfer duration overflows')
    except OverflowError as exc:
        raise ValueError('numeric magnitude too large') from exc
    return s
