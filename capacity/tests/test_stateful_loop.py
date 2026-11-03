import itertools
import unittest
from dataclasses import replace

from capacity.stateful_loop import (Stage, Loop, SyntheticProvenance, analyze, compare,
                                    MAX_STAGES, MAX_ITERATIONS)


def fixture():
    return Loop((Stage('host', 'host', 8, source_id='host-fixture'), Stage('compute', 'compute', 4, ('host',), source_id='stage-fixture'),
                 Stage('memory', 'memory', 2, ('host',), source_id='stage-fixture'),
                 Stage('fabric', 'fabric', 6, ('host',), source_id='stage-fixture'),
                 Stage('persist', 'state', 2, ('compute', 'memory', 'fabric'), source_id='state-fixture')),
                'persist', 3, 'synthetic-loop', 'fixed-quality', 'v1',
                SyntheticProvenance('hand-authored-v1', 'inline synthetic test', 'MIT',
                                    '2026-11-03', 'declared-fixture-revision-v1'))


def durations(loop, **changes):
    return replace(loop, stages=tuple(replace(s, duration_seconds=changes.get(s.id, s.duration_seconds))
                                     for s in loop.stages))


class StatefulLoopTests(unittest.TestCase):
    def test_success_and_sequential_persistence(self):
        result = analyze(fixture())
        self.assertEqual((result.elapsed_lower_bound_s, result.total_lower_bound_s), (16, 48))
        self.assertEqual(result.critical_path, ('host', 'fabric', 'persist'))

    def test_compute_only_no_benefit_and_joint_benefit(self):
        base = fixture()
        self.assertEqual(compare(base, durations(base, compute=1)).lower_bound_speedup, 1)
        self.assertEqual(compare(base, durations(base, host=4, fabric=3)).candidate.total_lower_bound_s, 30)
        self.assertEqual(compare(base, durations(base, host=4, fabric=3, compute=2)).candidate.total_lower_bound_s, 27)

    def test_delay_is_not_optimization(self):
        self.assertLess(compare(fixture(), durations(fixture(), persist=20)).lower_bound_speedup, 1)
        self.assertLess(compare(fixture(), durations(fixture(), persist=20)).lower_bound_saved_seconds, 0)

    def test_permutations_and_ties(self):
        base = durations(fixture(), compute=6)
        expected = analyze(base)
        self.assertEqual(expected.critical_path, ('host', 'compute', 'persist'))
        for order in itertools.permutations(base.stages):
            reordered = replace(base, stages=tuple(replace(s, dependencies=tuple(reversed(s.dependencies))) for s in order))
            self.assertEqual(analyze(reordered), expected)
            self.assertEqual(compare(base, reordered).lower_bound_speedup, 1)

    def test_zero_refused(self):
        with self.assertRaises(ValueError): analyze(durations(fixture(), memory=0))
        self.assertEqual(analyze(fixture()).total_lower_bound_s, 48)

    def test_unknown_refusal_and_correction(self):
        with self.assertRaises(ValueError):
            analyze(durations(fixture(), host=None))
        self.assertEqual(analyze(fixture()).total_lower_bound_s, 48)

    def test_bad_durations(self):
        for value in (True, False, -1, float('nan'), float('inf'), -float('inf'), '2', 10**1000):
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError):
                analyze(durations(fixture(), host=value))

    def test_iteration_bounds(self):
        for value in (True, 0, -1, 1.0, MAX_ITERATIONS+1):
            with self.assertRaises(ValueError):
                analyze(replace(fixture(), iterations=value))
        self.assertEqual(analyze(replace(fixture(), iterations=MAX_ITERATIONS)).total_lower_bound_s, 16*MAX_ITERATIONS)

    def test_overflow_paths_totals_and_ratio(self):
        for loop in (durations(fixture(), host=1e308, fabric=1e308),
                     durations(fixture(), host=1e308)):
            with self.assertRaises(ValueError):
                analyze(loop)
        tiny = durations(fixture(), **{s.id: 5e-324 for s in fixture().stages})
        with self.assertRaises(ValueError):
            compare(fixture(), tiny)

    def test_duplicates_missing_and_invalid_dependencies(self):
        base = fixture()
        variants = [replace(base, stages=base.stages+(base.stages[0],)),
                    replace(base, stages=(replace(base.stages[0], dependencies=('missing',)),)+base.stages[1:]),
                    replace(base, stages=(replace(base.stages[0], dependencies=('host',), source_id='stage-fixture'),)+base.stages[1:]),
                    replace(base, stages=(replace(base.stages[0], dependencies=('fabric','fabric')),)+base.stages[1:])]
        for loop in variants:
            with self.assertRaises(ValueError): analyze(loop)

    def test_disconnected_and_omitted_state(self):
        base = fixture()
        for loop in (replace(base, stages=base.stages+(Stage('extra','host',1, source_id='extra'),)),
                     replace(base, persisted_completion_id='compute'),
                     replace(base, persisted_completion_id='absent'),
                     replace(base, stages=tuple(replace(s, kind='compute') if s.kind=='state' else s for s in base.stages))):
            with self.assertRaises(ValueError): analyze(loop)

    def test_comparison_rejects_substitutions(self):
        base = fixture()
        for name, value in [('workload','other'), ('quality','other'), ('protocol','other'),
                            ('iterations',4), ('provenance',replace(base.provenance, fixture_id='other'))]:
            with self.assertRaises(ValueError): compare(base, replace(base, **{name:value}))
        # Both graphs valid, but changed edges are not a duration-only intervention.
        changed = replace(base, stages=tuple(replace(s, dependencies=('host','memory')) if s.id=='fabric' else s for s in base.stages))
        with self.assertRaises(ValueError): compare(base, changed)

    def test_bounded_shape_and_strict_types(self):
        base = fixture()
        for loop in (None, replace(base, stages=list(base.stages)), replace(base, stages=()),
                     replace(base, stages=base.stages*(MAX_STAGES+1)),
                     replace(base, quality=''), replace(base, provenance=None)):
            with self.assertRaises(ValueError): analyze(loop)
        for patch in ({'id':''}, {'kind':'gpu'}, {'dependencies':['host']}, {'dependencies':(True,)}):
            with self.assertRaises(ValueError):
                analyze(replace(base, stages=(replace(base.stages[0], **patch),)+base.stages[1:]))

    def test_missing_category_and_edge_bound(self):
        base = fixture()
        changed = tuple(replace(s, kind='compute') if s.kind == 'memory' else s for s in base.stages)
        with self.assertRaises(ValueError): analyze(replace(base, stages=changed))
        # Dense acyclic graph within node bound but over the explicit edge budget.
        stages = tuple(Stage(str(i), ('host','compute','memory','fabric','state')[i % 5],
                             1, tuple(str(j) for j in range(i)), source_id='dense') for i in range(100))
        with self.assertRaises(ValueError):
            analyze(replace(base, stages=stages, persisted_completion_id='99'))

    def test_serial_slack_hash_and_provenance(self):
        base = fixture()
        result = analyze(base)
        self.assertEqual(result.serial_sum_s, 22)
        self.assertEqual(result.total_serial_sum_s, 66)
        self.assertEqual(dict(result.stage_slack_seconds)['compute'], 2)
        self.assertEqual(dict(result.stage_slack_seconds)['memory'], 4)
        self.assertEqual(result.graph_context_sha256, analyze(durations(base, host=2)).graph_context_sha256)
        for cls in ('measured', 'model_derived', None):
            with self.assertRaises(ValueError):
                analyze(replace(base, stages=(replace(base.stages[0], provenance_class=cls),)+base.stages[1:]))
        with self.assertRaises(ValueError):
            analyze(replace(base, stages=(replace(base.stages[0], source_id=''),)+base.stages[1:]))
        self.assertEqual(analyze(base), result)

    def test_seeded_dags_bound_and_iterations(self):
        import random
        rng = random.Random(96)
        for size in range(5, 45):
            stages = []
            for i in range(size):
                deps = tuple(str(j) for j in range(i) if i == size-1 or rng.random() < .15)
                kind = 'state' if i == size-1 else ('host','compute','memory','fabric')[i % 4]
                stages.append(Stage(str(i), kind, rng.randint(1, 100), deps, source_id='synthetic-random'))
            loop = replace(fixture(), stages=tuple(stages), persisted_completion_id=str(size-1))
            result = analyze(loop)
            self.assertLessEqual(result.elapsed_lower_bound_s, result.serial_sum_s)
            self.assertEqual(result.total_lower_bound_s, 3*analyze(replace(loop, iterations=1)).elapsed_lower_bound_s)

    def test_fractional_chain_and_permutations(self):
        kinds = ('host','compute','memory','fabric','state')
        stages = tuple(Stage(str(i), kinds[i], d, (str(i-1),) if i else (), source_id='fractional')
                       for i, d in enumerate((.1,.1,.1,.3,.1)))
        loop = replace(fixture(), stages=stages, persisted_completion_id='4')
        expected = analyze(loop)
        self.assertEqual(expected.elapsed_lower_bound_s, expected.serial_sum_s)
        self.assertTrue(all(s == 0 for _, s in expected.stage_slack_seconds))
        for permutation in itertools.permutations(stages):
            self.assertEqual(analyze(replace(loop, stages=permutation)), expected)

    def test_full_input_identity_tracks_durations(self):
        base = fixture()
        changed = durations(base, compute=1)
        before, after = analyze(base), analyze(changed)
        self.assertEqual(before.graph_context_sha256, after.graph_context_sha256)
        self.assertNotEqual(before.input_sha256, after.input_sha256)
        self.assertEqual(before.input_sha256, analyze(replace(base, stages=tuple(reversed(base.stages)))).input_sha256)
        # Supplied numeric representation is retained, not a semantic identity.
        self.assertNotEqual(before.input_sha256, analyze(durations(base, host=8.0)).input_sha256)
        self.assertEqual(before.total_lower_bound_s, analyze(durations(base, host=8.0)).total_lower_bound_s)

    def test_trim_and_control_characters_refuse_then_correct(self):
        base = fixture()
        for bad in (' host', 'host ', 'h\x00ost', 'h\nost', 'h\x7fost', 'x'*513):
            for changed in (replace(base, workload=bad),
                            replace(base, provenance=replace(base.provenance, fixture_id=bad)),
                            replace(base, stages=(replace(base.stages[0], source_id=bad),)+base.stages[1:]),
                            replace(base, stages=(replace(base.stages[0], id=bad),)+base.stages[1:])):
                with self.assertRaises(ValueError): analyze(changed)
                self.assertEqual(analyze(base).total_lower_bound_s, 48)

    def test_exact_comparison_before_float_boundary(self):
        from fractions import Fraction
        kinds = ('host', 'compute', 'memory', 'fabric', 'state')
        a, b = (.3,.3,1.1,.4,.2), (.1,.3,.1,1.1,.1)
        def chain(values):
            stages = tuple(Stage(str(i), kinds[i], d, (str(i-1),) if i else (), source_id='exact')
                           for i, d in enumerate(values))
            return replace(fixture(), stages=stages, persisted_completion_id='4')
        before, after = sum(map(Fraction, a))*3, sum(map(Fraction, b))*3
        result = compare(chain(a), chain(b))
        self.assertEqual(result.lower_bound_speedup, float(before/after))
        self.assertEqual(result.lower_bound_saved_seconds, float(before-after))
        self.assertNotEqual(result.lower_bound_speedup, float(before)/float(after))
        self.assertNotEqual(result.lower_bound_saved_seconds, float(before)-float(after))

    def test_immutability(self):
        base = fixture()
        snapshot = repr(base)
        compare(base, durations(base, compute=1))
        self.assertEqual(repr(base), snapshot)


if __name__ == '__main__':
    unittest.main()
