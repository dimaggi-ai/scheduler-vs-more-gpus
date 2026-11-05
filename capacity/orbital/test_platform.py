import copy
import json
import subprocess
import sys
import unittest
from .contracts import digest
from .platform import compare_mission,plan_mission,verify_mission,evaluate_policies
from .platform.fixtures import demo,suite
from .platform.tools import dispatch

class PlatformTests(unittest.TestCase):
    def test_agent_journey_deterministic_no_execution(self):
        m=demo();before=copy.deepcopy(m)
        request=dict(schema='capacity-orbital/mission-tool-v1',id='agent-1',tool='compare',arguments=dict(mission=m))
        a=dispatch(request);b=dispatch(request)
        self.assertEqual(a,b);self.assertEqual(m,before);self.assertFalse(a['execution_performed']);self.assertFalse(a['promoted'])
        self.assertEqual(a['status'],'evaluated')
        for r in a['result']['comparisons']:self.assertTrue(r['admissible']);self.assertTrue(verify_mission(m,r)['valid'])

    def test_refusal_and_corrected_recovery(self):
        for kind in ('battery','network-loss','late','held'):
            with self.subTest(kind=kind):
                results=compare_mission(demo(kind))['comparisons']
                self.assertTrue(all(not r['admissible'] for r in results))
        self.assertTrue(all(r['admissible'] for r in compare_mission(demo('corrected'))['comparisons']))

    def test_authority_never_becomes_execution(self):
        for mode in ('held','refused','expired'):
            m=demo()
            if mode=='expired':m['authority']['expires_s']=1
            else:m['authority']['disposition']=mode
            for r in compare_mission(m)['comparisons']:
                self.assertFalse(r['admissible']);self.assertFalse(r['execution_performed']);self.assertTrue(any(f['code'].startswith('DYNAMICS_AUTHORITY') for f in r['failures']))

    def test_final_completion_not_arrival(self):
        m=demo();m['jobs']=m['jobs'][:1];m['jobs'][0]['deadline_s']=20
        r=plan_mission(m,'ground');self.assertEqual(r['network']['jobs'][0]['arrival_s'],16)
        self.assertEqual(r['jobs'][0]['completion_s'],26);self.assertFalse(r['admissible']);self.assertIn('DEADLINE',[f['code'] for f in r['failures']])

    def test_compute_network_precedence_and_energy(self):
        m=demo()
        for route in ('ground','onboard','hybrid'):
            r=plan_mission(m,route);events=r['proposal']['events']
            for node in m['compute']:
                lane=sorted([e for e in events if e['kind']=='compute' and e['node']==node],key=lambda e:e['start_s'])
                for a,b in zip(lane,lane[1:]):self.assertLessEqual(a['end_s'],b['start_s'])
            for j in r['network']['jobs']:
                origin=next((e for e in events if e['id']==f"compute:{j['id']}:origin"),None)
                ground=next((e for e in events if e['id']==f"compute:{j['id']}:ground"),None)
                if origin:self.assertGreaterEqual(j['hops'][0]['start_s'],origin['end_s'])
                if ground:self.assertGreaterEqual(ground['start_s'],j['arrival_s'])
            self.assertAlmostEqual(r['energy']['proposed_event_kwh'],r['energy']['evaluated_prefix_load_kwh'])

    def test_processing_buffer_and_memory_refusal(self):
        m=demo();m['network']['nodes']['A']['buffer_gb']=.5
        self.assertFalse(plan_mission(m,'onboard')['admissible']) # result fits, raw does not
        m=demo();m['compute']['G']['memory_gb']=.5
        self.assertFalse(plan_mission(m,'ground')['admissible'])

    def test_corrupt_relationship_rehashed_still_refuses(self):
        m=demo();r=plan_mission(m,'ground')
        r['jobs'][0]['completion_s']=0
        r['receipt_id']=digest({k:v for k,v in r.items() if k!='receipt_id'})
        v=verify_mission(m,r);self.assertFalse(v['valid']);self.assertIn('FINAL_COMPLETION',v['errors'])
        r=plan_mission(m,'ground');r['cost']['partial_operating_usd']=0
        r['receipt_id']=digest({k:v for k,v in r.items() if k!='receipt_id'})
        self.assertIn('COST_RELATIONSHIP',verify_mission(m,r)['errors'])
        r=plan_mission(m,'ground');node=next(iter(r['dynamics']['nodes']));r['dynamics']['nodes'][node]['intervals'][0]['energy']['load_kwh']=100
        r['receipt_id']=digest({k:v for k,v in r.items() if k!='receipt_id'})
        self.assertFalse(verify_mission(m,r)['valid'])

    def test_fixed_baseline_heldout_and_no_leakage(self):
        s=suite();original=copy.deepcopy(s);r=evaluate_policies(s,'ground',['onboard','hybrid'])
        self.assertEqual(s,original);self.assertEqual(r['recommendation'],'onboard');self.assertFalse(r['promoted'])
        s['heldout']=[copy.deepcopy(s['train'][0])];s['heldout'][0]['id']='renamed';s['heldout'][0]['diligence']['mission_id']='renamed'
        with self.assertRaises(ValueError):evaluate_policies(s,'ground',['onboard'])
        with self.assertRaises(ValueError):evaluate_policies(suite(),'ground',[{'route':'onboard','drop_jobs':True}])
        s=suite()
        for split in ('train','heldout'):
            for m in s[split]:
                for j in m['jobs']:j['onboard_quality']=.1
        self.assertIsNone(evaluate_policies(s,'ground',['onboard'])['recommendation'])

    def test_synthetic_feedback_success_worsening_and_wrong_binding(self):
        from .platform.fixtures import feedback_suite
        from .platform.feedback import assess_feedback
        s=feedback_suite();before=copy.deepcopy(s);r=assess_feedback(s)
        self.assertEqual(r,assess_feedback(s));self.assertEqual(s,before)
        self.assertEqual(r['recommendation'],'scale_110');self.assertFalse(r['promoted']);self.assertFalse(r['changes_prices'])
        log=r['prediction_outcome_log']['train'][0];self.assertEqual(log['proposal_receipt_id'],s['train'][0]['report']['receipt_id'])
        self.assertEqual(len(log['jobs']),len(s['train'][0]['mission']['jobs']))
        for row in log['jobs']:
            self.assertAlmostEqual(row['baseline_residual']['duration_s'],row['prediction']['duration_s']-row['replay']['duration_s'])
        self.assertIsNone(assess_feedback(feedback_suite(True))['recommendation'])
        s['train'][0]['records'][0]['source_sha256']='0'*64
        with self.assertRaises(ValueError):assess_feedback(s)
        s=feedback_suite();s['heldout'][0]['records'].pop()
        with self.assertRaises(ValueError):assess_feedback(s)
        s=feedback_suite();s['train'][0]['records'][0]['classification']='measured telemetry'
        with self.assertRaises(ValueError):assess_feedback(s)

    def test_job_reordering_cannot_create_heldout_evidence(self):
        a=demo();a['jobs'][0]['raw_gb']=1.25;b=copy.deepcopy(a)
        b['id']='renamed';b['diligence']['mission_id']=b['id'];b['jobs'].reverse();b['network']['contacts'].reverse()
        s=dict(schema='capacity-orbital/mission-suite-v1',train=[a],heldout=[b])
        with self.assertRaisesRegex(ValueError,'duplicate workload'):evaluate_policies(s,'ground',['onboard'])

    def test_training_candidate_cannot_sacrifice_baseline_success(self):
        a=demo();b=demo();b['id']='other';b['diligence']['mission_id']='other'
        for j in a['jobs']:j['onboard_quality']=.1
        for j in b['jobs']:j['ground_quality']=.1;j['raw_gb']=1.1
        held=suite()['heldout'][0]
        s=dict(schema='capacity-orbital/mission-suite-v1',train=[a,b],heldout=[held])
        r=evaluate_policies(s,'ground',['onboard'])
        self.assertIn('onboard',r['rejected_training_regressions']);self.assertEqual(r['selected_on_train'],'ground');self.assertIsNone(r['recommendation'])

    def test_diligence_explicit_horizon_and_unknown(self):
        m=demo();r=plan_mission(m,'onboard');d=r['diligence']
        self.assertEqual(d['mission_input_sha256'],digest(m));self.assertEqual(d['mission_horizon_s'],300)
        self.assertEqual(d['lifecycle_horizon_years'],2);self.assertFalse(d['mission_cost_combined_with_lifecycle'])
        self.assertTrue(all(x['result']['status']=='consistent' for x in d['contact_claims']))
        m['diligence']['lifecycle']=None;r=plan_mission(m,'onboard')
        self.assertIsNone(r['diligence']['lifecycle']);self.assertIsNone(r['cost']['lifecycle_total_usd'])
        m['diligence']['mission_id']='different'
        with self.assertRaises(ValueError):plan_mission(m,'onboard')

    def test_mismatched_bundles_and_cli(self):
        m=demo();m['dynamics']['horizon_s']=100
        with self.assertRaises(ValueError):compare_mission(m)
        m=demo();m['currency']='unknown'
        with self.assertRaises(ValueError):compare_mission(m)
        for kind,code in (('nominal',0),('battery',3),('corrected',0)):
            p=subprocess.run([sys.executable,'-m','capacity.orbital.platform','--demo',kind],capture_output=True,text=True)
            self.assertEqual(p.returncode,code,p.stderr);self.assertIn('comparisons',json.loads(p.stdout))

if __name__=='__main__':unittest.main()
