import copy
from dataclasses import asdict
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr

from capacity import loop_study as study
from capacity.stateful_loop import Loop, Stage, SyntheticProvenance, analyze, compare


def decode(record):
    values = dict(record)
    values['stages'] = tuple(Stage(**dict(s, dependencies=tuple(s['dependencies']))) for s in values['stages'])
    values['provenance'] = SyntheticProvenance(**values['provenance'])
    return Loop(**values)


class StudyTests(unittest.TestCase):
    def test_independent_analytic_controls(self):
        inputs, results = study.study()
        rows = {r['id']: r for r in results['interventions']}
        expected = {'baseline':48, 'compute':48, 'memory':48, 'host':36,
                    'fabric':42, 'host-fabric':30, 'joint':27, 'delayed-state':60}
        self.assertEqual({k:r['analysis']['total_lower_bound_s'] for k,r in rows.items()}, expected)
        self.assertEqual(rows['baseline']['analysis']['total_serial_sum_s'], 66)
        self.assertEqual(rows['delayed-state']['lower_bound_saved_seconds'], -12)
        self.assertEqual(rows['joint']['analysis']['critical_path'], ('host','fabric','persist'))
        self.assertEqual(rows['fabric']['analysis']['critical_path'], ('host','compute','persist'))
        self.assertEqual(len(inputs['fixtures']), 24)

    def test_every_export_matches_existing_api_and_hash(self):
        inputs, results = study.study()
        base = decode(inputs['fixtures']['baseline'])
        for row in results['interventions'] + results['sensitivity']:
            candidate = decode(inputs['fixtures'][row['id']])
            result = analyze(candidate)
            self.assertEqual(row['analysis'], asdict(result))
            comparison = compare(base, candidate)
            self.assertEqual(result.graph_context_sha256, analyze(base).graph_context_sha256)
            if 'lower_bound_saved_seconds' in row:
                self.assertEqual(row['lower_bound_saved_seconds'], comparison.lower_bound_saved_seconds)

    def test_sensitivity_switches_and_no_benefit_region(self):
        _, results = study.study()
        rows = {(r['compute_multiplier'],r['fabric_multiplier']):r['analysis'] for r in results['sensitivity']}
        self.assertEqual(rows[(.25,1)]['total_lower_bound_s'],48)
        self.assertEqual(rows[(.5,1)]['total_lower_bound_s'],48)
        self.assertEqual(rows[(.25,.25)]['critical_path'],('host','memory','persist'))
        self.assertEqual(rows[(2,.25)]['critical_path'],('host','compute','persist'))
        self.assertEqual(rows[(1,2)]['critical_path'],('host','fabric','persist'))

    def test_deterministic_artifacts_and_manifest_hashes(self):
        first, second = study.artifacts(), study.artifacts()
        self.assertEqual(first,second)
        self.assertEqual(set(first),{'index.html','inputs.json','results.json','manifest.json'})
        manifest=json.loads(first['manifest.json'])
        self.assertIsNone(manifest['git_sha'])
        for name, record in manifest['files'].items():
            self.assertEqual(record['sha256'],hashlib.sha256(first[name]).hexdigest())
            self.assertEqual(record['bytes'],len(first[name]))
        self.assertEqual(manifest['source_sha256']['capacity/stateful_loop.py'],
                         hashlib.sha256(Path(study.stateful_loop.__file__).read_bytes()).hexdigest())
        self.assertIn('limits',json.loads(first['results.json']))
        self.assertIn('limits',json.loads(first['inputs.json']))

    def test_family_digest_is_actual_canonical_family_hash(self):
        inputs, _ = study.study()
        encoded=(json.dumps(inputs['family_definition'], sort_keys=True, indent=2,
                            ensure_ascii=True, allow_nan=False)+'\n').encode()
        expected=hashlib.sha256(encoded).hexdigest()
        self.assertEqual(inputs['fixture_family']['sha256'],expected)
        for fixture in inputs['fixtures'].values():
            self.assertEqual(fixture['provenance']['sha256'],expected)

    def test_invalid_sensitivity_refuses_before_output(self):
        for bad in ((0,.5,1,2), (True,.5,1,2), (float('nan'),.5,1,2),
                    (float('inf'),.5,1,2), (1,2), (1,2,3,5)):
            with patch.object(study,'MULTIPLIERS',bad), self.assertRaises(ValueError):
                study.study()
        self.assertEqual(len(study.study()[1]['sensitivity']),16)

    def test_html_escaping_and_only_local_asset_links(self):
        _, results=study.study()
        results=copy.deepcopy(results)
        attack='<script src="https://bad.invalid/x">&\'</script>'
        results['interventions'][0]['label']=attack
        results['interventions'][0]['analysis']['input_sha256']=attack
        results['limits']=[attack]
        output=study.render(results)
        self.assertNotIn('<script',output)
        self.assertIn('&lt;script',output)
        class Inspect(HTMLParser):
            def __init__(self): super().__init__(); self.tags=[];self.links=[]
            def handle_starttag(self,tag,attrs):
                self.tags.append(tag)
                for name,value in attrs:
                    if name in ('href','src'): self.links.append(value)
                    self.assertion = not name.lower().startswith('on')
                    if not self.assertion: raise AssertionError(name)
        parser=Inspect();parser.feed(output)
        self.assertNotIn('script',parser.tags)
        self.assertNotIn('iframe',parser.tags)
        self.assertEqual(parser.links,['inputs.json','results.json','manifest.json'])
        self.assertNotIn('@import',output)
        self.assertNotIn('url(',output)

    def test_success_collision_and_corrected_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp).resolve();target=parent/'study'
            self.assertEqual(study.write_study(target),target)
            contents={p.name:p.read_bytes() for p in target.iterdir()}
            with self.assertRaises(OSError): study.write_study(target)
            self.assertEqual(contents,{p.name:p.read_bytes() for p in target.iterdir()})
            corrected=parent/'corrected';study.write_study(corrected)
            self.assertEqual(contents,{p.name:p.read_bytes() for p in corrected.iterdir()})

    def test_symlink_leaf_and_ancestor_refuse_without_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp).resolve();real=parent/'real';real.mkdir()
            marker=real/'marker';marker.write_text('preserve')
            link=parent/'link';link.symlink_to(real,target_is_directory=True)
            for target in (link,link/'new',parent/'link'/'child'/'new'):
                with self.assertRaises(OSError):study.write_study(target)
                self.assertEqual(list(real.iterdir()),[marker])
                self.assertEqual(marker.read_text(),'preserve')
            broken=parent/'broken';broken.symlink_to(parent/'absent')
            with self.assertRaises(OSError):study.write_study(broken)
            self.assertFalse((parent/'absent').exists())

    def test_unsafe_missing_parent_and_file_collision(self):
        for path in ('','.', '/', '../new'):
            with self.assertRaises(ValueError):study.write_study(path)
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp).resolve();file=parent/'file';file.write_text('unchanged')
            for path in (parent/'missing'/'new',file,file/'new'):
                with self.assertRaises(OSError):study.write_study(path)
            self.assertEqual(file.read_text(),'unchanged')

    def test_failed_write_retains_partial_no_false_success_and_recovers(self):
        real_open=os.open
        def fail_second(path,*args,**kwargs):
            if path=='results.json':raise PermissionError('synthetic denied write')
            return real_open(path,*args,**kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp).resolve();target=parent/'partial';out=io.StringIO();err=io.StringIO()
            with patch.object(study.os,'open',side_effect=fail_second),redirect_stdout(out),redirect_stderr(err):
                self.assertEqual(study.main(['--output',str(target)]),2)
            self.assertEqual(out.getvalue(),'')
            self.assertIn('partial output retained',err.getvalue())
            self.assertEqual([p.name for p in target.iterdir()],['inputs.json'])
            with redirect_stdout(io.StringIO()):
                self.assertEqual(study.main(['--output',str(parent/'recovered')]),0)

    def test_computation_failure_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp).resolve()/'none'
            with patch.object(study,'artifacts',side_effect=ValueError('synthetic bad input')):
                with self.assertRaises(ValueError):study.write_study(target)
            self.assertFalse(target.exists())
            study.write_study(target)


if __name__ == '__main__':
    unittest.main()
