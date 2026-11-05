"""Independent numerical oracles and adversarial diligence tool journeys."""
from copy import deepcopy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from .contracts import digest
from .diligence.api import dispatch,dispatch_json,REQUEST,source_manifest
from .diligence.lifecycle import lifecycle_cost,SCHEMA
from .diligence.claims import check_claim
from .diligence.report import html_report

PROVENANCE=dict(kind='synthetic',source='DIMAGGI hand-computable test fixture',licence='MIT',generated_on='2026-11-05')


def lifecycle():
    return dict(schema=SCHEMA,name='Two-year hand oracle',currency='USD',horizon_years=2,discount_rate=.1,
                cash_flows=[dict(id='initial',category='payload',year=0,amount=1000,currency='USD'),
                            dict(id='opex1',category='operation',year=1,amount=100,currency='USD'),
                            dict(id='opex2',category='operation',year=2,amount=100,currency='USD')],
                cohorts=[dict(id='first',count=1,commission_year=0,retirement_year=2,capacity_kw=1,utilization=1,availability=1)],
                provenance=deepcopy(PROVENANCE))


def claim(kind='battery',**changes):
    params={
        'power':dict(generation_kw=2,auxiliary_kw=.2,compute_kw=1,conversion_efficiency=.9),
        'battery':dict(initial_kwh=1,reserve_kwh=.2,load_kw=.8,discharge_efficiency=1,claimed_duration_h=1),
        'link':dict(data_gb=1,goodput_gbps=1,window_s=8,claimed_duration_s=8),
        'thermal':dict(heat_w=400,temperature_k=300,sink_temperature_k=0,emissivity=1,fin_efficiency=1,
                       absorbed_flux_w_m2=0,area_m2=1,area_basis='emitting',view_factor=1)}[kind]
    params.update(changes)
    return dict(schema='capacity-orbital/claim-v1',name='Synthetic '+kind,kind=kind,parameters=params,provenance=deepcopy(PROVENANCE))


def req(tool,value,ident='test'):
    return dict(schema=REQUEST,id=ident,tool=tool,input=value)


class LifecycleTest(unittest.TestCase):
    def test_present_cost_and_matching_output_basis(self):
        r=lifecycle_cost(lifecycle());t=r['totals']
        self.assertAlmostEqual(t['discounted_cost'],1173.5537190082644)
        self.assertAlmostEqual(t['discounted_useful_kw_years'],1/1.1+1/1.1**2)
        self.assertAlmostEqual(t['cost_per_discounted_useful_kw_year'],676.1904761904761)
        self.assertEqual(t['undiscounted_cost'],1200)
        self.assertEqual(t['undiscounted_useful_kw_years'],2)

    def test_lower_utilization_increases_unit_cost(self):
        s=lifecycle();hi=lifecycle_cost(s)['totals'];s['cohorts'][0]['utilization']=.5
        lo=lifecycle_cost(s)['totals']
        self.assertEqual(lo['discounted_cost'],hi['discounted_cost'])
        self.assertAlmostEqual(lo['cost_per_discounted_useful_kw_year'],2*hi['cost_per_discounted_useful_kw_year'])

    def test_commission_retire_and_replacement_gap(self):
        s=lifecycle();s['horizon_years']=4
        s['cohorts']=[dict(s['cohorts'][0],commission_year=.5,retirement_year=1.5),
                       dict(s['cohorts'][0],id='replacement',commission_year=3,retirement_year=4)]
        r=lifecycle_cost(s)
        self.assertEqual([a['useful_kw_years'] for a in r['annual_output']],[.5,.5,0,1])
        self.assertEqual(sum(c['useful_kw_years'] for c in r['cohort_output']),2)

    def test_zero_output_is_unknown_not_free(self):
        s=lifecycle();s['cohorts'][0]['availability']=0;r=lifecycle_cost(s)
        self.assertEqual(r['status'],'unknown');self.assertEqual(r['reason_code'],'ZERO_USEFUL_OUTPUT')
        self.assertIsNone(r['totals']['cost_per_discounted_useful_kw_year'])
        s['cohorts']=[];self.assertIsNone(lifecycle_cost(s)['totals']['cost_per_discounted_useful_kw_year'])

    def test_prepaid_and_marginal_are_distinct(self):
        s=lifecycle();s['cash_flows']=[dict(id='prepaid',category='downlink_allocated',year=0,amount=500,currency='USD'),
                                     dict(id='incremental',category='downlink_marginal',year=1,amount=0,currency='USD')]
        r=lifecycle_cost(s)
        self.assertEqual(r['by_category']['downlink_allocated']['undiscounted'],500)
        self.assertEqual(r['by_category']['downlink_marginal']['undiscounted'],0)
        self.assertEqual(r['totals']['discounted_cost'],500)

    def test_residual_credit_discounted(self):
        s=lifecycle();s['cash_flows'].append(dict(id='salvage',category='residual',year=2,amount=-121,currency='USD'))
        self.assertAlmostEqual(lifecycle_cost(s)['by_category']['residual']['discounted'],-100)

    def test_zero_discount_and_fractional_cash_time(self):
        s=lifecycle();s['discount_rate']=0
        self.assertEqual(lifecycle_cost(s)['totals']['discounted_cost'],1200)
        s['discount_rate']=.1;s['cash_flows']=[dict(id='half',category='launch',year=.5,amount=100,currency='USD')]
        self.assertAlmostEqual(lifecycle_cost(s)['totals']['discounted_cost'],100/math.sqrt(1.1))

    def test_currency_conversion_refused(self):
        s=lifecycle();s['cash_flows'][1]['currency']='EUR'
        self.assertEqual(dispatch(req('lifecycle_cost',s))['reason_code'],'UNSUPPORTED_CURRENCY')
        s['fx_rate']=1.1
        self.assertEqual(dispatch(req('lifecycle_cost',s))['status'],'refused')

    def test_financing_and_invalid_categories_refused(self):
        for category in ['interest','debt_proceeds','arbitrary']:
            s=lifecycle();s['cash_flows'][0]['category']=category
            self.assertEqual(dispatch(req('lifecycle_cost',s))['status'],'refused')

    def test_domains_and_bounds_refuse(self):
        for key,value in [('discount_rate',-1),('discount_rate',float('nan')),('horizon_years',101),('horizon_years',1.5)]:
            s=lifecycle();s[key]=value
            self.assertEqual(dispatch(req('lifecycle_cost',s))['status'],'refused')
        for change in [dict(count=True),dict(count=0),dict(utilization=1.1),dict(commission_year=3),dict(retirement_year=0),dict(capacity_kw=-1)]:
            s=lifecycle();s['cohorts'][0].update(change)
            self.assertEqual(dispatch(req('lifecycle_cost',s))['status'],'refused')
        s=lifecycle();s['cash_flows']*=400
        self.assertEqual(dispatch(req('lifecycle_cost',s))['reason_code'],'BUDGET_EXCEEDED')

    def test_duplicate_ids_and_negative_cost_refused(self):
        s=lifecycle();s['cash_flows'][1]['id']='initial'
        self.assertEqual(dispatch(req('lifecycle_cost',s))['status'],'refused')
        s=lifecycle();s['cash_flows'][1]['amount']=-1
        self.assertEqual(dispatch(req('lifecycle_cost',s))['status'],'refused')
        s=lifecycle();s['cash_flows'][0]['category']='residual'
        self.assertEqual(dispatch(req('lifecycle_cost',s))['status'],'refused')

    def test_net_credit_not_negative_unit_cost(self):
        s=lifecycle();s['cash_flows'].append(dict(id='credit',category='residual',year=2,amount=-2000,currency='USD'))
        for utilization in (1,.5):
            s['cohorts'][0]['utilization']=utilization;r=lifecycle_cost(s)
            self.assertEqual(r['reason_code'],'NET_CREDIT_REVIEW')
            self.assertLess(r['totals']['discounted_cost'],0)
            self.assertIsNone(r['totals']['cost_per_discounted_useful_kw_year'])

    def test_positive_cashflow_and_capacity_underflow_refuse(self):
        s=lifecycle();s['horizon_years']=100;s['discount_rate']=1
        s['cash_flows']=[dict(id='tiny',category='payload',year=100,amount=1e-300,currency='USD')]
        self.assertEqual(dispatch(req('lifecycle_cost',s))['reason_code'],'ARITHMETIC_RESOLUTION')
        s=lifecycle();s['cohorts'][0].update(capacity_kw=1e-300,utilization=1e-300)
        self.assertEqual(dispatch(req('lifecycle_cost',s))['reason_code'],'ARITHMETIC_RESOLUTION')

    def test_overflow_refuses(self):
        s=lifecycle();s['cohorts'][0].update(count=1_000_000,capacity_kw=1e308)
        self.assertEqual(dispatch(req('lifecycle_cost',s))['reason_code'],'ARITHMETIC_OVERFLOW')


class ClaimTest(unittest.TestCase):
    def test_battery_hand_oracle(self):
        r=check_claim(claim());self.assertEqual(r['status'],'consistent')
        self.assertEqual(r['prediction']['usable_duration_h'],1)
        r=check_claim(claim(discharge_efficiency=.5));self.assertEqual(r['status'],'inconsistent')
        self.assertEqual(r['prediction']['usable_duration_h'],.5)

    def test_battery_below_reserve_is_insufficient(self):
        r=check_claim(claim(initial_kwh=.1));self.assertEqual(r['status'],'inconsistent')
        self.assertEqual(r['prediction']['usable_duration_h'],0)

    def test_power_balance(self):
        r=check_claim(claim('power'));self.assertEqual(r['status'],'consistent')
        self.assertAlmostEqual(r['prediction']['available_compute_kw'],1.6)
        self.assertEqual(check_claim(claim('power',generation_kw=0))['status'],'inconsistent')

    def test_decimal_link_hand_oracle(self):
        r=check_claim(claim('link'));self.assertEqual(r['status'],'consistent')
        self.assertEqual(r['prediction']['required_duration_s'],8)
        self.assertEqual(r['prediction']['capacity_gb'],1)
        self.assertEqual(check_claim(claim('link',window_s=7.999))['status'],'inconsistent')
        self.assertEqual(check_claim(claim('link',claimed_duration_s=7))['status'],'inconsistent')

    def test_thermal_independent_numeric_oracle(self):
        r=check_claim(claim('thermal'));self.assertEqual(r['status'],'consistent')
        self.assertAlmostEqual(r['prediction']['net_heat_rejection_w'],459.300327939)
        p=claim('thermal');p['parameters'].update(area_basis='panel_footprint',emitting_faces=2)
        self.assertAlmostEqual(check_claim(p)['prediction']['net_heat_rejection_w'],918.600655878)

    def test_positive_duration_underflow_cannot_claim_zero_time(self):
        p=claim('link',data_gb=1e-300,goodput_gbps=1e300,window_s=0,claimed_duration_s=0)
        self.assertEqual(dispatch(req('check_claim',p))['reason_code'],'ARITHMETIC_RESOLUTION')
        p=claim(initial_kwh=1e-300,reserve_kwh=0,discharge_efficiency=1e-300,claimed_duration_h=0)
        self.assertEqual(dispatch(req('check_claim',p))['reason_code'],'ARITHMETIC_RESOLUTION')

    def test_missing_and_ambiguous_area_unknown(self):
        p=claim('thermal');del p['parameters']['area_basis']
        self.assertEqual(check_claim(p)['status'],'unknown')
        p=claim('thermal',area_basis='panel_footprint')
        self.assertEqual(check_claim(p)['missing_assumptions'],['emitting_faces'])
        p=claim();del p['parameters']['discharge_efficiency']
        self.assertEqual(check_claim(p)['reason_code'],'MISSING_ASSUMPTIONS')
        p=claim();p['parameters']['reserve_kwh']=None
        self.assertEqual(check_claim(p)['status'],'unknown')

    def test_absorbed_flux_and_sink_cannot_win(self):
        r=check_claim(claim('thermal',absorbed_flux_w_m2=1000))
        self.assertEqual(r['status'],'inconsistent');self.assertLess(r['prediction']['net_heat_rejection_w'],0)
        self.assertEqual(check_claim(claim('thermal',sink_temperature_k=300))['status'],'inconsistent')

    def test_unsupported_models_unknown(self):
        for kind in ['radiation','transient','flight_qualification']:
            p=claim();p['kind']=kind
            r=check_claim(p);self.assertEqual(r['status'],'unknown');self.assertEqual(r['reason_code'],'UNSUPPORTED_MODEL')

    def test_invalid_parameters_refused(self):
        for kind,change in [('battery',dict(load_kw=0)),('battery',dict(initial_kwh=-1)),('battery',dict(discharge_efficiency=2)),
                            ('link',dict(goodput_gbps=float('inf'))),('thermal',dict(area_m2=-1)),('thermal',dict(emitting_faces=2)),
                            ('thermal',dict(view_factor=1.1)),('power',dict(conversion_efficiency=True))]:
            self.assertEqual(dispatch(req('check_claim',claim(kind,**change)))['status'],'refused')
        self.assertEqual(dispatch(req('check_claim',claim('thermal',temperature_k=1e300)))['reason_code'],'ARITHMETIC_OVERFLOW')

    def test_present_invalid_even_when_other_missing_refuses(self):
        p=claim();del p['parameters']['load_kw'];p['parameters']['initial_kwh']=-1
        self.assertEqual(dispatch(req('check_claim',p))['status'],'refused')


class ApiTest(unittest.TestCase):
    def test_determinism_immutability_and_source(self):
        request=req('lifecycle_cost',lifecycle());before=deepcopy(request)
        a=dispatch(request);b=dispatch_json(json.dumps(request))
        self.assertEqual(a,b);self.assertEqual(before,request)
        self.assertEqual(a['source_sha256'],digest(source_manifest()))
        self.assertEqual(a['outcome_sha256'],digest({k:v for k,v in a.items() if k!='outcome_sha256'}))
        self.assertFalse(a['execution_performed']);self.assertFalse(a['promoted'])

    def test_corrected_retry(self):
        request=req('check_claim',claim(load_kw=-1))
        self.assertEqual(dispatch(request)['status'],'refused')
        request['input']['parameters']['load_kw']=.8
        result=dispatch(request);self.assertEqual(result['result']['status'],'consistent')
        self.assertEqual(result,dispatch(request))

    def test_no_callbacks_authority_or_unknown_tools(self):
        for tool in ['shell','fetch','authorize']:
            self.assertEqual(dispatch(req(tool,{}))['reason_code'],'UNKNOWN_TOOL')
        request=req('check_claim',claim());request['authority']=True
        self.assertEqual(dispatch(request)['status'],'refused')

    def test_malformed_json_and_budgets(self):
        for raw in ['[]','{"id":1,"id":2}','{"x":NaN}', '{bad']:
            self.assertEqual(dispatch_json(raw)['status'],'refused')
        self.assertEqual(dispatch_json(' '*1_000_001)['reason_code'],'BUDGET_EXCEEDED')

    def test_source_unavailable_refuses(self):
        with patch('capacity.orbital.diligence.api.source_manifest',side_effect=OSError('missing')):
            self.assertEqual(dispatch(req('check_claim',claim()))['reason_code'],'SOURCE_UNAVAILABLE')

    def test_html_escaping(self):
        request=req('lifecycle_cost',lifecycle());request['input']['cash_flows'][0]['id']='<script>alert(1)</script>'
        output=html_report(dispatch(request))
        self.assertNotIn('<script>',output);self.assertIn('&lt;script&gt;',output)
        self.assertIn('Not physical verification',output)
        self.assertNotIn('http://',output)

    def test_cli_outputs_and_preserves_existing(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'request.json';out=Path(td)/'report.json';html=Path(td)/'report.html'
            source.write_text(json.dumps(req('check_claim',claim())))
            cmd=[sys.executable,'-m','capacity.orbital.diligence','--request',str(source),'--output',str(out),'--html',str(html)]
            p=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(p.returncode,0,p.stderr)
            before=out.read_bytes();self.assertEqual(json.loads(before)['result']['status'],'consistent')
            p=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(p.returncode,2)
            self.assertEqual(before,out.read_bytes())


if __name__=='__main__':unittest.main()
