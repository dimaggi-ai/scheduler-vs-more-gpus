import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
import os
import unittest

from .adapters import synthetic
from .contracts import validate, digest
from .planner import compare, plan_route, receipt_id
from .output import publish
from .report import html_report


class OrbitalTests(unittest.TestCase):
    def test_hand_oracle(self):
        s = synthetic(jobs=1)
        r = compare(s)['comparisons']
        # 10 decimal GB at 1 Gbps = 80s; ground compute20s.
        self.assertEqual(r[0]['jobs'][0]['completion_s'], 100)
        self.assertAlmostEqual(r[1]['jobs'][0]['completion_s'], 30.8)
        self.assertEqual(r[2]['jobs'][0]['completion_s'], 28)
        self.assertAlmostEqual(r[0]['summary']['energy_kwh'], 20/3600)
        self.assertAlmostEqual(r[0]['summary']['cost_usd'], 2 + 20/3600*2 + 20/3600*0.2)
        self.assertEqual([x['summary']['downlink_gb'] for x in r], [10, .1, 1])

    def test_shared_terminal_not_double_booked(self):
        s = synthetic(jobs=3)
        for j in s['jobs']:
            j.update(release_s=0, deadline_s=150)
        result = plan_route(s, 'ground')
        self.assertEqual([j['status'] for j in result['jobs']], ['planned','refused','refused'])
        self.assertEqual(result['summary']['downlink_gb'], 10)
        self.assertEqual(len(result['events']), 2)  # failed trial left no reservation

    def test_multiwindow_transfer_and_gap(self):
        s=synthetic(jobs=1)
        s['contacts']=[dict(id='a',start_s=0,end_s=40,goodput_gbps=1,usd_per_gb=.2),
                       dict(id='b',start_s=80,end_s=140,goodput_gbps=1,usd_per_gb=.2)]
        r=plan_route(s,'ground')
        self.assertEqual(r['jobs'][0]['completion_s'],140)
        self.assertEqual([e['gb'] for e in r['events'] if e['kind']=='downlink'],[5,5])

    def test_compute_serial_and_energy_conserved(self):
        s=synthetic(jobs=3)
        for j in s['jobs']:
            j.update(release_s=0,deadline_s=180)
        r=plan_route(s,'onboard')
        compute=[e for e in r['events'] if e['kind']=='compute']
        self.assertEqual([e['start_s'] for e in compute],[0,30,60])
        self.assertAlmostEqual(sum(e['energy_kwh'] for e in compute),r['summary']['energy_kwh'])
        self.assertEqual(len({j['receipt_id'] for j in r['jobs']}),3)

    def test_resource_refusal_and_corrected_recovery(self):
        for field,value,reason in [('memory_gb',1,'memory'),('max_power_kw',.5,'power'),
                                  ('max_heat_kw',.5,'thermal'),('energy_budget_kwh',0,'energy')]:
            with self.subTest(field=field):
                s=synthetic(jobs=1);s['nodes']['orbital'][field]=value
                r=plan_route(s,'onboard')
                self.assertEqual(r['summary']['planned'],0)
                self.assertIn(reason,r['jobs'][0]['reason'])
                self.assertEqual(r['events'],[])
                self.assertEqual(plan_route(synthetic(jobs=1),'onboard')['summary']['planned'],1)

    def test_quality_refusal(self):
        s=synthetic(jobs=1);s['jobs'][0]['onboard_quality']=.8
        self.assertIn('quality',plan_route(s,'onboard')['jobs'][0]['reason'])
        self.assertEqual(plan_route(s,'ground')['summary']['planned'],1)

    def test_missed_contact_and_no_tiny_transfer_bypass(self):
        s=synthetic(jobs=1);s['contacts']=[]
        for r in compare(s)['comparisons']:
            self.assertEqual(r['summary']['planned'],0)
            self.assertIsNone(r['summary']['cost_per_planned_result_usd'])
        s['jobs'][0]['result_gb']=1e-15
        self.assertEqual(plan_route(s,'onboard')['summary']['planned'],0)

    def test_nonfinite_and_wrong_types_refuse(self):
        for val in [None,True,'1',float('nan'),float('inf'),-1,10**1000]:
            with self.subTest(value=str(val)[:20]):
                s=synthetic(jobs=1);s['jobs'][0]['power_kw']=val
                with self.assertRaises(ValueError):compare(s)
        for root in [[],None,'x']:
            with self.assertRaises(ValueError):compare(root)

    def test_contract_schema_units_duplicates(self):
        for mutation in [lambda s:s.update(schema='future'),lambda s:s['jobs'][0].pop('raw_gb'),
                         lambda s:s['jobs'].append(copy.deepcopy(s['jobs'][0])),
                         lambda s:s['jobs'][0].update(raw_mb=100),
                         lambda s:s['jobs'][0].update(deadline_s=0),
                         lambda s:s['contacts'].append(dict(s['contacts'][0],id='b'))]:
            s=synthetic(jobs=1);mutation(s)
            with self.assertRaises(ValueError):compare(s)

    def test_overflow_refuses(self):
        s=synthetic(jobs=1);s['jobs'][0]['raw_gb']=1e308
        with self.assertRaises(ValueError):compare(s)
        s=synthetic(jobs=1);s['horizon_s']=200000
        s['nodes']['ground'].update(compute_usd_per_hour=1e308,energy_budget_kwh=1000)
        s['jobs'][0].update(ground_s=100000,deadline_s=200000)
        with self.assertRaises(ValueError):compare(s)

    def test_adapter_swap_and_replay(self):
        for name in ('continuous','intermittent'):
            s=synthetic(name)
            a=compare(s);b=compare(copy.deepcopy(s))
            self.assertEqual(a,b)
            self.assertEqual(a['input_sha256'],digest(s))
            self.assertEqual(len(a['comparisons']),3)
        self.assertNotEqual(compare(synthetic('continuous')),compare(synthetic('intermittent')))

    def test_deadline_failed_reservation_rolls_back(self):
        s=synthetic(jobs=2);s['jobs'][0].update(deadline_s=50)
        s['jobs'][1].update(release_s=0,deadline_s=180)
        r=plan_route(s,'ground')
        self.assertEqual([x['status'] for x in r['jobs']],['refused','planned'])
        self.assertEqual(r['jobs'][1]['completion_s'],100)

    def test_html_escapes_untrusted_fields(self):
        s=synthetic(jobs=1);s['name']='<script>alert(1)</script>'
        html=html_report(compare(s))
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertIn('viewport',html)
        self.assertNotIn('https://',html)

    def test_cli_success_error_recovery_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scenario=root/'scenario.json';out=root/'report.json';html=root/'report.html'
            scenario.write_text('{"schema":"bad"}')
            command=[sys.executable,'-m','capacity.orbital','--scenario',str(scenario),'--output',str(out),'--html',str(html)]
            bad=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(bad.returncode,2);self.assertIn('REFUSE:',bad.stderr);self.assertFalse(out.exists())
            scenario.write_text(json.dumps(synthetic(jobs=1)))
            good=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(good.returncode,0,good.stderr)
            report=json.loads(out.read_text());self.assertIn('source_sha256',report);self.assertTrue(html.exists())
            old=out.read_bytes()
            self.assertEqual(subprocess.run(command,capture_output=True).returncode,2)
            self.assertEqual(out.read_bytes(),old)
            duplicate=root/'duplicate.json';duplicate.write_text('{"schema":1,"schema":2}')
            bad=subprocess.run([sys.executable,'-m','capacity.orbital','--scenario',str(duplicate)],capture_output=True,text=True)
            self.assertEqual(bad.returncode,2);self.assertIn('duplicate JSON key',bad.stderr)


    def test_missing_directory_produces_no_partial_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'partial.json'
            result=subprocess.run([sys.executable,'-m','capacity.orbital','--demo','continuous',
                                   '--output',str(out),'--html',str(root/'missing'/'report.html')],
                                  capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertFalse(out.exists())
            self.assertEqual(list(root.iterdir()),[])

    def test_publish_rollback_preserves_concurrent_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'a';b=root/'b';link=os.link
            def injected(src,dst):
                if Path(dst)==b:
                    b.write_text('another writer')
                    raise FileExistsError('race')
                link(src,dst)
            with patch('capacity.orbital.output.os.link',side_effect=injected):
                with self.assertRaises(FileExistsError):
                    publish([(a,'first'),(b,'second')])
            self.assertFalse(a.exists())
            self.assertEqual(b.read_text(),'another writer')
            self.assertEqual(list(root.iterdir()),[b])

    def test_publish_preflight_and_staging_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'a';b=root/'b'
            with patch('capacity.orbital.output.os.fsync',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):publish([(a,'first'),(b,'second')])
            self.assertEqual(list(root.iterdir()),[])
            b.write_text('existing')
            with self.assertRaises(ValueError):publish([(a,'first'),(b,'second')])
            self.assertFalse(a.exists());self.assertEqual(b.read_text(),'existing')

    def test_receipts_bind_source_outcome_and_events(self):
        s=synthetic(jobs=1);code='a'*64
        r=compare(s,source_sha256=code);route=r['comparisons'][0];row=route['jobs'][0]
        original=row['receipt_id']
        self.assertEqual(original,receipt_id(r['input_sha256'],code,row,route['events']))
        for key in ('completion_s','energy_kwh','cost_usd','downlink_gb','quality'):
            altered=dict(row);altered[key]+=1
            self.assertNotEqual(original,receipt_id(r['input_sha256'],code,altered,route['events']))
        changed=copy.deepcopy(route['events']);changed[0]['start_s']+=1
        self.assertNotEqual(original,receipt_id(r['input_sha256'],code,row,changed))
        self.assertNotEqual(original,compare(s,source_sha256='b'*64)['comparisons'][0]['jobs'][0]['receipt_id'])
        self.assertIsNone(compare(s)['source_sha256'])
        self.assertIn('unbound',compare(s)['source_binding'])
        with self.assertRaises(ValueError):compare(s,source_sha256='invalid')

    def test_scenario_with_jobs_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'s.json';path.write_text(json.dumps(synthetic(jobs=1)))
            result=subprocess.run([sys.executable,'-m','capacity.orbital','--scenario',str(path),'--jobs','999'],
                                  capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertIn('--jobs is only valid with --demo',result.stderr)

    def test_compare_validates_once(self):
        from .contracts import validate
        with patch('capacity.orbital.planner.validate',wraps=validate) as check:
            compare(synthetic())
            self.assertEqual(check.call_count,1)

    def test_contact_bisect_keeps_boundary_and_rollback(self):
        s=synthetic(jobs=1)
        s['jobs'][0].update(release_s=40,deadline_s=180)
        s['contacts']=[dict(id='past',start_s=0,end_s=40,goodput_gbps=1,usd_per_gb=.2),
                       dict(id='future',start_s=40,end_s=180,goodput_gbps=1,usd_per_gb=.2)]
        r=plan_route(s,'ground')
        self.assertEqual(r['jobs'][0]['completion_s'],140)
        self.assertEqual(r['events'][0]['resource'],'future')


if __name__ == '__main__':
    unittest.main()
