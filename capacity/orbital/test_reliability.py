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
if __name__=='__main__':unittest.main()
