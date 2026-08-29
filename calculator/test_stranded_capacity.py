"""Tests for the stranded-capacity calculator. Run: python3 test_stranded_capacity.py"""

import math

from stranded_capacity import PRESETS, Scenario, compute


def test_conservation():
    """Losses plus usable must equal nominal, for every preset."""
    for name, s in PRESETS.items():
        r = compute(s)
        total = r.usable_gpu_hours + r.loss_scheduler + r.loss_allocation + r.loss_productivity
        assert math.isclose(total, r.nominal_gpu_hours, rel_tol=1e-9), name


def test_no_loss_identity():
    s = Scenario(name="ideal", description="", gpus=100, window_hours=100.0)
    r = compute(s)
    assert math.isclose(r.usable_gpu_hours, 10_000.0)
    assert r.stranded_gpu_hours == 0.0


def test_hard_outage_only():
    s = Scenario(name="o", description="", gpus=1000, window_hours=720.0, hard_outage_hours=3.7)
    r = compute(s)
    assert math.isclose(r.loss_scheduler, 1000 * 3.7, rel_tol=1e-9)
    assert r.loss_allocation == 0.0 and r.loss_productivity == 0.0


def test_degradation_weighting():
    s = Scenario(
        name="d", description="", gpus=100, window_hours=100.0,
        degraded_hours=10.0, degradation_weight=0.5,
    )
    r = compute(s)
    # 10 h at 50% weight = 5 lost hours of availability on 100 GPUs.
    assert math.isclose(r.loss_scheduler, 500.0, rel_tol=1e-9)


def test_layer_ordering():
    """Attribution is sequential: allocation losses apply to available hours only."""
    s = Scenario(
        name="s", description="", gpus=100, window_hours=100.0,
        hard_outage_hours=50.0, allocation_efficiency=0.5, productive_ratio=0.5,
    )
    r = compute(s)
    assert math.isclose(r.loss_scheduler, 5000.0)
    assert math.isclose(r.loss_allocation, 2500.0)
    assert math.isclose(r.loss_productivity, 1250.0)
    assert math.isclose(r.usable_gpu_hours, 1250.0)


def test_alibaba_delta_is_large():
    """The before/after allocation delta on 155k GPUs must be ~28M GPU-h/month."""
    before = compute(PRESETS["alibaba-allocation-before"])
    after = compute(PRESETS["alibaba-allocation-after"])
    delta = before.loss_allocation - after.loss_allocation
    assert 27e6 < delta < 29e6, delta


def test_invalid_inputs_raise():
    for bad in (
        Scenario(name="x", description="", gpus=10, window_hours=1.0, hard_outage_hours=2.0),
        Scenario(name="y", description="", gpus=10, window_hours=10.0, allocation_efficiency=1.5),
    ):
        try:
            compute(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad.name} should have raised")


if __name__ == "__main__":
    for fn in sorted(k for k in dir() if k.startswith("test_")):
        globals()[fn]()
        print(f"ok {fn}")
    print("all calculator tests passed")
