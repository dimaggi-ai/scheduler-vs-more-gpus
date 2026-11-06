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

    def test_required_source_missing_or_unreadable_refuses(self):
        from .platform.checkpoint import REQUIRED_SOURCE
        root=Path(__file__).resolve().parent.parent
        original=Path.read_bytes
        s=demo();report=plan(s,'hybrid');pin=digest(enc(normalized(s)))
        # Every required source must remain bound after it has been imported.
        for name in REQUIRED_SOURCE:
            missing=root/name
            def read(path, target=missing):
                if path==target:raise FileNotFoundError('synthetic missing source')
                return original(path)
            with patch.object(Path,'read_bytes',read):
                self.refusal(source_digest,'SOURCE_UNAVAILABLE')
        for name in ('orbital/platform/checkpoint/contracts.py','orbital/platform/contracts.py','orbital/reliability/contracts.py','__init__.py'):
            missing=root/name
            def read(path, target=missing):
                if path==target:raise PermissionError('synthetic unreadable source')
                return original(path)
            with patch.object(Path,'read_bytes',read):
                for fn in (lambda:plan(s,'hybrid'),lambda:verify(s,report),lambda:compare(s,s,'hybrid',pin)):
                    self.refusal(fn,'SOURCE_UNAVAILABLE')
                for tool,data in [('plan',dict(scenario=s,route='hybrid')),('verify',dict(scenario=s,report=report)),('compare',dict(baseline=s,candidate=s,route='hybrid',expected_baseline_sha256=pin))]:
                    result=dispatch(dict(schema=request()['schema'],id='missing-source',tool=tool,input=data))
                    self.assertEqual(result['code'],'SOURCE_UNAVAILABLE');self.assertEqual(result['id'],'missing-source')
        self.assertTrue(verify(s,plan(s,'hybrid'))['valid'])
        self.assertEqual(compare(s,s,'hybrid',pin)['outcome'],'both_admissible')

    def test_failure_coverage_and_shared_planner_defects(self):
        scenarios=[]
        for code,change,route in [
            ('PROCESSING_BUFFER_CAPACITY',lambda m:m['network']['nodes']['A'].update(buffer_gb=.5),'onboard'),
            ('DYNAMICS_BATTERY_RESERVE',lambda m:m['dynamics']['nodes']['A']['battery'].update(initial_kwh=.0001),'onboard'),
            ('QUALITY',lambda m:m['jobs'][0].update(onboard_quality=.1),'onboard'),
            ('COMPUTE_MEMORY',lambda m:m['compute']['A'].update(memory_gb=.5),'onboard'),
            ('NETWORK_',lambda m:m['network'].update(contacts=[]),'ground')]:
            scenario=demo();change(scenario['mission']);report=plan(scenario,route)
            self.assertFalse(report['admissible']);self.assertTrue(any(f['code'].startswith(code) for f in report['failures']));self.assertTrue(verify(scenario,report)['valid'])
            bad=copy.deepcopy(report);bad['failures']=[];bad['admissible']=True
            if code=='PROCESSING_BUFFER_CAPACITY':bad['processing_buffers']=[]
            bad.pop('receipt_id');bad['receipt_id']=digest(bad)
            # A shared planner bug also appears on replan. Relationship checks must
            # reject it even though whole-report replay equality now succeeds.
            with patch('capacity.orbital.platform.checkpoint.plan_checkpoint_mission',return_value=bad):
                self.assertFalse(verify(scenario,bad)['valid'],code)
        s=demo();r=plan(s,'hybrid')
        for collection in ('events','replay_event_map'):
            bad=copy.deepcopy(r);bad['stages'][0][collection].pop();bad.pop('receipt_id');bad['receipt_id']=digest(bad)
            with patch('capacity.orbital.platform.checkpoint.plan_checkpoint_mission',return_value=bad):
                self.assertIn('TRACE_CARDINALITY',verify(s,bad)['errors'])
        bad=copy.deepcopy(r);event=bad['stages'][0]['events'][0];ident=event['id'];event['start_s']+=1;event['end_s']+=1
        for e in bad['proposal']['events']:
            if e['id']==ident:e.update(start_s=event['start_s'],end_s=event['end_s'])
        with patch('capacity.orbital.platform.checkpoint.plan_checkpoint_mission',return_value=bad):
            self.assertIn('DECLARED_EVENT_MAPPING',verify(s,bad)['errors'])
        with patch('capacity.orbital.platform.checkpoint.parent_source_digest',return_value='0'*64):
            self.refusal(lambda:plan(s,'hybrid'),'SOURCE_MISMATCH')

    def test_report_numeric_view_and_scenario_preflight(self):
        from .platform.checkpoint.contracts import Token
        for badvalue in (Token('1e-400'),Token('1e400')):
            s=demo();r=plan(s,'hybrid');r['jobs'][0]['completion_s']=badvalue
            self.assertFalse(verify(s,r)['valid'])
            result=dispatch(dict(schema=request()['schema'],id='evidence',tool='verify',input=dict(scenario=s,report=r)))
            self.assertEqual(result['status'],'ok');self.assertFalse(result['result']['valid'])
        req=dict(schema=request()['schema'],id='oversized-scenario',tool='verify',input=dict(scenario={'values':[1]*50_001},report={}))
        with patch('capacity.orbital.platform.checkpoint.tools.normalize',side_effect=AssertionError('must not normalize oversized scenario')):
            # Envelope normalization is small; guard scenario before any normalization.
            result=dispatch(req)
        self.assertEqual(result['code'],'BUDGET_EXCEEDED')
        self.refusal(lambda:parse(b'{"tool":"verify","id":"bad-unicode","input":{"scenario":{"x":"\\ud800"}}}'),'INVALID_ARGUMENT')

    def test_source_inventory_import_coverage_and_guarded_startup(self):
        import shutil
        from .platform.checkpoint import REQUIRED_SOURCE
        root=Path(__file__).resolve().parent.parent
        code="""import json,sys
from pathlib import Path
from capacity.orbital.platform.checkpoint import plan_checkpoint_mission,verify_checkpoint_mission,compare_checkpoint_missions
from capacity.orbital.platform.checkpoint.fixtures import demo
from capacity.orbital.platform.checkpoint.tools import dispatch
from capacity.orbital.platform.checkpoint.contracts import enc,normalized
from capacity.orbital.contracts import digest
s=demo();r=plan_checkpoint_mission(s,'hybrid');verify_checkpoint_mission(s,r);compare_checkpoint_missions(s,s,'hybrid',digest(enc(normalized(s))))
root=Path('capacity').resolve()
print(json.dumps(sorted(str(Path(m.__file__).resolve().relative_to(root)) for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(root))))
"""
        run=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stderr);self.assertLessEqual(set(json.loads(run.stdout)),set(REQUIRED_SOURCE))
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'capacity';shutil.copytree(root,target,ignore=shutil.ignore_patterns('__pycache__'))
            launcher=target/'orbital/platform/checkpoint/cli.py'
            for name in ('orbital/platform/checkpoint/contracts.py','orbital/platform/checkpoint/tools.py','orbital/platform/mission.py'):
                path=target/name;hidden=path.with_suffix('.hidden');path.rename(hidden)
                try:
                    run=subprocess.run([sys.executable,str(launcher),'--request','unused','--output',str(target/'must-not-publish.json')],capture_output=True,text=True,timeout=20)
                    self.assertEqual(run.returncode,2);self.assertEqual(json.loads(run.stdout)['code'],'SOURCE_UNAVAILABLE');self.assertNotIn('Traceback',run.stderr);self.assertFalse((target/'must-not-publish.json').exists())
                finally:hidden.rename(path)
            import os
            foreign=Path(td)/'foreign/capacity';foreign.mkdir(parents=True)
            (foreign/'__init__.py').write_text("raise RuntimeError('wrong source tree')\n")
            env=dict(os.environ,PYTHONPATH=str(foreign.parent))
            run=subprocess.run([sys.executable,str(launcher),'--request',str(target/'orbital/examples/checkpoint-mission-plan.json')],env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(json.loads(run.stdout)['status'],'ok')

    def test_zero_ground_availability_independent_of_planner(self):
        s=demo();s['mission']['jobs'][0].update(preprocess_s=0,hybrid_ground_s=0)
        s['mission']['network']['nodes']['G']['unavailable']=[dict(start_s=6.4,end_s=7.4)]
        r=plan(s,'hybrid');self.assertFalse(r['admissible']);self.assertIn('COMPUTE_UNAVAILABLE',[f['code'] for f in r['failures']]);self.assertTrue(verify(s,r)['valid'])
        bad=copy.deepcopy(r);bad['stages'][1]['failures']=[];bad['stages'][1]['completion_s']=dict(numerator='32',denominator='5');bad['jobs'][0]['completion_s']=6.4;bad['failures']=[];bad['admissible']=True
        bad.pop('receipt_id');bad['receipt_id']=digest(bad)
        with patch('capacity.orbital.platform.checkpoint.plan_checkpoint_mission',return_value=bad):
            self.assertIn('FAILURE_COVERAGE',verify(s,bad)['errors'])

    def test_independent_relationship_check_table(self):
        from .network import plan_network
        s=demo();base=plan(s,'hybrid')
        def no_delivery(r):
            r['network_input']['jobs']=[]
            r['network']=plan_network(r['network_input'],source_sha256=r['source_sha256'])
        cases=[
            ('AUTHORITY_CLAIM',lambda r:r.update(promoted=True)),
            ('STAGE_COVERAGE',lambda r:r['stages'].reverse()),
            ('TRANSFER_DATA_PRECEDENCE',lambda r:r['stages'][0].update(completion_s=dict(numerator='3',denominator='1'))),
            ('FINAL_COMPLETION',lambda r:r['jobs'][0].update(completion_s=99)),
            ('GROUND_WITHOUT_DELIVERY',no_delivery),
            ('PROCESSING_BUFFER_COVERAGE',lambda r:r['processing_buffers'].clear()),
            ('DYNAMICS_BINDING',lambda r:r['dynamics'].update(extra='wrong')),
            ('ADMISSIBILITY',lambda r:r.update(admissible=False)),
            ('INCOMPLETE_ADMISSIBLE',lambda r:r['jobs'][0].update(completion_s=None)),
            ('TRANSFER_CARDINALITY',lambda r:r['transfer_event_map'].pop()),
            ('AUTHORITY_BINDING',lambda r:r['proposal']['authority'].update(expires_s=299)),
            ('TRANSFER_EVENT_BINDING',lambda r:r['transfer_event_map'][0].update(original_event_id='wrong')),
            ('DECLARED_RESOURCE_BINDING',lambda r:r['stages'][0]['replay_event_map'][0].update(declared_heat_w=dict(numerator='101',denominator='1'))),
            ('TRANSFER_ID_BINDING',lambda r:r['transfer_event_map'][0].update(mapped_event_id='wrong'))]
        for code,mutate in cases:
            r=copy.deepcopy(base);mutate(r);r.pop('receipt_id');r['receipt_id']=digest(r)
            with patch('capacity.orbital.platform.checkpoint.plan_checkpoint_mission',return_value=r):
                self.assertIn(code,verify(s,r)['errors'],code)

    def test_report_transport_limits_and_parsed_evidence(self):
        from .platform.checkpoint.verify import prepare_report
        s=demo();values=[]
        deep={};cursor=deep
        for _ in range(70):cursor['x']={};cursor=cursor['x']
        for report,code in [(deep,'BUDGET_EXCEEDED'),({'text':'\ud800'},'INVALID_ARGUMENT'),([0]*1_000_001,'BUDGET_EXCEEDED')]:
            self.refusal(lambda:verify(s,report),code)
            req=dict(schema=request()['schema'],id='transport',tool='verify',input=dict(scenario=s,report=report))
            self.assertEqual(dispatch(req)['code'],code)
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)/'request.json';path.write_text(canonical(req)+'\n')
                proc=subprocess.run([sys.executable,'-m','capacity.orbital.platform.checkpoint','--request',str(path)],capture_output=True,text=True,timeout=30)
                self.assertEqual(proc.returncode,2);self.assertEqual(json.loads(proc.stdout)['code'],code)
        self.refusal(lambda:verify(s,{'oversized':'x'*8_000_001}),'BUDGET_EXCEEDED')
        with patch('capacity.orbital.platform.checkpoint.verify.view',side_effect=AssertionError('invalid root must not normalize')):
            self.assertIsNone(prepare_report([0]*990_000))
        for report in ([],{},'invalid evidence'):
            self.assertFalse(verify(s,report)['valid'])
            req=dict(schema=request()['schema'],id='parsed',tool='verify',input=dict(scenario=s,report=report))
            self.assertEqual(dispatch(req)['status'],'ok');self.assertFalse(dispatch(req)['result']['valid'])
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)/'request.json';path.write_text(canonical(req)+'\n')
                proc=subprocess.run([sys.executable,'-m','capacity.orbital.platform.checkpoint','--request',str(path)],capture_output=True,text=True,timeout=30)
                self.assertEqual(proc.returncode,0);self.assertFalse(json.loads(proc.stdout)['result']['valid'])

    def test_startup_preflight_manifest_and_import_race(self):
        import shutil
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);capacity=root/'capacity'
            shutil.copytree(Path(__file__).resolve().parent.parent,capacity,ignore=shutil.ignore_patterns('__pycache__'))
            launcher=capacity/'orbital/platform/checkpoint/cli.py'
            manifest=launcher.with_name('source_inventory.json');original=manifest.read_bytes()
            for invalid in ({},[],['../escape'],['/absolute'],[3]):
                manifest.write_text(json.dumps(invalid))
                run=subprocess.run([sys.executable,str(launcher),'--request','unused'],capture_output=True,text=True,timeout=20)
                self.assertEqual(run.returncode,2);self.assertEqual(json.loads(run.stdout)['code'],'SOURCE_UNAVAILABLE')
            manifest.write_bytes(original)
            # Missing a non-eager source must refuse before any project import.
            initializer=capacity/'__init__.py';saved=initializer.read_bytes();marker=root/'imported'
            initializer.write_text("from pathlib import Path\nPath("+repr(str(marker))+").write_text('imported')\n")
            unused=capacity/'orbital/benchmark.py';hidden=unused.with_suffix('.hidden');unused.rename(hidden)
            run=subprocess.run([sys.executable,str(launcher),'--request','unused'],capture_output=True,text=True,timeout=20)
            self.assertEqual(run.returncode,2);self.assertFalse(marker.exists())
            hidden.rename(unused);initializer.write_bytes(saved)
            wrapper=root/'probe.py'
            template="""import runpy,builtins,sys
from pathlib import Path
ns=runpy.run_path(LAUNCHER)
real=builtins.__import__;triggered=False
def intercept(name,*args,**kwargs):
 global triggered
 if name=='capacity' and not triggered:
  triggered=True
  ACTION
 return real(name,*args,**kwargs)
builtins.__import__=intercept
sys.argv=['cli.py','--request','unused']
raise SystemExit(ns['main']())
"""
            target=capacity/'orbital/dynamics/__init__.py';hidden=target.with_suffix('.hidden')
            for action,refuses in [("Path("+repr(str(target))+").rename("+repr(str(hidden))+")",True),("raise ImportError('synthetic programmer error')",False),("raise RuntimeError('synthetic programmer error')",False)]:
                wrapper.write_text(template.replace('LAUNCHER',repr(str(launcher))).replace('ACTION',action))
                run=subprocess.run([sys.executable,str(wrapper)],capture_output=True,text=True,timeout=20)
                if refuses:
                    self.assertEqual(run.returncode,2,run.stderr);self.assertEqual(json.loads(run.stdout)['code'],'SOURCE_UNAVAILABLE');hidden.rename(target)
                else:self.assertNotEqual(run.returncode,0);self.assertIn('synthetic programmer error',run.stderr);self.assertEqual(run.stdout,'')

    def test_parent_and_nominal_routes(self):
        self.assertEqual(v1_source(),PARENT_SOURCE)
        s=demo();old=copy.deepcopy(s)
        for route,completion in [('ground',26),('hybrid',F(54887,4096)),('onboard',6.600000000000001)]:
            r=plan(s,route);self.assertTrue(r['admissible']);self.assertIs(r['execution_performed'],False);self.assertIs(r['promoted'],False);self.assertEqual(r['jobs'][0]['completion_s'],float(completion));self.assertTrue(verify(s,r)['valid'])
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
        r=plan(s,'hybrid');self.assertTrue(r['admissible']);self.assertIs(r['execution_performed'],False);self.assertIs(r['promoted'],False);self.assertEqual(r['jobs'][0]['completion_s'],6.4);self.assertEqual(fraction(r['stages'][1]['quantization_delay_s']),0)

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

    def test_regression_summary_and_weighted_energy(self):
        s=self.loss();s['mission']['jobs'][0]['deadline_s']=20
        candidate=copy.deepcopy(s);candidate['replay']['origin']['policy']['checkpoint_every_work_s']=1
        result=compare(s,candidate,'onboard',digest(enc(normalized(s))))
        self.assertEqual(result['outcome'],'regression');self.assertIsNone(result['deltas']['completion_s']);self.assertIs(result['promoted'],False)
        s=self.loss();s['replay']['origin']['power_kw'].update(checkpoint=3,restart=2)
        self.assertEqual(fraction(plan(s,'onboard')['energy']['declared_replay_kwh']),F(23,3600))

    def test_fixed_comparison_and_allowed_descriptions(self):
        s=demo();pin=digest(enc(normalized(s)));c=copy.deepcopy(s);c['id']='candidate';c['mission']['id']='new';c['mission']['diligence']['mission_id']='new';c['replay']['origin']['policy'].update(version='new',checkpoint_every_work_s=4)
        self.assertEqual(compare(s,c,'onboard',pin)['outcome'],'both_admissible')
        self.refusal(lambda:compare(s,c,'onboard','0'*64),'BASELINE_BINDING')
        changes=[lambda x:x['mission']['compute']['A'].update(cost_per_s_usd=.02),lambda x:x['replay']['origin']['policy'].update(restart_duration_s=3),lambda x:x['replay']['origin']['policy'].update(checkpoint_duration_s=3),lambda x:x['mission']['jobs'][0].update(raw_gb=2),lambda x:x['replay']['origin']['heat_w'].update(down=99)]
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
            for numeric in ('1e-400','1e400'):
                evidence=copy.deepcopy(r['result']);evidence['jobs'][0]['completion_s']='RAW_NUMBER'
                envelope=dict(schema=request()['schema'],id='invalid-evidence',tool='verify',input=dict(scenario=demo(),report=evidence))
                path.write_text(canonical(envelope).replace('"RAW_NUMBER"',numeric)+'\n')
                proc=subprocess.run([sys.executable,'-m','capacity.orbital.platform.checkpoint','--request',str(path)],capture_output=True,text=True,timeout=20)
                value=json.loads(proc.stdout);self.assertEqual(proc.returncode,0);self.assertEqual(value['status'],'ok');self.assertFalse(value['result']['valid'])
            req=request();req['input']['scenario']['mission']['jobs'][0]['preprocess_s']=2.1
            proc,refused=run(req);self.assertEqual(proc.returncode,2);self.assertEqual(refused['code'],'UNSUPPORTED_NUMERIC_DOMAIN');self.assertEqual(refused['id'],'demo-plan')
            refused_path=Path(td)/'must-not-exist.json'
            path.write_text(canonical(req)+'\n')
            proc=subprocess.run([sys.executable,'-m','capacity.orbital.platform.checkpoint','--request',str(path),'--output',str(refused_path)],capture_output=True,text=True,timeout=20)
            self.assertEqual(proc.returncode,2);self.assertFalse(refused_path.exists())
            _,good=run(request());self.assertEqual(good['status'],'ok')

if __name__=='__main__':unittest.main()
