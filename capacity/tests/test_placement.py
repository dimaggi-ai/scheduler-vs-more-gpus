import pytest
from slicepacker import Fabric, Topology, SliceRect, Request
from spancontract import SpanEnvelope, ScaleOut
from spancontract import SliceRect as SpanRect

from capacity.placement import placement_preview, admission_preview


def test_sequential_packing_does_not_mutate_input():
    fabric = Fabric(Topology((4, 4), (True, True)))
    result = placement_preview(fabric, [Request("a", 12), Request("b", 12)])
    assert [r["status"] for r in result["requests"]] == ["placeable", "unplaceable"]
    assert result["free_chips_after"] == 4
    assert fabric.allocations == {}
    assert result["execution_authorized"] is False


def test_unhealthy_and_fragmented_space_is_not_free_capacity():
    fabric = Fabric(Topology((4, 4), (True, True)), unhealthy={(1, j) for j in range(4)})
    result = placement_preview(fabric, [Request("a", 12, shape=(3, 4))])
    assert result["free_chips_before"] == 12
    assert result["requests"][0]["status"] == "unplaceable"


@pytest.mark.parametrize("requests", [[Request("a", 4), Request("a", 4)],
                                     [Request("a", 4, tenant="org")],
                                     [Request("a", 4, shape=(4,))]])
def test_ambiguous_placement_refused(requests):
    with pytest.raises(ValueError):
        placement_preview(Fabric(Topology((4, 4), (True, True))), requests)


def test_existing_job_not_overwritten():
    fabric = Fabric(Topology((4, 4), (True, True)), {"a": SliceRect((0, 0), (2, 2))})
    with pytest.raises(ValueError, match="already allocated"):
        placement_preview(fabric, [Request("a", 4)])


def envelope(**changes):
    env = SpanEnvelope(scale_out=ScaleOut.OCS_STITCHED, span_mode="span",
                       span_rtt_us=400, span_bw_gbps=800, span_failure_domain="metro",
                       slice_rect=SpanRect("hall-a", (0, 0, 0), (8, 8, 8)),
                       stitch_id="ab", stitch_api="offline-fixture", topology_hash="a" * 64,
                       measured_il_db=10, measured_ber=1e-12, checkpoint_window_s=120,
                       collective_window_s=300, ingest_budget_GBps=40,
                       thermal_headroom_k=3, ride_through_s=180, power_headroom_kw=250,
                       compile_cache_key="", blast_radius=1, autonomy_level="L1",
                       requested_action="train", measured_age_s=30, stitch_api_reachable=True,
                       labels={"graph_hash": "b" * 64, "cut": "pp"})
    return env.replace(compile_cache_key=env.expected_compile_cache_key("b" * 64), **changes)


def test_missing_checks_are_not_approval():
    result = admission_preview(envelope())
    assert result["decision"] == "span"
    assert result["not_checked"]
    assert not result["passes_supplied_checks"]
    assert not result["execution_authorized"]


def test_stale_measurement_still_refused():
    result = admission_preview(envelope(measured_age_s=1e9))
    assert result["decision"] not in ("span", "local")
    assert result["reasons"]
    assert not result["passes_supplied_checks"]


def test_nonfinite_admission_data_refused():
    with pytest.raises(ValueError):
        admission_preview(envelope(power_headroom_kw=float("nan")))
