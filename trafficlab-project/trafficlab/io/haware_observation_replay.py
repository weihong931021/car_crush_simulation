"""Narrow, deterministic provider-neutral Haware observation replay I/O.

The reader and writer require an identity-bound :class:`ValidatedProfile`.
This module deliberately stops at normalized observations: candidate labels are
retained as evidence and are never interpreted as confirmed correspondences.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import gzip
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence, Union

from trafficlab.motion.haware_accuracy.models import (
    AcceptanceProfile,
    CanonicalModel,
    ContentIdentity,
    ImageObservation,
    ObservationRecord,
    ProviderProvenance,
    SourceProvenance,
    TrackKind,
    TrackProvenance,
    canonical_bytes,
    canonical_order,
)
from trafficlab.motion.haware_accuracy.validation import (
    MvpScopeGuard,
    ValidatedProfile,
    require_validated_profile,
)


REPLAY_FORMAT = "trafficlab.haware.observation-replay"
COMPRESSION_METADATA = {
    "algorithm": "gzip",
    "compresslevel": 9,
    "mtime": 0,
    "original_filename": "",
}
MAX_IMAGE_DIMENSION_PX = 1_000_000
MAX_COVARIANCE_ABS_PX2 = 1.0e12
MAX_REPLAY_RECORDS = 100_000


class ReplaySchemaError(ValueError):
    """A deterministic replay failure raised by writer/file APIs."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True, kw_only=True)
class ObservationExclusion(CanonicalModel):
    """One observation removed without invalidating its containing record."""

    observation_id: Optional[str]
    reason: str


@dataclass(frozen=True, kw_only=True)
class AcceptedReplayRecord(CanonicalModel):
    """A normalized record and its deterministic observation exclusions."""

    record_index: int
    record: ObservationRecord
    exclusions: tuple[ObservationExclusion, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "exclusions", canonical_order(self.exclusions))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class RecordRejection(CanonicalModel):
    """One rejected replay record; sibling records remain readable."""

    record_index: int
    reason: str


ReplayReadItem = Union[AcceptedReplayRecord, RecordRejection]


class ObservationAdapter(Protocol):
    """Provider-neutral normalization boundary consumed before optimization."""

    provider_name: str

    def normalize(self, record: Any, contract: Any) -> ReplayReadItem:
        """Normalize one provider record without asserting correspondences."""
        ...


@dataclass(frozen=True)
class LegacyInput:
    """Read-only legacy bytes with repository-relative provenance."""

    payload: bytes
    provenance: SourceProvenance


_REQUIRED_RECORD_FIELDS = frozenset({
    "schema_version", "site", "source_sequence", "frame_id", "detection_id",
    "image_size_px", "observations", "provider", "source",
})
_OPTIONAL_RECORD_FIELDS = frozenset({"track"})
_REQUIRED_OBSERVATION_FIELDS = frozenset({
    "observation_id", "pixel", "confidence", "candidate_labels", "provider_key",
})
_OPTIONAL_OBSERVATION_FIELDS = frozenset({"covariance_px2"})


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _finite_number(value: Any) -> Optional[float]:
    if not _is_number(value):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _bounded_string(value: Any, maximum: int, *, optional: bool = False) -> Optional[str]:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError
    return value


def _identity_mapping(value: Any, maximum: int) -> ContentIdentity:
    if not isinstance(value, Mapping) or set(value) != {"algorithm", "digest"}:
        raise ValueError
    algorithm = _bounded_string(value["algorithm"], maximum)
    digest = _bounded_string(value["digest"], maximum)
    return ContentIdentity(digest=digest, algorithm=algorithm)


def _provider_mapping(value: Any, maximum: int) -> ProviderProvenance:
    required = {"schema_version", "provider_name", "provider_version", "adapter_version"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError
    return ProviderProvenance(
        schema_version=_bounded_string(value["schema_version"], maximum),
        provider_name=_bounded_string(value["provider_name"], maximum),
        provider_version=_bounded_string(value["provider_version"], maximum),
        adapter_version=_bounded_string(value["adapter_version"], maximum),
    )


def _source_mapping(value: Any, maximum: int) -> SourceProvenance:
    required = {"schema_version", "source_id", "repository_relative_path", "source_content_identity"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError
    path = value["repository_relative_path"]
    if path is not None:
        path = _bounded_string(path, maximum)
    return SourceProvenance(
        schema_version=_bounded_string(value["schema_version"], maximum),
        source_id=_bounded_string(value["source_id"], maximum),
        repository_relative_path=path,
        source_content_identity=_identity_mapping(value["source_content_identity"], maximum),
    )


def _track_mapping(value: Any, maximum: int, maximum_frames: int) -> TrackProvenance:
    required = {
        "schema_version", "claimed_id", "tracker_name", "tracker_version",
        "source_sequence", "association_provenance", "observed_frames", "kind", "reason",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError
    frames = value["observed_frames"]
    if not isinstance(frames, list) or len(frames) > maximum_frames:
        raise ValueError
    optional_names = ("tracker_name", "tracker_version", "source_sequence", "association_provenance", "reason")
    optional = {
        name: _bounded_string(value[name], maximum, optional=True)
        for name in optional_names
    }
    try:
        kind = TrackKind(_bounded_string(value["kind"], maximum))
    except (ValueError, TypeError) as error:
        raise ValueError from error
    return TrackProvenance(
        schema_version=_bounded_string(value["schema_version"], maximum),
        claimed_id=_bounded_string(value["claimed_id"], maximum),
        tracker_name=optional["tracker_name"],
        tracker_version=optional["tracker_version"],
        source_sequence=optional["source_sequence"],
        association_provenance=optional["association_provenance"],
        observed_frames=tuple(_bounded_string(frame, maximum) for frame in frames),
        kind=kind,
        reason=optional["reason"],
    )


def _observation_reason(raw: Any, image_size: tuple[int, int], contract: Any) -> tuple[Optional[ImageObservation], Optional[str], Optional[str]]:
    """Return (observation, reason, best-effort id) without raising."""
    if not isinstance(raw, Mapping):
        return None, "observation_not_object", None
    identity = raw.get("observation_id") if isinstance(raw.get("observation_id"), str) else None
    fields = set(raw)
    if not _REQUIRED_OBSERVATION_FIELDS.issubset(fields):
        return None, "observation_missing_required_field", identity
    if fields - _REQUIRED_OBSERVATION_FIELDS - _OPTIONAL_OBSERVATION_FIELDS - {"schema_version"}:
        return None, "observation_unknown_field", identity
    try:
        observation_id = _bounded_string(raw["observation_id"], contract.maximum_string_length)
        provider_key = _bounded_string(raw["provider_key"], contract.maximum_string_length)
    except ValueError:
        return None, "observation_invalid_identity", identity

    pixel = raw["pixel"]
    if not isinstance(pixel, list) or len(pixel) != 2:
        return None, "observation_invalid_coordinate_type", observation_id
    u, v = (_finite_number(item) for item in pixel)
    if u is None or v is None:
        return None, "observation_non_finite_coordinate", observation_id
    width, height = image_size
    if not (0.0 <= u < width and 0.0 <= v < height):
        return None, "observation_coordinate_out_of_bounds", observation_id

    confidence = _finite_number(raw["confidence"])
    if confidence is None:
        return None, "observation_non_finite_confidence", observation_id
    if not contract.confidence_bounds.contains(confidence):
        return None, "observation_confidence_out_of_bounds", observation_id

    labels = raw["candidate_labels"]
    if not isinstance(labels, list):
        return None, "observation_invalid_labels_type", observation_id
    if len(labels) > contract.maximum_labels_per_observation:
        return None, "observation_label_count_exceeded", observation_id
    try:
        candidate_labels = tuple(_bounded_string(label, contract.maximum_string_length) for label in labels)
    except ValueError:
        return None, "observation_invalid_label", observation_id

    covariance = raw.get("covariance_px2")
    parsed_covariance = None
    if covariance is not None:
        if (not isinstance(covariance, list) or len(covariance) != 2
                or any(not isinstance(row, list) or len(row) != 2 for row in covariance)):
            return None, "observation_invalid_covariance", observation_id
        values = tuple(tuple(_finite_number(item) for item in row) for row in covariance)
        if any(item is None or abs(item) > MAX_COVARIANCE_ABS_PX2 for row in values for item in row):
            return None, "observation_invalid_covariance", observation_id
        a, b = values[0]
        c, d = values[1]
        if a < 0.0 or d < 0.0 or b != c or a * d - b * c < -1e-12:
            return None, "observation_invalid_covariance", observation_id
        parsed_covariance = values

    try:
        observation = ImageObservation(
            schema_version=_bounded_string(raw.get("schema_version", "1.0"), contract.maximum_string_length),
            observation_id=observation_id,
            pixel=(u, v),
            confidence=confidence,
            candidate_labels=candidate_labels,
            provider_key=provider_key,
            covariance_px2=parsed_covariance,
        )
    except (ValueError, TypeError):
        return None, "observation_invalid_value", observation_id
    return observation, None, observation_id


def _normalize_duplicates(observations: Sequence[ImageObservation]) -> tuple[Optional[tuple[ImageObservation, ...]], tuple[ObservationExclusion, ...]]:
    grouped: dict[str, list[ImageObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.observation_id, []).append(observation)
    retained: list[ImageObservation] = []
    exclusions: list[ObservationExclusion] = []
    for identity in sorted(grouped):
        candidates = sorted(grouped[identity], key=lambda item: item.canonical_bytes())
        keys: dict[bytes, ImageObservation] = {}
        for candidate in candidates:
            key = candidate.canonical_bytes()
            if key in keys and candidate != keys[key]:
                return None, ()
            keys[key] = candidate
        winner = candidates[0]
        retained.append(winner)
        for duplicate in candidates[1:]:
            reason = "duplicate_observation_exact" if duplicate == winner else "duplicate_observation_conflict_discarded"
            exclusions.append(ObservationExclusion(observation_id=identity, reason=reason))
    return tuple(retained), canonical_order(exclusions)


def normalize_record_mapping(
    raw: Any,
    *,
    contract: Any,
    record_index: int = 0,
) -> ReplayReadItem:
    """Normalize one provider-neutral mapping under the frozen replay contract.

    Provider adapters call this public boundary so observation- and record-level
    validation has exactly the same behavior as replay reads.
    """
    index = record_index
    if not isinstance(raw, Mapping):
        return RecordRejection(record_index=index, reason="record_not_object")
    fields = set(raw)
    if not _REQUIRED_RECORD_FIELDS.issubset(fields):
        return RecordRejection(record_index=index, reason="record_missing_required_field")
    if fields - _REQUIRED_RECORD_FIELDS - _OPTIONAL_RECORD_FIELDS:
        return RecordRejection(record_index=index, reason="record_unknown_field")
    try:
        schema_version = _bounded_string(raw["schema_version"], contract.maximum_string_length)
    except ValueError:
        return RecordRejection(record_index=index, reason="invalid_schema_version")
    if schema_version != contract.version:
        return RecordRejection(record_index=index, reason="replay_schema_version_mismatch")

    try:
        site = _bounded_string(raw["site"], contract.maximum_string_length)
        source_sequence = _bounded_string(raw["source_sequence"], contract.maximum_string_length)
        frame_id = _bounded_string(raw["frame_id"], contract.maximum_string_length)
        detection_id = _bounded_string(raw["detection_id"], contract.maximum_string_length)
    except ValueError:
        return RecordRejection(record_index=index, reason="invalid_record_identity")

    image_size = raw["image_size_px"]
    if (not isinstance(image_size, list) or len(image_size) != 2
            or any(not isinstance(item, int) or isinstance(item, bool) for item in image_size)
            or any(item <= 0 or item > MAX_IMAGE_DIMENSION_PX for item in image_size)):
        return RecordRejection(record_index=index, reason="invalid_image_dimensions")
    image_size_tuple = (image_size[0], image_size[1])

    raw_observations = raw["observations"]
    if not isinstance(raw_observations, list):
        return RecordRejection(record_index=index, reason="invalid_observation_collection")
    if not 1 <= len(raw_observations) <= contract.maximum_observations:
        return RecordRejection(record_index=index, reason="observation_count_out_of_bounds")

    try:
        provider = _provider_mapping(raw["provider"], contract.maximum_string_length)
        source = _source_mapping(raw["source"], contract.maximum_string_length)
        track = None if raw.get("track") is None else _track_mapping(
            raw["track"], contract.maximum_string_length, contract.maximum_observations,
        )
    except (ValueError, TypeError):
        return RecordRejection(record_index=index, reason="invalid_record_provenance")

    valid: list[ImageObservation] = []
    exclusions: list[ObservationExclusion] = []
    for raw_observation in raw_observations:
        observation, reason, identity = _observation_reason(raw_observation, image_size_tuple, contract)
        if observation is None:
            exclusions.append(ObservationExclusion(observation_id=identity, reason=reason or "observation_invalid_value"))
        else:
            valid.append(observation)
    normalized, duplicate_exclusions = _normalize_duplicates(valid)
    if normalized is None:
        return RecordRejection(record_index=index, reason="non_deterministic_duplicate_resolution")
    exclusions.extend(duplicate_exclusions)
    try:
        record = ObservationRecord(
            schema_version=schema_version,
            site=site,
            source_sequence=source_sequence,
            frame_id=frame_id,
            detection_id=detection_id,
            image_size_px=image_size_tuple,
            observations=normalized,
            provider=provider,
            source=source,
            track=track,
        )
    except (ValueError, TypeError):
        return RecordRejection(record_index=index, reason="invalid_record_value")
    return AcceptedReplayRecord(record_index=index, record=record, exclusions=tuple(exclusions))


def _record_mapping(record: ObservationRecord, schema_version: str) -> dict[str, Any]:
    """Convert only frozen schema fields; no semantic label interpretation occurs."""
    def identity(value: ContentIdentity) -> dict[str, str]:
        return {"algorithm": value.algorithm, "digest": value.digest}

    source = {
        "schema_version": record.source.schema_version,
        "source_id": record.source.source_id,
        "repository_relative_path": record.source.repository_relative_path,
        "source_content_identity": identity(record.source.source_content_identity),
    }
    provider = {
        "schema_version": record.provider.schema_version,
        "provider_name": record.provider.provider_name,
        "provider_version": record.provider.provider_version,
        "adapter_version": record.provider.adapter_version,
    }
    observations = []
    for observation in record.observations:
        value: dict[str, Any] = {
            "schema_version": observation.schema_version,
            "observation_id": observation.observation_id,
            "pixel": list(observation.pixel),
            "confidence": observation.confidence,
            "candidate_labels": list(observation.candidate_labels),
            "provider_key": observation.provider_key,
        }
        if observation.covariance_px2 is not None:
            value["covariance_px2"] = [list(row) for row in observation.covariance_px2]
        observations.append(value)
    result: dict[str, Any] = {
        "schema_version": schema_version,
        "site": record.site,
        "source_sequence": record.source_sequence,
        "frame_id": record.frame_id,
        "detection_id": record.detection_id,
        "image_size_px": list(record.image_size_px),
        "observations": observations,
        "provider": provider,
        "source": source,
    }
    if record.track is not None:
        result["track"] = {
            "schema_version": record.track.schema_version,
            "claimed_id": record.track.claimed_id,
            "tracker_name": record.track.tracker_name,
            "tracker_version": record.track.tracker_version,
            "source_sequence": record.track.source_sequence,
            "association_provenance": record.track.association_provenance,
            "observed_frames": list(record.track.observed_frames),
            "kind": record.track.kind.value,
            "reason": record.track.reason,
        }
    return result


def _envelope(record_mappings: Sequence[Mapping[str, Any]], schema_version: str) -> dict[str, Any]:
    return {
        "compression": COMPRESSION_METADATA,
        "format": REPLAY_FORMAT,
        "records": list(record_mappings),
        "schema_version": schema_version,
    }


def _decode_payload(payload: bytes) -> Any:
    if not isinstance(payload, bytes):
        raise ReplaySchemaError("invalid_replay_payload", "payload must be bytes")
    try:
        decoded = gzip.decompress(payload) if payload.startswith(b"\x1f\x8b") else payload
        return json.loads(decoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReplaySchemaError("invalid_replay_payload", str(error)) from error


def _validate_envelope(value: Any, profile: AcceptanceProfile) -> Sequence[Any]:
    if not isinstance(value, Mapping) or set(value) != {"compression", "format", "records", "schema_version"}:
        raise ReplaySchemaError("invalid_replay_envelope")
    if value["format"] != REPLAY_FORMAT:
        raise ReplaySchemaError("unsupported_replay_format")
    if value["schema_version"] != profile.replay_contract.version:
        raise ReplaySchemaError("replay_schema_version_mismatch")
    if value["compression"] != COMPRESSION_METADATA:
        raise ReplaySchemaError("compression_metadata_mismatch")
    records = value["records"]
    if not isinstance(records, list) or len(records) > MAX_REPLAY_RECORDS:
        raise ReplaySchemaError("replay_record_count_out_of_bounds")
    return records


class ObservationReplayReader:
    """Parse canonical or equivalent UTF-8/gzip replay payloads record-by-record."""

    def read(
        self,
        payload: bytes,
        *,
        token: ValidatedProfile,
        profile: AcceptanceProfile,
        scope: MvpScopeGuard,
    ) -> tuple[ReplayReadItem, ...]:
        require_validated_profile(token, profile, scope)
        try:
            records = _validate_envelope(_decode_payload(payload), profile)
        except ReplaySchemaError as error:
            return (RecordRejection(record_index=-1, reason=error.code),)
        return tuple(
            normalize_record_mapping(raw, contract=profile.replay_contract, record_index=index)
            for index, raw in enumerate(records)
        )
    def read_verified(
        self,
        payload: bytes,
        *,
        token: ValidatedProfile,
        profile: AcceptanceProfile,
        scope: MvpScopeGuard,
    ) -> tuple[ReplayReadItem, ...]:
        """Read a pilot replay and isolate non-canonical records.

        Envelope failures remain payload-level rejections.  Each otherwise
        valid record is reserialized independently so one mismatch cannot
        discard conforming siblings.
        """
        require_validated_profile(token, profile, scope)
        try:
            records = _validate_envelope(_decode_payload(payload), profile)
        except ReplaySchemaError as error:
            return (RecordRejection(record_index=-1, reason=error.code),)
        verified: list[ReplayReadItem] = []
        for index, raw in enumerate(records):
            result = normalize_record_mapping(
                raw, contract=profile.replay_contract, record_index=index,
            )
            if isinstance(result, AcceptedReplayRecord):
                canonical = _record_mapping(result.record, profile.replay_contract.version)
                if raw != canonical:
                    result = RecordRejection(
                        record_index=index, reason="replay_round_trip_mismatch",
                    )
            verified.append(result)
        return tuple(verified)


class ObservationReplayWriter:
    """Normalize records and emit deterministic canonical replay bytes."""

    def _normalized_mappings(
        self,
        records: Iterable[ObservationRecord],
        *,
        profile: AcceptanceProfile,
    ) -> tuple[dict[str, Any], ...]:
        normalized: list[ObservationRecord] = []
        for index, record in enumerate(records):
            if not isinstance(record, ObservationRecord):
                raise ReplaySchemaError("invalid_writer_record_type", f"record {index}")
            result = normalize_record_mapping(
                _record_mapping(record, profile.replay_contract.version),
                contract=profile.replay_contract,
                record_index=index,
            )
            if isinstance(result, RecordRejection):
                raise ReplaySchemaError(result.reason, f"record {index}")
            normalized.append(result.record)
        ordered = sorted(
            normalized,
            key=lambda item: (item.site, item.source_sequence, item.frame_id, item.detection_id, item.canonical_bytes()),
        )
        identities = [(item.site, item.source_sequence, item.frame_id, item.detection_id) for item in ordered]
        if len(identities) != len(set(identities)):
            raise ReplaySchemaError("duplicate_record_identity")
        return tuple(_record_mapping(item, profile.replay_contract.version) for item in ordered)

    def canonical_bytes(
        self,
        records: Iterable[ObservationRecord],
        *,
        token: ValidatedProfile,
        profile: AcceptanceProfile,
        scope: MvpScopeGuard,
    ) -> bytes:
        require_validated_profile(token, profile, scope)
        mappings = self._normalized_mappings(records, profile=profile)
        payload = canonical_bytes(_envelope(mappings, profile.replay_contract.version))
        self._verify_round_trip(payload, mappings, token=token, profile=profile, scope=scope)
        return payload

    def compressed_bytes(
        self,
        records: Iterable[ObservationRecord],
        *,
        token: ValidatedProfile,
        profile: AcceptanceProfile,
        scope: MvpScopeGuard,
    ) -> bytes:
        require_validated_profile(token, profile, scope)
        mappings = self._normalized_mappings(records, profile=profile)
        utf8_payload = canonical_bytes(_envelope(mappings, profile.replay_contract.version))
        output = BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, compresslevel=9, mtime=0) as stream:
            stream.write(utf8_payload)
        payload = output.getvalue()
        self._verify_round_trip(payload, mappings, token=token, profile=profile, scope=scope)
        return payload

    def _verify_round_trip(
        self,
        payload: bytes,
        mappings: Sequence[Mapping[str, Any]],
        *,
        token: ValidatedProfile,
        profile: AcceptanceProfile,
        scope: MvpScopeGuard,
    ) -> None:
        results = ObservationReplayReader().read(payload, token=token, profile=profile, scope=scope)
        if any(not isinstance(item, AcceptedReplayRecord) or item.exclusions for item in results):
            raise ReplaySchemaError("replay_round_trip_mismatch")
        reserialized = tuple(_record_mapping(item.record, profile.replay_contract.version) for item in results)
        if tuple(mappings) != reserialized:
            raise ReplaySchemaError("replay_round_trip_mismatch")
        canonical_payload = canonical_bytes(_envelope(reserialized, profile.replay_contract.version))
        if payload.startswith(b"\x1f\x8b"):
            output = BytesIO()
            with gzip.GzipFile(filename="", mode="wb", fileobj=output, compresslevel=9, mtime=0) as stream:
                stream.write(canonical_payload)
            canonical_payload = output.getvalue()
        if payload != canonical_payload:
            raise ReplaySchemaError("replay_round_trip_mismatch")

    def write(
        self,
        path: Union[str, Path],
        records: Iterable[ObservationRecord],
        *,
        token: ValidatedProfile,
        profile: AcceptanceProfile,
        scope: MvpScopeGuard,
        compressed: bool = True,
        repository_root: Optional[Union[str, Path]] = None,
    ) -> None:
        destination = Path(path)
        root = Path(repository_root).resolve() if repository_root is not None else Path(__file__).resolve().parents[3]
        resolved_destination = destination.resolve()
        try:
            relative = resolved_destination.relative_to(root)
        except ValueError:
            relative = None
        if relative is not None and relative.parts and relative.parts[0] in {"pifpaf", "location"}:
            raise ReplaySchemaError("legacy_input_tree_is_read_only")
        payload = (
            self.compressed_bytes(records, token=token, profile=profile, scope=scope)
            if compressed else self.canonical_bytes(records, token=token, profile=profile, scope=scope)
        )
        destination.write_bytes(payload)


def read_legacy_input(
    repository_root: Union[str, Path],
    source_path: Union[str, Path],
    *,
    token: ValidatedProfile,
    profile: AcceptanceProfile,
    scope: MvpScopeGuard,
) -> LegacyInput:
    """Read a root legacy artifact without importing, dispatching to, or writing it."""
    require_validated_profile(token, profile, scope)
    root = Path(repository_root).resolve(strict=True)
    source = Path(source_path)
    candidate = (root / source).resolve(strict=True) if not source.is_absolute() else source.resolve(strict=True)
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ReplaySchemaError("legacy_source_outside_repository") from error
    parts = relative.parts
    if not parts or parts[0] not in {"pifpaf", "location"}:
        raise ReplaySchemaError("not_legacy_input_tree")
    if "trafficlab-project" in parts:
        raise ReplaySchemaError("not_legacy_input_tree")
    if not candidate.is_file():
        raise ReplaySchemaError("legacy_source_not_file")
    payload = candidate.read_bytes()
    relative_posix = relative.as_posix()
    provenance = SourceProvenance(
        source_id=f"legacy:{relative_posix}",
        repository_relative_path=relative_posix,
        source_content_identity=ContentIdentity.for_bytes(payload),
    )
    return LegacyInput(payload=payload, provenance=provenance)
