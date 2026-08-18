"""Focused unit tests for immutable Task 8.3 held-out controls."""
from dataclasses import replace
import unittest

from trafficlab.measurement.haware_held_out import (
    HeldOutAccessError,
    HeldOutDecisionController,
    HeldOutOutcomeBatch,
    default_off_dispatch_evidence,
    freeze_held_out_acceptance,
)
from trafficlab.measurement.haware_pilot import (
    ACCEPTANCE_SITES,
    SOURCE_GROUP,
    TRACK_GROUP,
    GroundTruthValidationPolicy,
    IndependentViewMembership,
    PartitionAssignment,
    PilotArm,
    PilotPopulationFreezer,
    compute_pilot_statistics,
    decide_pilot_feasibility,
    run_frozen_pilot_arms,
)
from trafficlab.motion.haware_accuracy.models import (
    ClosedInterval,
    ContentIdentity,
    DecisionStatus,
    PartitionKind,
    SeedClass,
)
from trafficlab.motion.haware_accuracy.validation import (
    resolve_optimizer_dispatch,
    validate_before_read,
)
from tests.test_haware_pilot import ground_truth, tracked_record
from tests.test_haware_pilot_statistics import accepted, rejected
from tests.test_haware_profile_validation import profile as acceptance_profile, scope as mvp_scope

CALIBRATION_ID = ContentIdentity("a" * 64)


def _policy(site):
    return GroundTruthValidationPolicy(
        site=site,
        calibration_identity=CALIBRATION_ID,
        reference_point="vehicle_ground_center",
        coordinate_x_m=ClosedInterval(lower=0.0, upper=100.0),
        coordinate_y_m=ClosedInterval(lower=0.0, upper=100.0),
        uncertainty_m=ClosedInterval(lower=0.0, upper=5.0),
    )


def _mixed_evidence(kee_held_out_tracks=2, taoyuan_held_out_tracks=2):
    records = []
    assignments = []
    views = []
    held_out_tracks = {
        "kee-cc": kee_held_out_tracks,
        "taoyuan-tc": taoyuan_held_out_tracks,
    }
    for site, prefix in (("kee-cc", "k"), ("taoyuan-tc", "t")):
        for partition in (PartitionKind.PILOT, PartitionKind.HELD_OUT):
            track_count = (
                held_out_tracks[site]
                if partition is PartitionKind.HELD_OUT
                else 2
            )
            tag = "p" if partition is PartitionKind.PILOT else "h"
            sequence = f"{prefix}-{tag}-video"
            assignments.append(
                PartitionAssignment(
                    site=site,
                    group_kind=SOURCE_GROUP,
                    group_id=sequence,
                    partition=partition,
                )
            )
            for track_number in range(track_count):
                track_id = f"{tag}-track-{track_number}"
                assignments.append(
                    PartitionAssignment(
                        site=site,
                        group_kind=TRACK_GROUP,
                        group_id=track_id,
                        partition=partition,
                    )
                )
                for ordinal in (1, 2):
                    value = tracked_record(
                        site,
                        f"{prefix}-{tag}{track_number}-{ordinal}",
                        f"d-{tag}{track_number}-{ordinal}",
                        track_id,
                        sequence,
                    )
                    records.append(value)
                    views.append(
                        IndependentViewMembership(
                            site=site,
                            frame_id=value.frame_id,
                            detection_id=value.detection_id,
                            view_id=f"camera:{track_number}",
                            camera_id="camera",
                            scene_region_id=str(track_number),
                            source_video_id=sequence,
                        )
                    )
    gt = tuple(
        replace(
            ground_truth(value),
            record=replace(
                ground_truth(value).record,
                metric_coordinate_m=(10.0, 20.0),
                uncertainty_m=0.25,
            ),
        )
        for value in records
    )
    return PilotPopulationFreezer().freeze(
        replay_records=tuple(records),
        ground_truth=gt,
        policies=tuple(_policy(site) for site in ACCEPTANCE_SITES),
        partition_assignments=tuple(assignments),
        independent_views=tuple(views),
    )


class HeldOutControlsTest(unittest.TestCase):
    def setUp(self):
        self.build_context()

    def build_context(self, kee_held_out_tracks=2, taoyuan_held_out_tracks=2):
        self.frozen = _mixed_evidence(
            kee_held_out_tracks=kee_held_out_tracks,
            taoyuan_held_out_tracks=taoyuan_held_out_tracks,
        )
        self.scope = mvp_scope()
        self.profiles = {site: acceptance_profile(site) for site in ACCEPTANCE_SITES}
        self.tokens = {
            site: validate_before_read(profile, self.scope)
            for site, profile in self.profiles.items()
        }

        def baseline(record):
            scale = self.profiles[record.site].calibration.snapshot.pixels_per_metre
            if record.frame_id.endswith("-2"):
                return {
                    "status": "rejected",
                    "sat_coords": None,
                    "heading": None,
                }
            return {
                "status": "ok",
                "sat_coords": (14.0 * scale, 20.0 * scale),
                "heading": 0.0,
            }

        def optimizer(record, profile, _configuration, _identity):
            scale = profile.calibration.snapshot.pixels_per_metre
            return accepted((11.0 * scale, 20.0 * scale), SeedClass.NON_WHEEL)

        self.runs = run_frozen_pilot_arms(
            frozen_evidence=self.frozen,
            outcome_access=self.frozen.outcome_access,
            profiles=self.profiles,
            validated_profiles=self.tokens,
            scope=self.scope,
            replay_identities={
                "kee-cc": ContentIdentity("c" * 64),
                "taoyuan-tc": ContentIdentity("d" * 64),
            },
            template_identity=ContentIdentity("e" * 64),
            code_revision="held-out-test-revision",
            runtime_dependencies=(ContentIdentity("f" * 64),),
            baseline_localize=baseline,
            optimizer_localize=optimizer,
        )
        self.statistics = compute_pilot_statistics(
            frozen_evidence=self.frozen,
            frozen_runs=self.runs,
            profiles=self.profiles,
        )
        self.pilot_decision = decide_pilot_feasibility(
            statistics=self.statistics, frozen_runs=self.runs
        )
        self.grant = freeze_held_out_acceptance(
            pilot_decision=self.pilot_decision,
            statistics=self.statistics,
            frozen_runs=self.runs,
            frozen_evidence=self.frozen,
            profiles=self.profiles,
            validated_profiles=self.tokens,
            scope=self.scope,
        )


    def loader(self, reject_site=None, bad_site=None):
        def load(grant):
            batches = []
            for site in ACCEPTANCE_SITES:
                partition = grant.acceptance_profile.partition_for_site(site)
                profile = self.profiles[site]
                scale = profile.calibration.snapshot.pixels_per_metre
                count = len(partition.ordered_eligible_ids)
                baseline = tuple(
                    {"status": "ok", "sat_coords": (14.0 * scale, 20.0 * scale), "heading": 0.0}
                    for _ in range(count)
                )
                candidate = tuple(
                    rejected()
                    if site == reject_site
                    else accepted((11.0 * scale, 20.0 * scale), SeedClass.NON_WHEEL)
                    for _ in range(count)
                )
                batches.append(
                    HeldOutOutcomeBatch(
                        site=site,
                        final_decision_identity=(
                            ContentIdentity("0" * 64) if site == bad_site else grant.final_decision_identity
                        ),
                        partition_identity=partition.partition.content_identity,
                        ordered_eligible_ids=partition.ordered_eligible_ids,
                        baseline_outcomes=baseline,
                        candidate_outcomes=candidate,
                    )
                )
            return tuple(batches)
        return load

    def evaluate(self, controller=None, **kwargs):
        controller = controller or HeldOutDecisionController()
        return controller.evaluate(
            grant=self.grant,
            pilot_decision=self.pilot_decision,
            statistics=self.statistics,
            frozen_runs=self.runs,
            frozen_evidence=self.frozen,
            profiles=self.profiles,
            validated_profiles=self.tokens,
            scope=self.scope,
            outcome_loader=kwargs.pop("outcome_loader", self.loader()),
            **kwargs,
        )

    def test_pilot_callbacks_never_receive_held_out_records(self):
        for site in ACCEPTANCE_SITES:
            run = self.runs.for_site(site)
            pilot_ids = tuple(
                value.eligible_detection_id
                for value in self.frozen.for_site(site).eligible_detections
                if value.partition is PartitionKind.PILOT
            )
            self.assertEqual(run.denominator, len(pilot_ids))
            self.assertTrue(all(value.ordered_eligible_ids == pilot_ids for value in run.arms))

    def test_access_requires_exact_complete_freeze_and_denies_tampering_before_load(self):
        calls = []
        changed = dict(self.profiles)
        changed["kee-cc"] = replace(changed["kee-cc"], profile_id="tampered")
        with self.assertRaisesRegex(HeldOutAccessError, "held_out_identity_verification_incomplete"):
            HeldOutDecisionController().evaluate(
                grant=self.grant,
                pilot_decision=self.pilot_decision,
                statistics=self.statistics,
                frozen_runs=self.runs,
                frozen_evidence=self.frozen,
                profiles=changed,
                validated_profiles=self.tokens,
                scope=self.scope,
                outcome_loader=lambda _grant: calls.append(True),
            )
        self.assertEqual(calls, [])

    def test_one_decision_per_identity_and_tampering_burns_attempt(self):
        controller = HeldOutDecisionController()
        self.assertIs(self.evaluate(controller).overall, DecisionStatus.GO)
        with self.assertRaisesRegex(HeldOutAccessError, "final_decision_identity_already_evaluated"):
            self.evaluate(controller)
        tampered = HeldOutDecisionController()
        with self.assertRaisesRegex(HeldOutAccessError, "held_out_outcome_decision_identity_mismatch"):
            self.evaluate(tampered, outcome_loader=self.loader(bad_site="kee-cc"))
        with self.assertRaisesRegex(HeldOutAccessError, "final_decision_identity_already_evaluated"):
            self.evaluate(tampered)


    def test_post_exposure_threshold_change_requires_new_untouched_partition(self):
        controller = HeldOutDecisionController()
        self.evaluate(controller)
        site = self.statistics.for_site("kee-cc")
        full = site.for_arm(PilotArm.FULL_OPTIMIZER)
        changed_full = replace(
            full,
            candidate_thresholds=replace(
                full.candidate_thresholds,
                maximum_median_error_m=full.candidate_thresholds.maximum_median_error_m + 0.1,
            ),
        )
        changed_statistics = replace(
            self.statistics,
            sites=tuple(
                replace(
                    value,
                    reports=tuple(
                        changed_full if report.arm is PilotArm.FULL_OPTIMIZER else report
                        for report in value.reports
                    ),
                )
                if value.site == "kee-cc" else value
                for value in self.statistics.sites
            ),
        )
        changed_decision = decide_pilot_feasibility(
            statistics=changed_statistics, frozen_runs=self.runs
        )
        changed_grant = freeze_held_out_acceptance(
            pilot_decision=changed_decision,
            statistics=changed_statistics,
            frozen_runs=self.runs,
            frozen_evidence=self.frozen,
            profiles=self.profiles,
            validated_profiles=self.tokens,
            scope=self.scope,
        )
        self.assertNotEqual(changed_grant.final_decision_identity, self.grant.final_decision_identity)
        calls = []
        with self.assertRaisesRegex(HeldOutAccessError, "held_out_partition_previously_exposed"):
            controller.evaluate(
                grant=changed_grant,
                pilot_decision=changed_decision,
                statistics=changed_statistics,
                frozen_runs=self.runs,
                frozen_evidence=self.frozen,
                profiles=self.profiles,
                validated_profiles=self.tokens,
                scope=self.scope,
                outcome_loader=lambda _grant: calls.append(True),
            )
        self.assertEqual(calls, [])

    def test_precedence_both_site_conjunction_and_diagnostics_cannot_rescue(self):
        self.build_context(taoyuan_held_out_tracks=1)
        first = self.evaluate(
            HeldOutDecisionController(),
            outcome_loader=self.loader(reject_site="kee-cc"),
            diagnostic_values={"taipei-cm": "go", "pooled": "go", "proxy": "go", "selective_risk": "go"},
        )
        second = self.evaluate(
            HeldOutDecisionController(),
            outcome_loader=self.loader(reject_site="kee-cc"),
            diagnostic_values={"taipei-cm": "no_go", "pooled": "no_go", "proxy": "no_go", "selective_risk": "no_go"},
        )
        self.assertIs(first.kee_cc.status, DecisionStatus.NO_GO)
        self.assertIs(first.taoyuan_tc.status, DecisionStatus.INSUFFICIENT_DATA)
        self.assertIs(first.overall, DecisionStatus.NO_GO)
        self.assertEqual(first, second)

    def test_site_failure_is_not_rescued_by_other_site(self):
        decision = self.evaluate(outcome_loader=self.loader(reject_site="taoyuan-tc"))
        self.assertIs(decision.kee_cc.status, DecisionStatus.GO)
        self.assertIs(decision.taoyuan_tc.status, DecisionStatus.NO_GO)
        self.assertIs(decision.overall, DecisionStatus.NO_GO)

    def test_dual_site_go_only_feeds_default_off_guard_without_hardening(self):
        decision = self.evaluate()
        evidence = default_off_dispatch_evidence(decision)
        self.assertIsNotNone(evidence)
        dispatch = resolve_optimizer_dispatch(decision.candidate_identity, evidence)
        self.assertFalse(dispatch.optimizer_enabled)
        self.assertEqual(dispatch.production_path, "corrected_legacy_baseline")
        self.assertEqual(dispatch.optimizer_output_role, "diagnostic_only")
        self.assertEqual(dispatch.reason, "hardening_authorization_incomplete")


if __name__ == "__main__":
    unittest.main()