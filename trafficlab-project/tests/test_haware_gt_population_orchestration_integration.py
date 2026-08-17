"""Synthetic GT/population/orchestration integration tests for task 7.5.

These fixtures exercise contracts only.  They are not real pilot or acceptance
 evidence and must continue to report ``insufficient_data``.
"""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trafficlab.measurement.haware_pilot import (  # noqa: E402
    ACCEPTANCE_SITES,
    GROUND_TRUTH_CONTAMINATION,
    GROUND_TRUTH_DUPLICATE_GROUP,
    GROUND_TRUTH_MATCH_COUNT_INVALID,
    PARTITION_ASSIGNMENT_CONFLICT,
    POPULATION_NOT_FROZEN,
    SOURCE_GROUP,
    TRACK_GROUP,
    PartitionAssignment,
    PilotArm,
    PilotEvidenceError,
    PilotPopulationFreezer,
    run_frozen_pilot_arms,
)
from trafficlab.motion.haware_accuracy.models import (  # noqa: E402
    ContentIdentity,
    DecisionStatus,
    PartitionKind,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read  # noqa: E402
from tests.test_haware_observation_replay import record  # noqa: E402
from tests.test_haware_pilot import (  # noqa: E402
    assignment,
    complete_fixture,
    ground_truth,
    policy,
    tracked_record,
    view,
)
from tests.test_haware_profile_validation import (  # noqa: E402
    profile as acceptance_profile,
    scope as mvp_scope,
)
from tests.test_haware_track_provenance import claim  # noqa: E402


class GroundTruthPopulationOrchestrationIntegrationTest(unittest.TestCase):
    """Requirements 8.5-8.13, 9.1-9.19, and 10.1-10.2/10.15-10.19/10.32."""
    def setUp(self):
        records, ground_truth_values, assignments, views = complete_fixture()
        # Both acceptance sites need non-empty pilot populations for the
        # four-configuration integration assertions.
        self.records = records
        self.ground_truth = ground_truth_values
        self.assignments = tuple(
            replace(value, partition=PartitionKind.PILOT)
            if value.site == "taoyuan-tc"
            else value
            for value in assignments
        )
        self.views = views
        self.policies = tuple(policy(site) for site in ACCEPTANCE_SITES)
        self.scope = mvp_scope()
        self.profiles = {
            site: acceptance_profile(site) for site in ACCEPTANCE_SITES
        }
        self.validated_profiles = {
            site: validate_before_read(self.profiles[site], self.scope)
            for site in ACCEPTANCE_SITES
        }

    def freeze(self, *, records=None, ground_truth_values=None, assignments=None, views=None):
        freezer = PilotPopulationFreezer()
        frozen = freezer.freeze(
            replay_records=self.records if records is None else records,
            ground_truth=(
                self.ground_truth
                if ground_truth_values is None
                else ground_truth_values
            ),
            policies=self.policies,
            partition_assignments=(
                self.assignments if assignments is None else assignments
            ),
            independent_views=self.views if views is None else views,
        )
        return freezer, frozen

    def run_arms(self, frozen, baseline_localize, optimizer_localize):
        return run_frozen_pilot_arms(
            frozen_evidence=frozen,
            outcome_access=frozen.outcome_access,
            profiles=self.profiles,
            validated_profiles=self.validated_profiles,
            scope=self.scope,
            replay_identities={
                "kee-cc": ContentIdentity("c" * 64),
                "taoyuan-tc": ContentIdentity("d" * 64),
            },
            template_identity=ContentIdentity("e" * 64),
            code_revision="synthetic-task-7.5",
            runtime_dependencies=(ContentIdentity("f" * 64),),
            baseline_localize=baseline_localize,
            optimizer_localize=optimizer_localize,
        )

    def test_outcomes_require_atomic_freeze_and_token_captures_all_population_inputs(self):
        freezer = PilotPopulationFreezer()
        with self.assertRaises(PilotEvidenceError) as unavailable:
            _ = freezer.outcome_access
        self.assertEqual(unavailable.exception.code, POPULATION_NOT_FROZEN)

        freezer, frozen = self.freeze()
        token = freezer.outcome_access
        self.assertEqual(token, frozen.outcome_access)
        self.assertEqual(dict(token.denominators), {"kee-cc": 2, "taoyuan-tc": 2})

        for site in ACCEPTANCE_SITES:
            site_evidence = frozen.for_site(site)
            self.assertEqual(
                dict(token.ordered_eligible_ids)[site],
                site_evidence.population.frozen_eligible_ids,
            )
            self.assertEqual(
                dict(token.population_identities)[site],
                site_evidence.population.content_identity,
            )
            self.assertEqual(site_evidence.denominator, 2)
            self.assertTrue(site_evidence.population.ground_truth_group_ids)
            self.assertEqual(len(site_evidence.population.real_track_ids), 1)
            self.assertEqual(len(site_evidence.population.source_sequences), 1)
            self.assertEqual(len(site_evidence.population.independent_views), 1)
            pilot = next(
                item
                for item in site_evidence.population.partitions
                if item.kind is PartitionKind.PILOT
            )
            self.assertEqual(
                pilot.eligible_detection_ids,
                site_evidence.population.frozen_eligible_ids,
            )
    def test_exact_one_join_and_whole_group_contamination_and_duplicates(self):
        # No GT match excludes one detection while the other site remains exact.
        _, missing = self.freeze(ground_truth_values=self.ground_truth[1:])
        self.assertEqual(missing.for_site("kee-cc").denominator, 1)
        self.assertIn(
            GROUND_TRUTH_MATCH_COUNT_INVALID,
            {item.reason for item in missing.for_site("kee-cc").exclusions},
        )
        self.assertEqual(missing.for_site("taoyuan-tc").denominator, 2)

        # One contaminated member contaminates the complete matching group.
        contaminated_gt = (
            replace(
                self.ground_truth[0],
                matching_group_id="kee-whole-group",
                creation_inputs=("candidate_output",),
            ),
            replace(self.ground_truth[1], matching_group_id="kee-whole-group"),
        ) + self.ground_truth[2:]
        _, contaminated = self.freeze(ground_truth_values=contaminated_gt)
        kee = contaminated.for_site("kee-cc")
        self.assertEqual(kee.denominator, 0)
        contaminated_ids = {
            (item.frame_id, item.detection_id)
            for item in kee.exclusions
            if item.reason == GROUND_TRUTH_CONTAMINATION
        }
        self.assertEqual(contaminated_ids, {("k1", "d1"), ("k2", "d2")})
        self.assertEqual(contaminated.for_site("taoyuan-tc").denominator, 2)

        # Duplicate identity across distinct GT groups excludes every duplicate
        # group deterministically, not an iteration-order-selected winner.
        duplicate = replace(
            self.ground_truth[0], matching_group_id="kee-duplicate-group"
        )
        _, duplicated = self.freeze(
            ground_truth_values=(duplicate,) + tuple(reversed(self.ground_truth)),
            views=tuple(reversed(self.views)),
        )
        kee = duplicated.for_site("kee-cc")
        self.assertEqual(kee.denominator, 1)
        self.assertGreaterEqual(
            sum(
                item.reason == GROUND_TRUTH_DUPLICATE_GROUP
                and item.frame_id == "k1"
                and item.detection_id == "d1"
                for item in kee.exclusions
            ),
            2,
        )
        self.assertEqual(duplicated.for_site("taoyuan-tc").denominator, 2)

    def test_partition_conflict_is_atomic_and_outcomes_remain_unavailable(self):
        conflicting = self.assignments + (
            assignment(
                "kee-cc",
                SOURCE_GROUP,
                "kee-video",
                PartitionKind.HELD_OUT,
            ),
        )
        freezer = PilotPopulationFreezer()
        with self.assertRaises(PilotEvidenceError) as conflict:
            freezer.freeze(
                replay_records=self.records,
                ground_truth=self.ground_truth,
                policies=self.policies,
                partition_assignments=conflicting,
                independent_views=self.views,
            )
        self.assertEqual(conflict.exception.code, PARTITION_ASSIGNMENT_CONFLICT)
        with self.assertRaises(PilotEvidenceError) as unavailable:
            _ = freezer.outcome_access
        self.assertEqual(unavailable.exception.code, POPULATION_NOT_FROZEN)
    def test_pseudo_and_diagnostic_site_inputs_cannot_change_acceptance_sites(self):
        pseudo_records = tuple(
            replace(
                tracked_record(
                    "kee-cc", f"p{ordinal}", f"pd{ordinal}", "500", "kee-video"
                ),
                track=claim(
                    claimed_id="500",
                    source_sequence="kee-video",
                    association_provenance="frame-local-detection-index",
                ),
            )
            for ordinal in (1, 2)
        )
        taipei_records = tuple(
            tracked_record(
                "taipei-cm", f"c{ordinal}", f"cd{ordinal}", "track-1", "cm-video"
            )
            for ordinal in (1, 2)
        )
        no_track = replace(
            record(), site="taoyuan-tc", frame_id="no-track", track=None
        )
        _, baseline = self.freeze()
        _, augmented = self.freeze(
            records=self.records + pseudo_records + taipei_records + (no_track,),
            ground_truth_values=(
                self.ground_truth
                + tuple(ground_truth(item) for item in pseudo_records)
                + tuple(ground_truth(item) for item in taipei_records)
            ),
            views=(
                self.views
                + tuple(view(item) for item in pseudo_records)
                + tuple(view(item) for item in taipei_records)
            ),
        )
        self.assertEqual(augmented, baseline)
        self.assertEqual(
            baseline.for_site("kee-cc").population.real_track_ids,
            ("kee-cc:track-1",),
        )
        self.assertEqual(
            baseline.for_site("taoyuan-tc").population.real_track_ids,
            ("taoyuan-tc:track-1",),
        )

    def test_all_four_configurations_receive_identical_ordered_site_inputs(self):
        _, frozen = self.freeze()
        calls = []

        def baseline(record_value):
            calls.append(
                (record_value.site, PilotArm.CORRECTED_BASELINE, record_value.frame_id)
            )
            return ("baseline", record_value.frame_id)

        def optimizer(record_value, _profile, configuration, identity):
            self.assertEqual(identity.candidate_configuration, configuration)
            calls.append((record_value.site, identity.arm, record_value.frame_id))
            return (identity.arm.value, record_value.frame_id)

        runs = self.run_arms(frozen, baseline, optimizer)
        self.assertIs(runs.current_evidence_status, DecisionStatus.INSUFFICIENT_DATA)
        self.assertFalse(runs.proven_improvement_claim_allowed)
        self.assertTrue(runs.optimizer_default_off_outside_pilot)

        expected = {
            "kee-cc": ("kee-cc:k1:d1", "kee-cc:k2:d2"),
            "taoyuan-tc": ("taoyuan-tc:t1:d1", "taoyuan-tc:t2:d2"),
        }
        frame_by_eligible_id = {
            item.eligible_detection_id: item.record.frame_id
            for site in frozen.sites
            for item in site.eligible_detections
        }
        for site in ACCEPTANCE_SITES:
            site_runs = runs.for_site(site)
            self.assertEqual(site_runs.denominator, 2)
            self.assertEqual(
                tuple(item.identity.arm for item in site_runs.arms), tuple(PilotArm)
            )
            self.assertTrue(
                all(item.ordered_eligible_ids == expected[site] for item in site_runs.arms)
            )
            expected_frames = tuple(frame_by_eligible_id[item] for item in expected[site])
            for arm in PilotArm:
                self.assertEqual(
                    tuple(
                        frame_id
                        for call_site, call_arm, frame_id in calls
                        if call_site == site and call_arm is arm
                    ),
                    expected_frames,
                )
            identities = {
                item.identity.arm: item.identity for item in site_runs.arms
            }
            full = identities[PilotArm.FULL_OPTIMIZER]
            for arm, changed_flag in (
                (
                    PilotArm.WHEEL_INITIALIZATION_DISABLED,
                    "wheel_seeded_initialization_enabled",
                ),
                (
                    PilotArm.NON_WHEEL_INITIALIZATION_DISABLED,
                    "non_wheel_seeded_initialization_enabled",
                ),
            ):
                ablation = identities[arm]
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
                self.assertEqual(changed, {changed_flag})
                self.assertEqual(full.run, ablation.run)
                self.assertEqual(full.eligible_ordering, ablation.eligible_ordering)
                self.assertEqual(full.scoring, ablation.scoring)
                self.assertEqual(full.support_rules, ablation.support_rules)
                self.assertEqual(full.gates, ablation.gates)
                self.assertEqual(full.metric_definitions, ablation.metric_definitions)
                self.assertEqual(full.baseline_identity, ablation.baseline_identity)


if __name__ == "__main__":
    unittest.main()
