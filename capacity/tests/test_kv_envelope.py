"""Independent arithmetic oracles and bounded CLI journeys (synthetic only)."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from capacity.kv_envelope import evaluate, evaluate_bytes, MAX_BYTES, MAX_INTEGER

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / 'examples/kv-envelope.json'


class KVEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(EXAMPLE.read_text())

    def test_oracle_exact_fit_and_concurrency(self):
        out = evaluate(self.data)
        self.assertEqual(out['status'], 'simulated')
        m = out['metrics']
        self.assertEqual(m['kv_bytes_per_token'], 131072)
        self.assertEqual(m['allocated_blocks_per_request'], 2)
        self.assertEqual(m['kv_bytes_per_request'], 4194304)
        self.assertEqual(m['kv_budget_bytes'], 8388608)
        self.assertEqual(m['max_memory_feasible_concurrency'], 2)
        self.assertEqual(m['remaining_bytes'], 0)
        self.assertTrue(m['feasible'])
        self.assertEqual(out, evaluate(copy.deepcopy(self.data)))

    def test_one_byte_short_zero_and_negative_budget(self):
        self.data['device']['usable_hbm_bytes'] -= 1
        m = evaluate(self.data)['metrics']
        self.assertFalse(m['feasible'])
        self.assertEqual(m['deficit_bytes'], 1)
        self.assertEqual(m['max_memory_feasible_concurrency'], 1)
        self.data['device']['usable_hbm_bytes'] = 8388608
        self.assertEqual(evaluate(self.data)['metrics']['max_memory_feasible_concurrency'], 0)
        self.data['device']['usable_hbm_bytes'] -= 1
        m = evaluate(self.data)['metrics']
        self.assertEqual(m['reason'], 'infeasible_non_kv_budget')
        self.assertEqual(m['kv_budget_bytes'], -1)
        self.assertEqual(m['deficit_bytes'], m['requested_kv_bytes'] + 1)

    def test_heads_precision_and_allocator_accounting(self):
        self.data['architecture']['kv_heads'] = 32
        self.assertEqual(evaluate(self.data)['metrics']['kv_bytes_per_token'], 4 * 131072)
        self.data['architecture']['kv_heads'] = 8
        self.data['architecture']['k_bits'] = 8
        self.assertEqual(evaluate(self.data)['metrics']['kv_bytes_per_token'], 98304)
        self.data['allocation']['metadata_bytes_per_block'] = 7
        self.data['allocation']['overhead_bytes_per_request'] = 11
        self.assertEqual(evaluate(self.data)['metrics']['kv_bytes_per_request'], 32 * 98304 + 14 + 11)

    def test_missing_and_zero_are_distinct_and_bad_beats_missing(self):
        del self.data['allocation']['metadata_bytes_per_block']
        out = evaluate(self.data)
        self.assertEqual(out['status'], 'insufficient_evidence')
        self.assertIn('$.allocation.metadata_bytes_per_block', out['missing_paths'])
        self.data['allocation']['metadata_bytes_per_block'] = None
        self.assertEqual(evaluate(self.data)['status'], 'insufficient_evidence')
        self.data['architecture']['k_bits'] = 4
        self.assertEqual(evaluate(self.data)['status'], 'refused')
        self.data['architecture']['k_bits'] = 16
        self.data['allocation']['metadata_bytes_per_block'] = 0
        self.assertEqual(evaluate(self.data)['status'], 'simulated')

    def test_unsupported_models_sharing_and_trace_claims(self):
        mutations = [('architecture', 'kind', 'MLA'), ('allocation', 'prefix_sharing', 'automatic'),
                     ('architecture', 'tensor_parallel', 2), ('demand', 'cached_input_tokens', 17)]
        for section, key, value in mutations:
            with self.subTest(key=key):
                data = copy.deepcopy(self.data)
                data[section][key] = value
                self.assertEqual(evaluate(data)['status'], 'refused')
        self.data['evidence_kind'] = 'trace_informed'
        self.assertEqual(evaluate(self.data)['status'], 'refused')

    def test_bad_numerics_and_derived_bounds(self):
        for value in (True, False, -1, 0, 1.5, '32', MAX_INTEGER + 1, float('inf'), float('nan')):
            with self.subTest(value=value):
                self.data['architecture']['layers'] = value
                self.assertEqual(evaluate(self.data)['status'], 'refused')
        self.data['architecture']['layers'] = MAX_INTEGER
        self.assertEqual(evaluate(self.data)['code'], 'derived_integer_limit')

    def test_duplicate_depth_size_unicode_and_structural_bounds(self):
        for raw in (b'{"schema":1,"schema":2}', b'{"x":NaN}', b'\xff', b'[' * 9 + b']' * 9,
                    b' ' * (MAX_BYTES + 1), b'[]', b'null', b'{'):
            with self.subTest(raw=raw[:40]):
                self.assertEqual(evaluate_bytes(raw)['status'], 'refused')
        data = {'x': [None] * 1025}
        self.assertEqual(evaluate(data)['status'], 'refused')
        data = {}
        data['self'] = data
        self.assertEqual(evaluate(data)['status'], 'refused')
        self.assertEqual(evaluate({1: 'converted-key'})['status'], 'refused')

    def test_provenance_validation_and_exact_digest(self):
        raw = EXAMPLE.read_bytes()
        self.assertEqual(evaluate_bytes(raw)['input_sha256'], hashlib.sha256(raw).hexdigest())
        for key, value in [('sha256', 'x' * 64), ('retrieved_at', '2026-02-30'), ('uri', 'file:///secret'),
                           ('uri', 'https://user:secret@example.com'), ('uri', 'https:///missing-host'),
                           ('uri', 'https://example.com:bad'), ('uri', 'https://[broken')]:
            data = copy.deepcopy(self.data)
            data['sources'][0][key] = value
            self.assertEqual(evaluate(data)['status'], 'refused')
        before = copy.deepcopy(self.data)
        evaluate(self.data)
        self.assertEqual(self.data, before)

    def test_domain_labels_never_qualify(self):
        for label in ('Synthetic defence logistics', 'Synthetic health IT continuity', 'Synthetic finance reporting'):
            self.data['scenario_label'] = label
            out = evaluate(self.data)
            self.assertEqual(out['status'], 'simulated')
            self.assertIn('operational_qualification', out['not_evaluated'])
            self.assertIn('latency', out['not_evaluated'])

    def test_cli_success_refusal_recovery_and_file_guards(self):
        def run(path):
            proc = subprocess.run([sys.executable, '-m', 'capacity.kv_envelope', str(path)], cwd=ROOT,
                                  capture_output=True, text=True, timeout=10)
            return proc.returncode, json.loads(proc.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'scenario.json'
            path.write_text('{}')
            self.assertEqual(run(path)[1]['status'], 'insufficient_evidence')
            path.write_text('{broken')
            self.assertEqual(run(path)[0], 2)
            path.write_bytes(EXAMPLE.read_bytes())
            before = path.read_bytes()
            self.assertEqual(run(path)[0], 0)
            self.assertEqual(path.read_bytes(), before)
            link = Path(tmp) / 'link'
            link.symlink_to(path)
            self.assertEqual(run(link)[1]['status'], 'refused')
            self.assertEqual(run(tmp)[0], 2)
            self.assertEqual(run(Path(tmp) / 'absent')[0], 2)
            fifo = Path(tmp) / 'pipe'
            os.mkfifo(fifo)
            self.assertEqual(run(fifo)[0], 2)
            path.write_bytes(b' ' * (MAX_BYTES + 1))
            self.assertEqual(run(path)[1]['code'], 'input_size_limit')


if __name__ == '__main__':
    unittest.main()
