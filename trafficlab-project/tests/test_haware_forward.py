"""Focused parity and numeric-failure tests for the pure Haware projector."""
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trafficlab.motion.haware_accuracy.models import (  # noqa: E402
    CalibrationProfile,
    CalibrationSnapshot,
    ClosedInterval,
    ContentIdentity,
    CueEvidenceProfile,
    CueFamily,
    CueHeightSpec,
    NuisanceField,
    NuisanceProfile,
    NuisanceVector,
    Pose2D,
    SourceProvenance,
)
from trafficlab.projection.g_projection import GProjection  # noqa: E402
from trafficlab.projection.haware_forward import (  # noqa: E402
    ForwardProjectionError,
    HawareForwardProjector,
    ScaledPoseNuisanceParameterization,
    project_satellite_points,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def source(path: Path) -> SourceProvenance:
    relative = path.relative_to(PROJECT_ROOT).as_posix()
    return SourceProvenance(
        source_id=relative,
        repository_relative_path=relative,
        source_content_identity=ContentIdentity.for_bytes(path.read_bytes()),
    )


def load_site(site: str) -> tuple[GProjection, CalibrationSnapshot]:
    path = PROJECT_ROOT / "location" / site / f"G_projection_{site}.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    engine = GProjection(config, base_dir=str(path.parent))
    snapshot = CalibrationSnapshot.from_g_projection(
        engine, version=f"{site}-fixture", provenance=source(path)
    )
    return engine, snapshot


def identity_snapshot(**changes) -> CalibrationSnapshot:
    value = CalibrationSnapshot(
        version="identity-v1",
        camera_matrix=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        distortion=(0.0, 0.0, 0.0, 0.0, 0.0),
        homography=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        inverse_homography=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        camera_sat_px=(0.0, 0.0),
        camera_height_m=10.0,
        pixels_per_metre=2.0,
        provenance=SourceProvenance(
            source_id="identity",
            repository_relative_path=None,
            source_content_identity=ContentIdentity("0" * 64),
        ),
    )
    return replace(value, **changes)


def bounded_parameterization(
    *,
    fields: tuple[NuisanceField, ...] | None = None,
    authorized: tuple[str, ...] = ("delta_z_cam", "delta_C_x", "delta_H_00"),
    roof_interval: ClosedInterval = ClosedInterval(lower=1.2, upper=1.8),
) -> ScaledPoseNuisanceParameterization:
    evidence = SourceProvenance(
        source_id="cue-evidence",
        repository_relative_path=None,
        source_content_identity=ContentIdentity("1" * 64),
    )
    if fields is None:
        fields = (
            NuisanceField(name="vehicle_length_m", unit="m", bounds=ClosedInterval(lower=4.0, upper=6.0), scale=0.5),
            NuisanceField(name="vehicle_width_m", unit="m", bounds=ClosedInterval(lower=2.0, upper=3.0), scale=0.25),
            NuisanceField(name="roof_height_m", unit="m", bounds=roof_interval, scale=0.2),
            NuisanceField(name="delta_z_cam", unit="m", bounds=ClosedInterval(lower=-0.5, upper=0.5), scale=0.1),
            NuisanceField(name="delta_C_x", unit="m", bounds=ClosedInterval(lower=-1.0, upper=1.0), scale=0.2),
            NuisanceField(name="delta_H_00", unit="dimensionless", bounds=ClosedInterval(lower=-0.1, upper=0.1), scale=0.05),
        )
    template = np.array(
        (
            (-1.0, 0.4, -1.5), (1.0, -0.2, -1.5),
            (-1.0, 0.1, 1.5), (1.0, 0.3, 1.5),
            (-0.5, 1.4, -1.0), (0.5, 1.4, 1.0),
        ),
        dtype=np.float64,
    )
    families = (CueFamily.WHEEL,) * 4 + (CueFamily.ROOF,) * 2
    return ScaledPoseNuisanceParameterization(
        seed_pose=Pose2D(center_sat_px=(20.0, 30.0), heading_rad_unwrapped=4.0 * math.pi + 0.25),
        template_points=template,
        template_cue_families=families,
        calibration_profile=CalibrationProfile(
            version="calibration-profile-v1",
            snapshot=identity_snapshot(),
            authorized_nuisance_fields=authorized,
        ),
        nuisance_profile=NuisanceProfile(version="nuisance-v1", fields=fields),
        cue_evidence=CueEvidenceProfile(
            version="cue-v1",
            site="kee-cc",
            view="test-view",
            semantic_mappings=(),
            height_specs=(
                CueHeightSpec(cue_family=CueFamily.WHEEL, height_m=ClosedInterval(lower=0.0, upper=0.0), evidence=evidence),
                CueHeightSpec(cue_family=CueFamily.ROOF, height_m=roof_interval, evidence=evidence),
            ),
            minimal_configurations=(),
            provenance=(evidence,),
        ),
        position_delta_bounds_m=(
            ClosedInterval(lower=-2.0, upper=2.0),
            ClosedInterval(lower=-3.0, upper=3.0),
        ),
        heading_delta_bounds_rad=ClosedInterval(lower=-6.0 * math.pi, upper=6.0 * math.pi),
        pose_scales=(0.5, 0.75, 0.1),
    )


class CalibrationSnapshotTest(unittest.TestCase):
    def test_factory_copies_every_mutable_g_projection_value(self):
        engine, snapshot = load_site("kee-cc")
        expected = (
            snapshot.camera_matrix,
            snapshot.distortion,
            snapshot.homography,
            snapshot.inverse_homography,
            snapshot.camera_sat_px,
            snapshot.camera_height_m,
            snapshot.pixels_per_metre,
        )
        engine.K[:] = -1.0
        engine.D[:] = 99.0
        engine.H[:] = 0.0
        engine.H_inv[:] = 0.0
        engine.cam_sat[:] = -50.0
        engine.z_cam = -1.0
        engine.px_per_m = -1.0
        self.assertEqual(
            expected,
            (
                snapshot.camera_matrix,
                snapshot.distortion,
                snapshot.homography,
                snapshot.inverse_homography,
                snapshot.camera_sat_px,
                snapshot.camera_height_m,
                snapshot.pixels_per_metre,
            ),
        )

    def test_factory_rejects_singular_or_inconsistent_homography(self):
        engine, _ = load_site("kee-cc")
        engine.H[:] = 0.0
        with self.assertRaisesRegex(ForwardProjectionError, "singular_homography"):
            CalibrationSnapshot.from_g_projection(engine)


class NominalParityTest(unittest.TestCase):
    def test_actual_site_ground_and_elevated_points_match_g_projection(self):
        cases = {
            "kee-cc": np.array(((1054.0, 932.0), (1155.0, 962.0), (1218.0, 659.0))),
            "taoyuan-tc": np.array(((320.0, 747.0), (473.0, 309.0), (673.0, 749.0))),
        }
        heights = np.array((0.0, 1.25, 2.0), dtype=np.float64)
        for site, points in cases.items():
            with self.subTest(site=site):
                engine, snapshot = load_site(site)
                batch = project_satellite_points(points, heights, snapshot)
                expected = np.array(
                    [engine.sat_to_cctv(x, y, h=float(h)) for (x, y), h in zip(points, heights)]
                )
                self.assertTrue(batch.valid.all(), batch.failure_reasons)
                np.testing.assert_allclose(batch.pixels, expected, rtol=1e-12, atol=1e-9)

    def test_pose_template_projection_preserves_direct_pixel_semantics(self):
        engine, snapshot = load_site("kee-cc")
        pose = Pose2D(center_sat_px=(1100.0, 850.0), heading_rad_unwrapped=math.radians(37.0))
        template = np.array(
            ((0.0, 0.0, 0.0), (0.8, 0.0, 1.4), (-0.7, 1.5, -1.2)),
            dtype=np.float64,
        )
        batch = HawareForwardProjector().predict_pixels(pose, template, snapshot)
        forward = np.array((math.cos(pose.heading_rad_unwrapped), math.sin(pose.heading_rad_unwrapped)))
        left = np.array((math.sin(pose.heading_rad_unwrapped), -math.cos(pose.heading_rad_unwrapped)))
        real = np.asarray(pose.center_sat_px) + snapshot.pixels_per_metre * (
            template[:, 0, None] * left - template[:, 2, None] * forward
        )
        expected = np.array(
            [engine.sat_to_cctv(x, y, h=float(h)) for (x, y), h in zip(real, template[:, 1])]
        )
        self.assertTrue(batch.valid.all(), batch.failure_reasons)
        np.testing.assert_allclose(batch.pixels, expected, rtol=1e-12, atol=1e-9)

    def test_body_axes_and_handedness_for_east_north_and_arbitrary_headings(self):
        snapshot = identity_snapshot()
        template = np.array(((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))  # left, rear
        projector = HawareForwardProjector()
        for heading in (0.0, math.pi / 2.0, math.radians(217.0)):
            pose = Pose2D(center_sat_px=(20.0, 20.0), heading_rad_unwrapped=heading)
            batch = projector.predict_pixels(pose, template, snapshot)
            vectors = batch.pixels - np.asarray(pose.center_sat_px)
            self.assertTrue(batch.valid.all())
            self.assertAlmostEqual(float(np.linalg.det(vectors.T)), -4.0, places=12)


class ExplicitFailureTest(unittest.TestCase):
    def test_point_failures_are_aligned_finite_and_deterministic(self):
        snapshot = identity_snapshot()
        real = np.array(((1.0, 2.0), (math.inf, 0.0), (2.0, 3.0), (3.0, 4.0)))
        heights = np.array((0.0, 0.0, snapshot.camera_height_m, -0.1))
        first = project_satellite_points(real, heights, snapshot)
        second = project_satellite_points(real, heights, snapshot)
        self.assertEqual(first.failure_reasons, second.failure_reasons)
        self.assertEqual(
            first.failure_reasons,
            (None, "non_finite_satellite_point", "height_not_below_camera", "height_below_ground"),
        )
        self.assertEqual(first.valid.tolist(), [True, False, False, False])
        self.assertTrue(np.isfinite(first.pixels).all())
        with self.assertRaises(ValueError):
            first.pixels[0, 0] = 9.0

    def test_near_zero_parallax_and_homography_denominators_are_explicit(self):
        snapshot = identity_snapshot()
        near_height = snapshot.camera_height_m - 0.5e-12
        parallax = project_satellite_points(np.array(((1.0, 0.0),)), np.array((near_height,)), snapshot)
        self.assertEqual(parallax.failure_reasons, ("parallax_denominator_near_zero",))

        homography = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 1.0))
        inverse = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 1.0))
        denominator_snapshot = identity_snapshot(
            homography=homography, inverse_homography=inverse
        )
        projected = project_satellite_points(
            np.array(((1.0, 0.0),)), np.array((0.0,)), denominator_snapshot
        )
        self.assertEqual(projected.failure_reasons, ("homography_denominator_near_zero",))

    def test_rational_distortion_denominator_and_layout_fail_explicitly(self):
        rational = identity_snapshot(
            distortion=(0.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0)
        )
        batch = project_satellite_points(np.array(((1.0, 0.0),)), np.array((0.0,)), rational)
        self.assertEqual(batch.failure_reasons, ("distortion_denominator_near_zero",))

        unsupported = identity_snapshot(distortion=(0.0, 0.0, 0.0))
        with self.assertRaisesRegex(ForwardProjectionError, "unsupported_distortion_layout"):
            project_satellite_points(np.array(((0.0, 0.0),)), np.array((0.0,)), unsupported)

    def test_raw_nonempty_nuisance_requires_profile_backed_parameterization(self):
        with self.assertRaisesRegex(ForwardProjectionError, "unbounded_nuisance_parameterization"):
            HawareForwardProjector().predict_pixels(
                Pose2D(center_sat_px=(0.0, 0.0), heading_rad_unwrapped=0.0),
                np.array(((0.0, 0.0, 0.0),)),
                identity_snapshot(),
                NuisanceVector(values=(("delta_z_cam", 0.0),)),
            )


class Task33ForwardProjectionCoverageTest(unittest.TestCase):
    """Task 3.3 coverage.

    Validates: Requirements 1.6-1.8, 3.1-3.6, 4.1-4.8.
    """

    def test_distorted_site_fixture_parity_is_pointwise_for_zero_and_nonzero_heights(self):
        fixture_points = {
            "kee-cc": ((1054.0, 932.0), (1155.0, 962.0), (1218.0, 659.0)),
            "taoyuan-tc": ((320.0, 747.0), (473.0, 309.0), (673.0, 749.0)),
        }
        heights = (0.0, 1.25, 2.0)
        for site, point_values in fixture_points.items():
            engine, snapshot = load_site(site)
            self.assertTrue(np.any(np.asarray(snapshot.distortion) != 0.0))
            points = np.asarray(point_values, dtype=np.float64)
            batch = project_satellite_points(points, np.asarray(heights), snapshot)
            self.assertTrue(batch.valid.all(), batch.failure_reasons)
            for index, ((x, y), height) in enumerate(zip(points, heights)):
                with self.subTest(site=site, point=index, height=height):
                    expected = engine.sat_to_cctv(float(x), float(y), h=height)
                    np.testing.assert_allclose(
                        batch.pixels[index], expected, rtol=1e-12, atol=1e-9
                    )

    def test_pose_projection_matches_g_projection_for_east_north_and_arbitrary_headings(self):
        headings = (("east", 0.0), ("north", math.pi / 2.0), ("arbitrary", math.radians(217.0)))
        template = np.asarray(
            ((-0.8, 0.0, -1.4), (0.8, 1.2, 0.0), (0.0, 2.0, 1.4)),
            dtype=np.float64,
        )
        projector = HawareForwardProjector()
        for site in ("kee-cc", "taoyuan-tc"):
            engine, snapshot = load_site(site)
            pose_center = np.asarray(snapshot.camera_sat_px) + np.asarray((-100.0, -200.0))
            for heading_name, heading in headings:
                with self.subTest(site=site, heading=heading_name):
                    pose = Pose2D(
                        center_sat_px=(float(pose_center[0]), float(pose_center[1])),
                        heading_rad_unwrapped=heading,
                    )
                    batch = projector.predict_pixels(pose, template, snapshot)
                    forward = np.asarray((math.cos(heading), math.sin(heading)))
                    left = np.asarray((math.sin(heading), -math.cos(heading)))
                    real_points = pose_center + snapshot.pixels_per_metre * (
                        template[:, 0, None] * left - template[:, 2, None] * forward
                    )
                    self.assertTrue(batch.valid.all(), batch.failure_reasons)
                    for index, ((x, y), height) in enumerate(
                        zip(real_points, template[:, 1])
                    ):
                        expected = engine.sat_to_cctv(float(x), float(y), h=float(height))
                        np.testing.assert_allclose(
                            batch.pixels[index], expected, rtol=1e-12, atol=1e-9
                        )

    def test_invalid_homographies_and_unsupported_distortion_layouts_fail(self):
        point = np.asarray(((0.0, 0.0),), dtype=np.float64)
        height = np.asarray((0.0,), dtype=np.float64)
        singular = identity_snapshot(
            homography=((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        )
        with self.assertRaisesRegex(ForwardProjectionError, "singular_homography"):
            project_satellite_points(point, height, singular)

        inconsistent = identity_snapshot(
            inverse_homography=((1.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        )
        with self.assertRaisesRegex(ForwardProjectionError, "inconsistent_homography_inverse"):
            project_satellite_points(point, height, inconsistent)

        for coefficient_count in (1, 3, 6, 13):
            with self.subTest(coefficient_count=coefficient_count):
                unsupported = identity_snapshot(distortion=(0.0,) * coefficient_count)
                with self.assertRaisesRegex(
                    ForwardProjectionError, "unsupported_distortion_layout"
                ):
                    project_satellite_points(point, height, unsupported)

    def test_exact_height_and_parameter_endpoints_are_closed(self):
        snapshot = identity_snapshot()
        heights = project_satellite_points(
            np.asarray(((1.0, 2.0), (1.0, 2.0))),
            np.asarray((0.0, snapshot.camera_height_m)),
            snapshot,
        )
        self.assertEqual(heights.valid.tolist(), [True, False])
        self.assertEqual(heights.failure_reasons, (None, "height_not_below_camera"))

        parameterization = bounded_parameterization()
        initial = parameterization.initial_values
        for index, spec in enumerate(parameterization.parameter_specs):
            for endpoint_name, endpoint in (
                ("lower", spec.bounds.lower),
                ("upper", spec.bounds.upper),
            ):
                with self.subTest(parameter=spec.name, endpoint=endpoint_name):
                    values = initial.copy()
                    values[index] = endpoint
                    decoded = parameterization.decode(values)
                    self.assertTrue(math.isfinite(decoded.pose.heading_rad_unwrapped))
                    self.assertTrue(np.isfinite(decoded.template_points).all())
                    self.assertTrue(
                        HawareForwardProjector()
                        .predict_parameterized(parameterization, values)
                        .valid.all()
                    )


class ScaledPoseNuisanceParameterizationTest(unittest.TestCase):
    def test_frozen_order_units_scales_and_scaled_decode(self):
        parameterization = bounded_parameterization()
        self.assertEqual(
            tuple(spec.name for spec in parameterization.parameter_specs),
            (
                "delta_center_x_m", "delta_center_y_m", "delta_heading_rad",
                "vehicle_length_m", "vehicle_width_m", "roof_height_m",
                "delta_z_cam", "delta_C_x", "delta_H_00",
            ),
        )
        self.assertEqual(
            tuple(spec.unit for spec in parameterization.parameter_specs[:3]),
            ("m", "m", "rad"),
        )
        np.testing.assert_allclose(
            parameterization.x_scale,
            (0.5, 0.75, 0.1, 0.5, 0.25, 0.2, 0.1, 0.2, 0.05),
        )
        physical = parameterization.initial_values
        scaled = physical / parameterization.x_scale
        decoded_physical = parameterization.decode(physical)
        decoded_scaled = parameterization.decode_scaled(scaled)
        self.assertEqual(decoded_physical.pose, decoded_scaled.pose)
        np.testing.assert_array_equal(decoded_physical.template_points, decoded_scaled.template_points)
        self.assertEqual(decoded_physical.local_calibration, decoded_scaled.local_calibration)

    def test_closed_endpoints_apply_metres_heights_dimensions_and_local_calibration(self):
        parameterization = bounded_parameterization()
        original = parameterization.calibration_profile.snapshot
        for values in (parameterization.lower_bounds, parameterization.upper_bounds):
            with self.subTest(endpoint=values.tolist()):
                decoded = parameterization.decode(values)
                expected_center = (
                    original.camera_sat_px[0] + 0.0,  # documents calibration independence
                    original.camera_sat_px[1] + 0.0,
                )
                del expected_center
                self.assertEqual(
                    decoded.pose.center_sat_px,
                    (
                        20.0 + values[0] * original.pixels_per_metre,
                        30.0 + values[1] * original.pixels_per_metre,
                    ),
                )
                self.assertEqual(
                    decoded.pose.heading_rad_unwrapped,
                    4.0 * math.pi + 0.25 + values[2],
                )
                self.assertGreaterEqual(decoded.output_heading_deg, 0.0)
                self.assertLess(decoded.output_heading_deg, 360.0)
                self.assertAlmostEqual(float(np.ptp(decoded.template_points[:, 2])), values[3])
                self.assertAlmostEqual(float(np.ptp(decoded.template_points[:, 0])), values[4])
                np.testing.assert_array_equal(decoded.template_points[:4, 1], np.zeros(4))
                np.testing.assert_array_equal(decoded.template_points[4:, 1], np.full(2, values[5]))
                self.assertAlmostEqual(decoded.local_calibration.camera_height_m, original.camera_height_m + values[6])
                self.assertAlmostEqual(decoded.local_calibration.camera_sat_px[0], original.camera_sat_px[0] + values[7] * original.pixels_per_metre)
                self.assertAlmostEqual(decoded.local_calibration.homography[0][0], 1.0 + values[8])
                self.assertEqual(
                    tuple(name for name, _ in decoded.published_nuisance.values),
                    ("roof_height_m", "vehicle_length_m", "vehicle_width_m"),
                )
                batch = HawareForwardProjector().predict_parameterized(parameterization, values)
                self.assertTrue(batch.valid.all(), batch.failure_reasons)
        self.assertEqual(parameterization.calibration_profile.snapshot, original)

    def test_heading_stays_unwrapped_until_output(self):
        parameterization = bounded_parameterization()
        values = parameterization.initial_values.copy()
        values[2] = 5.0 * math.pi
        decoded = parameterization.decode(values)
        self.assertGreater(decoded.pose.heading_rad_unwrapped, 8.0 * math.pi)
        self.assertAlmostEqual(
            decoded.output_heading_deg,
            math.degrees(decoded.pose.heading_rad_unwrapped) % 360.0,
        )

    def test_bounds_count_and_numeric_failures_are_explicit(self):
        parameterization = bounded_parameterization()
        outside = parameterization.initial_values.copy()
        outside[0] = parameterization.upper_bounds[0] + 1e-12
        cases = (
            (outside, "parameter_out_of_bounds"),
            (np.append(parameterization.initial_values, 0.0), "parameter_count_mismatch"),
            (np.full(len(parameterization.parameter_specs), math.nan), "non_finite_parameter"),
        )
        for values, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ForwardProjectionError, reason):
                parameterization.decode(values)

    def test_rejects_unauthorized_calibration_ground_height_and_bad_dimension(self):
        with self.assertRaisesRegex(ForwardProjectionError, "unauthorized_calibration_nuisance"):
            bounded_parameterization(authorized=("delta_z_cam", "delta_H_00"))

        standard = bounded_parameterization().nuisance_profile.fields
        ground_field = NuisanceField(
            name="wheel_height_m", unit="m",
            bounds=ClosedInterval(lower=0.0, upper=0.1), scale=0.1,
        )
        with self.assertRaisesRegex(ForwardProjectionError, "ground_height_must_be_constant"):
            bounded_parameterization(fields=standard + (ground_field,))

        invalid_dimension = replace(
            standard[0], bounds=ClosedInterval(lower=0.0, upper=6.0)
        )
        with self.assertRaisesRegex(ForwardProjectionError, "invalid_dimension_bounds"):
            bounded_parameterization(fields=(invalid_dimension,) + standard[1:])

    def test_nonfixed_non_ground_height_requires_exact_evidence_bounds(self):
        fields = tuple(
            field for field in bounded_parameterization().nuisance_profile.fields
            if field.name != "roof_height_m"
        )
        with self.assertRaisesRegex(ForwardProjectionError, "missing_cue_height_parameter"):
            bounded_parameterization(fields=fields)

        mismatched = tuple(
            replace(field, bounds=ClosedInterval(lower=1.0, upper=1.8))
            if field.name == "roof_height_m" else field
            for field in bounded_parameterization().nuisance_profile.fields
        )
        with self.assertRaisesRegex(ForwardProjectionError, "cue_height_bounds_mismatch"):
            bounded_parameterization(fields=mismatched)


if __name__ == "__main__":
    unittest.main()
