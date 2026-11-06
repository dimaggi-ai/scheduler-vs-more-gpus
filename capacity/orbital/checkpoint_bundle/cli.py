"""Standalone source-guarded launcher; stdlib must itself be available."""
import json
import sys
from pathlib import Path

def unavailable():
    print(json.dumps(dict(schema='capacity-orbital/checkpoint-bundle-tool-result-v1',id=None,status='refused',code='SOURCE_UNAVAILABLE',reason='required source or inventory missing/unreadable/invalid',execution_performed=False),sort_keys=True,separators=(',',':')))
    return 2

def main():
    here=Path(__file__).resolve().parent;capacity=here.parents[1]
    try:
        names=[]
        for manifest in (here/'source_inventory.json',capacity/'orbital/platform/checkpoint/source_inventory.json'):
            data=manifest.read_bytes()
            if len(data)>100_000:raise ValueError('inventory budget')
            rows=json.loads(data)
            if type(rows) is not list or not rows or len(rows)>1000 or any(type(n) is not str or not n or '\x00' in n or Path(n).is_absolute() or '..' in Path(n).parts for n in rows):raise ValueError('inventory shape')
            names.extend(rows)
        for name in names:(capacity/name).read_bytes()
    except (OSError,ValueError):return unavailable()
    sys.path.insert(0,str(capacity.parent))
    try:
        import capacity as package
        if Path(package.__file__).resolve()!=capacity/'__init__.py':raise RuntimeError('imported capacity differs from preflighted tree')
        from capacity.orbital.checkpoint_bundle.__main__ import main as run
    except ImportError:
        # Match the composed checkpoint startup boundary: classify a failed
        # import only when an inventoried file has actually disappeared.
        for name in names:
            try:(capacity/name).read_bytes()
            except OSError:return unavailable()
        raise
    return run()
if __name__=='__main__':raise SystemExit(main())
