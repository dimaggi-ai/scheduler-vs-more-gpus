"""Offline declared KV allocation to existing single-device service simulation."""
import copy
import hashlib
import json
import math
import os
import re
import stat
import sys
import unicodedata

from capacity import inference, kv_envelope

SCHEMA = 'capacity-kv-inference-bridge/v1'
RESULT_SCHEMA = 'capacity-kv-inference-bridge-result/v1'
MAX_BYTES = 262144
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 8
MAX_NODES = 8192
MAX_INTEGER = 2**53 - 1
ATTRIBUTION = {
    'runtime_source_verified': False,
    'meaning': 'Expected build attribution only; installed source bytes are not verified.',
    'engine_commit': '2b013ff94699f549300d8c9c6ae34d7447c63982',
    'engine_sha256': 'ee5bbf74aa4de25f961cf8c9f81c817efef8b954cc0333aded45e7afd6f505c8',
    'envelope_commit': '37080402c0df716dd9a379f3858eeaa6c73197c5',
    'envelope_sha256': '3c23b98e11096cc7c4bf2a5c95b533226ed20a2df781ef71c064a13fa2715e81',
    'engine_api': 'inference.simulate explicit reservations',
    'envelope_api': 'kv_envelope.evaluate',
}
LIMITATIONS = [
    'Declared hypothetical single-device uniform standard-attention scenario; not a measured trace.',
    'Allocation affects admission; service uses the existing raw-KV roofline approximation.',
    'Padding, metadata, workspace and allocator overhead timing costs are not modeled.',
    'FCFS peak is not an optimal packing limit; queued completion is not simultaneous fit.',
    'Source hashes and URIs are declarations, not authenticated source truth or benchmarks.',
    'No calibrated hardware, kernel, accuracy, prefix sharing, offload, network or energy evidence.',
    'No service, clinical, defence, finance, operational qualification, acceptance or execution authority.',
]


class Refusal(ValueError):
    def __init__(self, code, path='$'):
        self.code, self.path = code, path
        super().__init__(code)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('utf-8')


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _refused(code, path='$', **base):
    return dict(base, status='refused', code=code, path=path,
                runtime_source_verified=False)


def _text(value, path):
    if (type(value) is not str or not value.strip() or len(value) > 512
            or any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs') for c in value)):
        raise Refusal('invalid_text', path)


def _integer(value, path, minimum=0, maximum=MAX_INTEGER):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Refusal('invalid_integer', path)


def _number(value, path, minimum=0, positive=True):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or value < minimum or (positive and value == minimum):
        raise Refusal('invalid_number', path)


def _structure(data):
    stack = [(data, 0, '$')]
    nodes = 0
    while stack:
        value, depth, path = stack.pop()
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise Refusal('structure_limit', path)
        if type(value) is dict:
            if len(value) > MAX_NODES:
                raise Refusal('structure_limit', path)
            for key in value:
                _text(key, path)
            stack.extend((v, depth + 1, path + '.' + k) for k, v in value.items())
        elif type(value) is list:
            if len(value) > MAX_NODES:
                raise Refusal('structure_limit', path)
            stack.extend((v, depth + 1, path + '.' + str(i)) for i, v in enumerate(value))
        elif type(value) is str:
            _text(value, path)
        elif type(value) is float and not math.isfinite(value):
            raise Refusal('nonfinite_number', path)
        elif type(value) not in (str, int, float, bool, type(None)):
            raise Refusal('unsupported_object', path)
        elif type(value) is int and abs(value) > MAX_INTEGER:
            raise Refusal('integer_limit', path)


def _evaluate_envelope(scenario, path):
    try:
        return kv_envelope.evaluate(scenario)
    except (Refusal, MemoryError):
        raise
    except Exception:
        raise Refusal('bridge_consistency_violation', path) from None


def _validate(data):
    missing = []

    def obj(value, keys, path):
        if type(value) is not dict:
            raise Refusal('expected_object', path)
        if set(value) - set(keys):
            raise Refusal('unknown_field', path)
        missing.extend(path + '.' + k for k in keys if value.get(k) is None)

    def fields(value, specs, path):
        obj(value, specs, path)
        for key, check in specs.items():
            if value.get(key) is not None:
                check(value[key], path + '.' + key)

    def enum(*allowed):
        def check(value, path):
            if type(value) is not str or value not in allowed:
                raise Refusal('unsupported_value', path)
        return check

    def positive(value, path):
        _integer(value, path, 1)

    def source_indices(value, path):
        if type(value) is not list or not 1 <= len(value) <= 16:
            raise Refusal('invalid_source_indices', path)
        for i, v in enumerate(value):
            _integer(v, path + '.' + str(i), 0, 15)
        if len(set(value)) != len(value):
            raise Refusal('duplicate_source_index', path)

    def assumptions(value, path):
        if type(value) is not list or not 1 <= len(value) <= 32:
            raise Refusal('invalid_assumptions', path)
        for i, v in enumerate(value):
            _text(v, path + '.' + str(i))

    def slug(value, path):
        if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', value):
            raise Refusal('invalid_request_id', path)

    obj(data, ('schema', 'parent_envelope', 'model', 'service', 'requests'), '$')
    if data.get('schema') is not None:
        enum(SCHEMA)(data['schema'], '$.schema')
    if data.get('model') is not None:
        fields(data['model'], {'model_revision': _text, 'tokenizer_revision': _text,
                              'parameters': positive, 'bytes_per_parameter': positive}, '$.model')
    if data.get('service') is not None:
        fields(data['service'], {'hardware_name': _text, 'compute_flops_s': _number,
                                'memory_bandwidth_bytes_s': _number, 'efficiency': _number,
                                'ttft_slo_s': _number, 'itl_slo_s': _number,
                                'max_batch': lambda v, p: _integer(v, p, 1, 128),
                                'policy': enum('decode-first', 'prefill-first'),
                                'source_indices': source_indices, 'assumptions': assumptions}, '$.service')
        if data['service'].get('efficiency') is not None and data['service']['efficiency'] > 1:
            raise Refusal('invalid_efficiency', '$.service.efficiency')
    if data.get('requests') is not None:
        reqs = data['requests']
        if type(reqs) is not list or not 1 <= len(reqs) <= 128:
            raise Refusal('request_count', '$.requests')
        ids = set()
        for i, req in enumerate(reqs):
            path = '$.requests.' + str(i)
            fields(req, {'request_id': slug, 'arrival_s': lambda v, p: _number(v, p, positive=False),
                         'input_tokens': positive, 'output_tokens': positive,
                         'cached_prefix_tokens': _integer, 'max_resident_context_tokens': positive}, path)
            if req.get('request_id') is not None:
                if req['request_id'] in ids:
                    raise Refusal('duplicate_request_id', path + '.request_id')
                ids.add(req['request_id'])
            if req.get('input_tokens') is not None and req.get('cached_prefix_tokens') is not None:
                if req['cached_prefix_tokens'] > req['input_tokens']:
                    raise Refusal('invalid_cached_prefix', path + '.cached_prefix_tokens')
            if all(req.get(k) is not None for k in ('input_tokens', 'output_tokens', 'max_resident_context_tokens')):
                total = req['input_tokens'] + req['output_tokens']
                if total > MAX_INTEGER:
                    raise Refusal('derived_integer_limit', path)
                if req['max_resident_context_tokens'] < total:
                    raise Refusal('bound_too_small', path + '.max_resident_context_tokens')
        if sum(r.get('output_tokens') or 0 for r in reqs) > 100000:
            raise Refusal('output_token_limit', '$.requests')
    parent = None
    if data.get('parent_envelope') is not None:
        parent = _evaluate_envelope(data['parent_envelope'], '$.parent_envelope')
        if parent['status'] == 'refused':
            raise Refusal(parent['code'], '$.parent_envelope' + parent.get('path', '$')[1:])
        if parent['status'] == 'insufficient_evidence':
            missing.extend('$.parent_envelope' + p[1:] for p in parent['missing_paths'])
    return sorted(missing), parent


def _finite_nonnegative(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _timing_precision(reqs, service, engine):
    """Conservative first-order diagnostic policy, not a formal error proof."""
    additions = len(reqs) + sum(r['output_tokens'] for r in reqs)
    method = 'conservative_first_order_estimate_not_proof'
    served = [r for r in engine['requests'] if not r['rejected']]
    if not served:
        return {'status': 'not_evaluated', 'reason': 'no_served_requests',
                'event_addition_bound': additions, 'method': method}
    try:
        arrivals = [r['arrival_s'] for r in reqs]
        clock_scale = max(max(arrivals), min(arrivals) + engine['makespan_s']) * (1 + 2**-40)
        estimate = (additions + 8) * math.ulp(clock_scale)
        if not math.isfinite(clock_scale) or not math.isfinite(estimate):
            raise Refusal('timing_precision_indeterminate', '$.service_simulation')
        resolution_floor = 1000 * estimate
        if engine['makespan_s'] <= resolution_floor:
            raise Refusal('timing_precision_indeterminate', '$.service_simulation')
        for row in served:
            metrics = [('ttft_s', 'ttft_slo_s')]
            if reqs[row['id']]['output_tokens'] > 1:
                metrics.append(('max_itl_s', 'itl_slo_s'))
            for metric, threshold in metrics:
                value = row[metric]
                if (not math.isfinite(value) or value <= resolution_floor
                        or abs(value - service[threshold]) <= estimate):
                    raise Refusal('timing_precision_indeterminate', '$.service_simulation')
    except (OverflowError, ValueError) as exc:
        if isinstance(exc, Refusal):
            raise
        raise Refusal('timing_precision_indeterminate', '$.service_simulation') from None
    return {'status': 'evaluated', 'estimate_s': estimate, 'clock_scale_s': clock_scale,
            'event_addition_bound': additions, 'resolution_multiplier': 1000, 'method': method}


def _timing_invariants(reqs, service, engine):
    """Check returned clock relationships; do not recompute service formulas."""
    served = [row for row in engine['requests'] if not row['rejected']]
    for row in served:
        if (type(row.get('output_tokens')) is not int
                or row['output_tokens'] != reqs[row['id']]['output_tokens']
                or type(row.get('slo_met')) is not bool
                or row['slo_met'] is not (row['ttft_s'] <= service['ttft_slo_s']
                                         and row['max_itl_s'] <= service['itl_slo_s'])):
            raise Refusal('bridge_consistency_violation', '$.service_simulation')
    if not served:
        return
    arrivals = [req['arrival_s'] for req in reqs]
    first = min(arrivals)
    scale = max(max(arrivals), first + engine['makespan_s'],
                max(reqs[row['id']]['arrival_s'] + row['ttft_s'] + row['max_itl_s']
                    for row in served)) * (1 + 2**-40)
    tolerance = (len(reqs) + sum(req['output_tokens'] for req in reqs) + 8) * math.ulp(scale)
    # The separate precision diagnostic owns nonfinite derived-clock refusals.
    if not math.isfinite(scale) or not math.isfinite(tolerance):
        return
    for row in served:
        offset = reqs[row['id']]['arrival_s'] - first
        if (offset + row['ttft_s'] > engine['makespan_s'] + tolerance
                or offset + row['ttft_s'] + row['max_itl_s'] > engine['makespan_s'] + tolerance):
            raise Refusal('bridge_consistency_violation', '$.service_simulation')


def _compose(data, parent):
    model, service, reqs, scenario = (data[k] for k in ('model', 'service', 'requests', 'parent_envelope'))
    arch, device, demand = (scenario[k] for k in ('architecture', 'device', 'demand'))
    for field in ('model_revision', 'tokenizer_revision'):
        if model[field] != arch[field]:
            raise Refusal('revision_mismatch', '$.model.' + field)
    weight = model['parameters'] * model['bytes_per_parameter']
    if weight > MAX_INTEGER or weight != device['resident_weights_bytes'] or weight == 0:
        raise Refusal('unsupported_weight_mapping', '$.model')
    if any(i >= len(scenario['sources']) for i in service['source_indices']):
        raise Refusal('invalid_source_index', '$.service.source_indices')
    if demand['requested_concurrency'] != len(reqs) or demand['max_resident_context_tokens'] != max(r['max_resident_context_tokens'] for r in reqs):
        raise Refusal('parent_demand_mismatch', '$.parent_envelope.demand')
    global_bytes = device['workspace_bytes'] + device['headroom_bytes']
    hbm = device['usable_hbm_bytes']
    budget = hbm - weight - global_bytes
    if weight + global_bytes > MAX_INTEGER:
        raise Refusal('derived_integer_limit')
    if parent['metrics']['kv_budget_bytes'] != budget:
        raise Refusal('bridge_consistency_violation', '$.parent_envelope')
    children, by_context = [], {}
    for i, req in enumerate(reqs):
        context = req['max_resident_context_tokens']
        if context not in by_context:
            patch = {'max_resident_context_tokens': context, 'requested_concurrency': 1}
            child = copy.deepcopy(scenario)
            child['demand'] = patch
            report = _evaluate_envelope(child, '$.derived_envelopes')
            if report['status'] != 'simulated':
                raise Refusal('bridge_consistency_violation', '$.derived_envelopes')
            metrics = report['metrics']
            if (metrics['kv_budget_bytes'] != budget or metrics['feasible'] != (metrics['kv_bytes_per_request'] <= budget)
                    or metrics['kv_bytes_per_token'] != parent['metrics']['kv_bytes_per_token']):
                raise Refusal('bridge_consistency_violation', '$.derived_envelopes')
            entry = {'parent_canonical_sha256': parent['input_sha256'], 'demand_patch': patch,
                     'child_canonical_sha256': report['input_sha256'], 'formula_version': report['formula_version'],
                     'metrics': metrics, 'request_indices': []}
            by_context[context] = len(children)
            children.append(entry)
        children[by_context[context]]['request_indices'].append(i)
    vector = [children[by_context[r['max_resident_context_tokens']]]['metrics']['kv_bytes_per_request'] for r in reqs]
    total = sum(vector)
    if total > MAX_INTEGER or abs(total - budget) > MAX_INTEGER:
        raise Refusal('derived_integer_limit')
    mapping = [{'original_index': i, 'request_id': r['request_id'], 'max_resident_context_tokens': r['max_resident_context_tokens'],
                'reservation_bytes': vector[i], 'request_declaration': copy.deepcopy(r),
                'derived_envelope_index': by_context[r['max_resident_context_tokens']]} for i, r in enumerate(reqs)]
    result = {'parent_uniform_reference': parent, 'derived_envelopes': children, 'request_mapping': mapping,
              'fixed_memory_deficit_bytes': max(0, -budget),
              'cohort_simultaneous_fit': {'feasible': total <= budget, 'required_kv_bytes': total,
                                         'kv_budget_bytes': budget, 'deficit_bytes': max(0, total - budget)},
              'individually_infeasible_ids': [r['request_id'] for r, size in zip(reqs, vector) if size > budget],
              'service_declarations': service, 'model_declarations': model,
              'source_attribution': copy.deepcopy(ATTRIBUTION), 'runtime_source_verified': False,
              'limitations': list(LIMITATIONS)}
    if budget < 0:
        return dict(result, status='infeasible', service_simulation={'status': 'not_run_fixed_memory_infeasible'})
    try:
        hardware = inference.Hardware(service['hardware_name'], service['compute_flops_s'], hbm,
                                      service['memory_bandwidth_bytes_s'], service['efficiency'])
        requests = [inference.Request(r['arrival_s'], r['input_tokens'], r['output_tokens'], r['cached_prefix_tokens']) for r in reqs]
        engine = inference.simulate(requests, hardware, parameters=model['parameters'],
                                    bytes_per_parameter=model['bytes_per_parameter'], kv_bytes_per_token=parent['metrics']['kv_bytes_per_token'],
                                    ttft_slo_s=service['ttft_slo_s'], itl_slo_s=service['itl_slo_s'], max_batch=service['max_batch'],
                                    policy=service['policy'], request_reservations_bytes=vector, workspace_headroom_bytes=global_bytes)
    except (Refusal, MemoryError):
        raise
    except Exception:
        raise Refusal('engine_contract_violation', '$.service_simulation') from None
    try:
        if type(engine) is not dict or type(engine.get('memory_accounting')) is not dict or type(engine.get('requests')) is not list:
            raise Refusal('bridge_consistency_violation', '$.service_simulation')
        accounting = engine['memory_accounting']
        expected = {'usable_hbm_bytes': hbm, 'resident_weights_bytes': weight, 'workspace_headroom_bytes': global_bytes,
                    'kv_budget_bytes': budget, 'request_reservations_bytes': vector, 'final_remaining_bytes': budget}
        rows = engine.get('requests', [])
        if (any(accounting.get(k) != v for k, v in expected.items())
                or type(accounting.get('peak_reserved_bytes')) is not int or not 0 <= accounting['peak_reserved_bytes'] <= budget
                or type(engine.get('peak_concurrency')) is not int or not 0 <= engine['peak_concurrency'] <= len(reqs)
                or any(type(r) is not dict for r in rows)
                or len(rows) != len(reqs) or [r.get('id') for r in rows] != list(range(len(reqs)))
                or any(r.get('rejected') is not (size > budget) for r, size in zip(rows, vector))):
            raise Refusal('bridge_consistency_violation', '$.service_simulation')
        if (not _finite_nonnegative(engine.get('makespan_s'))
                or any(not _finite_nonnegative(row.get(key))
                       for row in rows if not row['rejected']
                       for key in ('ttft_s', 'max_itl_s'))):
            raise Refusal('bridge_consistency_violation', '$.service_simulation')
        _timing_invariants(reqs, service, engine)
        result['timing_precision'] = _timing_precision(reqs, service, engine)
        result['simulated_admission'] = {'peak_reserved_bytes': accounting['peak_reserved_bytes'], 'peak_concurrency': engine['peak_concurrency'],
                                        'final_remaining_bytes': accounting['final_remaining_bytes'],
                                        'completed_ids': [mapping[r['id']]['request_id'] for r in rows if not r['rejected']],
                                        'rejected_ids': [mapping[r['id']]['request_id'] for r in rows if r['rejected']]}
        result['service_simulation'] = dict(engine, status='simulated')
        return dict(result, status='simulated')
    except (Refusal, MemoryError):
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
        raise Refusal('bridge_consistency_violation', '$.service_simulation') from None


def _bounded_result(result):
    code = 'output_size_limit'
    try:
        if len(_canonical(result)) + 1 <= MAX_OUTPUT_BYTES:
            return result
    except (TypeError, ValueError, OverflowError, RecursionError):
        code = 'bridge_consistency_violation'
    # Keep only bounded identity fields, never partial simulation results.
    identities = {key: result[key] for key in ('raw_input_sha256', 'canonical_input_sha256')
                  if type(result.get(key)) is str and re.fullmatch('[0-9a-f]{64}', result[key])}
    identities['schema'] = RESULT_SCHEMA
    refusal = _refused(code, **identities)
    return refusal if len(_canonical(refusal)) + 1 <= MAX_OUTPUT_BYTES else _refused(code, schema=identities['schema'])


def evaluate_bytes(raw):
    """Evaluate bounded JSON; raw and canonical identities are explicitly distinct."""
    if type(raw) is not bytes:
        return _refused('expected_bytes')
    if len(raw) > MAX_BYTES:
        return _refused('input_size_limit')
    base = {'schema': RESULT_SCHEMA, 'raw_input_sha256': _digest(raw)}
    try:
        def pairs(items):
            out = {}
            for key, value in items:
                if key in out:
                    raise Refusal('duplicate_key')
                out[key] = value
            return out
        def constant(value):
            raise Refusal('nonfinite_number')
        text = raw.decode('utf-8')
        # Scan before the JSON parser to bound nesting even for malformed text.
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
        data = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        _structure(data)
        base['canonical_input_sha256'] = _digest(_canonical(data))
    except Refusal as exc:
        return _refused(exc.code, exc.path, **base)
    except (UnicodeError, ValueError, RecursionError, OverflowError):
        return _refused('invalid_json', **base)
    try:
        missing, parent = _validate(data)
        if missing:
            return _bounded_result(dict(base, status='insufficient_evidence', missing_paths=missing,
                                        parent_uniform_reference=parent, runtime_source_verified=False))
        return _bounded_result(dict(base, **_compose(data, parent)))
    except Refusal as exc:
        return _refused(exc.code, exc.path, **base)


def evaluate(scenario):
    """Object API uses canonical bytes as its input identity; no original file inferred."""
    try:
        _structure(scenario)
        raw = _canonical(scenario)
    except Refusal as exc:
        return _refused(exc.code, exc.path)
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        return _refused('invalid_json_object')
    return evaluate_bytes(raw)


def read_scenario(path):
    """Caller owns the raw descriptor; stream cleanup precedes exactly one raw close."""
    try:
        if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_NONBLOCK'):
            raise Refusal('unsupported_platform')
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except ValueError:
            raise Refusal('input_unreadable') from None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise Refusal('expected_regular_file')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                result = evaluate_bytes(stream.read(MAX_BYTES + 1))
        finally:
            os.close(fd)
        return result
    except (OSError, Refusal) as exc:
        return _refused(exc.code if isinstance(exc, Refusal) else 'input_unreadable')


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    result = read_scenario(args[0]) if len(args) == 1 else _refused('expected_one_input_path')
    result = _bounded_result(result)
    payload = _canonical(result).decode('utf-8')
    print(payload)
    return 0 if result['status'] in ('simulated', 'infeasible') else 2


if __name__ == '__main__':
    sys.exit(main())
