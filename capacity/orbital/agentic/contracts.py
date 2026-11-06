"""Versioned, exact-field contracts and resource budgets for the agent boundary."""
import json
from ..contracts import canonical, digest, fields, number, text, validate
from ..planner import ROUTES

MAX_REQUEST_BYTES = 1_000_000
MAX_REQUESTS = 32
MAX_SCENARIOS = 20
MAX_JOBS = 200
MAX_CONTACTS = 200
MAX_CANDIDATES = 3
SUITE_SCHEMA = 'capacity-orbital/evaluation-suite-v1'


class Refuse(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def bounded_scenario(value):
    if not isinstance(value, dict):
        raise ValueError('scenario must be an object')
    for key, maximum in [('jobs', MAX_JOBS), ('contacts', MAX_CONTACTS)]:
        if not isinstance(value.get(key), list) or len(value[key]) > maximum:
            raise Refuse('BUDGET_EXCEEDED', f'{key}: at most {maximum} entries')
    return validate(value)


def semantic_digest(s):
    """Ignore descriptive labels/IDs so renamed copies cannot leak across splits.

    Stricter than exact simulation equivalence: job identity can affect tie order,
    but relabelling the same workload still cannot turn it into held-out evidence.
    """
    obj = {k: v for k, v in s.items() if k not in ('name', 'provenance', 'jobs', 'contacts')}
    obj['jobs'] = sorted(({k: v for k, v in j.items() if k != 'id'} for j in s['jobs']), key=canonical)
    obj['contacts'] = [{k: v for k, v in c.items() if k != 'id'} for c in s['contacts']]
    return digest(obj)


def validate_suite(suite):
    fields(suite, 'schema objective cost_tolerance_usd train heldout', 'suite')
    if suite['schema'] != SUITE_SCHEMA:
        raise ValueError('unsupported evaluation schema')
    if suite['objective'] != 'failures_then_cost':
        raise ValueError('fixed objective must be failures_then_cost')
    number(suite, 'cost_tolerance_usd')
    ids, contents = set(), set()
    total = 0
    for partition in ('train', 'heldout'):
        entries = suite[partition]
        if not isinstance(entries, list) or not entries:
            raise ValueError('train and heldout must be nonempty lists')
        total += len(entries)
        if total > MAX_SCENARIOS:
            raise Refuse('BUDGET_EXCEEDED', f'at most {MAX_SCENARIOS} total scenarios')
        for entry in entries:
            fields(entry, 'id scenario', partition + ' entry')
            text(entry['id'], 'scenario id')
            bounded_scenario(entry['scenario'])
            fingerprint = semantic_digest(entry['scenario'])
            if entry['id'] in ids or fingerprint in contents:
                raise Refuse('DATA_LEAKAGE', 'duplicate scenario ID or canonical workload content across suite')
            ids.add(entry['id'])
            contents.add(fingerprint)
    return suite


def validate_routes(baseline, candidates):
    if baseline not in ROUTES:
        raise ValueError('baseline must be a registered route')
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_CANDIDATES:
        raise Refuse('BUDGET_EXCEEDED', 'one to three fixed route candidates required')
    if any(not isinstance(c, str) or c not in ROUTES for c in candidates):
        raise ValueError('candidate must be a registered route, not executable code')
    if len(set(candidates)) != len(candidates):
        raise ValueError('duplicate candidates')


def parse_json(raw):
    if not isinstance(raw, (str, bytes)):
        raise ValueError('JSON text required')
    if len(raw.encode('utf-8') if isinstance(raw, str) else raw) > MAX_REQUEST_BYTES:
        raise Refuse('BUDGET_EXCEEDED', 'request byte limit exceeded')
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('duplicate JSON key: ' + key)
            out[key] = value
        return out
    def invalid(value):
        raise ValueError('non-finite JSON number: ' + value)
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
