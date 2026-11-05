"""Strict explicit-unit contracts for analytic synthetic resource feasibility."""
import math
from ..contracts import fields, number, text

SCENARIO = 'capacity-orbital/dynamics-v1'
PROPOSAL = 'capacity-orbital/proposal-v1'
MAX_ITEMS = 10000


def validate(s, p):
    fields(s, 'schema name horizon_s provenance nodes', 'dynamics scenario')
    if s['schema'] != SCENARIO:
        raise ValueError('unsupported dynamics scenario schema')
    text(s['name'], 'name')
    horizon = number(s, 'horizon_s', positive=True, upper=31557600)
    fields(s['provenance'], 'kind source licence generated_on', 'provenance')
    if s['provenance']['kind'] != 'synthetic':
        raise ValueError('only explicitly synthetic data supported')
    for k, v in s['provenance'].items():
        text(v, k)
    if not isinstance(s['nodes'], dict) or not 1 <= len(s['nodes']) <= 128:
        raise ValueError('nodes must be an object with 1..128 entries')
    profile_count = 0
    for node_id, n in s['nodes'].items():
        text(node_id, 'node id')
        fields(n, 'battery thermal profiles', 'node')
        b = n['battery']
        fields(b, 'capacity_kwh initial_kwh reserve_kwh charge_efficiency discharge_efficiency max_charge_kw max_discharge_kw', 'battery')
        for key in b:
            number(b, key, positive=key in ('capacity_kwh','charge_efficiency','discharge_efficiency'),
                   upper=1 if key.endswith('efficiency') else None)
        if not b['reserve_kwh'] <= b['initial_kwh'] <= b['capacity_kwh']:
            raise ValueError('reserve <= initial <= capacity required')
        t = n['thermal']
        fields(t, 'initial_k maximum_k heat_capacity_j_per_k conductance_w_per_k', 'thermal')
        for key in t:
            number(t, key, positive=key != 'conductance_w_per_k')
        if t['initial_k'] > t['maximum_k']:
            raise ValueError('initial temperature exceeds maximum')
        if not isinstance(n['profiles'], list) or not n['profiles']:
            raise ValueError('profiles must be nonempty list')
        profile_count += len(n['profiles'])
        if profile_count > MAX_ITEMS:
            raise ValueError('too many profiles')
        end = 0
        for profile in n['profiles']:
            fields(profile, 'start_s end_s solar_kw background_kw background_heat_w sink_k', 'profile')
            for key in profile:
                number(profile, key, positive=key == 'sink_k')
            if profile['start_s'] != end or not end < profile['end_s'] <= horizon:
                raise ValueError('profiles must cover horizon contiguously, in order')
            end = profile['end_s']
        if end != horizon:
            raise ValueError('profiles must cover entire horizon')
    if profile_count > MAX_ITEMS:
        raise ValueError('too many profiles')
    if not isinstance(p, dict):
        raise ValueError('proposal must be object')
    required = {'schema','id','at_s','events'}
    if not required <= set(p) or not set(p) <= required | {'authority'}:
        raise ValueError('proposal requires schema,id,at_s,events and optional authority')
    if p['schema'] != PROPOSAL:
        raise ValueError('unsupported proposal schema')
    text(p['id'], 'proposal id')
    at = number(p, 'at_s', upper=horizon)
    if not isinstance(p['events'], list) or len(p['events']) > MAX_ITEMS:
        raise ValueError('events must be bounded list')
    ids = set()
    for e in p['events']:
        fields(e, 'id node kind start_s end_s power_kw heat_w', 'event')
        text(e['id'], 'event id')
        if e['id'] in ids:
            raise ValueError('duplicate event id')
        ids.add(e['id'])
        if not isinstance(e['node'], str) or e['node'] not in s['nodes'] or e['kind'] not in ('compute','transfer'):
            raise ValueError('unknown event node or kind')
        for key in ('start_s','end_s','power_kw','heat_w'):
            number(e,key)
        if not at <= e['start_s'] < e['end_s'] <= horizon:
            raise ValueError('event must be positive interval at/after proposal at_s within horizon')
    if 'authority' in p:
        a = p['authority']
        fields(a,'disposition valid_from_s expires_s scope','authority')
        if a['disposition'] not in ('allowed','refused','held') or a['scope'] != 'synthetic-evaluation':
            raise ValueError('unknown authority disposition or scope')
        number(a,'valid_from_s');number(a,'expires_s',positive=True)
        if a['expires_s'] <= a['valid_from_s']:
            raise ValueError('authority expiry must follow valid_from')
    return s,p


def source_hash(value):
    if value is not None and (not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError('source_sha256 must be lowercase hex SHA256 or None')


def finite(*values):
    if not all(math.isfinite(v) for v in values):
        raise ValueError('nonfinite derived state')
