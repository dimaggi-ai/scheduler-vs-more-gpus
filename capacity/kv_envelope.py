"""Bounded, offline single-device KV memory scenarios; no serving predictions."""
import argparse
import datetime
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
from urllib.parse import urlsplit

SCHEMA = 'capacity-kv-envelope/v1'
MAX_BYTES = 65536
MAX_INTEGER = 2**53 - 1
MAX_DEPTH = 8
MAX_NODES = 1024


class Refusal(ValueError):
    def __init__(self, code, path='$'):
        self.code, self.path = code, path
        super().__init__(code)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refusal('duplicate_key')
        result[key] = value
    return result


def _constant(value):
    raise Refusal('nonfinite_number')


def _depth_guard(text):
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            if depth > MAX_DEPTH:
                raise Refusal('depth_limit')
        elif char in ']}':
            depth -= 1


def _validate(data):
    missing = []
    nodes = 0

    def bounded(value, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise Refusal('structure_limit')
        if isinstance(value, dict):
            for v in value.values():
                bounded(v, depth + 1)
        elif isinstance(value, list):
            for v in value:
                bounded(v, depth + 1)
    bounded(data)

    def obj(value, keys, path):
        if type(value) is not dict:
            raise Refusal('expected_object', path)
        if set(value) - set(keys):
            raise Refusal('unknown_field', path)
        for key in keys:
            if key not in value or value[key] is None:
                missing.append(path + '.' + key)
        return value

    def text(value, path):
        if type(value) is not str or not value.strip() or len(value) > 512 or any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs') for c in value):
            raise Refusal('invalid_text', path)

    def number(value, path, minimum=0):
        if type(value) is not int or not minimum <= value <= MAX_INTEGER:
            raise Refusal('invalid_integer', path)

    def fields(value, specs, path):
        value = obj(value, specs, path)
        for key, validator in specs.items():
            if key in value and value[key] is not None:
                validator(value[key], path + '.' + key)

    def enum(*allowed):
        def check(value, path):
            if type(value) is not str or value not in allowed:
                raise Refusal('unsupported_value', path)
        return check

    def positive(value, path):
        number(value, path, 1)

    def precision(value, path):
        number(value, path, 1)
        if value not in (8, 16, 32):
            raise Refusal('unsupported_precision', path)

    root_keys = ('schema', 'scenario_label', 'evidence_kind', 'sources', 'assumptions', 'architecture', 'allocation', 'device', 'demand')
    obj(data, root_keys, '$')
    for key, validator in [('schema', enum(SCHEMA)), ('scenario_label', text), ('evidence_kind', enum('declared_scenario'))]:
        if data.get(key) is not None:
            validator(data[key], '$.' + key)
    if data.get('assumptions') is not None:
        assumptions = data['assumptions']
        if type(assumptions) is not list or not 1 <= len(assumptions) <= 32:
            raise Refusal('invalid_assumptions', '$.assumptions')
        for i, item in enumerate(assumptions):
            text(item, '$.assumptions.' + str(i))
    if data.get('sources') is not None:
        sources = data['sources']
        if type(sources) is not list or not 1 <= len(sources) <= 16:
            raise Refusal('invalid_sources', '$.sources')
        for i, source in enumerate(sources):
            path = '$.sources.' + str(i)
            fields(source, dict.fromkeys(('uri', 'revision', 'sha256', 'license', 'retrieved_at'), text), path)
            if source.get('sha256') is not None and not re.fullmatch('[0-9a-f]{64}', source['sha256']):
                raise Refusal('invalid_sha256', path + '.sha256')
            if source.get('uri') is not None:
                uri = source['uri']
                try:
                    parsed = urlsplit(uri)
                    if any(c.isspace() for c in uri) or '\\' in uri:
                        raise ValueError()
                    if parsed.scheme in ('http', 'https'):
                        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
                            raise ValueError()
                        _ = parsed.port
                    elif parsed.scheme != 'urn' or not parsed.path:
                        raise ValueError()
                except ValueError:
                    raise Refusal('invalid_uri', path + '.uri') from None
            if source.get('retrieved_at') is not None:
                try:
                    date = datetime.date.fromisoformat(source['retrieved_at'])
                    if date.isoformat() != source['retrieved_at']:
                        raise ValueError()
                except ValueError:
                    raise Refusal('invalid_date', path + '.retrieved_at') from None
    specs = {
        'architecture': {'kind': enum('uniform_standard_attention'), 'model_revision': text, 'tokenizer_revision': text,
                         'layers': positive, 'kv_heads': positive, 'head_dimension': positive,
                         'k_bits': precision, 'v_bits': precision},
        'allocation': {'prefix_sharing': enum('none'), 'block_tokens': positive,
                       'metadata_bytes_per_block': number, 'overhead_bytes_per_request': number},
        'device': {'usable_hbm_bytes': positive, 'resident_weights_bytes': number,
                   'workspace_bytes': number, 'headroom_bytes': number},
        'demand': {'max_resident_context_tokens': positive, 'requested_concurrency': positive},
    }
    for key, spec in specs.items():
        if data.get(key) is not None:
            fields(data[key], spec, '$.' + key)
    return sorted(missing)


def evaluate_bytes(raw):
    """Return simulated/insufficient_evidence/refused; digest binds exact JSON bytes."""
    if type(raw) is not bytes:
        return {'status': 'refused', 'code': 'expected_bytes', 'path': '$'}
    if len(raw) > MAX_BYTES:
        return {'status': 'refused', 'code': 'input_size_limit', 'path': '$'}
    digest = hashlib.sha256(raw).hexdigest()
    base = {'schema': 'capacity-kv-envelope-result/v1', 'input_sha256': digest}
    try:
        text = raw.decode('utf-8')
        _depth_guard(text)
        data = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        missing = _validate(data)
        if missing:
            return dict(base, status='insufficient_evidence', missing_paths=missing)
        arch, alloc, device, demand = (data[k] for k in ('architecture', 'allocation', 'device', 'demand'))
        token_bytes = arch['layers'] * arch['kv_heads'] * arch['head_dimension'] * (arch['k_bits'] + arch['v_bits']) // 8
        blocks = (demand['max_resident_context_tokens'] + alloc['block_tokens'] - 1) // alloc['block_tokens']
        per_request = blocks * (alloc['block_tokens'] * token_bytes + alloc['metadata_bytes_per_block']) + alloc['overhead_bytes_per_request']
        non_kv = device['resident_weights_bytes'] + device['workspace_bytes'] + device['headroom_bytes']
        budget = device['usable_hbm_bytes'] - non_kv
        requested = demand['requested_concurrency'] * per_request
        # Bound derived quantities too, so JSON consumers can preserve integer precision.
        if max(token_bytes, blocks, per_request, non_kv, requested) > MAX_INTEGER:
            raise Refusal('derived_integer_limit')
        remaining = budget - requested
        if abs(remaining) > MAX_INTEGER:
            raise Refusal('derived_integer_limit')
        metrics = dict(kv_bytes_per_token=token_bytes, allocated_blocks_per_request=blocks,
                       kv_bytes_per_request=per_request, non_kv_reserved_bytes=non_kv,
                       kv_budget_bytes=budget, requested_kv_bytes=requested,
                       max_memory_feasible_concurrency=max(0, budget) // per_request,
                       remaining_bytes=remaining, deficit_bytes=max(0, -remaining),
                       feasible=remaining >= 0,
                       reason='infeasible_non_kv_budget' if budget < 0 else ('memory_fit' if remaining >= 0 else 'insufficient_kv_budget'))
        return dict(base, status='simulated', formula_version='uniform-standard-attention-no-sharing/v1',
                    units='bytes (integer); tokens and requests (counts)', declarations=data, metrics=metrics,
                    not_evaluated=['bandwidth', 'latency', 'throughput', 'offload', 'network', 'energy', 'accuracy', 'operational_qualification'],
                    limitations=['Declared scenario only; input hash does not authenticate upstream source bytes or declarations.',
                                 'One device; uniform standard-attention KV; no prefix sharing or cache-hit memory subtraction.',
                                 'Memory fit is not service capacity, an SLA, domain acceptance or execution authority.'])
    except Refusal as exc:
        return dict(base, status='refused', code=exc.code, path=exc.path)
    except (UnicodeError, ValueError, RecursionError):
        return dict(base, status='refused', code='invalid_json', path='$')


def evaluate(scenario):
    """Object API; input digest binds canonical UTF-8 JSON of the supplied object."""
    try:
        stack = [(scenario, 0)]
        nodes = 0
        while stack:
            value, depth = stack.pop()
            nodes += 1
            if nodes > MAX_NODES or depth > MAX_DEPTH:
                raise ValueError('structure limit')
            if type(value) is dict:
                if len(value) > MAX_NODES or any(type(k) is not str or len(k) > 512 for k in value):
                    raise ValueError('invalid keys')
                stack.extend((v, depth + 1) for v in value.values())
            elif type(value) is list:
                if len(value) > MAX_NODES:
                    raise ValueError('list limit')
                stack.extend((v, depth + 1) for v in value)
            elif type(value) is str and len(value) > MAX_BYTES:
                raise ValueError('text limit')
            elif type(value) not in (str, int, float, bool, type(None)):
                raise ValueError('unsupported object')
        raw = json.dumps(scenario, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return {'status': 'refused', 'code': 'invalid_json_object', 'path': '$'}
    return evaluate_bytes(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline declared single-device KV memory envelope; no cluster access')
    parser.add_argument('scenario')
    args = parser.parse_args(argv)
    fd = None
    try:
        if not hasattr(os, 'O_NOFOLLOW'):
            raise Refusal('unsupported_platform')
        fd = os.open(args.scenario, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Refusal('expected_regular_file')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            result = evaluate_bytes(stream.read(MAX_BYTES + 1))
    except (OSError, Refusal) as exc:
        result = {'status': 'refused', 'code': exc.code if isinstance(exc, Refusal) else 'input_unreadable', 'path': '$'}
    finally:
        if fd is not None:
            os.close(fd)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['status'] == 'simulated' else 2


if __name__ == '__main__':
    sys.exit(main())
