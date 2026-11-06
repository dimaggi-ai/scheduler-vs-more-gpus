"""Local file IO only; agent payloads never interpret paths."""
import argparse
import os
from pathlib import Path
from . import export_checkpoint_bundle,verify_checkpoint_bundle,required_sources,source_digest
from .contracts import Refuse,INNER,BUNDLE,TOOL,wire
from .tools import refusal,SCHEMA
from ..output import publish

def destination(path,input_path):
    output=Path(path);resolved=output.resolve();parent=resolved.parent
    own=Path(__file__).resolve().parent
    if resolved==Path(input_path).resolve():raise Refuse('INVALID_ARGUMENT','output cannot equal input')
    if resolved.is_relative_to(own):raise Refuse('FORBIDDEN_OUTPUT','output is inside bundle source')
    _,sources=required_sources()
    # Existing checkpoint source discovery is nonrecursive. Evidence subdirectories
    # remain allowed; aliases of exact source directory identities do not.
    for directory in {p.parent for p in sources}:
        if parent==directory.resolve():raise Refuse('FORBIDDEN_OUTPUT','output parent is a hashed source directory')
        try:same=os.path.samefile(parent,directory)
        except FileNotFoundError:same=False
        if same:raise Refuse('FORBIDDEN_OUTPUT','output parent aliases a hashed source directory')
    if os.path.lexists(output):raise Refuse('IO_ERROR','output exists; choose a fresh path')
    if not output.parent.is_dir():raise Refuse('IO_ERROR','output parent does not exist')
    return output

def read(path,limit):
    try:
        with open(path,'rb') as handle:return handle.read(limit+1)
    except OSError:raise Refuse('IO_ERROR','input could not be read') from None

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);subs=parser.add_subparsers(dest='command',required=True)
    ex=subs.add_parser('export');ex.add_argument('--request',required=True);ex.add_argument('--output',required=True)
    ve=subs.add_parser('verify');ve.add_argument('--bundle',required=True);ve.add_argument('--expected-sha256')
    args=parser.parse_args(argv)
    try:
        source_digest()
        if args.command=='export':
            path=destination(args.output,args.request)
            result=export_checkpoint_bundle(read(args.request,INNER))
            try:publish([(path,result['bundle_json'])],args.request)
            except (OSError,ValueError):raise Refuse('IO_ERROR','fresh output could not be published') from None
        else:result=verify_checkpoint_bundle(read(args.bundle,BUNDLE),args.expected_sha256)
        response=dict(schema=SCHEMA,id=None,status='ok',result=result,execution_performed=False)
        print(wire(response,TOOL),end='')
        return 2 if args.command=='verify' and not result['valid'] else 0
    except Refuse as ex:
        print(wire(refusal(ex.code,str(ex)),TOOL),end='');return 2
if __name__=='__main__':raise SystemExit(main())
