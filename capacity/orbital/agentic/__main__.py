"""Stdlib CLI: one request file or a bounded JSON-lines session on stdin."""
import argparse
import json
from pathlib import Path
import sys
from ..output import publish
from .contracts import MAX_REQUEST_BYTES, MAX_REQUESTS
from .dispatcher import Dispatcher, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description='Capacity Orbital agent tools: synthetic planning only')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--request', help='Versioned JSON request file')
    mode.add_argument('--jsonl', action='store_true', help='Up to 32 JSON-line requests on stdin')
    mode.add_argument('--manifest', action='store_true')
    parser.add_argument('--output', help='New response JSON file; not valid with --jsonl')
    args = parser.parse_args(argv)
    if args.jsonl and args.output:
        parser.error('--output cannot be combined with --jsonl')
    try:
        dispatcher = Dispatcher()
        if args.jsonl:
            failed = False
            for _ in range(MAX_REQUESTS):
                raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
                if not raw:
                    return 2 if failed else 0
                response = dispatcher.dispatch_json(raw)
                print(json.dumps(response, allow_nan=False), flush=True)
                failed |= response['status'] == 'refused'
                if len(raw) > MAX_REQUEST_BYTES:
                    return 2  # do not interpret the rest of an overlong line as another request
            # Explicit bounded session: stop after 32 lines without unbounded stdin reads.
            print('STOP: 32-line session budget reached; remaining input not consumed', file=sys.stderr)
            return 2
        if args.manifest:
            result = manifest()
        else:
            with Path(args.request).open('rb') as stream:
                result = dispatcher.dispatch_json(stream.read(MAX_REQUEST_BYTES + 1))
        encoded = json.dumps(result, indent=2, allow_nan=False) + '\n'
        if args.output:
            publish([(args.output, encoded)], args.request)
        else:
            print(encoded, end='')
        return 2 if result.get('status') == 'refused' else 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('REFUSE: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
