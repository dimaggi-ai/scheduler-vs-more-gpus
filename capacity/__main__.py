"""Run: python -m capacity replay examples/capacity-replay.json."""
import argparse
import json
import sys
from pathlib import Path

from .report import replay, compare


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline scheduler capacity replay; no cluster access")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("replay")
    run.add_argument("scenario", type=Path)
    diff = sub.add_parser("compare")
    diff.add_argument("baseline", type=Path)
    diff.add_argument("candidate", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "replay":
            data = json.loads(args.scenario.read_text())
            if not isinstance(data, dict) or data.keys() - {"config", "policy", "workloads"}:
                raise ValueError("scenario accepts config, policy and optional workloads only")
            result = replay(data["config"], data["policy"], data.get("workloads"))
        else:
            result = compare(json.loads(args.baseline.read_text()), json.loads(args.candidate.read_text()))
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"capacity: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
