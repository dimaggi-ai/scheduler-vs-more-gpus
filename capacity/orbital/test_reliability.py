import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from decimal import Decimal as D
from fractions import Fraction as F
from unittest.mock import patch
from .reliability import evaluate_checkpoint_policy as evaluate,compare_checkpoint_policies as compare
from .reliability.api import dispatch
from .reliability.contracts import parse,number,Refuse,encoded,validate,rational
from .reliability.fixtures import scenario,request
from .contracts import digest

def q(value):return F(int(value['numerator']),int(value['denominator']))

class CheckpointTests(unittest.TestCase):
    def check(self,s,stop,durable,volatile,lost,durations,energy,status):
        original=copy.deepcopy(s);r=evaluate(s);self.assertEqual(s,original)
        self.assertEqual(r['status'],status)
        for key,value in dict(stop_s=stop,durable_work_s=durable,volatile_work_s=volatile,lost_work_s=lost,total_energy_kwh=energy).items():self.assertEqual(q(r[key]),value,key)
        self.assertEqual({k:q(v) for k,v in r['durations_s'].items()},dict(zip(('productive','checkpoint','restart','down'),durations)))
        self.assertEqual(q(r['productive_work_s']),lost+durable+volatile)
        last=F(s['release_s']);total=F(0)
        for row in r['trace']:
            self.assertEqual(q(row['start_s']),last);self.assertGreater(q(row['duration_s']),0)
            self.assertEqual(q(row['end_s'])-last,q(row['duration_s']));last=q(row['end_s']);total+=q(row['energy_kwh'])
        self.assertEqual(last,stop);self.assertEqual(total,energy)
        self.assertEqual(r['trace_sha256'],digest(r['trace']));self.assertEqual(r['receipt_id'],digest({k:v for k,v in r.items() if k!='receipt_id'}))
        self.assertEqual(r,evaluate(s));return r
    def test_five_original_hand_cases(self):
        s=scenario();self.check(s,8,6,0,0,[6,2,0,0],F(8,3600),'completed')
        s['interruptions']=[dict(start_s=5,end_s=7)];self.check(s,17,6,0,4,[10,3,2,2],F(15,3600),'completed')
        s['interruptions']=[dict(start_s=6,end_s=8)];self.check(s,12,6,0,0,[6,2,2,2],F(10,3600),'completed')
        s=scenario();s.update(work_s=4,deadline_s=12,interruptions=[dict(start_s=2,end_s=4),dict(start_s=5,end_s=6)]);s['policy'].update(checkpoint_every_work_s=None,restart_duration_s=3)
        self.check(s,12,0,3,2,[5,0,4,3],F(9,3600),'deadline_exceeded')
        s['deadline_s']=13;self.check(s,13,4,0,2,[6,0,4,3],F(10,3600),'completed')
        s=scenario();s.update(work_s=10,interruptions=[dict(start_s=D('8.5'),end_s=D('9.5'))]);s['policy'].update(checkpoint_every_work_s=3,checkpoint_duration_s=1,restart_duration_s=1)
        self.check(s,F(31,2),10,0,F(1,2),[F(21,2),3,1,1],F(29,7200),'completed')
    def test_five_additional_power_deadline_oracles(self):
        s=scenario();s.update(work_s=9,deadline_s=6);self.check(s,6,4,0,0,[4,2,0,0],F(6,3600),'deadline_exceeded')
        s['deadline_s']=5;self.check(s,5,0,4,0,[4,1,0,0],F(5,3600),'deadline_exceeded')
        s['policy']['checkpoint_every_work_s']=None;s['interruptions']=[dict(start_s=5,end_s=6)]
        self.check(s,5,0,0,5,[5,0,0,0],F(5,3600),'deadline_exceeded')
        s=scenario();s['interruptions']=[dict(start_s=5,end_s=7)];s['power_kw'].update(checkpoint=2,restart=3,down=D('.5'))
        self.check(s,17,6,0,4,[10,3,2,2],F(23,3600),'completed')
        s.update(release_s=3,work_s=2,interruptions=[dict(start_s=1,end_s=5)]);s['policy']['checkpoint_every_work_s']=None
        self.check(s,9,2,0,0,[2,0,2,2],F(9,3600),'completed')
    def test_decimal_tie_and_pin(self):
        self.assertEqual(evaluate(scenario())['input_sha256'],'4573714e8a4c374d5e96134129ebc8c49a935ec56069e96e37fb67fd0b618824')
        s=scenario();s.update(work_s=1,interruptions=[dict(start_s=D('.3'),end_s=D('.4'))]);s['policy'].update(checkpoint_every_work_s=D('.1'),checkpoint_duration_s=D('.2'),restart_duration_s=1)
        self.check(s,D('3.9'),1,0,0,[1,D('1.8'),1,D('.1')],F(19,18000),'completed')
        a=dispatch(request());b=dispatch(dict(request(),id='r2'));self.assertEqual(a['result']['input_sha256'],b['result']['input_sha256']);self.assertNotEqual(a['input_sha256'],b['input_sha256'])
    def test_boundary_ties_and_normalization(self):
        s=scenario();s.update(work_s=2,deadline_s=2,interruptions=[dict(start_s=2,end_s=3)]);self.assertEqual(evaluate(s)['status'],'completed')
        s=scenario();s['release_s']=s['deadline_s'];r=dispatch(request(s));self.assertEqual(r['status'],'ok');self.assertEqual(r['result']['status'],'deadline_exceeded');self.assertEqual(r['result']['trace'],[])
        a=scenario();a['interruptions']=[dict(start_s=2,end_s=3),dict(start_s=3,end_s=4)];b=copy.deepcopy(a);b['interruptions']=[dict(start_s=2,end_s=4)]
        self.assertEqual(evaluate(a),evaluate(b))
        b['release_s']=-0.0;self.assertEqual(evaluate(a)['input_sha256'],evaluate(b)['input_sha256'])
        s=scenario();s.update(release_s=4,interruptions=[dict(start_s=2,end_s=4)]);self.assertEqual(q(evaluate(s)['durations_s']['restart']),0)
        s=scenario();s.update(interruptions=[dict(start_s=0,end_s=1),dict(start_s=3,end_s=4)]);self.assertEqual(q(evaluate(s)['durations_s']['restart']),4)
    def test_compare_four_outcomes_and_hardware_pin(self):
        for deadline,base_interval,candidate_interval,outcome in [(30,4,None,'both_completed'),(6,None,4,'regression'),(6,4,None,'candidate_completed_baseline_missed'),(3,4,None,'both_missed')]:
            a=scenario();a['deadline_s']=deadline;a['policy']['checkpoint_every_work_s']=base_interval;b=copy.deepcopy(a);b['policy']['checkpoint_every_work_s']=candidate_interval
            r=compare(a,b,evaluate(a)['input_sha256']);self.assertEqual(r['outcome'],outcome);self.assertNotIn('trace',r['baseline']);self.assertNotIn('trace',r['candidate'])
            self.assertEqual(r['deltas']['completion_s'] is None,outcome!='both_completed');self.assertFalse(r['promoted'])
        a=scenario();b=copy.deepcopy(a);b['policy']['restart_duration_s']=1
        with self.assertRaisesRegex(Refuse,'only checkpoint'):compare(a,b,evaluate(a)['input_sha256'])
        with self.assertRaisesRegex(Refuse,'baseline differs'):compare(a,a,'0'*64)
        r=dispatch(dict(request(),tool='compare',input=dict(baseline=a,candidate=b,expected_baseline_sha256=None)));self.assertEqual(r['code'],'BASELINE_BINDING')
    def test_lexical_and_parser_boundaries(self):
        for token in ('0.1','-0','-0.0','1e-12','0.000000000001','31557600','1e7','1e-05'):
            self.assertIsInstance(number(parse(token)),F)
        for token in ('1.5e-12','1e13','0e999','1e+012','0.30000000000000004','5e-324','1.0000000000000','10000000000000e-13'):
            with self.assertRaises(Refuse) as e:number(parse(token))
            self.assertEqual(e.exception.code,'BUDGET_EXCEEDED',token)
        for token in ('31557601','1e12'):
            with self.assertRaises(Refuse) as e:number(parse(token))
            self.assertEqual(e.exception.code,'INVALID_ARGUMENT')
        for raw in ('01','.5','5.','+1','NaN','-Infinity','{"x":1,"x":2}','"\\ud800"'):
            with self.assertRaises(Refuse) as e:parse(raw)
            self.assertEqual(e.exception.code,'INVALID_ARGUMENT')
        for raw in (json.dumps(request()).encode('utf-16'),json.dumps(request()).encode('utf-32')):
            with self.assertRaises(Refuse) as e:parse(raw)
            self.assertEqual(e.exception.code,'INVALID_ARGUMENT')
        for raw in ('['*100000+']'*100000,' '*1000001):
            with self.assertRaises(Refuse) as e:parse(raw)
            self.assertEqual(e.exception.code,'BUDGET_EXCEEDED')
        for value in ('1',True,float('inf')):
            with self.assertRaises(Refuse):number(value)
        with self.assertRaises(Refuse):number(D('1e999999'))
        direct=request();direct['input']['id']='\ud800'
        self.assertEqual(dispatch(direct)['code'],'INVALID_ARGUMENT')
        with self.assertRaises(Refuse):number(.30000000000000004)
        with self.assertRaises(Refuse):rational(F(10**256))
    def test_budget_refusal_recovery_and_source(self):
        s=scenario();s['policy']['checkpoint_every_work_s']=D('.000000000001')
        with patch('capacity.orbital.reliability.MAX_INTERVALS',10):self.assertEqual(dispatch(request(s))['code'],'BUDGET_EXCEEDED')
        self.assertEqual(dispatch(request())['status'],'ok')
        with patch('capacity.orbital.reliability.api.source_digest',side_effect=OSError):self.assertEqual(dispatch(request())['code'],'SOURCE_UNAVAILABLE')
        s=scenario();s['work_s']=-1;r=dispatch(request(s));self.assertEqual(r['id'],'r1');self.assertEqual(r['code'],'INVALID_ARGUMENT')
        with patch('capacity.orbital.reliability.contracts.MAX_OUTPUT',50):self.assertEqual(dispatch(request())['code'],'BUDGET_EXCEEDED')
    def test_actual_trace_cap_summary_comparison(self):
        s=scenario();s.update(work_s=50,horizon_s=100,deadline_s=100)
        s['policy'].update(checkpoint_every_work_s=D('.01'),checkpoint_duration_s=D('.001'))
        r=evaluate(s);self.assertEqual(len(r['trace']),9999)
        c=compare(s,s,r['input_sha256']);self.assertNotIn('trace',c['baseline']);self.assertLess(len(json.dumps(c)),10000)
        limit=copy.deepcopy(s);limit['interruptions']=[dict(start_s=D('54.995'),end_s=55)];limit['deadline_s']=D('54.996')
        self.assertEqual(len(evaluate(limit)['trace']),10000)
        s['work_s']=D('50.001')
        self.assertEqual(dispatch(request(s))['code'],'BUDGET_EXCEEDED')

    def test_cli_fresh_process_refusal_recovery_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'input.json';out=Path(temp)/'out.json'
            def run():return subprocess.run([sys.executable,'-m','capacity.orbital.reliability','--request',str(p),'--output',str(out)],capture_output=True,text=True,timeout=15)
            bad=request();bad['input']['work_s']=-1;p.write_text(json.dumps(bad));self.assertEqual(run().returncode,2)
            out.unlink();p.write_text(json.dumps(request()));self.assertEqual(run().returncode,0);saved=out.read_bytes();self.assertEqual(run().returncode,2);self.assertEqual(out.read_bytes(),saved)
            for malformed in ('{','{"id":1,"id":2}','NaN'):
                p.write_text(malformed);reply=run();self.assertEqual(reply.returncode,2)
                result=json.loads(reply.stdout);self.assertEqual(result['schema'],'capacity-orbital/checkpoint-tool-result-v1');self.assertEqual(result['code'],'INVALID_ARGUMENT');self.assertIsNone(result['input_sha256'])
    def test_fixed_fields_allowed_fields_and_complete_comparison_contract(self):
        a=scenario();pin=evaluate(a)['input_sha256']
        changes=[('power_kw','productive',2),('work_s',None,7),('deadline_s',None,29),('release_s',None,1),('horizon_s',None,31),('interruptions',None,[dict(start_s=1,end_s=2)]),('policy','checkpoint_duration_s',1),('policy','restart_duration_s',1)]
        for group,key,value in changes:
            with self.subTest(fixed=group,key=key):
                b=copy.deepcopy(a)
                if key:b[group][key]=value
                else:b[group]=value
                with self.assertRaises(Refuse) as caught:compare(a,b,pin)
                self.assertEqual(caught.exception.code,'BASELINE_MISMATCH')
        b=copy.deepcopy(a);b['schema']='wrong'
        with self.assertRaises(Refuse) as caught:compare(a,b,pin)
        self.assertEqual(caught.exception.code,'UNSUPPORTED_SCHEMA')
        for group,key,value in [('id',None,'candidate'),('provenance','source','distinct synthetic source'),('policy','version','candidate-v2')]:
            b=copy.deepcopy(a)
            if key:b[group][key]=value
            else:b[group]=value
            result=compare(a,b,pin)
            self.assertEqual(result['candidate']['scenario_id'],b['id']);self.assertEqual(result['candidate']['provenance'],b['provenance']);self.assertEqual(result['candidate']['policy_version'],b['policy']['version'])
        for deadline,expected in [(30,dict(stop_s=-2,total_energy_kwh=F(-2,3600),lost_work_s=0,durable_work_s=0,completion_s=-2)),(5,dict(stop_s=0,total_energy_kwh=0,lost_work_s=0,durable_work_s=0,completion_s=None))]:
            a=scenario();a['deadline_s']=deadline;b=copy.deepcopy(a);b['policy'].update(checkpoint_every_work_s=None,version='candidate-v2');pin=evaluate(a)['input_sha256']
            result=compare(a,b,pin)
            self.assertEqual({k:q(v) if v is not None else None for k,v in result['deltas'].items()},expected)
            self.assertEqual(result['input_sha256'],digest(dict(baseline=encoded(validate(a)),candidate=encoded(validate(b)),expected_baseline_sha256=pin)))
            self.assertEqual(result['evidence_scope'],'one declared timeline');self.assertEqual(result['recommendation'],'diagnostic only; held-out evaluation and independent acceptance required');self.assertEqual(result['baseline_binding'],'baseline matched supplied digest')
            self.assertFalse(result['execution_performed']);self.assertFalse(result['promoted'])
            for report in (result['baseline'],result['candidate']):
                self.assertEqual(report['classification'],'deterministic synthetic replay; not observed telemetry');self.assertFalse(report['promoted']);self.assertFalse(report['execution_performed'])

    def test_trace_rows_vector_and_source_graph(self):
        from .reliability import source_digest
        import hashlib
        result=evaluate(scenario());self.assertEqual(result['trace_sha256'],'ffab3991857f8007188464947085e2ac786bcec4e37a8a76ee8952f789379714')
        def progress(d,v):return dict(durable_work_s=F(d),volatile_work_s=F(v),lost_work_s=F(0))
        rows=[]
        for state,start,end,before,after,reasons in [('productive',0,4,progress(0,0),progress(0,4),['checkpoint_started']),('checkpoint',4,6,progress(0,4),progress(4,0),['checkpoint_committed']),('productive',6,8,progress(4,0),progress(6,0),['job_completed'])]:
            rows.append(dict(state=state,start_s=F(start),end_s=F(end),duration_s=F(end-start),energy_kwh=F(end-start,3600),progress_before=before,progress_after=after,reasons=reasons))
        self.assertEqual(result['trace'],encoded(rows))
        root=Path(__file__).parent
        files=[root/'reliability'/name for name in ('__init__.py','__main__.py','api.py','contracts.py','fixtures.py')]+[root/'contracts.py',root/'output.py',root/'__init__.py',root.parent/'__init__.py']
        expected=digest({str(p.relative_to(root.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)})
        self.assertEqual(source_digest(),expected);self.assertEqual(result['source_sha256'],expected);self.assertEqual(dispatch(request())['source_sha256'],expected)
        original=Path.read_bytes
        for target in (root/'contracts.py',root/'output.py'):
            with patch.object(Path,'read_bytes',lambda p:original(p)+(b'\n# test source binding' if p==target else b'')):
                self.assertNotEqual(source_digest(),expected)

    def test_validator_cases_and_exact_limit_pairs(self):
        from .reliability.contracts import bounded,Lexeme
        bads=[]
        for intervals in ([dict(start_s=1,end_s=3),dict(start_s=2,end_s=4)],[dict(start_s=1,end_s=31)],[dict(start_s=1,end_s=1)],{}):
            s=scenario();s['interruptions']=intervals;bads.append(s)
        for key,value in [('release_s',31),('deadline_s',31),('horizon_s',5),('work_s',31),('work_s',0)]:
            s=scenario();s[key]=value;bads.append(s)
        for key in ('checkpoint_duration_s','restart_duration_s'):
            s=scenario();s['policy'][key]=0;bads.append(s)
        s=scenario();s['provenance']['kind']='measured';bads.append(s)
        for s in bads:self.assertEqual(dispatch(request(s))['code'],'INVALID_ARGUMENT')
        self.assertEqual(dispatch(dict(request(),tool='missing'))['code'],'UNKNOWN_TOOL')
        self.assertEqual(dispatch(dict(request(),schema='wrong'))['code'],'UNSUPPORTED_SCHEMA')
        for n,accepted in [(128,True),(129,False)]:
            for field in ('request','scenario'):
                req=request()
                if field=='request':req['id']='a'*n
                else:req['input']['id']='a'*n
                self.assertEqual(dispatch(req)['status']=='ok',accepted)
        for n,accepted in [(256,True),(257,False)]:
            s=scenario();s['provenance']['source']='a'*n;self.assertEqual(dispatch(request(s))['status']=='ok',accepted)
        for power,accepted in [(1_000_000_000,True),(1_000_000_001,False)]:
            s=scenario();s['power_kw']['down']=power;self.assertEqual(dispatch(request(s))['status']=='ok',accepted)
        for count,accepted in [(1000,True),(1001,False)]:
            s=scenario();s.update(horizon_s=3000,interruptions=[dict(start_s=2*i,end_s=2*i+1) for i in range(count)])
            if accepted:validate(s)
            else:
                with self.assertRaises(Refuse) as caught:validate(s)
                self.assertEqual(caught.exception.code,'BUDGET_EXCEEDED')
        for depth in (32,33):
            nested=0
            for _ in range(depth):nested=[nested]
            if depth==32:bounded(nested)
            else:
                with self.assertRaises(Refuse):bounded(nested)
        bounded([0]*49999)
        with self.assertRaises(Refuse):bounded([0]*50000)
        self.assertEqual(number(Lexeme('0'*1+'.'+'0'*12)),0)
        for token in ('0.'+'0'*47,'1'*25):
            with self.assertRaises(Refuse) as caught:number(Lexeme(token))
            self.assertEqual(caught.exception.code,'BUDGET_EXCEEDED')
        with self.assertRaises(Refuse):rational(F(10**5000))

    def test_comparison_intermediate_budget_side(self):
        def too_big(s):raise Refuse('BUDGET_EXCEEDED','output byte budget')
        s=scenario();pin=evaluate(s)['input_sha256']
        with patch('capacity.orbital.reliability._evaluate',side_effect=too_big):
            with self.assertRaisesRegex(Refuse,'baseline full evaluation/trace budget'):compare(s,s,pin)
        with patch('capacity.orbital.reliability._evaluate',side_effect=[evaluate(s),Refuse('BUDGET_EXCEEDED','output byte budget')]):
            with self.assertRaisesRegex(Refuse,'candidate full evaluation/trace budget'):compare(s,s,pin)

    def test_cli_identity_channels_and_programmer_error(self):
        from .reliability.__main__ import main
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'input.json';out=Path(temp)/'out.json'
            def run(output=None):
                cmd=[sys.executable,'-m','capacity.orbital.reliability','--request',str(p)]
                if output is not None:cmd+=['--output',str(output)]
                return subprocess.run(cmd,capture_output=True,text=True,timeout=10)
            s=scenario();s['deadline_s']=5;p.write_text(json.dumps(request(s)))
            r=run();self.assertEqual(r.returncode,0);self.assertEqual(json.loads(r.stdout)['result']['status'],'deadline_exceeded')
            r=run(out);self.assertEqual(r.returncode,0);self.assertEqual(r.stdout,'')
            r=run(out);failure=json.loads(r.stdout);self.assertEqual(failure['id'],'r1')
            saved=json.loads(out.read_text());self.assertEqual(failure['input_sha256'],saved['input_sha256']);self.assertEqual(failure['source_sha256'],saved['source_sha256'])
            before=p.read_bytes();r=run(p);self.assertEqual(r.returncode,2);self.assertEqual(p.read_bytes(),before)
            req=request();v=0
            for _ in range(40):v=[v]
            req['input']['extra']=v;p.write_text(json.dumps(req));r=run();self.assertEqual(json.loads(r.stdout)['id'],'r1');self.assertEqual(json.loads(r.stdout)['code'],'BUDGET_EXCEEDED')
            req=request();req['input']['extra']=[0]*60000;p.write_text(json.dumps(req));r=run();self.assertEqual(json.loads(r.stdout)['id'],'r1')
            p.write_text(json.dumps(request()))
            with patch('capacity.orbital.reliability.__main__.dispatch',side_effect=ValueError('programmer defect')):
                with self.assertRaisesRegex(ValueError,'programmer defect'):main(['--request',str(p)])
            p.write_bytes(b' '*999999+b'0');r=run();self.assertEqual(json.loads(r.stdout)['code'],'INVALID_ARGUMENT')
            p.write_bytes(b' '*1000000+b'0');r=run();self.assertEqual(json.loads(r.stdout)['code'],'BUDGET_EXCEEDED')

if __name__=='__main__':unittest.main()
