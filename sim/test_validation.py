"""Validation registry tests. Run: python3 test_validation.py (~10 s).

Two halves, and the second is the one that matters:

  1. the registry reproduces, its kinds are labeled honestly, and its
     tolerances are not wide enough to swallow the values they bracket;
  2. the model is broken on purpose, one mechanism at a time, and the
     registry is required to go RED. A registry nobody has ever seen fail
     is not evidence that the model is right — it is evidence that the
     registry is easy. Every mutation below deletes something the study
     leans on, and names the point that must notice.

The mutations run at a reduced horizon (4 days, 2 seeds) so the suite stays
fast. That reduction is itself a risk — a registry can go green simply
because a short run is too quiet to fail — so the first mutation test is a
control proving the reduced configuration is green *unmutated*.
"""

import contextlib
import unittest.mock as mock

import simulator
import validation
from validation import DECLINED, points, validate

FAST_HORIZON, FAST_SEEDS = 4, (0, 1)

_POINTS = points()


# --------------------------------------------------------------- the registry

def test_every_point_reproduces():
    for p in _POINTS:
        assert p.ok, (
            f"{p.name}: expected {p.expected} +/- {p.tolerance} {p.ref}, "
            f"model gives {p.actual:.4f}"
        )


def test_all_three_kinds_present():
    kinds = {p.kind for p in _POINTS}
    assert kinds == {"calibrated", "emergent", "sanity"}, kinds


def test_evidence_points_cite_their_sources():
    # sanity points deliberately cite nothing — they claim no evidence
    for p in _POINTS:
        if p.kind in ("calibrated", "emergent"):
            assert p.ref.startswith("["), p.name
        else:
            assert p.ref == "-", p.name


def test_validate_reports_all_ok():
    pts, ok = validate()
    assert ok
    assert len(pts) == len(_POINTS)


def test_no_tolerance_swamps_the_value_it_brackets():
    # A band wide enough to admit any plausible model is not a check.
    for p in _POINTS:
        if p.expected:
            assert p.tolerance <= 0.20 * abs(p.expected), (
                f"{p.name}: tolerance {p.tolerance} is more than 20% of "
                f"{p.expected}"
            )


def test_declined_list_is_populated_and_explained():
    assert len(DECLINED) >= 5, "the DECLINED list has gone thin"
    for name, why in DECLINED:
        assert name and why, name
        assert len(why) > 40, f"{name}: 'why' is too short to be honest"


# ------------------------------------------------- breaking the model on purpose

def _registry(*mutations):
    """Re-evaluate the registry at the reduced horizon with (module, attr,
    value) triples applied. The cache is cleared on both sides so a mutated
    result can never be served to a later test, or a clean one to this test."""
    with contextlib.ExitStack() as stack:
        for module, attr, value in mutations:
            stack.enter_context(mock.patch.object(module, attr, value))
        validation.points.cache_clear()
        try:
            return {p.name for p in validation.points(FAST_HORIZON, FAST_SEEDS)
                    if not p.ok}
        finally:
            validation.points.cache_clear()


def _config_with(**overrides):
    """A drop-in for validation.Config that forces a field."""
    def factory(**kw):
        return simulator.Config(**{**kw, **overrides})
    return factory


def test_the_reduced_horizon_is_green_unmutated():
    # Control for the control: every mutation below must fail against a
    # configuration that passes when nothing is broken.
    assert _registry() == set(), "the reduced-horizon control is not green"


def test_an_intent_policy_that_is_secretly_rigid_is_noticed():
    red = _registry((validation, "INTENT", validation.RIGID))
    assert "scheduler-work-reclaims-capacity" in red, red


def test_a_tiered_policy_that_kills_instead_of_checkpointing_is_noticed():
    red = _registry((validation, "TIERED", validation.RIGID))
    assert "emergency-kills-lose-work" in red, red


def test_a_flattened_job_size_distribution_is_noticed():
    flat = [(s, 1.0 / len(simulator.SIZE_PROBS)) for s, _ in simulator.SIZE_PROBS]
    red = _registry((simulator, "SIZE_PROBS", flat),
                    (validation, "SIZE_PROBS", flat))
    assert "meta-most-jobs-small" in red, red


def test_a_wrong_rsc1_failure_rate_is_noticed():
    red = _registry((validation, "Config",
                     _config_with(failures_per_1000_node_days=13.0)))
    assert "rsc1-failure-rate" in red, red


def test_a_broken_checkpoint_interval_is_noticed():
    # Checkpoint every step: the overhead step then eats most of the run and
    # training ETTR falls out of Meta's band.
    red = _registry((simulator, "CKPT_INTERVAL_STEPS", 1))
    assert "meta-ettr-band" in red, red


def test_comparing_the_two_offered_loads_at_the_same_load_is_noticed():
    red = _registry((validation, "LOAD_LO", validation.LOAD_HI))
    assert "queueing-grows-with-load" in red, red


def test_comparing_small_jobs_against_themselves_is_noticed():
    red = _registry((validation, "LARGE_RANGE", validation.SMALL_RANGE))
    assert "philly-large-jobs-wait-longer" in red, red


def test_peak_provisioning_both_policies_is_noticed():
    # If the intent policy stops tracking demand, the reservation ratio
    # collapses toward 1.0 and the sanity point must refuse it.
    red = _registry((validation, "INTENT", validation.TIERED))
    assert "demand-tracking-cuts-reservation-waste" in red, red


if __name__ == "__main__":
    for fn in sorted(k for k in dir() if k.startswith("test_")):
        globals()[fn]()
        print(f"ok {fn}")
    print("all validation tests passed")
