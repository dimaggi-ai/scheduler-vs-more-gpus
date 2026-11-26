"""Offline declaration comparison; delegates all memory arithmetic to kv_envelope."""
import argparse
import hashlib
import json
import math
import os
import stat

from capacity import kv_envelope as envelope

SCHEMA = 'capacity-kv-comparison/v1'
VERSION = 'kv-scenario-comparator/v1'
MAX_BYTES = 3 * envelope.MAX_BYTES + 1024
NAMES = ('baseline', 'active', 'candidate')
PROTECTED = ('architecture', 'demand', 'evidence_kind')
MEMORY_METRICS = ('kv_bytes_per_token', 'kv_bytes_per_request',
                  'non_kv_reserved_bytes', 'kv_budget_bytes',
                  'requested_kv_bytes', 'remaining_bytes', 'deficit_bytes')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _canonical_input(value):
    """Same canonical bytes as _canonical, but stop before joining oversized input."""
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'),
                               ensure_ascii=False, allow_nan=False)
    raw = bytearray()
    for chunk in encoder.iterencode(value):
        encoded = chunk.encode('utf-8')
        if len(raw) + len(encoded) > MAX_BYTES:
            raise envelope.Refusal('input_size_limit')
        raw.extend(encoded)
    return bytes(raw)


def _bounded(value):
    # Depth is checked before recursion: at most eleven live traversal frames, including the refused depth.
    # Keep one mutable path, not a copied ancestor string for every sibling.
    nodes = 0
    segments = []

    def error_path():
        parts = ['$']
        for kind, part in segments:
            if kind == 'index':
                parts.append(f'[{part}]')
            elif part.isascii() and part.isidentifier():
                parts.append('.' + part)
            else:
                parts.append('[' + json.dumps(part, ensure_ascii=True) + ']')
        return ''.join(parts)

    def visit(item, depth):
        nonlocal nodes
        nodes += 1
        if nodes > 3 * envelope.MAX_NODES + 8 or depth > envelope.MAX_DEPTH + 1:
            raise envelope.Refusal('structure_limit')
        if type(item) is dict:
            if len(item) > 3 * envelope.MAX_NODES:
                raise envelope.Refusal('structure_limit')
            for key in item:
                if type(key) is not str or len(key) > 512:
                    raise envelope.Refusal('invalid_key')
            # Match the original LIFO diagnostic order without queuing siblings.
            for key in reversed(item):
                segments.append(('key', key))
                visit(item[key], depth + 1)
                segments.pop()
        elif type(item) is list:
            if len(item) > 3 * envelope.MAX_NODES:
                raise envelope.Refusal('structure_limit')
            for index in range(len(item) - 1, -1, -1):
                segments.append(('index', index))
                visit(item[index], depth + 1)
                segments.pop()
        elif type(item) is float and not math.isfinite(item):
            raise envelope.Refusal('nonfinite_number', error_path())
        elif type(item) not in (str, int, float, bool, type(None)):
            raise envelope.Refusal('invalid_json_object')
        elif type(item) is str and len(item) > MAX_BYTES:
            raise envelope.Refusal('input_size_limit')

    visit(value, 0)


def _paths(left, right, prefix):
    if type(left) is dict and type(right) is dict:
        return [path for key in sorted(set(left) | set(right))
                for path in _paths(left.get(key), right.get(key), prefix + '.' + key)]
    return [] if left == right else [prefix]


def _finish(base, **fields):
    result = dict(base, **fields)
    result['result_sha256'] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


def evaluate_bytes(raw):
    base = {'schema': 'capacity-kv-comparison-result/v1', 'comparator_version': VERSION,
            'authenticity': 'not_established', 'qualification': 'not_established'}
    if type(raw) is not bytes:
        return _finish(base, status='refused', code='expected_bytes', path='$')
    if len(raw) > MAX_BYTES:
        return _finish(base, status='refused', code='input_size_limit', path='$')
    base['input_sha256'] = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode('utf-8')
        # Bundle adds one level to the envelope. This scanner avoids recursive parsing
        # of hostile deep JSON without changing the envelope's independent limits.
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
                if depth > envelope.MAX_DEPTH + 1:
                    raise envelope.Refusal('depth_limit')
            elif char in ']}':
                depth -= 1
        data = json.loads(text, object_pairs_hook=envelope._pairs,
                          parse_constant=envelope._constant)
        _bounded(data)
        if type(data) is not dict:
            raise envelope.Refusal('expected_object')
        if set(data) - {'schema', *NAMES}:
            raise envelope.Refusal('unknown_field')
        if data.get('schema') is not None and data['schema'] != SCHEMA:
            raise envelope.Refusal('unsupported_schema', '$.schema')
        missing = ['$.schema'] if data.get('schema') is None else []
        reports = {}
        errors = []
        for name in NAMES:
            if data.get(name) is None:
                missing.append('$.' + name)
                continue
            report = envelope.evaluate(data[name])
            reports[name] = report
            if report['status'] == 'refused':
                errors.append({'scenario': name, 'code': report['code'],
                               'path': '$.' + name + report.get('path', '$')[1:]})
            elif report['status'] == 'insufficient_evidence':
                missing.extend('$.' + name + p[1:] for p in report['missing_paths'])
        if errors:
            return _finish(base, status='refused', errors=errors)
        if missing:
            return _finish(base, status='insufficient_evidence', missing_paths=sorted(missing))
        base['scenario_sha256'] = {n: reports[n]['input_sha256'] for n in NAMES}
        mismatches = [path for n in ('active', 'candidate') for key in PROTECTED
                      for path in _paths(data['baseline'][key], data[n][key], '$.' + n + '.' + key)]
        if mismatches:
            return _finish(base, status='not_comparable', mismatch_paths=mismatches,
                           comparison_reference='baseline')
        deltas = {}
        for reference in ('baseline', 'active'):
            delta = {key: reports['candidate']['metrics'][key] - reports[reference]['metrics'][key]
                     for key in MEMORY_METRICS}
            if any(abs(v) > envelope.MAX_INTEGER for v in delta.values()):
                raise envelope.Refusal('delta_integer_limit', '$.deltas.candidate_minus_' + reference)
            deltas['candidate_minus_' + reference] = delta
        changes = {n: {key: {'baseline': data['baseline'][key], n: data[n][key]}
                       for key in ('allocation', 'device', 'sources', 'assumptions', 'scenario_label')
                       if data['baseline'][key] != data[n][key]} for n in ('active', 'candidate')}
        return _finish(base, status='compared', declarations=data, reports=reports,
                       changed_declarations_vs_baseline=changes, deltas=deltas,
                       delta_units='bytes (kv_bytes_per_token: bytes/token; kv_bytes_per_request: bytes/request)',
                       limitations=['Declared synthetic scenarios only; no source authentication or measured validation.',
                                    'Memory feasibility is not serving capacity, a ranking, or operational authority.',
                                    'No latency, throughput, bandwidth, accuracy, energy, cost or domain qualification.'])
    except envelope.Refusal as exc:
        return _finish(base, status='refused', code=exc.code, path=exc.path)
    except (ValueError, UnicodeError, RecursionError, TypeError):
        return _finish(base, status='refused', code='invalid_json', path='$')


def evaluate(bundle):
    """Bound, serialize and snapshot before evaluation; callers must not mutate concurrently."""
    try:
        _bounded(bundle)
        return evaluate_bytes(_canonical_input(bundle))
    except envelope.Refusal as exc:
        return _finish({'schema': 'capacity-kv-comparison-result/v1', 'comparator_version': VERSION,
                        'authenticity': 'not_established', 'qualification': 'not_established'},
                       status='refused', code=exc.code, path=exc.path)
    except (ValueError, TypeError, UnicodeError, RecursionError, RuntimeError):
        return _finish({'schema': 'capacity-kv-comparison-result/v1', 'comparator_version': VERSION,
                        'authenticity': 'not_established', 'qualification': 'not_established'},
                       status='refused', code='invalid_json_object', path='$')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', help='regular non-symlink JSON bundle; stdout only')
    args = parser.parse_args(argv)
    try:
        if not hasattr(os, 'O_NOFOLLOW'):
            raise OSError('unsupported platform')
        try:
            fd = os.open(args.bundle, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except ValueError as exc:
            raise OSError('invalid path') from exc
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise OSError('not regular')
            stream = os.fdopen(fd, 'rb', closefd=False)
            # The raw descriptor always remains ours, even if wrapping fails.
            with stream:
                raw = stream.read(MAX_BYTES + 1)
                after = os.fstat(stream.fileno())
                identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                if identity(before) != identity(after):
                    raise OSError('changed file')
        finally:
            if fd is not None:
                os.close(fd)
        result = evaluate_bytes(raw)
    except OSError:
        result = evaluate_bytes(None)
        result.pop('result_sha256')
        result.update(code='input_file_refused')
        result = _finish(result)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['status'] == 'compared' else 2


if __name__ == '__main__':
    raise SystemExit(main())
