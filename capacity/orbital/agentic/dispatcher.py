"""Bounded, idempotent agent tool dispatcher. No shell, network or live actions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict
from ..contracts import canonical, digest, fields, text
from ..planner import plan_route, compare
from . import REQUEST_SCHEMA, RESPONSE_SCHEMA, VERSION
from .contracts import (MAX_REQUEST_BYTES, MAX_REQUESTS, MAX_SCENARIOS, MAX_JOBS,
                        MAX_CONTACTS, MAX_CANDIDATES, Refuse, bounded_scenario, parse_json)
from .evaluation import evaluate, EVALUATOR

MAX_RESPONSE_BYTES = 4_000_000
MAX_CACHE_BYTES = 16_000_000


def source_manifest():
    """Bind own source AND imported v1 planner/resource/IO contracts, not just this folder."""
    root = Path(__file__).resolve().parents[1]
    paths = list(root.glob('*.py')) + list((root / 'agentic').glob('*.py')) + [root / 'agentic' / 'request.schema.json']
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if not p.name.startswith('test_')}


def source_digest():
    return digest(source_manifest())


def manifest():
    return {
        'schema': 'capacity-orbital/tool-manifest-v1', 'version': VERSION,
        'request_schema': REQUEST_SCHEMA, 'request_schema_file': 'request.schema.json',
        'response_schema': RESPONSE_SCHEMA,
        'evaluator': EVALUATOR, 'source_sha256': source_digest(),
        'tools': {
            'plan': {'arguments': ['scenario', 'route'], 'routes': ['ground', 'onboard', 'hybrid']},
            'compare': {'arguments': ['scenario']},
            'evaluate': {'arguments': ['suite', 'baseline', 'candidates']},
        },
        'limits': {'request_bytes': MAX_REQUEST_BYTES, 'requests_per_session': MAX_REQUESTS,
                   'jobs_per_scenario': MAX_JOBS, 'contacts_per_scenario': MAX_CONTACTS,
                   'evaluation_scenarios': MAX_SCENARIOS, 'candidates': MAX_CANDIDATES,
                   'response_bytes': MAX_RESPONSE_BYTES, 'cache_bytes': MAX_CACHE_BYTES},
        'refusal_codes': ['INVALID_ARGUMENT', 'UNSUPPORTED_SCHEMA', 'UNKNOWN_TOOL', 'DATA_LEAKAGE',
                          'BUDGET_EXCEEDED', 'REQUEST_ID_CONFLICT', 'SOURCE_CHANGED', 'SOURCE_UNAVAILABLE'],
        'authority': 'planning_only; no execution permission, authentication or Tool Guard authorization',
        'promotion': 'never; recommendations require independent review and designated acceptance',
    }


class Dispatcher:
    """One bounded local session; retries persist only for this object/process lifetime.

    JSON requests cannot provide callbacks, code, file paths or new authority.
    A caller may use the Python API or JSON-lines CLI; neither executes a plan.
    """
    def __init__(self):
        try:
            self._source = source_digest()
        except OSError:
            self._source = None
        self._cache: Dict[str, Any] = {}
        self._cache_bytes = 0
        self._closed = False

    def _envelope(self, request_id, request_hash, status, code, message, result=None):
        output = dict(schema=RESPONSE_SCHEMA, request_id=request_id, request_sha256=request_hash,
                      source_sha256=self._source, status=status, code=code, message=message,
                      authority_disposition='planning_only', execution_performed=False,
                      classification='synthetic planning proposal, not a measured hardware outcome', result=result)
        output['outcome_sha256'] = digest(output)
        return output

    def dispatch_json(self, raw):
        try:
            return self.dispatch(parse_json(raw))
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError) as exc:
            return self._envelope(None, None, 'refused', getattr(exc, 'code', 'INVALID_ARGUMENT'), str(exc))

    def dispatch(self, request: Dict[str, Any]) -> Dict[str, Any]:
        request_id = request_hash = None
        try:
            encoded = canonical(request).encode('utf-8')
            if len(encoded) > MAX_REQUEST_BYTES:
                raise Refuse('BUDGET_EXCEEDED', 'request byte limit exceeded')
            request = json.loads(encoded)
            fields(request, 'schema id tool arguments', 'request')
            text(request['id'], 'request id')
            request_id, request_hash = request['id'], digest(request)
            try:
                current_source = source_digest()
            except OSError as exc:
                raise Refuse('SOURCE_UNAVAILABLE', 'cannot read source provenance') from exc
            if self._source is None:
                raise Refuse('SOURCE_UNAVAILABLE', 'source unavailable when session opened; start a new session')
            if current_source != self._source:
                raise Refuse('SOURCE_CHANGED', 'source changed during session; start a new session')
            if request_id in self._cache:
                previous_hash, previous_response = self._cache[request_id]
                if previous_hash != request_hash:
                    raise Refuse('REQUEST_ID_CONFLICT', 'request id was already used with different content')
                return deepcopy(previous_response)
            if self._closed:
                raise Refuse('BUDGET_EXCEEDED', 'session cache budget exhausted; no new work admitted')
            if len(self._cache) >= MAX_REQUESTS:
                raise Refuse('BUDGET_EXCEEDED', 'session request limit reached; no eviction of idempotency records')
            if request['schema'] != REQUEST_SCHEMA:
                raise Refuse('UNSUPPORTED_SCHEMA', 'unsupported request schema')
            tool, args = request['tool'], request['arguments']
            if tool == 'plan':
                fields(args, 'scenario route', 'plan arguments')
                bounded_scenario(args['scenario'])
                result = plan_route(args['scenario'], args['route'], source_sha256=self._source)
            elif tool == 'compare':
                fields(args, 'scenario', 'compare arguments')
                bounded_scenario(args['scenario'])
                result = compare(args['scenario'], source_sha256=self._source)
            elif tool == 'evaluate':
                fields(args, 'suite baseline candidates', 'evaluate arguments')
                result = evaluate(args['suite'], args['baseline'], args['candidates'], self._source)
            else:
                raise Refuse('UNKNOWN_TOOL', 'tool is not in the fixed planning registry')
            response = self._envelope(request_id, request_hash, 'proposed', 'PROPOSAL_ONLY',
                                      'no action executed; baseline and permissions unchanged', result)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            response = self._envelope(request_id, request_hash, 'refused', getattr(exc, 'code', 'INVALID_ARGUMENT'), str(exc))
        size = len(canonical(response).encode('utf-8'))
        if size > MAX_RESPONSE_BYTES:
            response = self._envelope(request_id, request_hash, 'refused', 'BUDGET_EXCEEDED', 'response byte limit exceeded')
            size = len(canonical(response).encode('utf-8'))
        if request_id and request_hash and request_id not in self._cache and len(self._cache) < MAX_REQUESTS:
            if self._cache_bytes + size > MAX_CACHE_BYTES:
                self._closed = True
                return self._envelope(request_id, request_hash, 'refused', 'BUDGET_EXCEEDED', 'session cache budget exhausted; no new work admitted')
            self._cache[request_id] = (request_hash, deepcopy(response))
            self._cache_bytes += size
        return response
