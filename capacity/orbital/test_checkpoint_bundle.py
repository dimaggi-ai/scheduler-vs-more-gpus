"""Portable exact-text evidence, agent transport, and file publication controls."""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from .contracts import canonical,digest
from .platform.checkpoint.fixtures import request
from .platform.checkpoint import source_digest as checkpoint_source
from .platform.mission import source_digest as parent_source
from .checkpoint_bundle import export_checkpoint_bundle as export,verify_checkpoint_bundle as verify,CHECKPOINT_SOURCE,source_digest
from .checkpoint_bundle.contracts import Refuse,wire,parse,BUNDLE,TOOL,INNER
from .checkpoint_bundle.tools import dispatch,dispatch_json

class CheckpointBundle(unittest.TestCase):
    def inner(self,route='hybrid'):return canonical(request(route))+'\n'
    def tool(self,name,data,ident='delivery'):
        return dict(schema='capacity-orbital/checkpoint-bundle-tool-v1',id=ident,tool=name,input=data)
    def refused(self,fn,code=None):
        with self.assertRaises(Refuse) as cm:fn()
        if code:self.assertEqual(cm.exception.code,code)
    def seal(self,envelope):
        envelope['sha256']=digest(envelope['content']);return wire(envelope,BUNDLE)

    def test_exact_original_and_tool_roundtrip(self):
        req=request('onboard');scenario=req['input']['scenario'];scenario['mission']['jobs'][0]['onboard_s']=10
        for role,node in [('origin','A'),('destination','G')]:
            scenario['mission']['compute'][node].update(power_kw=.35,heat_w=33.3)
            scenario['replay'][role]['power_kw']['productive']=.35;scenario['replay'][role]['heat_w']['productive']=33.3
        raw=canonical(req).replace('"cost_per_s_usd":0.01','"cost_per_s_usd":1e-300')
        result=dispatch(self.tool('export',dict(request_json=raw)))
        self.assertEqual(result['status'],'ok');bundle=result['result'];content=json.loads(bundle['bundle_json'])['content']
        self.assertEqual(content['request_json'],raw);self.assertIn('1e-300',content['request_json'])
        self.assertEqual(content['report']['energy']['declared_replay_kwh'],dict(numerator='7',denominator='7200'))
        verified=dispatch_json(wire(self.tool('verify',dict(bundle_json=bundle['bundle_json'],expected_sha256=bundle['sha256']),ident='another-delivery'),TOOL))
        self.assertTrue(verified['result']['valid']);self.assertEqual(verified['id'],'another-delivery');self.assertFalse(verified['result']['authenticity_established'])
        spelling=export(' '+raw);self.assertNotEqual(spelling['sha256'],bundle['sha256']);self.assertEqual(json.loads(spelling['bundle_json'])['content']['scenario_sha256'],content['scenario_sha256'])

    def test_precision_and_resealed_substitution(self):
        a=export(self.inner());other=self.inner().replace('"cost_per_s_usd":0.01','"cost_per_s_usd":0.01000000000000000000000001');b=export(other)
        ar=json.loads(a['bundle_json'])['content']['report'];br=json.loads(b['bundle_json'])['content']['report']
        self.assertNotEqual(ar['input_sha256'],br['input_sha256']);self.assertEqual(ar['parent_view_sha256'],br['parent_view_sha256'])
        self.assertTrue(verify(b['bundle_json'])['valid']);self.assertFalse(verify(b['bundle_json'],a['sha256'])['valid'])
        for target in ('request','route','map','source','scenario','report','boolean','sha'):
            env=json.loads(a['bundle_json']);c=env['content']
            if target=='request':c['request_json']=other
            elif target=='route':c['report']['route']='ground'
            elif target=='map':c['report']['transfer_event_map'][0]['mapped_event_id']='wrong'
            elif target=='source':c['checkpoint_source_sha256']='0'*64
            elif target=='scenario':c['scenario_sha256']='0'*64
            elif target=='report':c['report']['jobs'][0]['completion_s']=0
            elif target=='boolean':c['execution_performed']=0
            else:env['sha256']='0'*64
            text=wire(env,BUNDLE) if target=='sha' else self.seal(env)
            self.assertFalse(verify(text)['valid'],target)
        self.refused(lambda:verify(a['bundle_json'],'X'*64),'INVALID_ARGUMENT')
        with patch('capacity.orbital.platform.checkpoint.verify_checkpoint_mission',side_effect=RuntimeError('programmer defect')):
            with self.assertRaisesRegex(RuntimeError,'programmer defect'):verify(a['bundle_json'])

    def test_single_verifier_replan_and_inadmissible_evidence(self):
        from .platform.checkpoint import verify_checkpoint_mission
        cases=[]
        r=request();r['input']['scenario']['mission']['dynamics']['nodes']['A']['battery']['initial_kwh']=.0001;cases.append(r)
        r=request('onboard');s=r['input']['scenario'];s['mission']['network']['nodes']['A'].update(preserve_storage=False,unavailable=[dict(start_s=5,end_s=7)]);s['mission']['jobs'][0].update(onboard_s=6,deadline_s=8);s['replay']['origin']['policy']['checkpoint_every_work_s']=4;cases.append(r)
        for r in cases:
            bundle=export(canonical(r));self.assertFalse(json.loads(bundle['bundle_json'])['content']['report']['admissible'])
            with patch('capacity.orbital.platform.checkpoint.verify_checkpoint_mission',wraps=verify_checkpoint_mission) as check,patch('capacity.orbital.platform.checkpoint.tools.dispatch',side_effect=AssertionError('verify must not dispatch plan')):
                result=verify(bundle['bundle_json']);self.assertTrue(result['valid']);self.assertFalse(result['admissible']);self.assertEqual(check.call_count,1)
        r=request();r['input']['scenario']['mission']['jobs'][0].update(preprocess_s=0,hybrid_ground_s=0,deadline_s=6.4)
        bundle=export(canonical(r));self.assertTrue(verify(bundle['bundle_json'])['valid'])
        self.assertEqual(json.loads(bundle['bundle_json'])['content']['report']['jobs'][0]['completion_s'],6.4)

    def test_strict_transport_and_limits_before_parse(self):
        result=export(self.inner());env=json.loads(result['bundle_json'])
        for bad in (result['bundle_json']+' ',json.dumps(env)+'\n',result['bundle_json'].replace('13.400146484375','1.3400146484375e1'),'{"a":1,"a":2}\n','{"x":NaN}\n','{}\ud800'):
            if bad==result['bundle_json']:continue
            self.refused(lambda:verify(bad))
        for limit,fn in [(BUNDLE,lambda s:verify(s)),(INNER,lambda s:export(s)),(TOOL,lambda s:dispatch_json(s))]:
            with patch('json.loads',side_effect=AssertionError('over-cap input must not parse')):
                if limit==TOOL:self.assertEqual(fn(' '*(limit+1))['code'],'BUDGET_EXCEEDED')
                else:self.refused(lambda:fn(' '*(limit+1)),'BUDGET_EXCEEDED')
        for raw in ('{"x":'+'9'*769+'}\n','{"x":1e4301}\n'):
            self.refused(lambda:parse(raw,BUNDLE),'BUDGET_EXCEEDED')
        self.refused(lambda:verify('['*10000+']'*10000),'BUDGET_EXCEEDED')
        unknown=self.tool('export',dict(request_json=self.inner()));unknown['input']['path']='unused'
        self.assertEqual(dispatch(unknown)['code'],'INVALID_ARGUMENT')
        self.assertEqual(dispatch(self.tool('verify',dict(bundle_json=result['bundle_json'],expected_sha256=3)))['code'],'INVALID_ARGUMENT')

    def test_large_real_bundle_and_separate_tool_transport(self):
        req=request('onboard');scenario=req['input']['scenario'];scenario['mission']['jobs'][0]['onboard_s']=.34375
        scenario['replay']['origin']['policy'].update(checkpoint_every_work_s=.000244140625,checkpoint_duration_s=.000244140625)
        original=canonical(req);original='\n'*(999_999-len(original.encode()))+original
        result=export(original)
        self.assertGreater(len(result['bundle_json']),9_800_000);self.assertLessEqual(len(result['bundle_json']),BUNDLE)
        transport=wire(self.tool('verify',dict(bundle_json=result['bundle_json'],expected_sha256=result['sha256'])),TOOL)
        self.assertGreater(len(transport),BUNDLE);self.assertLess(len(transport),TOOL)
        checked=dispatch_json(transport);self.assertEqual(checked['status'],'ok');self.assertTrue(checked['result']['valid'])
        # The same individually legal request with more checkpoint rows exceeds
        # the combined bundle cap or the inherited report cap; never truncate.
        scenario['mission']['jobs'][0]['onboard_s']=.375
        self.refused(lambda:export(canonical(req)),'BUDGET_EXCEEDED')
        self.refused(lambda:parse('{"x":"'+'é'*400_000+'"}',1_000_000),'BUDGET_EXCEEDED')

    def test_file_journey_and_hashed_directory_guards(self):
        launcher=Path('capacity/orbital/checkpoint_bundle/cli.py').resolve()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'request.json';src.write_text(self.inner());out=root/'bundle.json';before=src.read_bytes()
            def run(*args):
                p=subprocess.run([sys.executable,str(launcher),*map(str,args)],capture_output=True,text=True,timeout=30)
                return p,json.loads(p.stdout)
            p,e=run('export','--request',src,'--output',out);self.assertEqual(p.returncode,0);self.assertEqual(out.read_text(),e['result']['bundle_json']);original=out.read_bytes()
            p,v=run('verify','--bundle',out,'--expected-sha256',e['result']['sha256']);self.assertEqual(p.returncode,0);self.assertTrue(v['result']['valid'])
            p,v=run('verify','--bundle',out,'--expected-sha256','0'*64);self.assertEqual(p.returncode,2);self.assertEqual(v['status'],'ok');self.assertFalse(v['result']['valid'])
            for dest in (src,out):
                p,v=run('export','--request',src,'--output',dest);self.assertEqual(p.returncode,2);self.assertEqual(v['status'],'refused')
            self.assertEqual(src.read_bytes(),before);self.assertEqual(out.read_bytes(),original)
            for directory in ('capacity/orbital','capacity/orbital/platform/checkpoint','capacity/orbital/checkpoint_bundle','capacity/orbital/network'):
                alias=root/('alias'+str(len(list(root.iterdir()))));alias.symlink_to(Path(directory).resolve(),target_is_directory=True);dest=alias/'never-created.json'
                p,v=run('export','--request',src,'--output',dest);self.assertEqual(p.returncode,2);self.assertEqual(v['code'],'FORBIDDEN_OUTPUT');self.assertFalse(dest.exists())
            missing=root/'missing-parent'/'bundle.json'
            p,v=run('export','--request',src,'--output',missing);self.assertEqual(p.returncode,2);self.assertEqual(v['code'],'IO_ERROR');self.assertFalse(missing.exists())
            missing.parent.mkdir();p,v=run('export','--request',src,'--output',missing);self.assertEqual(p.returncode,0)
            src.write_text('{}');p,v=run('export','--request',src,'--output',root/'bad.json');self.assertEqual(p.returncode,2);self.assertFalse((root/'bad.json').exists())
            src.write_bytes(before);p,v=run('export','--request',src,'--output',root/'recovered.json');self.assertEqual(p.returncode,0)
        self.assertEqual(checkpoint_source(),CHECKPOINT_SOURCE);self.assertEqual(parent_source(),'dc7420c8d4be3466d1036eadf39206567d37d2b0bc11ddd8d9f3c00040e0593e')

    def test_reserved_subtree_identity_and_permitted_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);capacity=root/'capacity'
            shutil.copytree(Path(__file__).resolve().parent.parent,capacity,ignore=shutil.ignore_patterns('__pycache__'))
            own=capacity/'orbital/checkpoint_bundle';(own/'nested').mkdir()
            src=root/'request.json';src.write_text(self.inner());launcher=own/'cli.py'
            targets=[own/'nested/new.json']
            alias=own.with_name(own.name.upper())
            # Exercise a real case alias when the host filesystem supports it.
            if alias.exists() and os.path.samefile(alias,own):targets.extend([alias/'nested/new.json',alias/'not-created/deeper/new.json'])
            for target in targets:
                run=subprocess.run([sys.executable,str(launcher),'export','--request',str(src),'--output',str(target)],capture_output=True,text=True,timeout=30)
                self.assertEqual(run.returncode,2,run.stderr);self.assertEqual(json.loads(run.stdout)['code'],'FORBIDDEN_OUTPUT');self.assertFalse(target.exists())
            allowed=capacity/'orbital/evidence/checkpoint-bundle/fresh-permitted.json'
            run=subprocess.run([sys.executable,str(launcher),'export','--request',str(src),'--output',str(allowed)],capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stderr);self.assertTrue(allowed.exists())
            self.assertTrue(verify(allowed.read_bytes())['valid'])

    def test_guarded_startup_and_source_restore(self):
        with tempfile.TemporaryDirectory() as td:
            capacity=Path(td)/'capacity';shutil.copytree(Path(__file__).resolve().parent.parent,capacity,ignore=shutil.ignore_patterns('__pycache__'))
            launcher=capacity/'orbital/checkpoint_bundle/cli.py';src=Path(td)/'request.json';src.write_text(self.inner())
            for name in ('orbital/checkpoint_bundle/contracts.py','orbital/platform/checkpoint/contracts.py','orbital/platform/mission.py','orbital/platform/checkpoint/source_inventory.json'):
                path=capacity/name;hidden=path.with_suffix('.hidden');path.rename(hidden)
                try:
                    p=subprocess.run([sys.executable,str(launcher),'export','--request',str(src),'--output',str(Path(td)/'no-output.json')],capture_output=True,text=True,timeout=20)
                    self.assertEqual(p.returncode,2);self.assertEqual(json.loads(p.stdout)['code'],'SOURCE_UNAVAILABLE');self.assertFalse((Path(td)/'no-output.json').exists())
                finally:hidden.rename(path)
            p=subprocess.run([sys.executable,str(launcher),'export','--request',str(src),'--output',str(Path(td)/'recovered.json')],capture_output=True,text=True,timeout=20)
            self.assertEqual(p.returncode,0,p.stderr)

    def test_committed_portable_fixture(self):
        root=Path(__file__).parent
        path=root/'evidence/checkpoint-bundle/nominal.json'
        expected=(root/'evidence/checkpoint-bundle/expected-sha256.txt').read_text().strip()
        self.assertTrue(verify(path.read_bytes(),expected)['valid'])
        reproduced=export((root/'examples/checkpoint-bundle-request.json').read_bytes())
        self.assertEqual(reproduced['bundle_json'].encode(),path.read_bytes())
        run=subprocess.run([sys.executable,str(root/'checkpoint_bundle/cli.py'),'verify','--bundle',str(path),'--expected-sha256',expected],capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stderr);self.assertTrue(json.loads(run.stdout)['result']['valid'])

if __name__=='__main__':unittest.main()
