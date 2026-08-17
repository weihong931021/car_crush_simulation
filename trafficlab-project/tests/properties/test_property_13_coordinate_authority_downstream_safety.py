"""Property 13: coordinate authority is coherent and downstream-safe."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import math
import unittest

from hypothesis import given, strategies as st

from scripts.filter_and_enrich_output import filter_and_enrich
from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.property_support.strategies import bounded_floats
from trafficlab.motion.haware_accuracy.models import (
    LegacyStatusPolicy,
    LocalizationResult,
    LocalizationStatus,
)
from trafficlab.motion.localization_authority import (
    INCONSISTENT_COORDINATE_STATE,
    LEGACY_STATUS_EVIDENCE_INSUFFICIENT,
    LocalizationAuthority,
    LocalizationAuthorityError,
    authoritative_extent,
    authoritative_position,
    collider_footprint,
    diagnostic_visualization_position,
    grouped_authority_counts,
    sanitize_spatial_record_for_export,
)
from trafficlab.trajectory.smoothing import smooth_trajectories


REJECTION_REASONS = (
    "spread_rejected",
    "insufficient_support",
    "unobservable_pose",
    "ill_conditioned_pose",
    "pose_uncertainty_exceeded",
    "ambiguous_hypotheses",
)
PRIOR_MAP = {"car": {"length": 4.0, "width": 2.0}}
PX_PER_METRE = 10.0
FPS = 2.0
TRACK_ID = 17
VELOCITY_ABS_TOL = 1e-12


@dataclass(frozen=True)
class AuthorityCase:
    events: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    origin: tuple[float, float]
    first_diagnostic: tuple[float, float]
    second_diagnostic: tuple[float, float]


@st.composite
def authority_cases(draw) -> AuthorityCase:
    """Generate both statuses, both rejection coordinate roles, and every gap kind."""
    extras = draw(
        st.lists(st.sampled_from(("accepted", "rejected", "missing")), max_size=5)
    )
    events = tuple(
        draw(st.permutations(("accepted", "rejected", "missing", *extras)))
    )
    rejected_count = events.count("rejected")
    generated_reasons = tuple(
        draw(st.lists(st.sampled_from(REJECTION_REASONS), min_size=max(0, rejected_count - 1), max_size=max(0, rejected_count - 1)))
    )
    # Every case includes the inclusive spread rejection required by 1.9-1.10.
    reasons = ("spread_rejected", *generated_reasons)
    origin = (
        draw(bounded_floats(-1000.0, 1000.0)),
        draw(bounded_floats(-1000.0, 1000.0)),
    )
    diagnostic = (
        draw(bounded_floats(-1000.0, 1000.0)),
        draw(bounded_floats(-1000.0, 1000.0)),
    )
    delta = draw(bounded_floats(1.0, 100.0))
    return AuthorityCase(
        events=events,
        rejection_reasons=reasons,
        origin=origin,
        first_diagnostic=diagnostic,
        second_diagnostic=(diagnostic[0] + delta, diagnostic[1] - delta),
    )


def _accepted_result(position: tuple[float, float]) -> LocalizationResult:
    return LocalizationResult(
        status=LocalizationStatus.ACCEPTED,
        usable=True,
        authoritative_position_sat_px=position,
        diagnostic_position_sat_px=None,
        heading_deg=0.0,
        decisive_gate="accepted",
        reason=None,
    )


def _rejected_result(
    reason: str, diagnostic: tuple[float, float] | None
) -> LocalizationResult:
    return LocalizationResult(
        status=LocalizationStatus.REJECTED,
        usable=False,
        authoritative_position_sat_px=None,
        diagnostic_position_sat_px=diagnostic,
        heading_deg=0.0 if diagnostic is not None else None,
        decisive_gate=reason,
        reason=reason,
    )


def _record(result: LocalizationResult, *, stale_coordinate=None) -> dict:
    authority = LocalizationAuthority()
    mapped = authority.compatibility_mapping(
        result,
        {
            "tracked_id": TRACK_ID,
            "track": {"kind": "real"},
            "class": "car",
            "sat_coords": stale_coordinate,
        },
    )
    if result.status is LocalizationStatus.REJECTED:
        # Seed every forbidden spatial field; consumers must clear or ignore it.
        mapped.update(
            sat_coords=stale_coordinate,
            sat_floor_box=[[9999.0, 9999.0]],
            position_m=[9999.0, 9999.0],
            velocity_mps=[9999.0, 9999.0],
        )
    return mapped


def _data(case: AuthorityCase, diagnostic: tuple[float, float]) -> dict:
    frames = []
    rejection_index = 0
    for frame_index, event in enumerate(case.events):
        if event == "missing":
            objects = []
        elif event == "accepted":
            position = (case.origin[0] + frame_index * 10.0, case.origin[1])
            objects = [_record(_accepted_result(position), stale_coordinate=[8000.0, 8000.0])]
        else:
            reason = case.rejection_reasons[rejection_index]
            rejection_index += 1
            # Exercise both legal rejected roles: retained diagnostic and no fit.
            retained = diagnostic if rejection_index % 2 else None
            objects = [_record(_rejected_result(reason, retained), stale_coordinate=list(diagnostic))]
        frames.append({"frame_index": frame_index, "objects": objects})
    return {"meta": {"fps": FPS}, "frames": frames}


def _flat_records(data: dict) -> list[dict]:
    return [obj for frame in data["frames"] for obj in frame["objects"]]


def _spatial_fingerprint(enriched: dict) -> tuple:
    objects = tuple(
        (
            frame["frame_index"],
            tuple(
                (
                    authoritative_position(obj),
                    obj.get("position_m"),
                    obj.get("velocity_mps"),
                    obj.get("collider_sat_floor_box"),
                )
                for obj in frame["objects"]
            ),
        )
        for frame in enriched["frames"]
    )
    return objects, enriched["scene_extent_sat_px"], enriched["localization_counts"]


def _expected_counts(case: AuthorityCase) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    rejection_index = 0
    for event in case.events:
        if event == "accepted":
            status, reason = "accepted", "accepted"
        elif event == "missing":
            status, reason = "missing", "missing_localization"
        else:
            status, reason = "rejected", case.rejection_reasons[rejection_index]
            rejection_index += 1
        reasons = counts.setdefault(status, {})
        reasons[reason] = reasons.get(reason, 0) + 1
    return {
        status: {reason: reasons[reason] for reason in sorted(reasons)}
        for status, reasons in sorted(counts.items())
    }


def _assert_result_invariants(case: AuthorityCase) -> None:
    authority = LocalizationAuthority()
    accepted = _accepted_result(case.origin)
    retained = _rejected_result("spread_rejected", case.first_diagnostic)
    no_fit = _rejected_result("unobservable_pose", None)
    assert authority.validate_new(accepted) is accepted
    assert authority.validate_new(retained) is retained
    assert authority.validate_new(no_fit) is no_fit
    assert authority.compatibility_mapping(accepted)["sat_coords"] == case.origin
    assert authority.compatibility_mapping(retained)["sat_coords"] is None

    # Exhaust every contradictory accepted/rejected coordinate-authority state.
    mutations = (
        (accepted, "usable", False),
        (accepted, "authoritative_position_sat_px", None),
        (accepted, "authoritative_position_sat_px", (math.nan, case.origin[1])),
        (accepted, "diagnostic_position_sat_px", case.first_diagnostic),
        (accepted, "heading_deg", math.inf),
        (accepted, "reason", "unexpected_reason"),
        (retained, "usable", True),
        (retained, "authoritative_position_sat_px", case.origin),
        (retained, "diagnostic_position_sat_px", (math.inf, case.first_diagnostic[1])),
        (retained, "reason", None),
        (retained, "decisive_gate", ""),
    )
    output = [{"frame_id": "already-emitted", "sat_coords": [1.0, 2.0]}]
    for base, attribute, value in mutations:
        inconsistent = copy.deepcopy(base)
        object.__setattr__(inconsistent, attribute, value)
        before = copy.deepcopy(output)
        try:
            authority.append_compatibility(output, inconsistent)
        except LocalizationAuthorityError as error:
            assert error.reason == INCONSISTENT_COORDINATE_STATE
        else:
            raise AssertionError(f"authority mutation was accepted: {attribute}={value!r}")
        assert output == before


def _assert_segments(case: AuthorityCase, enriched: dict, smoothed: dict, stats) -> None:
    accepted_run = 0
    expected_smoothed_segments = 0
    expected_short_segments = 0
    run_lengths = []
    for event in (*case.events, "gap-sentinel"):
        if event == "accepted":
            accepted_run += 1
        elif accepted_run:
            run_lengths.append(accepted_run)
            accepted_run = 0
    expected_smoothed_segments = sum(length >= 3 for length in run_lengths)
    expected_short_segments = sum(length < 3 for length in run_lengths)

    for frame_index, event in enumerate(case.events):
        objects = enriched["frames"][frame_index]["objects"]
        smooth_objects = smoothed["frames"][frame_index]["objects"]
        if event == "missing":
            assert not objects and not smooth_objects
            continue
        obj = objects[0]
        smooth_obj = smooth_objects[0]
        if event == "rejected":
            assert obj["position_m"] is None
            assert obj["velocity_mps"] is None
            assert obj["collider_sat_floor_box"] is None
            assert "smoothed_position_sat_px" not in smooth_obj
            continue
        previous_accepted = frame_index > 0 and case.events[frame_index - 1] == "accepted"
        if previous_accepted:
            expected_velocity = (2.0, 0.0)
            actual_velocity = obj["velocity_mps"]
            assert actual_velocity is not None
            assert len(actual_velocity) == len(expected_velocity)
            assert all(math.isfinite(component) for component in actual_velocity)
            assert all(
                math.isclose(
                    actual,
                    expected,
                    rel_tol=0.0,
                    abs_tol=VELOCITY_ABS_TOL,
                )
                for actual, expected in zip(actual_velocity, expected_velocity)
            )
        else:
            assert obj["velocity_mps"] is None

        left = frame_index
        while left > 0 and case.events[left - 1] == "accepted":
            left -= 1
        right = frame_index
        while right + 1 < len(case.events) and case.events[right + 1] == "accepted":
            right += 1
        assert ("smoothed_position_sat_px" in smooth_obj) == (right - left + 1 >= 3)

    assert stats.smoothed_tracks == expected_smoothed_segments
    assert stats.skipped_short_tracks == expected_short_segments


def _assert_legacy_diagnostic_only(case: AuthorityCase) -> None:
    authority = LocalizationAuthority()
    policy = LegacyStatusPolicy(
        version="property-13-legacy-v1",
        accepted_statuses=("ok",),
        rejected_statuses=("failed", "spread_rejected"),
    )
    normalized = authority.normalize_legacy(
        {
            "status": "unknown",
            "sat_coords": case.first_diagnostic,
            "heading": 0.0,
        },
        policy,
    )
    assert normalized.status is LocalizationStatus.REJECTED
    assert normalized.reason == LEGACY_STATUS_EVIDENCE_INSUFFICIENT
    assert normalized.authoritative_position_sat_px is None
    assert normalized.diagnostic_position_sat_px == case.first_diagnostic
    mapped = authority.compatibility_mapping(normalized)
    assert mapped["sat_coords"] is None
    assert authoritative_position(mapped) is None
    assert collider_footprint(
        mapped, length_m=4.0, width_m=2.0, px_per_meter=PX_PER_METRE
    ) is None


# Feature: haware-localization-accuracy, Property 13: Coordinate authority is coherent and downstream-safe
@deterministic_property(13)
@given(case=authority_cases())
def test_coordinate_authority_is_coherent_and_downstream_safe(case: AuthorityCase) -> None:
    # **Validates: Requirements 1.9-1.10, 7.1-7.14, 7.16**
    record_failure_metadata(
        replay_identity="property-13-authority-replay",
        profile_identity="property-13-authority-profile",
        run_identity="property-13-authority-run",
    )
    _assert_result_invariants(case)
    _assert_legacy_diagnostic_only(case)

    first_data = _data(case, case.first_diagnostic)
    second_data = _data(case, case.second_diagnostic)
    first = filter_and_enrich(first_data, [TRACK_ID], PX_PER_METRE, PRIOR_MAP)
    second = filter_and_enrich(second_data, [TRACK_ID], PX_PER_METRE, PRIOR_MAP)

    # Diagnostic mutation is visible only through the explicit debug adapter.
    first_rejected = [
        record for record in _flat_records(first_data) if record.get("status") == "rejected"
    ]
    second_rejected = [
        record for record in _flat_records(second_data) if record.get("status") == "rejected"
    ]
    retained_pairs = [
        (left, right)
        for left, right in zip(first_rejected, second_rejected)
        if left["diagnostic_position_sat_px"] is not None
    ]
    assert retained_pairs
    assert all(
        diagnostic_visualization_position(left) == case.first_diagnostic
        and diagnostic_visualization_position(right) == case.second_diagnostic
        for left, right in retained_pairs
    )

    assert _spatial_fingerprint(first) == _spatial_fingerprint(second)
    assert first["localization_counts"] == _expected_counts(case)
    assert authoritative_extent(_flat_records(first_data)) == authoritative_extent(
        _flat_records(second_data)
    )

    first_smoothed, first_stats = smooth_trajectories(
        first, window_length=3, polyorder=1
    )
    second_smoothed, second_stats = smooth_trajectories(
        second, window_length=3, polyorder=1
    )
    assert _spatial_fingerprint(first_smoothed) == _spatial_fingerprint(second_smoothed)
    assert first_stats == second_stats
    _assert_segments(case, first, first_smoothed, first_stats)

    for left, right in zip(first_rejected, second_rejected):
        left_export = sanitize_spatial_record_for_export(left)
        right_export = sanitize_spatial_record_for_export(right)
        for field in ("sat_coords", "sat_floor_box", "position_m", "velocity_mps"):
            assert left_export.get(field) is None
            assert right_export.get(field) is None
        assert collider_footprint(
            left, length_m=4.0, width_m=2.0, px_per_meter=PX_PER_METRE
        ) is None

    reporting_records = _flat_records(first_data) + [
        {} for event in case.events if event == "missing"
    ]
    assert grouped_authority_counts(reporting_records) == _expected_counts(case)


class CoordinateAuthorityDownstreamSafetyPropertyTest(unittest.TestCase):
    def test_property_13(self) -> None:
        test_coordinate_authority_is_coherent_and_downstream_safe()


if __name__ == "__main__":
    unittest.main()
