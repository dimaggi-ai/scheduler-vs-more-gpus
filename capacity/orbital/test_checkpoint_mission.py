"""Mission-v2 integration oracles and refusal/recovery regressions."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from fractions import Fraction as F
from pathlib import Path
from unittest.mock import patch
from .contracts import digest,canonical
from .platform.mission import source_digest as v1_source,plan_mission
from .platform.checkpoint import (plan_checkpoint_mission as plan,compare_checkpoint_missions as compare,
                                 verify_checkpoint_mission as verify,source_digest,PARENT_SOURCE)
from .platform.checkpoint.fixtures import demo,request
from .platform.checkpoint.contracts import Refuse,parse,enc,normalized,fraction,exact,rational,view,Token
from .platform.checkpoint.tools import dispatch

class CheckpointMission(unittest.TestCase):
    def refusal(self,fn,code):
        with self.assertRaises(Refuse) as cm:fn()
        self.assertEqual(cm.exception.code,code)
        return str(cm.exception)

    def test_parent_and_nominal_routes(self):
        self.assertEqual(v1_source(),PARENT_SOURCE)
        s=demo();old=copy.deepcopy(s)
        for route,completion in [('ground',26),('hybrid',F(54887,4096)),('onboard',6.600000000000001)]:
            r=plan(s,route);self.assertTrue(r['admissible']);self.assertEqual(r['jobs'][0]['completion_s'],float(completion));self.assertTrue(verify(s,r)['valid'])
            self.assertEqual(r['parent_view_sha256'],digest(s['mission']))
            self.assertAlmostEqual(r['cost']['partial_operating_usd'],plan_mission(s['mission'],route)['cost']['partial_operating_usd'],delta=.000002)
        self.assertEqual(s,old)
        hybrid=plan(s,'hybrid')['stages'][1]
        self.assertEqual(fraction(hybrid['replay_release_s']),F(34407,4096))
        self.assertEqual(fraction(hybrid['quantization_delay_s']),F(34407,4096)-F.from_float(8.4))

    def loss(self,preserve=True):
        s=demo();m=s['mission'];j=m['jobs'][0];j['onboard_s']=6
        m['network']['nodes']['A'].update(unavailable=[dict(start_s=5,end_s=7)],preserve_storage=preserve)
        s['replay']['origin']['policy']['checkpoint_every_work_s']=4
        return s

    def test_loss_heat_cost_and_conditional_exclusion(self):
        s=self.loss();r=plan(s,'onboard');stage=r['stages'][0]
        self.assertEqual(fraction(stage['completion_s']),17);self.assertEqual(fraction(stage['replay']['lost_work_s']),4)
        self.assertEqual(fraction(r['cost']['compute_exact_usd']),F(15,100))
        self.assertEqual(fraction(r['energy']['declared_replay_kwh']),F(15,3600))
        for row,event in zip(stage['replay']['trace'],stage['events']):self.assertEqual(event['heat_w'],s['replay']['origin']['heat_w'][row['state']])
        for deadline,battery in [(100,.002),(8,.002),(12,.002),(100,.001)]:
            c=self.loss(False);c['mission']['jobs'][0]['deadline_s']=deadline;c['mission']['dynamics']['nodes']['A']['battery']['initial_kwh']=battery
            cr=plan(c,'onboard');codes=[f['code'] for f in cr['failures']]
            self.assertIn('CHECKPOINT_STORAGE_UNPRESERVED',codes)
            if deadline<17:self.assertIn('DEADLINE',codes)
            self.assertEqual(cr['proposal']['events'],[]);self.assertEqual(fraction(cr['energy']['declared_replay_kwh']),0)
            self.assertFalse(cr['network']['jobs']);self.assertTrue(cr['stages'][0]['conditional'])
            self.assertFalse(any(x.startswith('DYNAMICS_BATTERY') for x in codes));self.assertTrue(verify(c,cr)['valid'])

    def test_decimal_energy_and_retirement(self):
        s=demo();s['mission']['jobs'][0]['onboard_s']=10
        s['mission']['compute']['A'].update(power_kw=.35,heat_w=33.3);s['replay']['origin']['power_kw']['productive']=.35;s['replay']['origin']['heat_w']['productive']=33.3
        r=plan(s,'onboard');self.assertEqual(fraction(r['energy']['declared_replay_kwh']),F(7,7200))
        self.assertNotEqual(fraction(r['energy']['signed_conversion_difference_kwh']),0)
        s=demo();s['mission']['jobs'][0].update(onboard_s=120,deadline_s=200);s['mission']['network']['nodes']['A']['retired_s']=100
        r=plan(s,'onboard');self.assertEqual(fraction(r['stages'][0]['terminal_s']),100);self.assertIn('COMPUTE_UNAVAILABLE',[f['code'] for f in r['failures']]);self.assertTrue(all(x['end_s']<=100 for x in r['proposal']['events']))

    def test_zero_origin_and_zero_ground(self):
        for release,adjacent in [(6,False),(5,False),(6,True),(5,True)]:
            s=demo();s['mission']['jobs'][0].update(onboard_s=0,release_s=release)
            s['mission']['network']['nodes']['A']['unavailable']=[dict(start_s=5,end_s=7)]+([dict(start_s=7,end_s=9)] if adjacent else [])
            r=plan(s,'onboard');self.assertEqual(fraction(r['stages'][0]['completion_s']),9 if adjacent else 7);self.assertIsNone(r['stages'][0]['replay'])
        s=demo();s['mission']['jobs'][0].update(preprocess_s=0,hybrid_ground_s=0,deadline_s=6.4)
        r=plan(s,'hybrid');self.assertTrue(r['admissible']);self.assertEqual(r['jobs'][0]['completion_s'],6.4);self.assertEqual(fraction(r['stages'][1]['quantization_delay_s']),0)

    def test_long_identifiers_remap_and_tampering(self):
        s=demo();s['mission']['jobs'][0]['id']='j'*200;r=plan(s,'ground')
        self.assertTrue(r['admissible']);self.assertTrue(all(len(e['id'])<=200 for e in r['proposal']['events']))
        for mutate in [lambda x:x['transfer_event_map'].reverse(),lambda x:x['proposal']['events'][0].update(power_kw=99),lambda x:x['stages'][0]['replay']['trace'][0].update(state='down'),lambda x:x.update(source_sha256='0'*64)]:
            bad=copy.deepcopy(r);mutate(bad);bad.pop('receipt_id');bad['receipt_id']=digest(bad);self.assertFalse(verify(s,bad)['valid'])

    def test_selected_domain_and_corrected_retry(self):
        s=demo();s['mission']['jobs'][0].update(onboard_s=5.1,ground_s=10.1);s['mission']['network']['nodes']['G']['retired_s']=299.9
        self.assertTrue(plan(s,'hybrid')['admissible'])
        for change in [lambda x:x['mission']['jobs'][0].update(preprocess_s=2.1),lambda x:x['mission']['jobs'][0].update(deadline_s=99.9),lambda x:x['mission']['network']['nodes']['G'].update(unavailable=[dict(start_s=250.1,end_s=260)])]:
            c=copy.deepcopy(s);change(c);self.refusal(lambda:plan(c,'hybrid'),'UNSUPPORTED_NUMERIC_DOMAIN')
        self.assertTrue(plan(s,'hybrid')['admissible'])
        c=demo();c['mission']['network']['nodes']['A']['unavailable']=[dict(start_s=0,end_s=300)];c['mission']['network']['nodes']['G']['unavailable']=[dict(start_s=250.1,end_s=260)]
        self.refusal(lambda:plan(c,'hybrid'),'UNSUPPORTED_NUMERIC_DOMAIN')
        c=demo();c['mission']['compute']['A']['power_kw']=6.600000000000001;c['replay']['origin']['power_kw']['productive']=6.600000000000001
        self.refusal(lambda:plan(c,'hybrid'),'UNSUPPORTED_NUMERIC_DOMAIN')

    def test_numeric_views_parser_bounds(self):
        self.assertEqual(view(Token('1e-300')),1e-300)
        self.assertEqual(view(Decimal('1E+1'),'mission.diligence.lifecycle.horizon_years'),10)
        self.refusal(lambda:view(Token('1e-400')),'UNSUPPORTED_NUMERIC_DOMAIN')
        self.refusal(lambda:exact(Token('1e-4301')),'BUDGET_EXCEEDED')
        self.refusal(lambda:rational(F(10**1200)),'BUDGET_EXCEEDED')
        for raw in [b'{"a":1,"a":2}',b'{"a":NaN}',b'{}\xff','{}'.encode('utf-16')]:self.refusal(lambda:parse(raw),'INVALID_ARGUMENT')
        self.refusal(lambda:parse(b' '*1_000_001+b'{}'),'BUDGET_EXCEEDED')
        self.refusal(lambda:parse(b'['*10000+b']'*10000),'BUDGET_EXCEEDED')
        s=demo();s['mission']['compute']['G']['cost_per_s_usd']=Decimal('0.01000000000000000000000001')
        r=plan(s,'ground');self.assertNotEqual(r['input_sha256'],plan(demo(),'ground')['input_sha256']);self.assertEqual(r['parent_view_sha256'],plan(demo(),'ground')['parent_view_sha256'])

    def test_exact_grid_and_report_transport(self):
        from .platform.checkpoint.contracts import selected
        self.assertEqual(selected(Decimal('99999.000244140625'),'exact',time=True),Decimal('99999.000244140625'))
        self.refusal(lambda:selected(99999.00024414062,'repr',time=True),'UNSUPPORTED_NUMERIC_DOMAIN')
        self.refusal(lambda:selected(Decimal('0.0001220703125'),'half-grid',time=True),'UNSUPPORTED_NUMERIC_DOMAIN')
        s=demo();s['mission']['jobs'][0]['onboard_s']=.5
        s['replay']['origin']['policy'].update(checkpoint_every_work_s=Decimal('0.000244140625'),checkpoint_duration_s=Decimal('0.000244140625'))
        self.refusal(lambda:plan(s,'onboard'),'BUDGET_EXCEEDED')
        s['mission']['jobs'][0]['onboard_s']=.25
        r=plan(s,'onboard');self.assertEqual(len(r['stages'][0]['replay']['trace']),2047)
        # Preserve exact declarations in JSON, rather than serialize Decimal as strings.
        scenario_json=canonical(demo()).replace('"onboard_s":5','"onboard_s":0.25').replace('"checkpoint_every_work_s":null','"checkpoint_every_work_s":0.000244140625').replace('"checkpoint_duration_s":2','"checkpoint_duration_s":0.000244140625')
        original=parse(('{"schema":"capacity-orbital/checkpoint-mission-tool-v2","id":"large","tool":"plan","input":{"route":"onboard","scenario":'+scenario_json+'}}').encode())
        actual=dispatch(original);self.assertEqual(actual['status'],'ok')
        raw=('{"schema":"capacity-orbital/checkpoint-mission-tool-v2","id":"verify-large","tool":"verify","input":{"scenario":'+scenario_json+',"report":'+canonical(actual['result'])+'}}\n').encode()
        result=dispatch(parse(raw));self.assertEqual(result['status'],'ok');self.assertTrue(result['result']['valid'])

    def test_scope_and_typed_parent_boundaries(self):
        from .diligence.contracts import Refuse as DR
        for code,expected in [('BUDGET_EXCEEDED','BUDGET_EXCEEDED'),('ARITHMETIC_RESOLUTION','UNSUPPORTED_NUMERIC_DOMAIN'),('UNSUPPORTED_CURRENCY','INVALID_ARGUMENT')]:
            with patch('capacity.orbital.platform.checkpoint.contracts.parent_validate',side_effect=DR(code,'injected typed validation')):
                self.refusal(lambda:plan(demo(),'ground'),expected)
        s=demo();s['mission']['dynamics']['nodes']['A']['profiles'][0]['background_kw']=.1
        self.refusal(lambda:plan(s,'ground'),'UNSUPPORTED_SCOPE')
        s=demo();s['mission']['jobs'][0]['onboard_s']=31_557_601
        self.refusal(lambda:plan(s,'onboard'),'INVALID_ARGUMENT')
        s=demo();s['mission']['diligence']['lifecycle']['horizon_years']=Decimal('1E+1')
        r=dispatch(dict(schema=request()['schema'],id='decimal-horizon',tool='plan',input=dict(scenario=s,route='ground')))
        self.assertEqual(r['status'],'ok')

    def test_fixed_comparison_and_allowed_descriptions(self):
        s=demo();pin=digest(enc(normalized(s)));c=copy.deepcopy(s);c['id']='candidate';c['mission']['id']='new';c['mission']['diligence']['mission_id']='new';c['replay']['origin']['policy'].update(version='new',checkpoint_every_work_s=4)
        self.assertEqual(compare(s,c,'onboard',pin)['outcome'],'both_admissible')
        self.refusal(lambda:compare(s,c,'onboard','0'*64),'BASELINE_BINDING')
        changes=[lambda x:x['mission']['compute']['A'].update(cost_per_s_usd=.02),lambda x:x['replay']['origin']['policy'].update(restart_duration_s=3),lambda x:x['mission']['jobs'][0].update(raw_gb=2),lambda x:x['replay']['origin']['heat_w'].update(down=99)]
        for change in changes:
            c=copy.deepcopy(s);change(c);self.refusal(lambda:compare(s,c,'onboard',pin),'BASELINE_MISMATCH')

    def test_named_parent_errors_and_programmer_propagation(self):
        for message,code in [('positive transfer duration below numeric resolution','UNSUPPORTED_NUMERIC_DOMAIN'),('energy conservation failure',None)]:
            with patch('capacity.orbital.platform.checkpoint.plan_network',side_effect=ValueError(message)):
                if code:self.refusal(lambda:plan(demo(),'ground'),code)
                else:
                    with self.assertRaisesRegex(ValueError,message):plan(demo(),'ground')
        with patch('capacity.orbital.platform.checkpoint.contracts.parent_validate',side_effect=ValueError('future validator error')):
            self.refusal(lambda:plan(demo(),'ground'),'INVALID_ARGUMENT')
        with patch('capacity.orbital.platform.checkpoint.evaluate',side_effect=ValueError('shared-clock node/interval budget exceeds 100000')):
            self.refusal(lambda:plan(demo(),'ground'),'BUDGET_EXCEEDED')

    def test_real_cli_roundtrip_refusal_and_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'request.json';out=Path(td)/'report.json'
            def run(req,output=False):
                path.write_text(canonical(req)+'\n');p=subprocess.run([sys.executable,'-m','capacity.orbital.platform.checkpoint','--request',str(path)]+(['--output',str(out)] if output else []),capture_output=True,text=True,timeout=20)
                return p,json.loads(p.stdout)
            p,r=run(request(),True);self.assertEqual(p.returncode,0);self.assertEqual(out.read_text(),canonical(r)+'\n');before=out.read_bytes()
            _,bad=run(request(),True);self.assertEqual(bad['code'],'IO_ERROR');self.assertEqual(bad['id'],'demo-plan');self.assertEqual(before,out.read_bytes())
            _,v=run(dict(schema=request()['schema'],id='verify',tool='verify',input=dict(scenario=demo(),report=r['result'])));self.assertTrue(v['result']['valid'])
            req=request();req['input']['scenario']['mission']['jobs'][0]['preprocess_s']=2.1
            _,refused=run(req);self.assertEqual(refused['code'],'UNSUPPORTED_NUMERIC_DOMAIN');self.assertEqual(refused['id'],'demo-plan')
            _,good=run(request());self.assertEqual(good['status'],'ok')

if __name__=='__main__':unittest.main()
