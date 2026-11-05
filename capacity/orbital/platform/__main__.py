import argparse,json,sys
from ..dynamics.__main__ import read_json
from ..output import publish
from .mission import compare_mission
from .fixtures import demo
from .report import render
from .tools import dispatch,manifest

def main(argv=None):
    p=argparse.ArgumentParser(description='Capacity Orbital coupled mission workspace (offline synthetic)')
    g=p.add_mutually_exclusive_group(required=True);g.add_argument('--demo',choices=('nominal','battery','corrected','network-loss','late','held'));g.add_argument('--mission');g.add_argument('--request');g.add_argument('--manifest',action='store_true')
    p.add_argument('--output');p.add_argument('--html');a=p.parse_args(argv)
    try:
        if a.manifest:
            if a.html:raise ValueError('HTML requires mission comparison')
            result=manifest();comparison=None
        elif a.request:
            result=dispatch(read_json(a.request))
            if a.html:raise ValueError('HTML requires mission comparison, not generic tool request')
            comparison=None
        else:
            comparison=compare_mission(read_json(a.mission) if a.mission else demo(a.demo));result=comparison
        data=json.dumps(result,indent=2,allow_nan=False)+'\n'
        publish([(a.output,data),(a.html,render(comparison) if comparison else '')],a.mission or a.request)
        if not a.output:print(data,end='')
        if comparison:return 0 if any(r['admissible'] for r in comparison['comparisons']) else 3
        return 2 if result.get('status')=='refused' else 0
    except (ValueError,TypeError,KeyError,OSError,OverflowError,RecursionError) as exc:
        print('REFUSE: '+str(exc),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
