"""Property 4: common scoring permits a non-wheel winner."""
from __future__ import annotations

from dataclasses import dataclass, replace
import unittest

from hypothesis import given, strategies as st

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.test_haware_hypotheses import record, scope, seed_profile, template
from tests.test_haware_optimizer import optimizer_profile, refinement_bounds
from trafficlab.motion.haware_accuracy.models import (
    LocalizationStatus,
    NuisanceVector,
    Pose2D,
    SeedClass,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read
from trafficlab.motion.haware_hypotheses import DirectImageHypothesisGenerator
from trafficlab.motion.haware_optimizer import (
    BoundedScipyRefiner,
    CommonSupportScorer,
    OrderedGateSelector,
)
from trafficlab.projection.haware_forward import HawareForwardProjector


_PROFILE = optimizer_profile()
_SCOPE = scope()
_TOKEN = validate_before_read(_PROFILE, _SCOPE)
_TEMPLATE = template()
_RECORD = record(_PROFILE, _TEMPLATE)
_PROJECTOR = HawareForwardProjector()
_GENERATION = DirectImageHypothesisGenerator(_PROJECTOR).generate(
    _RECORD,
    _TEMPLATE,
    token=_TOKEN,
    profile=_PROFILE,
    scope=_SCOPE,
    seed_profile=seed_profile(),
)
_REFINEMENT = BoundedScipyRefiner(_PROJECTOR).refine(
    _GENERATION,
    _RECORD,
    _TEMPLATE,
    token=_TOKEN,
    profile=_PROFILE,
    scope=_SCOPE,
    bounds=refinement_bounds(),
)
_WHEEL = next(
    candidate for candidate in _REFINEMENT.refined
    if candidate.path.seed_class is SeedClass.WHEEL
)
_NON_WHEEL = next(
    candidate for candidate in _REFINEMENT.refined
    if candidate.path.seed_class is SeedClass.NON_WHEEL
)


@dataclass(frozen=True)
class CommonScoringCase:
    equal_offsets: tuple[tuple[float, float], tuple[float, float]]
    low_offset_x: float
    wheel_offset_x: float
    delta_z_cam: float
    roof_height_m: float
    reverse_evaluation: bool
    reverse_generation: bool


@st.composite
def common_scoring_cases(draw):
    quarter = lambda value: float(value) / 4.0
    equal_offsets = tuple(
        (
            quarter(draw(st.integers(min_value=-16, max_value=16))),
            quarter(draw(st.integers(min_value=-16, max_value=16))),
        )
        for _ in range(2)
    )
    return CommonScoringCase(
        equal_offsets=equal_offsets,
        low_offset_x=quarter(draw(st.integers(min_value=-2, max_value=2))),
        wheel_offset_x=quarter(draw(st.integers(min_value=12, max_value=28)))
        * draw(st.sampled_from((-1.0, 1.0))),
        delta_z_cam=float(draw(st.integers(min_value=-20, max_value=20))) / 100.0,
        roof_height_m=float(draw(st.integers(min_value=120, max_value=180))) / 100.0,
        reverse_evaluation=draw(st.booleans()),
        reverse_generation=draw(st.booleans()),
    )


def _with_offsets(candidate, offsets, nuisance, center):
    observation_by_id = {
        observation.observation_id: observation for observation in _RECORD.observations
    }
    offset_by_id = {
        correspondence.observation_id: offset
        for correspondence, offset in zip(candidate.path.correspondence, offsets)
    }
    predictions = tuple(
        replace(
            prediction,
            pixel=(
                observation_by_id[prediction.observation_id].pixel[0]
                + offset_by_id[prediction.observation_id][0],
                observation_by_id[prediction.observation_id].pixel[1]
                + offset_by_id[prediction.observation_id][1],
            ),
        )
        for prediction in candidate.predictions
    )
    nuisance_by_name = dict(nuisance.values)
    parameter_values = tuple(
        (name, nuisance_by_name.get(name, value))
        for name, value in candidate.parameter_values
    )
    return replace(
        candidate,
        pose=Pose2D(center_sat_px=center, heading_rad_unwrapped=0.0),
        nuisance=nuisance,
        predictions=predictions,
        parameter_values=parameter_values,
        pixel_residual_components=tuple(
            component for offset in offsets for component in offset
        ),
        observability_failures=(),
    )


def _refinement_for(candidates, *, reverse_generation):
    ordered = tuple(candidates)
    generation = _REFINEMENT.generation
    if reverse_generation:
        generation = replace(
            generation,
            report=replace(
                generation.report,
                generated_paths=tuple(reversed(generation.report.generated_paths)),
                stable_order=tuple(reversed(generation.report.stable_order)),
            ),
            hypotheses=tuple(reversed(generation.hypotheses)),
        )
    path_ids = tuple(candidate.path.path_id for candidate in ordered)
    return replace(
        _REFINEMENT,
        generation=generation,
        sampled_path_ids=path_ids,
        retained_path_ids=path_ids,
        refined=ordered,
        failures=(),
        skipped_path_ids=(),
    )


def _score(candidates, *, reverse_generation):
    return CommonSupportScorer().evaluate(
        _refinement_for(candidates, reverse_generation=reverse_generation),
        _RECORD,
        _TEMPLATE,
        token=_TOKEN,
        profile=_PROFILE,
        scope=_SCOPE,
    )


def _select(scoring):
    return OrderedGateSelector().select(
        scoring,
        _RECORD,
        _TEMPLATE,
        token=_TOKEN,
        profile=_PROFILE,
        scope=_SCOPE,
    )


def _residual_signature(scored):
    return tuple(
        (residual.residual_px, residual.magnitude_px, residual.in_support)
        for residual in scored.support.residuals
    )


@deterministic_property(4)
@given(common_scoring_cases())
def test_common_scoring_permits_a_non_wheel_winner(case: CommonScoringCase) -> None:
    """**Validates: Requirements 1.18, 4.11, 4.17-4.18, 5.10**"""
    nuisance = NuisanceVector(values=(
        ("delta_z_cam", case.delta_z_cam),
        ("roof_height_m", case.roof_height_m),
    ))

    equal_candidates = (
        _with_offsets(_WHEEL, case.equal_offsets, nuisance, (20.0, 0.0)),
        _with_offsets(_NON_WHEEL, case.equal_offsets, nuisance, (0.0, 0.0)),
    )
    if case.reverse_evaluation:
        equal_candidates = tuple(reversed(equal_candidates))
    equal_scoring = _score(
        equal_candidates, reverse_generation=case.reverse_generation,
    )
    equal_by_class = {
        candidate.path.seed_class: candidate for candidate in equal_scoring.evaluated
    }
    wheel_equal = equal_by_class[SeedClass.WHEEL]
    non_wheel_equal = equal_by_class[SeedClass.NON_WHEEL]

    assert _residual_signature(wheel_equal) == _residual_signature(non_wheel_equal)
    assert len(wheel_equal.support.support_observation_ids) == len(
        non_wheel_equal.support.support_observation_ids
    )
    assert wheel_equal.support_accepted == non_wheel_equal.support_accepted
    assert (
        wheel_equal.score_components.bounded_nuisance_prior_cost
        == non_wheel_equal.score_components.bounded_nuisance_prior_cost
    )
    assert wheel_equal.score_components == non_wheel_equal.score_components
    assert wheel_equal.score == non_wheel_equal.score
    assert wheel_equal.support.visible_wheel_count == 2
    assert non_wheel_equal.support.visible_wheel_count == 0

    equal_result = _select(equal_scoring)
    assert equal_result.status is LocalizationStatus.REJECTED
    assert equal_result.reason == "ambiguous_equal_score"
    assert equal_result.authoritative_position_sat_px is None

    low_offsets = ((case.low_offset_x, 0.0),) * 2
    wheel_offsets = ((case.wheel_offset_x, 0.0),) * 2
    winning_candidates = (
        _with_offsets(_WHEEL, wheel_offsets, nuisance, (20.0, 0.0)),
        _with_offsets(_NON_WHEEL, low_offsets, nuisance, (0.0, 0.0)),
    )
    if case.reverse_evaluation:
        winning_candidates = tuple(reversed(winning_candidates))
    winning_scoring = _score(
        winning_candidates, reverse_generation=case.reverse_generation,
    )
    winning_by_class = {
        candidate.path.seed_class: candidate for candidate in winning_scoring.evaluated
    }
    wheel = winning_by_class[SeedClass.WHEEL]
    non_wheel = winning_by_class[SeedClass.NON_WHEEL]
    assert wheel.support_accepted and non_wheel.support_accepted
    assert wheel.support.visible_wheel_count == 2
    assert non_wheel.support.visible_wheel_count == 0
    assert non_wheel.score < wheel.score
    assert wheel.score - non_wheel.score >= _PROFILE.optimizer.ambiguity.margin_absolute

    result = _select(winning_scoring)
    record_failure_metadata(
        replay_identity=_RECORD,
        profile_identity=_PROFILE,
        run_identity=result,
    )
    assert result.status is LocalizationStatus.ACCEPTED
    assert result.usable
    assert result.reason is None
    assert result.decisive_gate == "accepted"
    assert result.diagnostics.selected_path == non_wheel.path.path_id
    assert result.authoritative_position_sat_px == (0.0, 0.0)
    assert result.diagnostic_position_sat_px is None
    assert result.diagnostics.hypothesis_margin == wheel.score - non_wheel.score


class CommonScoringNonWheelWinnerPropertyTest(unittest.TestCase):
    def test_property_4(self) -> None:
        test_common_scoring_permits_a_non_wheel_winner()


if __name__ == "__main__":
    unittest.main()
