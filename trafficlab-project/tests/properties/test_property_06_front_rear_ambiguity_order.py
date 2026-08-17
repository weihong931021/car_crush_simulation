"""Property 6: front/rear alternatives never resolve ambiguity by order."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import unittest

from hypothesis import given, strategies as st

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.test_haware_hypotheses import configured_profile, record, scope, seed_profile, template
from tests.test_haware_optimizer import optimizer_profile, refinement_bounds
from trafficlab.motion.haware_accuracy.models import (
    HypothesisState,
    LocalizationStatus,
    Pose2D,
    ProjectionPrediction,
    ResidualDiagnostic,
    SeedClass,
    SemanticPath,
    TrackKind,
    TrackProvenance,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read
from trafficlab.motion.haware_hypotheses import DirectImageHypothesisGenerator
from trafficlab.motion.haware_optimizer import (
    BoundedScipyRefiner,
    CommonScoreComponents,
    CommonSupportScorer,
    OrderedGateSelector,
    SupportDiagnostics,
)
from trafficlab.projection.haware_forward import HawareForwardProjector


@dataclass(frozen=True)
class AmbiguityCase:
    mode: str
    order: tuple[int, ...]
    chain_fraction: float
    margin_fraction: float
    origin: tuple[float, float]
    heading_rad: float
    motion_favorite: int


@st.composite
def ambiguity_cases(draw):
    return AmbiguityCase(
        mode=draw(st.sampled_from(("equal", "insufficient_margin"))),
        order=tuple(draw(st.permutations(range(6)))),
        chain_fraction=draw(st.integers(min_value=55, max_value=90)) / 100.0,
        margin_fraction=draw(st.integers(min_value=1, max_value=9)) / 10.0,
        origin=(
            draw(st.integers(min_value=-4000, max_value=4000)) / 4.0,
            draw(st.integers(min_value=-4000, max_value=4000)) / 4.0,
        ),
        heading_rad=draw(st.integers(min_value=-720, max_value=720)) * math.pi / 360.0,
        motion_favorite=draw(st.integers(min_value=0, max_value=5)),
    )


def _fixture():
    """Build one genuine generated/refined/scored fixture for all examples."""
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
    assert scoring.supported, "Property 6 fixture must reach common scoring"
    return profile_value, scope_value, token, template_value, record_value, generation, scoring


_PROFILE, _SCOPE, _TOKEN, _TEMPLATE, _RECORD, _GENERATION, _BASE_SCORING = _fixture()


def _semantic_source(semantic_path: SemanticPath):
    return next(
        path
        for path in _GENERATION.report.authorized_paths
        if path.semantic_path is semantic_path
    )


def _path_set():
    normal = _semantic_source(SemanticPath.NORMAL)
    reversed_path = _semantic_source(SemanticPath.REVERSED)
    heading_pi = _semantic_source(SemanticPath.HEADING_PI)
    normal_a = replace(normal, path_id="property-6-normal-a")
    normal_b = replace(
        normal,
        path_id="property-6-normal-b",
        seed_class=(
            SeedClass.NON_WHEEL
            if normal.seed_class is SeedClass.WHEEL
            else SeedClass.WHEEL
        ),
        initialization_source=replace(
            normal.initialization_source,
            method="property-6-second-initializer",
            source_cell="property-6-cell-b",
        ),
    )
    normal_c = replace(
        normal,
        path_id="property-6-normal-c",
        initialization_source=replace(
            normal.initialization_source,
            method="property-6-third-initializer",
            source_cell="property-6-cell-c",
            start_heading_rad=(normal.initialization_source.start_heading_rad or 0.0)
            + 2.0 * math.pi,
        ),
    )
    reversed_a = replace(reversed_path, path_id="property-6-reversed-a")
    reversed_b = replace(
        reversed_path,
        path_id="property-6-reversed-b",
        initialization_source=replace(
            reversed_path.initialization_source,
            method="property-6-reversed-second-initializer",
            source_cell="property-6-cell-r",
        ),
    )
    heading = replace(heading_pi, path_id="property-6-heading-pi")
    return tuple(
        replace(path, terminal_state=HypothesisState.SCORED, terminal_reason=None)
        for path in (
            normal_a,
            normal_b,
            normal_c,
            reversed_a,
            reversed_b,
            heading,
        )
    )


def _predictions(path, shift):
    observations = {item.observation_id: item for item in _RECORD.observations}
    return tuple(
        ProjectionPrediction(
            observation_id=item.observation_id,
            template_semantic_id=item.template_semantic_id,
            pixel=(
                observations[item.observation_id].pixel[0] + shift[0],
                observations[item.observation_id].pixel[1] + shift[1],
            ),
            valid=True,
        )
        for item in path.correspondence
    )


def _support(path):
    observation_ids = tuple(item.observation_id for item in path.correspondence)
    return SupportDiagnostics(
        residuals=tuple(
            ResidualDiagnostic(
                observation_id=observation_id,
                residual_px=(0.0, 0.0),
                magnitude_px=0.0,
                in_support=True,
            )
            for observation_id in observation_ids
        ),
        support_observation_ids=observation_ids,
        outlier_observation_ids=(),
        authorized_observation_count=len(observation_ids),
        minimum_support=len(observation_ids),
        support_boundary_px=_PROFILE.optimizer.robust.support_boundary_px,
        support_includes_equality=_PROFILE.optimizer.robust.support_includes_equality,
        visible_wheel_count=sum(
            "wheel" in item.template_semantic_id for item in path.correspondence
        ),
    )


def _candidate(path, *, center, heading, shift, score):
    base = _BASE_SCORING.supported[0]
    refinement = replace(
        base.refinement,
        path=path,
        pose=Pose2D(center_sat_px=center, heading_rad_unwrapped=heading),
        predictions=_predictions(path, shift),
        observability_failures=(),
    )
    return replace(
        base,
        refinement=refinement,
        path=path,
        support=_support(path),
        score_components=CommonScoreComponents(
            robust_residual_loss=score,
            outlier_penalty_cost=0.0,
            bounded_nuisance_prior_cost=0.0,
            weighted_nuisance_prior_cost=0.0,
            total=score,
        ),
        support_accepted=True,
        rejection_reason=None,
        minimum_configuration_id="property-6-complete-evaluation",
    )


def _scoring(case: AmbiguityCase):
    paths = _path_set()
    equivalence = _PROFILE.optimizer.equivalence
    position_step_px = (
        equivalence.position_tolerance_m
        * _PROFILE.calibration.snapshot.pixels_per_metre
        * case.chain_fraction
    )
    prediction_step_px = equivalence.prediction_tolerance_px * case.chain_fraction
    margin = _PROFILE.optimizer.ambiguity.margin_absolute
    alternative_score = (
        1.0
        if case.mode == "equal"
        else 1.0 + margin * case.margin_fraction
    )
    heading_score = 1.0 if case.mode == "equal" else 3.0
    x, y = case.origin
    specifications = (
        ((x, y), case.heading_rad, (0.0, 0.0), 1.0),
        ((x + position_step_px, y), case.heading_rad, (prediction_step_px, 0.0), 2.0),
        ((x + 2.0 * position_step_px, y), case.heading_rad, (2.0 * prediction_step_px, 0.0), 3.0),
        ((x + 20.0, y), case.heading_rad, (10.0, 0.0), alternative_score),
        ((x + 20.0 + position_step_px, y), case.heading_rad, (10.0 + prediction_step_px, 0.0), alternative_score + 1.0),
        ((x - 20.0, y), case.heading_rad + math.pi, (-10.0, 0.0), heading_score),
    )
    candidates = tuple(
        _candidate(
            path,
            center=center,
            heading=heading,
            shift=shift,
            score=score,
        )
        for path, (center, heading, shift, score) in zip(paths, specifications)
    )

    path_ids = tuple(path.path_id for path in paths)
    generation_report = replace(
        _BASE_SCORING.refinement.generation.report,
        authorized_paths=paths,
        generated_paths=paths,
        budget_exclusions=(),
        stable_order=path_ids,
    )
    generation = replace(
        _BASE_SCORING.refinement.generation,
        report=generation_report,
        hypotheses=(),
        invalid_paths=(),
    )
    refinement = replace(
        _BASE_SCORING.refinement,
        generation=generation,
        sampled_path_ids=path_ids,
        retained_path_ids=path_ids,
        refined=tuple(item.refinement for item in candidates),
        failures=(),
        skipped_path_ids=(),
    )
    return replace(
        _BASE_SCORING,
        refinement=refinement,
        evaluated=candidates,
    ), candidates


def _select(scoring, record_value):
    return OrderedGateSelector().select(
        scoring,
        record_value,
        _TEMPLATE,
        token=_TOKEN,
        profile=_PROFILE,
        scope=_SCOPE,
    )


def _real_track_record():
    return replace(
        _RECORD,
        track=TrackProvenance(
            claimed_id="property-6-real-track",
            tracker_name="property-6-tracker",
            tracker_version="1",
            source_sequence=_RECORD.source_sequence,
            association_provenance="property-6-association",
            observed_frames=("frame-before", _RECORD.frame_id, "frame-after"),
            kind=TrackKind.REAL,
        ),
    )


def _assert_path_provenance(result, candidates):
    retained = {item.path_id: item for item in result.diagnostics.paths}
    assert set(retained) == {item.path.path_id for item in candidates}
    for candidate in candidates:
        source = candidate.path
        diagnostic = retained[source.path_id]
        assert diagnostic.semantic_path is source.semantic_path
        assert diagnostic.correspondence == source.correspondence
        assert diagnostic.cue_subset == source.cue_subset
        assert diagnostic.seed_class is source.seed_class
        assert diagnostic.minimal_observations == source.minimal_observations
        assert diagnostic.initialization_source == source.initialization_source


# Feature: haware-localization-accuracy, Property 6: Front/rear alternatives never resolve ambiguity by order
@deterministic_property(6)
@given(case=ambiguity_cases())
def test_front_rear_alternatives_never_resolve_ambiguity_by_order(case) -> None:
    """**Validates: Requirements 2.22-2.23, 5.2-5.4, 5.13-5.17, 6.22-6.24, 6.29, 8.9**"""
    scoring, candidates = _scoring(case)

    # Margin necessity is latched from the initial unique set.  A later gate on
    # the next-best representative remains diagnostic and cannot remove the
    # required frame-local margin rejection (Requirement 6.23).
    if case.mode == "insufficient_margin":
        later_rejected = replace(
            candidates[3],
            refinement=replace(
                candidates[3].refinement,
                observability_failures=("unobservable_pose",),
            ),
        )
        candidates = (*candidates[:3], later_rejected, *candidates[4:])
        scoring = replace(
            scoring,
            refinement=replace(
                scoring.refinement,
                refined=tuple(item.refinement for item in candidates),
            ),
            evaluated=candidates,
        )

    result = _select(scoring, _RECORD)
    record_failure_metadata(
        replay_identity=_RECORD,
        profile_identity=_PROFILE,
        run_identity=result,
    )

    generated_ids = tuple(
        item.path_id for item in scoring.refinement.generation.report.generated_paths
    )
    evaluated_ids = tuple(item.path.path_id for item in scoring.evaluated)
    assert set(generated_ids) == set(evaluated_ids)
    assert len(generated_ids) == len(evaluated_ids) == 6
    assert {item.path.semantic_path for item in scoring.evaluated} == set(SemanticPath)
    assert all(item.support_accepted for item in scoring.evaluated)

    observations = {item.observation_id: item for item in _RECORD.observations}
    for candidate in scoring.evaluated:
        for correspondence in candidate.path.correspondence:
            assert correspondence.candidate_label_provenance == observations[
                correspondence.observation_id
            ].candidate_labels
            assert observations[correspondence.observation_id].confidence == 1.0
    normal_mapping = {
        item.observation_id: item.template_semantic_id
        for item in next(
            candidate.path
            for candidate in scoring.evaluated
            if candidate.path.semantic_path is SemanticPath.NORMAL
        ).correspondence
    }
    reversed_mapping = {
        item.observation_id: item.template_semantic_id
        for item in next(
            candidate.path
            for candidate in scoring.evaluated
            if candidate.path.semantic_path is SemanticPath.REVERSED
        ).correspondence
    }
    assert normal_mapping != reversed_mapping

    components = {frozenset(component) for component in result.diagnostics.merged_components}
    normal_component = frozenset(
        ("property-6-normal-a", "property-6-normal-b", "property-6-normal-c")
    )
    reversed_component = frozenset(
        ("property-6-reversed-a", "property-6-reversed-b")
    )
    assert normal_component in components
    assert reversed_component in components
    assert set().union(*components) == set(generated_ids)

    paths = {item.path_id: item for item in result.diagnostics.paths}
    assert paths["property-6-normal-b"].terminal_state is HypothesisState.MERGED
    assert paths["property-6-normal-c"].terminal_state is HypothesisState.MERGED
    assert paths["property-6-normal-b"].terminal_reason == "merged_into:property-6-normal-a"
    assert paths["property-6-normal-c"].terminal_reason == "merged_into:property-6-normal-a"
    assert paths["property-6-reversed-b"].terminal_state is HypothesisState.MERGED
    assert paths["property-6-reversed-b"].terminal_reason == "merged_into:property-6-reversed-a"
    _assert_path_provenance(result, candidates)

    assert result.status is LocalizationStatus.REJECTED
    assert not result.usable
    assert result.authoritative_position_sat_px is None
    assert result.diagnostic_position_sat_px is not None
    if case.mode == "equal":
        assert result.reason == "ambiguous_equal_score"
        assert result.diagnostics.hypothesis_margin == 0.0
        assert "ambiguous_equal_score" in result.diagnostics.gate_failures
    else:
        assert result.reason == "ambiguous_hypotheses"
        assert 0.0 < result.diagnostics.hypothesis_margin < _PROFILE.optimizer.ambiguity.margin_absolute
        assert "unobservable_pose" in result.diagnostics.gate_failures
    assert "ambiguous_hypotheses" in result.diagnostics.gate_failures

    # Once equivalent initializations collapse to exactly one unique pose, no
    # margin is required (Requirement 6.22), while every merged initializer and
    # its semantic/cue/seed provenance remains in diagnostics.
    single_candidates = candidates[:3]
    single_paths = tuple(item.path for item in single_candidates)
    single_ids = tuple(item.path_id for item in single_paths)
    single_generation = replace(
        scoring.refinement.generation,
        report=replace(
            scoring.refinement.generation.report,
            authorized_paths=single_paths,
            generated_paths=single_paths,
            budget_exclusions=(),
            stable_order=single_ids,
        ),
        hypotheses=(),
        invalid_paths=(),
    )
    single_refinement = replace(
        scoring.refinement,
        generation=single_generation,
        sampled_path_ids=single_ids,
        retained_path_ids=single_ids,
        refined=tuple(item.refinement for item in single_candidates),
        failures=(),
        skipped_path_ids=(),
    )
    single_scoring = replace(
        scoring,
        refinement=single_refinement,
        evaluated=single_candidates,
    )
    single_result = _select(single_scoring, _RECORD)
    assert single_result.status is LocalizationStatus.ACCEPTED
    assert single_result.diagnostics.hypothesis_margin is None
    assert single_result.diagnostics.merged_components == (single_ids,)
    _assert_path_provenance(single_result, single_candidates)

    permuted_candidates = tuple(candidates[index] for index in case.order)
    permuted_refinement = replace(
        scoring.refinement,
        refined=tuple(item.refinement for item in permuted_candidates),
        sampled_path_ids=tuple(item.path.path_id for item in permuted_candidates),
        retained_path_ids=tuple(item.path.path_id for item in permuted_candidates),
    )
    permuted_scoring = replace(
        scoring,
        refinement=permuted_refinement,
        evaluated=permuted_candidates,
    )
    assert _select(permuted_scoring, _RECORD).canonical_bytes() == result.canonical_bytes()

    # Motion remains diagnostic-only: even a validated real track and an output
    # favoring any path may at most alter presentation order, never frame-local
    # ambiguity authority.  Promote the generated favorite to the front to model
    # the strongest ordering influence such an output could attempt.
    favorite = candidates[case.motion_favorite]
    motion_order = (favorite,) + tuple(
        item for item in reversed(candidates) if item.path.path_id != favorite.path.path_id
    )
    motion_refinement = replace(
        scoring.refinement,
        refined=tuple(item.refinement for item in motion_order),
        sampled_path_ids=tuple(item.path.path_id for item in motion_order),
        retained_path_ids=tuple(item.path.path_id for item in motion_order),
    )
    motion_scoring = replace(
        scoring,
        refinement=motion_refinement,
        evaluated=motion_order,
    )
    motion_result = _select(motion_scoring, _real_track_record())
    assert motion_result.canonical_bytes() == result.canonical_bytes()
    assert motion_result.reason == result.reason
    assert motion_result.authoritative_position_sat_px is None


class FrontRearAmbiguityOrderPropertyTest(unittest.TestCase):
    def test_property_6(self) -> None:
        test_front_rear_alternatives_never_resolve_ambiguity_by_order()


if __name__ == "__main__":
    unittest.main()
