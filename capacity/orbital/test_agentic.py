"""Agent-only journeys and adversarial fixed-suite evaluation contracts."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .adapters import synthetic
from .contracts import digest
from .agentic import REQUEST_SCHEMA
from .agentic.contracts import semantic_digest, SUITE_SCHEMA
from .agentic.dispatcher import Dispatcher, manifest, source_digest, source_manifest


def request(tool, args, ident='r1'):
    return dict(schema=REQUEST_SCHEMA, id=ident, tool=tool, arguments=args)


def scenario(index=0, **job_changes):
    s = synthetic('continuous', 1)
    s['jobs'][0]['release_s'] = index  # meaningful temporal change avoids duplicate content
    s['jobs'][0].update(job_changes)
    return s


def suite(train=None, heldout=None):
    return dict(schema=SUITE_SCHEMA, objective='failures_then_cost', cost_tolerance_usd=1e-9,
                train=[dict(id='train1', scenario=train or scenario())],
                heldout=[dict(id='heldout1', scenario=heldout or scenario(1))])


def evaluation(s=None, baseline='ground', candidates=None):
    return request('evaluate', dict(suite=s or suite(), baseline=baseline,
                                   candidates=candidates or ['onboard', 'hybrid']))


class ToolsTest(unittest.TestCase):
    def test_agent_no_ui_journey_and_hand_values(self):
        d = Dispatcher()
        r = d.dispatch(request('plan', dict(scenario=scenario(), route='ground')))
        self.assertEqual(r['status'], 'proposed')
        row = r['result']['jobs'][0]
        self.assertEqual(row['completion_s'], 100)
        self.assertEqual(row['downlink_gb'], 10)
        self.assertAlmostEqual(row['energy_kwh'], 20/3600)
        self.assertAlmostEqual(row['cost_usd'], 2 + 20/3600*2.2)
        r = d.dispatch(request('compare', dict(scenario=scenario()), 'r2'))
        self.assertEqual([x['jobs'][0]['completion_s'] for x in r['result']['comparisons']], [100, 30.8, 28])
        self.assertFalse(r['execution_performed'])
        self.assertEqual(r['authority_disposition'], 'planning_only')
        self.assertEqual(r['source_sha256'], source_digest())
        self.assertEqual(r['outcome_sha256'], digest({k:v for k,v in r.items() if k!='outcome_sha256'}))

    def test_idempotency_conflict_and_result_isolation(self):
        d=Dispatcher(); req=request('compare', dict(scenario=scenario()))
        r=d.dispatch(req); same=d.dispatch(deepcopy(req)); self.assertEqual(r,same)
        r['result']['name']='tampered'; self.assertEqual(d.dispatch(req),same)
        changed=deepcopy(req); changed['arguments']['scenario']['name']='changed'
        self.assertEqual(d.dispatch(changed)['code'],'REQUEST_ID_CONFLICT')
        self.assertEqual(d.dispatch(req),same)

    def test_immutability(self):
        req=evaluation(); before=deepcopy(req); Dispatcher().dispatch(req); self.assertEqual(req,before)

    def test_invalid_then_corrected_retry(self):
        d=Dispatcher(); req=request('plan',dict(scenario=scenario(),route='python:exec'))
        self.assertEqual(d.dispatch(req)['code'],'INVALID_ARGUMENT')
        req['arguments']['route']='ground'
        self.assertEqual(d.dispatch(req)['code'],'REQUEST_ID_CONFLICT')
        req['id']='corrected'
        self.assertEqual(d.dispatch(req)['status'],'proposed')

    def test_unknown_schema_and_tool(self):
        req=request('shell',{'command':'echo forbidden'})
        self.assertEqual(Dispatcher().dispatch(req)['code'],'UNKNOWN_TOOL')
        req['schema']='v999'
        self.assertEqual(Dispatcher().dispatch(req)['code'],'UNSUPPORTED_SCHEMA')

    def test_no_callbacks_or_authority_fields(self):
        req=evaluation(); req['arguments']['callback']='__import__("os").system'
        self.assertEqual(Dispatcher().dispatch(req)['code'],'INVALID_ARGUMENT')
        req=evaluation(); req['authority']={'approved':True}
        self.assertEqual(Dispatcher().dispatch(req)['code'],'INVALID_ARGUMENT')
        req=evaluation(); req['arguments']['candidates']=[{'code':'exec'}]
        self.assertEqual(Dispatcher().dispatch(req)['code'],'INVALID_ARGUMENT')

    def test_json_parser_duplicates_and_nonfinite(self):
        d=Dispatcher()
        for raw in ['{"id":"a","id":"b"}', '{"x":NaN}', '{"x":Infinity}', '[]', '{bad']:
            self.assertEqual(d.dispatch_json(raw)['status'],'refused')

    def test_budgets(self):
        d=Dispatcher()
        self.assertEqual(d.dispatch_json(' '*1_000_001)['code'],'BUDGET_EXCEEDED')
        s=synthetic('continuous',201)
        self.assertEqual(d.dispatch(request('compare',dict(scenario=s)))['code'],'BUDGET_EXCEEDED')
        d=Dispatcher()  # the preceding invalid request correctly occupies its own id
        for i in range(32):
            self.assertEqual(d.dispatch(request('plan',dict(scenario=scenario(),route='ground'),str(i)))['status'],'proposed')
        self.assertEqual(d.dispatch(request('plan',dict(scenario=scenario(),route='ground'),'33'))['code'],'BUDGET_EXCEEDED')
        self.assertEqual(d.dispatch(request('plan',dict(scenario=scenario(),route='ground'),'0'))['status'],'proposed')

    def test_response_and_cache_budget(self):
        with patch('capacity.orbital.agentic.dispatcher.MAX_RESPONSE_BYTES', 100):
            self.assertEqual(Dispatcher().dispatch(evaluation())['code'],'BUDGET_EXCEEDED')
        with patch('capacity.orbital.agentic.dispatcher.MAX_CACHE_BYTES', 100):
            self.assertEqual(Dispatcher().dispatch(evaluation())['code'],'BUDGET_EXCEEDED')

    def test_cache_exhaustion_stops_new_evaluation(self):
        d=Dispatcher()
        with patch('capacity.orbital.agentic.dispatcher.MAX_CACHE_BYTES', 100):
            first=d.dispatch(evaluation())
            self.assertEqual(first['code'],'BUDGET_EXCEEDED')
        self.assertEqual(d.dispatch(evaluation()),first)
        req=evaluation();req['id']='new'
        with patch('capacity.orbital.agentic.dispatcher.evaluate', side_effect=AssertionError('must not run')):
            self.assertEqual(d.dispatch(req)['code'],'BUDGET_EXCEEDED')

    def test_source_manifest_covers_dependencies(self):
        m=source_manifest()
        for name in ['planner.py','resources.py','contacts.py','contracts.py','__init__.py','agentic/dispatcher.py','agentic/evaluation.py']:
            self.assertIn(name,m)
        self.assertEqual(source_digest(),digest(m))
        d=Dispatcher()
        with patch('capacity.orbital.agentic.dispatcher.source_digest',return_value='a'*64):
            self.assertEqual(d.dispatch(evaluation())['code'],'SOURCE_CHANGED')

    def test_unavailable_source_fails_closed(self):
        d=Dispatcher()
        with patch('capacity.orbital.agentic.dispatcher.source_digest',side_effect=OSError('unavailable')):
            self.assertEqual(d.dispatch(evaluation())['code'],'SOURCE_UNAVAILABLE')
            failed=Dispatcher()
        self.assertEqual(failed.dispatch(evaluation())['code'],'SOURCE_UNAVAILABLE')

    def test_deterministic_sources_and_outcomes(self):
        req=evaluation()
        self.assertEqual(Dispatcher().dispatch(req),Dispatcher().dispatch(req))
        self.assertEqual(Dispatcher().dispatch_json(json.dumps(req)),Dispatcher().dispatch(req))

    def test_manifest(self):
        m=manifest(); self.assertEqual(set(m['tools']), {'plan','compare','evaluate'})
        self.assertEqual(m['limits']['candidates'],3)


class EvaluationTest(unittest.TestCase):
    def run_eval(self,s=None,baseline='ground',candidates=None):
        r=Dispatcher().dispatch(evaluation(s,baseline,candidates))
        self.assertEqual(r['status'],'proposed',r)
        return r['result']

    def test_hand_aggregate_and_improvement(self):
        r=self.run_eval(); self.assertEqual(r['selected_on_train'],'onboard')
        self.assertEqual(r['heldout_disposition'],'improvement')
        score=r['heldout']['onboard']['metrics']
        self.assertEqual(score['planned'],1); self.assertEqual(score['failed'],0)
        self.assertAlmostEqual(score['cost_usd'],.02+30/3600*2.2)
        self.assertAlmostEqual(score['latency_p50_s'],30.8)
        self.assertAlmostEqual(score['latency_p95_s'],30.8)
        self.assertEqual(score['quality_min'],.98)
        self.assertFalse(r['promoted']); self.assertEqual(r['active_policy'],'ground')
        self.assertEqual(r['recommendation'],'independent_review')

    def test_training_winner_regresses_heldout(self):
        s=suite(heldout=scenario(1,onboard_quality=.1,hybrid_quality=.1))
        r=self.run_eval(s)
        self.assertEqual(r['selected_on_train'],'onboard')
        self.assertEqual(r['heldout_disposition'],'regression')
        self.assertEqual(r['recommendation'],'retain_baseline')
        self.assertEqual(r['active_policy'],'ground'); self.assertFalse(r['promoted'])

    def test_heldout_cannot_select_the_winner(self):
        good=self.run_eval(); bad=self.run_eval(suite(heldout=scenario(1,onboard_quality=0)))
        self.assertEqual(good['training'],bad['training'])
        self.assertEqual(good['selected_on_train'],bad['selected_on_train'])
        self.assertNotEqual(good['heldout_disposition'],bad['heldout_disposition'])

    def test_worse_candidate_does_not_win(self):
        r=self.run_eval(baseline='onboard',candidates=['ground'])
        self.assertEqual(r['selected_on_train'],'onboard')
        self.assertEqual(r['heldout_disposition'],'no_improvement')

    def test_cost_cannot_win_by_dropping_jobs(self):
        s=suite(train=scenario(onboard_quality=0,hybrid_quality=0))
        r=self.run_eval(s)
        self.assertEqual(r['selected_on_train'],'ground')
        self.assertEqual(r['training']['onboard']['metrics']['cost_usd'],0)
        self.assertIn('onboard',r['training_excluded_for_lost_baseline_outcomes'])

    def test_rename_content_leakage_refused(self):
        s=suite(); duplicate=deepcopy(s['train'][0]['scenario'])
        duplicate['name']='renamed'; duplicate['provenance']['source']='renamed source'
        duplicate['jobs'][0]['id']='newjob'; duplicate['contacts'][0]['id']='newcontact'
        s['heldout'][0]['scenario']=duplicate
        self.assertEqual(Dispatcher().dispatch(evaluation(s))['code'],'DATA_LEAKAGE')

    def test_duplicate_id_refused(self):
        s=suite(); s['heldout'][0]['id']='train1'
        self.assertEqual(Dispatcher().dispatch(evaluation(s))['code'],'DATA_LEAKAGE')

    def test_semantic_fingerprint_preserves_physics_and_requirements(self):
        s=scenario(); changed=deepcopy(s); changed['jobs'][0]['required_quality']=.99
        self.assertNotEqual(semantic_digest(s),semantic_digest(changed))
        changed=deepcopy(s); changed['nodes']['orbital']['max_power_kw']=.1
        self.assertNotEqual(semantic_digest(s),semantic_digest(changed))

    def test_empty_invalid_and_overbudget_suite(self):
        for changes in [{'train':[]},{'heldout':[]},{'objective':'cost_only'},
                        {'cost_tolerance_usd':-1},{'cost_tolerance_usd':float('nan')}, {'schema':'v2'}]:
            s=suite();s.update(changes)
            self.assertEqual(Dispatcher().dispatch(evaluation(s))['status'],'refused')
        s=suite();s['train']=[dict(id=str(i),scenario=scenario(i)) for i in range(21)]
        self.assertEqual(Dispatcher().dispatch(evaluation(s))['code'],'BUDGET_EXCEEDED')

    def test_candidate_order_does_not_matter(self):
        a=self.run_eval(candidates=['onboard','hybrid']);b=self.run_eval(candidates=['hybrid','onboard'])
        self.assertEqual(a,b)

    def test_fixed_tolerance_prefers_baseline_on_tie(self):
        s=suite();s['cost_tolerance_usd']=100
        self.assertEqual(self.run_eval(s)['selected_on_train'],'ground')

    def test_all_refused_not_free_improvement(self):
        s=suite(train=scenario(deadline_s=1),heldout=scenario(1,deadline_s=2))
        r=self.run_eval(s)
        self.assertEqual(r['heldout_disposition'],'no_improvement')
        self.assertIsNone(r['heldout']['ground']['metrics']['cost_per_planned_result_usd'])


class CliTest(unittest.TestCase):
    def test_jsonl_duplicate_agent_journey(self):
        req=request('plan',dict(scenario=scenario(),route='ground'))
        result=subprocess.run([sys.executable,'-m','capacity.orbital.agentic','--jsonl'],input=(json.dumps(req)+'\n')*2,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        a,b=map(json.loads,result.stdout.splitlines());self.assertEqual(a,b)

    def test_jsonl_stops_at_line_budget(self):
        req=request('plan',dict(scenario=scenario(),route='ground'))
        result=subprocess.run([sys.executable,'-m','capacity.orbital.agentic','--jsonl'],input=(json.dumps(req)+'\n')*33,text=True,capture_output=True)
        self.assertEqual(result.returncode,2)
        self.assertEqual(len(result.stdout.splitlines()),32)
        self.assertIn('remaining input not consumed',result.stderr)

    def test_safe_file_output_and_refused_contract(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'request.json';dest=Path(td)/'result.json'
            source.write_text(json.dumps(evaluation()))
            cmd=[sys.executable,'-m','capacity.orbital.agentic','--request',str(source),'--output',str(dest)]
            r=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
            before=dest.read_bytes()
            r=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(r.returncode,2)
            self.assertEqual(dest.read_bytes(),before)
            source.write_text('{"schema":"bad"}')
            r=subprocess.run(cmd[:-2],capture_output=True,text=True);self.assertEqual(r.returncode,2)
            self.assertEqual(json.loads(r.stdout)['status'],'refused')


if __name__=='__main__':
    unittest.main()
