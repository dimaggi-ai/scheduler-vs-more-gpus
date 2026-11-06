"""Directed validation and energy-resolution controls for accepted parent verifier."""
import copy
import unittest
from .platform.fixtures import demo
from .platform.mission import plan_mission
from .platform.verify import _report_shapes,_energy_matches,verify_mission

class PlatformVerifierGuards(unittest.TestCase):
    def test_numeric_rows_refuse_before_derived_arithmetic(self):
        report=plan_mission(demo(),'hybrid')
        def targets(r):
            interval=next(x for n in r['dynamics']['nodes'].values() for x in n['intervals'])
            return [(r['jobs'][0],'quality'),(r['jobs'][0],'completion_s'),
                    (r['proposal']['events'][0],'power_kw'),(r['network']['jobs'][0],'arrival_s'),
                    (r['network']['jobs'][0]['hops'][0],'data_gb'),
                    (r['network']['resource_reservations'][0],'start_s'),
                    (r['processing_buffers'][0],'data_gb'),
                    (r['network_input']['jobs'][0],'data_gb'),(interval,'heat_w'),
                    (interval['energy'],'load_kwh'),(r['cost'],'network_usd')]
        _report_shapes(report)
        for index in range(len(targets(report))):
            for invalid in ('12',[12],True,float('inf'),10**400):
                changed=copy.deepcopy(report);row,key=targets(changed)[index];row[key]=invalid
                with self.assertRaises(ValueError,msg=(index,key,type(invalid))):_report_shapes(changed)
                self.assertFalse(verify_mission(demo(),changed)['valid'])

    def test_energy_accounts_for_timestamp_resolution_not_large_tolerance(self):
        # Exact physical duration 0.3 is rounded when added to a large timestamp.
        # Recovered subtraction differs, so an absolute timestamp ULP term is required.
        start=100_000.0;end=start+.3;energy=.3/3600
        self.assertTrue(_energy_matches(energy,1,start,end))
        self.assertFalse(_energy_matches(energy+1e-8,1,start,end))
        self.assertFalse(_energy_matches(float('inf'),1,start,end))

if __name__=='__main__':unittest.main()
