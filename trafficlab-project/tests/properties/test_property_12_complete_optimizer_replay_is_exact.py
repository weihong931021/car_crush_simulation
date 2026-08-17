"""Property 12: complete optimizer replay is exact."""
from __future__ import annotations

from dataclasses import replace
import json
import unittest

from hypothesis import given, strategies as st

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.property_support.strategies import bounded_floats
from tests.test_haware_hypotheses import (
    configured_profile,
    record,
    scope,
    seed_profile,
    template,
)
from tests.test_haware_optimizer import refinement_bounds
from trafficlab.io.haware_observation_replay import (
    AcceptedReplayRecord,
    ObservationReplayReader,
    ObservationReplayWriter,
)
from trafficlab.motion.haware_accuracy.models import (
    ClosedInterval,
    ContentIdentity,
    LocalizationStatus,
    NuisanceField,
    NuisanceProfile,
    canonical_bytes,
    canonical_order,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read
from trafficlab.motion.haware_hypotheses import DirectImageHypothesisGenerator
from trafficlab.motion.haware_optimizer import (
    BoundedScipyRefiner,
    CommonSupportScorer,
    OrderedGateSelector,
)
from trafficlab.projection.haware_forward import HawareForwardProjector


def _refinement_profile():
    """Return the frozen Acceptance Profile this property replays against.

    ``configured_profile()`` is a generation fixture: it declares non-fixed roof
    height evidence without the matching bounded nuisance coordinate, and its
    ``parameter_scale`` does not carry the per-field scales, so every hypothesis
    fails at ``invalid_refinement_parameterization`` and nothing reaches
    scoring or selection. Property 12 must compare real refinements, so the
    profile is completed here and then held fixed; the replay content is the
    generated axis, exactly as the property states.
    """
    value = configured_profile()
    fields = (
        NuisanceField(
            name="vehicle_width",
            unit="m",
            bounds=ClosedInterval(lower=1.0, upper=2.5),
            scale=0.25,
            prior=None,
        ),
        NuisanceField(
            name="delta_z_cam",
            unit="m",
            bounds=ClosedInterval(lower=-0.3, upper=0.3),
            scale=0.05,
            prior=None,
        ),
        NuisanceField(
            name="roof_height_m",
            unit="m",
            bounds=ClosedInterval(lower=1.2, upper=1.8),
            scale=0.1,
            prior=None,
        ),
    )
    optimizer = replace(
        value.optimizer,
        sampled_candidate_budget=4,
        retained_candidate_count=4,
        optimizer=replace(
            value.optimizer.optimizer,
            parameter_scale=(1.0, 1.0, 1.0, 0.25, 0.05, 0.1),
        ),
    )
    return replace(
        value,
        nuisance=NuisanceProfile(version="property-12-nuisance-v1", fields=fields),
        optimizer=optimizer,
    )


_PROFILE = _refinement_profile()
_SCOPE = scope()
_TOKEN = validate_before_read(_PROFILE, _SCOPE)
_TEMPLATE = template()
_BASE_RECORD = record(_PROFILE, _TEMPLATE)
_SEED_PROFILE = seed_profile()
_BOUNDS = refinement_bounds()
_READER = ObservationReplayReader()
_WRITER = ObservationReplayWriter()
_OBSERVATION_COUNT = len(_BASE_RECORD.observations)


def _in_image(value: float, limit: int) -> float:
    """Keep a jittered coordinate inside the frozen image bounds.

    Base pixels sit near the image origin, so unclamped jitter can push a
    coordinate negative. Such an observation is a contract violation that the
    replay layer legitimately drops, which would silently change the content
    under test instead of exercising replay exactness.
    """
    return min(max(value, 1.0), float(limit) - 1.0)


def _content_variant(jitter, confidences, identifier_prefix):
    """Return one replay content variant of the frozen base record.

    Only observation identity, pixel, and confidence vary. Identifiers are part
    of the canonical sort value, so varying their prefix moves observations to
    different normalized positions without changing what was observed.
    """
    width, height = _BASE_RECORD.image_size_px
    observations = tuple(
        replace(
            item,
            observation_id=f"{identifier_prefix}-{index}",
            pixel=(
                _in_image(item.pixel[0] + jitter[index][0], width),
                _in_image(item.pixel[1] + jitter[index][1], height),
            ),
            confidence=confidences[index],
        )
        for index, item in enumerate(_BASE_RECORD.observations)
    )
    return replace(_BASE_RECORD, observations=observations)


def _digest(payload: bytes) -> str:
    return ContentIdentity.for_bytes(payload).digest


def _replay_bytes(record_value):
    return _WRITER.canonical_bytes(
        (record_value,), token=_TOKEN, profile=_PROFILE, scope=_SCOPE
    )


def _read_single(payload):
    items = _READER.read(payload, token=_TOKEN, profile=_PROFILE, scope=_SCOPE)
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, AcceptedReplayRecord), item
    return item.record


def _repermuted_bytes(payload, order):
    """Re-present the identical observations in a different serialized order.

    Canonical serialization preserves list order, so the permutation survives
    into the reader and exercises normalization rather than being undone here.
    """
    envelope = json.loads(payload.decode("utf-8"))
    observations = envelope["records"][0]["observations"]
    envelope["records"][0]["observations"] = [observations[index] for index in order]
    return canonical_bytes(envelope)


def _run(record_value):
    """Run the complete generation, refinement, scoring, and selection chain."""
    projector = HawareForwardProjector()
    generation = DirectImageHypothesisGenerator(projector).generate(
        record_value,
        _TEMPLATE,
        token=_TOKEN,
        profile=_PROFILE,
        scope=_SCOPE,
        seed_profile=_SEED_PROFILE,
    )
    refinement = BoundedScipyRefiner(projector).refine(
        generation,
        record_value,
        _TEMPLATE,
        token=_TOKEN,
        profile=_PROFILE,
        scope=_SCOPE,
        bounds=_BOUNDS,
    )
    scoring = CommonSupportScorer().evaluate(
        refinement, record_value, _TEMPLATE, token=_TOKEN, profile=_PROFILE, scope=_SCOPE
    )
    result = OrderedGateSelector().select(
        scoring, record_value, _TEMPLATE, token=_TOKEN, profile=_PROFILE, scope=_SCOPE
    )
    return generation, refinement, scoring, result


def _terminal_states(generation, result):
    """Return one terminal state per accounted path, from both reports."""
    generated = {
        path.path_id: (path.terminal_state, path.terminal_reason)
        for path in generation.report.generated_paths
    }
    excluded = {
        path.path_id: (path.terminal_state, path.terminal_reason)
        for path in generation.report.budget_exclusions
    }
    finalized = {
        path.path_id: (path.terminal_state, path.terminal_reason)
        for path in result.diagnostics.paths
    }
    return generated, excluded, finalized


def _support_fingerprint(scoring):
    return {
        candidate.path.path_id: (
            candidate.support_accepted,
            candidate.rejection_reason,
            candidate.support.support_observation_ids,
            candidate.support.outlier_observation_ids,
            candidate.support.authorized_observation_count,
            candidate.support.visible_wheel_count,
            candidate.score,
        )
        for candidate in scoring.evaluated
    }


def _pose_fingerprint(result):
    """Return pose floats verbatim; Property 12 requires exact reproduction."""
    return (
        result.authoritative_position_sat_px,
        result.diagnostic_position_sat_px,
        result.heading_deg,
    )


def _assert_identical(left, right, *, context):
    """Assert every value Property 12 names is reproduced exactly."""
    left_generation, left_scoring, left_result = left
    right_generation, right_scoring, right_result = right

    assert left_result.canonical_bytes() == right_result.canonical_bytes(), context
    assert left_result.status is right_result.status, context
    assert left_result.usable == right_result.usable, context
    assert left_result.decisive_gate == right_result.decisive_gate, context
    assert left_result.reason == right_result.reason, context
    assert _pose_fingerprint(left_result) == _pose_fingerprint(right_result), context

    left_diagnostics = left_result.diagnostics
    right_diagnostics = right_result.diagnostics
    assert (
        left_diagnostics.normalized_observations
        == right_diagnostics.normalized_observations
    ), context
    assert left_diagnostics.selected_path == right_diagnostics.selected_path, context
    assert (
        left_diagnostics.hypothesis_margin == right_diagnostics.hypothesis_margin
    ), context
    assert left_diagnostics.spread_m == right_diagnostics.spread_m, context
    assert left_diagnostics.gate_failures == right_diagnostics.gate_failures, context
    assert (
        left_diagnostics.merged_components == right_diagnostics.merged_components
    ), context
    assert left_diagnostics.exclusions == right_diagnostics.exclusions, context

    assert _terminal_states(left_generation, left_result) == _terminal_states(
        right_generation, right_result
    ), context
    assert _support_fingerprint(left_scoring) == _support_fingerprint(
        right_scoring
    ), context


@st.composite
def replay_presentations(draw):
    """Draw one replay content variant plus an equivalent presentation order."""
    jitter = tuple(
        (draw(bounded_floats(-1.0, 1.0)), draw(bounded_floats(-1.0, 1.0)))
        for _ in range(_OBSERVATION_COUNT)
    )
    confidences = tuple(
        draw(bounded_floats(0.05, 1.0)) for _ in range(_OBSERVATION_COUNT)
    )
    identifier_prefix = draw(st.sampled_from(("obs", "a", "zz", "觀測")))
    order = draw(st.permutations(range(_OBSERVATION_COUNT)))
    return jitter, confidences, identifier_prefix, tuple(order)


# Feature: haware-localization-accuracy, Property 12: Complete optimizer replay is exact
@deterministic_property(12)
@given(presentation=replay_presentations())
def test_complete_optimizer_replay_is_exact(presentation) -> None:
    jitter, confidences, identifier_prefix, order = presentation
    record_value = _content_variant(jitter, confidences, identifier_prefix)

    payload = _replay_bytes(record_value)
    assert payload == _replay_bytes(record_value)

    replayed = _read_single(payload)
    record_failure_metadata(
        replay_identity=_digest(payload),
        profile_identity=_PROFILE,
        run_identity=replayed,
    )

    # Normalized order follows the canonical value rule, not presentation order
    # and not the observation identifier sequence.
    assert replayed.observations == canonical_order(replayed.observations)
    assert {item.observation_id for item in replayed.observations} == {
        f"{identifier_prefix}-{index}" for index in range(_OBSERVATION_COUNT)
    }

    permuted_payload = _repermuted_bytes(payload, order)
    permuted = _read_single(permuted_payload)
    assert permuted == replayed
    assert permuted.canonical_bytes() == replayed.canonical_bytes()

    first_generation, first_refinement, first_scoring, first_result = _run(replayed)
    second_generation, _, second_scoring, second_result = _run(replayed)
    permuted_generation, _, permuted_scoring, permuted_result = _run(permuted)

    # The example is only meaningful when the chain actually produced work.
    # `test_the_replayed_fixture_reaches_a_selected_pose` guards the stronger
    # claim that this fixture can reach acceptance at all, so a future profile
    # or fixture change cannot turn this property vacuous in silence.
    assert first_generation.hypotheses
    assert first_generation.report.generated_paths
    assert first_refinement.refined or first_refinement.failures

    _assert_identical(
        (first_generation, first_scoring, first_result),
        (second_generation, second_scoring, second_result),
        context="repeated execution of identical replay bytes",
    )
    _assert_identical(
        (first_generation, first_scoring, first_result),
        (permuted_generation, permuted_scoring, permuted_result),
        context="equivalent presentation of the same observations",
    )

    seed_value = _PROFILE.optimizer.deterministic_seed
    for candidate in first_scoring.evaluated:
        assert candidate.refinement.settings.deterministic_seed == seed_value



class CompleteOptimizerReplayIsExactPropertyTest(unittest.TestCase):
    def test_complete_optimizer_replay_is_exact(self):
        test_complete_optimizer_replay_is_exact()

    def test_the_replayed_fixture_reaches_a_selected_pose(self):
        """Fail loudly if the property degenerates into comparing empty runs."""
        replayed = _read_single(
            _replay_bytes(
                _content_variant(((0.0, 0.0),) * _OBSERVATION_COUNT, (0.9,) * _OBSERVATION_COUNT, "obs")
            )
        )
        generation, refinement, scoring, result = _run(replayed)
        self.assertEqual(len(replayed.observations), _OBSERVATION_COUNT)
        self.assertTrue(generation.hypotheses)
        self.assertTrue(refinement.refined)
        self.assertTrue(scoring.evaluated)
        self.assertTrue(any(item.support_accepted for item in scoring.evaluated))
        self.assertIs(result.status, LocalizationStatus.ACCEPTED)
        self.assertIsNotNone(result.diagnostics.selected_path)
        self.assertIsNotNone(result.authoritative_position_sat_px)
        self.assertIsNotNone(result.heading_deg)


if __name__ == "__main__":
    unittest.main()
