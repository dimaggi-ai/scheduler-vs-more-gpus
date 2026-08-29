#!/usr/bin/env python3
"""Run the full experiment grid and produce results + figures.

Usage: python3 run.py [--days 30] [--seeds 42 43 44] [--out ../results] [--figdir ../figures]
"""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from simulator import Config, Simulation, DT_H, power_cap_fraction, inference_demand

POLICIES = ["rigid-fifo", "tiered-preemption", "intent-closed-loop"]
POLICY_LABEL = {
    "rigid-fifo": "Rigid FIFO\n(static quota)",
    "tiered-preemption": "Tiered preemption\n(Borg-style)",
    "intent-closed-loop": "Intent closed-loop\n(carrier-style)",
}
SCENARIOS = {
    "S1-steady": {},
    "S2-power": {"power_envelope": True},
    "S3-failures": {"failures": True},
    "S4-full": {"power_envelope": True, "failures": True, "inf_surges": True},
}
COLORS = {"rigid-fifo": "#c0504d", "tiered-preemption": "#4f81bd", "intent-closed-loop": "#4e9a06"}


def run_grid(days: int, seeds: list[int]) -> list[dict]:
    rows = []
    for scen, kw in SCENARIOS.items():
        for policy in POLICIES:
            for seed in seeds:
                r = Simulation(Config(horizon_days=days, seed=seed, **kw), policy).run()
                r["scenario"] = scen
                rows.append(r)
                print(
                    f"{scen:12s} {policy:20s} seed={seed} "
                    f"realization={r['capacity_realization']:.3f} "
                    f"slo={r['slo_attainment']:.3f} stranded={r['stranded_gpu_h']:,.0f}"
                )
    return rows


def aggregate(rows: list[dict]) -> dict[tuple[str, str], dict]:
    agg: dict[tuple[str, str], dict] = {}
    for scen in SCENARIOS:
        for policy in POLICIES:
            sel = [r for r in rows if r["scenario"] == scen and r["policy"] == policy]
            out = {}
            for key in sel[0]:
                if isinstance(sel[0][key], (int, float)) and key != "seed":
                    vals = [r[key] for r in sel]
                    out[key] = statistics.mean(vals)
                    out[key + "_sd"] = statistics.stdev(vals) if len(vals) > 1 else 0.0
            agg[(scen, policy)] = out
    return agg


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_summary(agg: dict, path: Path, days: int, seeds: list[int]) -> None:
    lines = [
        "# Simulation results summary",
        "",
        f"1,024-GPU cluster, {days} days, seeds {seeds} (values are means across seeds).",
        "Full per-run data in results.csv. Reproduce: `python3 sim/run.py`.",
        "",
        "| Scenario | Policy | Capacity realization | Inference SLO | Train ETTR | "
        "Stranded GPU-h | ...idle | ...reservation | ...overhead+lost | Preempts | Kills | Resizes | Mean wait h |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for (scen, policy), a in agg.items():
        lines.append(
            f"| {scen} | {policy} | {a['capacity_realization']:.3f} | "
            f"{a['slo_attainment']:.3f} | {a['train_ettr']:.3f} | "
            f"{a['stranded_gpu_h']:,.0f} | {a['stranded_idle_gpu_h']:,.0f} | "
            f"{a['stranded_reservation_gpu_h']:,.0f} | "
            f"{a['stranded_train_overhead_gpu_h']:,.0f} | "
            f"{a['preemptions']:.0f} | {a['emergency_kills']:.0f} | "
            f"{a['resizes']:.0f} | {a['mean_wait_h']:.1f} |"
        )
    path.write_text("\n".join(lines) + "\n")


def fig_stranded_breakdown(agg: dict, outdir: Path) -> None:
    scen = "S4-full"
    parts = [
        ("stranded_idle_gpu_h", "Idle (queue/fragmentation)", "#bbbbbb"),
        ("stranded_reservation_gpu_h", "Reservation waste (inference over-provision)", "#f4a582"),
        ("stranded_train_overhead_gpu_h", "Overhead + lost work (training)", "#92c5de"),
    ]
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(POLICIES))
    bottom = np.zeros(len(POLICIES))
    for key, label, color in parts:
        vals = np.array([agg[(scen, p)][key] for p in POLICIES]) / 1000.0
        ax.bar(x, vals, bottom=bottom, label=label, color=color, width=0.6)
        bottom += vals
    for i, p in enumerate(POLICIES):
        real = agg[(scen, p)]["capacity_realization"]
        ax.text(i, bottom[i] + 2, f"realization\n{real:.1%}", ha="center", fontsize=9)
    ax.set_ylim(0, bottom.max() * 1.18)   # headroom for the labels
    ax.set_xticks(x, [POLICY_LABEL[p] for p in POLICIES])
    ax.set_ylabel("Stranded capacity, thousand GPU-hours / 30 days")
    ax.set_title(
        "Where a 1,024-GPU month goes missing — scenario S4\n"
        "(power envelope + failures + inference surges)"
    )
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(outdir / "stranded_breakdown.png", dpi=150)
    plt.close(fig)


def fig_power_day(days: int, outdir: Path) -> None:
    """One representative day of S2: envelope vs productive use, per policy."""
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True, sharey=True)
    day = min(10, days - 1)
    for ax, policy in zip(axes, POLICIES):
        # instrumented re-run: duplicate of Simulation.run() with tracing of a
        # single day's cap/alloc series (keep in sync with simulator.py)
        trace = {"cap": [], "alloc": [], "inf": []}
        cfg2 = Config(horizon_days=days, seed=42, power_envelope=True)
        sim2 = Simulation(cfg2, policy)
        import simulator as S

        for t in range(cfg2.steps):
            demand = inference_demand(cfg2, t, 0.0)
            cap = min(sim2.gpus_up(t), int(cfg2.gpus * power_cap_fraction(cfg2, t)))
            if sim2.policy == "intent-closed-loop" and t % 3 == 0:
                sim2._intent_controller(cap, t, demand)
            if sim2.policy != "intent-closed-loop":
                sim2.inf_alloc = float(min(sim2.inf_reservation, cap))
            sim2._enforce_cap(cap, t)
            while (
                sim2.next_arrival_idx < len(sim2.jobs)
                and sim2.jobs[sim2.next_arrival_idx].submit_step <= t
            ):
                sim2.queue.append(sim2.jobs[sim2.next_arrival_idx])
                sim2.next_arrival_idx += 1
            sim2._admit(cap, t)
            if sim2.policy == "intent-closed-loop" and t % 3 == 0:
                sim2._intent_restore(cap, t)
            done = []
            for j in sim2.running:
                if j.overhead_steps > 0:
                    j.overhead_steps -= 1
                elif j.steps_since_ckpt >= S.CKPT_INTERVAL_STEPS:
                    j.steps_since_ckpt = 0
                    j.progress_since_ckpt = 0.0
                else:
                    added = j.alloc * DT_H
                    j.progress += added
                    j.progress_since_ckpt += added
                    j.steps_since_ckpt += 1
                if j.progress >= j.work:
                    j.status = "DONE"
                    done.append(j)
            for j in done:
                sim2.running.remove(j)
            if day * S.STEPS_PER_DAY <= t < (day + 1) * S.STEPS_PER_DAY:
                trace["cap"].append(cap)
                trace["alloc"].append(sim2.train_alloc() + sim2.inf_alloc)
                trace["inf"].append(min(sim2.inf_alloc, demand))

        hours = np.arange(len(trace["cap"])) * DT_H
        ax.plot(hours, trace["cap"], color="black", lw=1.5, label="available (power envelope)")
        ax.plot(hours, trace["alloc"], color=COLORS[policy], lw=1.2, label="allocated")
        ax.fill_between(hours, 0, trace["inf"], color="#f4a582", alpha=0.5,
                        label="inference (productive)")
        ax.set_ylabel("GPUs")
        ax.set_title(POLICY_LABEL[policy].replace("\n", " "), fontsize=10)
        ax.legend(loc="lower left", fontsize=7)
    axes[-1].set_xlabel(f"Hour of day {day} — scenario S2 (daily 4 h contraction to 75%)")
    fig.suptitle("How each policy rides a power envelope", y=0.995)
    fig.tight_layout()
    fig.savefig(outdir / "power_envelope_day.png", dpi=150)
    plt.close(fig)


def fig_frontier(agg: dict, outdir: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 5))
    markers = {"S1-steady": "o", "S2-power": "s", "S3-failures": "^", "S4-full": "D"}
    for scen in SCENARIOS:
        for p in POLICIES:
            a = agg[(scen, p)]
            ax.scatter(
                a["slo_attainment"], a["capacity_realization"],
                c=COLORS[p], marker=markers[scen], s=70,
                label=f"{scen} / {p}" if scen == "S1-steady" else None,
            )
    for p in POLICIES:
        pts = sorted(
            (agg[(s, p)]["slo_attainment"], agg[(s, p)]["capacity_realization"])
            for s in SCENARIOS
        )
        ax.plot([x for x, _ in pts], [y for _, y in pts], c=COLORS[p], alpha=0.3, lw=1)
    ax.set_xlabel("Inference SLO attainment")
    ax.set_ylabel("Capacity realization (productive / available)")
    ax.set_title("SLO vs capacity realization across scenarios\n"
                 "(marker = scenario: o steady, s power, ^ failures, D full)")
    handles = [plt.Line2D([], [], color=COLORS[p], marker="o", ls="", label=p) for p in POLICIES]
    ax.legend(handles=handles, loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(outdir / "slo_vs_realization.png", dpi=150)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    ap.add_argument("--out", default="../results")
    ap.add_argument("--figdir", default="../figures")
    args = ap.parse_args()

    outdir = Path(__file__).resolve().parent / args.out
    outdir.mkdir(parents=True, exist_ok=True)
    figdir = (Path(__file__).resolve().parent / args.figdir).resolve()
    figdir.mkdir(parents=True, exist_ok=True)

    rows = run_grid(args.days, args.seeds)
    write_csv(rows, outdir / "results.csv")
    agg = aggregate(rows)
    write_summary(agg, outdir / "summary.md", args.days, args.seeds)
    fig_stranded_breakdown(agg, figdir)
    fig_power_day(args.days, figdir)
    fig_frontier(agg, figdir)
    print(f"\nwrote {outdir}/results.csv, summary.md and 3 figures to {figdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
