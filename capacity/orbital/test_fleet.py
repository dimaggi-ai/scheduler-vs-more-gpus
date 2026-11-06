import copy,json,math,subprocess,sys,tempfile,unittest
from pathlib import Path
from .fleet import evaluate,compare,project_economics
from .fleet.api import dispatch
from .fleet.fixtures import demo,request
from .diligence.fixtures import lifecycle_example
from .diligence.lifecycle import lifecycle_cost
class FleetTests(unittest.TestCase):
    def test_zero_and_exponential_hand_oracle(self):
        s=demo();s['cohorts']=s['cohorts'][:1];c=s['cohorts'][0];c.update(count=10,capacity_kw=2,utilization=1,availability=1,hazard_per_year=0)
        self.assertEqual(evaluate(s)['total_useful_kw_years'],60)
        c['hazard_per_year']=math.log(2);r=evaluate(s)
        self.assertAlmostEqual(r['annual'][0]['expected_surviving_nodes'],5)
        self.assertAlmostEqual(r['annual'][0]['expected_useful_kw_years'],10/math.log(2))
        self.assertAlmostEqual(r['total_useful_kw_years'],20*(1-.125)/math.log(2))
    def test_commission_retirement_conservation_and_projection(self):
        s=demo();before=copy.deepcopy(s);r=evaluate(s);self.assertEqual(s,before)
        replacement=[x for x in r['cohort_periods'] if x['cohort_id']=='replacement'];self.assertEqual(replacement[0]['expected_node_years'],0)
        self.assertAlmostEqual(replacement[1]['expected_node_years'],3*(1-math.exp(-.05))/.1)
        for year in r['annual']:
            self.assertAlmostEqual(sum(year[k] for k in ('expected_surviving_nodes','expected_failed_nodes','expected_retired_nodes','uncommissioned_nodes')),13)
        template=lifecycle_example();template.update(horizon_years=3,cohorts=[])
        p=project_economics(s,template);self.assertEqual(template['cohorts'],[])
        for a,b in zip(r['annual'],p['economics']['annual_output']):self.assertAlmostEqual(a['expected_useful_kw_years'],b['useful_kw_years'])
        self.assertEqual(p['projected_lifecycle']['cash_flows'],template['cash_flows'])
        s['cohorts'][1]['delay_years']=3
        self.assertEqual([x for x in evaluate(s)['cohort_periods'] if x['cohort_id']=='replacement'][-1]['expected_surviving_nodes'],0)
    def test_fixed_comparison_hazard_delay_and_determinism(self):
        a=demo();b=copy.deepcopy(a)
        for c in b['cohorts']:c['hazard_per_year']+=.2;c['delay_years']+=.25
        r=compare(a,b);self.assertLess(r['useful_exposure_delta_kw_years'],0);self.assertFalse(r['promoted']);self.assertEqual(r,compare(a,b))
        b['demand_kw'][0]+=1
        self.assertEqual(dispatch(dict(request(),tool='compare',input=dict(baseline=a,candidate=b)))['code'],'BASELINE_MISMATCH')
    def test_refusal_recovery_and_bounds(self):
        for bad in (-1,float('inf'),True,10**400):
            s=demo();s['cohorts'][0]['hazard_per_year']=bad
            self.assertEqual(dispatch(request(s))['status'],'refused')
        self.assertEqual(dispatch(request())['status'],'completed')
        s=demo();s['cohorts']*=101;self.assertEqual(dispatch(request(s))['code'],'BUDGET_EXCEEDED')
        s=demo();s['horizon_years']=100;s['demand_kw']=[1]*100;s['cohorts']=[dict(s['cohorts'][0],id=str(i),retirement_year=100) for i in range(3)]
        t=lifecycle_example();t.update(horizon_years=100,cohorts=[])
        self.assertEqual(dispatch(dict(request(),tool='economics',input=dict(scenario=s,template=t)))['code'],'BUDGET_EXCEEDED')
    def test_zero_hazard_matches_existing_lifecycle_and_fractional_buckets(self):
        s=demo();s['cohorts'][0].update(planned_commission_year=.25,delay_years=.25,retirement_year=2.25,hazard_per_year=0)
        s['cohorts']=s['cohorts'][:1];c=s['cohorts'][0]
        t=lifecycle_example();t.update(horizon_years=3,cohorts=[dict(id=c['id'],count=c['count'],commission_year=.5,retirement_year=2.25,capacity_kw=c['capacity_kw'],utilization=c['utilization'],availability=c['availability'])])
        fleet=evaluate(s);old=lifecycle_cost(t)
        self.assertEqual([x['expected_useful_kw_years'] for x in fleet['annual']],[x['useful_kw_years'] for x in old['annual_output']])
        c['hazard_per_year']=math.log(2)
        expected=[10*(1-2**(-.5))/math.log(2),10*(2**(-.5)-2**(-1.5))/math.log(2),10*(2**(-1.5)-2**(-1.75))/math.log(2)]
        for row,oracle in zip(evaluate(s)['cohort_periods'],expected):self.assertAlmostEqual(row['expected_node_years'],oracle)
    def test_monotonicity_separate_hazard_and_delay(self):
        base=demo();reference=evaluate(base)['total_useful_kw_years']
        for key,extra in (('delay_years',.5),('hazard_per_year',.2)):
            altered=copy.deepcopy(base)
            for c in altered['cohorts']:c[key]+=extra
            self.assertLessEqual(evaluate(altered)['total_useful_kw_years'],reference)
        s=demo();s['cohorts'][0].update(utilization=1e-300,availability=1e-300)
        self.assertEqual(dispatch(request(s))['code'],'ARITHMETIC_RESOLUTION')

    def test_nearzero_hazard_partial_interval_and_projection(self):
        from .fleet import integral
        from decimal import Decimal,localcontext
        for rate in [0,5e-324,1e-323,1e-320,1e-310,1e-200,1e-100,1e-20,1e-12,1e-6,.1,1,10]:
            with localcontext() as context:
                context.prec=380
                r=Decimal.from_float(rate);a=Decimal('.25');b=Decimal('1');start=Decimal('0')
                oracle=b-a if not r else ((-r*(a-start)).exp()-(-r*(b-start)).exp())/r
            actual=integral({'hazard_per_year':rate},.25,1,0)
            self.assertTrue(math.isclose(actual,float(oracle),rel_tol=2e-14,abs_tol=1e-15),(rate,actual,float(oracle)))
            self.assertLessEqual(actual,.75)
            s=demo();s['cohorts']=s['cohorts'][:1];s['cohorts'][0].update(planned_commission_year=.25,retirement_year=2.5,hazard_per_year=rate)
            template=lifecycle_example();template.update(horizon_years=3,cohorts=[])
            result=project_economics(s,template)
            for fleet,econ in zip(result['fleet']['annual'],result['economics']['annual_output']):
                self.assertTrue(math.isclose(fleet['expected_useful_kw_years'],econ['useful_kw_years'],rel_tol=2e-14,abs_tol=1e-15))
        self.assertEqual(integral({'hazard_per_year':5e-324},.25,1,.25),.75)

    def test_pinned_baseline_numeric_equivalence_and_receipts(self):
        from .contracts import digest
        a=demo();b=copy.deepcopy(a);b['cohorts'][0]['capacity_kw']=2.0;b['demand_kw'][0]=16.0;b['cohorts'][0]['retirement_year']=3.0
        result=compare(a,b,digest(a));self.assertEqual(result['baseline_binding'],'baseline matched supplied digest')
        self.assertEqual(result['receipt_id'],digest({k:v for k,v in result.items() if k!='receipt_id'}))
        self.assertEqual(result['input_sha256'],digest(dict(baseline=a,candidate=b,expected_baseline_sha256=digest(a))))
        b['cohorts'][0]['planned_commission_year']=-0.0
        self.assertEqual(compare(a,b)['candidate']['total_useful_kw_years'],result['candidate']['total_useful_kw_years'])
        null=dispatch(dict(request(),tool='compare',input=dict(baseline=a,candidate=b,expected_baseline_sha256=None)))
        self.assertEqual(null['code'],'BASELINE_BINDING')
        drift=copy.deepcopy(a);drift['demand_kw'][0]=100
        response=dispatch(dict(request(),tool='compare',input=dict(baseline=drift,candidate=drift,expected_baseline_sha256=digest(a))))
        self.assertEqual(response['code'],'BASELINE_BINDING');self.assertEqual(response['id'],'synthetic-evaluation');self.assertIsNotNone(response['input_sha256'])
        self.assertEqual(compare(drift,drift)['baseline_binding'],'unbound caller-supplied pair')
    def test_economics_complete_binding_mapping_and_assumptions(self):
        from .contracts import digest
        s=demo();t=lifecycle_example();t.update(horizon_years=3,cohorts=[])
        result=project_economics(s,t)
        self.assertEqual(result['input_sha256'],digest(dict(scenario=s,template=t)))
        self.assertEqual(result['receipt_id'],digest({k:v for k,v in result.items() if k!='receipt_id'}))
        self.assertEqual(len(result['projection_mapping']),len(result['projected_lifecycle']['cohorts']))
        active=[r for r in result['fleet']['cohort_periods'] if r['active_years']>0]
        counts={c['id']:c['count'] for c in s['cohorts']}
        for mapping,row,projected in zip(result['projection_mapping'],active,result['projected_lifecycle']['cohorts']):
            self.assertEqual(mapping,dict(projection_id=projected['id'],source_cohort_id=row['cohort_id'],year_end=row['year_end'],mean_survival=row['expected_node_years']/counts[row['cohort_id']]/row['active_years'],active_years=row['active_years']))
        self.assertEqual(result['scenario_provenance'],s['provenance']);self.assertEqual(result['template_provenance'],t['provenance'])
        self.assertFalse(any('not inferred survival probabilities' in x for x in result['economics']['assumptions']))
        t['cash_flows'][0]['amount']+=1
        other=project_economics(s,t);self.assertNotEqual(result['input_sha256'],other['input_sha256']);self.assertNotEqual(result['receipt_id'],other['receipt_id'])
        from unittest.mock import patch
        fake=evaluate(s);fake['cohort_periods'][0]['expected_node_years']*=2
        with patch('capacity.orbital.fleet.evaluate',return_value=fake):
            with self.assertRaisesRegex(ValueError,'beyond roundoff'):project_economics(s,t)

    def test_dispatch_hashes_underflow_and_roundoff_clamp(self):
        from .contracts import digest
        from .fleet import source_digest,integral
        from unittest.mock import patch
        req=request();done=dispatch(req)
        self.assertEqual(done['input_sha256'],digest(req));self.assertEqual(done['source_sha256'],source_digest())
        req['input']['cohorts'][0]['hazard_per_year']=-1
        refused=dispatch(req)
        self.assertEqual(refused['source_sha256'],source_digest());self.assertEqual(refused['input_sha256'],digest(req))
        with self.assertRaisesRegex(ValueError,'below numeric resolution'):integral({'hazard_per_year':100},99,100,0)
        s=demo();s['cohorts']=s['cohorts'][:1];s['cohorts'][0].update(hazard_per_year=0,availability=1)
        t=lifecycle_example();t.update(horizon_years=3,cohorts=[])
        fake=evaluate(s);fake['cohort_periods'][0]['expected_node_years']*=1+1e-13
        with patch('capacity.orbital.fleet.evaluate',return_value=fake):
            result=project_economics(s,t)
        self.assertEqual(result['projected_lifecycle']['cohorts'][0]['availability'],1)

    def test_real_cli_success_refusal_recovery_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.json';out=Path(d)/'out.json'
            def run():return subprocess.run([sys.executable,'-m','capacity.orbital.fleet','--request',str(p),'--output',str(out)],capture_output=True,text=True,timeout=10)
            bad=request();bad['input']['cohorts'][0]['delay_years']=-1;p.write_text(json.dumps(bad));self.assertEqual(run().returncode,2)
            out.unlink();p.write_text(json.dumps(request()));self.assertEqual(run().returncode,0);saved=out.read_bytes();self.assertEqual(run().returncode,2);self.assertEqual(out.read_bytes(),saved)
if __name__=='__main__':unittest.main()
