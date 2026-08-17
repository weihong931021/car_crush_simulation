"""Focused tests for direct image-space Haware hypothesis generation."""
from dataclasses import replace
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_haware_profile_validation import profile as base_profile, scope
from trafficlab.motion.haware_accuracy.models import (
    ContentIdentity,
    CueEvidenceProfile,
    CueFamily,
    CueHeightSpec,
    HypothesisState,
    ImageObservation,
    MinimalConfiguration,
    ObservationRecord,
    ProviderProvenance,
    SemanticPath,
    SemanticPathSpec,
    SeedClass,
    SourceProvenance,
    VehicleTemplate,
    VehicleTemplatePoint,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read
from trafficlab.motion.haware_hypotheses import (
    DirectImageHypothesisGenerator,
    DirectSeedProfile,
    SeedSearchCell,
)
from trafficlab.projection.haware_forward import (
    HawareForwardProjector,
    ProjectionBatch,
)


TRUE_POSE = (20.0, 30.0, 0.35)


def provenance(name: str) -> SourceProvenance:
    return SourceProvenance(
        source_id=name,
        repository_relative_path=None,
        source_content_identity=ContentIdentity.for_bytes(name.encode()),
    )


def template() -> VehicleTemplate:
    return VehicleTemplate(
        version="test-template-v1",
        points=(
            VehicleTemplatePoint(
                semantic_id="wheel_front_left",
                position_m=(-1.0, 0.2, -1.5),
                cue_family=CueFamily.WHEEL,
            ),
            VehicleTemplatePoint(
                semantic_id="wheel_rear_right",
                position_m=(1.0, -0.1, 1.5),
                cue_family=CueFamily.WHEEL,
            ),
            VehicleTemplatePoint(
                semantic_id="roof_front",
                position_m=(-0.6, 1.0, -1.0),
                cue_family=CueFamily.ROOF,
            ),
            VehicleTemplatePoint(
                semantic_id="roof_rear",
                position_m=(0.7, 2.0, 1.1),
                cue_family=CueFamily.ROOF,
            ),
        ),
    )


def configured_profile():
    value = base_profile()
    minimal = (
        MinimalConfiguration(
            configuration_id="roof-pair",
            cue_families=(CueFamily.ROOF,),
            minimum_support=2,
        ),
        MinimalConfiguration(
            configuration_id="wheel-pair",
            cue_families=(CueFamily.WHEEL,),
            minimum_support=2,
        ),
    )
    cue_evidence = replace(
        value.cue_evidence,
        semantic_mappings=(
            ("label-roof-front", "roof_front"),
            ("label-roof-rear", "roof_rear"),
            ("label-wheel-front-left", "wheel_front_left"),
            ("label-wheel-rear-right", "wheel_rear_right"),
        ),
        minimal_configurations=minimal,
    )
    semantic_paths = (
        SemanticPathSpec(semantic_path=SemanticPath.NORMAL),
        SemanticPathSpec(
            semantic_path=SemanticPath.REVERSED,
            front_rear_mapping=(
                ("roof_front", "roof_rear"),
                ("roof_rear", "roof_front"),
                ("wheel_front_left", "wheel_rear_right"),
                ("wheel_rear_right", "wheel_front_left"),
            ),
        ),
        SemanticPathSpec(semantic_path=SemanticPath.HEADING_PI),
    )
    optimizer = replace(
        value.optimizer,
        hypothesis_budget=6,
        minimal_configurations=minimal,
        semantic_paths=semantic_paths,
    )
    return replace(value, cue_evidence=cue_evidence, optimizer=optimizer)


def seed_profile() -> DirectSeedProfile:
    return DirectSeedProfile(
        search_cells=(SeedSearchCell(
            cell_id="cell-a",
            center_x_px=replace_interval(10.0, 30.0),
            center_y_px=replace_interval(20.0, 40.0),
            initial_center_sat_px=TRUE_POSE[:2],
        ),),
        heading_starts_rad=(TRUE_POSE[2],),
        max_evaluations=200,
        ftol=1e-10,
        xtol=1e-10,
        gtol=1e-10,
        finite_difference_step=1e-6,
        parameter_scale=(5.0, 5.0, 0.5),
    )


def replace_interval(lower: float, upper: float):
    from trafficlab.motion.haware_accuracy.models import ClosedInterval
    return ClosedInterval(lower=lower, upper=upper)


def record(value, vehicle_template: VehicleTemplate) -> ObservationRecord:
    pose = value.calibration.snapshot
    del pose
    points_by_id = {point.semantic_id: point for point in vehicle_template.points}
    semantic_labels = (
        ("wheel_front_left", "label-wheel-front-left"),
        ("wheel_rear_right", "label-wheel-rear-right"),
        ("roof_front", "label-roof-front"),
        ("roof_rear", "label-roof-rear"),
    )
    height_by_family = {
        spec.cue_family: 0.5 * (spec.height_m.lower + spec.height_m.upper)
        for spec in value.cue_evidence.height_specs
    }
    direct_points = np.asarray([
        (
            points_by_id[semantic_id].position_m[0],
            height_by_family[points_by_id[semantic_id].cue_family],
            points_by_id[semantic_id].position_m[2],
        )
        for semantic_id, _ in semantic_labels
    ])
    from trafficlab.motion.haware_accuracy.models import Pose2D
    pixels = HawareForwardProjector().predict_pixels(
        Pose2D(
            center_sat_px=TRUE_POSE[:2],
            heading_rad_unwrapped=TRUE_POSE[2],
        ),
        direct_points,
        value.calibration.snapshot,
    ).pixels
    observations = tuple(
        ImageObservation(
            observation_id=f"obs-{index}",
            pixel=(float(pixel[0]), float(pixel[1])),
            confidence=1.0,
            candidate_labels=(label, "unmapped-provider-label"),
            provider_key=f"provider-{index}",
        )
        for index, ((_, label), pixel) in enumerate(zip(semantic_labels, pixels))
    )
    return ObservationRecord(
        site="kee-cc",
        source_sequence="sequence-a",
        frame_id="frame-1",
        detection_id="detection-1",
        image_size_px=(1920, 1080),
        observations=observations,
        provider=ProviderProvenance(
            provider_name="fixture-provider",
            provider_version="1",
            adapter_version="1",
        ),
        source=provenance("fixture-record"),
    )


class RejectGroundProjector:
    """A projector whose ground equations fail without affecting elevated cues."""

    def __init__(self) -> None:
        self.delegate = HawareForwardProjector()

    def predict_pixels(self, pose, template_points, calibration, nuisance=None):
        points = np.asarray(template_points)
        if np.all(points[:, 1] == 0.0):
            return ProjectionBatch(
                pixels=np.zeros((len(points), 2)),
                valid=np.zeros(len(points), dtype=np.bool_),
                failure_reasons=tuple("synthetic_ground_failure" for _ in points),
            )
        return self.delegate.predict_pixels(
            pose, template_points, calibration, nuisance
        )


class RecordingProjector:
    def __init__(self) -> None:
        self.delegate = HawareForwardProjector()
        self.heights: list[tuple[float, ...]] = []

    def predict_pixels(self, pose, template_points, calibration, nuisance=None):
        self.heights.append(tuple(float(value) for value in np.asarray(template_points)[:, 1]))
        return self.delegate.predict_pixels(
            pose, template_points, calibration, nuisance
        )


class DirectImageHypothesisGeneratorTest(unittest.TestCase):
    def setUp(self):
        self.profile = configured_profile()
        self.scope = scope()
        self.token = validate_before_read(self.profile, self.scope)
        self.template = template()
        self.record = record(self.profile, self.template)

    def generate(self, projector=None):
        return DirectImageHypothesisGenerator(
            projector or HawareForwardProjector()
        ).generate(
            self.record,
            self.template,
            token=self.token,
            profile=self.profile,
            scope=self.scope,
            seed_profile=seed_profile(),
        )

    def test_wheel_attempts_precede_independently_generated_non_wheel_attempts(self):
        result = self.generate()
        path_by_id = {
            path.path_id: path for path in result.report.authorized_paths
        }
        ordered_classes = tuple(
            path_by_id[path_id].seed_class
            for path_id in result.report.stable_order
        )
        self.assertIn(SeedClass.WHEEL, ordered_classes)
        self.assertIn(SeedClass.NON_WHEEL, ordered_classes)
        first_non_wheel = ordered_classes.index(SeedClass.NON_WHEEL)
        self.assertTrue(all(
            seed_class is SeedClass.WHEEL
            for seed_class in ordered_classes[:first_non_wheel]
        ))
        self.assertTrue(all(
            seed_class is SeedClass.NON_WHEEL
            for seed_class in ordered_classes[first_non_wheel:]
        ))
        self.assertLessEqual(
            len(result.report.stable_order), self.profile.optimizer.hypothesis_budget
        )
        self.assertEqual(
            {
                (path.semantic_path, path.seed_class)
                for path in result.report.authorized_paths
            },
            {
                (semantic_path, seed_class)
                for semantic_path in SemanticPath
                for seed_class in SeedClass
            },
        )
        self.assertEqual(result.report.budget_exclusions, ())

    def test_semantic_paths_keep_candidate_provenance_and_explicit_pi_start(self):
        result = self.generate()
        paths = result.report.authorized_paths
        self.assertEqual(
            {path.semantic_path for path in paths},
            {SemanticPath.NORMAL, SemanticPath.REVERSED, SemanticPath.HEADING_PI},
        )
        for path in paths:
            for correspondence in path.correspondence:
                observation = next(
                    item for item in self.record.observations
                    if item.observation_id == correspondence.observation_id
                )
                self.assertEqual(
                    correspondence.candidate_label_provenance,
                    observation.candidate_labels,
                )
        normal = next(
            path for path in paths
            if path.semantic_path is SemanticPath.NORMAL
            and path.seed_class is SeedClass.WHEEL
        )
        reversed_path = next(
            path for path in paths
            if path.semantic_path is SemanticPath.REVERSED
            and path.seed_class is SeedClass.WHEEL
        )
        normal_mapping = {
            item.observation_id: item.template_semantic_id
            for item in normal.correspondence
        }
        reversed_mapping = {
            item.observation_id: item.template_semantic_id
            for item in reversed_path.correspondence
        }
        self.assertNotEqual(normal_mapping, reversed_mapping)
        for path in paths:
            if path.semantic_path is SemanticPath.HEADING_PI:
                self.assertAlmostEqual(
                    path.initialization_source.start_heading_rad,
                    TRUE_POSE[2] + math.pi,
                )

    def test_ground_height_is_exact_zero_and_seed_residuals_are_direct_pixels(self):
        recorder = RecordingProjector()
        result = self.generate(recorder)
        wheel_hypotheses = tuple(
            item for item in result.hypotheses
            if item.path.seed_class is SeedClass.WHEEL
        )
        self.assertTrue(wheel_hypotheses)
        for hypothesis in wheel_hypotheses:
            self.assertEqual(
                tuple(height for _, height in hypothesis.cue_heights_m),
                (0.0, 0.0),
            )
        self.assertTrue(any(all(height == 0.0 for height in call) for call in recorder.heights))
        normal = next(
            item for item in result.hypotheses
            if item.path.semantic_path is SemanticPath.NORMAL
            and item.path.seed_class is SeedClass.WHEEL
        )
        self.assertLess(normal.residual_rms_px, 1e-7)
        self.assertAlmostEqual(normal.seed.pose.center_sat_px[0], TRUE_POSE[0], places=7)
        self.assertAlmostEqual(normal.seed.pose.center_sat_px[1], TRUE_POSE[1], places=7)

    def test_non_wheel_generation_continues_when_all_wheel_equations_fail(self):
        result = self.generate(RejectGroundProjector())
        self.assertTrue(result.invalid_paths)
        self.assertTrue(all(
            path.seed_class is SeedClass.WHEEL for path in result.invalid_paths
        ))
        non_wheel = tuple(
            item for item in result.hypotheses
            if item.path.seed_class is SeedClass.NON_WHEEL
        )
        self.assertTrue(non_wheel)
        self.assertTrue(all(
            set(path.cue_subset) == {CueFamily.ROOF}
            for path in (item.path for item in non_wheel)
        ))

    def test_oversized_cross_product_has_one_accounted_terminal_per_combination(self):
        multi_template = replace(
            self.template,
            points=tuple(
                replace(point, cue_family=CueFamily.GLASS)
                if point.semantic_id == "roof_front"
                else point
                for point in self.template.points
            ),
        )
        minimal = (
            MinimalConfiguration(
                configuration_id="elevated-single",
                cue_families=(CueFamily.GLASS, CueFamily.ROOF),
                minimum_support=1,
            ),
            MinimalConfiguration(
                configuration_id="wheel-pair",
                cue_families=(CueFamily.WHEEL,),
                minimum_support=2,
            ),
        )
        multi_cues = replace(
            self.profile.cue_evidence,
            height_specs=(
                *self.profile.cue_evidence.height_specs,
                CueHeightSpec(
                    cue_family=CueFamily.GLASS,
                    height_m=replace_interval(0.8, 1.4),
                    evidence=provenance("glass-height"),
                ),
            ),
            minimal_configurations=minimal,
        )
        multi_profile = replace(
            self.profile,
            cue_evidence=multi_cues,
            optimizer=replace(
                self.profile.optimizer,
                hypothesis_budget=6,
                minimal_configurations=minimal,
            ),
        )
        multi_scope = scope()
        token = validate_before_read(multi_profile, multi_scope)
        multi_record = record(multi_profile, multi_template)

        def generate(value):
            return DirectImageHypothesisGenerator(HawareForwardProjector()).generate(
                value,
                multi_template,
                token=token,
                profile=multi_profile,
                scope=multi_scope,
                seed_profile=seed_profile(),
            )

        result = generate(multi_record)
        combinations = tuple(
            (path.semantic_path, path.cue_subset, path.seed_class)
            for path in result.report.authorized_paths
        )
        self.assertEqual(len(combinations), 9)
        self.assertEqual(len(set(combinations)), len(combinations))
        self.assertEqual(len(result.report.stable_order), 6)
        self.assertEqual(
            {
                (path.semantic_path, path.seed_class)
                for path in result.report.authorized_paths
                if path.terminal_state is not HypothesisState.BUDGET_EXCLUDED
            },
            {
                (semantic_path, seed_class)
                for semantic_path in SemanticPath
                for seed_class in SeedClass
            },
        )
        self.assertEqual(len(result.report.budget_exclusions), 3)
        self.assertTrue(all(
            path.terminal_state is HypothesisState.BUDGET_EXCLUDED
            and path.terminal_reason == "hypothesis_budget_exceeded"
            for path in result.report.budget_exclusions
        ))

        permuted = replace(
            multi_record, observations=tuple(reversed(multi_record.observations))
        )
        self.assertEqual(
            result.report.canonical_bytes(), generate(permuted).report.canonical_bytes()
        )

    def test_provider_confidence_does_not_promote_labels_to_truth(self):
        changed = tuple(
            replace(observation, confidence=0.25 if index == 0 else 1.0)
            for index, observation in enumerate(self.record.observations)
        )
        lower_confidence_record = replace(self.record, observations=changed)
        result = DirectImageHypothesisGenerator(HawareForwardProjector()).generate(
            lower_confidence_record,
            self.template,
            token=self.token,
            profile=self.profile,
            scope=self.scope,
            seed_profile=seed_profile(),
        )
        self.assertEqual(
            tuple(path.path_id for path in result.report.authorized_paths),
            tuple(path.path_id for path in self.generate().report.authorized_paths),
        )


if __name__ == "__main__":
    unittest.main()
