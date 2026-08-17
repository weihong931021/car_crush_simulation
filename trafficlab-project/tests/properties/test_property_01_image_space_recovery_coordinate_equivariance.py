"""Property 1: image-space recovery and coordinate equivariance."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import unittest

from hypothesis import given, strategies as st
import numpy as np

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.test_haware_profile_validation import profile as base_profile, scope, source
from trafficlab.motion.haware_accuracy.models import (
    ClosedInterval,
    CueFamily,
    CueHeightSpec,
    HypothesisState,
    ImageObservation,
    LocalizationStatus,
    MinimalConfiguration,
    NuisanceField,
    NuisanceProfile,
    ObservationRecord,
    Pose2D,
    ProviderProvenance,
    SemanticPath,
    SemanticPathSpec,
    VehicleTemplate,
    VehicleTemplatePoint,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read
from trafficlab.motion.haware_hypotheses import (
    DirectImageHypothesisGenerator,
    DirectSeedProfile,
    SeedSearchCell,
)
from trafficlab.motion.haware_optimizer import (
    BoundedScipyRefiner,
    CommonSupportScorer,
    OrderedGateSelector,
    RefinementBounds,
)
from trafficlab.projection.haware_forward import HawareForwardProjector


_POSITION_TOLERANCE_M = 0.1
_HEADING_TOLERANCE_RAD = 0.01
_GATE_MODES = (
    "eligible", "support", "observability", "conditioning", "uncertainty", "uniqueness",
)

@dataclass(frozen=True)
class SyntheticCase:
    pose: Pose2D
    translation_px: tuple[float, float]
    heading_transform_rad: float
    roof_height_m: float
    seed_offset_m: tuple[float, float]
    seed_heading_offset_rad: float
    gate_mode: str


@st.composite
def observable_projection_cases(draw):
    quarter_degree = math.pi / 720.0
    return SyntheticCase(
        pose=Pose2D(
            center_sat_px=(
                float(draw(st.integers(min_value=160, max_value=360))) / 4.0,
                float(draw(st.integers(min_value=240, max_value=480))) / 4.0,
            ),
            heading_rad_unwrapped=draw(st.integers(min_value=-720, max_value=720)) * quarter_degree,
        ),
        translation_px=(
            float(draw(st.integers(min_value=-80, max_value=80))) / 4.0,
            float(draw(st.integers(min_value=-80, max_value=80))) / 4.0,
        ),
        heading_transform_rad=draw(st.integers(min_value=-480, max_value=480)) * quarter_degree,
        roof_height_m=float(draw(st.integers(min_value=120, max_value=180))) / 100.0,
        seed_offset_m=(
            float(draw(st.integers(min_value=-4, max_value=4))) / 20.0,
            float(draw(st.integers(min_value=-4, max_value=4))) / 20.0,
        ),
        seed_heading_offset_rad=float(draw(st.integers(min_value=-8, max_value=8))) / 100.0,
        gate_mode=draw(st.sampled_from(_GATE_MODES)),
    )


def _template() -> VehicleTemplate:
    coordinates = (
        (-1.1, -2.1),
        (-0.35, -1.25),
        (0.8, -0.55),
        (-0.75, 0.45),
        (0.2, 1.35),
        (1.25, 2.25),
    )
    return VehicleTemplate(
        version="property-1-asymmetric-body-axes-v1",
        points=tuple(
            VehicleTemplatePoint(
                semantic_id=f"roof-{index}",
                position_m=(x, 0.0, z),
                cue_family=CueFamily.ROOF,
            )
            for index, (x, z) in enumerate(coordinates)
        ),
    )

def _profile(template: VehicleTemplate):
    value = base_profile()
    roof_configuration = MinimalConfiguration(
        configuration_id="observable-roof-six",
        cue_families=(CueFamily.ROOF,),
        minimum_support=len(template.points),
    )
    wheel_configuration = next(
        configuration
        for configuration in value.optimizer.minimal_configurations
        if CueFamily.WHEEL in configuration.cue_families
    )
    roof_interval = ClosedInterval(lower=1.2, upper=1.8)
    wheel_height = next(
        spec
        for spec in value.cue_evidence.height_specs
        if spec.cue_family is CueFamily.WHEEL
    )
    configurations = (roof_configuration, wheel_configuration)
    cue_evidence = replace(
        value.cue_evidence,
        semantic_mappings=(
            *( (f"label-{point.semantic_id}", point.semantic_id) for point in template.points ),
            ("wheel", "wheel"),
        ),
        height_specs=(
            wheel_height,
            CueHeightSpec(
                cue_family=CueFamily.ROOF,
                height_m=roof_interval,
                evidence=source("property-1-roof-height"),
            ),
        ),
        minimal_configurations=configurations,
    )
    optimizer = replace(
        value.optimizer,
        hypothesis_budget=2,
        sampled_candidate_budget=2,
        retained_candidate_count=2,
        minimal_configurations=configurations,
        semantic_paths=(SemanticPathSpec(semantic_path=SemanticPath.NORMAL),),
        robust=replace(value.optimizer.robust, nuisance_penalty=0.0),
        optimizer=replace(
            value.optimizer.optimizer,
            max_evaluations=80,
            parameter_scale=(1.0, 1.0, 0.5, 0.2),
        ),
        observability=replace(
            value.optimizer.observability,
            rank_tolerance=1e-10,
            condition_rejection_boundary=1e12,
            position_uncertainty_boundary_m=1e6,
            heading_uncertainty_boundary_rad=1e6,
        ),
        equivalence=replace(
            value.optimizer.equivalence,
            position_tolerance_m=_POSITION_TOLERANCE_M,
            heading_tolerance_rad=_HEADING_TOLERANCE_RAD,
        ),
    )
    return replace(
        value,
        profile_id="property-1-profile-v2",
        calibration=replace(value.calibration, authorized_nuisance_fields=()),
        cue_evidence=cue_evidence,
        nuisance=NuisanceProfile(
            version="property-1-nuisance-v2",
            fields=(NuisanceField(
                name="roof_height_m",
                unit="m",
                bounds=roof_interval,
                scale=0.2,
            ),),
        ),
        optimizer=optimizer,
    )


def _record(
    profile,
    template: VehicleTemplate,
    pose: Pose2D,
    height_m: float,
) -> ObservationRecord:
    points = np.asarray(
        tuple((point.position_m[0], height_m, point.position_m[2]) for point in template.points),
        dtype=np.float64,
    )
    projection = HawareForwardProjector().predict_pixels(
        pose, points, profile.calibration.snapshot,
    )
    assert projection.valid.all()
    observations = tuple(
        ImageObservation(
            observation_id=f"observation-{index}",
            pixel=(float(pixel[0]), float(pixel[1])),
            confidence=1.0,
            candidate_labels=(f"label-{point.semantic_id}",),
            provider_key=f"synthetic-{index}",
        )
        for index, (point, pixel) in enumerate(zip(template.points, projection.pixels))
    )
    return ObservationRecord(
        site="kee-cc",
        source_sequence="property-1-sequence",
        frame_id="property-1-frame",
        detection_id="property-1-detection",
        image_size_px=(1920, 1080),
        observations=observations,
        provider=ProviderProvenance(
            provider_name="property-1-forward-model",
            provider_version="1",
            adapter_version="1",
        ),
        source=source("property-1-synthetic-record"),
    )

def _seed_profile(profile, pose: Pose2D, case: SyntheticCase) -> DirectSeedProfile:
    scale = profile.calibration.snapshot.pixels_per_metre
    initial = (
        pose.center_sat_px[0] + case.seed_offset_m[0] * scale,
        pose.center_sat_px[1] + case.seed_offset_m[1] * scale,
    )
    return DirectSeedProfile(
        search_cells=(SeedSearchCell(
            cell_id="property-1-cell",
            center_x_px=ClosedInterval(
                lower=pose.center_sat_px[0] - 8.0,
                upper=pose.center_sat_px[0] + 8.0,
            ),
            center_y_px=ClosedInterval(
                lower=pose.center_sat_px[1] - 8.0,
                upper=pose.center_sat_px[1] + 8.0,
            ),
            initial_center_sat_px=initial,
        ),),
        heading_starts_rad=(pose.heading_rad_unwrapped + case.seed_heading_offset_rad,),
        max_evaluations=80,
        ftol=1e-10,
        xtol=1e-10,
        gtol=1e-10,
        finite_difference_step=1e-6,
        parameter_scale=(1.0, 1.0, 0.5),
    )


def _recover(profile, template: VehicleTemplate, pose: Pose2D, case: SyntheticCase):
    guard = scope()
    token = validate_before_read(profile, guard)
    record = _record(profile, template, pose, case.roof_height_m)
    projector = HawareForwardProjector()
    generation = DirectImageHypothesisGenerator(projector).generate(
        record,
        template,
        token=token,
        profile=profile,
        scope=guard,
        seed_profile=_seed_profile(profile, pose, case),
    )
    refinement = BoundedScipyRefiner(projector).refine(
        generation,
        record,
        template,
        token=token,
        profile=profile,
        scope=guard,
        bounds=RefinementBounds(
            position_delta_x_m=ClosedInterval(lower=-2.5, upper=2.5),
            position_delta_y_m=ClosedInterval(lower=-2.5, upper=2.5),
            heading_delta_rad=ClosedInterval(lower=-0.6, upper=0.6),
            residual_scale_px=1.0,
        ),
    )
    scoring = CommonSupportScorer().evaluate(
        refinement, record, template, token=token, profile=profile, scope=guard,
    )
    result = OrderedGateSelector().select(
        scoring, record, template, token=token, profile=profile, scope=guard,
    )
    return record, scoring, result, token, guard


def _circular_distance(left: float, right: float) -> float:
    return abs((left - right + math.pi) % (2.0 * math.pi) - math.pi)


def _assert_recovery(result, expected: Pose2D, pixels_per_metre: float) -> None:
    assert result.status is LocalizationStatus.ACCEPTED
    assert result.authoritative_position_sat_px is not None
    position_error_m = math.dist(
        result.authoritative_position_sat_px, expected.center_sat_px,
    ) / pixels_per_metre
    heading = math.radians(result.heading_deg)
    assert position_error_m <= _POSITION_TOLERANCE_M
    assert _circular_distance(heading, expected.heading_rad_unwrapped) <= _HEADING_TOLERANCE_RAD
    assert result.diagnostic_position_sat_px is None


def _world_offsets(pose: Pose2D, template: VehicleTemplate, scale: float) -> np.ndarray:
    heading = pose.heading_rad_unwrapped
    forward = np.asarray((math.cos(heading), math.sin(heading)))
    left = np.asarray((math.sin(heading), -math.cos(heading)))
    return np.asarray(tuple(
        scale * (point.position_m[0] * left - point.position_m[2] * forward)
        for point in template.points
    ))

def _force_gate(scoring, mode: str):
    candidate = scoring.evaluated[0]
    if mode == "support":
        path = replace(
            candidate.path,
            terminal_state=HypothesisState.REJECTED,
            terminal_reason="insufficient_support",
        )
        rejected = replace(
            candidate,
            path=path,
            support=replace(
                candidate.support,
                minimum_support=candidate.support.authorized_observation_count + 1,
            ),
            support_accepted=False,
            rejection_reason="insufficient_support",
        )
        return replace(scoring, evaluated=(rejected,)), "insufficient_support"

    reason_by_mode = {
        "observability": "unobservable_pose",
        "conditioning": "ill_conditioned_pose",
        "uncertainty": "pose_uncertainty_exceeded",
    }
    if mode in reason_by_mode:
        reason = reason_by_mode[mode]
        failed_refinement = replace(
            candidate.refinement, observability_failures=(reason,),
        )
        failed = replace(candidate, refinement=failed_refinement)
        refinement = replace(scoring.refinement, refined=(failed_refinement,))
        return replace(
            scoring, refinement=refinement, evaluated=(failed,),
        ), reason

    if mode == "uniqueness":
        alternative_path = replace(
            candidate.path, path_id=candidate.path.path_id + "-alternative",
        )
        alternative_refinement = replace(
            candidate.refinement,
            path=alternative_path,
            pose=replace(
                candidate.refinement.pose,
                center_sat_px=(
                    candidate.refinement.pose.center_sat_px[0] + 40.0,
                    candidate.refinement.pose.center_sat_px[1],
                ),
            ),
        )
        alternative = replace(
            candidate,
            path=alternative_path,
            refinement=alternative_refinement,
        )
        refinement = replace(
            scoring.refinement,
            sampled_path_ids=(candidate.path.path_id, alternative_path.path_id),
            retained_path_ids=(candidate.path.path_id, alternative_path.path_id),
            refined=(candidate.refinement, alternative_refinement),
        )
        return replace(
            scoring,
            refinement=refinement,
            evaluated=(candidate, alternative),
        ), "ambiguous_equal_score"
    return scoring, None


@deterministic_property(1)
@given(observable_projection_cases())
def test_image_space_recovery_and_coordinate_equivariance(case: SyntheticCase) -> None:
    """**Validates: Requirements 1.6-1.7, 3.1-3.6, 3.10-3.11**"""
    template = _template()
    profile = _profile(template)

    # The acceptance profile remains complete even though recovery observations
    # intentionally exercise only roof/non-ground evidence.
    wheel_height = next(
        spec.height_m
        for spec in profile.cue_evidence.height_specs
        if spec.cue_family is CueFamily.WHEEL
    )
    assert (wheel_height.lower, wheel_height.upper) == (0.0, 0.0)
    configured_families = {
        family
        for configuration in profile.optimizer.minimal_configurations
        for family in configuration.cue_families
    }
    assert CueFamily.WHEEL in configured_families
    assert CueFamily.ROOF in configured_families

    transformed_pose = Pose2D(
        center_sat_px=(
            case.pose.center_sat_px[0] + case.translation_px[0],
            case.pose.center_sat_px[1] + case.translation_px[1],
        ),
        heading_rad_unwrapped=(
            case.pose.heading_rad_unwrapped + case.heading_transform_rad
        ),
    )
    base_record, base_scoring, base_result, token, guard = _recover(
        profile, template, case.pose, case,
    )
    transformed_record, transformed_scoring, transformed_result, _, _ = _recover(
        profile, template, transformed_pose, case,
    )
    record_failure_metadata(
        replay_identity=transformed_record,
        profile_identity=profile,
        run_identity=transformed_scoring,
    )

    scale = profile.calibration.snapshot.pixels_per_metre
    _assert_recovery(base_result, case.pose, scale)
    _assert_recovery(transformed_result, transformed_pose, scale)

    recovered_translation = (
        transformed_result.authoritative_position_sat_px[0]
        - base_result.authoritative_position_sat_px[0],
        transformed_result.authoritative_position_sat_px[1]
        - base_result.authoritative_position_sat_px[1],
    )
    np.testing.assert_allclose(
        recovered_translation, case.translation_px, atol=scale * 0.2,
    )
    recovered_heading_delta = _circular_distance(
        math.radians(transformed_result.heading_deg)
        - math.radians(base_result.heading_deg),
        case.heading_transform_rad,
    )
    assert recovered_heading_delta <= 2.0 * _HEADING_TOLERANCE_RAD

    base_offsets = _world_offsets(case.pose, template, scale)
    transformed_offsets = _world_offsets(transformed_pose, template, scale)
    cosine = math.cos(case.heading_transform_rad)
    sine = math.sin(case.heading_transform_rad)
    rotation = np.asarray(((cosine, -sine), (sine, cosine)))
    np.testing.assert_allclose(
        transformed_offsets, base_offsets @ rotation.T, atol=1e-10,
    )

    left_only = VehicleTemplate(
        version="property-1-left-axis-check-v1",
        points=(VehicleTemplatePoint(
            semantic_id="left",
            position_m=(1.0, 0.0, 0.0),
            cue_family=CueFamily.ROOF,
        ),),
    )
    rear_only = VehicleTemplate(
        version="property-1-rear-axis-check-v1",
        points=(VehicleTemplatePoint(
            semantic_id="rear",
            position_m=(0.0, 0.0, 1.0),
            cue_family=CueFamily.ROOF,
        ),),
    )
    heading = transformed_pose.heading_rad_unwrapped
    np.testing.assert_allclose(
        _world_offsets(transformed_pose, left_only, scale)[0] / scale,
        (math.sin(heading), -math.cos(heading)),
        atol=1e-12,
    )
    np.testing.assert_allclose(
        _world_offsets(transformed_pose, rear_only, scale)[0] / scale,
        (-math.cos(heading), -math.sin(heading)),
        atol=1e-12,
    )

    gated_scoring, expected_reason = _force_gate(
        transformed_scoring, case.gate_mode,
    )
    if expected_reason is not None:
        gated = OrderedGateSelector().select(
            gated_scoring,
            transformed_record,
            template,
            token=token,
            profile=profile,
            scope=guard,
        )
        assert gated.status is LocalizationStatus.REJECTED
        assert not gated.usable
        assert gated.authoritative_position_sat_px is None
        assert gated.reason == expected_reason
        assert expected_reason in gated.diagnostics.gate_failures


class ImageSpaceRecoveryCoordinateEquivariancePropertyTest(unittest.TestCase):
    def test_property_1(self) -> None:
        test_image_space_recovery_and_coordinate_equivariance()


if __name__ == "__main__":
    unittest.main()
