#!/usr/bin/env python3
"""Keep published numerical blocks tied to the committed 36-run experiment.

After regenerating sim/run.py outputs, run --write and review the prose outside
these blocks. CI uses --check --verify-run to catch both missed regeneration and
paper/README drift. Figures are rendered by sim/run.py; PNG byte identity is not
promised across Matplotlib/font versions.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("S1-steady", "S2-power", "S3-failures", "S4-full")
POLICIES = ("rigid-fifo", "tiered-preemption", "intent-closed-loop")
SEEDS = (42, 43, 44)
METRICS = ("nominal_gpu_h", "productive_gpu_h", "stranded_gpu_h",
           "stranded_reservation_gpu_h", "capacity_realization", "slo_attainment",
           "train_ettr", "preemptions", "emergency_kills", "resizes", "mean_wait_h")
DOCUMENT_BLOCKS = {
    "README.md": ("headline", "s4-table", "readme-findings"),
    "paper/paper.md": ("headline", "s4-table", "scenario-gains", "reservation", "tradeoffs", "tiers"),
}


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        raw = list(csv.DictReader(handle))
    expected = {(s, p, seed) for s in SCENARIOS for p in POLICIES for seed in SEEDS}
    rows, seen = [], set()
    for row in raw:
        key = (row["scenario"], row["policy"], int(row["seed"]))
        if key in seen or key not in expected:
            raise ValueError(f"unexpected/duplicate experiment row: {key}")
        seen.add(key)
        converted = {**row, **{k: float(row[k]) for k in METRICS}}
        if any(not math.isfinite(converted[k]) or converted[k] < 0 for k in METRICS):
            raise ValueError(f"non-finite/negative metric: {key}")
        if converted["nominal_gpu_h"] != 1024 * 30 * 24:
            raise ValueError("publication blocks require the 1,024-GPU, 30-day experiment")
        if any(converted[k] > 1 for k in ("capacity_realization", "slo_attainment", "train_ettr")):
            raise ValueError(f"invalid fraction: {key}")
        rows.append(converted)
    if seen != expected:
        raise ValueError(f"incomplete experiment grid: missing {sorted(expected - seen)}")
    return rows


def aggregate(rows: list[dict]) -> dict:
    return {(s, p): {k: statistics.mean(r[k] for r in rows if r["scenario"] == s and r["policy"] == p)
                     for k in METRICS}
            for s in SCENARIOS for p in POLICIES}


def blocks(agg: dict) -> dict[str, str]:
    a, b, c = (agg[("S4-full", p)] for p in POLICIES)
    gap = c["productive_gpu_h"] - a["productive_gpu_h"]
    gains = [100 * (agg[(s, POLICIES[2])]["capacity_realization"] -
                    agg[(s, POLICIES[0])]["capacity_realization"]) for s in SCENARIOS]
    headline = (
        "**Corrected experiment (offered-load correction: 2026-09-10):** on a simulated "
        "1,024-GPU cluster over 30 days, with a public-research-informed synthetic workload, "
        "power constraints, failures and demand surges (S4), the intent policy realizes "
        f"**{c['capacity_realization']:.1%}** of the available envelope versus "
        f"**{a['capacity_realization']:.1%}** for rigid FIFO. The difference is "
        f"**~{gap:,.0f} modeled productive GPU-hours (~{gap / 720:.1f} continuously productive GPU equivalents)**. "
        "These are modeled output differences, not GPUs purchased or production savings. "
        "The comparison bundles reservation tracking and elasticity; it does not isolate their causal contributions."
    )
    rows = [
        "| Scenario S4 (power + failures + surges) | rigid-fifo | tiered-preemption | intent-closed-loop |",
        "|---|---|---|---|",
    ]
    for label, key, spec in (
        ("Capacity realization", "capacity_realization", ".3f"),
        ("Inference SLO attainment", "slo_attainment", ".3f"),
        ("Training productive / allocated GPU-h (legacy `train_ettr` field)", "train_ettr", ".3f"),
        ("Stranded GPU-h / month", "stranded_gpu_h", ",.0f"),
        ("— of which reservation waste", "stranded_reservation_gpu_h", ",.0f"),
    ):
        rows.append("| " + label + " | " + " | ".join(format(x[key], spec) for x in (a, b, c)) + " |")
    rows.append("| Kills / preemptions / resizes | " + " | ".join(
        " / ".join(f"{x[k]:.0f}" for k in ("emergency_kills", "preemptions", "resizes")) for x in (a, b, c)) + " |")
    rows.append("| Mean started-job wait (h) | " + " | ".join(f"{x['mean_wait_h']:.1f}" for x in (a, b, c)) + " |")
    return {
        "headline": headline,
        "readme-findings": (
            f"1. **Scenario means:** intent exceeds rigid FIFO by {min(gains):.1f}–{max(gains):.1f} percentage points. "
            f"S4 reservation waste is lower by ~{a['stranded_reservation_gpu_h'] - c['stranded_reservation_gpu_h']:,.0f} GPU-hours; "
            "that ledger difference does not isolate the causal contributions of tracking and elasticity.\n"
            f"2. **Aggregate inference attainment:** {c['slo_attainment']:.3f} for intent versus {a['slo_attainment']:.3f} for the static policies. "
            "The modeled surges exceed the static reservation by construction; this is not request-level latency validation.\n"
            f"3. **Churn and training:** intent performs ~{c['resizes']:,.0f} resizes and ~{c['preemptions']:,.0f} graceful preemptions "
            f"versus ~{b['preemptions']:,.0f} preemptions for tiered. Its training productive/allocated ratio is {c['train_ettr']:.3f} "
            f"versus {a['train_ettr']:.3f}/{b['train_ettr']:.3f}; mean started-job wait is {c['mean_wait_h']:.1f} h "
            f"versus {a['mean_wait_h']:.1f}/{b['mean_wait_h']:.1f} h. Never-started jobs are excluded from that wait metric.\n"
            f"4. **Tiered preemption:** emergency kills fall from ~{a['emergency_kills']:.0f} to {b['emergency_kills']:.0f} "
            f"while realization moves from {a['capacity_realization']:.3f} to {b['capacity_realization']:.3f}; fixed inference reservations remain.\n"
            "5. **Scope:** these conditional model results do not establish a production guarantee, universal policy ordering or hardware purchase avoided."
        ),
        "s4-table": "\n".join(rows),
        "scenario-gains": (
            f"**(1) Scenario means.** Intent exceeds rigid FIFO by {gains[0]:.1f} percentage points "
            f"in steady state, {gains[1]:.1f} under power contraction, {gains[2]:.1f} under failures, "
            f"and {gains[3]:.1f} in S4 (differences of the three-seed means before display rounding). "
            "The ordering holds across these four scenario means, including S1 without failures, contraction or surges. "
            "This is a result for the stated synthetic workload, not a universal policy ranking."
        ),
        "reservation": (
            "**(2) Reservation accounting.** S4 reservation waste falls from "
            f"{a['stranded_reservation_gpu_h']:,.0f} to {c['stranded_reservation_gpu_h']:,.0f} GPU-hours; "
            f"the difference before display rounding is {a['stranded_reservation_gpu_h'] - c['stranded_reservation_gpu_h']:,.1f} GPU-hours. "
            "This component of the ledger does not by itself identify a causal contribution: the policies also differ in elasticity and admission. "
            "The separate `sim/sensitivity.py` factorial experiment varies demand tracking and elasticity within the intent mechanism; "
            "those outputs remain conditional simulations."
        ),
        "tradeoffs": (
            f"**(4) Costs and service outcomes.** In S4 the intent policy performs {c['resizes']:,.0f} resizes and "
            f"{c['preemptions']:,.0f} graceful preemptions, versus {b['preemptions']:,.0f} preemptions for tiered. "
            f"Its training productive/allocated ratio is {c['train_ettr']:.3f} versus "
            f"{a['train_ettr']:.3f}/{b['train_ettr']:.3f}; mean started-job wait is {c['mean_wait_h']:.1f} h "
            f"versus {a['mean_wait_h']:.1f}/{b['mean_wait_h']:.1f} h. "
            "The wait metric excludes jobs that never started. These tradeoffs require workload-specific judgment; "
            "the experiment does not establish that additional churn is always worth its cost."
        ),
        "tiers": (
            f"**(5) Priority tiers in this workload.** Graceful preemption reduces S4 emergency kills from "
            f"{a['emergency_kills']:.0f} to {b['emergency_kills']:.0f}, while capacity realization changes from "
            f"{a['capacity_realization']:.3f} to {b['capacity_realization']:.3f}. "
            "Fixed inference reservations remain unchanged. The modeled failures affect all policies; "
            "this comparison does not establish that production failure losses are negligible."
        ),
    }


def replace_block(text: str, name: str, value: str) -> str:
    begin, end = f"<!-- research:{name}:begin -->", f"<!-- research:{name}:end -->"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError(f"exactly one complete {name!r} block required")
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(text):
        raise ValueError(f"reversed {name!r} block markers")
    return pattern.sub(lambda _: f"{begin}\n{value}\n{end}", text)


def evidence_errors(root: Path, agg: dict) -> list[str]:
    data = json.loads((root / "evidence.json").read_text())
    results = data["results"]
    a, b, c = (agg[("S4-full", p)] for p in POLICIES)
    gap = c["productive_gpu_h"] - a["productive_gpu_h"]
    expected = {
        "S4 rigid realization": round(a["capacity_realization"], 3),
        "S4 tiered realization": round(b["capacity_realization"], 3),
        "S4 intent realization": round(c["capacity_realization"], 3),
        "S4 productive difference": round(gap),
        "S4 continuous GPU equivalent": round(gap / 720, 1),
    }
    errors = []
    for name, value in expected.items():
        matches = [r for r in results if r["name"] == name]
        if len(matches) != 1 or matches[0].get("value") != value:
            errors.append(f"evidence.json: {name} must be {value!r} from unrounded aggregates")
    return errors


def synchronize(root: Path, *, write: bool = False) -> list[str]:
    agg = aggregate(load_rows(root / "results/results.csv"))
    rendered = blocks(agg)
    errors = []
    for relative, names in DOCUMENT_BLOCKS.items():
        path = root / relative
        original = updated = path.read_text()
        for name in names:
            updated = replace_block(updated, name, rendered[name])
        if updated != original:
            if write:
                path.write_text(updated)
            else:
                errors.append(f"{relative}: generated research claims are stale; run python tools/sync_research.py --write")
    # Provenance is reviewed separately, never silently rewrite its metadata.
    return errors + evidence_errors(root, agg)


def verify_run(root: Path) -> list[str]:
    with tempfile.TemporaryDirectory(prefix=".research-reproduction-", dir=root) as temporary:
        directory = Path(temporary)
        completed = subprocess.run(
            [sys.executable, str(root / "sim/run.py"), "--out", str(directory / "results"),
             "--figdir", str(directory / "figures")], cwd=root, text=True, capture_output=True,
            env={**os.environ, "MPLCONFIGDIR": str(directory / "mpl-cache"), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if completed.returncode:
            return [f"simulator regeneration failed:\n{completed.stdout}\n{completed.stderr}"]
        return [f"{relative}: committed output differs from the current simulator"
                for relative in ("results/results.csv", "results/summary.md")
                if (root / relative).read_bytes() != (directory / relative).read_bytes()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="refresh marked publication blocks from committed CSV")
    mode.add_argument("--check", action="store_true", help="check without changing files (default)")
    parser.add_argument("--verify-run", action="store_true", help="also regenerate CSV/summary in temporary repository storage")
    args = parser.parse_args()
    try:
        errors = synchronize(ROOT, write=args.write)
        if args.verify_run:
            errors.extend(verify_run(ROOT))
    except (ValueError, KeyError, OSError) as error:
        errors = [str(error)]
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print("Publication numerical blocks and evidence agree with the complete 36-run CSV." +
              (" Current simulator reproduces CSV/summary byte-for-byte." if args.verify_run else ""))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
