"""Focused unit tests for per-site Haware pilot statistics (Task 8.1)."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trafficlab.measurement.haware_pilot import (  # noqa: E402
    ACCEPTANCE_SITES,
    SOURCE_GROUP,
    TRACK_GROUP,
    GroundTruthValidationPolicy,
    IndependentViewMembership,
    PartitionAssignment,
    PilotArm,
    PilotPopulationFreezer,
    compute_pilot_statistics,
    freeze_pilot_statistics_method,
    run_frozen_pilot_arms,
)
from trafficlab.motion.haware_accuracy.models import (  # noqa: E402
    ClosedInterval,
    ContentIdentity,
    Correspondence,
    CueFamily,
    HypothesisPath,
    HypothesisState,
    InitializationSource,
    LocalizationDiagnostics,
    LocalizationResult,
    LocalizationStatus,
    PartitionKind,
    SeedClass,
    SemanticPath,
)
from tests.test_haware_pilot import ground_truth, tracked_record  # noqa: E402
from tests.test_haware_profile_validation import (  # noqa: E402
    profile as acceptance_profile,
    scope as mvp_scope,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read  # noqa: E402


CALIBRATION_ID = ContentIdentity("a" * 64)

def policy(site):
    return GroundTruthValidationPolicy(
        site=site,
        calibration_identity=CALIBRATION_ID,
        reference_point="vehicle_ground_center",
        coordinate_x_m=ClosedInterval(lower=0.0, upper=100.0),
        coordinate_y_m=ClosedInterval(lower=0.0, upper=100.0),
        uncertainty_m=ClosedInterval(lower=0.0, upper=5.0),
    )


def statistics_fixture():
    records = []
    assignments = []
    views = []
    for site, prefix in (("kee-cc", "k"), ("taoyuan-tc", "t")):
        sequence = f"{prefix}-video"
        assignments.append(
            PartitionAssignment(
                site=site,
                group_kind=SOURCE_GROUP,
                group_id=sequence,
                partition=PartitionKind.PILOT,
            )
        )
        for track in ("a", "b"):
            track_id = f"track-{track}"
            assignments.append(
                PartitionAssignment(
                    site=site,
                    group_kind=TRACK_GROUP,
                    group_id=track_id,
                    partition=PartitionKind.PILOT,
                )
            )
            for ordinal in (1, 2):
                value = tracked_record(
                    site,
                    f"{prefix}-{track}{ordinal}",
                    f"d-{track}{ordinal}",
                    track_id,
                    sequence,
                )
                records.append(value)
                views.append(
                    IndependentViewMembership(
                        site=site,
                        frame_id=value.frame_id,
                        detection_id=value.detection_id,
                        view_id=f"camera:{track}",
                        camera_id="camera",
                        scene_region_id=track,
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
        policies=tuple(policy(site) for site in ACCEPTANCE_SITES),
        partition_assignments=tuple(assignments),
        independent_views=tuple(views),
    )


def selected_path(seed_class):
    path = HypothesisPath(
        path_id=f"selected-{seed_class.value}",
        semantic_path=SemanticPath.NORMAL,
        correspondence=(
            Correspondence(
                observation_id="observation",
                template_semantic_id="wheel",
                candidate_label_provenance=("provider",),
            ),
        ),
        cue_subset=(CueFamily.WHEEL,),
        seed_class=seed_class,
        minimal_observations=("observation",),
        initialization_source=InitializationSource(
            method="direct_image_space", observation_ids=("observation",)
        ),
        terminal_state=HypothesisState.SELECTED,
    )
    return LocalizationDiagnostics(paths=(path,), selected_path=path.path_id)


def accepted(position, seed_class):
    return LocalizationResult(
        status=LocalizationStatus.ACCEPTED,
        usable=True,
        authoritative_position_sat_px=position,
        diagnostic_position_sat_px=None,
        heading_deg=0.0,
        decisive_gate="accepted",
        reason=None,
        diagnostics=selected_path(seed_class),
    )


def rejected():
    return LocalizationResult(
        status=LocalizationStatus.REJECTED,
        usable=False,
        authoritative_position_sat_px=None,
        diagnostic_position_sat_px=None,
        heading_deg=None,
        decisive_gate="insufficient_support",
        reason="insufficient_support",
    )


class PilotStatisticsTest(unittest.TestCase):
    def setUp(self):
        self.frozen = statistics_fixture()
        self.scope = mvp_scope()
        self.profiles = {site: acceptance_profile(site) for site in ACCEPTANCE_SITES}
        self.tokens = {
            site: validate_before_read(profile, self.scope)
            for site, profile in self.profiles.items()
        }

    def run_arms(self):
        pixels_per_metre = {
            site: profile.calibration.snapshot.pixels_per_metre
            for site, profile in self.profiles.items()
        }
        optimizer_offsets = {
            "a1": (1.0, SeedClass.WHEEL),
            "a2": (2.0, SeedClass.NON_WHEEL),
            "b1": (3.0, SeedClass.WHEEL),
        }

        def baseline(record):
            scale = pixels_per_metre[record.site]
            return {
                "status": "ok",
                "sat_coords": (14.0 * scale, 20.0 * scale),
                "heading": 0.0,
            }

        def optimizer(record, profile, configuration, _identity):
            suffix = record.frame_id.split("-")[-1]
            if suffix not in optimizer_offsets:
                return rejected()
            offset, seed_class = optimizer_offsets[suffix]
            scale = profile.calibration.snapshot.pixels_per_metre
            return accepted(((10.0 + offset) * scale, 20.0 * scale), seed_class)

        return run_frozen_pilot_arms(
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
            code_revision="statistics-test-revision",
            runtime_dependencies=(ContentIdentity("f" * 64),),
            baseline_localize=baseline,
            optimizer_localize=optimizer,
        )

    def test_metrics_intervals_provenance_and_thresholds_are_hand_computed(self):
        runs = self.run_arms()
        statistics = compute_pilot_statistics(
            frozen_evidence=self.frozen,
            frozen_runs=runs,
            profiles=self.profiles,
        )

        self.assertEqual(statistics.current_evidence_status.value, "insufficient_data")
        self.assertFalse(statistics.proven_improvement_claim_allowed)
        self.assertFalse(statistics.held_out_acceptance_claim_allowed)
        for site in ACCEPTANCE_SITES:
            report = statistics.for_site(site).for_arm(PilotArm.FULL_OPTIMIZER)
            self.assertEqual((report.accepted_count, report.rejected_count), (3, 1))
            self.assertEqual(report.unrounded_planar_errors_m, (1.0, 2.0, 3.0))
            self.assertEqual((report.median_error_m, report.p90_error_m), (2.0, 3.0))
            self.assertEqual(report.usable_coverage, 0.75)
            self.assertEqual(
                dict(report.signed_effects),
                {
                    "median_error_m": -2.0,
                    "p90_error_m": -1.0,
                    "usable_coverage": -0.25,
                },
            )
            intervals = dict(report.effect_intervals)
            self.assertEqual(
                (intervals["median_error_m"].lower, intervals["median_error_m"].upper),
                (-2.5, -1.0),
            )
            self.assertEqual(
                (intervals["p90_error_m"].lower, intervals["p90_error_m"].upper),
                (-2.0, -1.0),
            )
            self.assertEqual(
                (intervals["usable_coverage"].lower, intervals["usable_coverage"].upper),
                (-0.5, 0.0),
            )
            self.assertEqual(report.genuine_track_count, 2)
            self.assertEqual(
                report.selected_seed_provenance,
                report.selected_seed_provenance.__class__(
                    wheel=2, non_wheel=1, unavailable=1
                ),
            )
            coverage_by_view = {
                item.view_id: (
                    item.eligible_count,
                    item.accepted_count,
                    item.usable_coverage,
                )
                for item in report.independent_view_coverage
            }
            self.assertEqual(
                coverage_by_view,
                {
                    f"{site}:camera:a": (2, 2, 1.0),
                    f"{site}:camera:b": (2, 1, 0.5),
                },
            )
            self.assertEqual(report.ground_truth_uncertainty.values, (0.25,) * 4)
            self.assertEqual(
                (
                    report.candidate_thresholds.maximum_median_error_m,
                    report.candidate_thresholds.maximum_p90_error_m,
                    report.candidate_thresholds.minimum_usable_coverage,
                ),
                (3.0, 3.0, 0.5),
            )
            self.assertEqual(report.power_sufficiency.status.value, "insufficient_data")
            self.assertIn(
                "usable_coverage:no_observed_directional_effect",
                report.power_sufficiency.evidence_gaps,
            )

    def test_method_is_frozen_without_preclaimed_coverage_or_thresholds(self):
        method = freeze_pilot_statistics_method(
            frozen_evidence=self.frozen, profiles=self.profiles
        )
        runs = self.run_arms()
        self.assertEqual(runs.statistics_method, method)
        for site_method in method.sites:
            self.assertEqual(site_method.cluster_unit, "real_track")
            self.assertEqual(site_method.power_method, "cluster-bootstrap-v1")
            self.assertFalse(hasattr(site_method, "required_sample_count"))
            self.assertFalse(hasattr(site_method, "candidate_thresholds"))


if __name__ == "__main__":
    unittest.main()
