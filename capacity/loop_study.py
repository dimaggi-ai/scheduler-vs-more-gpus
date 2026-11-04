"""Deterministic offline visual study of a fixed synthetic stateful loop."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import sys

from . import stateful_loop
from .stateful_loop import Loop, Stage, SyntheticProvenance, analyze, compare

LIMITS = (
    "Synthetic dependency-only latency lower bound; unlimited stage resources and perfect branch overlap.",
    "Three sequential iterations; each waits for the declared state-completion barrier.",
    "Serial sum is an ideal no-overlap scenario, not an upper bound on actual runtime.",
    "No measured hardware performance, resource contention, uncertainty interval, energy or ROI estimate.",
    "Declared persistence is not verified durability, execution or crash recovery.",
    "Source and input hashes identify bytes or declarations; they do not authenticate results.",
)
MULTIPLIERS = (0.25, 0.5, 1.0, 2.0)


def family_definition() -> dict:
    """Canonical family record hashed as sorted, indented JSON plus newline."""
    stages = (Stage("host", "host", 8, source_id="host-fixture"),
                 Stage("compute", "compute", 4, ("host",), source_id="compute-fixture"),
                 Stage("memory", "memory", 2, ("host",), source_id="memory-fixture"),
                 Stage("fabric", "fabric", 6, ("host",), source_id="fabric-fixture"),
                 Stage("persist", "state", 2, ("compute", "memory", "fabric"), source_id="state-fixture"))
    return dict(family_id="hand-authored-v1", stages=[asdict(s) for s in stages],
                persisted_completion_id="persist", iterations=3, workload="synthetic-loop",
                quality="fixed-quality", protocol="v1")


def baseline() -> Loop:
    """The hand-authored positive-duration fixture; no external inputs."""
    family = family_definition()
    return Loop(tuple(Stage(**s) for s in family["stages"]), "persist", 3,
                "synthetic-loop", "fixed-quality", "v1",
                SyntheticProvenance("hand-authored-v1", "inline synthetic study", "MIT",
                                    "2026-11-04", _digest(_json(family))))


def _change(loop: Loop, **durations: float) -> Loop:
    if not set(durations) <= {s.id for s in loop.stages}:
        raise ValueError("unknown intervention stage")
    return replace(loop, stages=tuple(replace(s, duration_seconds=durations.get(s.id, s.duration_seconds))
                                     for s in loop.stages))


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def study() -> tuple[dict, dict]:
    """Return exact supplied fixtures and existing-API results; fixed bounded work."""
    if type(MULTIPLIERS) is not tuple or len(MULTIPLIERS) != 4 or any(
        type(m) not in (int, float) or not 0 < m <= 4 for m in MULTIPLIERS
    ):
        raise ValueError("sensitivity requires four positive finite multipliers at most 4")
    base = baseline()
    original = {s.id: s.duration_seconds for s in base.stages}
    definitions = (("baseline", "Baseline", {}), ("compute", "Compute only", {"compute": 1}),
                   ("memory", "Memory only", {"memory": 1}), ("host", "Host only", {"host": 4}),
                   ("fabric", "Fabric only", {"fabric": 3}),
                   ("host-fabric", "Host + fabric", {"host": 4, "fabric": 3}),
                   ("joint", "Host + fabric + compute", {"host": 4, "fabric": 3, "compute": 2}),
                   ("delayed-state", "Delayed state", {"persist": 6}))
    inputs, rows, grid = {}, [], []
    for key, label, changes in definitions:
        candidate = _change(base, **changes)
        inputs[key] = asdict(candidate)
        result = compare(base, candidate)
        rows.append(dict(id=key, label=label, changes_seconds={k:dict(before=original[k], after=v) for k,v in changes.items()}, analysis=asdict(result.candidate),
                         lower_bound_saved_seconds=result.lower_bound_saved_seconds,
                         lower_bound_speedup=result.lower_bound_speedup))
    for compute in MULTIPLIERS:
        for fabric in MULTIPLIERS:
            key = f"sensitivity-c{compute:g}-f{fabric:g}"
            candidate = _change(base, compute=4 * compute, fabric=6 * fabric)
            inputs[key] = asdict(candidate)
            result = compare(base, candidate)
            grid.append(dict(id=key, compute_multiplier=compute, fabric_multiplier=fabric,
                             analysis=asdict(result.candidate)))
    return (dict(schema="synthetic-loop-study/v1", evidence_class="synthetic", limits=LIMITS,
                 fixture_family=asdict(base.provenance), family_definition=family_definition(), fixtures=inputs),
            dict(schema="synthetic-loop-study/v1", evidence_class="synthetic", limits=LIMITS,
                 interventions=rows, sensitivity=grid))


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _number(value: float) -> str:
    return f"{value:g}"


def render(results: dict) -> str:
    """Render generated study content with escaped labels and no external assets."""
    rows = results["interventions"]
    base = rows[0]["analysis"]
    max_time = max(r["analysis"]["total_lower_bound_s"] for r in rows)
    comparisons = []
    for row in rows:
        a = row["analysis"]
        total, serial = a["total_lower_bound_s"], a["total_serial_sum_s"]
        width = total / max_time * 100
        changes = "; ".join(f"{k}: {_number(v['before'])} → {_number(v['after'])} s" for k,v in row["changes_seconds"].items()) or "Original durations"
        comparisons.append(f'''<article class="comparison"><div class="rowhead"><h3>{_escape(row['label'])}</h3>
<strong>{_number(total)} s</strong></div><div class="track" aria-hidden="true"><div class="bar" style="width:{width:.6f}%"></div></div>
<p>{_escape(changes)}</p><p>Serial scenario: {_number(serial)} s · Saved lower-bound time: {_number(row['lower_bound_saved_seconds'])} s</p>
<p class="path">Critical path: {_escape(' → '.join(a['critical_path']))}</p></article>''')
    cells = []
    for item in results["sensitivity"]:
        a = item["analysis"]
        branch = a["critical_path"][1]
        # CSS classes come from this closed map, never from displayed text.
        colour = {"compute": "compute", "fabric": "fabric", "memory": "memory"}.get(branch, "other")
        cells.append(f'''<td class="{colour}"><strong>{_number(a['total_lower_bound_s'])} s</strong><span>{_escape(branch)}</span></td>''')
    grid_rows = ''.join(f"<tr><th scope='row'>{m:g}×</th>{''.join(cells[i*4:i*4+4])}</tr>" for i,m in enumerate(MULTIPLIERS))
    # The fixed DAG displays declared durations; elapsed results come from the API.
    svg = '''<svg viewBox="0 0 360 350" role="img" aria-labelledby="dag-title dag-desc">
<title id="dag-title">Baseline dependency graph</title><desc id="dag-desc">Host eight seconds, parallel compute four, memory two and fabric six seconds, then state two seconds. Critical path: host to fabric to state. Each new iteration waits for state completion.</desc>
<g fill="none" stroke="#7e8e9e" stroke-width="2"><path d="M180 76 L180 108 L60 108 L60 139"/><path d="M180 76 L180 139"/><path d="M60 201 L60 229 L180 229 L180 258"/><path d="M180 201 L180 258"/></g>
<g fill="none" stroke="#006d77" stroke-width="4"><path d="M180 76 L180 108 L300 108 L300 139"/><path d="M300 201 L300 229 L180 229 L180 258"/></g>
<g fill="#e0f2f1" stroke="#006d77" stroke-width="2"><rect x="126" y="15" width="108" height="61" rx="10"/><rect x="246" y="139" width="108" height="62" rx="10"/><rect x="126" y="258" width="108" height="62" rx="10"/></g>
<g fill="#f1f5f9" stroke="#7e8e9e"><rect x="6" y="139" width="108" height="62" rx="10"/><rect x="126" y="139" width="108" height="62" rx="10"/></g>
<g text-anchor="middle" fill="#142c3a" font-size="15" font-family="system-ui,sans-serif"><text x="180" y="40">Host</text><text x="180" y="61">8 s</text><text x="60" y="164">Compute</text><text x="60" y="186">4 s</text><text x="180" y="164">Memory</text><text x="180" y="186">2 s</text><text x="300" y="164">Fabric</text><text x="300" y="186">6 s</text><text x="180" y="283">State</text><text x="180" y="305">2 s</text><text x="180" y="343">Sequential iteration barrier</text></g></svg>'''
    limits = ''.join(f"<li>{_escape(x)}</li>" for x in results['limits'])
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Stateful loop study · synthetic co-design</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6f9;color:#142c3a;font:16px/1.55 system-ui,sans-serif}}main{{max-width:1120px;margin:auto;padding:40px 24px}}h1{{font-size:clamp(2rem,5vw,3.4rem);line-height:1.12;max-width:880px;margin:16px 0}}h2{{font-size:1.45rem;line-height:1.25;margin:0 0 14px}}h3,p{{margin:0}}p{{margin-bottom:10px}}.eyebrow{{font-size:.8rem;font-weight:750;letter-spacing:.12em;text-transform:uppercase;color:#00616a}}.intro{{max-width:800px;color:#415768}}.badge{{display:inline-block;padding:5px 12px;background:#e0f2f1;border-radius:20px;font-weight:650}}.layout{{display:grid;grid-template-columns:1fr 1.35fr;gap:24px;margin:28px 0}}section,.panel{{background:white;border:1px solid #c9d5df;border-radius:16px;padding:24px;min-width:0}}section{{margin-top:24px}}.layout section{{margin:0}}.big{{font-size:2.6rem;font-weight:750}}.muted{{color:#415768}}.dag{{max-width:450px;margin:auto}}svg{{display:block;width:100%;height:auto}}.rowhead{{display:flex;justify-content:space-between;gap:10px;align-items:baseline}}.rowhead h3{{font-size:1rem}}.rowhead strong{{white-space:nowrap}}.comparison{{padding:13px 0;border-bottom:1px solid #dae3e9}}.comparison:last-child{{border:0}}.comparison p{{font-size:.82rem;margin:4px 0 0;color:#415768}}.track{{height:10px;background:#eaf0f4;border-radius:8px;margin:7px 0}}.bar{{height:100%;background:#006d77;border-radius:8px}}.path{{overflow-wrap:anywhere}}table{{width:100%;border-collapse:separate;border-spacing:5px;table-layout:fixed;margin-top:14px;text-align:center}}th{{font-size:.9rem}}td{{padding:12px 2px;border-radius:8px}}td strong,td span{{display:block}}td span{{font-size:.8rem}}.fabric{{background:#d9eeed;color:#004f58}}.compute{{background:#e9e1f7;color:#452a6c}}.memory{{background:#fff0cc;color:#674500}}.other{{background:#edf1f5}}.legend{{display:flex;gap:14px;flex-wrap:wrap;font-size:.9rem}}.legend span{{padding:4px 10px;border-radius:6px}}.downloads{{display:flex;flex-wrap:wrap;gap:12px}}a{{color:#005d70;text-decoration-thickness:2px;text-underline-offset:3px}}a:focus-visible{{outline:3px solid #ad4c00;outline-offset:5px}}.hash{{font-family:ui-monospace,monospace;overflow-wrap:anywhere;font-size:.8rem}}ul{{padding-left:22px}}li{{margin-bottom:8px}}footer{{padding:24px 0;color:#415768;font-size:.85rem}}@media(max-width:700px){{main{{padding:24px 14px}}.layout{{grid-template-columns:1fr;gap:18px}}section,.panel{{padding:18px 14px}}table{{border-spacing:3px}}td{{padding:10px 1px}}td strong{{font-size:.95rem}}th{{font-size:.78rem}}}}
</style></head><body><main>
<header><p class="eyebrow">Scheduler vs more GPUs / offline study</p><h1>Synthetic dependency-only latency lower bound</h1>
<p class="intro">A faster compute stage does not always shorten a stateful AI/SI loop. Explore eight declared interventions with unlimited resources, perfect branch overlap and three sequential iterations.</p>
<span class="badge">Synthetic fixture · no hardware measurements</span></header>
<div class="layout"><section><h2>Where the baseline waits</h2><p><span class="big">{_number(base['total_lower_bound_s'])} s</span> <span class="muted">for 3 iterations</span></p>
<p class="muted">{_number(base['elapsed_lower_bound_s'])} s per iteration. Teal edges mark the critical path.</p><div class="dag">{svg}</div>
<p>State is the declared completion barrier; this diagram does not verify data durability.</p></section>
<section><h2>Matched duration interventions</h2><p class="muted">All values describe the same fixed workload, graph, quality and protocol. Lower is shorter.</p>{''.join(comparisons)}</section></div>
<section><h2>When the critical path switches</h2><p>Rows scale compute duration; columns scale fabric duration. Host, memory and state stay fixed. Each cell shows the total lower bound for 3 iterations and the controlling branch.</p>
<p class="muted">Scenario sensitivity, not an uncertainty interval. Equal-time paths use the API’s lexical tie rule; another zero-slack branch can be equally critical.</p><p><strong>Columns: fabric duration multiplier</strong></p>
<table aria-label="Compute by fabric duration sensitivity in seconds"><thead><tr><th scope="col">Compute ↓</th>{''.join(f'<th scope="col">{m:g}×</th>' for m in MULTIPLIERS)}</tr></thead><tbody>{grid_rows}</tbody></table>
<div class="legend"><span class="fabric">Fabric path</span><span class="compute">Compute path</span><span class="memory">Memory path</span></div></section>
<section><h2>Exact inputs and evidence</h2><p>Read the supplied fixtures, API results and file/source digests. Hashes identify content; they do not authenticate a run.</p><nav class="downloads" aria-label="Study data"><a href="inputs.json">Input fixtures (JSON)</a><a href="results.json">Results (JSON)</a><a href="manifest.json">Source manifest (JSON)</a></nav><p class="hash">Baseline input SHA-256: {_escape(base['input_sha256'])}</p></section>
<section><h2>How to read this study</h2><ul>{limits}</ul></section>
<footer>Research tooling candidate. Independent review and designated technical acceptance remain separate from these calculations. Fixture licence: MIT.</footer></main></body></html>'''


def artifacts() -> dict[str, bytes]:
    inputs, results = study()
    output = {"inputs.json": _json(inputs), "results.json": _json(results),
              "index.html": render(results).encode()}
    manifest = dict(schema="synthetic-loop-study-manifest/v1", python_version=platform.python_version(),
                    python_implementation=platform.python_implementation(), git_sha=None,
                    git_sha_note="Not observed by this offline command; identify the checkout separately.",
                    source_sha256={"capacity/stateful_loop.py": _digest(Path(stateful_loop.__file__).read_bytes()),
                                   "capacity/loop_study.py": _digest(Path(__file__).read_bytes())},
                    files={name: dict(sha256=_digest(data), bytes=len(data)) for name,data in output.items()},
                    limits=LIMITS)
    output["manifest.json"] = _json(manifest)
    return output


def write_study(output: str | Path) -> Path:
    """Create exactly four new files; refuse existing/symlink paths, never delete.

    Descriptor-relative traversal refuses symlinks at every component. A failed
    write retains a partial new directory and raises; retry with a fresh name.
    """
    if not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")):
        raise ValueError("safe output writer requires POSIX directory/no-follow support")
    target = Path(output)
    if not str(output) or '..' in target.parts or target.name in ('', '.'):
        raise ValueError("output must name a fresh directory without '..'")
    target = Path(os.path.abspath(target))
    data = artifacts()  # Finish bounded computation before touching the filesystem.
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    created = False
    try:
        for component in target.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        os.mkdir(target.name, mode=0o700, dir_fd=fd)
        created = True
        child = os.open(target.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        os.close(fd)
        fd = child
        for name, content in data.items():
            file_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(file_fd, 'wb') as handle:
                handle.write(content)
        return target
    except OSError as exc:
        detail = "partial output retained; retry with a fresh name" if created else "no output created; choose a fresh real directory under an existing parent"
        raise OSError(f"cannot write study: {detail}: {exc}") from exc
    finally:
        os.close(fd)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='Fresh output directory; all parents must exist and be real directories')
    args = parser.parse_args(argv)
    try:
        path = write_study(args.output)
    except (OSError, ValueError) as exc:
        print(f"loop-study: {exc}", file=sys.stderr)
        return 2
    print(path / 'index.html')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
