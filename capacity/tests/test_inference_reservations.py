"""Synthetic, independent memory oracles; no serving or domain qualification."""
import copy
import math
import random
import unittest
from capacity.inference import Hardware, Request, simulate, MAX_EXACT_BYTES


def hw(hbm=216, compute=1000, bandwidth=1000, efficiency=1):
    return Hardware('synthetic', compute, hbm, bandwidth, efficiency)


def run(requests, reservations, hbm=216, global_bytes=50, **kwargs):
    return simulate(requests, hw(hbm), parameters=5, bytes_per_parameter=2,
                    kv_bytes_per_token=2, request_reservations_bytes=reservations,
                    workspace_headroom_bytes=global_bytes, **kwargs)


class ReservationTests(unittest.TestCase):
    def assert_accounting(self, result, budget, vector):
        a = result['memory_accounting']
        self.assertEqual(a['kv_budget_bytes'], budget)
        self.assertEqual(a['request_reservations_bytes'], vector)
        self.assertEqual(a['final_remaining_bytes'], budget)
        self.assertLessEqual(a['peak_reserved_bytes'], budget)
        self.assertGreaterEqual(a['peak_reserved_bytes'], 0)

    def test_full_fit_one_byte_short_and_queue_completion(self):
        requests = [Request(0,16,1)] * 2
        a = run(requests, [78,78]); b = run(requests, [78,78], hbm=215)
        self.assertEqual((a['peak_concurrency'], b['peak_concurrency']), (2,1))
        self.assert_accounting(a,156,[78,78]); self.assert_accounting(b,155,[78,78])
        self.assertEqual(a['memory_accounting']['peak_reserved_bytes'],156)
        self.assertFalse(any(r['rejected'] for r in b['requests']))
        four = run(requests*2,[78]*4,hbm=166,global_bytes=0)
        self.assertEqual(four['peak_concurrency'],2)
        self.assertFalse(any(r['rejected'] for r in four['requests']))

    def test_heterogeneous_original_order_and_exact_release(self):
        staggered = run([Request(2,16,1),Request(0,15,1)],[78,44],hbm=182)
        self.assert_accounting(staggered,122,[78,44])
        self.assertEqual(staggered['memory_accounting']['peak_reserved_bytes'],78)
        # If sorting accidentally swaps the vector, request0 is wrongly rejected.
        out = run([Request(2,16,1),Request(0,15,1)],[124,44],hbm=182)
        self.assertEqual([r['rejected'] for r in out['requests']],[True,False])
        requests = [Request(0,16,1),Request(0,15,1)]
        for hbm, peak in ((182,2),(181,1)):
            out = run(requests,[78,44],hbm=hbm)
            self.assertEqual(out['peak_concurrency'],peak)
            self.assert_accounting(out,hbm-60,[78,44])

    def test_raw_service_timing_and_global_capacity_only(self):
        requests = [Request(0,31,1)]*2
        args = dict(parameters=5,bytes_per_parameter=2,kv_bytes_per_token=2)
        legacy = simulate(requests,hw(138),**args)
        explicit = simulate(requests,hw(138),request_reservations_bytes=[64,64],**args)
        overhead = run(requests,[74,74],hbm=208)
        for out in (legacy,explicit,overhead):
            self.assertAlmostEqual(out['requests'][0]['ttft_s'],.754)
            self.assertEqual(out['requests'],legacy['requests'])
            self.assertEqual(out['makespan_s'],legacy['makespan_s'])
        self.assertNotIn('memory_accounting',legacy)
        self.assert_accounting(overhead,148,[74,74])

    def test_fixed_budget_boundary_and_legacy_boundary(self):
        req=[Request(0,1,1)]
        out=run(req,[4],hbm=60)
        self.assert_accounting(out,0,[4]); self.assertTrue(out['requests'][0]['rejected'])
        self.assertEqual(out['makespan_s'],0)
        with self.assertRaises(ValueError): run(req,[4],hbm=59)
        with self.assertRaises(ValueError): simulate(req,hw(10),parameters=5)
        out=run(req,[4],hbm=10,global_bytes=0)
        self.assert_accounting(out,0,[4])

    def test_fully_reserved_scenario_runs_no_service_arithmetic(self):
        out = simulate([Request(0,1,1)], hw(10,compute=5e-324), parameters=5,
                       kv_bytes_per_token=2, request_reservations_bytes=[4])
        self.assertTrue(out['requests'][0]['rejected'])
        self.assert_accounting(out,0,[4])

    def test_fcfs_head_of_line_and_prefix_invariance(self):
        req=[Request(0,1,3),Request(0,1,1),Request(0,1,1)]
        # Budget10: first8 blocks next8 although final4 could fit; do not bypass.
        out=run(req,[8,8,4],hbm=70)
        self.assertEqual(out['peak_concurrency'],1)
        self.assertLess(out['requests'][1]['ttft_s'],out['requests'][2]['ttft_s'])
        uncached=run([Request(0,16,1)]*2,[78]*2)
        cached=run([Request(0,16,1,16)]*2,[78]*2)
        self.assertEqual(uncached['memory_accounting'],cached['memory_accounting'])
        self.assertLess(cached['requests'][0]['ttft_s'],uncached['requests'][0]['ttft_s'])

    def test_random_rejection_equivalence_conservation_both_policies(self):
        rng=random.Random(717)
        for policy in ('decode-first','prefill-first'):
            for _ in range(100):
                req=[Request(rng.choice((0,1,2)),rng.randint(1,20),rng.randint(1,5)) for _ in range(rng.randint(1,12))]
                vector=[2*(r.input_tokens+r.output_tokens)+rng.randint(0,80) for r in req]
                budget=rng.randint(0,200)
                out=run(req,vector,hbm=60+budget,policy=policy,max_batch=rng.randint(1,8))
                self.assertEqual([r['id'] for r in out['requests']],list(range(len(req))))
                self.assertEqual([r['rejected'] for r in out['requests']],[v>budget for v in vector])
                self.assert_accounting(out,budget,vector)
                for r in out['requests']:
                    if not r['rejected']: self.assertEqual(r['output_tokens'],req[r['id']].output_tokens)

    def test_validation_and_corrected_recovery(self):
        req=[Request(0,1,1)]
        for invalid in (None, {}, object(), 'request'):
            with self.subTest(invalid=repr(invalid)), self.assertRaises(ValueError):
                run([invalid],[4])
        for vector in (None, [], [4,4], [True], [4.0], [0], [-1], [3], [float('nan')], iter([4])):
            with self.subTest(vector=repr(vector)), self.assertRaises(ValueError): run(req,vector)
        for g in (-1,True,1.0,float('inf'),MAX_EXACT_BYTES+1):
            with self.subTest(global_bytes=g),self.assertRaises(ValueError): run(req,[4],global_bytes=g)
        for label in ('health IT continuity','defence logistics IT','finance reporting'):
            with self.subTest(synthetic_label=label):
                with self.assertRaises(ValueError): run(req,[3])
                self.assertEqual(run(req,[4]),run(req,[4]))
        self.assertEqual(run([],[],global_bytes=0)['requests'],[])
        self.assertEqual(run(req,(4,),global_bytes=None)['memory_accounting']['workspace_headroom_bytes'],0)

    def test_actual_integer_fields_and_overflow(self):
        req=[Request(0,1,1)]
        args=dict(parameters=5,bytes_per_parameter=2,kv_bytes_per_token=2,request_reservations_bytes=[4])
        for field in ('parameters','bytes_per_parameter','kv_bytes_per_token'):
            for value in (True,1.0,MAX_EXACT_BYTES+1,10**1000):
                altered=dict(args,**{field:value})
                with self.subTest(field=field,value=value),self.assertRaises(ValueError): simulate(req,hw(),**altered)
        with self.assertRaises(ValueError): simulate(req,hw(216.0),**args)
        with self.assertRaises(ValueError): simulate(req,hw(MAX_EXACT_BYTES),**dict(args,parameters=MAX_EXACT_BYTES))
        with self.assertRaises(ValueError): run(req*2,[MAX_EXACT_BYTES]*2,hbm=MAX_EXACT_BYTES,global_bytes=0)
        with self.assertRaises(ValueError): run([Request(0,MAX_EXACT_BYTES,1)],[MAX_EXACT_BYTES],hbm=MAX_EXACT_BYTES,global_bytes=0)
        # Legacy float default parameters must not be silently rounded in explicit mode.
        with self.assertRaises(ValueError): simulate(req,hw(80000000000),request_reservations_bytes=[1000000])

    def test_caps_before_loop_and_bounded_generator_consumption(self):
        consumed=[]
        def endless():
            while True:
                consumed.append(1)
                yield Request(0,1,1)
        with self.assertRaises(ValueError): run(endless(),[4]*128)
        self.assertEqual(len(consumed),129)
        with self.assertRaises(ValueError): run([Request(0,1,100001)],[200004])
        with self.assertRaises(ValueError): run([Request(0,1,1)],[4],max_batch=129)
        # Exactly the work cap remains valid when memory rejects it before service.
        out=run([Request(0,1,100000)],[200002],hbm=60,max_batch=128)
        self.assertTrue(out['requests'][0]['rejected'])
        out=run([Request(0,1,1)]*128,[4]*128,hbm=60)
        self.assertEqual(len(out['requests']),128)

    def test_nonfinite_service_arithmetic_refused(self):
        args=dict(parameters=5,bytes_per_parameter=2,kv_bytes_per_token=2,request_reservations_bytes=[4])
        for hardware in (hw(compute=5e-324),hw(bandwidth=5e-324),hw(efficiency=5e-324)):
            with self.subTest(hardware=hardware),self.assertRaises(ValueError):
                simulate([Request(0,1,1)],hardware,**args)


if __name__ == '__main__':
    unittest.main()
