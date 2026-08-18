"""Property 3: wheel-first ordering is non-exclusive."""
from __future__ import annotations

from dataclasses import replace

from hypothesis import given, strategies as st
import numpy as np

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.test_haware_hypotheses import (
    configured_profile,
    record,
    scope,
    seed_profile,
    template,
)
from trafficlab.motion.haware_accuracy.models import CueFamily, SeedClass, SemanticPath
from trafficlab.motion.haware_accuracy.validation import validate_before_read
from trafficlab.motion.haware_hypotheses import DirectImageHypothesisGenerator
from trafficlab.projection.haware_forward import HawareForwardProjector, ProjectionBatch


_PROFILE = configured_profile()
_SCOPE = scope()
_TOKEN = validate_before_read(_PROFILE, _SCOPE)
_TEMPLATE = template()
_BASE_RECORD = record(_PROFILE, _TEMPLATE)


class _GroundStatusProjector:
    """Reject optional ground equations without changing elevated equations."""

    def __init__(self, reject_ground: bool) -> None:
        self._delegate = HawareForwardProjector()
        self._reject_ground = reject_ground
        self.heights: list[tuple[float, ...]] = []

    def predict_pixels(self, pose, template_points, calibration, nuisance=None):
        heights = tuple(float(value) for value in np.asarray(template_points)[:, 1])
        self.heights.append(heights)
        if self._reject_ground and all(height == 0.0 for height in heights):
            count = len(heights)
            return ProjectionBatch(
                pixels=np.zeros((count, 2)),
                valid=np.zeros(count, dtype=np.bool_),
                failure_reasons=("synthetic_wheel_outlier",) * count,
            )
        return self._delegate.predict_pixels(pose, template_points, calibration, nuisance)


def _generate(observation_record, *, reject_ground: bool):
    projector = _GroundStatusProjector(reject_ground)
    result = DirectImageHypothesisGenerator(projector).generate(
        observation_record,
        _TEMPLATE,
        token=_TOKEN,
        profile=_PROFILE,
        scope=_SCOPE,
        seed_profile=seed_profile(),
    )
    return result, projector


def _non_wheel_signature(result):
    return tuple(
        (
            item.path.canonical_bytes(),
            item.seed.pose.canonical_bytes(),
            item.cue_heights_m,
            item.residual_rms_px,
        )
        for item in result.hypotheses
        if item.path.seed_class is SeedClass.NON_WHEEL
    )


@deterministic_property(3)
@given(
    observation_order=st.permutations(_BASE_RECORD.observations),
    wheel_state=st.sampled_from(("valid", "outlier", "unavailable")),
)
def test_non_exclusive_wheel_first_ordering(observation_order, wheel_state) -> None:
    """**Validates: Requirements 1.17, 4.1, 4.9-4.12, 5.6-5.7**"""
    observations = tuple(observation_order)
    if wheel_state == "unavailable":
        observations = tuple(
            value for value in observations
            if not value.observation_id.startswith(("obs-0", "obs-1"))
        )
    observation_record = replace(_BASE_RECORD, observations=observations)
    reject_ground = wheel_state == "outlier"
    result, projector = _generate(
        observation_record,
        reject_ground=reject_ground,
    )
    record_failure_metadata(
        replay_identity=observation_record,
        profile_identity=_PROFILE,
        run_identity=result.report,
    )

    path_by_id = {path.path_id: path for path in result.report.authorized_paths}
    ordered_classes = tuple(
        path_by_id[path_id].seed_class for path_id in result.report.stable_order
    )
    if wheel_state != "unavailable":
        first_non_wheel = ordered_classes.index(SeedClass.NON_WHEEL)
        assert first_non_wheel > 0
        assert all(
            seed_class is SeedClass.WHEEL
            for seed_class in ordered_classes[:first_non_wheel]
        )
        assert all(
            seed_class is SeedClass.NON_WHEEL
            for seed_class in ordered_classes[first_non_wheel:]
        )
        assert any(all(height == 0.0 for height in call) for call in projector.heights)
    else:
        assert ordered_classes
        assert all(seed_class is SeedClass.NON_WHEEL for seed_class in ordered_classes)

    non_wheel = tuple(
        item for item in result.hypotheses
        if item.path.seed_class is SeedClass.NON_WHEEL
    )
    assert non_wheel
    assert all(set(item.path.cue_subset) == {CueFamily.ROOF} for item in non_wheel)

    if wheel_state == "valid":
        assert result.hypotheses[0].path.seed_class is SeedClass.WHEEL
        assert all(
            height == 0.0
            for _, height in result.hypotheses[0].cue_heights_m
        )
    elif wheel_state == "outlier":
        assert result.invalid_paths
        assert all(
            path.seed_class is SeedClass.WHEEL for path in result.invalid_paths
        )

    canonical_observations = tuple(
        value for value in _BASE_RECORD.observations
        if wheel_state != "unavailable"
        or not value.observation_id.startswith(("obs-0", "obs-1"))
    )
    canonical_record = replace(_BASE_RECORD, observations=canonical_observations)
    canonical_result, _ = _generate(
        canonical_record,
        reject_ground=reject_ground,
    )
    assert result.report.canonical_bytes() == canonical_result.report.canonical_bytes()
    assert _non_wheel_signature(result) == _non_wheel_signature(canonical_result)


from unittest import TestCase


class NonExclusiveWheelFirstOrderingPropertyTest(TestCase):
    def test_property_3(self) -> None:
        test_non_exclusive_wheel_first_ordering()
