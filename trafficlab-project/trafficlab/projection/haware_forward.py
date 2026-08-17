"""Pure, vectorized CCTV forward projection for Haware localization.

The module snapshots mutable :class:`GProjection` state and never retains or
mutates the source engine. Invalid geometry is reported per point; invalid
calibration/request contracts fail deterministically before projection.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Optional, Protocol, Sequence

import cv2
import numpy as np
from numpy.typing import NDArray

from trafficlab.motion.haware_accuracy.models import (
    CalibrationProfile,
    CalibrationSnapshot,
    ClosedInterval,
    ContentIdentity,
    CueEvidenceProfile,
    CueFamily,
    NuisanceField,
    NuisanceProfile,
    NuisanceVector,
    Pose2D,
    SourceProvenance,
    canonical_bytes,
)
from trafficlab.motion.haware_accuracy.validation import SUPPORTED_DISTORTION_LENGTHS


FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
_DENOMINATOR_EPS = 1e-12
_INVERSE_TOLERANCE = 1e-8


class ForwardProjectionError(ValueError):
    """Deterministic request- or calibration-level projection failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _readonly_array(value: Any, dtype: Any) -> NDArray[Any]:
    result = np.array(value, dtype=dtype, copy=True)
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class ProjectionBatch:
    """Direct CCTV pixel predictions and point-aligned validity diagnostics."""

    pixels: FloatArray
    valid: BoolArray
    failure_reasons: tuple[Optional[str], ...]

    def __post_init__(self) -> None:
        pixels = _readonly_array(self.pixels, np.float64)
        valid = _readonly_array(self.valid, np.bool_)
        reasons = tuple(self.failure_reasons)
        if pixels.ndim != 2 or pixels.shape[1:] != (2,):
            raise ForwardProjectionError("invalid_projection_batch", "pixels must have shape (N,2)")
        if valid.shape != (pixels.shape[0],) or len(reasons) != pixels.shape[0]:
            raise ForwardProjectionError("invalid_projection_batch", "validity diagnostics must align with pixels")
        for index, is_valid in enumerate(valid):
            if is_valid and (reasons[index] is not None or not np.isfinite(pixels[index]).all()):
                raise ForwardProjectionError("invalid_projection_batch", "valid points require finite pixels and no failure")
            if not is_valid and not reasons[index]:
                raise ForwardProjectionError("invalid_projection_batch", "invalid points require a failure reason")
        object.__setattr__(self, "pixels", pixels)
        object.__setattr__(self, "valid", valid)
        object.__setattr__(self, "failure_reasons", reasons)


class ForwardProjector(Protocol):
    def predict_pixels(
        self,
        pose: Pose2D,
        template_points: NDArray[Any],
        calibration: CalibrationSnapshot,
        nuisance: Optional[NuisanceVector] = None,
    ) -> ProjectionBatch: ...


def _derived_provenance(projection: Any) -> SourceProvenance:
    config = getattr(projection, "config", {})
    identity = ContentIdentity.for_bytes(canonical_bytes(config))
    location = str(config.get("meta", {}).get("location_code", "unknown"))
    return SourceProvenance(
        source_id=f"g-projection:{location}",
        repository_relative_path=None,
        source_content_identity=identity,
    )


def calibration_snapshot_from_g_projection(
    projection: Any,
    *,
    version: Optional[str] = None,
    provenance: Optional[SourceProvenance] = None,
) -> CalibrationSnapshot:
    """Copy validated calibration values from a mutable ``GProjection``.

    No array is retained by reference. When explicit artifact provenance is
    unavailable, a deterministic identity is derived from the engine config.
    """
    config = getattr(projection, "config", {})
    meta = config.get("meta", {}) if isinstance(config, dict) else {}
    if version is None:
        location = str(meta.get("location_code", "unknown"))
        timestamp = str(meta.get("timestamp", "unversioned"))
        version = f"{location}:{timestamp}"
    try:
        camera = np.array(projection.K, dtype=np.float64, copy=True)
        distortion = np.array(projection.D, dtype=np.float64, copy=True).reshape(-1)
        homography = np.array(projection.H, dtype=np.float64, copy=True)
        inverse = np.array(projection.H_inv, dtype=np.float64, copy=True)
        camera_sat = np.array(projection.cam_sat, dtype=np.float64, copy=True).reshape(-1)
        camera_height = float(projection.z_cam)
        pixel_scale = float(projection.px_per_m)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ForwardProjectionError("invalid_g_projection", "required calibration values are absent or malformed") from exc

    _validate_calibration_arrays(
        camera, distortion, homography, inverse, camera_sat, camera_height, pixel_scale
    )
    return CalibrationSnapshot(
        version=version,
        camera_matrix=tuple(tuple(float(value) for value in row) for row in camera),
        distortion=tuple(float(value) for value in distortion),
        homography=tuple(tuple(float(value) for value in row) for row in homography),
        inverse_homography=tuple(tuple(float(value) for value in row) for row in inverse),
        camera_sat_px=(float(camera_sat[0]), float(camera_sat[1])),
        camera_height_m=camera_height,
        pixels_per_metre=pixel_scale,
        provenance=provenance or _derived_provenance(projection),
    )


def _validate_calibration_arrays(
    camera: FloatArray,
    distortion: FloatArray,
    homography: FloatArray,
    inverse: FloatArray,
    camera_sat: FloatArray,
    camera_height: float,
    pixel_scale: float,
) -> None:
    arrays = (camera, distortion, homography, inverse, camera_sat)
    if camera.shape != (3, 3) or homography.shape != (3, 3) or inverse.shape != (3, 3):
        raise ForwardProjectionError("invalid_calibration_shape", "K, H, and H_inv must be 3x3")
    if camera_sat.shape != (2,):
        raise ForwardProjectionError("invalid_calibration_shape", "camera satellite point must contain two values")
    if any(not np.isfinite(value).all() for value in arrays) or not np.isfinite((camera_height, pixel_scale)).all():
        raise ForwardProjectionError("non_finite_calibration", "all calibration values must be finite")

    if distortion.size not in SUPPORTED_DISTORTION_LENGTHS:
        raise ForwardProjectionError(
            "unsupported_distortion_layout", f"distortion length {distortion.size} is unsupported"
        )
    if camera[0, 0] <= 0.0 or camera[1, 1] <= 0.0:
        raise ForwardProjectionError("invalid_camera_matrix", "focal lengths must be positive")
    canonical_entries = (
        abs(camera[0, 1]), abs(camera[1, 0]), abs(camera[2, 0]),
        abs(camera[2, 1]), abs(camera[2, 2] - 1.0),
    )
    if max(canonical_entries) > _DENOMINATOR_EPS:
        raise ForwardProjectionError("unsupported_camera_matrix", "camera matrix must use zero skew and canonical scale")
    if camera_height <= 0.0 or pixel_scale <= 0.0:
        raise ForwardProjectionError("invalid_calibration_scale", "camera height and pixel scale must be positive")
    if abs(float(np.linalg.det(homography))) <= _DENOMINATOR_EPS or abs(float(np.linalg.det(inverse))) <= _DENOMINATOR_EPS:
        raise ForwardProjectionError("singular_homography", "H and H_inv must be nonsingular")
    identity = np.eye(3, dtype=np.float64)
    if not (
        np.allclose(homography @ inverse, identity, rtol=_INVERSE_TOLERANCE, atol=_INVERSE_TOLERANCE)
        and np.allclose(inverse @ homography, identity, rtol=_INVERSE_TOLERANCE, atol=_INVERSE_TOLERANCE)
    ):
        raise ForwardProjectionError("inconsistent_homography_inverse", "H_inv must invert H")


def _arrays_from_snapshot(snapshot: CalibrationSnapshot) -> tuple[FloatArray, ...]:
    camera = np.asarray(snapshot.camera_matrix, dtype=np.float64)
    distortion = np.asarray(snapshot.distortion, dtype=np.float64)
    homography = np.asarray(snapshot.homography, dtype=np.float64)
    inverse = np.asarray(snapshot.inverse_homography, dtype=np.float64)
    camera_sat = np.asarray(snapshot.camera_sat_px, dtype=np.float64)
    _validate_calibration_arrays(
        camera,
        distortion,
        homography,
        inverse,
        camera_sat,
        float(snapshot.camera_height_m),
        float(snapshot.pixels_per_metre),
    )
    return camera, distortion, homography, inverse, camera_sat


def _empty_batch(size: int) -> tuple[FloatArray, BoolArray, list[Optional[str]]]:
    return (
        np.zeros((size, 2), dtype=np.float64),
        np.ones(size, dtype=np.bool_),
        [None] * size,
    )


def _invalidate(valid: BoolArray, reasons: list[Optional[str]], mask: BoolArray, reason: str) -> None:
    selected = valid & mask
    for index in np.flatnonzero(selected):
        reasons[int(index)] = reason
    valid[selected] = False


def project_satellite_points(
    real_sat_points: NDArray[Any],
    heights_m: NDArray[Any],
    calibration: CalibrationSnapshot,
) -> ProjectionBatch:
    """Project real horizontal satellite positions directly to CCTV pixels."""
    real = np.asarray(real_sat_points, dtype=np.float64)
    heights = np.asarray(heights_m, dtype=np.float64)
    if real.ndim != 2 or real.shape[1:] != (2,):
        raise ForwardProjectionError("invalid_satellite_points_shape", "satellite points must have shape (N,2)")
    if heights.shape != (real.shape[0],):
        raise ForwardProjectionError("invalid_heights_shape", "heights must have shape (N,)")

    camera, distortion, _homography, inverse, camera_sat = _arrays_from_snapshot(calibration)
    pixels, valid, reasons = _empty_batch(real.shape[0])
    _invalidate(valid, reasons, ~np.isfinite(real).all(axis=1), "non_finite_satellite_point")
    _invalidate(valid, reasons, ~np.isfinite(heights), "non_finite_height")
    _invalidate(valid, reasons, heights < 0.0, "height_below_ground")
    _invalidate(valid, reasons, heights >= calibration.camera_height_m, "height_not_below_camera")

    parallax_denominator = calibration.camera_height_m - heights
    _invalidate(
        valid,
        reasons,
        np.abs(parallax_denominator) <= _DENOMINATOR_EPS,
        "parallax_denominator_near_zero",
    )
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        scale = calibration.camera_height_m / parallax_denominator
        apparent = camera_sat + (real - camera_sat) * scale[:, None]
    _invalidate(valid, reasons, ~np.isfinite(apparent).all(axis=1), "non_finite_parallax")

    homogeneous_input = np.column_stack((apparent, np.ones(real.shape[0], dtype=np.float64)))
    with np.errstate(over="ignore", invalid="ignore"):
        homogeneous = homogeneous_input @ inverse.T
    _invalidate(valid, reasons, ~np.isfinite(homogeneous).all(axis=1), "non_finite_homography")
    denominator = homogeneous[:, 2]
    _invalidate(
        valid,
        reasons,
        np.abs(denominator) <= _DENOMINATOR_EPS,
        "homography_denominator_near_zero",
    )

    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        undistorted = homogeneous[:, :2] / denominator[:, None]
    _invalidate(valid, reasons, ~np.isfinite(undistorted).all(axis=1), "non_finite_undistorted_pixel")

    fx, fy = camera[0, 0], camera[1, 1]
    cx, cy = camera[0, 2], camera[1, 2]
    normalized = np.column_stack(((undistorted[:, 0] - cx) / fx, (undistorted[:, 1] - cy) / fy))
    _invalidate(valid, reasons, ~np.isfinite(normalized).all(axis=1), "non_finite_distortion_input")

    if distortion.size >= 8:
        with np.errstate(over="ignore", invalid="ignore"):
            radius2 = np.sum(normalized * normalized, axis=1)
            radial_denominator = (
                1.0
                + distortion[5] * radius2
                + distortion[6] * radius2**2
                + distortion[7] * radius2**3
            )
        _invalidate(
            valid,
            reasons,
            ~np.isfinite(radial_denominator),
            "non_finite_distortion_denominator",
        )
        _invalidate(
            valid,
            reasons,
            np.abs(radial_denominator) <= _DENOMINATOR_EPS,
            "distortion_denominator_near_zero",
        )

    indices = np.flatnonzero(valid)
    if indices.size:
        object_points = np.column_stack(
            (normalized[indices], np.ones(indices.size, dtype=np.float64))
        ).reshape(-1, 1, 3)
        coefficients: Optional[FloatArray] = distortion if distortion.size else None
        try:
            distorted, _ = cv2.projectPoints(
                object_points,
                np.zeros(3, dtype=np.float64),
                np.zeros(3, dtype=np.float64),
                camera,
                coefficients,
            )
        except cv2.error as exc:
            raise ForwardProjectionError("distortion_projection_failed", "OpenCV rejected validated projection inputs") from exc
        projected = distorted.reshape(-1, 2)
        finite_output = np.isfinite(projected).all(axis=1)
        pixels[indices[finite_output]] = projected[finite_output]
        invalid_output = indices[~finite_output]
        if invalid_output.size:
            output_mask = np.zeros(real.shape[0], dtype=np.bool_)
            output_mask[invalid_output] = True
            _invalidate(valid, reasons, output_mask, "non_finite_distorted_pixel")

    return ProjectionBatch(pixels=pixels, valid=valid, failure_reasons=tuple(reasons))


@dataclass(frozen=True)
class ParameterSpec:
    """One frozen optimization coordinate in physical units."""

    name: str
    unit: str
    bounds: ClosedInterval
    scale: float
    role: str


@dataclass(frozen=True)
class DecodedFitParameters:
    """Fit-local physical state; calibration values are never publication output."""

    pose: Pose2D
    template_points: FloatArray
    local_calibration: CalibrationSnapshot
    published_nuisance: NuisanceVector

    def __post_init__(self) -> None:
        points = _readonly_array(self.template_points, np.float64)
        if points.ndim != 2 or points.shape[1:] != (3,):
            raise ForwardProjectionError("invalid_template_shape", "template points must have shape (N,3)")
        object.__setattr__(self, "template_points", points)

    @property
    def output_heading_deg(self) -> float:
        """Normalize heading only at the external result boundary."""
        return math.degrees(self.pose.heading_rad_unwrapped) % 360.0


_DIMENSION_FIELDS = {
    "length_m": "length",
    "vehicle_length": "length",
    "vehicle_length_m": "length",
    "width_m": "width",
    "vehicle_width": "width",
    "vehicle_width_m": "width",
    "wheelbase_m": "wheelbase",
    "vehicle_wheelbase_m": "wheelbase",
    "track_m": "track",
    "track_width_m": "track",
    "vehicle_track_m": "track",
}
_GROUND_FAMILIES = frozenset((CueFamily.GROUND_CONTACT, CueFamily.WHEEL))


def _height_family(name: str) -> Optional[CueFamily]:
    normalized = name.casefold()
    for family in CueFamily:
        aliases = {
            f"h_{family.value}",
            f"h_{family.value}_m",
            f"{family.value}_height",
            f"{family.value}_height_m",
            f"height_{family.value}_m",
        }
        if normalized in aliases:
            return family
    return None


def _calibration_kind(name: str) -> Optional[tuple[str, Optional[tuple[int, int]]]]:
    normalized = name.casefold()
    if normalized in {"delta_z_cam", "delta_z_cam_m", "delta_camera_height_m"}:
        return ("camera_height", None)
    if normalized in {"delta_c_x", "delta_c_x_m", "delta_camera_sat_x_m"}:
        return ("camera_x", None)
    if normalized in {"delta_c_y", "delta_c_y_m", "delta_camera_sat_y_m"}:
        return ("camera_y", None)
    if normalized.startswith("delta_h"):
        suffix = normalized[len("delta_h"):].replace("_", "")
        if len(suffix) == 2 and suffix.isdigit():
            row, column = int(suffix[0]), int(suffix[1])
            if 0 <= row <= 2 and 0 <= column <= 2:
                return ("homography", (row, column))
    return None


def _require_unit(field: NuisanceField, expected: frozenset[str]) -> None:
    if field.unit.casefold() not in expected:
        allowed = ", ".join(sorted(expected))
        raise ForwardProjectionError(
            "invalid_parameter_unit",
            f"{field.name} requires one of [{allowed}], got {field.unit!r}",
        )


def _set_span(
    points: FloatArray,
    mask: BoolArray,
    axis: int,
    target: float,
    field_name: str,
) -> None:
    values = points[mask, axis]
    if values.size < 2:
        raise ForwardProjectionError(
            "dimension_not_observable_in_template",
            f"{field_name} requires at least two applicable template points",
        )
    lower, upper = float(np.min(values)), float(np.max(values))
    span = upper - lower
    if span <= _DENOMINATOR_EPS:
        raise ForwardProjectionError(
            "dimension_not_observable_in_template",
            f"{field_name} cannot scale a zero-span template axis",
        )
    midpoint = 0.5 * (lower + upper)
    points[mask, axis] = midpoint + (values - midpoint) * (target / span)


class ScaledPoseNuisanceParameterization:
    """Frozen-order bounded codec for one local refinement.

    The first two coordinates are local metre offsets from ``seed_pose`` and
    the third is an unwrapped radian heading delta. Remaining coordinates are
    the nuisance profile's semantic order. Conversion of the local position to
    satellite pixels occurs only in :meth:`decode`.
    """

    def __init__(
        self,
        *,
        seed_pose: Pose2D,
        template_points: NDArray[Any],
        template_cue_families: Sequence[CueFamily],
        calibration_profile: CalibrationProfile,
        nuisance_profile: NuisanceProfile,
        cue_evidence: CueEvidenceProfile,
        position_delta_bounds_m: tuple[ClosedInterval, ClosedInterval],
        heading_delta_bounds_rad: ClosedInterval,
        pose_scales: tuple[float, float, float] = (1.0, 1.0, 1.0),
    ) -> None:
        points = np.asarray(template_points, dtype=np.float64)
        families = tuple(CueFamily(family) for family in template_cue_families)
        if points.ndim != 2 or points.shape[1:] != (3,):
            raise ForwardProjectionError("invalid_template_shape", "template points must have shape (N,3)")
        if len(families) != points.shape[0]:
            raise ForwardProjectionError("cue_family_count_mismatch", "one cue family is required per template point")
        if not np.isfinite(points).all():
            raise ForwardProjectionError("non_finite_template", "parameterized template points must be finite")
        if len(position_delta_bounds_m) != 2:
            raise ForwardProjectionError("invalid_pose_bounds", "x/y position bounds are required")
        if len(pose_scales) != 3 or any(not math.isfinite(value) or value <= 0.0 for value in pose_scales):
            raise ForwardProjectionError("invalid_parameter_scale", "pose scales must contain three finite positive values")

        self.seed_pose = seed_pose
        self._template_points = np.array(points, copy=True)
        self._template_points.setflags(write=False)
        self._families = families
        self.calibration_profile = calibration_profile
        self.nuisance_profile = nuisance_profile
        self.cue_evidence = cue_evidence

        pose_specs = (
            ParameterSpec("delta_center_x_m", "m", position_delta_bounds_m[0], pose_scales[0], "pose"),
            ParameterSpec("delta_center_y_m", "m", position_delta_bounds_m[1], pose_scales[1], "pose"),
            ParameterSpec("delta_heading_rad", "rad", heading_delta_bounds_rad, pose_scales[2], "pose"),
        )
        authorized = set(calibration_profile.authorized_nuisance_fields)
        nuisance_specs: list[ParameterSpec] = []
        classifications: dict[str, tuple[str, Any]] = {}
        height_fields: dict[CueFamily, NuisanceField] = {}

        for field in nuisance_profile.fields:
            calibration_kind = _calibration_kind(field.name)
            dimension_kind = _DIMENSION_FIELDS.get(field.name.casefold())
            family = _height_family(field.name)
            if field.name in authorized:
                if calibration_kind is None:
                    raise ForwardProjectionError(
                        "unsupported_calibration_nuisance",
                        f"authorized field {field.name!r} is not a supported fit-local calibration delta",
                    )
                if calibration_kind[0] == "homography":
                    _require_unit(field, frozenset(("1", "dimensionless")))
                    if calibration_kind[1] == (2, 2):
                        raise ForwardProjectionError("variable_homography_scale", "H[2,2] must remain fixed at 1")
                else:
                    _require_unit(field, frozenset(("m", "metre", "metres")))
                classifications[field.name] = ("calibration", calibration_kind)
            elif calibration_kind is not None:
                raise ForwardProjectionError(
                    "unauthorized_calibration_nuisance",
                    f"calibration delta {field.name!r} is absent from the calibration profile authorization",
                )
            elif dimension_kind is not None:
                _require_unit(field, frozenset(("m", "metre", "metres")))
                if field.bounds.lower <= 0.0:
                    raise ForwardProjectionError("invalid_dimension_bounds", f"{field.name} must remain positive")
                classifications[field.name] = ("dimension", dimension_kind)
            elif family is not None:
                _require_unit(field, frozenset(("m", "metre", "metres")))
                if family in _GROUND_FAMILIES:
                    raise ForwardProjectionError(
                        "ground_height_must_be_constant",
                        f"{field.name} attempts to parameterize a ground-contact height",
                    )
                if family in height_fields:
                    raise ForwardProjectionError("duplicate_cue_height_parameter", f"multiple fields parameterize {family.value}")
                height_fields[family] = field
                classifications[field.name] = ("height", family)
            else:
                raise ForwardProjectionError("unsupported_nuisance_field", f"unsupported nuisance field {field.name!r}")
            nuisance_specs.append(ParameterSpec(field.name, field.unit, field.bounds, field.scale, classifications[field.name][0]))

        evidence = {spec.cue_family: spec.height_m for spec in cue_evidence.height_specs}
        for family in set(families):
            interval = evidence.get(family)
            if interval is None:
                raise ForwardProjectionError("missing_cue_height_evidence", f"no height interval for {family.value}")
            if family in _GROUND_FAMILIES:
                if interval.lower != 0.0 or interval.upper != 0.0:
                    raise ForwardProjectionError("invalid_ground_contact_height", f"{family.value} must use [0,0]")
                continue
            field = height_fields.get(family)
            if interval.lower < interval.upper and field is None:
                raise ForwardProjectionError(
                    "missing_cue_height_parameter",
                    f"non-fixed {family.value} evidence requires a bounded height coordinate",
                )
            if field is not None and field.bounds != interval:
                raise ForwardProjectionError(
                    "cue_height_bounds_mismatch",
                    f"{field.name} bounds must equal the evidence interval for {family.value}",
                )

        self._classifications = classifications
        self._height_evidence = evidence
        self.parameter_specs = pose_specs + tuple(nuisance_specs)

    @property
    def lower_bounds(self) -> FloatArray:
        return np.asarray(tuple(spec.bounds.lower for spec in self.parameter_specs), dtype=np.float64)

    @property
    def upper_bounds(self) -> FloatArray:
        return np.asarray(tuple(spec.bounds.upper for spec in self.parameter_specs), dtype=np.float64)

    @property
    def x_scale(self) -> FloatArray:
        return np.asarray(tuple(spec.scale for spec in self.parameter_specs), dtype=np.float64)

    @property
    def initial_values(self) -> FloatArray:
        values = [0.0, 0.0, 0.0]
        for field in self.nuisance_profile.fields:
            if field.prior is not None:
                values.append(field.prior.mean)
            elif self._classifications[field.name][0] == "calibration" and field.bounds.contains(0.0):
                values.append(0.0)
            else:
                values.append(0.5 * (field.bounds.lower + field.bounds.upper))
        result = np.asarray(values, dtype=np.float64)
        if np.any(result < self.lower_bounds) or np.any(result > self.upper_bounds):
            raise ForwardProjectionError("initial_value_out_of_bounds", "zero local pose is outside frozen pose bounds")
        return result

    def decode_scaled(self, scaled_values: Sequence[float]) -> DecodedFitParameters:
        scaled = np.asarray(scaled_values, dtype=np.float64)
        if scaled.shape != (len(self.parameter_specs),):
            raise ForwardProjectionError("parameter_count_mismatch", "scaled vector does not match frozen parameter order")
        return self.decode(scaled * self.x_scale)

    def decode(self, values: Sequence[float]) -> DecodedFitParameters:
        vector = np.asarray(values, dtype=np.float64)
        if vector.shape != (len(self.parameter_specs),):
            raise ForwardProjectionError("parameter_count_mismatch", "vector does not match frozen parameter order")
        if not np.isfinite(vector).all():
            raise ForwardProjectionError("non_finite_parameter", "all fit parameters must be finite")
        below = vector < self.lower_bounds
        above = vector > self.upper_bounds
        if np.any(below | above):
            index = int(np.flatnonzero(below | above)[0])
            raise ForwardProjectionError("parameter_out_of_bounds", f"{self.parameter_specs[index].name} is outside its closed interval")

        snapshot = self.calibration_profile.snapshot
        center = (
            self.seed_pose.center_sat_px[0] + vector[0] * snapshot.pixels_per_metre,
            self.seed_pose.center_sat_px[1] + vector[1] * snapshot.pixels_per_metre,
        )
        pose = Pose2D(
            center_sat_px=center,
            heading_rad_unwrapped=self.seed_pose.heading_rad_unwrapped + vector[2],
        )
        points = np.array(self._template_points, copy=True)
        value_by_name = dict(zip((field.name for field in self.nuisance_profile.fields), vector[3:]))

        all_points = np.ones(points.shape[0], dtype=np.bool_)
        wheel_points = np.asarray(tuple(family is CueFamily.WHEEL for family in self._families), dtype=np.bool_)
        for field in self.nuisance_profile.fields:
            role, detail = self._classifications[field.name]
            value = float(value_by_name[field.name])
            if role != "dimension":
                continue
            if detail == "length":
                _set_span(points, all_points, 2, value, field.name)
            elif detail == "width":
                _set_span(points, all_points, 0, value, field.name)
            elif detail == "wheelbase":
                _set_span(points, wheel_points, 2, value, field.name)
            elif detail == "track":
                _set_span(points, wheel_points, 0, value, field.name)

        published: list[tuple[str, float]] = []
        camera_height = snapshot.camera_height_m
        camera_sat = list(snapshot.camera_sat_px)
        homography = np.asarray(snapshot.homography, dtype=np.float64).copy()
        for field in self.nuisance_profile.fields:
            role, detail = self._classifications[field.name]
            value = float(value_by_name[field.name])
            if role == "height":
                mask = np.asarray(tuple(family is detail for family in self._families), dtype=np.bool_)
                points[mask, 1] = value
                published.append((field.name, value))
            elif role == "dimension":
                published.append((field.name, value))
            elif detail[0] == "camera_height":
                camera_height += value
            elif detail[0] == "camera_x":
                camera_sat[0] += value * snapshot.pixels_per_metre
            elif detail[0] == "camera_y":
                camera_sat[1] += value * snapshot.pixels_per_metre
            elif detail[0] == "homography":
                row, column = detail[1]
                homography[row, column] += value

        for index, family in enumerate(self._families):
            interval = self._height_evidence[family]
            if family in _GROUND_FAMILIES:
                points[index, 1] = 0.0
            elif family not in self._height_evidence:
                raise AssertionError("cue evidence was validated during construction")
            elif interval.lower == interval.upper and family not in {
                detail for role, detail in self._classifications.values() if role == "height"
            }:
                points[index, 1] = interval.lower

        if abs(homography[2, 2] - 1.0) > _DENOMINATOR_EPS:
            raise ForwardProjectionError("variable_homography_scale", "fit-local H[2,2] changed")
        try:
            inverse = np.linalg.inv(homography)
        except np.linalg.LinAlgError as exc:
            raise ForwardProjectionError("singular_fit_local_homography", "calibration deltas made H singular") from exc
        local_calibration = replace(
            snapshot,
            camera_height_m=float(camera_height),
            camera_sat_px=(float(camera_sat[0]), float(camera_sat[1])),
            homography=tuple(tuple(float(item) for item in row) for row in homography),
            inverse_homography=tuple(tuple(float(item) for item in row) for row in inverse),
        )
        _arrays_from_snapshot(local_calibration)
        return DecodedFitParameters(
            pose=pose,
            template_points=points,
            local_calibration=local_calibration,
            published_nuisance=NuisanceVector(values=tuple(published)),
        )


class HawareForwardProjector:
    """Pure nominal and profile-bounded fit-local forward model."""

    def predict_parameterized(
        self,
        parameterization: ScaledPoseNuisanceParameterization,
        values: Sequence[float],
        *,
        scaled: bool = False,
    ) -> ProjectionBatch:
        decoded = (
            parameterization.decode_scaled(values)
            if scaled
            else parameterization.decode(values)
        )
        return self.predict_pixels(
            decoded.pose,
            decoded.template_points,
            decoded.local_calibration,
        )

    def predict_pixels(
        self,
        pose: Pose2D,
        template_points: NDArray[Any],
        calibration: CalibrationSnapshot,
        nuisance: Optional[NuisanceVector] = None,
    ) -> ProjectionBatch:
        if nuisance is not None and nuisance.values:
            raise ForwardProjectionError(
                "unbounded_nuisance_parameterization",
                "non-empty nuisance vectors require ScaledPoseNuisanceParameterization",
            )
        points = np.asarray(template_points, dtype=np.float64)
        if points.ndim != 2 or points.shape[1:] != (3,):
            raise ForwardProjectionError("invalid_template_shape", "template points must have shape (N,3)")

        heading = float(pose.heading_rad_unwrapped)
        forward = np.array((np.cos(heading), np.sin(heading)), dtype=np.float64)
        left = np.array((np.sin(heading), -np.cos(heading)), dtype=np.float64)
        center = np.asarray(pose.center_sat_px, dtype=np.float64)
        with np.errstate(over="ignore", invalid="ignore"):
            real_sat = center + calibration.pixels_per_metre * (
                points[:, 0, None] * left - points[:, 2, None] * forward
            )
        return project_satellite_points(real_sat, points[:, 1], calibration)


__all__ = [
    "DecodedFitParameters",
    "ForwardProjectionError",
    "ForwardProjector",
    "HawareForwardProjector",
    "ParameterSpec",
    "ProjectionBatch",
    "ScaledPoseNuisanceParameterization",
    "calibration_snapshot_from_g_projection",
    "project_satellite_points",
]
