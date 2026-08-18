"""Property 5: robust outliers cannot displace sufficient clean support."""
from __future__ import annotations

from dataclasses import replace
import unittest

from hypothesis import given, strategies as st

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.property_support.strategies import SupportBoundaryCase, support_boundaries
from tests.test_haware_hypotheses import record, scope, seed_profile, template
from tests.test_haware_optimizer import optimizer_profile, refinement_bounds
from trafficlab.motion.haware_accuracy.models import (
    HypothesisState,
    LocalizationStatus,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read
from trafficlab.motion.haware_hypotheses import DirectImageHypothesisGenerator
from trafficlab.motion.haware_optimizer import (
    BoundedScipyRefiner,
    CommonSupportScorer,
    OrderedGateSelector,
)
from trafficlab.projection.haware_forward import HawareForwardProjector


_SCOPE = scope()
_TEMPLATE = template()
_BASE_PROFILE = optimizer_profile()
_BASE_TOKEN = validate_before_read(_BASE_PROFILE, _SCOPE)
_BASE_RECORD = record(_BASE_PROFILE, _TEMPLATE)
_PROJECTOR = HawareForwardProjector()
_BASE_GENERATION = DirectImageHypothesisGenerator(_PROJECTOR).generate(
    _BASE_RECORD,
    _TEMPLATE,
    token=_BASE_TOKEN,
    profile=_BASE_PROFILE,
    scope=_SCOPE,
    seed_profile=seed_profile(),
)
_BASE_REFINEMENT = BoundedScipyRefiner(_PROJECTOR).refine(
    _BASE_GENERATION,
    _BASE_RECORD,
    _TEMPLATE,
    token=_BASE_TOKEN,
    profile=_BASE_PROFILE,
    scope=_SCOPE,
    bounds=refinement_bounds(),
)
if not _BASE_REFINEMENT.refined:  # pragma: no cover - fixture contract
    raise RuntimeError("Property 5 requires one converged deterministic fixture")
_BASE_CANDIDATE = _BASE_REFINEMENT.refined[0]


def _profile(case: SupportBoundaryCase, includes_equality: bool):
    minimum_configurations = tuple(
        replace(configuration, minimum_support=3)
        for configuration in _BASE_PROFILE.optimizer.minimal_configurations
    )
    robust = replace(
        _BASE_PROFILE.optimizer.robust,
        support_boundary_px=case.boundary_px,
        support_includes_equality=includes_equality,
    )
    return replace(
        _BASE_PROFILE,
        cue_evidence=replace(
            _BASE_PROFILE.cue_evidence,
            minimal_configurations=minimum_configurations,
        ),
        optimizer=replace(
            _BASE_PROFILE.optimizer,
            minimal_configurations=minimum_configurations,
            robust=robust,
        ),
    )


def _scoring_input(offsets: tuple[tuple[str, float], ...], path_id: str):
    source_observation = _BASE_RECORD.observations[0]
    source_correspondence = _BASE_CANDIDATE.path.correspondence[0]
    source_prediction = _BASE_CANDIDATE.predictions[0]
    observations = []
    correspondences = []
    predictions = []
    residual_components = []
    for observation_id, residual_x in offsets:
        # A zero origin preserves nextafter residuals exactly through subtraction.
        observed_pixel = (0.0, 0.0)
        observations.append(replace(
            source_observation,
            observation_id=observation_id,
            pixel=observed_pixel,
            provider_key=f"property-5:{observation_id}",
        ))
        correspondences.append(replace(
            source_correspondence,
            observation_id=observation_id,
        ))
        predictions.append(replace(
            source_prediction,
            observation_id=observation_id,
            template_semantic_id=source_correspondence.template_semantic_id,
            pixel=(observed_pixel[0] + residual_x, observed_pixel[1]),
            valid=True,
            failure_reason=None,
        ))
        residual_components.extend((residual_x, 0.0))

    minimum_ids = tuple(observation_id for observation_id, _ in offsets[:3])
    path = replace(
        _BASE_CANDIDATE.path,
        path_id=path_id,
        correspondence=tuple(correspondences),
        minimal_observations=minimum_ids,
        initialization_source=replace(
            _BASE_CANDIDATE.path.initialization_source,
            observation_ids=minimum_ids,
        ),
        terminal_state=HypothesisState.REFINED,
        terminal_reason=None,
    )
    candidate = replace(
        _BASE_CANDIDATE,
        path=path,
        predictions=tuple(predictions),
        pixel_residual_components=tuple(residual_components),
        observability_failures=(),
    )
    observation_record = replace(_BASE_RECORD, observations=tuple(observations))
    refinement = replace(
        _BASE_REFINEMENT,
        sampled_path_ids=(path_id,),
        retained_path_ids=(path_id,),
        refined=(candidate,),
        failures=(),
        skipped_path_ids=(),
    )
    return observation_record, refinement


def _score_and_select(offsets, path_id, profile_value, token):
    observation_record, refinement = _scoring_input(offsets, path_id)
    scoring = CommonSupportScorer().evaluate(
        refinement,
        observation_record,
        _TEMPLATE,
        token=token,
        profile=profile_value,
        scope=_SCOPE,
    )
    result = OrderedGateSelector().select(
        scoring,
        observation_record,
        _TEMPLATE,
        token=token,
        profile=profile_value,
        scope=_SCOPE,
    )
    return observation_record, scoring.evaluated[0], result


def _assert_boundary_diagnostics(scored, case, includes_equality):
    by_id = {item.observation_id: item for item in scored.support.residuals}
    assert by_id["boundary-below"].residual_px == (case.immediately_below_px, 0.0)
    assert by_id["boundary-below"].magnitude_px == case.immediately_below_px
    assert by_id["boundary-below"].in_support
    assert by_id["boundary-equal"].residual_px == (case.equal_px, 0.0)
    assert by_id["boundary-equal"].magnitude_px == case.equal_px
    assert by_id["boundary-equal"].in_support is includes_equality
    assert by_id["boundary-above"].residual_px == (case.immediately_above_px, 0.0)
    assert by_id["boundary-above"].magnitude_px == case.immediately_above_px
    assert not by_id["boundary-above"].in_support

    expected_outliers = {"boundary-above"}
    if not includes_equality:
        expected_outliers.add("boundary-equal")
    assert set(scored.support.outlier_observation_ids) == expected_outliers
    assert set(scored.support.support_observation_ids).isdisjoint(expected_outliers)
    assert (
        set(scored.support.support_observation_ids)
        | set(scored.support.outlier_observation_ids)
    ) == set(by_id)


@deterministic_property(5)
@given(case=support_boundaries(), includes_equality=st.booleans())
def test_robust_outliers_cannot_displace_sufficient_clean_support(
    case: SupportBoundaryCase,
    includes_equality: bool,
) -> None:
    # Feature: haware-localization-accuracy, Property 5: Robust outliers cannot displace sufficient clean support
    """**Validates: Requirements 4.12, 6.3-6.4, 6.13-6.15, 6.27**"""
    profile_value = _profile(case, includes_equality)
    token = validate_before_read(profile_value, _SCOPE)
    clean_offsets = tuple((f"clean-{index}", 0.0) for index in range(3))
    boundary_offsets = (
        ("boundary-below", case.immediately_below_px),
        ("boundary-equal", case.equal_px),
        ("boundary-above", case.immediately_above_px),
    )

    _, clean_scored, clean_result = _score_and_select(
        clean_offsets, "property-5-clean", profile_value, token
    )
    contaminated_record, contaminated_scored, contaminated_result = _score_and_select(
        clean_offsets + boundary_offsets,
        "property-5-contaminated",
        profile_value,
        token,
    )
    _, insufficient_scored, insufficient_result = _score_and_select(
        boundary_offsets, "property-5-insufficient", profile_value, token
    )

    record_failure_metadata(
        replay_identity=contaminated_record,
        profile_identity=profile_value,
        run_identity=contaminated_result,
    )

    assert clean_scored.support_accepted
    assert contaminated_scored.support_accepted
    assert clean_result.status is LocalizationStatus.ACCEPTED
    assert contaminated_result.status is LocalizationStatus.ACCEPTED
    assert contaminated_result.authoritative_position_sat_px == (
        clean_result.authoritative_position_sat_px
    )
    assert contaminated_result.heading_deg == clean_result.heading_deg
    assert contaminated_result.reason is None
    assert contaminated_result.diagnostic_position_sat_px is None
    _assert_boundary_diagnostics(contaminated_scored, case, includes_equality)

    assert not insufficient_scored.support_accepted
    assert insufficient_scored.rejection_reason == "insufficient_support"
    assert len(insufficient_scored.support.support_observation_ids) < 3
    _assert_boundary_diagnostics(insufficient_scored, case, includes_equality)
    assert insufficient_result.status is LocalizationStatus.REJECTED
    assert not insufficient_result.usable
    assert insufficient_result.reason == "insufficient_support"
    assert insufficient_result.decisive_gate == "insufficient_support"
    assert insufficient_result.authoritative_position_sat_px is None
    assert insufficient_result.diagnostic_position_sat_px is None
    assert "insufficient_support" in insufficient_result.diagnostics.gate_failures
    assert "insufficient_valid_hypothesis" in insufficient_result.diagnostics.gate_failures


class RobustSupportAndOutliersPropertyTest(unittest.TestCase):
    def test_robust_support_and_outliers(self) -> None:
        test_robust_outliers_cannot_displace_sufficient_clean_support()


if __name__ == "__main__":
    unittest.main()
