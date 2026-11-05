import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from .bundle import export_bundle,verify_bundle,MAX_BYTES
from .contracts import digest
from .platform.fixtures import demo

class BundleTests(unittest.TestCase):
    def test_roundtrip_immutable_and_infeasible(self):
        for kind in ('nominal','held','battery','network-loss'):
            mission=demo(kind);before=copy.deepcopy(mission);bundle=export_bundle(mission)
            self.assertEqual(mission,before);self.assertTrue(verify_bundle(bundle)['valid'])
            if kind=='held':self.assertEqual(verify_bundle(bundle)['admissible_routes'],[])
    def test_rehashed_tampering(self):
        base=export_bundle(demo())
        for target in ('mission','report','source','coverage','schema'):
            b=copy.deepcopy(base);c=b['content']
            if target=='mission':c['mission']['jobs'][0]['raw_gb']+=1;c['input_sha256']=digest(c['mission'])
            elif target=='report':
                r=c['comparison']['comparisons'][0];r['jobs'][0]['completion_s']=0;r['receipt_id']=digest({k:v for k,v in r.items() if k!='receipt_id'})
            elif target=='source':c['platform_source_sha256']='0'*64
            elif target=='coverage':c['comparison']['comparisons'].pop()
            else:c['schema']='future'
            b['sha256']=digest(c);self.assertFalse(verify_bundle(b)['valid'],target)
        replacement=demo();replacement['jobs'][0]['raw_gb']=2
        other=export_bundle(replacement);self.assertTrue(verify_bundle(other)['valid'])
        self.assertFalse(verify_bundle(other,base['sha256'])['valid'])
    def test_shape_depth_size(self):
        for value in (None,[],{'content':[],'sha256':'bad'},'x'*(MAX_BYTES+1)):
            self.assertFalse(verify_bundle(value)['valid'])
        value=[];child=value
        for _ in range(1000):n=[];child.append(n);child=n
        self.assertFalse(verify_bundle(value)['valid'])
    def test_fresh_process_cli_and_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);mission=root/'mission.json';out=root/'bundle.json'
            mission.write_text(json.dumps(demo()));original=mission.read_bytes()
            def run(*args):return subprocess.run([sys.executable,'-m','capacity.orbital.bundle',*map(str,args)],capture_output=True,text=True,timeout=20)
            self.assertEqual(run('export','--mission',mission,'--output',out).returncode,0)
            saved=out.read_bytes();self.assertEqual(run('verify','--bundle',out).returncode,0)
            self.assertEqual(run('export','--mission',mission,'--output',out).returncode,2)
            self.assertEqual(out.read_bytes(),saved);self.assertEqual(mission.read_bytes(),original)
            self.assertEqual(run('export','--mission',mission,'--output',mission).returncode,2)
            for bad in ('{','{"a":1,"a":2}', ' '* (MAX_BYTES+1)):
                path=root/'bad.json';path.write_text(bad)
                self.assertEqual(run('verify','--bundle',path).returncode,2)
if __name__=='__main__':unittest.main()
