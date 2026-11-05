"""Independent arithmetic and public-boundary contracts for synthetic dynamics."""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from .contracts import digest
from .dynamics import evaluate
from .dynamics.fixtures import demo
from .dynamics.physics import temperature
from .dynamics.report import render

class DynamicsTests(unittest.TestCase):
    def run_case(self, kind='nominal'):
        bundle=demo(kind)
        return bundle, evaluate(bundle['proposal'],bundle['scenario'])

    def test_nominal_energy_and_immutable_replay(self):
        b=demo('nominal'); original=copy.deepcopy(b)
        r=evaluate(b['proposal'],b['scenario'])
        self.assertTrue(r['admissible']);self.assertEqual(original,b)
        self.assertEqual(r,evaluate(b['proposal'],b['scenario']))
        n=next(iter(r['nodes'].values()))
        self.assertAlmostEqual(n['intervals'][0]['energy']['final_kwh'],.9)
        self.assertAlmostEqual(n['final_kwh'],.4)
        for row in n['intervals']:
            self.assertLessEqual(abs(row['energy']['residual_kwh']),row['energy']['residual_tolerance_kwh'])

    def test_reserve_crossing_and_recovery(self):
        _,r=self.run_case('reserve')
        self.assertFalse(r['admissible']);self.assertEqual(r['violations'][0]['code'],'BATTERY_RESERVE')
        self.assertAlmostEqual(r['violations'][0]['at_s'],720)
        _,good=self.run_case('corrected');self.assertTrue(good['admissible'])

    def test_thermal_hand_oracle(self):
        self.assertAlmostEqual(temperature(300,280,3000,100,10000,100),306.3212055882856)
        self.assertEqual(temperature(300,280,1000,0,10000,20),302)
        _,r=self.run_case('thermal')
        self.assertEqual(r['violations'][0]['code'],'THERMAL_LIMIT')
        self.assertAlmostEqual(r['violations'][0]['at_s'],69.31471805599453)

    def simple(self,horizon=1800):
        b=demo('nominal');s=b['scenario'];p=b['proposal'];s['horizon_s']=horizon
        n=next(iter(s['nodes'].values()));n['profiles']=[dict(start_s=0,end_s=horizon,solar_kw=0,background_kw=0,background_heat_w=0,sink_k=300)]
        p['events']=[];p['authority']['expires_s']=horizon
        return b,n

    def test_efficiency_curtailment_and_bus_limit(self):
        b,n=self.simple();n['battery']['charge_efficiency']=.8
        n['profiles'][0].update(solar_kw=1,background_kw=.2)
        r=evaluate(b['proposal'],b['scenario']);self.assertAlmostEqual(next(iter(r['nodes'].values()))['final_kwh'],1.32)
        n['battery']['capacity_kwh']=1.1
        r=evaluate(b['proposal'],b['scenario']);e=next(iter(r['nodes'].values()))['intervals'][0]['energy']
        self.assertAlmostEqual(e['final_kwh'],1.1);self.assertAlmostEqual(e['curtailed_kwh'],.275)
        b,n=self.simple(3600);n['battery'].update(initial_kwh=2,discharge_efficiency=.9,max_discharge_kw=.9)
        n['profiles'][0]['background_kw']=.9
        r=evaluate(b['proposal'],b['scenario']);self.assertTrue(r['admissible']);self.assertAlmostEqual(next(iter(r['nodes'].values()))['final_kwh'],1)
        n['battery']['max_discharge_kw']=.8
        self.assertEqual(evaluate(b['proposal'],b['scenario'])['violations'][0]['code'],'DISCHARGE_POWER_LIMIT')

    def test_segmentation_and_shared_clock(self):
        b,n=self.simple();n['profiles'][0].update(background_kw=.2,background_heat_w=1000)
        r=evaluate(b['proposal'],b['scenario']);base=next(iter(r['nodes'].values()))
        row=n['profiles'][0];n['profiles']=[dict(row,end_s=600),dict(row,start_s=600)]
        other=copy.deepcopy(n);other['profiles']=[dict(row,end_s=300),dict(row,start_s=300)]
        b['scenario']['nodes']['other']=other
        r=evaluate(b['proposal'],b['scenario'])
        for value in r['nodes'].values():
            self.assertAlmostEqual(value['final_kwh'],base['final_kwh'])
            self.assertAlmostEqual(value['final_k'],base['final_k'])
            self.assertEqual([x['start_s'] for x in value['intervals']],[0,300,600])

    def test_active_events_do_not_lose_small_remaining_load(self):
        b,n=self.simple(2);node=next(iter(b['scenario']['nodes']))
        n['battery'].update(capacity_kwh=1e17,initial_kwh=1e17,max_discharge_kw=1e17)
        b['proposal']['events']=[dict(id='large',node=node,kind='compute',start_s=0,end_s=1,power_kw=1e16,heat_w=0),dict(id='small',node=node,kind='transfer',start_s=0,end_s=2,power_kw=1,heat_w=0)]
        r=evaluate(b['proposal'],b['scenario']);self.assertEqual(r['nodes'][node]['intervals'][1]['load_kw'],1)
        b['proposal']['events'].reverse();r2=evaluate(b['proposal'],b['scenario'])
        self.assertEqual(r['nodes'],r2['nodes'])

    def test_transfer_only_heat_and_simultaneous_load(self):
        b,n=self.simple(20);node=next(iter(b['scenario']['nodes']))
        n['thermal']['conductance_w_per_k']=0
        b['proposal']['events']=[dict(id=str(i),node=node,kind='transfer',start_s=0,end_s=20,power_kw=.1,heat_w=500) for i in range(2)]
        r=evaluate(b['proposal'],b['scenario']);self.assertAlmostEqual(r['nodes'][node]['final_k'],302)
        self.assertAlmostEqual(r['nodes'][node]['final_kwh'],1-.2*20/3600)

    def test_authority_fail_closed(self):
        for mode in ('missing','held','refused','expired','future'):
            with self.subTest(mode=mode):
                b=demo('nominal');a=b['proposal']['authority']
                if mode=='missing':del b['proposal']['authority']
                elif mode=='expired':a['expires_s']=1
                elif mode=='future':a['valid_from_s']=1
                else:a['disposition']=mode
                r=evaluate(b['proposal'],b['scenario']);self.assertFalse(r['admissible']);self.assertFalse(r['nodes']);self.assertTrue(r['violations'][0]['code'].startswith('AUTHORITY_'))

    def test_invalid_domains_and_overflow(self):
        for value in (-1,True,float('inf'),float('nan'),10**1000):
            b,n=self.simple();n['battery']['capacity_kwh']=value
            with self.subTest(value=str(value)[:30]),self.assertRaises(ValueError):evaluate(b['proposal'],b['scenario'])
        for bad in (None,[],{},'x'):
            with self.assertRaises(ValueError):evaluate({},bad)
        b,n=self.simple();n['profiles'][0]['background_heat_w']=1e308;n['thermal']['conductance_w_per_k']=1e-308
        with self.assertRaises(ValueError):evaluate(b['proposal'],b['scenario'])
        b,n=self.simple();n['profiles'][0]['end_s']-=1
        with self.assertRaises(ValueError):evaluate(b['proposal'],b['scenario'])

    def test_receipt_and_html_binding(self):
        b=demo('nominal');b['proposal']['id']='<script>alert(1)</script>'
        r=evaluate(b['proposal'],b['scenario'],source_sha256='a'*64)
        self.assertEqual(r['receipt_id'],digest({k:v for k,v in r.items() if k!='receipt_id'}))
        html=render(r);self.assertNotIn('<script>',html);self.assertIn('&lt;script&gt;',html);self.assertIn('a'*64,html)
        b['proposal']['events'][0]['power_kw']=.9
        self.assertNotEqual(r['receipt_id'],evaluate(b['proposal'],b['scenario'],source_sha256='a'*64)['receipt_id'])

    def test_cli_refusal_recovery_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'report.json';html=Path(temp)/'report.html'
            command=[sys.executable,'-m','capacity.orbital.dynamics']
            r=subprocess.run(command+['--demo','reserve','--output',str(target),'--html',str(html)],capture_output=True,text=True)
            self.assertEqual(r.returncode,3,r.stderr);self.assertTrue(html.exists())
            original=target.read_bytes()
            r=subprocess.run(command+['--demo','corrected','--output',str(target)],capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertEqual(target.read_bytes(),original)
            r=subprocess.run(command+['--demo','corrected'],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(json.loads(r.stdout)['admissible'])
            malformed=Path(temp)/'bad.json';malformed.write_text('{}')
            r=subprocess.run(command+['--scenario',str(malformed)],capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertIn('REFUSE:',r.stderr)

if __name__=='__main__':unittest.main()
