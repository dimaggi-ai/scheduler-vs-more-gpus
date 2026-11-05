import copy
import json
import subprocess
import sys
import unittest
from .network import plan_network,dynamics_proposal
from .network.fixtures import demo,dynamics_fixture
from .dynamics import evaluate
from .network.report import render
from .contracts import digest

class NetworkTests(unittest.TestCase):
    def test_relay_hand_oracle_and_replay(self):
        s=demo();original=copy.deepcopy(s);r=plan_network(s)
        self.assertEqual(s,original);self.assertEqual(r,plan_network(s))
        j=r['jobs'][0];self.assertEqual(j['status'],'delivered');self.assertEqual(j['arrival_s'],18)
        self.assertEqual([(h['start_s'],h['tx_end_s']) for h in j['hops']],[(0,8),(10,18)])
        self.assertEqual(j['estimated_cost'],.2)
        self.assertEqual(r['receipt_id'],digest({k:v for k,v in r.items() if k!='receipt_id'}))

    def test_propagation_and_too_early_relay(self):
        s=demo();s['contacts'][0]['propagation_s']=2
        self.assertEqual(plan_network(s)['jobs'][0]['arrival_s'],18)
        s['contacts'][0]['propagation_s']=3
        self.assertEqual(plan_network(s)['jobs'][0]['reason_code'],'CONTACT_CAPACITY')
        s=demo();s['contacts'][1].update(start_s=0,end_s=8)
        self.assertEqual(plan_network(s)['jobs'][0]['status'],'refused')

    def test_shared_link_and_terminal(self):
        s=demo('contention');r=plan_network(s)
        self.assertEqual([j['status'] for j in r['jobs']],['delivered','refused'])
        self.assertEqual(r['estimated_cost'],.2)
        # Different contact/link IDs still share A's terminal.
        c=dict(s['contacts'][0],id='AB2',link_id='AB2');s['contacts'].append(c)
        self.assertEqual(plan_network(s)['jobs'][1]['status'],'refused')
        for i,a in enumerate(r['resource_reservations']):
            for b in r['resource_reservations'][i+1:]:
                if a['resource']==b['resource']:self.assertFalse(a['start_s']<b['end_s'] and b['start_s']<a['end_s'])

    def test_buffer_source_relay_and_identical_concurrent_storage(self):
        for node in ('A','B','G'):
            s=demo();s['nodes'][node]['buffer_gb']=.9
            self.assertEqual(plan_network(s)['jobs'][0]['reason_code'],'BUFFER_CAPACITY')
        s=demo('contention')
        for c in s['contacts']:c['end_s']+=30
        s['nodes']['A']['buffer_gb']=1
        # Job2 waits for terminal, but both source inputs occupy storage from release.
        self.assertEqual(plan_network(s)['jobs'][1]['reason_code'],'BUFFER_CAPACITY')

    def test_outage_retention_and_recovery(self):
        r=plan_network(demo('outage'));self.assertEqual(r['jobs'][0]['reason_code'],'STORAGE_RETENTION')
        self.assertFalse(r['resource_reservations']);self.assertEqual(r['estimated_cost'],0)
        self.assertEqual(plan_network(demo('corrected'))['jobs'][0]['status'],'delivered')

    def test_refused_trial_rolls_back(self):
        s=demo();s['jobs']=[dict(s['jobs'][0],id='a-refused',deadline_s=17),dict(s['jobs'][0],id='b-good')]
        r=plan_network(s);self.assertEqual([j['status'] for j in r['jobs']],['refused','delivered'])
        self.assertEqual(r['jobs'][1]['arrival_s'],18);self.assertEqual(r['estimated_cost'],.2)

    def test_availability_boundaries_and_capacity_integral(self):
        s=demo();s['jobs']=[];s['contacts']=[];del s['nodes']['G']
        s['nodes']['B']['unavailable']=[dict(start_s=100,end_s=200)]
        self.assertEqual(plan_network(s)['available_capacity_kw_seconds'],500)
        s=demo();s['nodes']['G']['commissioned_s']=11
        self.assertEqual(plan_network(s)['jobs'][0]['status'],'refused')
        s['nodes']['G']['commissioned_s']=10
        self.assertEqual(plan_network(s)['jobs'][0]['status'],'delivered')
        s['nodes']['G']['retired_s']=18
        self.assertEqual(plan_network(s)['jobs'][0]['status'],'delivered')
        s['nodes']['G']['retired_s']=17
        self.assertEqual(plan_network(s)['jobs'][0]['status'],'refused')

    def test_no_path_jurisdiction_and_deadline(self):
        s=demo();s['contacts']=[];self.assertEqual(plan_network(s)['jobs'][0]['reason_code'],'NO_PATH')
        s=demo();s['nodes']['B']['jurisdiction']='excluded';self.assertEqual(plan_network(s)['jobs'][0]['reason_code'],'JURISDICTION')
        s=demo();s['jobs'][0]['deadline_s']=17;self.assertEqual(plan_network(s)['jobs'][0]['reason_code'],'DEADLINE')

    def test_zero_payload_is_explicit_no_transfer(self):
        s=demo();s['contacts']=[];s['jobs'][0]['data_gb']=0
        r=plan_network(s);self.assertEqual(r['jobs'][0]['arrival_s'],0);self.assertFalse(r['resource_reservations']);self.assertFalse(r['buffer_reservations']);self.assertEqual(r['estimated_cost'],0)

    def test_strict_invalid_and_derived_overflow(self):
        for value in (0,-1,float('inf'),float('nan'),True,10**1000):
            s=demo();s['contacts'][0]['goodput_gbps']=value
            with self.assertRaises(ValueError):plan_network(s)
        s=demo();s['jobs'].append(s['jobs'][0])
        with self.assertRaises(ValueError):plan_network(s)
        s=demo();s['contacts'][0]['cost_per_gb']=1e308;s['jobs'][0]['data_gb']=2
        for c in s['contacts']:c['end_s']+=30
        with self.assertRaises(ValueError):plan_network(s)
        for bad in (None,[],{},'x'):
            with self.assertRaises(ValueError):plan_network(bad)

    def test_positive_transfer_numeric_resolution_refuses(self):
        s=demo();s['jobs'][0]['data_gb']=5e-324;s['contacts'][0]['goodput_gbps']=1e308
        with self.assertRaises(ValueError):plan_network(s)
        s=demo();s['jobs'][0]['data_gb']=1e-20;s['jobs'][0]['release_s']=1
        with self.assertRaises(ValueError):plan_network(s)
        s=demo();s['contacts'][0]['propagation_s']=1e-300;s['jobs'][0]['release_s']=1
        with self.assertRaises(ValueError):plan_network(s)

    def test_dynamics_transfer_energy_and_refusal(self):
        s=demo();r=plan_network(s);a=dict(disposition='allowed',valid_from_s=0,expires_s=300,scope='synthetic-evaluation')
        p=dynamics_proposal(s,r,a);self.assertEqual(len(p['events']),4)
        good=evaluate(p,dynamics_fixture(s));self.assertTrue(good['admissible'])
        self.assertAlmostEqual(sum(1-n['final_kwh'] for n in good['nodes'].values()),32/3600)
        bad=evaluate(p,dynamics_fixture(s,True));self.assertFalse(bad['admissible']);self.assertEqual(bad['violations'][0]['code'],'BATTERY_RESERVE')
        r['jobs'][0]['hops'][0]['data_gb']=.5
        with self.assertRaises(ValueError):dynamics_proposal(s,r,a)

    def test_budget_refusal_is_atomic(self):
        s=demo();s['contacts']=[dict(s['contacts'][0],end_s=300,id=str(i)) for i in range(2)]
        s['jobs']=[dict(s['jobs'][0],id=f'job-{i:03d}',destination='B',data_gb=.01,deadline_s=300) for i in range(100)]
        for n in s['nodes'].values():n['buffer_gb']=100
        original=copy.deepcopy(s)
        with self.assertRaisesRegex(ValueError,'budget'):plan_network(s)
        self.assertEqual(s,original)

    def test_link_identity_across_distinct_terminal_pairs(self):
        s=demo('contention')
        for n in s['nodes'].values():n['terminals'].append('other')
        s['contacts'].append(dict(s['contacts'][0],id='alternate',source_terminal='other',destination_terminal='other'))
        self.assertEqual(plan_network(s)['jobs'][1]['status'],'refused')
        # Removing the link conflict with a physically distinct link admits both
        # first hops, but the shared onward BG contact still refuses job2.
        s['contacts'][-1]['link_id']='independent'
        self.assertEqual(plan_network(s)['jobs'][1]['status'],'refused')

    def test_cli_and_html(self):
        for kind,code in (('relay',0),('outage',3),('corrected',0)):
            r=subprocess.run([sys.executable,'-m','capacity.orbital.network','--demo',kind],capture_output=True,text=True)
            self.assertEqual(r.returncode,code,r.stderr);self.assertIn('receipt_id',json.loads(r.stdout))
        s=demo();s['jobs'][0]['id']='<script>'
        self.assertNotIn('<script>',render(plan_network(s)));self.assertIn('&lt;script&gt;',render(plan_network(s)))

if __name__=='__main__':unittest.main()
