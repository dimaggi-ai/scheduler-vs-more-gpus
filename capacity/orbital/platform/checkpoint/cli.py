"""Source-guarded standalone entry point; run by file path, not -m."""
import json
import sys
from pathlib import Path

def unavailable():
    print(json.dumps(dict(schema='capacity-orbital/checkpoint-mission-tool-result-v2',id=None,status='refused',code='SOURCE_UNAVAILABLE',reason='required source or inventory missing/unreadable/invalid',input_sha256=None,source_sha256=None,execution_performed=False),sort_keys=True,separators=(',',':')))
    return 2

def main():
    here=Path(__file__).resolve().parent;capacity=here.parents[2]
    try:
        manifest=(here/'source_inventory.json').read_bytes()
        if len(manifest)>100_000:raise ValueError('inventory budget')
        names=json.loads(manifest)
        if type(names) is not list or not names or any(type(n) is not str or Path(n).is_absolute() or '..' in Path(n).parts for n in names):raise ValueError('inventory shape')
        for name in names:(capacity/name).read_bytes()
    except (OSError,json.JSONDecodeError,ValueError):
        return unavailable()
    sys.path.insert(0,str(capacity.parent))
    try:
        import capacity as package
        if Path(package.__file__).resolve() != capacity/'__init__.py':
            raise RuntimeError('imported capacity is outside preflighted source tree')
        from capacity.orbital.platform.checkpoint.__main__ import main as run
    except ModuleNotFoundError as ex:
        relative=ex.name.removeprefix('capacity.').replace('.','/') if ex.name else ''
        candidates=[relative+'.py',relative+'/__init__.py']
        if ex.name=='capacity':candidates=['__init__.py']
        for name in candidates:
            if name in names:
                try:(capacity/name).read_bytes()
                except OSError:return unavailable()
        raise

    return run()

if __name__=='__main__':raise SystemExit(main())
