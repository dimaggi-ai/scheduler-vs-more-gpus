"""Simulator invariant tests. Run: python3 test_sim.py (takes a few seconds)."""

import math

from simulator import (
    Config,
    Simulation,
    expected_gpu_hours_per_job,
    SIZE_PROBS,
    MEAN_DURATION_H,
)


def test_size_distribution_meta_shaped():
    """Job mix must reproduce Meta's shape: most jobs small, most GPU-time large."""
    assert math.isclose(sum(p for _, p in SIZE_PROBS), 1.0, abs_tol=1e-9)
    total = expected_gpu_hours_per_job()
    small_time = sum(p * s * MEAN_DURATION_H[s] for s, p in SIZE_PROBS if s < 8)
    big_time = sum(p * s * MEAN_DURATION_H[s] for s, p in SIZE_PROBS if s >= 256)
    small_jobs = sum(p for s, p in SIZE_PROBS if s < 8)
    assert small_jobs > 0.6            # most jobs are tiny...
    assert small_time / total < 0.10   # ...but under 10% of GPU-time (arXiv:2410.21680)
    assert big_time / total > 0.50     # 256+ jobs dominate GPU-time (arXiv:2410.21680)


def test_determinism():
    a = Simulation(Config(horizon_days=3, seed=7), "intent-closed-loop").run()
    b = Simulation(Config(horizon_days=3, seed=7), "intent-closed-loop").run()
    assert a == b


def test_seed_changes_results():
    a = Simulation(Config(horizon_days=3, seed=7), "rigid-fifo").run()
    b = Simulation(Config(horizon_days=3, seed=8), "rigid-fifo").run()
    assert a != b


def test_accounting_conservation():
    """envelope = productive + all stranded components, per policy/scenario."""
    for policy in ("rigid-fifo", "tiered-preemption", "intent-closed-loop"):
        for kw in ({}, {"power_envelope": True, "failures": True, "inf_surges": True}):
            r = Simulation(Config(horizon_days=4, seed=11, **kw), policy).run()
            total = (
                r["productive_gpu_h"]
                + r["stranded_idle_gpu_h"]
                + r["stranded_reservation_gpu_h"]
                + r["stranded_train_overhead_gpu_h"]
            )
            # identity is exact pre-rounding; reported values are rounded to
            # 0.1 GPU-h, so allow the worst-case sum of rounding errors
            assert math.isclose(total, r["envelope_gpu_h"], abs_tol=0.5), (policy, kw)
            assert r["envelope_gpu_h"] <= r["nominal_gpu_h"] + 1e-6
            assert 0.0 <= r["slo_attainment"] <= 1.0
            assert 0.0 <= r["train_ettr"] <= 1.0


def test_rigid_policy_never_preempts_gracefully():
    r = Simulation(
        Config(horizon_days=4, seed=5, power_envelope=True), "rigid-fifo"
    ).run()
    assert r["preemptions"] == 0
    assert r["resizes"] == 0
    assert r["emergency_kills"] > 0        # power shed must kill something
    assert r["work_lost_gpu_h"] > 0


def test_tiered_policy_prefers_graceful():
    r = Simulation(
        Config(horizon_days=4, seed=5, power_envelope=True), "tiered-preemption"
    ).run()
    assert r["preemptions"] > 0
    assert r["emergency_kills"] == 0       # no failures configured -> none


def test_intent_only_policy_resizes():
    for policy, expect in (
        ("rigid-fifo", 0),
        ("tiered-preemption", 0),
    ):
        r = Simulation(Config(horizon_days=4, seed=5, power_envelope=True), policy).run()
        assert r["resizes"] == expect, policy
    r = Simulation(
        Config(horizon_days=4, seed=5, power_envelope=True), "intent-closed-loop"
    ).run()
    assert r["resizes"] > 0


def test_failures_cause_lost_work_everywhere():
    for policy in ("rigid-fifo", "tiered-preemption", "intent-closed-loop"):
        r = Simulation(Config(horizon_days=6, seed=3, failures=True), policy).run()
        assert r["emergency_kills"] > 0, policy
        assert r["work_lost_gpu_h"] > 0, policy


def test_intent_recovers_reservation_waste():
    """Demand-tracking must waste far less reservation than peak-provisioning."""
    base = dict(horizon_days=6, seed=13)
    rigid = Simulation(Config(**base), "rigid-fifo").run()
    intent = Simulation(Config(**base), "intent-closed-loop").run()
    assert intent["stranded_reservation_gpu_h"] < 0.5 * rigid["stranded_reservation_gpu_h"]


def test_all_policies_same_offered_workload():
    base = dict(horizon_days=3, seed=21)
    subs = {
        p: Simulation(Config(**base), p).run()["jobs_submitted"]
        for p in ("rigid-fifo", "tiered-preemption", "intent-closed-loop")
    }
    assert len(set(subs.values())) == 1, subs


def test_identical_event_timeline_across_policies():
    """Failure/surge timing must be policy-independent by construction:
    the envelope (cap after failures and power) must match exactly."""
    base = dict(horizon_days=6, seed=17, failures=True, power_envelope=True, inf_surges=True)
    envs = {
        p: Simulation(Config(**base), p).run()["envelope_gpu_h"]
        for p in ("rigid-fifo", "tiered-preemption", "intent-closed-loop")
    }
    assert len(set(envs.values())) == 1, envs


if __name__ == "__main__":
    for fn in sorted(k for k in dir() if k.startswith("test_")):
        globals()[fn]()
        print(f"ok {fn}")
    print("all simulator tests passed")
