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

    @staticmethod
    def relabel(m):
        """Rename every graph/job identifier and reverse unordered collections."""
        out=copy.deepcopy(m);names={name:'renamed-'+str(i) for i,name in enumerate(reversed(list(m['network']['nodes'])))}
        terminals={(n,t):'terminal-'+str(i) for i,(n,t) in enumerate((n,t) for n,node in m['network']['nodes'].items() for t in node['terminals'])}
        links={c['link_id']:'link-'+str(i) for i,c in enumerate(m['network']['contacts'])}
        out['id']='relabeled';out['diligence']['mission_id']='relabeled'
        for role in ('origin','destination'):out[role]=names[m[role]]
        out['compute']={names[k]:v for k,v in reversed(list(out['compute'].items()))}
        out['dynamics']['nodes']={names[k]:v for k,v in reversed(list(out['dynamics']['nodes'].items()))}
        out['network']['nodes']={names[k]:dict(v,terminals=[terminals[(k,t)] for t in reversed(v['terminals'])]) for k,v in reversed(list(out['network']['nodes'].items()))}
        for i,c in enumerate(out['network']['contacts']):
            source,destination=c['source'],c['destination']
            c['source_terminal']=terminals[(source,c['source_terminal'])];c['destination_terminal']=terminals[(destination,c['destination_terminal'])]
            c['source']=names[source];c['destination']=names[destination];c['link_id']=links[c['link_id']];c['id']='contact-'+str(i)
        out['network']['contacts'].reverse();out['jobs'].reverse()
        for i,j in enumerate(out['jobs']):j['id']='payload-'+str(i);j['allowed_jurisdictions'].reverse()
        return out

    def test_relabelled_graph_and_jobs_cannot_be_heldout(self):
        from .platform.evaluation import semantic
        a=demo();a['jobs'][0]['raw_gb']=1.25;b=self.relabel(a)
        self.assertEqual(digest(semantic(a)),digest(semantic(b)))
        s=dict(schema='capacity-orbital/mission-suite-v1',train=[a],heldout=[b])
        with self.assertRaisesRegex(ValueError,'duplicate workload'):evaluate_policies(s,'ground',['onboard'])
        # Physical/jurisdiction/price changes are not erased as label changes.
        for edit in ('price','jurisdiction','power','quality'):
            changed=copy.deepcopy(b)
            if edit=='price':changed['network']['contacts'][0]['cost_per_gb']+=.01
            elif edit=='jurisdiction':changed['network']['nodes'][changed['origin']]['jurisdiction']='other-zone'
            elif edit=='power':changed['compute'][changed['origin']]['power_kw']+=.1
            else:changed['jobs'][0]['required_quality']=.89
            self.assertNotEqual(digest(semantic(a)),digest(semantic(changed)))

    def test_feedback_relabelled_graph_cannot_be_heldout(self):
        from .platform.fixtures import feedback_suite
        from .platform.feedback import assess_feedback,predictions
        from .platform.mission import source_digest
        s=feedback_suite();m=self.relabel(s['train'][0]['mission']);r=plan_mission(m,'onboard');records=[]
        for j in m['jobs']:
            pred=predictions(m,r,j['id'])
            records.append(dict(schema='capacity-orbital/synthetic-replay-v1',id=j['id'],classification='supplied synthetic replay',mission_input_sha256=digest(m),source_sha256=source_digest(),proposal_receipt_id=r['receipt_id'],job_id=j['id'],completion_s=j['release_s']+pred['duration_s'],energy_kwh=pred['energy_kwh'],link_gb=pred['link_gb'],cost_usd=pred['cost_usd']))
        s['heldout']=[dict(mission=m,report=r,records=records)]
        with self.assertRaisesRegex(ValueError,'workload leakage'):assess_feedback(s)

    def test_topology_aliasing_is_preserved_and_symmetry_refuses(self):
        from .platform.evaluation import semantic
        from .platform.semantic import SemanticRefusal
        from unittest.mock import patch
        a=demo();a['network']['contacts'].append(dict(a['network']['contacts'][0],id='later',start_s=205,end_s=220))
        b=copy.deepcopy(a);b['network']['contacts'][-1]['link_id']='separate-link'
        self.assertNotEqual(digest(semantic(a)),digest(semantic(b)))
        a=demo();a['network']['nodes']['A']['terminals'].append('unused')
        b=copy.deepcopy(a);b['network']['contacts'].append(dict(b['network']['contacts'][0],id='later',start_s=205,end_s=220))
        a=copy.deepcopy(b);b['network']['contacts'][-1]['source_terminal']='unused'
        self.assertNotEqual(digest(semantic(a)),digest(semantic(b)))
        symmetric=demo()
        for i in range(29):
            name='symmetric-'+str(i);symmetric['network']['nodes'][name]=copy.deepcopy(symmetric['network']['nodes']['B']);symmetric['dynamics']['nodes'][name]=copy.deepcopy(symmetric['dynamics']['nodes']['B'])
        with self.assertRaises(SemanticRefusal) as caught:semantic(symmetric)
        self.assertEqual(caught.exception.code,'SEMANTIC_TOPOLOGY_AMBIGUOUS')
        request=dict(schema='capacity-orbital/mission-tool-v1',id='symmetric',tool='evaluate',arguments=dict(suite=dict(schema='capacity-orbital/mission-suite-v1',train=[symmetric],heldout=[demo()]),baseline='ground',candidates=['onboard']))
        self.assertEqual(dispatch(request)['code'],'SEMANTIC_TOPOLOGY_AMBIGUOUS')
        with patch('capacity.orbital.platform.semantic.MAX_WORK',1):
            with self.assertRaises(SemanticRefusal) as caught:semantic(demo())
            self.assertEqual(caught.exception.code,'BUDGET_EXCEEDED')

    def test_tool_refusal_codes_and_source_failure(self):
        from unittest.mock import patch
        request=dict(schema='capacity-orbital/mission-tool-v1',id='recoverable',tool='unknown',arguments={})
        r=dispatch(request);self.assertEqual(r['code'],'UNKNOWN_TOOL');self.assertEqual(r['request_id'],'recoverable')
        request['schema']='bad';self.assertEqual(dispatch(request)['code'],'UNSUPPORTED_SCHEMA')
        request['schema']='capacity-orbital/mission-tool-v1';request['tool']='compare';request['arguments']={'mission':demo()}
        with patch('capacity.orbital.platform.tools.source_digest',side_effect=OSError('unavailable')):
            self.assertEqual(dispatch(request)['code'],'SOURCE_UNAVAILABLE')
        with patch('capacity.orbital.platform.tools.compare_mission',return_value={'oversized':'x'*8000001}):
            result=dispatch(request);self.assertEqual(result['code'],'BUDGET_EXCEEDED');self.assertLess(len(json.dumps(result)),3000)
        self.assertEqual(dispatch(request)['status'],'evaluated')

    def test_mismatched_bundles_and_cli(self):
        m=demo();m['dynamics']['horizon_s']=100
        with self.assertRaises(ValueError):compare_mission(m)
        m=demo();m['currency']='unknown'
        with self.assertRaises(ValueError):compare_mission(m)
        for kind,code in (('nominal',0),('battery',3),('corrected',0)):
            p=subprocess.run([sys.executable,'-m','capacity.orbital.platform','--demo',kind],capture_output=True,text=True)
            self.assertEqual(p.returncode,code,p.stderr);self.assertIn('comparisons',json.loads(p.stdout))

    def test_queued_zero_ground_and_hybrid_verify_lane(self):
        for route,field in (('ground','ground_s'),('hybrid','hybrid_ground_s')):
            for outage in (False,True):
                m=demo();m['jobs'][0][field]=20;m['jobs'][1][field]=0
                if outage:m['network']['nodes'][m['destination']]['unavailable']=[dict(start_s=20,end_s=30)]
                r=plan_mission(m,route)
                self.assertEqual(r['jobs'][1]['completion_s'],r['jobs'][0]['completion_s'])
                self.assertGreater(r['jobs'][1]['completion_s'],r['network']['jobs'][1]['arrival_s'])
                self.assertTrue(verify_mission(m,r)['valid'],verify_mission(m,r))
                bad=copy.deepcopy(r);bad['jobs'][1]['completion_s']=bad['network']['jobs'][1]['arrival_s'];bad['receipt_id']=digest({k:v for k,v in bad.items() if k!='receipt_id'})
                self.assertIn('FINAL_COMPLETION',verify_mission(m,bad)['errors'])
                m['jobs'].reverse();self.assertTrue(verify_mission(m,plan_mission(m,route))['valid'])
            m=demo()
            for j in m['jobs']:j[field]=0
            self.assertTrue(verify_mission(m,plan_mission(m,route))['valid'])
        m=demo();m['jobs'][0]['onboard_s']=20;m['jobs'][1]['onboard_s']=0
        self.assertTrue(verify_mission(m,plan_mission(m,'onboard'))['valid'])

    def test_malformed_report_references_all_boundaries(self):
        import tempfile
        from pathlib import Path
        m=demo();original=plan_mission(m,'ground')
        mutations=[lambda r:r['network']['jobs'][0]['hops'][0].update(contact_id='missing'),lambda r:r['dynamics'].update(nodes=[]),lambda r:r.update(dynamics=[]),lambda r:r['network'].update(jobs={}),lambda r:r['proposal'].update(events={}),lambda r:r['network']['jobs'][0].update(hops=[[]])]
        for mutate in mutations:
            r=copy.deepcopy(original);mutate(r);r['receipt_id']=digest({k:v for k,v in r.items() if k!='receipt_id'})
            result=verify_mission(m,r);self.assertFalse(result['valid']);self.assertTrue(any(e.startswith('MALFORMED_EVIDENCE:') for e in result['errors']))
            req=dict(schema='capacity-orbital/mission-tool-v1',id='malformed-report',tool='verify',arguments=dict(mission=m,report=r))
            reply=dispatch(req);self.assertEqual(reply['status'],'evaluated');self.assertFalse(reply['result']['valid'])
            with tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'request.json';path.write_text(json.dumps(req))
                proc=subprocess.run([sys.executable,'-m','capacity.orbital.platform','--request',str(path)],capture_output=True,text=True)
                self.assertEqual(proc.returncode,0,proc.stderr);self.assertNotIn('Traceback',proc.stderr);self.assertFalse(json.loads(proc.stdout)['result']['valid'])

    def test_honest_queue_branch_regressions(self):
        for adjustment in ('outage-at-cursor','retired-at-cursor','retired-mid','memory','rounding','unavailable-cursor'):
            m=demo();m['jobs'][0]['ground_s']=20;m['jobs'][1]['ground_s']=0;g=m['network']['nodes'][m['destination']]
            if adjustment=='outage-at-cursor':g['unavailable']=[dict(start_s=36,end_s=40)]
            elif adjustment=='retired-at-cursor':g['retired_s']=36
            elif adjustment=='retired-mid':g['retired_s']=30
            elif adjustment=='memory':m['jobs'][0]['memory_gb']=m['compute'][m['destination']]['memory_gb']+1
            elif adjustment=='rounding':m['jobs'][0]['ground_s']=.1;m['jobs'][1]['ground_s']=.3
            else:m['jobs'][0]['ground_s']=300
            result=plan_mission(m,'ground');self.assertTrue(verify_mission(m,result)['valid'],(adjustment,verify_mission(m,result)))
        import random
        rng=random.Random(773)
        for _ in range(60):
            m=demo();template=copy.deepcopy(m['jobs'][0]);m['jobs']=[]
            for i in range(4):
                j=copy.deepcopy(template);j.update(id=f'j{3-i}',release_s=rng.choice([0,1,5,20]),memory_gb=rng.choice([1,10000]))
                for key in ('ground_s','hybrid_ground_s','onboard_s','preprocess_s'):j[key]=rng.choice([0,.1,.3,5,20])
                m['jobs'].append(j)
            rng.shuffle(m['jobs'])
            if rng.randrange(2):m['network']['nodes'][m['destination']]['unavailable']=[dict(start_s=20,end_s=30)]
            for route in ('ground','hybrid','onboard'):
                result=plan_mission(m,route);self.assertTrue(verify_mission(m,result)['valid'],verify_mission(m,result))

    def test_replay_extra_fields_and_reason_codes(self):
        m=demo();original=plan_mission(m,'ground')
        for kind in ('extra','reason'):
            result=copy.deepcopy(original)
            if kind=='extra':result['extra_unverified_claim']=1
            else:result['network']['jobs'][0]['reason_code']='altered'
            result['receipt_id']=digest({k:v for k,v in result.items() if k!='receipt_id'})
            self.assertIn('REPLAY_MISMATCH',verify_mission(m,result)['errors'])

    def test_resource_sweep_bounded_diagnostics_and_halfopen(self):
        m=demo();original=plan_mission(m,'ground')
        for overlapping in (True,False):
            result=copy.deepcopy(original)
            result['network']['resource_reservations']=[dict(resource=['synthetic','r'],start_s=0 if overlapping else i,end_s=1 if overlapping else i+1) for i in range(4000)]
            result['receipt_id']=digest({k:v for k,v in result.items() if k!='receipt_id'})
            errors=verify_mission(m,result)['errors']
            self.assertEqual('SHARED_RESOURCE_OVERLAP' in errors,overlapping);self.assertEqual(len(errors),len(set(errors)));self.assertLess(len(errors),10)
        huge=copy.deepcopy(original);huge['processing_buffers']=[dict(node=m['origin'],start_s=i,end_s=i+1,data_gb=0) for i in range(2000)]
        huge['receipt_id']=digest({k:v for k,v in huge.items() if k!='receipt_id'})
        self.assertIn('REPLAY_MISMATCH',verify_mission(m,huge)['errors'])
        for i,b in enumerate(huge['processing_buffers']):b.update(start_s=i/10000,end_s=100+i/10000)
        huge['receipt_id']=digest({k:v for k,v in huge.items() if k!='receipt_id'})
        self.assertTrue(any(e.startswith('VERIFICATION_BUDGET:') for e in verify_mission(m,huge)['errors']))
        result=copy.deepcopy(original);result['network']['resource_reservations']=[dict(resource=['r'],start_s=0,end_s=1),dict(resource=['r'],start_s=1,end_s=2),dict(resource=['r'],start_s=.5,end_s=.5)]
        result['receipt_id']=digest({k:v for k,v in result.items() if k!='receipt_id'})
        self.assertNotIn('SHARED_RESOURCE_OVERLAP',verify_mission(m,result)['errors'])

    def test_large_mismatched_job_coverage_refuses_before_relationships(self):
        m=demo();r=plan_mission(m,'ground');template=r['jobs'][0];network=r['network']['jobs'][0]
        r['jobs']=[dict(template,id='output-'+str(i)) for i in range(2000)]
        r['network']['jobs']=[dict(network,id='other-'+str(i),hops=[]) for i in range(2000)]
        r['receipt_id']=digest({k:v for k,v in r.items() if k!='receipt_id'})
        result=verify_mission(m,r);self.assertIn('JOB_COVERAGE',result['errors']);self.assertTrue(any('coverage differs' in e for e in result['errors']))

    def test_maximum_legal_profiles_and_memory_cursor(self):
        from .contracts import canonical
        m=demo()
        for index,node in enumerate(m['dynamics']['nodes'].values()):
            count=3333
            base=node['profiles'][0]
            node['profiles']=[dict(base,start_s=300*i/count,end_s=300*(i+1)/count) for i in range(count)]
            if index==0:
                first=node['profiles'].pop(0);mid=first['end_s']/2
                node['profiles'][:0]=[dict(first,end_s=mid),dict(first,start_s=mid)]
        self.assertEqual(sum(len(n['profiles']) for n in m['dynamics']['nodes'].values()),10000)
        r=plan_mission(m,'hybrid');self.assertLess(len(canonical(r).encode()),4000000)
        self.assertTrue(r['admissible']);self.assertTrue(verify_mission(m,r)['valid'],verify_mission(m,r))
        # A long admitted stage sets the cursor; a later memory refusal must
        # not reset it backward to that refused job's arrival.
        m=demo();base=copy.deepcopy(m['jobs'][0]);m['jobs']=[dict(base,id='a',ground_s=100),dict(base,id='b',ground_s=0,memory_gb=10000),dict(base,id='c',ground_s=0)]
        r=plan_mission(m,'ground');self.assertTrue(verify_mission(m,r)['valid'],verify_mission(m,r))
        self.assertEqual(r['jobs'][0]['completion_s'],r['jobs'][2]['completion_s'])

class PlatformTimestampAndNumericTests(unittest.TestCase):
    @staticmethod
    def shifted(release,duration,power=1,kind='nominal'):
        m=demo(kind);h=31_557_600
        m['network']['horizon_s']=m['dynamics']['horizon_s']=h;m['authority']['expires_s']=h
        for n in m['network']['nodes'].values():n['retired_s']=h
        for c in m['network']['contacts']:c.update(start_s=0,end_s=h)
        for n in m['dynamics']['nodes'].values():n['profiles'][0]['end_s']=h
        for c in m['compute'].values():c['power_kw']=power
        for j in m['jobs']:j.update(release_s=release,deadline_s=h,ground_s=duration,onboard_s=duration,preprocess_s=duration,hybrid_ground_s=duration)
        return m

    def test_large_timestamp_fractional_honest_reports_and_resealed_edits(self):
        import math
        for release in (16_384,1_000_000,30_000_000,31_000_000):
            for duration in (.1,.3,.7,37.3,1234.5):
                for route in ('ground','onboard','hybrid'):
                    m=self.shifted(release,duration,3);r=plan_mission(m,route)
                    with self.subTest(release=release,duration=duration,route=route):
                        self.assertTrue(verify_mission(m,r)['valid'],verify_mission(m,r))
                        event=next(e for e in r['proposal']['events'] if e['kind']=='compute')
                        expected=event['start_s']+duration
                        if expected-event['start_s']<duration:expected=math.nextafter(expected,math.inf)
                        self.assertEqual(event['end_s'],expected)
                        bad=copy.deepcopy(r);e=next(e for e in bad['proposal']['events'] if e['kind']=='compute');e['end_s']=math.nextafter(e['end_s'],math.inf)
                        bad['receipt_id']=digest({k:v for k,v in bad.items() if k!='receipt_id'})
                        verdict=verify_mission(m,bad);self.assertFalse(verdict['valid']);self.assertIn('COMPUTE_DURATION',verdict['errors']);self.assertIn('REPLAY_MISMATCH',verdict['errors'])
        for route in ('ground','hybrid','onboard'):
            m=self.shifted(31_000_000,1234.5,.7,'battery');r=plan_mission(m,route)
            self.assertFalse(r['admissible']);self.assertTrue(verify_mission(m,r)['valid'])

    def test_timestamp_energy_ulp_allowance_and_replay(self):
        from .platform.verify import _energy_matches
        import math
        start=31_000_000.;limit=.0001234;power=3.;end=start+limit;measured=power*limit/3600
        self.assertTrue(_energy_matches(measured,power,start,end))
        uncertainty=abs(power)/3600*(math.ulp(start)+math.ulp(end))+4*max(math.ulp(measured),math.ulp(power*(end-start)/3600))
        self.assertFalse(_energy_matches(measured+10*uncertainty,power,start,end))
        m=self.shifted(31_000_000,1234.5,3);r=plan_mission(m,'ground')
        self.assertTrue(verify_mission(m,r)['valid'])
        bad=copy.deepcopy(r);row=bad['dynamics']['nodes']['G']['intervals'][-1];row['energy']['load_kwh']+=1e-5
        bad['receipt_id']=digest({k:v for k,v in bad.items() if k!='receipt_id'})
        verdict=verify_mission(m,bad);self.assertFalse(verdict['valid']);self.assertIn('ENERGY_RELATIONSHIP',verdict['errors']);self.assertIn('REPLAY_MISMATCH',verdict['errors'])

    def test_integer_price_hostile_sequences_rejected_before_multiplication(self):
        class NoMultiplyList(list):
            def __mul__(self,other):raise AssertionError('sequence multiplied before numeric validation')
        class NoMultiplyString(str):
            def __mul__(self,other):raise AssertionError('sequence multiplied before numeric validation')
        m=demo()
        for c in m['network']['contacts']:c['cost_per_gb']=10**18
        r=plan_mission(m,'ground');self.assertTrue(verify_mission(m,r)['valid'])
        for value in (NoMultiplyList([0]),NoMultiplyString('x'),[],True,10**400):
            bad=copy.deepcopy(r);bad['network']['jobs'][0]['hops'][0]['data_gb']=value
            bad['receipt_id']=digest({k:v for k,v in bad.items() if k!='receipt_id'})
            verdict=verify_mission(m,bad);self.assertFalse(verdict['valid']);self.assertTrue(any('finite non-boolean number' in e for e in verdict['errors']))
            if type(value) in (list,bool,int):
                response=dispatch(dict(schema='capacity-orbital/mission-tool-v1',id='hostile',tool='verify',arguments=dict(mission=m,report=bad)))
                self.assertFalse(response['result']['valid'])
        # Fresh-process plain nonempty sequences use a small integer price: a
        # regression cannot allocate huge memory in the test runner itself.
        import tempfile
        from pathlib import Path
        for c in m['network']['contacts']:c['cost_per_gb']=7
        r=plan_mission(m,'ground')
        with tempfile.TemporaryDirectory() as folder:
            for value in ([0],'x',True):
                bad=copy.deepcopy(r);bad['network']['jobs'][0]['hops'][0]['data_gb']=value;bad['receipt_id']=digest({k:v for k,v in bad.items() if k!='receipt_id'})
                request=dict(schema='capacity-orbital/mission-tool-v1',id='cli-hostile',tool='verify',arguments=dict(mission=m,report=bad))
                response=dispatch(request);self.assertFalse(response['result']['valid'])
                path=Path(folder)/'request.json';path.write_text(json.dumps(request))
                p=subprocess.run([sys.executable,'-m','capacity.orbital.platform','--request',str(path)],capture_output=True,text=True,timeout=15)
                self.assertEqual(p.returncode,0,p.stderr);self.assertFalse(json.loads(p.stdout)['result']['valid']);self.assertNotIn('Traceback',p.stderr)

    def test_all_report_arithmetic_groups_are_numeric_before_operations(self):
        m=demo();r=plan_mission(m,'ground')
        paths=[('proposal','events',0,'power_kw'),('proposal','events',0,'start_s'),('network','jobs',0,'hops',0,'arrival_s'),('processing_buffers',0,'data_gb'),('dynamics','nodes','A','intervals',0,'energy','load_kwh'),('dynamics','nodes','A','intervals',0,'load_kw'),('cost','partial_operating_usd'),('jobs',0,'completion_s')]
        for path in paths:
            for value in (True,'x',[0],float('inf')):
                bad=copy.deepcopy(r);where=bad
                for key in path[:-1]:where=where[key]
                where[path[-1]]=value
                # Nonfinite canonicalization is already refused before shape checks.
                if value!=float('inf'):bad['receipt_id']=digest({k:v for k,v in bad.items() if k!='receipt_id'})
                self.assertFalse(verify_mission(m,bad)['valid'],path)

if __name__=='__main__':unittest.main()
