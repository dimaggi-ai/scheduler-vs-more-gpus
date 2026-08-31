"""Validation registry tests. Run: python3 test_validation.py (~2 min).

points() is lru_cached, so the ~30 simulations behind the registry run
once for the whole test session.
"""

from validation import points, validate


_POINTS = points()


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


if __name__ == "__main__":
    for fn in sorted(k for k in dir() if k.startswith("test_")):
        globals()[fn]()
        print(f"ok {fn}")
    print("all validation tests passed")
