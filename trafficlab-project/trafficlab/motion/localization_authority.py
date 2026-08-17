"""Atomic coordinate-authority validation and compatibility mapping.

This boundary is intentionally separate from frozen baseline dispatch.  It is
for new optimizer results and explicitly policy-governed legacy normalization;
it never gives an optimizer fit authority merely because coordinates exist.
"""
from __future__ import annotations

import copy
import math
from collections import Counter
from collections.abc import Iterable, Mapping, MutableSequence
from typing import Any, Optional

from trafficlab.motion.haware_accuracy.models import (
    LegacyStatusPolicy,
    LocalizationDiagnostics,
    LocalizationResult,
    LocalizationStatus,
)


INCONSISTENT_COORDINATE_STATE = "inconsistent_coordinate_state"
LEGACY_STATUS_EVIDENCE_INSUFFICIENT = "legacy_status_evidence_insufficient"


LEGACY_LOCALIZE_V1 = LegacyStatusPolicy(
    version="legacy-localize-v1",
    accepted_statuses=("ok",),
    rejected_statuses=(
        "ambiguous_heading",
        "extrapolated",
        "failed_insufficient_kp",
        "pre_gate_near_horizon",
    ),
    unknown_status_reason=LEGACY_STATUS_EVIDENCE_INSUFFICIENT,
    rejection_reasons=(
        ("ambiguous_heading", LEGACY_STATUS_EVIDENCE_INSUFFICIENT),
        ("extrapolated", "spread_rejected"),
        ("failed_insufficient_kp", LEGACY_STATUS_EVIDENCE_INSUFFICIENT),
        ("pre_gate_near_horizon", "pre_gate_near_horizon"),
    ),
    null_diagnostic_statuses=("pre_gate_near_horizon",),
)


class LocalizationAuthorityError(ValueError):
    """A localization record failed the frozen authority contract."""

    def __init__(self, reason: str = INCONSISTENT_COORDINATE_STATE) -> None:
        self.reason = reason
        super().__init__(reason)


def _finite_scalar(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _finite_position(value: Any) -> bool:
    return (
        isinstance(value, (tuple, list))
        and len(value) == 2
        and all(_finite_scalar(item) for item in value)
    )


def _position_or_none(value: Any) -> Optional[tuple[float, float]]:
    if not _finite_position(value):
        return None
    return (float(value[0]), float(value[1]))


def _text_or_default(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value.strip() else default


class LocalizationAuthority:
    """Validate and map localization records without mutating caller output."""

    def validate_new(self, result: LocalizationResult) -> LocalizationResult:
        """Return a coherent new result or raise the frozen inconsistency reason."""
        try:
            accepted = result.status is LocalizationStatus.ACCEPTED
            rejected = result.status is LocalizationStatus.REJECTED
            common_valid = (
                type(result.usable) is bool
                and isinstance(result.decisive_gate, str)
                and bool(result.decisive_gate.strip())
            )
            if not common_valid or not (accepted or rejected):
                raise LocalizationAuthorityError()

            if accepted:
                coherent = (
                    result.usable
                    and _finite_position(result.authoritative_position_sat_px)
                    and result.diagnostic_position_sat_px is None
                    and (result.heading_deg is None or _finite_scalar(result.heading_deg))
                    and result.reason is None
                )
            else:
                coherent = (
                    not result.usable
                    and result.authoritative_position_sat_px is None
                    and (
                        result.diagnostic_position_sat_px is None
                        or _finite_position(result.diagnostic_position_sat_px)
                    )
                    and (
                        result.heading_deg is None
                        or _finite_scalar(result.heading_deg)
                    )
                    and isinstance(result.reason, str)
                    and bool(result.reason.strip())
                )
            if not coherent:
                raise LocalizationAuthorityError()
        except LocalizationAuthorityError:
            raise
        except (AttributeError, TypeError, ValueError, OverflowError) as error:
            raise LocalizationAuthorityError() from error
        return result

    def normalize_legacy(
        self,
        record: Mapping[str, Any],
        policy: LegacyStatusPolicy,
    ) -> LocalizationResult:
        """Normalize legacy ``sat_coords`` only through an explicit policy."""
        if not isinstance(record, Mapping) or not isinstance(policy, LegacyStatusPolicy):
            raise TypeError("legacy normalization requires a mapping and LegacyStatusPolicy")

        overlap = set(policy.accepted_statuses).intersection(policy.rejected_statuses)
        if overlap:
            raise LocalizationAuthorityError()

        legacy_status = record.get("status")
        position = _position_or_none(record.get("sat_coords"))
        heading_value = record.get("heading")
        heading = float(heading_value) if _finite_scalar(heading_value) else None
        accepted_by_policy = (
            isinstance(legacy_status, str)
            and legacy_status in policy.accepted_statuses
        )
        rejected_by_policy = (
            isinstance(legacy_status, str)
            and legacy_status in policy.rejected_statuses
        )

        if accepted_by_policy and position is not None:
            return LocalizationResult(
                status=LocalizationStatus.ACCEPTED,
                usable=True,
                authoritative_position_sat_px=position,
                diagnostic_position_sat_px=None,
                heading_deg=heading,
                heading_status=None if heading is not None else "ambiguous",
                decisive_gate="legacy_status_policy",
                reason=None,
                diagnostics=LocalizationDiagnostics(legacy_policy_version=policy.version),
            )

        reason = (
            policy.rejection_reason_for(legacy_status)
            if rejected_by_policy
            else policy.unknown_status_reason
        )
        diagnostic = position if policy.retains_diagnostic_position(legacy_status) else None
        return LocalizationResult(
            status=LocalizationStatus.REJECTED,
            usable=False,
            authoritative_position_sat_px=None,
            diagnostic_position_sat_px=diagnostic,
            heading_deg=heading,
            decisive_gate=reason,
            reason=reason,
            diagnostics=LocalizationDiagnostics(
                exclusions=(reason,) if not rejected_by_policy else (),
                legacy_policy_version=policy.version,
            ),
        )


    def compatibility_mapping(
        self,
        result: LocalizationResult,
        record: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Return a fresh compatibility record after complete validation."""
        validated = self.validate_new(result)
        mapped = dict(record) if record is not None else {}
        authoritative = validated.authoritative_position_sat_px
        diagnostic = validated.diagnostic_position_sat_px
        mapped.update(
            status=validated.status.value,
            usable=validated.usable,
            authoritative_position_sat_px=authoritative,
            diagnostic_position_sat_px=diagnostic,
            heading_deg=validated.heading_deg,
            heading=validated.heading_deg,
            decisive_gate=validated.decisive_gate,
            reason=validated.reason,
            heading_status=validated.heading_status,
            legacy_policy_version=validated.diagnostics.legacy_policy_version,
            sat_coords=authoritative if validated.usable else None,
        )
        return mapped

    def append_compatibility(
        self,
        output: MutableSequence[dict[str, Any]],
        result: LocalizationResult,
        record: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Validate and build first, so inconsistent input cannot alter output."""
        mapped = self.compatibility_mapping(result, record)
        output.append(mapped)
        return mapped

    def from_mapping(
        self,
        record: Mapping[str, Any],
        *,
        legacy_policy: Optional[LegacyStatusPolicy] = LEGACY_LOCALIZE_V1,
    ) -> Optional[LocalizationResult]:
        """Validate a serialized result, or normalize legacy data explicitly.

        A mapping with no authority fields is a missing localization, not an
        implicit legacy acceptance. Legacy ``sat_coords`` require the caller to
        supply the frozen policy.
        """
        if not isinstance(record, Mapping):
            raise LocalizationAuthorityError()
        authority_fields = {
            "status",
            "usable",
            "authoritative_position_sat_px",
            "diagnostic_position_sat_px",
            "heading_deg",
            "decisive_gate",
            "reason",
        }
        # The new contract's ``status`` is exactly ``accepted``/``rejected``. A
        # legacy record that merely happens to carry ``decisive_gate`` must not
        # be routed here, or its legacy status explodes in the enum.
        status_value = record.get("status")
        new_contract_status = any(
            isinstance(status_value, str) and status_value == member.value
            for member in LocalizationStatus
        )
        has_new_contract = new_contract_status and any(
            key in record for key in authority_fields - {"status", "reason"}
        )
        if not has_new_contract:
            # A default policy must not manufacture a rejection out of a record
            # that carries no localization evidence at all; that is still a
            # missing localization, and downstream reporting depends on it.
            has_legacy_evidence = any(key in record for key in ("status", "sat_coords"))
            if legacy_policy is None or not has_legacy_evidence:
                return None
            return self.validate_new(self.normalize_legacy(record, legacy_policy))
        try:
            result = LocalizationResult(
                status=LocalizationStatus(record["status"]),
                usable=record["usable"],
                authoritative_position_sat_px=record.get("authoritative_position_sat_px"),
                diagnostic_position_sat_px=record.get("diagnostic_position_sat_px"),
                heading_deg=record.get("heading_deg"),
                decisive_gate=record["decisive_gate"],
                reason=record.get("reason"),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise LocalizationAuthorityError() from error
        return self.validate_new(result)


_AUTHORITY = LocalizationAuthority()
_SPATIAL_DERIVED_FIELDS = (
    "sat_center",
    "sat_floor_box",
    "collider_sat_floor_box",
    "bbox_3d",
    "position_m",
    "velocity_mps",
    "smoothed_position_sat_px",
    "postprocessed_position_sat_px",
    "visual_sat_coords",
    "visual_sat_center",
)


def authoritative_position(
    record: Mapping[str, Any],
    *,
    legacy_policy: Optional[LegacyStatusPolicy] = LEGACY_LOCALIZE_V1,
) -> Optional[tuple[float, float]]:
    """Return only a validated authoritative coordinate for spatial use."""
    result = _AUTHORITY.from_mapping(record, legacy_policy=legacy_policy)
    return None if result is None else result.authoritative_position_sat_px


def diagnostic_visualization_position(
    record: Mapping[str, Any],
) -> Optional[tuple[float, float]]:
    """Return a validated diagnostic point for explicitly non-spatial display."""
    result = _AUTHORITY.from_mapping(record)
    if result is None or result.status is LocalizationStatus.ACCEPTED:
        return None
    return result.diagnostic_position_sat_px


def has_real_track_motion_authority(record: Mapping[str, Any]) -> bool:
    """Require finalized real-track provenance; never infer it from a display ID."""
    for key in ("track", "track_provenance"):
        track = record.get(key)
        if isinstance(track, Mapping):
            return track.get("kind") == "real"
    return record.get("track_kind") == "real"


def authority_status_reason(record: Mapping[str, Any]) -> tuple[str, str]:
    """Return deterministic reporting keys for a serialized localization."""
    result = _AUTHORITY.from_mapping(record)
    if result is None:
        return "missing", "missing_localization"
    return result.status.value, result.decisive_gate


def grouped_authority_counts(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    """Count records by status and decisive reason with stable key order."""
    counts = Counter(authority_status_reason(record) for record in records)
    grouped: dict[str, dict[str, int]] = {}
    for (status, reason), count in sorted(counts.items()):
        grouped.setdefault(status, {})[reason] = count
    return grouped


def sanitize_spatial_record_for_export(record: Mapping[str, Any]) -> dict[str, Any]:
    """Copy an authority record and remove all non-authoritative spatial output."""
    mapped = copy.deepcopy(dict(record))
    result = _AUTHORITY.from_mapping(mapped)
    if result is None:
        return mapped
    position = result.authoritative_position_sat_px
    mapped["sat_coords"] = position
    if position is None:
        for field in _SPATIAL_DERIVED_FIELDS:
            if field in mapped:
                mapped[field] = None
    elif "sat_center" in mapped:
        mapped["sat_center"] = position
    return mapped


def sanitize_replay_for_export(data: Any) -> Any:
    """Sanitize authority-aware frame objects while preserving legacy schemas."""
    output = copy.deepcopy(data)
    if not isinstance(output, Mapping) or not isinstance(output.get("frames"), list):
        return output
    for frame in output["frames"]:
        if not isinstance(frame, dict) or not isinstance(frame.get("objects"), list):
            continue
        frame["objects"] = [
            sanitize_spatial_record_for_export(obj) if isinstance(obj, Mapping) else obj
            for obj in frame["objects"]
        ]
    return output


def authoritative_extent(
    records: Iterable[Mapping[str, Any]],
) -> Optional[tuple[float, float, float, float]]:
    """Compute a scene extent exclusively from validated authoritative positions."""
    positions = [position for record in records if (position := authoritative_position(record))]
    if not positions:
        return None
    xs, ys = zip(*positions)
    return min(xs), min(ys), max(xs), max(ys)


def collider_footprint(
    record: Mapping[str, Any],
    *,
    length_m: float,
    width_m: float,
    px_per_meter: float,
) -> Optional[list[list[float]]]:
    """Build collider geometry only for a validated accepted localization."""
    result = _AUTHORITY.from_mapping(record)
    if result is None or result.authoritative_position_sat_px is None:
        return None
    values = (length_m, width_m, px_per_meter, result.heading_deg)
    if not all(_finite_scalar(value) for value in values) or min(length_m, width_m, px_per_meter) <= 0:
        return None
    center_x, center_y = result.authoritative_position_sat_px
    angle = math.radians(float(result.heading_deg))
    cos_angle, sin_angle = math.cos(angle), math.sin(angle)
    half_length = float(length_m) * float(px_per_meter) / 2.0
    half_width = float(width_m) * float(px_per_meter) / 2.0
    corners = (
        (half_length, half_width),
        (half_length, -half_width),
        (-half_length, -half_width),
        (-half_length, half_width),
    )
    return [
        [
            center_x + x * cos_angle - y * sin_angle,
            center_y + x * sin_angle + y * cos_angle,
        ]
        for x, y in corners
    ]


__all__ = [
    "LEGACY_LOCALIZE_V1",
    "INCONSISTENT_COORDINATE_STATE",
    "LEGACY_STATUS_EVIDENCE_INSUFFICIENT",
    "LocalizationAuthority",
    "LocalizationAuthorityError",
    "authoritative_extent",
    "authoritative_position",
    "authority_status_reason",
    "collider_footprint",
    "diagnostic_visualization_position",
    "grouped_authority_counts",
    "has_real_track_motion_authority",
    "sanitize_replay_for_export",
    "sanitize_spatial_record_for_export",
]
