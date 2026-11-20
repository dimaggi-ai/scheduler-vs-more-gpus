"""Synthetic arithmetic, protected-context mutations and actual CLI journeys."""
import copy
import hashlib
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from capacity import kv_compare as compare
from capacity.kv_envelope import MAX_INTEGER

ROOT = Path(__file__).resolve().parents[2]


class KVCompareTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'examples/kv-compare.json').read_text())

    def test_hand_oracle_both_references(self):
        out = compare.evaluate(self.data)
        self.assertEqual(out['status'], 'compared')
        self.assertEqual(out['deltas']['candidate_minus_baseline']['requested_kv_bytes'], -3932160)
        self.assertEqual(out['deltas']['candidate_minus_baseline']['remaining_bytes'], 3932160)
        self.assertEqual(out['deltas']['candidate_minus_active']['remaining_bytes'], 3932161)
        self.assertEqual(out['reports']['baseline']['metrics']['remaining_bytes'], 0)
        self.assertEqual(out['reports']['active']['metrics']['deficit_bytes'], 1)
        self.assertEqual(out['changed_declarations_vs_baseline']['candidate']['allocation']['candidate']['block_tokens'], 1)
        self.assertEqual(out['authenticity'], 'not_established')
        digest = out.pop('result_sha256')
        self.assertEqual(digest, hashlib.sha256(compare._canonical(out)).hexdigest())

    def test_nonfinite_object_cause_and_path(self):
        for value in (float('inf'), float('-inf'), float('nan')):
            with self.subTest(value=value):
                out = compare.evaluate({'schema': value})
                self.assertEqual(out['code'], 'nonfinite_number')
                self.assertEqual(out['path'], '$.schema')
                data = copy.deepcopy(self.data)
                data['candidate']['device']['workspace_bytes'] = value
                out = compare.evaluate(data)
                self.assertEqual(out['code'], 'nonfinite_number')
                self.assertEqual(out['path'], '$.candidate.device.workspace_bytes')
        data = copy.deepcopy(self.data)
        data['active']['assumptions'][1] = float('inf')
        self.assertEqual(compare.evaluate(data)['path'], '$.active.assumptions[1]')
        raw = json.dumps(self.data).replace('"workspace_bytes": 2097152',
                                           '"workspace_bytes": 1e400', 1).encode()
        out = compare.evaluate_bytes(raw)
        self.assertEqual(out['code'], 'nonfinite_number')
        self.assertEqual(out['path'], '$.baseline.device.workspace_bytes')
        self.assertEqual(compare.evaluate({'schema': '\ud800'})['code'], 'invalid_json_object')
        self.assertEqual(compare.evaluate_bytes(None)['code'], 'expected_bytes')

    def test_escaped_scenario_limit_is_preserved_and_documented(self):
        from capacity import kv_envelope
        data = copy.deepcopy(self.data)
        data['candidate']['assumptions'] = ['界' * 512] * 22
        utf8 = compare._canonical(data['candidate'])
        escaped = json.dumps(data['candidate'], sort_keys=True, separators=(',', ':')).encode()
        self.assertLess(len(utf8), kv_envelope.MAX_BYTES)
        self.assertGreater(len(escaped), kv_envelope.MAX_BYTES)
        self.assertEqual(kv_envelope.evaluate_bytes(utf8)['status'], 'simulated')
        self.assertEqual(kv_envelope.evaluate(data['candidate'])['code'], 'input_size_limit')
        for result in (compare.evaluate(data), compare.evaluate_bytes(compare._canonical(data))):
            self.assertEqual(result['status'], 'refused')
            self.assertEqual(result['errors'][0]['code'], 'input_size_limit')
            self.assertEqual(result['errors'][0]['path'], '$.candidate')
        data['candidate']['assumptions'] = ['界' * 512] * 20
        self.assertEqual(compare.evaluate(data)['status'], 'compared')
        self.assertEqual(compare.evaluate_bytes(compare._canonical(data))['status'], 'compared')

    def test_same_controls(self):
        for name in ('active', 'candidate'):
            self.data[name] = copy.deepcopy(self.data['baseline'])
        out = compare.evaluate(self.data)
        self.assertTrue(all(v == 0 for d in out['deltas'].values() for v in d.values()))
        self.assertEqual(out['changed_declarations_vs_baseline'], {'active': {}, 'candidate': {}})

    def test_every_architecture_and_demand_field_both_lanes(self):
        for lane in ('active', 'candidate'):
            for group in ('architecture', 'demand'):
                for key, original in self.data[lane][group].items():
                    data = copy.deepcopy(self.data)
                    value = original + 1 if type(original) is int else original + ' '
                    if key in ('k_bits', 'v_bits'):
                        value = 8
                    data[lane][group][key] = value
                    out = compare.evaluate(data)
                    with self.subTest(lane=lane, group=group, key=key):
                        # Unsupported kinds fail their own contract, never compare.
                        self.assertIn(out['status'], ('refused', 'not_comparable'))
                        self.assertNotIn('deltas', out)
                        if out['status'] == 'not_comparable':
                            self.assertIn(f'$.{lane}.{group}.{key}', out['mismatch_paths'])

    def test_evidence_kind_mutation_refused(self):
        for name in compare.NAMES:
            data = copy.deepcopy(self.data)
            data[name]['evidence_kind'] = 'measured'
            self.assertEqual(compare.evaluate(data)['status'], 'refused')

    def test_missing_and_null_then_corrected_retry(self):
        for name in compare.NAMES:
            data = copy.deepcopy(self.data)
            data[name]['device']['workspace_bytes'] = None
            out = compare.evaluate(data)
            self.assertEqual(out['status'], 'insufficient_evidence')
            self.assertIn(f'$.{name}.device.workspace_bytes', out['missing_paths'])
            data[name]['device']['workspace_bytes'] = 0
            self.assertEqual(compare.evaluate(data)['status'], 'compared')
        del self.data['active']
        self.assertEqual(compare.evaluate(self.data)['missing_paths'], ['$.active'])

    def test_malformed_overrides_other_lane_missing(self):
        del self.data['baseline']
        self.data['candidate']['device']['workspace_bytes'] = True
        self.assertEqual(compare.evaluate(self.data)['status'], 'refused')

    def test_unknown_report_input_and_schema(self):
        for key, value in [('reports', {}), ('schema', 'other')]:
            data = copy.deepcopy(self.data)
            data[key] = value
            self.assertEqual(compare.evaluate(data)['status'], 'refused')
        self.data['active'] = compare.evaluate(self.data)
        self.assertEqual(compare.evaluate(self.data)['status'], 'refused')

    def test_infeasible_candidate_is_comparable(self):
        self.data['candidate']['device']['usable_hbm_bytes'] = 1
        out = compare.evaluate(self.data)
        self.assertEqual(out['status'], 'compared')
        self.assertFalse(out['reports']['candidate']['metrics']['feasible'])
        self.assertLess(out['deltas']['candidate_minus_baseline']['remaining_bytes'], 0)

    def test_signed_delta_overflow(self):
        for name in compare.NAMES:
            s = self.data[name]
            s['architecture'].update(layers=1, kv_heads=1, head_dimension=1, k_bits=8, v_bits=8)
            s['allocation'].update(block_tokens=1, metadata_bytes_per_block=0, overhead_bytes_per_request=0)
            s['demand'].update(max_resident_context_tokens=1, requested_concurrency=1)
            s['device'].update(usable_hbm_bytes=1, resident_weights_bytes=MAX_INTEGER-2,
                               workspace_bytes=0, headroom_bytes=0)
        self.data['candidate']['device'].update(usable_hbm_bytes=MAX_INTEGER, resident_weights_bytes=0)
        out = compare.evaluate(self.data)
        self.assertEqual(out['code'], 'delta_integer_limit')
        self.assertEqual(out['path'], '$.deltas.candidate_minus_baseline')
        self.data['baseline'] = copy.deepcopy(self.data['candidate'])
        second = compare.evaluate(self.data)
        self.assertEqual(second['code'], 'delta_integer_limit')
        self.assertEqual(second['path'], '$.deltas.candidate_minus_active')
        self.assertNotIn('deltas', out)

    def test_signed_delta_boundary(self):
        for name in compare.NAMES:
            self.data[name] = copy.deepcopy(self.data['baseline'])
        self.data['candidate']['device']['usable_hbm_bytes'] -= 1
        out = compare.evaluate(self.data)
        self.assertEqual(out['deltas']['candidate_minus_active']['remaining_bytes'], -1)
        self.assertEqual(out['deltas']['candidate_minus_active']['deficit_bytes'], 1)

    def test_changed_sources_assumptions_and_input_identity(self):
        self.data['candidate']['sources'][0]['revision'] = 'unverified-other'
        self.data['active']['assumptions'].reverse()
        raw = json.dumps(self.data).encode()
        out = compare.evaluate_bytes(raw)
        self.assertEqual(out['input_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertIn('sources', out['changed_declarations_vs_baseline']['candidate'])
        self.assertIn('assumptions', out['changed_declarations_vs_baseline']['active'])
        self.assertEqual(out['qualification'], 'not_established')
        snapshot = copy.deepcopy(out)
        self.data['candidate']['sources'][0]['revision'] = 'changed-after-evaluation'
        self.assertEqual(out, snapshot)

    def test_duplicate_nonfinite_deep_size_and_counts(self):
        raw = json.dumps(self.data).encode()
        duplicate = raw.replace(b'"block_tokens": 16', b'"block_tokens": 16, "block_tokens": 1', 1)
        for value in [duplicate, b'{"schema":NaN}', b'[' * 1000, b' ' * (compare.MAX_BYTES+1), b'\xff']:
            self.assertEqual(compare.evaluate_bytes(value)['status'], 'refused')
        self.assertEqual(compare.evaluate([0] * 4000)['status'], 'refused')
        self.assertEqual(compare.evaluate({'schema': float('inf')})['status'], 'refused')
        circular = {}; circular['self'] = circular
        self.assertEqual(compare.evaluate(circular)['status'], 'refused')

    def test_in_process_cli_nul_path(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = compare.main(['bad\x00path'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())['code'], 'input_file_refused')

    def test_cli_success_refusal_recovery_and_file_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bundle.json'
            def run(p):
                proc = subprocess.run([sys.executable, '-m', 'capacity.kv_compare', str(p)],
                                      cwd=ROOT, capture_output=True, text=True, timeout=10)
                return proc.returncode, json.loads(proc.stdout)
            path.write_text(json.dumps(self.data))
            code, out = run(path)
            self.assertEqual((code, out['status']), (0, 'compared'))
            path.write_text('{')
            self.assertEqual(run(path)[0], 2)
            path.write_text(json.dumps(self.data))
            self.assertEqual(run(path)[0], 0)
            link = Path(directory) / 'alias'; link.symlink_to(path)
            self.assertEqual(run(link)[1]['code'], 'input_file_refused')
            self.assertEqual(run(directory)[1]['code'], 'input_file_refused')
            self.assertEqual(run(Path(directory) / 'absent')[0], 2)
            path.write_bytes(b'x' * (compare.MAX_BYTES+1))
            self.assertEqual(run(path)[1]['code'], 'input_size_limit')


if __name__ == '__main__':
    unittest.main()
