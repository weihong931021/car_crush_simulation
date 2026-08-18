"""Property 10: decisive gate precedence is deterministic."""
from __future__ import annotations

from dataclasses import dataclass, replace
import unittest

from hypothesis import given, strategies as st

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.test_haware_hypotheses import record, scope, seed_profile, template
from tests.test_haware_optimizer import optimizer_profile, refinement_bounds
from trafficlab.motion.haware_accuracy.models import (
    HypothesisState,
    LocalizationStatus,
    TrackKind,
    TrackProvenance,
)
from trafficlab.motion.haware_accuracy.validation import (
    REQUIRED_GATE_PRECEDENCE,
    validate_before_read,
)
from trafficlab.motion.haware_hypotheses import DirectImageHypothesisGenerator
from trafficlab.motion.haware_optimizer import (
    BoundedScipyRefiner,
    CommonScoreComponents,
    CommonSupportScorer,
    OrderedGateSelector,
    RefinementFailure,
)
from trafficlab.projection.haware_forward import HawareForwardProjector


_REQUIRED_LATER_FAILURES = (
    "numerical_optimization_failure",  # normalized to non_finite_optimization
    "optimization_not_converged",
    "unobservable_pose",
    "ill_conditioned_pose",
    "pose_uncertainty_exceeded",
    "spread_rejected",
    "ambiguous_equal_score",
    "ambiguous_hypotheses",
)


@dataclass(frozen=True)
class DecisiveGateCase:
    candidate_order: tuple[int, ...]
    failure_order: tuple[int, ...]
    scores: tuple[float, ...]
    diagnostic_codes: tuple[str, ...]
    track_suffix: int


@st.composite
def decisive_gate_cases(draw):
    diagnostic_codes = tuple(draw(st.lists(
        st.from_regex(r"property_10_diagnostic_[a-z]{1,8}", fullmatch=True),
        min_size=1,
        max_size=4,
        unique=True,
    )))
    return DecisiveGateCase(
        candidate_order=tuple(draw(st.permutations(range(3)))),
        failure_order=tuple(draw(st.permutations(range(len(_REQUIRED_LATER_FAILURES))))),
        scores=tuple(float(value) for value in draw(
            st.lists(st.integers(min_value=0, max_value=1000), min_size=3, max_size=3)
        )),
        diagnostic_codes=diagnostic_codes,
        track_suffix=draw(st.integers(min_value=0, max_value=1_000_000)),
    )


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
    assert len(scoring.supported) >= 3, "Property 10 requires three supported candidates"
    return profile_value, scope_value, token, template_value, record_value, scoring


_PROFILE, _SCOPE, _TOKEN, _TEMPLATE, _RECORD, _BASE_SCORING = _fixture()
_BASE_CANDIDATES = _BASE_SCORING.supported[:3]


def _score_components(score: float) -> CommonScoreComponents:
    return CommonScoreComponents(
        robust_residual_loss=score,
        outlier_penalty_cost=0.0,
        bounded_nuisance_prior_cost=0.0,
        weighted_nuisance_prior_cost=0.0,
        total=score,
    )


def _insufficient_candidate(candidate, score: float):
    path = replace(
        candidate.path,
        terminal_state=HypothesisState.REJECTED,
        terminal_reason="insufficient_support",
    )
    return replace(
        candidate,
        refinement=replace(candidate.refinement, path=path, observability_failures=()),
        path=path,
        support=replace(
            candidate.support,
            minimum_support=candidate.support.authorized_observation_count + 1,
        ),
        score_components=_score_components(score),
        support_accepted=False,
        rejection_reason="insufficient_support",
    )


def _failure(candidate, reason: str) -> RefinementFailure:
    return RefinementFailure(
        path=replace(
            candidate.path,
            terminal_state=HypothesisState.REJECTED,
            terminal_reason=reason,
        ),
        reason=reason,
        detail=f"Property 10 simultaneous gate failure: {reason}",
        exception_type=None,
        settings=candidate.refinement.settings,
    )


def _rejection_scoring(case: DecisiveGateCase, *, reverse_diagnostics: bool):
    ordered = tuple(_BASE_CANDIDATES[index] for index in case.candidate_order)
    rejected = tuple(
        _insufficient_candidate(candidate, score)
        for candidate, score in zip(ordered, case.scores)
    )
    required = tuple(
        _REQUIRED_LATER_FAILURES[index] for index in case.failure_order
    )
    diagnostic_codes = (
        tuple(reversed(case.diagnostic_codes))
        if reverse_diagnostics
        else case.diagnostic_codes
    )
    reasons = required + diagnostic_codes
    if reverse_diagnostics:
        reasons = tuple(reversed(reasons))
    failures = tuple(
        _failure(rejected[index % len(rejected)], reason)
        for index, reason in enumerate(reasons)
    )
    path_ids = tuple(item.path.path_id for item in rejected)
    refinement = replace(
        _BASE_SCORING.refinement,
        sampled_path_ids=path_ids,
        retained_path_ids=path_ids,
        refined=tuple(item.refinement for item in rejected),
        failures=failures,
        skipped_path_ids=(),
    )
    return replace(_BASE_SCORING, refinement=refinement, evaluated=rejected)


def _accepted_scoring(diagnostic_codes: tuple[str, ...]):
    candidate = _BASE_CANDIDATES[0]
    path = replace(
        candidate.path,
        terminal_state=HypothesisState.SCORED,
        terminal_reason=None,
    )
    accepted = replace(
        candidate,
        refinement=replace(
            candidate.refinement,
            path=path,
            observability_failures=diagnostic_codes,
        ),
        path=path,
    )
    path_id = path.path_id
    refinement = replace(
        _BASE_SCORING.refinement,
        sampled_path_ids=(path_id,),
        retained_path_ids=(path_id,),
        refined=(accepted.refinement,),
        failures=(),
        skipped_path_ids=(),
    )
    return replace(_BASE_SCORING, refinement=refinement, evaluated=(accepted,))


def _record_with_motion_tie_breaker(case: DecisiveGateCase):
    return replace(
        _RECORD,
        track=TrackProvenance(
            claimed_id=f"property-10-track-{case.track_suffix}",
            tracker_name="property-10-tracker",
            tracker_version="1",
            source_sequence=_RECORD.source_sequence,
            association_provenance="property-10-motion-tie-breaker",
            observed_frames=("before", _RECORD.frame_id, "after"),
            kind=TrackKind.REAL,
        ),
    )


def _select(scoring, record_value):
    return OrderedGateSelector().select(
        scoring,
        record_value,
        _TEMPLATE,
        token=_TOKEN,
        profile=_PROFILE,
        scope=_SCOPE,
    )


@deterministic_property(10)
@given(case=decisive_gate_cases())
def test_decisive_gate_precedence_is_deterministic(case: DecisiveGateCase) -> None:
    # Feature: haware-localization-accuracy, Property 10: Decisive gate precedence is deterministic
    """**Validates: Requirements 6.25-6.29, 6.31**"""
    assert _PROFILE.optimizer.rejection_precedence[:len(REQUIRED_GATE_PRECEDENCE)] == (
        REQUIRED_GATE_PRECEDENCE
    )
    assert REQUIRED_GATE_PRECEDENCE[0] == "insufficient_support"

    baseline = _select(_rejection_scoring(case, reverse_diagnostics=False), _RECORD)
    perturbed = _select(
        _rejection_scoring(case, reverse_diagnostics=True),
        _record_with_motion_tie_breaker(case),
    )
    record_failure_metadata(
        replay_identity=_RECORD,
        profile_identity=_PROFILE,
        run_identity=baseline,
    )

    expected_gate_failures = {
        "insufficient_support",
        "non_finite_optimization",
        "optimization_not_converged",
        "unobservable_pose",
        "ill_conditioned_pose",
        "pose_uncertainty_exceeded",
        "spread_rejected",
        "ambiguous_equal_score",
        "ambiguous_hypotheses",
        "insufficient_valid_hypothesis",
        *case.diagnostic_codes,
    }
    for result in (baseline, perturbed):
        assert result.status is LocalizationStatus.REJECTED
        assert not result.usable
        assert result.reason == "insufficient_support"
        assert result.decisive_gate == "insufficient_support"
        assert result.authoritative_position_sat_px is None
        assert expected_gate_failures.issubset(result.diagnostics.gate_failures)
        assert set(case.diagnostic_codes).issubset(result.diagnostics.gate_failures)
    assert baseline.reason == perturbed.reason
    assert baseline.status is perturbed.status

    accepted = _select(_accepted_scoring(case.diagnostic_codes), _RECORD)
    accepted_perturbed = _select(
        _accepted_scoring(tuple(reversed(case.diagnostic_codes))),
        _record_with_motion_tie_breaker(case),
    )
    for result in (accepted, accepted_perturbed):
        assert result.status is LocalizationStatus.ACCEPTED
        assert result.usable
        assert result.reason is None
        assert result.decisive_gate == "accepted"
        assert result.authoritative_position_sat_px is not None
        assert result.diagnostic_position_sat_px is None
        assert set(case.diagnostic_codes).issubset(result.diagnostics.gate_failures)
    assert accepted.authoritative_position_sat_px == (
        accepted_perturbed.authoritative_position_sat_px
    )
    assert accepted.heading_deg == accepted_perturbed.heading_deg


class DeterministicDecisiveGatePrecedencePropertyTest(unittest.TestCase):
    def test_property_10(self) -> None:
        test_decisive_gate_precedence_is_deterministic()


if __name__ == "__main__":
    unittest.main()
