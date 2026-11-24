"""Bounded synthetic bridge journeys and independent integer/timing oracles."""
import copy
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

from capacity import kv_inference_bridge as bridge, kv_envelope

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    return json.loads((ROOT / 'examples/kv-inference-bridge.json').read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


class BridgeTests(unittest.TestCase):
    def test_a_exact_fit_and_public_api_calls(self):
        data = fixture()
        with patch.object(kv_envelope, 'evaluate', wraps=kv_envelope.evaluate) as envelope:
            result = bridge.evaluate(data)
        self.assertEqual(envelope.call_count, 2)  # Parent and one distinct context.
        self.assertEqual(result['status'], 'simulated')
        self.assertEqual([r['reservation_bytes'] for r in result['request_mapping']], [78,78])
        self.assertEqual(result['cohort_simultaneous_fit'], {'feasible':True,'required_kv_bytes':156,'kv_budget_bytes':156,'deficit_bytes':0})
        self.assertEqual(result['simulated_admission']['peak_reserved_bytes'],156)
        self.assertEqual(result['simulated_admission']['final_remaining_bytes'],156)
        for row in result['service_simulation']['requests']:
            self.assertAlmostEqual(row['ttft_s'], .394, delta=1e-12)
        self.assertEqual(data,fixture())

    def test_b_one_byte_short_queue_is_not_fit(self):
        data=fixture(); data['parent_envelope']['device']['usable_hbm_bytes']=215
        r=bridge.evaluate(data)
        self.assertFalse(r['cohort_simultaneous_fit']['feasible'])
        self.assertEqual(r['cohort_simultaneous_fit']['deficit_bytes'],1)
        self.assertEqual(r['individually_infeasible_ids'],[])
        self.assertEqual(r['simulated_admission']['completed_ids'],['request-0','request-1'])
        self.assertEqual(r['simulated_admission']['peak_reserved_bytes'],78)
        for row, expected in zip(r['service_simulation']['requests'],(.202,.404)):
            self.assertAlmostEqual(row['ttft_s'],expected,delta=1e-12)

    def test_c_heterogeneous_uniform_parent_and_actual_fit_remain_distinct(self):
        data=fixture(); data['parent_envelope']['device']['usable_hbm_bytes']=182
        data['requests'][0].update(input_tokens=15,max_resident_context_tokens=16)
        r=bridge.evaluate(data)
        self.assertEqual([x['reservation_bytes'] for x in r['request_mapping']],[44,78])
        self.assertFalse(r['parent_uniform_reference']['metrics']['feasible'])
        self.assertEqual(r['parent_uniform_reference']['metrics']['deficit_bytes'],34)
        self.assertTrue(r['cohort_simultaneous_fit']['feasible'])
        self.assertEqual(r['simulated_admission']['peak_reserved_bytes'],122)
        for row in r['service_simulation']['requests']:
            self.assertAlmostEqual(row['ttft_s'],.382,delta=1e-12)

    def test_d_sorting_identity_and_bound_recovery(self):
        data=fixture(); data['parent_envelope']['device']['usable_hbm_bytes']=182
        data['requests'][0].update(arrival_s=2,input_tokens=15,max_resident_context_tokens=16)
        r=bridge.evaluate(data)
        self.assertEqual([(m['original_index'],m['request_id'],m['reservation_bytes']) for m in r['request_mapping']],[(0,'request-0',44),(1,'request-1',78)])
        self.assertEqual([x['id'] for x in r['service_simulation']['requests']],[0,1])
        for row, expected in zip(r['service_simulation']['requests'],(.19,.202)):
            self.assertAlmostEqual(row['ttft_s'],expected,delta=1e-12)
        bad=copy.deepcopy(data);bad['requests'][1]['max_resident_context_tokens']=16
        with patch.object(bridge.inference,'simulate') as engine:
            self.assertEqual(bridge.evaluate(bad)['code'],'bound_too_small');engine.assert_not_called()
        self.assertEqual(bridge.evaluate(data),r)

    def test_e_fixed_deficit_and_zero_budget(self):
        data=fixture();data['parent_envelope']['device']['usable_hbm_bytes']=59
        with patch.object(bridge.inference,'simulate') as engine:
            r=bridge.evaluate(data);engine.assert_not_called()
        self.assertEqual(r['status'],'infeasible')
        self.assertEqual(r['fixed_memory_deficit_bytes'],1)
        self.assertEqual(r['parent_uniform_reference']['metrics']['deficit_bytes'],157)
        self.assertEqual(r['derived_envelopes'][0]['metrics']['deficit_bytes'],79)
        self.assertEqual(r['service_simulation']['status'],'not_run_fixed_memory_infeasible')
        data['parent_envelope']['device']['usable_hbm_bytes']=60
        r=bridge.evaluate(data)
        self.assertEqual(r['status'],'simulated')
        self.assertEqual(r['simulated_admission']['peak_reserved_bytes'],0)
        self.assertEqual(r['service_simulation']['makespan_s'],0)
        self.assertEqual(r['individually_infeasible_ids'],['request-0','request-1'])

    def test_missing_sorted_paths_and_syntactic_corruption_precedence(self):
        cases=[('model','model_revision'),('model','tokenizer_revision'),('service','compute_flops_s'),('service','source_indices')]
        for section,key in cases:
            data=fixture();data[section].pop(key)
            with self.subTest(key=key),patch.object(bridge.inference,'simulate') as engine:
                r=bridge.evaluate(data);self.assertEqual(r['status'],'insufficient_evidence');self.assertIn('$.'+section+'.'+key,r['missing_paths']);engine.assert_not_called()
        data=fixture();data['requests'][0].pop('cached_prefix_tokens');data['parent_envelope']['device'].pop('headroom_bytes')
        r=bridge.evaluate(data)
        self.assertEqual(r['missing_paths'],['$.parent_envelope.device.headroom_bytes','$.requests.0.cached_prefix_tokens'])
        self.assertEqual(r['parent_uniform_reference']['status'],'insufficient_evidence')
        data['service']['efficiency']=True
        self.assertEqual(bridge.evaluate(data)['status'],'refused')
        for section in ('model','service','requests','parent_envelope','schema'):
            data=fixture();data[section]=None
            self.assertEqual(bridge.evaluate(data)['status'],'insufficient_evidence')

    def test_merged_missing_paths_sorted_across_sections(self):
        data=fixture()
        del data['model']['tokenizer_revision']
        del data['service']['compute_flops_s']
        del data['parent_envelope']['device']['headroom_bytes']
        with patch.object(bridge.inference,'simulate') as engine:
            result=bridge.evaluate(data)
            engine.assert_not_called()
        self.assertEqual(result['status'],'insufficient_evidence')
        self.assertEqual(result['missing_paths'],[
            '$.model.tokenizer_revision',
            '$.parent_envelope.device.headroom_bytes',
            '$.service.compute_flops_s',
        ])

    def test_exact_individual_budget_is_admitted(self):
        data=fixture();data['requests']=data['requests'][:1]
        data['parent_envelope']['demand']['requested_concurrency']=1
        data['parent_envelope']['device']['usable_hbm_bytes']=138
        result=bridge.evaluate(data)
        self.assertEqual(result['cohort_simultaneous_fit']['kv_budget_bytes'],78)
        self.assertEqual(result['request_mapping'][0]['reservation_bytes'],78)
        self.assertEqual(result['individually_infeasible_ids'],[])
        self.assertEqual(result['simulated_admission']['completed_ids'],['request-0'])
        self.assertEqual(result['simulated_admission']['peak_reserved_bytes'],78)

    def test_f_malformed_unsupported_and_no_engine_call(self):
        changes=[('model','parameters',False),('model','parameters',5.0),('model','parameters',6),('model','model_revision','other'),
                 ('service','efficiency',2),('service','max_batch',129),('service','policy','other'),('service','source_indices',[1]),
                 ('service','source_indices',[0,0]),('service','compute_flops_s',0),('service','assumptions',[])]
        for section,key,value in changes:
            data=fixture();data[section][key]=value
            with self.subTest(key=key,value=value),patch.object(bridge.inference,'simulate') as engine:
                self.assertEqual(bridge.evaluate(data)['status'],'refused');engine.assert_not_called()
        for section,key,value in [('architecture','kind','unsupported'),('allocation','prefix_sharing','yes'),('device','resident_weights_bytes',0),('demand','requested_concurrency',3),('demand','max_resident_context_tokens',18)]:
            data=fixture();data['parent_envelope'][section][key]=value
            with self.subTest(key=key),patch.object(bridge.inference,'simulate') as engine:
                self.assertEqual(bridge.evaluate(data)['status'],'refused');engine.assert_not_called()
        for key,value in [('request_id','../private'),('arrival_s',-1),('input_tokens',True),('cached_prefix_tokens',17),('output_tokens',100001)]:
            data=fixture();data['requests'][0][key]=value
            self.assertEqual(bridge.evaluate(data)['status'],'refused')
        data=fixture();data['requests'][1]['request_id']='request-0'
        self.assertEqual(bridge.evaluate(data)['code'],'duplicate_request_id')
        data=fixture();data['parent_envelope']['sources'][0]['uri']='https://user:password@example.invalid/'
        self.assertEqual(bridge.evaluate(data)['code'],'invalid_uri')
        data=fixture();data['model']['unknown']=1
        self.assertEqual(bridge.evaluate(data)['code'],'unknown_field')
        data=fixture();data['service']['hardware_name']='bad\u200bname'
        self.assertEqual(bridge.evaluate(data)['code'],'invalid_text')
        self.assertEqual(bridge.evaluate(fixture())['status'],'simulated')

    def test_g_cached_prefix_capacity_invariance(self):
        data=fixture();plain=bridge.evaluate(data)
        for r in data['requests']:r['cached_prefix_tokens']=16
        cached=bridge.evaluate(data)
        for key in ('cohort_simultaneous_fit','simulated_admission','derived_envelopes'):
            self.assertEqual(cached[key],plain[key])
        for r in cached['service_simulation']['requests']:
            self.assertAlmostEqual(r['ttft_s'],.074,delta=1e-12)

    def test_h_unicode_digest_raw_whitespace_and_child_reconstruction(self):
        data=fixture();data['service']['hardware_name']='synthetic é device'
        raw=canonical(data);a=bridge.evaluate_bytes(raw);b=bridge.evaluate_bytes(b' \n'+raw+b'\n')
        self.assertNotEqual(a['raw_input_sha256'],b['raw_input_sha256'])
        self.assertEqual(a['canonical_input_sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(a['canonical_input_sha256'],b['canonical_input_sha256'])
        self.assertEqual(a['derived_envelopes'],b['derived_envelopes'])
        self.assertFalse(a['runtime_source_verified']);self.assertFalse(a['source_attribution']['runtime_source_verified'])
        self.assertEqual(canonical(a),canonical(bridge.evaluate_bytes(raw)))
        self.assertEqual(a['parent_uniform_reference']['input_sha256'],hashlib.sha256(canonical(data['parent_envelope'])).hexdigest())
        for child in a['derived_envelopes']:
            scenario=copy.deepcopy(data['parent_envelope']);scenario['demand']=child['demand_patch']
            self.assertEqual(child['child_canonical_sha256'],hashlib.sha256(canonical(scenario)).hexdigest())
        data['requests'].reverse();self.assertNotEqual(bridge.evaluate(data)['canonical_input_sha256'],a['canonical_input_sha256'])
        self.assertEqual(bridge.evaluate(data)['request_mapping'][0]['request_id'],'request-1')

    def test_i_fictional_domain_success_refusal_recovery(self):
        for label in ('Synthetic health-service IT continuity','Synthetic defence logistics IT','Synthetic finance reporting'):
            data=fixture();data['parent_envelope']['scenario_label']=label
            valid=bridge.evaluate(data);self.assertEqual(valid['status'],'simulated')
            data['requests'][0]['max_resident_context_tokens']=16
            self.assertEqual(bridge.evaluate(data)['status'],'refused')
            data['requests'][0]['max_resident_context_tokens']=17
            self.assertEqual(bridge.evaluate(data),valid)

    def test_bounded_json_and_object_limits(self):
        for raw in (b'{"schema":1,"schema":2}',b'{"x":NaN}',b'{"x":1e999}',b'\xff',b'{',b'['*9+b']'*9,b' '*262145):
            self.assertEqual(bridge.evaluate_bytes(raw)['status'],'refused')
        self.assertEqual(bridge.evaluate_bytes('not bytes')['code'],'expected_bytes')
        cyclic=[];cyclic.append(cyclic)
        self.assertEqual(bridge.evaluate(cyclic)['code'],'structure_limit')
        for obj in ([0]*8193, {'x':'a'*513}, {1:2}, {'x':2**53}, {'x':object()}):
            self.assertEqual(bridge.evaluate(obj)['status'],'refused')
        for count in (0,129):
            data=fixture();data['requests']=[copy.deepcopy(data['requests'][0]) for _ in range(count)]
            self.assertEqual(bridge.evaluate(data)['code'],'request_count')
        data=fixture();data['parent_envelope']['assumptions']=['x'*512]*32
        data['parent_envelope']['sources']=[dict(data['parent_envelope']['sources'][0],revision='é'*512,license='é'*512) for _ in range(16)]
        self.assertEqual(bridge.evaluate(data)['status'],'refused')  # Parent's own byte limit remains.
        with patch.object(bridge,'MAX_OUTPUT_BYTES',100):
            self.assertEqual(bridge.evaluate(fixture())['code'],'output_size_limit')

    def test_work_bounds_exact_limits_and_derived_overflow(self):
        data=fixture()
        data['requests']=[dict(data['requests'][0],request_id='r'+str(i)) for i in range(128)]
        data['parent_envelope']['demand']['requested_concurrency']=128
        data['service']['max_batch']=128
        r=bridge.evaluate(data)
        self.assertEqual(r['status'],'simulated')
        self.assertEqual(len(r['simulated_admission']['completed_ids']),128)
        data=fixture();data['requests']=data['requests'][:1]
        data['requests'][0].update(input_tokens=1,output_tokens=100000,max_resident_context_tokens=100001)
        data['parent_envelope']['demand'].update(max_resident_context_tokens=100001,requested_concurrency=1)
        data['parent_envelope']['device']['usable_hbm_bytes']=60
        self.assertEqual(bridge.evaluate(data)['status'],'simulated')
        data['requests'][0].update(output_tokens=100001,max_resident_context_tokens=100002)
        data['parent_envelope']['demand']['max_resident_context_tokens']=100002
        with patch.object(bridge.inference,'simulate') as engine:
            self.assertEqual(bridge.evaluate(data)['code'],'output_token_limit');engine.assert_not_called()
        data=fixture();data['model']['parameters']=bridge.MAX_INTEGER
        self.assertEqual(bridge.evaluate(data)['code'],'unsupported_weight_mapping')
        data=fixture();data['requests'][0].update(input_tokens=bridge.MAX_INTEGER,max_resident_context_tokens=bridge.MAX_INTEGER)
        self.assertEqual(bridge.evaluate(data)['code'],'derived_integer_limit')

    def test_refusal_identity_paths_and_signed_zero_declaration(self):
        data=fixture();expected=bridge.evaluate(data)
        with patch.object(bridge,'MAX_OUTPUT_BYTES',512):
            refused=bridge.evaluate(data)
        self.assertEqual(refused['code'],'output_size_limit')
        self.assertEqual(refused['schema'],expected['schema'])
        for key in ('raw_input_sha256','canonical_input_sha256'):
            self.assertEqual(refused[key],expected[key])
        self.assertNotIn('service_simulation',refused)
        malformed=dict(expected, unsupported=object())
        refused=bridge._bounded_result(malformed)
        self.assertEqual(refused['code'],'bridge_consistency_violation')
        self.assertEqual(refused['schema'],expected['schema'])
        self.assertEqual(refused['raw_input_sha256'],expected['raw_input_sha256'])
        data['service']['hardware_name']='x'*513
        self.assertEqual(bridge.evaluate(data)['path'],'$.service.hardware_name')
        data=fixture();data['requests'][1]['request_id']='bad\u200bid'
        self.assertEqual(bridge.evaluate(data)['path'],'$.requests.1.request_id')
        data=fixture();data['requests'][0]['arrival_s']=-0.0
        negative_zero=bridge.evaluate(data)
        self.assertNotEqual(negative_zero['canonical_input_sha256'],expected['canonical_input_sha256'])
        self.assertEqual(negative_zero['service_simulation'],expected['service_simulation'])
        self.assertEqual(str(negative_zero['request_mapping'][0]['request_declaration']['arrival_s']),'-0.0')

    def test_precision_large_offsets_and_supported_tiny_service(self):
        def single(arrival=0, rate=1000):
            data=fixture();data['requests']=data['requests'][:1]
            data['requests'][0]['arrival_s']=arrival
            data['parent_envelope']['demand']['requested_concurrency']=1
            data['service'].update(compute_flops_s=rate,memory_bandwidth_bytes_s=rate)
            return data
        for arrival in (1e17,1e300,sys.float_info.max):
            data=single(arrival);data['service']['ttft_slo_s']=.1
            result=bridge.evaluate(data)
            self.assertEqual(result['code'],'timing_precision_indeterminate')
            self.assertEqual(result['canonical_input_sha256'],hashlib.sha256(canonical(data)).hexdigest())
            self.assertNotIn('service_simulation',result)
        for arrival in (0,2**20,1e9):
            result=bridge.evaluate(single(arrival))
            self.assertEqual(result['status'],'simulated')
            self.assertGreater(result['timing_precision']['estimate_s'],0)
        result=bridge.evaluate(single(2**20))
        self.assertEqual(result['timing_precision']['estimate_s'],10*2**-32)
        for rate in (2**53-1,1e30):  # Supported integer and finite float declarations.
            data=single(0,rate);data['service']['ttft_slo_s']=1e-30
            result=bridge.evaluate(data)
            self.assertEqual(result['status'],'simulated')
            self.assertFalse(result['service_simulation']['requests'][0]['slo_met'])
            data['requests'][0]['arrival_s']=1000
            self.assertEqual(bridge.evaluate(data)['code'],'timing_precision_indeterminate')
        data=single(0,10**30)
        self.assertEqual(bridge.evaluate(data)['code'],'integer_limit')

    def test_precision_threshold_margin_single_token_itl_and_count(self):
        data=fixture();data['requests']=data['requests'][:1]
        data['parent_envelope']['demand']['requested_concurrency']=1
        ordinary=bridge.evaluate(data);ttft=ordinary['service_simulation']['requests'][0]['ttft_s']
        data['service']['ttft_slo_s']=ttft
        self.assertEqual(bridge.evaluate(data)['code'],'timing_precision_indeterminate')
        data['service']['ttft_slo_s']=ttft*(1+1e-9)
        self.assertEqual(bridge.evaluate(data)['status'],'simulated')
        data['service']['itl_slo_s']=1e-300  # Single-token ITL is an exact default zero.
        self.assertEqual(bridge.evaluate(data)['status'],'simulated')
        data['service'].update(ttft_slo_s=1,itl_slo_s=1)
        data['requests'][0].update(output_tokens=100,max_resident_context_tokens=116)
        data['parent_envelope']['demand']['max_resident_context_tokens']=116
        data['parent_envelope']['device']['usable_hbm_bytes']=2000
        baseline=bridge.evaluate(data)
        self.assertEqual(baseline['status'],'simulated')
        self.assertEqual(baseline['timing_precision']['event_addition_bound'],101)
        data['service']['ttft_slo_s']=baseline['service_simulation']['requests'][0]['ttft_s']+baseline['timing_precision']['estimate_s']/2
        self.assertEqual(bridge.evaluate(data)['code'],'timing_precision_indeterminate')
        data['service']['ttft_slo_s']=1
        data['service']['itl_slo_s']=baseline['service_simulation']['requests'][0]['max_itl_s']
        self.assertEqual(bridge.evaluate(data)['code'],'timing_precision_indeterminate')

    def test_precision_each_served_duration_not_only_makespan(self):
        data=fixture()
        data['requests'][0].update(input_tokens=100000000000,max_resident_context_tokens=100000000001)
        data['requests'][1]['arrival_s']=1e17
        data['parent_envelope']['demand']['max_resident_context_tokens']=100000000001
        data['parent_envelope']['device']['usable_hbm_bytes']=1000000000000
        data['service'].update(ttft_slo_s=1e20,itl_slo_s=1e20)
        real_engine=bridge.inference.simulate;captured={}
        def capture(*args,**kwargs):
            result=real_engine(*args,**kwargs);captured.update(result);return result
        with patch.object(bridge.inference,'simulate',side_effect=capture):
            self.assertEqual(bridge.evaluate(data)['code'],'timing_precision_indeterminate')
        self.assertEqual(captured['requests'][1]['ttft_s'],0)
        self.assertGreater(captured['requests'][0]['ttft_s'],1e9)
        self.assertGreater(captured['makespan_s'],1e16)
        # A long TTFT can likewise hide an unresolved multi-token ITL.
        data=fixture();data['requests'][0].update(output_tokens=2,max_resident_context_tokens=18)
        data['parent_envelope']['demand']['max_resident_context_tokens']=18
        def unresolved_itl(*args,**kwargs):
            result=real_engine(*args,**kwargs);result['requests'][0]['max_itl_s']=0;return result
        with patch.object(bridge.inference,'simulate',side_effect=unresolved_itl):
            self.assertEqual(bridge.evaluate(data)['code'],'timing_precision_indeterminate')

    def test_precision_no_service_and_ordinary_128_shifted_requests(self):
        data=fixture();data['parent_envelope']['device']['usable_hbm_bytes']=60
        for request in data['requests']:request['arrival_s']=sys.float_info.max
        result=bridge.evaluate(data)
        self.assertEqual(result['status'],'simulated')
        self.assertEqual(result['timing_precision']['status'],'not_evaluated')
        self.assertEqual(result['timing_precision']['reason'],'no_served_requests')
        data=fixture();data['requests']=[dict(data['requests'][0],request_id='r'+str(i),arrival_s=1e9) for i in range(128)]
        data['parent_envelope']['demand']['requested_concurrency']=128
        data['service'].update(ttft_slo_s=1000,itl_slo_s=1)
        result=bridge.evaluate(data)
        self.assertEqual(result['status'],'simulated')
        self.assertEqual(len(result['simulated_admission']['completed_ids']),128)
        self.assertEqual(result['timing_precision']['event_addition_bound'],256)

    def test_engine_timing_fields_are_validated_before_precision(self):
        real_engine=bridge.inference.simulate
        missing=object()
        invalid_values=(missing,None,'not a time',True,float('nan'),float('inf'),-1,10**1000)
        for field in ('makespan_s','ttft_s','max_itl_s'):
            for value in invalid_values:
                with self.subTest(field=field,value_type=type(value).__name__):
                    def malformed(*args,**kwargs):
                        result=real_engine(*args,**kwargs)
                        target=result if field=='makespan_s' else result['requests'][0]
                        if value is missing:target.pop(field)
                        else:target[field]=value
                        return result
                    with patch.object(bridge.inference,'simulate',side_effect=malformed):
                        for evaluate in (lambda:bridge.evaluate(fixture()),lambda:bridge.evaluate_bytes(canonical(fixture()))):
                            result=evaluate()
                            self.assertEqual(result['status'],'refused')
                            self.assertEqual(result['code'],'bridge_consistency_violation')
                            self.assertEqual(result['path'],'$.service_simulation')
                            self.assertIn('raw_input_sha256',result)
                            self.assertNotIn('service_simulation',result)
                            self.assertNotIn('timing_precision',result)
        def no_makespan(*args,**kwargs):
            result=real_engine(*args,**kwargs);result.pop('makespan_s');return result
        output=io.StringIO()
        with patch.object(bridge.inference,'simulate',side_effect=no_makespan),patch('sys.stdout',output):
            self.assertEqual(bridge.main([str(ROOT/'examples/kv-inference-bridge.json')]),2)
        self.assertEqual(json.loads(output.getvalue())['code'],'bridge_consistency_violation')
        with patch.object(bridge.inference,'simulate',side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):bridge.evaluate(fixture())

    def test_clock_scale_includes_service_span_rational_tie(self):
        data=fixture()
        data['requests']=[dict(data['requests'][0],request_id='r'+str(i),input_tokens=1,output_tokens=1,max_resident_context_tokens=2) for i in range(128)]
        data['parent_envelope']['demand'].update(requested_concurrency=128,max_resident_context_tokens=2)
        # Two requests per batch: prefill 20/1000 s plus decode max(20,14)/1000 s.
        # Rows 48 and 49 finish in batch 25, at exactly the declared one-second SLO.
        batch_time=Fraction(20,1000)+max(Fraction(20,1000),Fraction(14,1000))
        exact_ttft=25*batch_time
        self.assertEqual(exact_ttft,Fraction(1))
        real_engine=bridge.inference.simulate;captured={}
        def capture(*args,**kwargs):
            result=real_engine(*args,**kwargs);captured.update(result);return result
        with patch.object(bridge.inference,'simulate',side_effect=capture):
            result=bridge.evaluate(data)
        for index in (48,49):
            self.assertGreater(captured['requests'][index]['ttft_s'],float(exact_ttft))
            self.assertFalse(captured['requests'][index]['slo_met'])
        self.assertEqual(result['code'],'timing_precision_indeterminate')

    def test_resolution_multiplier_refuses_small_nonzero_duration(self):
        data=fixture()
        data['service'].update(compute_flops_s=2**53-1,memory_bandwidth_bytes_s=2**53-1)
        for request in data['requests']:request['arrival_s']=1
        real_engine=bridge.inference.simulate;captured={}
        def capture(*args,**kwargs):
            result=real_engine(*args,**kwargs);captured.update(result);return result
        with patch.object(bridge.inference,'simulate',side_effect=capture):
            result=bridge.evaluate(data)
        self.assertGreater(captured['requests'][0]['ttft_s'],0)
        self.assertEqual(result['code'],'timing_precision_indeterminate')

    def test_phase_specific_dependency_exceptions_and_control_flow(self):
        real_envelope=kv_envelope.evaluate
        exceptions=(ValueError,RecursionError,OverflowError,TypeError,KeyError,
                    ZeroDivisionError,AttributeError,IndexError,RuntimeError)
        for phase in ('parent','child','engine'):
            def inject(error):
                if phase=='engine':
                    return patch.object(bridge.inference,'simulate',side_effect=error)
                def envelope(data):
                    if phase=='parent' or data['demand']['requested_concurrency']==1:
                        raise error
                    return real_envelope(data)
                return patch.object(kv_envelope,'evaluate',side_effect=envelope)
            for exception in exceptions:
                with self.subTest(phase=phase,exception=exception.__name__),inject(exception('private exception detail')):
                    result=bridge.evaluate(fixture())
                    self.assertEqual(result['code'],'engine_contract_violation' if phase=='engine' else 'bridge_consistency_violation')
                    self.assertEqual(result['path'],{'parent':'$.parent_envelope','child':'$.derived_envelopes','engine':'$.service_simulation'}[phase])
                    self.assertEqual(result['schema'],bridge.RESULT_SCHEMA)
                    self.assertIn('canonical_input_sha256',result)
                    self.assertNotIn('service_simulation',result)
                    self.assertNotIn('private exception detail',str(result))
            for exception in (MemoryError,KeyboardInterrupt,SystemExit):
                with self.subTest(phase=phase,exception=exception.__name__),inject(exception()):
                    with self.assertRaises(exception):bridge.evaluate(fixture())
            with inject(bridge.Refusal('specific_refusal','$.specific')):
                result=bridge.evaluate(fixture())
                self.assertEqual((result['code'],result['path']),('specific_refusal','$.specific'))
        with patch.object(bridge,'_timing_precision',side_effect=bridge.Refusal('timing_precision_indeterminate','$.service_simulation')):
            self.assertEqual(bridge.evaluate(fixture())['code'],'timing_precision_indeterminate')
        for error in (TypeError(),ValueError(),KeyError(),OverflowError(),RecursionError()):
            with patch.object(bridge,'_timing_precision',side_effect=error):
                self.assertEqual(bridge.evaluate(fixture())['code'],'bridge_consistency_violation')
        for exception in (MemoryError,KeyboardInterrupt,SystemExit):
            with patch.object(bridge,'_timing_precision',side_effect=exception()):
                with self.assertRaises(exception):bridge.evaluate(fixture())
        for raw,code in ((b'{','invalid_json'),(b'\xff','invalid_json'),
                         (b'{"x":"\\ud800"}','invalid_text'),
                         (b'{"x":1,"x":2}','duplicate_key'),
                         (b'['*9+b']'*9,'depth_limit'),(b'{"x":NaN}','nonfinite_number')):
            self.assertEqual(bridge.evaluate_bytes(raw)['code'],code)

    def test_phase_specific_cli_refusal_and_recovery(self):
        for phase in ('parent','child','engine'):
            output=io.StringIO();stderr=io.StringIO();real=kv_envelope.evaluate
            def envelope(data):
                if phase=='parent' or data['demand']['requested_concurrency']==1:raise KeyError('private')
                return real(data)
            target=patch.object(bridge.inference,'simulate',side_effect=KeyError('private')) if phase=='engine' else patch.object(kv_envelope,'evaluate',side_effect=envelope)
            with target,patch('sys.stdout',output),patch('sys.stderr',stderr):
                self.assertEqual(bridge.main([str(ROOT/'examples/kv-inference-bridge.json')]),2)
            self.assertEqual(json.loads(output.getvalue())['code'],'engine_contract_violation' if phase=='engine' else 'bridge_consistency_violation')
            self.assertEqual(stderr.getvalue(),'')
        self.assertEqual(bridge.evaluate(fixture())['status'],'simulated')

    def test_timing_slo_invariants_precede_precision(self):
        real=bridge.inference.simulate
        cases=[('output_tokens',True),('output_tokens',2),('slo_met',1),('slo_met',0),('slo_met',False),('ttft_s',1e300)]
        for key,value in cases:
            def liar(*args,**kwargs):
                result=real(*args,**kwargs);result['requests'][0][key]=value
                if key=='ttft_s':result['requests'][0]['slo_met']=False
                return result
            with self.subTest(key=key,value=value),patch.object(bridge.inference,'simulate',side_effect=liar):
                result=bridge.evaluate(fixture())
                self.assertEqual(result['status'],'refused')
                self.assertIn('code',result)
                self.assertEqual(result['code'],'bridge_consistency_violation')
        def short_span(*args,**kwargs):
            result=real(*args,**kwargs);result['makespan_s']=1e-9;result['requests'][0]['ttft_s']=.5;return result
        with patch.object(bridge.inference,'simulate',side_effect=short_span):
            self.assertEqual(bridge.evaluate(fixture())['code'],'bridge_consistency_violation')
        data=fixture();data['requests'][0].update(output_tokens=2,max_resident_context_tokens=18)
        data['parent_envelope']['demand']['max_resident_context_tokens']=18
        def impossible_gap(*args,**kwargs):
            result=real(*args,**kwargs);result['makespan_s']=1
            result['requests'][0].update(ttft_s=.4,max_itl_s=.7,slo_met=True)
            return result
        with patch.object(bridge.inference,'simulate',side_effect=impossible_gap):
            result=bridge.evaluate(data)
            self.assertEqual(result['status'],'refused')
            self.assertIn('code',result)
            self.assertEqual(result['code'],'bridge_consistency_violation')
        # I2 contradicts the returned floats at an exact SLO tie; consistency wins.
        def wrong_tie(*args,**kwargs):
            result=real(*args,**kwargs);result['makespan_s']=1
            result['requests'][0].update(ttft_s=1,slo_met=False);return result
        with patch.object(bridge.inference,'simulate',side_effect=wrong_tie):
            self.assertEqual(bridge.evaluate(fixture())['code'],'bridge_consistency_violation')

    def test_clock_invariant_tolerance_boundary(self):
        real=bridge.inference.simulate;data=fixture();data['service']['ttft_slo_s']=2
        # N=2, O=2, S just above 1: tau = (2+2+8)*2^-52 exactly.
        tolerance=12*2**-52
        for multiplier,expected in ((1,'simulated'),(2,'refused')):
            def liar(*args,**kwargs):
                result=real(*args,**kwargs);result['makespan_s']=1
                result['requests'][0]['ttft_s']=1+multiplier*tolerance
                return result
            with self.subTest(multiplier=multiplier),patch.object(bridge.inference,'simulate',side_effect=liar):
                result=bridge.evaluate(data);self.assertEqual(result['status'],expected)
                if expected=='refused':self.assertEqual(result['code'],'bridge_consistency_violation')

    def test_timing_subclasses_and_minimal_refusal_fallback(self):
        class IntSubclass(int):pass
        class FloatSubclass(float):pass
        real=bridge.inference.simulate
        for field in ('makespan_s','ttft_s','max_itl_s'):
            for value in (IntSubclass(1),FloatSubclass(.5)):
                def liar(*args,**kwargs):
                    result=real(*args,**kwargs)
                    target=result if field=='makespan_s' else result['requests'][0]
                    target[field]=value;return result
                with self.subTest(field=field,value_type=type(value).__name__),patch.object(bridge.inference,'simulate',side_effect=liar):
                    self.assertEqual(bridge.evaluate(fixture())['code'],'bridge_consistency_violation')
        for cap in (200,1):
            with self.subTest(cap=cap),patch.object(bridge,'MAX_OUTPUT_BYTES',cap):
                result=bridge.evaluate(fixture())
            self.assertEqual(result['code'],'output_size_limit')
            self.assertIn('schema',result)
            self.assertEqual(result['schema'],bridge.RESULT_SCHEMA)
            self.assertNotIn('raw_input_sha256',result)
            self.assertNotIn('canonical_input_sha256',result)
            if cap==1:self.assertGreater(len(canonical(result))+1,cap)

    def test_child_engine_consistency_and_engine_errors(self):
        real=kv_envelope.evaluate
        for key,value in [('kv_budget_bytes',155),('feasible',False),('kv_bytes_per_token',4)]:
            def corrupt(data):
                r=real(data)
                if data['demand']['requested_concurrency']==1:r['metrics'][key]=value
                return r
            with self.subTest(key=key),patch.object(kv_envelope,'evaluate',side_effect=corrupt),patch.object(bridge.inference,'simulate') as engine:
                self.assertEqual(bridge.evaluate(fixture())['code'],'bridge_consistency_violation');engine.assert_not_called()
        for error in (ValueError('private detail'), OverflowError('private detail'), ZeroDivisionError('private detail')):
            with patch.object(bridge.inference,'simulate',side_effect=error):
                r=bridge.evaluate(fixture());self.assertEqual(r['code'],'engine_contract_violation');self.assertNotIn('private detail',str(r));self.assertNotIn('service_simulation',r)
        for invalid in (None, {}, {'memory_accounting':{},'requests':[None]}):
            with patch.object(bridge.inference,'simulate',return_value=invalid):
                self.assertEqual(bridge.evaluate(fixture())['code'],'bridge_consistency_violation')
        real_engine=bridge.inference.simulate
        def wrong_budget(*args,**kwargs):
            r=real_engine(*args,**kwargs);r['memory_accounting']['kv_budget_bytes']-=1;return r
        with patch.object(bridge.inference,'simulate',side_effect=wrong_budget):
            self.assertEqual(bridge.evaluate(fixture())['code'],'bridge_consistency_violation')
        def lying_engine(*args,**kwargs):
            r=real_engine(*args,**kwargs);r['requests'][0]['rejected']=True;return r
        with patch.object(bridge.inference,'simulate',side_effect=lying_engine):
            self.assertEqual(bridge.evaluate(fixture())['code'],'bridge_consistency_violation')
        data=fixture();data['service']['compute_flops_s']=5e-324
        self.assertEqual(bridge.evaluate(data)['code'],'engine_contract_violation')


class ReaderTests(unittest.TestCase):
    def test_actual_cli_success_refusal_recovery_and_file_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'input.json';path.write_bytes(canonical(fixture()))
            def cli(p):
                r=subprocess.run([sys.executable,'-m','capacity.kv_inference_bridge',str(p)],cwd=ROOT,capture_output=True,timeout=10)
                return r,json.loads(r.stdout)
            r,valid=cli(path);self.assertEqual(r.returncode,0);self.assertEqual(valid['status'],'simulated');self.assertEqual(r.stderr,b'')
            path.write_bytes(b'{');r,result=cli(path);self.assertEqual(r.returncode,2);self.assertEqual(result['status'],'refused')
            path.write_bytes(canonical(fixture()));self.assertEqual(cli(path)[1],valid)
            link=Path(tmp)/'link';link.symlink_to(path)
            fifo=Path(tmp)/'fifo';os.mkfifo(fifo)
            for bad in (link,fifo,Path(tmp),Path(tmp)/'missing'):
                r,result=cli(bad);self.assertEqual(r.returncode,2);self.assertEqual(result['status'],'refused')
            path.write_bytes(b' '*262145);self.assertEqual(cli(path)[1]['code'],'input_size_limit')
            self.assertEqual(bridge.read_scenario('bad\0path')['code'],'input_unreadable')

    def test_reader_descriptor_ownership_and_failure_precedence(self):
        for stage in ('success','fdopen','read','stream_close','interrupt'):
            for raw_close_fails in (False,True):
                with self.subTest(stage=stage,raw_close_fails=raw_close_fails):
                    stream=Mock();stream.__enter__=Mock(return_value=stream);stream.__exit__=Mock(return_value=False)
                    stream.read.return_value=canonical(fixture())
                    if stage=='read':stream.read.side_effect=OSError('read')
                    if stage=='interrupt':stream.read.side_effect=KeyboardInterrupt()
                    if stage=='stream_close':stream.__exit__.side_effect=OSError('close stream')
                    with patch.object(bridge.os,'open',return_value=77),patch.object(bridge.os,'fstat',return_value=Mock(st_mode=stat.S_IFREG)),patch.object(bridge.os,'fdopen',side_effect=OSError('partial') if stage=='fdopen' else None,return_value=stream) as fdopen,patch.object(bridge.os,'close',side_effect=OSError('raw') if raw_close_fails else None) as close:
                        if stage=='interrupt' and not raw_close_fails:
                            with self.assertRaises(KeyboardInterrupt):bridge.read_scenario('synthetic')
                        else:
                            try:r=bridge.read_scenario('synthetic')
                            except KeyboardInterrupt:self.fail('raw close failure must replace pending interrupt')
                            self.assertEqual(r['status'],'simulated' if stage=='success' and not raw_close_fails else 'refused')
                        close.assert_called_once_with(77);fdopen.assert_called_once_with(77,'rb',closefd=False)
                        if stage!='fdopen':stream.__exit__.assert_called_once();stream.read.assert_called_once_with(bridge.MAX_BYTES+1)

    def test_preopen_stat_failure_and_unsupported_platform(self):
        with patch.object(bridge.os,'open',side_effect=OSError()),patch.object(bridge.os,'close') as close:
            self.assertEqual(bridge.read_scenario('x')['status'],'refused');close.assert_not_called()
        with patch.object(bridge.os,'open',return_value=77),patch.object(bridge.os,'fstat',side_effect=OSError()),patch.object(bridge.os,'close') as close,patch.object(bridge.os,'fdopen') as stream:
            self.assertEqual(bridge.read_scenario('x')['status'],'refused');close.assert_called_once_with(77);stream.assert_not_called()
        with patch.object(bridge,'os',spec=['open']):
            self.assertEqual(bridge.read_scenario('x')['code'],'unsupported_platform')
        output=io.StringIO()
        with patch('sys.stdout',output):self.assertEqual(bridge.main([]),2)
        self.assertEqual(json.loads(output.getvalue())['code'],'expected_one_input_path')


if __name__=='__main__':
    unittest.main()
