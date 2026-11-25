"""Boundary and CLI regression tests; standard library only."""
import contextlib
import dataclasses
import io
import json
import math
import subprocess
import sys
import unittest
from pathlib import Path

from stranded_capacity import LEGACY_PRESET_ALIASES, PRESETS, Scenario, compute, main


class CalculatorValidation(unittest.TestCase):
    def scenario(self, **changes):
        return dataclasses.replace(Scenario('test', 'synthetic assumptions', 10, 100.0), **changes)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(Path(__file__).with_name('stranded_capacity.py')),
                               *args], capture_output=True, text=True, timeout=10)

    def test_each_explicit_flag_overrides_preset_without_mutation(self):
        original = {name: dataclasses.asdict(value) for name, value in PRESETS.items()}
        fields = dict(gpus=('4096', '123'), window_hours=('720', '24'), hard_outage_hours=('0', '2'),
                      degraded_hours=('0', '2'), degradation_weight=('0.15', '0.5'),
                      allocation_efficiency=('1.0', '0.5'), productive_ratio=('1.0', '0.6'),
                      usd_per_gpu_hour=('2.00', '3.5'))
        # Several explicit values equal custom defaults. They must still override
        # the selected preset rather than being mistaken for omitted arguments.
        for field, values in fields.items():
            for value in values:
                with self.subTest(field=field):
                    out, err = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        code = main(['--preset', 'typical-composite', '--' + field.replace('_', '-'), value, '--json'])
                    self.assertEqual(code, 0, err.getvalue())
                    scenario = json.loads(out.getvalue())['scenario']
                    self.assertEqual(scenario[field], float(value))
                    self.assertIn('Assumption-derived overrides', scenario['description'])
                    self.assertIn(field, scenario['description'])
                    self.assertEqual(scenario['name'], 'typical-composite-overridden')
                    for other in fields.keys() - {field}:
                        self.assertEqual(scenario[other], getattr(PRESETS['typical-composite'], other))
        self.assertEqual({name: dataclasses.asdict(value) for name, value in PRESETS.items()}, original)

    def test_combined_override_and_alias(self):
        for name in ('alibaba-with-interruptible', 'alibaba-allocation-after'):
            run = self.cli('--preset', name, '--gpus', '4096', '--allocation-efficiency', '0.5', '--json')
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            self.assertEqual(result['scenario']['gpus'], 4096)
            self.assertEqual(result['scenario']['allocation_efficiency'], .5)
            self.assertEqual(result['result']['usable_gpu_hours'], 4096 * 720 * .5)
            self.assertEqual(result['scenario']['name'], 'alibaba-with-interruptible-overridden')

    def test_omitted_flags_preserve_presets_and_aliases(self):
        for name, scenario in PRESETS.items():
            with self.subTest(name=name):
                run = self.cli('--preset', name, '--json')
                expected = json.dumps(dict(scenario=dataclasses.asdict(scenario),
                                           result=compute(scenario).as_dict()), indent=2) + '\n'
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(run.stdout, expected)
        for alias, canonical in LEGACY_PRESET_ALIASES.items():
            self.assertIs(PRESETS[alias], PRESETS[canonical])

    def test_custom_defaults_preserved(self):
        run = self.cli('--gpus', '10', '--json')
        self.assertEqual(run.returncode, 0, run.stderr)
        expected = Scenario('custom', 'custom scenario from CLI flags', 10, 720.0)
        self.assertEqual(json.loads(run.stdout)['scenario'], dataclasses.asdict(expected))
        self.assertEqual(json.loads(run.stdout)['result']['nominal_gpu_hours'], 7200.0)

    def test_numeric_api_boundaries_and_mutated_objects(self):
        fields = ('gpus', 'window_hours', 'hard_outage_hours', 'degraded_hours',
                  'degradation_weight', 'allocation_efficiency', 'productive_ratio', 'usd_per_gpu_hour')
        for field in fields:
            for bad in (True, False, float('nan'), float('inf'), -float('inf'), '1', None):
                with self.subTest(field=field, bad=bad):
                    scenario = self.scenario()
                    object.__setattr__(scenario, field, bad)
                    with self.assertRaises(ValueError): compute(scenario)
                    with self.assertRaises(ValueError): scenario.availability()
        for field, bad in [('gpus', 0), ('gpus', -1), ('gpus', 1.5), ('gpus', 10**400),
                           ('window_hours', 0), ('window_hours', -1), ('hard_outage_hours', -1),
                           ('degraded_hours', -1), ('usd_per_gpu_hour', -1),
                           ('degradation_weight', -0.1), ('degradation_weight', 1.1),
                           ('allocation_efficiency', -0.1), ('allocation_efficiency', 1.1),
                           ('productive_ratio', -0.1), ('productive_ratio', 1.1)]:
            with self.subTest(field=field, bad=bad):
                with self.assertRaises(ValueError): compute(self.scenario(**{field: bad}))
        with self.assertRaises(ValueError): compute(object())

    def test_weighted_loss_conservation_and_overlapping_duration_semantics(self):
        # The model constrains weighted loss, not raw sum or disjoint windows.
        scenario = self.scenario(hard_outage_hours=25, degraded_hours=150,
                                 degradation_weight=.5, allocation_efficiency=.3,
                                 productive_ratio=.4)
        result = compute(scenario)
        self.assertEqual(result.availability, 0)
        self.assertEqual(result.loss_scheduler, 1000)
        self.assertEqual(result.usable_gpu_hours, 0)
        with self.assertRaises(ValueError): compute(dataclasses.replace(scenario, hard_outage_hours=26))
        for a in (0, .1, 1):
            for e in (0, .3, 1):
                for p in (0, .6, 1):
                    r = compute(self.scenario(hard_outage_hours=100*(1-a), allocation_efficiency=e, productive_ratio=p))
                    self.assertTrue(math.isclose(r.usable_gpu_hours+r.stranded_gpu_hours, r.nominal_gpu_hours))
                    self.assertTrue(all(math.isfinite(v) and v >= 0 for v in r.as_dict().values()))
        self.assertEqual(compute(self.scenario(degraded_hours=1000, degradation_weight=0)).availability, 1)

    def test_overflow_and_finite_extremes(self):
        for changes in (dict(gpus=10**308, window_hours=1e308),
                        dict(gpus=1, window_hours=1e308, hard_outage_hours=1e308, usd_per_gpu_hour=2),
                        dict(window_hours=1e308, hard_outage_hours=10**308, degraded_hours=10**308, degradation_weight=1)):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError): compute(self.scenario(**changes))
        result = compute(self.scenario(gpus=1, window_hours=1e308, usd_per_gpu_hour=0))
        self.assertEqual(result.nominal_gpu_hours, 1e308)
        self.assertEqual(result.stranded_usd, 0)
        self.assertTrue(math.isfinite(compute(self.scenario(window_hours=5e-324)).nominal_gpu_hours))

    def test_cli_refusal_and_corrected_recovery(self):
        cases = [('--window-hours', 'nan'), ('--hard-outage-hours', '-1'),
                 ('--degraded-hours', 'inf'), ('--usd-per-gpu-hour', '-1'),
                 ('--degradation-weight', '2'), ('--window-hours', '0'),
                 ('--gpus', '0'), ('--gpus', '-1'), ('--window-hours', '1e308')]
        for flag, value in cases:
            with self.subTest(flag=flag, value=value):
                run = self.cli('--gpus', '10', flag, value, '--json')
                self.assertEqual(run.returncode, 2)
                self.assertEqual(run.stdout, '')
                self.assertTrue(run.stderr.startswith('REFUSE:'), run.stderr)
                self.assertNotIn('Traceback', run.stderr)
        run = self.cli('--gpus', '10', '--hard-outage-hours', '1', '--json')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertLessEqual(json.loads(run.stdout)['result']['availability'], 1)
        self.assertNotIn('NaN', run.stdout)
        self.assertNotIn('Infinity', run.stdout)


if __name__ == '__main__':
    unittest.main()
