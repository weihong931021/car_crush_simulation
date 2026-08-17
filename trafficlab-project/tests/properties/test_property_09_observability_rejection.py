"""Property 9: unobservable, ill-conditioned, or uncertain poses reject."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import unittest

from hypothesis import given, strategies as st
import numpy as np

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.test_haware_hypotheses import record, scope, seed_profile, template
from tests.test_haware_optimizer import optimizer_profile, refinement_bounds
from trafficlab.motion.haware_accuracy.models import LocalizationStatus
from trafficlab.motion.haware_accuracy.validation import validate_before_read
from trafficlab.motion.haware_hypotheses import DirectImageHypothesisGenerator
from trafficlab.motion.haware_optimizer import (
    BoundedScipyRefiner,
    CommonSupportScorer,
    OrderedGateSelector,
    compute_observability_from_linearization,
)
from trafficlab.projection.haware_forward import HawareForwardProjector


_ELLIPSE_CHI_SQUARE_95_DOF2 = 5.991464547107979
_GATE_KINDS = ("rank", "condition", "position", "heading")


@dataclass(frozen=True)
class ObservabilityCase:
    gate_kind: str
    pose_sensitivity: tuple[float, float, float]
    nuisance_coupling: tuple[tuple[float, float, float], ...]
    nuisance_sensitivity: tuple[float, float]
    residuals: tuple[float, ...]
    pose_scales: tuple[float, float, float]


@st.composite
def observability_cases(draw):
    gate_kind = draw(st.sampled_from(_GATE_KINDS))
    sensitivities = [
        draw(st.integers(min_value=1, max_value=8)) / 2.0
        for _ in range(3)
    ]
    if gate_kind == "rank":
        sensitivities[draw(st.integers(min_value=0, max_value=2))] = 0.0
    coupling = tuple(
        tuple(draw(st.integers(min_value=-4, max_value=4)) / 4.0 for _ in range(3))
        for _ in range(2)
    )
    residuals = tuple(
        draw(st.integers(min_value=-10, max_value=10)) / 5.0
        for _ in range(5)
    )
    if not any(residuals):
        residuals = (1.0, *residuals[1:])
    return ObservabilityCase(
        gate_kind=gate_kind,
        pose_sensitivity=tuple(sensitivities),
        nuisance_coupling=coupling,
        nuisance_sensitivity=(
            draw(st.integers(min_value=2, max_value=8)) / 2.0,
            draw(st.integers(min_value=2, max_value=8)) / 2.0,
        ),
        residuals=residuals,
        pose_scales=tuple(
            draw(st.integers(min_value=1, max_value=8)) / 4.0
            for _ in range(3)
        ),
    )


def _linearization(case: ObservabilityCase) -> np.ndarray:
    """Build pose-only rows plus nuisance-coupled rows.

    Marginalizing the two full-rank nuisance columns removes the final two
    rows' pose information, leaving the independently controlled pose block.
    """
    jacobian = np.zeros((5, 5), dtype=np.float64)
    jacobian[:3, :3] = np.diag(case.pose_sensitivity)
    jacobian[3:, :3] = np.asarray(case.nuisance_coupling)
    jacobian[3:, 3:] = np.diag(case.nuisance_sensitivity)
    return jacobian


def _reference_calculation(
    jacobian: np.ndarray,
    residuals: np.ndarray,
    scales: np.ndarray,
    rank_tolerance: float,
):
    """Independent linear-algebra reference for the frozen linear-loss formula."""
    information = jacobian.T @ jacobian
    nuisance = information[3:, 3:]
    information_pose = (
        information[:3, :3]
        - information[:3, 3:] @ np.linalg.inv(nuisance) @ information[3:, :3]
    )
    information_pose = 0.5 * (information_pose + information_pose.T)
    singular_values = np.linalg.svd(information_pose, compute_uv=False)
    retained = singular_values > rank_tolerance
    rank = int(np.count_nonzero(retained))
    condition = (
        float(singular_values[0] / singular_values[retained][-1])
        if rank
        else math.nan
    )
    degrees_of_freedom = max(residuals.size - rank, 1)
    residual_variance = float(np.dot(residuals, residuals) / degrees_of_freedom)
    largest = float(singular_values[0]) if singular_values.size else 1.0
    covariance_scaled = residual_variance * np.linalg.pinv(
        information_pose,
        rcond=rank_tolerance / max(largest, rank_tolerance),
        hermitian=True,
    )
    pose_scale = np.diag(scales[:3])
    covariance = pose_scale @ covariance_scaled @ pose_scale
    covariance = 0.5 * (covariance + covariance.T)
    position_eigenvalues = np.maximum(
        np.linalg.eigvalsh(covariance[:2, :2]), 0.0
    )
    ellipse = np.sqrt(
        _ELLIPSE_CHI_SQUARE_95_DOF2 * position_eigenvalues
    )[::-1]
    heading_uncertainty = math.sqrt(max(float(covariance[2, 2]), 0.0))
    return {
        "information": information,
        "information_pose": information_pose,
        "singular_values": singular_values,
        "rank": rank,
        "condition": condition,
        "degrees_of_freedom": degrees_of_freedom,
        "residual_variance": residual_variance,
        "covariance": covariance,
        "ellipse": ellipse,
        "heading_uncertainty": heading_uncertainty,
    }


def _fixture():
    profile_value = optimizer_profile()
    scope_value = scope()
    token = validate_before_read(profile_value, scope_value)
    template_value = template()
    record_value = record(profile_value, template_value)
    projector = HawareForwardProjector()
    generation = DirectImageHypothesisGenerator(projector).generate(
        record_value,
        template_value,
        token=token,
        profile=profile_value,
        scope=scope_value,
        seed_profile=seed_profile(),
    )
    refinement = BoundedScipyRefiner(projector).refine(
        generation,
        record_value,
        template_value,
        token=token,
        profile=profile_value,
        scope=scope_value,
        bounds=refinement_bounds(),
    )
    scoring = CommonSupportScorer().evaluate(
        refinement,
        record_value,
        template_value,
        token=token,
        profile=profile_value,
        scope=scope_value,
    )
    assert scoring.supported, "Property 9 requires one supported optimizer fixture"
    candidate = scoring.supported[0]
    path_id = candidate.path.path_id
    refinement = replace(
        scoring.refinement,
        sampled_path_ids=(path_id,),
        retained_path_ids=(path_id,),
        refined=(candidate.refinement,),
        failures=(),
        skipped_path_ids=(),
    )
    return (
        profile_value,
        scope_value,
        template_value,
        record_value,
        replace(scoring, refinement=refinement, evaluated=(candidate,)),
    )


_BASE_PROFILE, _SCOPE, _TEMPLATE, _RECORD, _BASE_SCORING = _fixture()


def _evaluate(case: ObservabilityCase):
    jacobian = _linearization(case)
    residuals = np.asarray(case.residuals, dtype=np.float64)
    scales = np.asarray((*case.pose_scales, 1.0, 1.0), dtype=np.float64)
    permissive = replace(
        _BASE_PROFILE.optimizer.observability,
        rank_tolerance=1e-8,
        minimum_rank=3,
        condition_rejection_boundary=1e12,
        position_uncertainty_boundary_m=1e12,
        heading_uncertainty_boundary_rad=1e12,
    )
    common = dict(
        image_residual_jacobian_scaled=jacobian,
        image_residuals=residuals,
        parameter_names=("x", "y", "heading", "height", "calibration"),
        parameter_units=("m", "m", "rad", "m", "m"),
        parameter_scales=scales,
        nuisance_prior_precision_scaled=(0.0,) * 5,
        robust_loss="linear",
        robust_loss_scale=1.0,
    )
    baseline = compute_observability_from_linearization(
        settings=permissive, **common
    )
    if case.gate_kind == "condition":
        settings = replace(
            permissive,
            condition_rejection_boundary=baseline.diagnostics.condition,
        )
    elif case.gate_kind == "position":
        settings = replace(
            permissive,
            position_uncertainty_boundary_m=(
                baseline.diagnostics.position_ellipse_95_m[0]
            ),
        )
    elif case.gate_kind == "heading":
        settings = replace(
            permissive,
            heading_uncertainty_boundary_rad=(
                baseline.diagnostics.heading_uncertainty_rad
            ),
        )
    else:
        settings = permissive
    return compute_observability_from_linearization(settings=settings, **common), settings


def _selection(evaluation, settings):
    profile_value = replace(
        _BASE_PROFILE,
        optimizer=replace(
            _BASE_PROFILE.optimizer,
            observability=settings,
        ),
    )
    token = validate_before_read(profile_value, _SCOPE)
    candidate = _BASE_SCORING.evaluated[0]
    refinement = replace(
        candidate.refinement,
        observability=evaluation.diagnostics,
        observability_failures=evaluation.gate_failures,
    )
    candidate = replace(candidate, refinement=refinement)
    scoring = replace(
        _BASE_SCORING,
        refinement=replace(_BASE_SCORING.refinement, refined=(refinement,)),
        evaluated=(candidate,),
    )
    result = OrderedGateSelector().select(
        scoring,
        _RECORD,
        _TEMPLATE,
        token=token,
        profile=profile_value,
        scope=_SCOPE,
        spread_m_by_path={candidate.path.path_id: 0.0},
    )
    return profile_value, result


@deterministic_property(9)
@given(case=observability_cases())
def test_unobservable_ill_conditioned_or_uncertain_poses_are_rejected(
    case: ObservabilityCase,
) -> None:
    # Feature: haware-localization-accuracy, Property 9: Observability rejection
    """**Validates: Requirements 6.6, 6.16-6.21, 7.2-7.3**"""
    evaluation, settings = _evaluate(case)
    diagnostics = evaluation.diagnostics
    jacobian = _linearization(case)
    residuals = np.asarray(case.residuals, dtype=np.float64)
    scales = np.asarray((*case.pose_scales, 1.0, 1.0), dtype=np.float64)
    reference = _reference_calculation(
        jacobian, residuals, scales, settings.rank_tolerance
    )

    np.testing.assert_allclose(
        diagnostics.information_scaled, reference["information"],
        rtol=1e-10, atol=1e-10,
    )
    np.testing.assert_allclose(
        diagnostics.information_pose, reference["information_pose"],
        rtol=1e-10, atol=1e-10,
    )
    np.testing.assert_allclose(
        diagnostics.singular_values, reference["singular_values"],
        rtol=1e-10, atol=1e-10,
    )
    np.testing.assert_allclose(
        diagnostics.covariance_pose, reference["covariance"],
        rtol=1e-9, atol=1e-10,
    )
    np.testing.assert_allclose(
        diagnostics.position_ellipse_95_m, reference["ellipse"],
        rtol=1e-9, atol=1e-10,
    )
    assert diagnostics.rank == reference["rank"]
    assert diagnostics.residual_degrees_of_freedom == reference["degrees_of_freedom"]
    assert math.isclose(
        diagnostics.residual_variance, reference["residual_variance"],
        rel_tol=1e-10, abs_tol=1e-10,
    )
    assert math.isclose(
        diagnostics.heading_uncertainty_rad,
        reference["heading_uncertainty"],
        rel_tol=1e-9,
        abs_tol=1e-10,
    )
    if diagnostics.rank:
        assert math.isclose(
            diagnostics.condition, reference["condition"],
            rel_tol=1e-10, abs_tol=1e-10,
        )

    expected = {
        "rank": "unobservable_pose",
        "condition": "ill_conditioned_pose",
        "position": "pose_uncertainty_exceeded",
        "heading": "pose_uncertainty_exceeded",
    }[case.gate_kind]
    if case.gate_kind == "rank":
        assert diagnostics.rank < settings.minimum_rank
    elif case.gate_kind == "condition":
        assert diagnostics.condition == settings.condition_rejection_boundary
    elif case.gate_kind == "position":
        assert (
            diagnostics.position_ellipse_95_m[0]
            == settings.position_uncertainty_boundary_m
        )
    else:
        assert (
            diagnostics.heading_uncertainty_rad
            == settings.heading_uncertainty_boundary_rad
        )
    assert expected in evaluation.gate_failures

    profile_value, result = _selection(evaluation, settings)
    record_failure_metadata(
        replay_identity=_RECORD,
        profile_identity=profile_value,
        run_identity=result,
    )
    assert result.status is LocalizationStatus.REJECTED
    assert not result.usable
    assert result.reason == expected
    assert result.decisive_gate == expected
    assert expected in result.diagnostics.gate_failures
    assert result.authoritative_position_sat_px is None
    assert result.diagnostic_position_sat_px is not None


class ObservabilityRejectionPropertyTest(unittest.TestCase):
    def test_property_09(self) -> None:
        test_unobservable_ill_conditioned_or_uncertain_poses_are_rejected()


if __name__ == "__main__":
    unittest.main()
