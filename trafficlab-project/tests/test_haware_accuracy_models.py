"""Focused tests for Haware immutable models and canonical serialization."""
from dataclasses import FrozenInstanceError
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trafficlab.motion.haware_accuracy.models import (  # noqa: E402
    CalibrationSnapshot,
    ClosedInterval,
    ContentIdentity,
    CueFamily,
    ImageObservation,
    LocalizationDiagnostics,
    LocalizationResult,
    LocalizationStatus,
    ModelValidationError,
    SourceProvenance,
    VehicleTemplate,
    VehicleTemplatePoint,
)


ZERO_IDENTITY = ContentIdentity("0" * 64)


def source() -> SourceProvenance:
    return SourceProvenance(
        source_id="fixture",
        repository_relative_path="location/kee-cc/calibration.json",
        source_content_identity=ZERO_IDENTITY,
    )


def observation(identity: str, labels=("wheel", "front")) -> ImageObservation:
    return ImageObservation(
        observation_id=identity,
        pixel=(10.0, 20.0),
        confidence=0.75,
        candidate_labels=labels,
        provider_key=f"apollo:{identity}",
    )


class CanonicalModelTest(unittest.TestCase):
    def test_models_are_frozen_and_copy_mutable_sequences(self):
        labels = ["wheel", "front"]
        value = observation("o1", labels)
        labels.append("roof")
        self.assertEqual(value.candidate_labels, ("front", "wheel"))
        with self.assertRaises(FrozenInstanceError):
            value.confidence = 0.5

    def test_set_like_values_are_canonical_but_template_order_is_semantic(self):
        left = observation("o1", ("wheel", "front", "wheel"))
        right = observation("o1", ("front", "wheel"))
        self.assertEqual(left, right)
        self.assertEqual(left.canonical_bytes(), right.canonical_bytes())

        points = (
            VehicleTemplatePoint(semantic_id="rear", position_m=(0.0, 0.0, 1.0), cue_family=CueFamily.WHEEL),
            VehicleTemplatePoint(semantic_id="front", position_m=(0.0, 0.0, -1.0), cue_family=CueFamily.WHEEL),
        )
        template = VehicleTemplate(version="apollo-24-v1", points=points)
        self.assertEqual(tuple(point.semantic_id for point in template.points), ("rear", "front"))

    def test_canonical_bytes_are_finite_compact_utf8_with_one_lf(self):
        payload = observation("觀測-1").canonical_bytes()
        self.assertTrue(payload.endswith(b"\n"))
        self.assertFalse(payload.endswith(b"\n\n"))
        decoded = json.loads(payload)
        self.assertEqual(decoded["observation_id"], "觀測-1")
        self.assertNotIn(b"NaN", payload)
        self.assertNotIn(b"Infinity", payload)

    def test_content_identity_is_stable_and_content_sensitive(self):
        first = observation("o1")
        equivalent = observation("o1", ("front", "wheel"))
        changed = observation("o2")
        self.assertEqual(first.content_identity, equivalent.content_identity)
        self.assertNotEqual(first.content_identity, changed.content_identity)
        self.assertEqual(first.content_identity.algorithm, "sha256")

    def test_closed_intervals_are_finite_closed_and_not_inverted(self):
        interval = ClosedInterval(lower=-1.0, upper=2.0)
        self.assertTrue(interval.contains(-1.0))
        self.assertTrue(interval.contains(2.0))
        self.assertFalse(interval.contains(-1.000001))
        self.assertFalse(interval.contains(2.000001))
        self.assertFalse(interval.contains(math.nan))

        with self.assertRaisesRegex(ModelValidationError, "lower bound exceeds upper bound"):
            ClosedInterval(lower=2.0, upper=1.0)
        for lower, upper in ((-math.inf, 1.0), (0.0, math.inf), (math.nan, 1.0)):
            with self.subTest(lower=lower, upper=upper), self.assertRaisesRegex(ModelValidationError, "finite"):
                ClosedInterval(lower=lower, upper=upper)

    def test_non_finite_values_are_rejected_at_any_model_depth(self):
        with self.assertRaisesRegex(ModelValidationError, "finite"):
            ImageObservation(
                observation_id="bad",
                pixel=(math.nan, 1.0),
                confidence=0.5,
                candidate_labels=("wheel",),
                provider_key="apollo:7",
            )

        with self.assertRaisesRegex(ModelValidationError, "finite"):
            CalibrationSnapshot(
                version="v1",
                camera_matrix=((1.0, 0.0, 0.0), (0.0, math.inf, 0.0), (0.0, 0.0, 1.0)),
                distortion=(),
                homography=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                inverse_homography=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                camera_sat_px=(0.0, 0.0),
                camera_height_m=10.0,
                pixels_per_metre=4.0,
                provenance=source(),
            )

    def test_legacy_source_path_must_be_repository_relative(self):
        with self.assertRaisesRegex(ModelValidationError, "repository-relative"):
            SourceProvenance(
                source_id="legacy",
                repository_relative_path="../pifpaf/input.json",
                source_content_identity=ZERO_IDENTITY,
            )


class LocalizationResultInvariantTest(unittest.TestCase):
    def test_accepted_result_has_only_authoritative_coordinate(self):
        result = LocalizationResult(
            status=LocalizationStatus.ACCEPTED,
            usable=True,
            authoritative_position_sat_px=(100.0, 200.0),
            diagnostic_position_sat_px=None,
            heading_deg=45.0,
            decisive_gate="accepted",
            reason=None,
        )
        self.assertEqual(result.authoritative_position_sat_px, (100.0, 200.0))
        self.assertIsNone(result.diagnostic_position_sat_px)

    def test_rejected_result_has_only_optional_diagnostic_coordinate(self):
        result = LocalizationResult(
            status=LocalizationStatus.REJECTED,
            usable=False,
            authoritative_position_sat_px=None,
            diagnostic_position_sat_px=(100.0, 200.0),
            heading_deg=45.0,
            decisive_gate="spread_rejected",
            reason="spread_rejected",
            diagnostics=LocalizationDiagnostics(gate_failures=("spread_rejected",)),
        )
        self.assertFalse(result.usable)
        self.assertIsNone(result.authoritative_position_sat_px)

    def test_inconsistent_coordinate_roles_are_rejected(self):
        invalid_cases = (
            dict(
                status=LocalizationStatus.ACCEPTED,
                usable=False,
                authoritative_position_sat_px=(1.0, 2.0),
                diagnostic_position_sat_px=None,
                heading_deg=0.0,
                decisive_gate="accepted",
                reason=None,
            ),
            dict(
                status=LocalizationStatus.ACCEPTED,
                usable=True,
                authoritative_position_sat_px=None,
                diagnostic_position_sat_px=None,
                heading_deg=0.0,
                decisive_gate="accepted",
                reason=None,
            ),
            dict(
                status=LocalizationStatus.ACCEPTED,
                usable=True,
                authoritative_position_sat_px=(1.0, 2.0),
                diagnostic_position_sat_px=None,
                heading_deg=None,
                decisive_gate="accepted",
                reason=None,
            ),
            dict(
                status=LocalizationStatus.ACCEPTED,
                usable=True,
                authoritative_position_sat_px=(1.0, 2.0),
                diagnostic_position_sat_px=(1.0, 2.0),
                heading_deg=0.0,
                decisive_gate="accepted",
                reason=None,
            ),
            dict(
                status=LocalizationStatus.REJECTED,
                usable=True,
                authoritative_position_sat_px=None,
                diagnostic_position_sat_px=None,
                heading_deg=None,
                decisive_gate="unobservable_pose",
                reason="unobservable_pose",
            ),
            dict(
                status=LocalizationStatus.REJECTED,
                usable=False,
                authoritative_position_sat_px=(1.0, 2.0),
                diagnostic_position_sat_px=None,
                heading_deg=None,
                decisive_gate="unobservable_pose",
                reason="unobservable_pose",
            ),
            dict(
                status=LocalizationStatus.REJECTED,
                usable=False,
                authoritative_position_sat_px=None,
                diagnostic_position_sat_px=None,
                heading_deg=None,
                decisive_gate="unobservable_pose",
                reason=None,
            ),
        )
        for values in invalid_cases:
            with self.subTest(values=values), self.assertRaises(ModelValidationError):
                LocalizationResult(**values)

    def test_non_finite_diagnostic_coordinate_is_rejected(self):
        with self.assertRaisesRegex(ModelValidationError, "finite"):
            LocalizationResult(
                status=LocalizationStatus.REJECTED,
                usable=False,
                authoritative_position_sat_px=None,
                diagnostic_position_sat_px=(math.inf, 2.0),
                heading_deg=None,
                decisive_gate="non_finite_optimization",
                reason="non_finite_optimization",
            )


if __name__ == "__main__":
    unittest.main()
