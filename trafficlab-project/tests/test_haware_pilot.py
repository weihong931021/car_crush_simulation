"""Focused tests for outcome-blind Haware pilot population freezing."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trafficlab.measurement.haware_pilot import (  # noqa: E402
    GROUND_TRUTH_CONTAMINATION,
    GROUND_TRUTH_CONTAMINATION_EXCLUSION_FAILED,
    GROUND_TRUTH_DUPLICATE_GROUP,
    GROUND_TRUTH_MATCH_COUNT_INVALID,
    GROUND_TRUTH_REFERENCE_POINT_INVALID,
    PARTITION_ASSIGNMENT_CONFLICT,
    POPULATION_NOT_FROZEN,
    SOURCE_GROUP,
    TRACK_GROUP,
    GroundTruthEvidence,
    GroundTruthValidationPolicy,
    IndependentViewMembership,
    PartitionAssignment,
    PilotArm,
    PilotCandidateConfiguration,
    PilotEvidenceError,
    PilotPopulationFreezer,
    run_frozen_pilot_arms,
)
from trafficlab.motion.haware_accuracy.models import (  # noqa: E402
    ClosedInterval,
    ContentIdentity,
    GroundTruthRecord,
    PartitionKind,
    SourceProvenance,
)
from tests.test_haware_observation_replay import record  # noqa: E402
from tests.test_haware_profile_validation import (  # noqa: E402
    profile as acceptance_profile,
    scope as mvp_scope,
)
from tests.test_haware_track_provenance import claim  # noqa: E402
from trafficlab.motion.haware_accuracy.validation import validate_before_read  # noqa: E402


CALIBRATION_ID = ContentIdentity("a" * 64)
GT_SOURCE_ID = ContentIdentity("b" * 64)


def tracked_record(site, frame_id, detection_id, track_id, sequence):
    track = claim(claimed_id=track_id, source_sequence=sequence)
    return replace(
        record(),
        site=site,
        source_sequence=sequence,
        frame_id=frame_id,
        detection_id=detection_id,
        track=track,
    )


def policy(site):
    return GroundTruthValidationPolicy(
        site=site,
        calibration_identity=CALIBRATION_ID,
        reference_point="vehicle_ground_center",
        coordinate_x_m=ClosedInterval(lower=0.0, upper=100.0),
        coordinate_y_m=ClosedInterval(lower=0.0, upper=100.0),
        uncertainty_m=ClosedInterval(lower=0.0, upper=5.0),
    )


def ground_truth(record_value, group_id=None, creation_inputs=("raw_video",)):
    assert record_value.track is not None
    value = GroundTruthRecord(
        site=record_value.site,
        frame_id=record_value.frame_id,
        detection_id=record_value.detection_id,
        real_track_id=record_value.track.claimed_id,
        reference_point="vehicle_ground_center",
        metric_coordinate_m=(10.0, 20.0),
        calibration_identity=CALIBRATION_ID,
        source=SourceProvenance(
            source_id=f"independent-gt:{record_value.site}",
            repository_relative_path=f"evidence/{record_value.site}/gt.json",
            source_content_identity=GT_SOURCE_ID,
        ),
        annotator_provenance="annotator-team-v1",
        independence_attestation="independent_no_haware_access",
        uncertainty_m=0.25,
    )
    return GroundTruthEvidence(
        record=value,
        matching_group_id=group_id or f"group-{record_value.frame_id}",
        units="metre",
        creation_inputs=creation_inputs,
        source_lineage=("manual_raw_video_annotation",),
    )


def view(record_value):
    return IndependentViewMembership(
        site=record_value.site,
        frame_id=record_value.frame_id,
        detection_id=record_value.detection_id,
        view_id="camera-a:road-center",
        camera_id="camera-a",
        scene_region_id="road-center",
        source_video_id=record_value.source_sequence,
    )


def assignment(site, kind, group_id, partition):
    return PartitionAssignment(
        site=site,
        group_kind=kind,
        group_id=group_id,
        partition=partition,
    )


def complete_fixture():
    records = (
        tracked_record("kee-cc", "k1", "d1", "track-1", "kee-video"),
        tracked_record("kee-cc", "k2", "d2", "track-1", "kee-video"),
        tracked_record("taoyuan-tc", "t1", "d1", "track-1", "tao-video"),
        tracked_record("taoyuan-tc", "t2", "d2", "track-1", "tao-video"),
    )
    assignments = (
        assignment("kee-cc", TRACK_GROUP, "track-1", PartitionKind.PILOT),
        assignment("kee-cc", SOURCE_GROUP, "kee-video", PartitionKind.PILOT),
        assignment("taoyuan-tc", TRACK_GROUP, "track-1", PartitionKind.HELD_OUT),
        assignment("taoyuan-tc", SOURCE_GROUP, "tao-video", PartitionKind.HELD_OUT),
    )
    return records, tuple(ground_truth(value) for value in records), assignments, tuple(
        view(value) for value in records
    )


class PilotPopulationFreezerTest(unittest.TestCase):
    def freeze(self, records, gt, assignments, views):
        freezer = PilotPopulationFreezer()
        frozen = freezer.freeze(
            replay_records=records,
            ground_truth=gt,
            policies=(policy("kee-cc"), policy("taoyuan-tc")),
            partition_assignments=assignments,
            independent_views=views,
        )
        return freezer, frozen

    def test_freezes_exact_matches_memberships_denominators_and_site_namespaces(self):
        records, gt, assignments, views = complete_fixture()
        freezer = PilotPopulationFreezer()
        with self.assertRaises(PilotEvidenceError) as failure:
            _ = freezer.outcome_access
        self.assertEqual(failure.exception.code, POPULATION_NOT_FROZEN)

        frozen = freezer.freeze(
            replay_records=records,
            ground_truth=gt,
            policies=(policy("kee-cc"), policy("taoyuan-tc")),
            partition_assignments=assignments,
            independent_views=views,
        )

        kee = frozen.for_site("kee-cc")
        tao = frozen.for_site("taoyuan-tc")
        self.assertEqual((kee.denominator, tao.denominator), (2, 2))
        self.assertEqual(kee.population.real_track_ids, ("kee-cc:track-1",))
        self.assertEqual(tao.population.real_track_ids, ("taoyuan-tc:track-1",))
        self.assertEqual(kee.population.source_sequences, ("kee-cc:kee-video",))
        self.assertEqual(tao.population.source_sequences, ("taoyuan-tc:tao-video",))
        self.assertTrue(all(value.partition is PartitionKind.PILOT for value in kee.eligible_detections))
        self.assertTrue(all(value.partition is PartitionKind.HELD_OUT for value in tao.eligible_detections))
        self.assertEqual(freezer.outcome_access, frozen.outcome_access)
        self.assertEqual(dict(frozen.outcome_access.denominators), {"kee-cc": 2, "taoyuan-tc": 2})
        with self.assertRaises(PilotEvidenceError):
            freezer.freeze(
                replay_records=records,
                ground_truth=gt,
                policies=(policy("kee-cc"), policy("taoyuan-tc")),
                partition_assignments=assignments,
                independent_views=views,
            )

    def test_partition_conflict_fails_atomically_before_outcome_access(self):
        records, gt, assignments, views = complete_fixture()
        conflicting = assignments + (
            assignment("kee-cc", SOURCE_GROUP, "kee-video", PartitionKind.HELD_OUT),
        )
        freezer = PilotPopulationFreezer()
        with self.assertRaises(PilotEvidenceError) as failure:
            freezer.freeze(
                replay_records=records,
                ground_truth=gt,
                policies=(policy("kee-cc"), policy("taoyuan-tc")),
                partition_assignments=conflicting,
                independent_views=views,
            )
        self.assertEqual(failure.exception.code, PARTITION_ASSIGNMENT_CONFLICT)
        with self.assertRaises(PilotEvidenceError) as locked:
            _ = freezer.outcome_access
        self.assertEqual(locked.exception.code, POPULATION_NOT_FROZEN)

    def test_contamination_excludes_complete_group_and_incomplete_scope_halts(self):
        records, gt, assignments, views = complete_fixture()
        contaminated = (
            replace(gt[0], matching_group_id="batch", creation_inputs=("haware_overlay",)),
            replace(gt[1], matching_group_id="batch"),
            gt[2],
            gt[3],
        )
        _, frozen = self.freeze(records, contaminated, assignments, views)
        kee = frozen.for_site("kee-cc")
        self.assertEqual(kee.denominator, 0)
        reasons = {value.reason for value in kee.exclusions}
        self.assertIn(GROUND_TRUTH_CONTAMINATION, reasons)
        self.assertIn(GROUND_TRUTH_MATCH_COUNT_INVALID, reasons)

        unsafe = replace(
            contaminated[0], matching_group_complete=False
        )
        freezer = PilotPopulationFreezer()
        with self.assertRaises(PilotEvidenceError) as failure:
            freezer.freeze(
                replay_records=records,
                ground_truth=(unsafe,) + contaminated[1:],
                policies=(policy("kee-cc"), policy("taoyuan-tc")),
                partition_assignments=assignments,
                independent_views=views,
            )
        self.assertEqual(
            failure.exception.code, GROUND_TRUTH_CONTAMINATION_EXCLUSION_FAILED
        )

    def test_duplicate_gt_groups_are_permutation_invariant_and_excluded(self):
        records, gt, assignments, views = complete_fixture()
        duplicate = replace(gt[0], matching_group_id="duplicate-group")
        left = self.freeze(records, gt + (duplicate,), assignments, views)[1]
        right = self.freeze(records, (duplicate,) + tuple(reversed(gt)), assignments, tuple(reversed(views)))[1]
        self.assertEqual(left, right)
        kee = left.for_site("kee-cc")
        self.assertEqual(kee.denominator, 1)
        self.assertIn(GROUND_TRUTH_DUPLICATE_GROUP, {value.reason for value in kee.exclusions})

    def test_invalid_reference_point_is_group_excluded(self):
        records, gt, assignments, views = complete_fixture()
        invalid_record = replace(gt[0].record, reference_point="rear_axle")
        invalid = replace(gt[0], record=invalid_record)
        _, frozen = self.freeze(records, (invalid,) + gt[1:], assignments, views)
        kee = frozen.for_site("kee-cc")
        self.assertEqual(kee.denominator, 1)
        self.assertIn(
            GROUND_TRUTH_REFERENCE_POINT_INVALID,
            {value.reason for value in kee.exclusions},
        )

    def test_pseudo_no_track_and_diagnostic_site_records_cannot_change_populations(self):
        records, gt, assignments, views = complete_fixture()
        pseudo = replace(
            tracked_record("kee-cc", "p1", "pd1", "500", "kee-video"),
            track=claim(
                claimed_id="500",
                source_sequence="kee-video",
                association_provenance="frame-local-detection-index",
            ),
        )
        no_track = replace(record(), site="taoyuan-tc", frame_id="none", track=None)
        taipei = (
            tracked_record("taipei-cm", "c1", "d1", "cm-track", "cm-video"),
            tracked_record("taipei-cm", "c2", "d2", "cm-track", "cm-video"),
        )
        baseline = self.freeze(records, gt, assignments, views)[1]
        changed = self.freeze(
            records + (pseudo, no_track) + taipei,
            gt + tuple(ground_truth(value) for value in taipei),
            assignments,
            views + tuple(view(value) for value in taipei),
        )[1]
        self.assertEqual(baseline, changed)


class PilotArmOrchestrationTest(unittest.TestCase):
    def setUp(self):
        records, gt, assignments, views = complete_fixture()
        self.frozen = PilotPopulationFreezer().freeze(
            replay_records=records,
            ground_truth=gt,
            policies=(policy("kee-cc"), policy("taoyuan-tc")),
            partition_assignments=assignments,
            independent_views=views,
        )
        self.scope = mvp_scope()
        self.profiles = {
            site: acceptance_profile(site) for site in ("kee-cc", "taoyuan-tc")
        }
        self.tokens = {
            site: validate_before_read(value, self.scope)
            for site, value in self.profiles.items()
        }
        self.replays = {
            "kee-cc": ContentIdentity("c" * 64),
            "taoyuan-tc": ContentIdentity("d" * 64),
        }
        self.template = ContentIdentity("e" * 64)
        self.runtime = (ContentIdentity("f" * 64), ContentIdentity("1" * 64))

    def run_arms(self, baseline, optimizer):
        return run_frozen_pilot_arms(
            frozen_evidence=self.frozen,
            outcome_access=self.frozen.outcome_access,
            profiles=self.profiles,
            validated_profiles=self.tokens,
            scope=self.scope,
            replay_identities=self.replays,
            template_identity=self.template,
            code_revision="revision-abc123",
            runtime_dependencies=self.runtime,
            baseline_localize=baseline,
            optimizer_localize=optimizer,
        )

    def test_runs_four_isolated_arms_on_identical_stable_site_ordering(self):
        baseline_calls = []
        optimizer_calls = []

        def baseline(record_value):
            baseline_calls.append((record_value.site, record_value.frame_id))
            return ("baseline", record_value.frame_id)

        def optimizer(record_value, profile_value, configuration, identity):
            self.assertEqual(record_value.site, profile_value.cue_evidence.site)
            self.assertEqual(identity.site, record_value.site)
            optimizer_calls.append(
                (
                    record_value.site,
                    record_value.frame_id,
                    identity.arm,
                    configuration.wheel_seeded_initialization_enabled,
                    configuration.non_wheel_seeded_initialization_enabled,
                )
            )
            return (identity.arm.value, record_value.frame_id)

        result = self.run_arms(baseline, optimizer)

        self.assertEqual(result.current_evidence_status.value, "insufficient_data")
        self.assertFalse(result.proven_improvement_claim_allowed)
        self.assertTrue(result.optimizer_default_off_outside_pilot)
        self.assertEqual(len(baseline_calls), 2)
        self.assertEqual(len(optimizer_calls), 6)
        expected_by_site = {
            "kee-cc": ("kee-cc:k1:d1", "kee-cc:k2:d2"),
            "taoyuan-tc": (),
        }
        self.assertEqual(
            tuple(f"{site}:{frame}:d{frame[-1]}" for site, frame in baseline_calls),
            expected_by_site["kee-cc"],
        )
        self.assertEqual(
            {
                site: tuple(
                    f"{call_site}:{frame}:d{frame[-1]}"
                    for call_site, frame, arm, _wheel, _non_wheel in optimizer_calls
                    if call_site == site and arm is PilotArm.FULL_OPTIMIZER
                )
                for site in ("kee-cc", "taoyuan-tc")
            },
            expected_by_site,
        )
        for site in ("kee-cc", "taoyuan-tc"):
            site_run = result.for_site(site)
            expected = expected_by_site[site]
            self.assertEqual(site_run.denominator, len(expected))
            self.assertTrue(
                all(arm.ordered_eligible_ids == expected for arm in site_run.arms)
            )
            self.assertEqual(
                tuple(arm.identity.arm for arm in site_run.arms), tuple(PilotArm)
            )
        self.assertEqual(
            {(call[2], call[3], call[4]) for call in optimizer_calls},
            {
                (PilotArm.FULL_OPTIMIZER, True, True),
                (PilotArm.WHEEL_INITIALIZATION_DISABLED, False, True),
                (PilotArm.NON_WHEEL_INITIALIZATION_DISABLED, True, False),
            },
        )

    def test_ablation_and_run_identities_change_only_named_enable_flag(self):
        result = self.run_arms(
            lambda value: value.detection_id,
            lambda value, _profile, _configuration, _identity: value.detection_id,
        )
        repeated = self.run_arms(
            lambda value: value.detection_id,
            lambda value, _profile, _configuration, _identity: value.detection_id,
        )
        self.assertEqual(
            tuple(arm.identity for site in result.sites for arm in site.arms),
            tuple(arm.identity for site in repeated.sites for arm in site.arms),
        )

        for site in result.sites:
            by_arm = {arm.identity.arm: arm.identity for arm in site.arms}
            full = by_arm[PilotArm.FULL_OPTIMIZER]
            for arm, expected_flag in (
                (PilotArm.WHEEL_INITIALIZATION_DISABLED, "wheel_seeded_initialization_enabled"),
                (PilotArm.NON_WHEEL_INITIALIZATION_DISABLED, "non_wheel_seeded_initialization_enabled"),
            ):
                ablation = by_arm[arm]
                changed = {
                    name
                    for name in (
                        "architecture",
                        "optimizer_profile",
                        "wheel_seeded_initialization_enabled",
                        "non_wheel_seeded_initialization_enabled",
                    )
                    if getattr(full.candidate_configuration, name)
                    != getattr(ablation.candidate_configuration, name)
                }
                self.assertEqual(changed, {expected_flag})
                self.assertEqual(full.run, ablation.run)
                self.assertEqual(full.eligible_ordering, ablation.eligible_ordering)
                self.assertEqual(full.scoring, ablation.scoring)
                self.assertEqual(full.support_rules, ablation.support_rules)
                self.assertEqual(full.gates, ablation.gates)
                self.assertEqual(full.metric_definitions, ablation.metric_definitions)
                self.assertEqual(full.baseline_identity, ablation.baseline_identity)

    def test_invalid_access_identity_stops_before_any_localizer_runs(self):
        calls = []
        altered = replace(
            self.frozen.outcome_access,
            denominators=(("kee-cc", 999), ("taoyuan-tc", 2)),
        )
        with self.assertRaisesRegex(PilotEvidenceError, "outcome_access_identity_mismatch"):
            run_frozen_pilot_arms(
                frozen_evidence=self.frozen,
                outcome_access=altered,
                profiles=self.profiles,
                validated_profiles=self.tokens,
                scope=self.scope,
                replay_identities=self.replays,
                template_identity=self.template,
                code_revision="revision-abc123",
                runtime_dependencies=self.runtime,
                baseline_localize=lambda value: calls.append(value),
                optimizer_localize=lambda value, *_args: calls.append(value),
            )
        self.assertEqual(calls, [])

    def test_candidate_configuration_rejects_disabling_both_optimizer_seed_classes(self):
        with self.assertRaisesRegex(ValueError, "requires_initialization_class"):
            PilotCandidateConfiguration(
                architecture="image_space_optimizer",
                optimizer_profile=self.profiles["kee-cc"].optimizer.content_identity,
                wheel_seeded_initialization_enabled=False,
                non_wheel_seeded_initialization_enabled=False,
            )


if __name__ == "__main__":
    unittest.main()
