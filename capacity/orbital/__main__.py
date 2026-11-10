"""CLI IO boundary. All calculations remain pure in planner.py."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from .adapters import synthetic
from .contracts import canonical
from .evidence_record import scenario_export, scenario_from_export
from .planner import compare
from .report import html_report
from .output import publish


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def source_digest():
    root = Path(__file__).parent
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.py')) if not p.name.startswith('test_')}
    return hashlib.sha256(canonical(files).encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Capacity Orbital: offline synthetic scenario planner (no spacecraft access)')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--scenario', help='Validated v1 synthetic JSON scenario')
    group.add_argument('--demo', choices=('continuous', 'intermittent'))
    parser.add_argument('--jobs', type=int, default=None, help='Number of synthetic demo jobs (demo only; default 3)')
    parser.add_argument('--output', help='JSON report path (stdout if omitted)')
    parser.add_argument('--html', help='Self-contained HTML report path')
    parser.add_argument('--save-scenario', help='Write the input scenario as a labelled export (assumptions, input and source hashes)')
    args = parser.parse_args(argv)
    try:
        if args.scenario and args.jobs is not None:
            raise ValueError('--jobs is only valid with --demo')
        s = scenario_from_export(read_json(args.scenario)) if args.scenario else synthetic(args.demo, 3 if args.jobs is None else args.jobs)
        source = source_digest()
        result = compare(s, source_sha256=source)
        data = json.dumps(result, indent=2, allow_nan=False) + '\n'
        outputs = [(args.output, data), (args.html, html_report(result)), (args.save_scenario, json.dumps(scenario_export(s, source), indent=2, allow_nan=False)+'\n')]
        publish(outputs, args.scenario)
        if not args.output:
            print(data, end='')
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
        print('REFUSE: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
