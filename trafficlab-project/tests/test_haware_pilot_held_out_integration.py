"""Concrete pilot-to-held-out integration coverage for task 8.6.

The synthetic fixtures verify contracts and hand-computed arithmetic only. They
are not acceptance evidence; the checked-in evidence remains insufficient.
"""
from dataclasses import FrozenInstanceError, replace
import unittest

from trafficlab.measurement.haware_held_out import (
    HeldOutAccessError,
    HeldOutDecisionController,
    default_off_dispatch_evidence,
    freeze_held_out_acceptance,
)
from trafficlab.measurement.haware_pilot import (
    ACCEPTANCE_SITES,
    PilotArm,
    compute_pilot_statistics,
    decide_pilot_feasibility,
    load_current_evidence_report,
)
from trafficlab.motion.haware_accuracy.models import (
    ContentIdentity,
    DecisionStatus,
    PartitionKind,
)
from trafficlab.motion.haware_accuracy.validation import resolve_optimizer_dispatch
from tests.test_haware_held_out import HeldOutControlsTest
from tests.test_haware_pilot_statistics import PilotStatisticsTest


class PilotHeldOutIntegrationTest(unittest.TestCase):
    """Validates Requirements 10.1-10.32, 11.1-11.22, and 12.1-12.9."""

    def setUp(self):
        self.fixture = HeldOutControlsTest(
            methodName="test_site_failure_is_not_rescued_by_other_site"
        )
        self.fixture.build_context()

    def _evaluate(self, controller, *, runs=None, decision=None, grant=None, loader=None):
        return controller.evaluate(
            grant=self.fixture.grant if grant is None else grant,
            pilot_decision=self.fixture.pilot_decision if decision is None else decision,
            statistics=self.fixture.statistics,
            frozen_runs=self.fixture.runs if runs is None else runs,
            frozen_evidence=self.fixture.frozen,
            profiles=self.fixture.profiles,
            validated_profiles=self.fixture.tokens,
            scope=self.fixture.scope,
            outcome_loader=self.fixture.loader() if loader is None else loader,
        )
    @staticmethod
    def _tamper_full_run(frozen_runs, site, **run_changes):
        changed_sites = []
        for site_runs in frozen_runs.sites:
            if site_runs.site != site:
                changed_sites.append(site_runs)
                continue
            changed_arms = []
            for arm_run in site_runs.arms:
                if arm_run.identity.arm is PilotArm.FULL_OPTIMIZER:
                    changed_run = replace(arm_run.identity.run, **run_changes)
                    arm_run = replace(
                        arm_run,
                        identity=replace(arm_run.identity, run=changed_run),
                    )
                changed_arms.append(arm_run)
            changed_sites.append(replace(site_runs, arms=tuple(changed_arms)))
        return replace(frozen_runs, sites=tuple(changed_sites))

    def test_complete_flow_has_hand_computed_metrics_power_reports_and_order(self):
        fixture = self.fixture
        acceptance = fixture.grant.acceptance_profile
        self.assertEqual(ACCEPTANCE_SITES, ("kee-cc", "taoyuan-tc"))
        self.assertEqual(tuple(value.site for value in fixture.frozen.sites), ACCEPTANCE_SITES)
        self.assertEqual(tuple(value.site for value in fixture.runs.sites), ACCEPTANCE_SITES)
        self.assertEqual(tuple(value.site for value in fixture.statistics.sites), ACCEPTANCE_SITES)
        self.assertEqual(tuple(value.site for value in acceptance.candidates), ACCEPTANCE_SITES)
        self.assertEqual(tuple(value.site for value in acceptance.partitions), ACCEPTANCE_SITES)
        self.assertEqual(tuple(value.site for value in acceptance.site_policies), ACCEPTANCE_SITES)

        for site in ACCEPTANCE_SITES:
            site_runs = fixture.runs.for_site(site)
            pilot_ids = tuple(
                value.eligible_detection_id
                for value in fixture.frozen.for_site(site).eligible_detections
                if value.partition is PartitionKind.PILOT
            )
            self.assertEqual(tuple(value.identity.arm for value in site_runs.arms), tuple(PilotArm))
            self.assertTrue(all(value.ordered_eligible_ids == pilot_ids for value in site_runs.arms))
            self.assertEqual(site_runs.denominator, 4)

            full = fixture.statistics.for_site(site).for_arm(PilotArm.FULL_OPTIMIZER)
            self.assertEqual((full.accepted_count, full.rejected_count), (4, 0))
            self.assertEqual(full.unrounded_planar_errors_m, (1.0, 1.0, 1.0, 1.0))
            self.assertEqual((full.median_error_m, full.p90_error_m), (1.0, 1.0))
            self.assertEqual(full.usable_coverage, 1.0)
            self.assertEqual(
                dict(full.signed_effects),
                {"median_error_m": -3.0, "p90_error_m": -3.0, "usable_coverage": 0.5},
            )
            for name, expected in (
                ("median_error_m", -3.0),
                ("p90_error_m", -3.0),
                ("usable_coverage", 0.5),
            ):
                interval = dict(full.effect_intervals)[name]
                self.assertEqual((interval.lower, interval.upper), (expected, expected))
                self.assertEqual(interval.bootstrap_variance, 0.0)
            self.assertEqual(full.genuine_track_count, 2)
            self.assertEqual(
                (full.selected_seed_provenance.wheel,
                 full.selected_seed_provenance.non_wheel,
                 full.selected_seed_provenance.unavailable),
                (0, 4, 0),
            )
            self.assertEqual(
                tuple(value.view_id for value in full.independent_view_coverage),
                (f"{site}:camera:0", f"{site}:camera:1"),
            )
            self.assertEqual(full.ground_truth_uncertainty.values, (0.25,) * 4)
            self.assertIs(full.power_sufficiency.status, DecisionStatus.GO)
            self.assertEqual(full.power_sufficiency.required_sample_count, 4)
            self.assertEqual(full.power_sufficiency.required_genuine_track_count, 2)
            self.assertEqual(full.power_sufficiency.achieved_power, 1.0)
            self.assertEqual(
                (full.candidate_thresholds.maximum_median_error_m,
                 full.candidate_thresholds.maximum_p90_error_m,
                 full.candidate_thresholds.minimum_usable_coverage),
                (1.0, 1.0, 1.0),
            )

        self.assertIs(fixture.pilot_decision.overall, DecisionStatus.GO)
        self.assertIs(fixture.pilot_decision.kee_cc.status, DecisionStatus.GO)
        self.assertIs(fixture.pilot_decision.taoyuan_tc.status, DecisionStatus.GO)
        with self.assertRaises(FrozenInstanceError):
            acceptance.candidates[0].profile_snapshot.profile_id = "changed"

        decision = self._evaluate(HeldOutDecisionController())
        self.assertIs(decision.overall, DecisionStatus.GO)
        for site, report in zip(
            ACCEPTANCE_SITES, (decision.kee_cc, decision.taoyuan_tc), strict=True
        ):
            self.assertEqual(report.site, site)
            self.assertEqual((report.denominator, report.accepted_count, report.rejected_count), (4, 4, 0))
            self.assertEqual((report.median_error_m, report.p90_error_m, report.usable_coverage), (1.0, 1.0, 1.0))
            self.assertEqual(
                dict(report.signed_effects),
                {"median_error_m": -3.0, "p90_error_m": -3.0, "usable_coverage": 0.0},
            )
            self.assertEqual(
                tuple(value.view_id for value in report.independent_view_coverage),
                (f"{site}:camera:0", f"{site}:camera:1"),
            )

        authorization = default_off_dispatch_evidence(decision)
        self.assertIsNotNone(authorization)
        dispatch = resolve_optimizer_dispatch(decision.candidate_identity, authorization)
        self.assertFalse(dispatch.optimizer_enabled)
        self.assertEqual(dispatch.production_path, "corrected_legacy_baseline")
        self.assertEqual(dispatch.optimizer_output_role, "diagnostic_only")
        self.assertEqual(dispatch.reason, "hardening_authorization_incomplete")
    def test_checked_in_evidence_is_consistent_and_cannot_open_held_out(self):
        report = load_current_evidence_report()
        self.assertIs(report.final_evidence_status, DecisionStatus.INSUFFICIENT_DATA)
        self.assertFalse(report.proven_improvement_claim_allowed)
        self.assertFalse(report.held_out_acceptance_claim_allowed)
        self.assertFalse(report.optimizer_authoritative_dispatch_allowed)
        self.assertEqual(report.diagnostic_inputs_role, "diagnostic_only")
        self.assertEqual(
            tuple(site for site, _gaps in report.per_site_evidence_gaps),
            ACCEPTANCE_SITES,
        )
        expected_gaps = (
            "independent_ground_truth_unavailable",
            "genuine_track_coverage_unavailable",
            "pilot_power_unavailable",
            "untouched_held_out_partition_unavailable",
        )
        self.assertTrue(
            all(gaps == expected_gaps for _site, gaps in report.per_site_evidence_gaps)
        )

        current = PilotStatisticsTest()
        current.setUp()
        current_runs = current.run_arms()
        current_statistics = compute_pilot_statistics(
            frozen_evidence=current.frozen,
            frozen_runs=current_runs,
            profiles=current.profiles,
        )
        current_decision = decide_pilot_feasibility(
            statistics=current_statistics,
            frozen_runs=current_runs,
        )
        self.assertIs(current_decision.overall, DecisionStatus.NO_GO)
        with self.assertRaisesRegex(HeldOutAccessError, "pilot_dual_site_go_required"):
            freeze_held_out_acceptance(
                pilot_decision=current_decision,
                statistics=current_statistics,
                frozen_runs=current_runs,
                frozen_evidence=current.frozen,
                profiles=current.profiles,
                validated_profiles=current.tokens,
                scope=current.scope,
            )
        dispatch = resolve_optimizer_dispatch(ContentIdentity("9" * 64))
        self.assertFalse(dispatch.optimizer_enabled)
        self.assertEqual(dispatch.reason, "optimizer_default_off")

    def test_identity_tampering_refuses_before_callbacks_or_authority(self):
        original = next(
            value.identity.run
            for value in self.fixture.runs.for_site("kee-cc").arms
            if value.identity.arm is PilotArm.FULL_OPTIMIZER
        )
        cases = (
            ("replay", {"replay": ContentIdentity("2" * 64)}, "held_out_identity_verification_failed"),
            ("profile", {"profile": ContentIdentity("3" * 64)}, "held_out_identity_verification_incomplete"),
            ("calibration", {"calibration": ContentIdentity("4" * 64)}, "held_out_identity_verification_incomplete"),
            (
                "runtime",
                {"runtime_dependencies": original.runtime_dependencies + (ContentIdentity("5" * 64),)},
                "held_out_identity_verification_failed",
            ),
        )
        for name, changes, expected in cases:
            with self.subTest(identity=name):
                changed_runs = self._tamper_full_run(
                    self.fixture.runs, "kee-cc", **changes
                )
                changed_decision = decide_pilot_feasibility(
                    statistics=self.fixture.statistics,
                    frozen_runs=changed_runs,
                )
                messages = []
                for _ in range(2):
                    calls = []
                    controller = HeldOutDecisionController()
                    with self.assertRaises(HeldOutAccessError) as failure:
                        self._evaluate(
                            controller,
                            runs=changed_runs,
                            decision=changed_decision,
                            loader=lambda _grant: calls.append("outcomes-read"),
                        )
                    messages.append(str(failure.exception))
                    self.assertIn(expected, messages[-1])
                    self.assertEqual(calls, [])
                    self.assertIsNone(
                        controller.decision_for(self.fixture.grant.final_decision_identity)
                    )
                    dispatch = resolve_optimizer_dispatch(
                        self.fixture.grant.acceptance_profile.candidate.content_identity
                    )
                    self.assertFalse(dispatch.optimizer_enabled)
                    self.assertEqual(dispatch.optimizer_output_role, "diagnostic_only")
                self.assertEqual(messages[0], messages[1])

    def test_post_exposure_replay_identity_change_needs_unexposed_partitions(self):
        controller = HeldOutDecisionController()
        accepted = self._evaluate(controller)
        changed_runs = self._tamper_full_run(
            self.fixture.runs,
            "kee-cc",
            replay=ContentIdentity("6" * 64),
        )
        changed_decision = decide_pilot_feasibility(
            statistics=self.fixture.statistics,
            frozen_runs=changed_runs,
        )
        changed_grant = freeze_held_out_acceptance(
            pilot_decision=changed_decision,
            statistics=self.fixture.statistics,
            frozen_runs=changed_runs,
            frozen_evidence=self.fixture.frozen,
            profiles=self.fixture.profiles,
            validated_profiles=self.fixture.tokens,
            scope=self.fixture.scope,
        )
        self.assertNotEqual(
            changed_grant.final_decision_identity,
            self.fixture.grant.final_decision_identity,
        )
        self.assertEqual(
            tuple(value.partition.content_identity for value in changed_grant.acceptance_profile.partitions),
            tuple(value.partition.content_identity for value in self.fixture.grant.acceptance_profile.partitions),
        )
        calls = []
        with self.assertRaisesRegex(HeldOutAccessError, "held_out_partition_previously_exposed"):
            self._evaluate(
                controller,
                runs=changed_runs,
                decision=changed_decision,
                grant=changed_grant,
                loader=lambda _grant: calls.append("outcomes-read"),
            )
        self.assertEqual(calls, [])
        authorization = default_off_dispatch_evidence(accepted)
        dispatch = resolve_optimizer_dispatch(accepted.candidate_identity, authorization)
        self.assertFalse(dispatch.optimizer_enabled)
        self.assertEqual(dispatch.reason, "hardening_authorization_incomplete")


if __name__ == "__main__":
    unittest.main()
