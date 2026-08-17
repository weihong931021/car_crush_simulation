"""Focused tests for deterministic bounded Haware refinement."""
import ast
import math
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.optimize import least_squares as scipy_least_squares

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_haware_hypotheses import (  # noqa: E402
    configured_profile,
    record,
    seed_profile,
    template,
)
from tests.test_haware_profile_validation import scope  # noqa: E402
from trafficlab.motion.haware_accuracy.models import (  # noqa: E402
    ClosedInterval,
    GaussianPrior,
    HypothesisState,
    LocalizationStatus,
    NuisanceField,
    NuisanceProfile,
    NuisanceVector,
    ObservabilitySettings,
    Pose2D,
    ProviderProvenance,
    SeedClass,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read  # noqa: E402
from trafficlab.motion.haware_hypotheses import DirectImageHypothesisGenerator  # noqa: E402
from trafficlab.motion.haware_optimizer import (  # noqa: E402
    BoundedScipyRefiner,
    CommonScoreComponents,
    CommonSupportScorer,
    ObservabilityCalculationError,
    OrderedGateSelector,
    RefinementBounds,
    _finite_difference_image_jacobian,
    compute_observability_from_linearization,
    resolve_equal_score_positions,
)
from trafficlab.projection.haware_forward import (  # noqa: E402
    HawareForwardProjector,
    ParameterSpec,
    ProjectionBatch,
)


def optimizer_profile():
    value = configured_profile()
    calibration_delta = replace(
        value.nuisance.fields[1],
        prior=GaussianPrior(mean=0.0, standard_deviation=0.1),
    )
    fields = (
        calibration_delta,
        NuisanceField(
            name="roof_height_m",
            unit="m",
            bounds=ClosedInterval(lower=1.2, upper=1.8),
            scale=0.2,
            prior=GaussianPrior(mean=1.5, standard_deviation=0.2),
        ),
    )
    optimizer = replace(
        value.optimizer,
        retained_candidate_count=4,
        optimizer=replace(
            value.optimizer.optimizer,
            parameter_scale=(1.0, 1.0, 1.0, 0.1, 0.2),
        ),
    )
    return replace(
        value,
        nuisance=NuisanceProfile(version="optimizer-test-v1", fields=fields),
        optimizer=optimizer,
    )


def refinement_bounds():
    return RefinementBounds(
        position_delta_x_m=ClosedInterval(lower=-2.0, upper=2.0),
        position_delta_y_m=ClosedInterval(lower=-2.0, upper=2.0),
        heading_delta_rad=ClosedInterval(lower=-0.5, upper=0.5),
        residual_scale_px=1.0,
    )


class InvalidProjectionProjector:
    def predict_pixels(self, pose, template_points, calibration, nuisance=None):
        count = len(template_points)
        return ProjectionBatch(
            pixels=np.zeros((count, 2), dtype=np.float64),
            valid=np.zeros(count, dtype=np.bool_),
            failure_reasons=tuple("synthetic_invalid_projection" for _ in range(count)),
        )


class ExplodingProjector:
    def predict_pixels(self, pose, template_points, calibration, nuisance=None):
        raise RuntimeError("synthetic numerical exception")


class BoundedScipyRefinerTest(unittest.TestCase):
    def setUp(self):
        self.profile = optimizer_profile()
        self.scope = scope()
        self.token = validate_before_read(self.profile, self.scope)
        self.template = template()
        self.record = record(self.profile, self.template)
        self.projector = HawareForwardProjector()
        self.generation = DirectImageHypothesisGenerator(self.projector).generate(
            self.record,
            self.template,
            token=self.token,
            profile=self.profile,
            scope=self.scope,
            seed_profile=seed_profile(),
        )

    def refine(self, projector=None):
        return BoundedScipyRefiner(projector or self.projector).refine(
            self.generation,
            self.record,
            self.template,
            token=self.token,
            profile=self.profile,
            scope=self.scope,
            bounds=refinement_bounds(),
        )

    def test_real_refinement_is_bounded_deterministic_and_non_authoritative(self):
        first = self.refine()
        second = self.refine()
        self.assertEqual(first.canonical_bytes(), second.canonical_bytes())
        self.assertTrue(first.refined)
        self.assertFalse(first.failures)
        self.assertLessEqual(
            len(first.sampled_path_ids), self.profile.optimizer.sampled_candidate_budget
        )
        self.assertLessEqual(
            len(first.retained_path_ids), self.profile.optimizer.retained_candidate_count
        )
        self.assertEqual(
            {candidate.path.seed_class for candidate in first.refined},
            {SeedClass.WHEEL, SeedClass.NON_WHEEL},
        )
        for candidate in first.refined:
            self.assertFalse(candidate.authoritative)
            value_by_name = dict(candidate.parameter_values)
            for name in ("delta_center_x_m", "delta_center_y_m", "delta_heading_rad"):
                self.assertIn(name, value_by_name)
            self.assertGreaterEqual(value_by_name["delta_center_x_m"], -2.0)
            self.assertLessEqual(value_by_name["delta_center_x_m"], 2.0)
            self.assertGreaterEqual(value_by_name["roof_height_m"], 1.2)
            self.assertLessEqual(value_by_name["roof_height_m"], 1.8)
            self.assertNotIn("wheel_height_m", value_by_name)
            self.assertEqual(candidate.settings.deterministic_seed, 1729)
            self.assertEqual(candidate.settings.retention_key, ("seed_residual_rms_px", "path_id"))

    def test_every_numerical_setting_is_passed_explicitly_to_trf(self):
        calls = []

        def recording_solver(*args, **kwargs):
            calls.append(kwargs.copy())
            return scipy_least_squares(*args, **kwargs)

        with patch("trafficlab.motion.haware_optimizer.least_squares", recording_solver):
            result = self.refine()
        self.assertTrue(result.refined)
        self.assertTrue(calls)
        expected = {
            "jac", "bounds", "method", "loss", "f_scale", "diff_step",
            "x_scale", "ftol", "xtol", "gtol", "max_nfev", "tr_solver", "verbose",
        }
        for call in calls:
            self.assertTrue(expected.issubset(call))
            self.assertEqual(call["method"], "trf")
            self.assertEqual(call["loss"], "huber")
            self.assertEqual(call["jac"], "2-point")
            self.assertEqual(call["tr_solver"], "exact")
            self.assertTrue(np.isfinite(call["bounds"][0]).all())
            self.assertTrue(np.isfinite(call["bounds"][1]).all())

    def test_invalid_projections_become_typed_non_authoritative_failures(self):
        result = self.refine(InvalidProjectionProjector())
        self.assertFalse(result.refined)
        self.assertTrue(result.failures)
        for failure in result.failures:
            self.assertFalse(failure.authoritative)
            self.assertIn(failure.reason, {"invalid_projection", "numerical_optimization_failure"})
            self.assertIn("synthetic_invalid_projection", failure.detail)

    def test_numerical_exceptions_become_typed_non_authoritative_failures(self):
        result = self.refine(ExplodingProjector())
        self.assertFalse(result.refined)
        self.assertTrue(result.failures)
        for failure in result.failures:
            self.assertFalse(failure.authoritative)
            self.assertEqual(failure.reason, "numerical_optimization_failure")
            self.assertEqual(failure.exception_type, "RuntimeError")
            self.assertIn("synthetic numerical exception", failure.detail)

    def test_retention_preserves_non_wheel_eligibility_without_score_bonus(self):
        result = self.refine()
        path_by_id = {
            item.path.path_id: item.path for item in self.generation.hypotheses
        }
        retained_classes = {
            path_by_id[path_id].seed_class for path_id in result.retained_path_ids
        }
        self.assertEqual(retained_classes, {SeedClass.WHEEL, SeedClass.NON_WHEEL})
        self.assertEqual(
            result.retained_path_ids,
            tuple(
                item.path.path_id
                for item in sorted(
                    (
                        item for item in self.generation.hypotheses
                        if item.path.path_id in set(result.retained_path_ids)
                    ),
                    key=lambda item: (item.residual_rms_px, item.path.path_id),
                )
            ),
        )

    def _candidate_with_offsets(self, candidate, offsets, *, nuisance=None, path=None):
        self.assertEqual(len(offsets), len(candidate.path.correspondence))
        observation_by_id = {
            item.observation_id: item for item in self.record.observations
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
        parameter_values = candidate.parameter_values
        if nuisance is not None:
            replacements = dict(nuisance.values)
            parameter_values = tuple(
                (name, replacements.get(name, value))
                for name, value in candidate.parameter_values
            )
        return replace(
            candidate,
            predictions=predictions,
            nuisance=candidate.nuisance if nuisance is None else nuisance,
            parameter_values=parameter_values,
            path=candidate.path if path is None else path,
        )

    def _score(self, refinement, candidates, *, profile=None, record_value=None):
        selected_profile = profile or self.profile
        selected_record = record_value or self.record
        token = validate_before_read(selected_profile, self.scope)
        return CommonSupportScorer().evaluate(
            replace(refinement, refined=tuple(candidates)),
            selected_record,
            self.template,
            token=token,
            profile=selected_profile,
            scope=self.scope,
        )

    def test_support_boundary_equality_obeys_the_frozen_policy(self):
        refinement = self.refine()
        candidate = self._candidate_with_offsets(
            refinement.refined[0], ((0.0, 0.0), (8.0, 0.0))
        )
        included = self._score(refinement, (candidate,)).evaluated[0]
        self.assertTrue(included.support_accepted)
        self.assertEqual(len(included.support.support_observation_ids), 2)
        self.assertIn(8.0, tuple(item.magnitude_px for item in included.support.residuals))

        exclusive_profile = replace(
            self.profile,
            optimizer=replace(
                self.profile.optimizer,
                robust=replace(
                    self.profile.optimizer.robust,
                    support_includes_equality=False,
                ),
            ),
        )
        excluded = self._score(
            refinement, (candidate,), profile=exclusive_profile
        ).evaluated[0]
        self.assertFalse(excluded.support_accepted)
        self.assertEqual(excluded.rejection_reason, "insufficient_support")
        self.assertEqual(excluded.path.terminal_state, HypothesisState.REJECTED)

    def test_every_pixel_residual_and_outlier_is_recorded(self):
        refinement = self.refine()
        candidate = self._candidate_with_offsets(
            refinement.refined[0], ((3.0, 4.0), (9.0, 0.0))
        )
        scored = self._score(refinement, (candidate,)).evaluated[0]
        diagnostics = scored.support
        self.assertEqual(diagnostics.authorized_observation_count, 2)
        self.assertEqual(len(diagnostics.residuals), 2)
        by_id = {item.observation_id: item for item in diagnostics.residuals}
        first_id, second_id = (
            item.observation_id for item in candidate.path.correspondence
        )
        self.assertEqual(by_id[first_id].residual_px, (3.0, 4.0))
        self.assertEqual(by_id[first_id].magnitude_px, 5.0)
        self.assertTrue(by_id[first_id].in_support)
        self.assertEqual(by_id[second_id].residual_px, (9.0, 0.0))
        self.assertFalse(by_id[second_id].in_support)
        self.assertEqual(diagnostics.outlier_observation_ids, (second_id,))

    def test_insufficient_support_is_rejected_before_later_selection(self):
        refinement = self.refine()
        candidate = self._candidate_with_offsets(
            refinement.refined[0], ((9.0, 0.0), (0.0, 9.0))
        )
        report = self._score(refinement, (candidate,))
        scored = report.evaluated[0]
        self.assertEqual(report.supported, ())
        self.assertEqual(report.rejected, (scored,))
        self.assertFalse(scored.support_accepted)
        self.assertEqual(scored.support.support_observation_ids, ())
        self.assertEqual(scored.support.minimum_support, 2)
        self.assertEqual(scored.rejection_reason, "insufficient_support")
        self.assertFalse(scored.authoritative)

    def test_common_score_is_exact_sum_of_frozen_terms(self):
        refinement = self.refine()
        scoring_profile = replace(
            self.profile,
            optimizer=replace(
                self.profile.optimizer,
                robust=replace(
                    self.profile.optimizer.robust,
                    support_boundary_px=2.0,
                    nuisance_penalty=2.0,
                ),
            ),
        )
        nuisance = NuisanceVector(values=(
            ("delta_z_cam", 0.1),
            ("roof_height_m", 1.7),
        ))
        candidate = self._candidate_with_offsets(
            refinement.refined[0], ((1.0, 0.0), (3.0, 0.0)), nuisance=nuisance
        )
        components = self._score(
            refinement, (candidate,), profile=scoring_profile
        ).evaluated[0].score_components
        # Huber with C=2: rho(1)=1 and C^2*rho(9/C^2)=8.
        self.assertAlmostEqual(components.robust_residual_loss, 9.0)
        self.assertAlmostEqual(components.outlier_penalty_cost, 3.0)
        self.assertAlmostEqual(components.bounded_nuisance_prior_cost, 2.0)
        self.assertAlmostEqual(components.weighted_nuisance_prior_cost, 4.0)
        self.assertAlmostEqual(components.total, 16.0)

    def test_score_and_support_ignore_prohibited_influences(self):
        refinement = self.refine()
        wheel = next(
            item for item in refinement.refined
            if item.path.seed_class is SeedClass.WHEEL
        )
        non_wheel = next(
            item for item in refinement.refined
            if item.path.seed_class is SeedClass.NON_WHEEL
        )
        neutral_nuisance = NuisanceVector(values=(
            ("delta_z_cam", 0.0),
            ("roof_height_m", 1.5),
        ))
        wheel = self._candidate_with_offsets(
            wheel, ((1.0, 0.0), (3.0, 0.0)), nuisance=neutral_nuisance
        )
        non_wheel = self._candidate_with_offsets(
            non_wheel, ((1.0, 0.0), (3.0, 0.0)), nuisance=neutral_nuisance
        )
        common = self._score(refinement, (non_wheel, wheel))
        by_class = {item.path.seed_class: item for item in common.evaluated}
        self.assertAlmostEqual(
            by_class[SeedClass.WHEEL].score,
            by_class[SeedClass.NON_WHEEL].score,
        )
        self.assertEqual(
            by_class[SeedClass.WHEEL].support_accepted,
            by_class[SeedClass.NON_WHEEL].support_accepted,
        )
        self.assertEqual(by_class[SeedClass.WHEEL].support.visible_wheel_count, 2)
        self.assertEqual(by_class[SeedClass.NON_WHEEL].support.visible_wheel_count, 0)

        changed_correspondence = tuple(
            replace(item, candidate_label_provenance=("changed-provider-label",))
            for item in wheel.path.correspondence
        )
        changed_path = replace(
            wheel.path,
            seed_class=SeedClass.NON_WHEEL,
            correspondence=changed_correspondence,
        )
        changed_candidate = self._candidate_with_offsets(
            wheel,
            ((1.0, 0.0), (3.0, 0.0)),
            nuisance=neutral_nuisance,
            path=changed_path,
        )
        changed_record = replace(
            self.record,
            observations=tuple(
                replace(item, confidence=0.0) for item in self.record.observations
            ),
            provider=ProviderProvenance(
                provider_name="different-provider",
                provider_version="999",
                adapter_version="different-adapter",
            ),
        )
        changed = self._score(
            refinement, (changed_candidate,), record_value=changed_record
        ).evaluated[0]
        original = by_class[SeedClass.WHEEL]
        self.assertAlmostEqual(changed.score, original.score)
        self.assertEqual(changed.support_accepted, original.support_accepted)

        reversed_order = self._score(refinement, (wheel, non_wheel))
        self.assertEqual(
            {item.path.path_id: (item.score, item.support_accepted)
             for item in common.evaluated},
            {item.path.path_id: (item.score, item.support_accepted)
             for item in reversed_order.evaluated},
        )

    def _selection_candidate(
        self,
        scored,
        *,
        center,
        heading=0.0,
        score=1.0,
        prediction_shift=(0.0, 0.0),
        observability_failures=(),
        path_id=None,
    ):
        path = replace(
            scored.path,
            path_id=scored.path.path_id if path_id is None else path_id,
            terminal_state=HypothesisState.SCORED,
            terminal_reason=None,
        )
        predictions = tuple(
            replace(
                item,
                pixel=(
                    item.pixel[0] + prediction_shift[0],
                    item.pixel[1] + prediction_shift[1],
                ),
            )
            for item in scored.refinement.predictions
        )
        refinement = replace(
            scored.refinement,
            path=path,
            pose=Pose2D(center_sat_px=center, heading_rad_unwrapped=heading),
            predictions=predictions,
            observability_failures=tuple(observability_failures),
        )
        return replace(
            scored,
            refinement=refinement,
            path=path,
            score_components=CommonScoreComponents(
                robust_residual_loss=score,
                outlier_penalty_cost=0.0,
                bounded_nuisance_prior_cost=0.0,
                weighted_nuisance_prior_cost=0.0,
                total=score,
            ),
            support_accepted=True,
            rejection_reason=None,
        )

    def _selection_report(self, scoring, candidates):
        path_ids = tuple(item.path.path_id for item in candidates)
        refinement = replace(
            scoring.refinement,
            sampled_path_ids=path_ids,
            retained_path_ids=path_ids,
            refined=tuple(item.refinement for item in candidates),
            failures=(),
        )
        return replace(scoring, refinement=refinement, evaluated=tuple(candidates))

    def _select(self, scoring, *, profile=None, spreads=None):
        selected_profile = profile or self.profile
        token = validate_before_read(selected_profile, self.scope)
        return OrderedGateSelector().select(
            scoring,
            self.record,
            self.template,
            token=token,
            profile=selected_profile,
            scope=self.scope,
            spread_m_by_path=spreads,
        )

    def _supported_scoring(self):
        refinement = self.refine()
        scoring = self._score(refinement, refinement.refined)
        supported = scoring.supported
        self.assertGreaterEqual(len(supported), 3)
        return scoring, supported

    def test_pose_equivalence_uses_connected_components_and_is_permutation_invariant(self):
        scoring, supported = self._supported_scoring()
        base = supported[0]
        candidates = (
            self._selection_candidate(
                base, center=(0.0, 0.0), score=3.0,
                prediction_shift=(0.0, 0.0),
                path_id=supported[0].path.path_id,
            ),
            self._selection_candidate(
                base, center=(0.3, 0.0), score=2.0,
                prediction_shift=(0.75, 0.0),
                path_id=supported[1].path.path_id,
            ),
            self._selection_candidate(
                base, center=(0.6, 0.0), score=1.0,
                prediction_shift=(1.5, 0.0),
                path_id=supported[2].path.path_id,
            ),
        )
        forward = self._select(self._selection_report(scoring, candidates))
        reverse = self._select(
            self._selection_report(scoring, tuple(reversed(candidates)))
        )
        self.assertEqual(forward.canonical_bytes(), reverse.canonical_bytes())
        self.assertEqual(len(forward.diagnostics.merged_components), 1)
        self.assertEqual(
            set(forward.diagnostics.merged_components[0]),
            {item.path.path_id for item in candidates},
        )
        self.assertEqual(forward.diagnostics.selected_path, candidates[2].path.path_id)
        states = {
            item.path_id: item.terminal_state for item in forward.diagnostics.paths
        }
        self.assertEqual(states[candidates[2].path.path_id], HypothesisState.SELECTED)
        self.assertEqual(states[candidates[0].path.path_id], HypothesisState.MERGED)
        self.assertEqual(states[candidates[1].path.path_id], HypothesisState.MERGED)
        for candidate in candidates:
            retained = next(
                item for item in forward.diagnostics.paths
                if item.path_id == candidate.path.path_id
            )
            self.assertEqual(retained.correspondence, candidate.path.correspondence)
            self.assertEqual(retained.initialization_source, candidate.path.initialization_source)

    def test_distinct_equal_score_alternatives_reject_without_order_authority(self):
        scoring, supported = self._supported_scoring()
        candidates = (
            self._selection_candidate(supported[0], center=(0.0, 0.0), score=1.0),
            self._selection_candidate(supported[1], center=(10.0, 0.0), score=1.0),
        )
        result = self._select(self._selection_report(scoring, candidates))
        self.assertEqual(result.reason, "ambiguous_equal_score")
        self.assertIn("ambiguous_hypotheses", result.diagnostics.gate_failures)
        self.assertIsNone(result.authoritative_position_sat_px)
        self.assertIsNotNone(result.diagnostic_position_sat_px)

    def test_equal_scores_with_agreeing_positions_accept_with_an_ambiguous_heading(self):
        """Requirement 5.19: a heading-only tie must not discard the position."""
        scoring, supported = self._supported_scoring()
        # A front/rear swap: the same footprint, the heading 180 degrees away.
        # The poses do not merge (heading differs), but the position does agree.
        candidates = (
            self._selection_candidate(supported[0], center=(0.0, 0.0), heading=0.0, score=1.0),
            self._selection_candidate(supported[1], center=(0.05, 0.0), heading=math.pi, score=1.0),
        )
        result = self._select(self._selection_report(scoring, candidates))
        self.assertEqual(result.status, LocalizationStatus.ACCEPTED)
        self.assertEqual(result.authoritative_position_sat_px, (0.0, 0.0))
        self.assertIsNone(result.heading_deg)
        self.assertEqual(result.heading_status, "ambiguous")
        self.assertIsNone(result.diagnostic_position_sat_px)

    def test_exact_absolute_margin_boundary_is_inclusive(self):
        scoring, supported = self._supported_scoring()
        candidates = (
            self._selection_candidate(supported[0], center=(0.0, 0.0), score=1.0),
            self._selection_candidate(supported[1], center=(10.0, 0.0), score=1.1),
        )
        result = self._select(self._selection_report(scoring, candidates))
        self.assertEqual(result.status, LocalizationStatus.ACCEPTED)
        self.assertAlmostEqual(result.diagnostics.hypothesis_margin, 0.1)

    def test_margin_requirement_is_latched_before_later_candidate_gates(self):
        scoring, supported = self._supported_scoring()
        candidates = (
            self._selection_candidate(supported[0], center=(0.0, 0.0), score=1.0),
            self._selection_candidate(
                supported[1], center=(10.0, 0.0), score=1.05,
                observability_failures=("unobservable_pose",),
            ),
        )
        result = self._select(self._selection_report(scoring, candidates))
        self.assertEqual(result.reason, "ambiguous_hypotheses")
        self.assertIn("unobservable_pose", result.diagnostics.gate_failures)

    def test_total_gate_precedence_retains_every_failure_and_inclusive_spread(self):
        scoring, supported = self._supported_scoring()
        candidates = (
            self._selection_candidate(
                supported[0], center=(0.0, 0.0), score=1.0,
                observability_failures=(
                    "unobservable_pose", "ill_conditioned_pose",
                    "pose_uncertainty_exceeded",
                ),
            ),
            self._selection_candidate(supported[1], center=(10.0, 0.0), score=1.0),
        )
        report = self._selection_report(scoring, candidates)
        result = self._select(
            report,
            spreads={candidates[0].path.path_id: 8.0},
        )
        self.assertEqual(result.reason, "unobservable_pose")
        self.assertEqual(result.decisive_gate, "unobservable_pose")
        for reason in (
            "unobservable_pose", "ill_conditioned_pose",
            "pose_uncertainty_exceeded", "spread_rejected",
            "ambiguous_equal_score", "ambiguous_hypotheses",
        ):
            self.assertIn(reason, result.diagnostics.gate_failures)

    def test_all_support_invalid_uses_higher_precedence_support_reason(self):
        refinement = self.refine()
        scoring = self._score(refinement, refinement.refined)
        rejected = []
        for item in scoring.evaluated:
            path = replace(
                item.path,
                terminal_state=HypothesisState.REJECTED,
                terminal_reason="insufficient_support",
            )
            rejected.append(replace(
                item,
                path=path,
                support=replace(
                    item.support,
                    minimum_support=item.support.authorized_observation_count + 1,
                ),
                support_accepted=False,
                rejection_reason="insufficient_support",
            ))
        report = replace(scoring, evaluated=tuple(rejected))
        result = self._select(report)
        self.assertEqual(result.reason, "insufficient_support")
        self.assertIsNone(result.diagnostic_position_sat_px)
        self.assertIn("insufficient_valid_hypothesis", result.diagnostics.gate_failures)

    def test_no_candidates_without_higher_failure_is_insufficient_valid_hypothesis(self):
        refinement = self.refine()
        empty_refinement = replace(
            refinement,
            refined=(),
            failures=(),
            sampled_path_ids=(),
            retained_path_ids=(),
        )
        scoring = self._score(empty_refinement, ())
        result = self._select(scoring)
        self.assertEqual(result.reason, "insufficient_valid_hypothesis")
        self.assertIsNone(result.authoritative_position_sat_px)
        self.assertIsNone(result.diagnostic_position_sat_px)

    def test_coordinate_roles_heading_normalization_and_non_wheel_winner(self):
        scoring, supported = self._supported_scoring()
        wheel = next(item for item in supported if item.path.seed_class is SeedClass.WHEEL)
        non_wheel = next(
            item for item in supported if item.path.seed_class is SeedClass.NON_WHEEL
        )
        candidates = (
            self._selection_candidate(wheel, center=(20.0, 0.0), score=2.0),
            self._selection_candidate(
                non_wheel, center=(0.0, 0.0), heading=-np.pi / 2.0, score=1.0,
            ),
        )
        result = self._select(self._selection_report(scoring, candidates))
        self.assertEqual(result.status, LocalizationStatus.ACCEPTED)
        self.assertTrue(result.usable)
        self.assertEqual(result.authoritative_position_sat_px, (0.0, 0.0))
        self.assertIsNone(result.diagnostic_position_sat_px)
        self.assertEqual(result.heading_deg, 270.0)
        self.assertEqual(result.diagnostics.selected_path, non_wheel.path.path_id)

    def test_observability_includes_every_varied_nuisance_category(self):
        base = configured_profile()
        dimension = base.nuisance.fields[0]
        calibration = replace(
            base.nuisance.fields[1],
            prior=GaussianPrior(mean=0.0, standard_deviation=0.1),
        )
        height = NuisanceField(
            name="roof_height_m",
            unit="m",
            bounds=ClosedInterval(lower=1.2, upper=1.8),
            scale=0.2,
            prior=GaussianPrior(mean=1.5, standard_deviation=0.2),
        )
        combined = replace(
            base,
            nuisance=NuisanceProfile(
                version="all-observability-nuisances-v1",
                fields=(dimension, calibration, height),
            ),
            optimizer=replace(
                base.optimizer,
                retained_candidate_count=4,
                optimizer=replace(
                    base.optimizer.optimizer,
                    parameter_scale=(1.0, 1.0, 1.0, 1.0, 0.1, 0.2),
                ),
            ),
        )
        token = validate_before_read(combined, self.scope)
        fixture_record = record(combined, self.template)
        generation = DirectImageHypothesisGenerator(self.projector).generate(
            fixture_record,
            self.template,
            token=token,
            profile=combined,
            scope=self.scope,
            seed_profile=seed_profile(),
        )
        report = BoundedScipyRefiner(self.projector).refine(
            generation,
            fixture_record,
            self.template,
            token=token,
            profile=combined,
            scope=self.scope,
            bounds=refinement_bounds(),
        )
        self.assertTrue(report.refined)
        self.assertFalse(report.failures)
        expected_names = (
            "delta_center_x_m", "delta_center_y_m", "delta_heading_rad",
            "vehicle_width", "delta_z_cam", "roof_height_m",
        )
        for candidate in report.refined:
            diagnostics = candidate.observability
            self.assertEqual(diagnostics.parameter_names, expected_names)
            self.assertEqual(np.asarray(diagnostics.image_residual_jacobian_scaled).shape[1], 6)
            self.assertEqual(np.asarray(diagnostics.information_scaled).shape, (6, 6))
            self.assertEqual(
                diagnostics.nuisance_prior_precision_scaled,
                (0.0, 0.0, 0.0, 0.0, 1.0, 1.0),
            )
            self.assertEqual(
                tuple(name for name, _scheme in diagnostics.derivative_schemes),
                expected_names,
            )
            self.assertFalse(candidate.authoritative)

    def test_schur_covariance_matches_reference_calculation(self):
        jacobian = np.asarray((
            (1.0, 0.0, 0.0, 1.0, 0.0),
            (0.0, 1.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 1.0, 1.0, 1.0),
            (1.0, 1.0, 0.0, 0.0, 1.0),
            (0.0, 1.0, 1.0, 1.0, 0.0),
            (1.0, 0.0, 1.0, 0.0, 0.0),
        ))
        residuals = np.asarray((0.2, -0.1, 0.3, 0.4, -0.2, 0.1))
        scales = np.asarray((2.0, 3.0, 0.5, 0.25, 4.0))
        prior = np.asarray((0.0, 0.0, 0.0, 4.0, 9.0))
        settings = replace(
            self.profile.optimizer.observability,
            rank_tolerance=1e-12,
            condition_rejection_boundary=1e12,
            position_uncertainty_boundary_m=1e6,
            heading_uncertainty_boundary_rad=1e6,
        )
        result = compute_observability_from_linearization(
            image_residual_jacobian_scaled=jacobian,
            image_residuals=residuals,
            parameter_names=("x", "y", "heading", "height", "calibration"),
            parameter_units=("m", "m", "rad", "m", "m"),
            parameter_scales=scales,
            nuisance_prior_precision_scaled=prior,
            settings=settings,
            robust_loss="linear",
            robust_loss_scale=2.0,
        )
        information = jacobian.T @ jacobian + np.diag(prior)
        reference_pose = (
            information[:3, :3]
            - information[:3, 3:]
            @ np.linalg.pinv(information[3:, 3:])
            @ information[3:, :3]
        )
        singular = np.linalg.svd(reference_pose, compute_uv=False)
        rank = int(np.count_nonzero(singular > settings.rank_tolerance))
        variance = float(np.dot(residuals, residuals) / max(len(residuals) - rank, 1))
        reference_covariance_scaled = variance * np.linalg.pinv(reference_pose)
        reference_covariance = (
            np.diag(scales[:3]) @ reference_covariance_scaled @ np.diag(scales[:3])
        )
        np.testing.assert_allclose(result.diagnostics.information_scaled, information, atol=1e-12)
        np.testing.assert_allclose(result.diagnostics.information_pose, reference_pose, atol=1e-12)
        np.testing.assert_allclose(result.diagnostics.singular_values, singular, atol=1e-12)
        np.testing.assert_allclose(result.diagnostics.covariance_pose, reference_covariance, atol=1e-12)
        self.assertEqual(result.diagnostics.rank, rank)
        self.assertAlmostEqual(
            result.diagnostics.condition, singular[0] / singular[-1]
        )
        self.assertEqual(result.gate_failures, ())

    def test_rank_condition_and_uncertainty_reject_at_exact_boundaries(self):
        names = ("x", "y", "heading")
        common = dict(
            parameter_names=names,
            parameter_units=("m", "m", "rad"),
            parameter_scales=(1.0, 1.0, 1.0),
            nuisance_prior_precision_scaled=(0.0, 0.0, 0.0),
            robust_loss="linear",
            robust_loss_scale=1.0,
        )
        rank_settings = ObservabilitySettings(
            jacobian_version="reference-jacobian-v1",
            curvature_version="reference-schur-v1",
            rank_tolerance=1.0,
            minimum_rank=3,
            condition_rejection_boundary=100.0,
            position_uncertainty_boundary_m=100.0,
            heading_uncertainty_boundary_rad=100.0,
        )
        rank_result = compute_observability_from_linearization(
            image_residual_jacobian_scaled=np.diag((1.0, 2.0, 3.0)),
            image_residuals=np.zeros(3),
            settings=rank_settings,
            **common,
        )
        self.assertEqual(rank_result.diagnostics.rank, 2)
        self.assertIn("unobservable_pose", rank_result.gate_failures)

        condition_settings = replace(
            rank_settings,
            rank_tolerance=1e-12,
            condition_rejection_boundary=4.0,
        )
        condition_result = compute_observability_from_linearization(
            image_residual_jacobian_scaled=np.diag((2.0, np.sqrt(2.0), 1.0)),
            image_residuals=np.zeros(3),
            settings=condition_settings,
            **common,
        )
        self.assertEqual(condition_result.diagnostics.condition, 4.0)
        self.assertIn("ill_conditioned_pose", condition_result.gate_failures)

        uncertainty_settings = replace(
            condition_settings,
            condition_rejection_boundary=100.0,
            position_uncertainty_boundary_m=100.0,
            heading_uncertainty_boundary_rad=100.0,
        )
        uncertainty_jacobian = np.vstack((np.eye(3), np.zeros((1, 3))))
        uncertainty_residuals = np.asarray((1.0, 0.0, 0.0, 0.0))
        baseline = compute_observability_from_linearization(
            image_residual_jacobian_scaled=uncertainty_jacobian,
            image_residuals=uncertainty_residuals,
            settings=uncertainty_settings,
            **common,
        )
        exact_boundary = baseline.diagnostics.position_ellipse_95_m[0]
        boundary_result = compute_observability_from_linearization(
            image_residual_jacobian_scaled=uncertainty_jacobian,
            image_residuals=uncertainty_residuals,
            settings=replace(
                uncertainty_settings,
                position_uncertainty_boundary_m=exact_boundary,
            ),
            **common,
        )
        self.assertIn("pose_uncertainty_exceeded", boundary_result.gate_failures)

    def test_non_finite_linearization_is_a_typed_rejection(self):
        with self.assertRaises(ObservabilityCalculationError) as raised:
            compute_observability_from_linearization(
                image_residual_jacobian_scaled=np.asarray(((np.nan, 0.0, 0.0),)),
                image_residuals=np.zeros(1),
                parameter_names=("x", "y", "heading"),
                parameter_units=("m", "m", "rad"),
                parameter_scales=(1.0, 1.0, 1.0),
                nuisance_prior_precision_scaled=(0.0, 0.0, 0.0),
                settings=self.profile.optimizer.observability,
                robust_loss="linear",
                robust_loss_scale=1.0,
            )
        self.assertEqual(raised.exception.code, "non_finite_optimization")

    def test_active_bounds_use_and_record_one_sided_derivatives(self):
        specs = (
            ParameterSpec("lower", "m", ClosedInterval(lower=0.0, upper=2.0), 2.0, "pose"),
            ParameterSpec("upper", "m", ClosedInterval(lower=-1.0, upper=1.0), 4.0, "pose"),
            ParameterSpec("fixed", "m", ClosedInterval(lower=0.5, upper=0.5), 1.0, "nuisance"),
        )
        jacobian, active, schemes = _finite_difference_image_jacobian(
            image_residual=lambda values: np.asarray((
                3.0 * values[0] - 2.0 * values[1] + 5.0 * values[2],
            )),
            values=np.asarray((0.0, 1.0, 0.5)),
            specs=specs,
            active_mask=np.asarray((-1, 1, 2)),
            step_scaled=1e-6,
        )
        np.testing.assert_allclose(jacobian, ((6.0, -8.0, 0.0),), atol=1e-9)
        self.assertEqual(active, ("lower=lower", "upper=upper", "fixed=fixed"))
        self.assertEqual(
            schemes,
            (("lower", "forward"), ("upper", "backward"), ("fixed", "fixed")),
        )


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# design.md "Static and smoke checks": the optimizer call graph.
CALL_GRAPH_MODULES = (
    "trafficlab/motion/haware_optimizer.py",
    "trafficlab/motion/haware_hypotheses.py",
    "trafficlab/motion/haware_accuracy/models.py",
    "trafficlab/projection/haware_forward.py",
)
FORBIDDEN_MODULES = (
    "haware_localization",
    "haware_baseline_dispatch",
    "haware_diagnostic_candidates",
)
FORBIDDEN_IDENTIFIERS = ("RoleConstraintGraph", "wheel_only", "wheel_weighted")


def scan_module(path):
    """Return (forbidden imports, forbidden identifiers) for one source file.

    Identifiers are matched on `ast.Name`/`ast.Attribute` only. String literals
    do NOT count: `haware_accuracy/validation.py` legitimately holds these exact
    strings as its prohibited-mode list, and a substring scan would also reject
    the legal diagnostic-candidate name `wheel_weighted_procrustes`.
    """
    tree = ast.parse(Path(path).read_text())
    imports, identifiers = [], []
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            # `from pkg import module` puts the module in names, not in .module.
            targets = [node.module or ""] + [alias.name for alias in node.names]
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_IDENTIFIERS:
            identifiers.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_IDENTIFIERS:
            identifiers.append(node.attr)
        for target in targets:
            parts = target.split(".")
            imports.extend(name for name in FORBIDDEN_MODULES if name in parts)
    return sorted(set(imports)), sorted(set(identifiers))


class OptimizerCallGraphStaticTest(unittest.TestCase):
    """Task 5.12: prove the boundary statically, not with runtime spies."""

    def test_the_scanner_detects_a_seeded_violation(self):
        """A scanner that cannot fail is not a proof.

        This arm is the only genuinely red one: the real modules are already
        clean, so without it the other arms would pass no matter how the
        scanner was written.
        """
        with tempfile.TemporaryDirectory() as directory:
            violating = Path(directory) / "violating_module.py"
            violating.write_text(
                "from trafficlab.motion.haware_localization import HawareLocalizer\n"
                "import trafficlab.motion.haware_baseline_dispatch as dispatch\n"
                "from trafficlab.measurement import haware_diagnostic_candidates\n"
                "\n"
                "PROHIBITED_LIST = ('wheel_only', 'wheel_weighted')  # literals must NOT count\n"
                "\n"
                "def build(graph):\n"
                "    mode = wheel_weighted\n"
                "    return RoleConstraintGraph(mode), graph.wheel_only\n"
            )
            imports, identifiers = scan_module(violating)

        self.assertEqual(
            imports,
            ["haware_baseline_dispatch", "haware_diagnostic_candidates", "haware_localization"],
        )
        self.assertEqual(identifiers, ["RoleConstraintGraph", "wheel_only", "wheel_weighted"])

    def test_string_literals_are_not_identifiers(self):
        """The prohibited-mode list must remain expressible in Python."""
        with tempfile.TemporaryDirectory() as directory:
            literals_only = Path(directory) / "literals_only.py"
            literals_only.write_text(
                "PROHIBITED = ('wheel_only', 'wheel_weighted', 'RoleConstraintGraph')\n"
                "DIAGNOSTIC_CANDIDATES = ('wheel_weighted_procrustes',)\n"
            )
            imports, identifiers = scan_module(literals_only)

        self.assertEqual(imports, [])
        self.assertEqual(identifiers, [])

    def test_optimizer_call_graph_imports_no_baseline_or_diagnostic_module(self):
        for relative in CALL_GRAPH_MODULES:
            with self.subTest(module=relative):
                imports, _ = scan_module(PROJECT_ROOT / relative)
                self.assertEqual(imports, [])

    def test_optimizer_call_graph_contains_no_prohibited_identifier(self):
        for relative in CALL_GRAPH_MODULES:
            with self.subTest(module=relative):
                _, identifiers = scan_module(PROJECT_ROOT / relative)
                self.assertEqual(identifiers, [])

    def test_the_validation_module_exclusion_stays_scoped_to_string_literals(self):
        """Pin why validation.py is excluded, so the exclusion cannot widen."""
        validation = PROJECT_ROOT / "trafficlab/motion/haware_accuracy/validation.py"
        imports, identifiers = scan_module(validation)
        self.assertEqual(imports, [])
        # It is excluded for its literals, not because it uses the identifiers.
        self.assertEqual(identifiers, [])
        self.assertIn("wheel_weighted", validation.read_text())


if __name__ == "__main__":
    unittest.main()


class RankZeroConditioningTest(unittest.TestCase):
    """Requirement 6.34: a rank-zero fit has no conditioning number to report.

    The pre-2026-08-17 code stored `condition = condition_rejection_boundary`
    as a sentinel, which made the `ill_conditioned_pose` gate fire
    unconditionally and made the reported value depend on the boundary being
    tested against — raising the boundary could never clear it.
    """

    @staticmethod
    def _settings():
        return ObservabilitySettings(
            jacobian_version="test-jacobian-v1",
            curvature_version="test-curvature-v1",
            rank_tolerance=1e-9,
            minimum_rank=3,
            condition_rejection_boundary=1e6,
            position_uncertainty_boundary_m=100.0,
            heading_uncertainty_boundary_rad=10.0,
        )

    def _evaluate(self, jacobian):
        return compute_observability_from_linearization(
            image_residual_jacobian_scaled=np.asarray(jacobian, dtype=float),
            image_residuals=np.zeros(jacobian.shape[0]),
            parameter_names=("dc_x", "dc_y", "dtheta"),
            parameter_units=("m", "m", "rad"),
            parameter_scales=(1.0, 1.0, 1.0),
            nuisance_prior_precision_scaled=(0.0, 0.0, 0.0),
            settings=self._settings(),
            robust_loss="huber",
            robust_loss_scale=1.0,
        )

    def test_rank_zero_reports_no_condition_and_only_the_observability_failure(self):
        evaluation = self._evaluate(np.zeros((4, 3)))
        self.assertEqual(evaluation.diagnostics.rank, 0)
        self.assertIsNone(evaluation.diagnostics.condition)
        self.assertEqual(evaluation.gate_failures[:1], ("unobservable_pose",))
        self.assertNotIn("ill_conditioned_pose", evaluation.gate_failures)

    def test_a_full_rank_fit_still_reports_a_finite_condition(self):
        evaluation = self._evaluate(np.eye(3))
        self.assertEqual(evaluation.diagnostics.rank, 3)
        self.assertIsNotNone(evaluation.diagnostics.condition)
        self.assertNotIn("unobservable_pose", evaluation.gate_failures)


class PositionEquivalentAmbiguityTest(unittest.TestCase):
    """Requirements 5.19-5.21: a heading tie must not discard a usable position.

    A front/rear semantic swap does not merely flip heading — with the
    correspondence reversed the fitted centre can move by roughly half a
    wheelbase — so position agreement has to be proven, never assumed.
    """

    @staticmethod
    def _tolerance():
        return 0.25

    def test_tied_scores_with_agreeing_positions_keep_position_authority(self):
        verdict = resolve_equal_score_positions(
            positions=((100.0, 200.0), (100.1, 200.05)),
            px_per_meter=1.0,
            tolerance_m=self._tolerance(),
        )
        self.assertTrue(verdict.position_equivalent)
        self.assertAlmostEqual(verdict.dispersion_m, 0.1118, places=3)

    def test_tied_scores_with_separated_positions_stay_ambiguous(self):
        """Half a wheelbase apart is a real position ambiguity, not a heading one."""
        verdict = resolve_equal_score_positions(
            positions=((100.0, 200.0), (101.3, 200.0)),
            px_per_meter=1.0,
            tolerance_m=self._tolerance(),
        )
        self.assertFalse(verdict.position_equivalent)

    def test_the_tolerance_is_measured_in_metres_not_pixels(self):
        verdict = resolve_equal_score_positions(
            positions=((100.0, 200.0), (105.0, 200.0)),
            px_per_meter=34.41,
            tolerance_m=self._tolerance(),
        )
        self.assertTrue(verdict.position_equivalent)
        self.assertAlmostEqual(verdict.dispersion_m, 5.0 / 34.41, places=6)

    def test_the_boundary_is_inclusive(self):
        verdict = resolve_equal_score_positions(
            positions=((0.0, 0.0), (0.25, 0.0)),
            px_per_meter=1.0,
            tolerance_m=self._tolerance(),
        )
        self.assertTrue(verdict.position_equivalent)

    def test_more_than_two_tied_poses_use_the_maximum_pairwise_distance(self):
        verdict = resolve_equal_score_positions(
            positions=((0.0, 0.0), (0.1, 0.0), (0.3, 0.0)),
            px_per_meter=1.0,
            tolerance_m=self._tolerance(),
        )
        self.assertFalse(verdict.position_equivalent)
        self.assertAlmostEqual(verdict.dispersion_m, 0.3, places=6)
