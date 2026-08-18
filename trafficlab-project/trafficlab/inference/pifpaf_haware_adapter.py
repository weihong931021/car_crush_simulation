"""Sole OpenPifPaf boundary for Haware observations and replay migration.

Provider labels and confidence are retained only as candidate evidence.  This
module never creates optimizer correspondences and the one-way legacy importer
never consumes stored localization outputs such as ``sat_coords`` or ``kp_sat``.
"""
from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from trafficlab.io.haware_observation_replay import (
    AcceptedReplayRecord,
    RecordRejection,
    ReplayReadItem,
    normalize_record_mapping,
)
from trafficlab.motion.haware_accuracy.models import (
    ContentIdentity,
    SourceProvenance,
    TrackKind,
    TrackProvenance,
)


ADAPTER_VERSION = "pifpaf-haware-adapter-v1"
PROVIDER_NAME = "openpifpaf"
APOLLO_24_LABELS = (
    "front_up_right", "front_up_left", "front_light_right", "front_light_left",
    "front_low_right", "front_low_left", "central_up_left", "front_wheel_left",
    "rear_wheel_left", "rear_corner_left", "rear_up_left", "rear_up_right",
    "rear_light_left", "rear_light_right", "rear_low_left", "rear_low_right",
    "central_up_right", "rear_corner_right", "rear_wheel_right", "front_wheel_right",
    "rear_plate_left", "rear_plate_right", "mirror_edge_left", "mirror_edge_right",
)

@dataclass(frozen=True)
class PifPafProviderRecord:
    """One Apollo-24 provider record before provider-neutral normalization."""

    site: str
    source_sequence: str
    frame_id: str
    detection_id: str
    image_size_px: tuple[int, int]
    keypoints: Sequence[Sequence[Any]]
    provider_version: str
    source: SourceProvenance
    track: Optional[TrackProvenance] = None


def _identity_mapping(identity: ContentIdentity) -> dict[str, str]:
    return {"algorithm": identity.algorithm, "digest": identity.digest}


def _source_mapping(source: SourceProvenance) -> dict[str, Any]:
    return {
        "schema_version": source.schema_version,
        "source_id": source.source_id,
        "repository_relative_path": source.repository_relative_path,
        "source_content_identity": _identity_mapping(source.source_content_identity),
    }


def _track_mapping(track: TrackProvenance) -> dict[str, Any]:
    return {
        "schema_version": track.schema_version,
        "claimed_id": track.claimed_id,
        "tracker_name": track.tracker_name,
        "tracker_version": track.tracker_version,
        "source_sequence": track.source_sequence,
        "association_provenance": track.association_provenance,
        "observed_frames": list(track.observed_frames),
        "kind": track.kind.value,
        "reason": track.reason,
    }


class PifPafObservationAdapter:
    """Map Apollo-24 provider rows into candidate-only image observations."""

    provider_name = PROVIDER_NAME

    def normalize(self, record: Any, contract: Any) -> ReplayReadItem:
        if not isinstance(record, PifPafProviderRecord):
            return RecordRejection(record_index=0, reason="pifpaf_record_invalid_type")
        if not isinstance(record.keypoints, Sequence) or isinstance(record.keypoints, (str, bytes)):
            return RecordRejection(record_index=0, reason="pifpaf_apollo24_keypoints_invalid")
        if len(record.keypoints) != len(APOLLO_24_LABELS):
            return RecordRejection(record_index=0, reason="pifpaf_apollo24_keypoint_count_invalid")

        observations = []
        for index, (label, row) in enumerate(zip(APOLLO_24_LABELS, record.keypoints)):
            if isinstance(row, Sequence) and not isinstance(row, (str, bytes)) and len(row) == 3:
                pixel: Any = [row[0], row[1]]
                confidence: Any = row[2]
            else:
                pixel = None
                confidence = None
            observations.append({
                "schema_version": "1.0",
                "observation_id": f"apollo24:{index:02d}",
                "pixel": pixel,
                "confidence": confidence,
                "candidate_labels": [label],
                "provider_key": f"apollo24:{index:02d}",
            })

        raw: dict[str, Any] = {
            "schema_version": contract.version,
            "site": record.site,
            "source_sequence": record.source_sequence,
            "frame_id": record.frame_id,
            "detection_id": record.detection_id,
            "image_size_px": list(record.image_size_px),
            "observations": observations,
            "provider": {
                "schema_version": "1.0",
                "provider_name": self.provider_name,
                "provider_version": record.provider_version,
                "adapter_version": ADAPTER_VERSION,
            },
            "source": _source_mapping(record.source),
        }
        if record.track is not None:
            raw["track"] = _track_mapping(record.track)
        return normalize_record_mapping(raw, contract=contract)


def _decode_legacy_payload(payload: bytes) -> Any:
    if not isinstance(payload, bytes):
        raise ValueError("payload must be bytes")
    decoded = gzip.decompress(payload) if payload.startswith(b"\x1f\x8b") else payload
    return json.loads(decoded.decode("utf-8"))


def _legacy_track_claim(
    claimed_id: Any,
    *,
    frame_id: str,
    source_sequence: str,
) -> Optional[TrackProvenance]:
    """Preserve a claim without performing complete-replay track finalization."""
    if claimed_id is None:
        return None
    display_id = str(claimed_id)
    frame_local = display_id.isdecimal() and int(display_id) >= 500
    return TrackProvenance(
        claimed_id=display_id,
        tracker_name=None,
        tracker_version=None,
        source_sequence=source_sequence,
        association_provenance=(
            "frame-local-detection-index" if frame_local
            else "legacy_trafficlab_replay_unverified"
        ),
        observed_frames=(frame_id,),
        kind=TrackKind.PSEUDO,
        reason=(
            "frame_local_track_identity" if frame_local
            else "legacy_track_claim_unfinalized"
        ),
    )


class TrafficLabReplayImporter:
    """One-way migration from existing TrafficLab replay JSON to observations."""

    def __init__(self, adapter: Optional[PifPafObservationAdapter] = None) -> None:
        self._adapter = adapter or PifPafObservationAdapter()

    def import_payload(
        self,
        payload: bytes,
        *,
        source_repository_relative_path: str,
        provider_version: str,
        contract: Any,
        source_sequence: Optional[str] = None,
        site: Optional[str] = None,
    ) -> tuple[ReplayReadItem, ...]:
        try:
            legacy = _decode_legacy_payload(payload)
            if not isinstance(legacy, Mapping):
                raise ValueError("legacy replay must be an object")
            frames = legacy.get("frames")
            meta = legacy.get("meta")
            if not isinstance(frames, list) or not isinstance(meta, Mapping):
                raise ValueError("legacy replay envelope is invalid")
            resolution = meta.get("resolution")
            selected_site = site if site is not None else legacy.get("location_code")
            selected_sequence = source_sequence if source_sequence is not None else legacy.get("mp4_path")
            if not isinstance(resolution, list) or len(resolution) != 2:
                raise ValueError("legacy replay resolution is invalid")
            if not isinstance(selected_site, str) or not isinstance(selected_sequence, str):
                raise ValueError("legacy replay identity is invalid")
            source = SourceProvenance(
                source_id=f"trafficlab-replay:{source_repository_relative_path}",
                repository_relative_path=source_repository_relative_path,
                source_content_identity=ContentIdentity.for_bytes(payload),
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return (RecordRejection(record_index=-1, reason="legacy_replay_invalid_payload"),)

        results: list[ReplayReadItem] = []
        record_index = 0
        for frame in frames:
            if not isinstance(frame, Mapping) or "frame_index" not in frame or not isinstance(frame.get("objects"), list):
                results.append(RecordRejection(record_index=record_index, reason="legacy_replay_invalid_frame"))
                record_index += 1
                continue
            frame_id = str(frame["frame_index"])
            for object_value in frame["objects"]:
                if not isinstance(object_value, Mapping):
                    results.append(RecordRejection(record_index=record_index, reason="legacy_replay_invalid_object"))
                    record_index += 1
                    continue
                provider_record = PifPafProviderRecord(
                    site=selected_site,
                    source_sequence=selected_sequence,
                    frame_id=frame_id,
                    detection_id=str(object_value.get("id", "")),
                    image_size_px=(resolution[0], resolution[1]),
                    keypoints=object_value.get("kp_cctv", ()),
                    provider_version=provider_version,
                    source=source,
                    track=_legacy_track_claim(
                        object_value.get("tracked_id"),
                        frame_id=frame_id,
                        source_sequence=selected_sequence,
                    ),
                )
                normalized = self._adapter.normalize(provider_record, contract)
                if isinstance(normalized, AcceptedReplayRecord):
                    normalized = AcceptedReplayRecord(
                        record_index=record_index,
                        record=normalized.record,
                        exclusions=normalized.exclusions,
                    )
                else:
                    normalized = RecordRejection(record_index=record_index, reason=normalized.reason)
                results.append(normalized)
                record_index += 1
        return tuple(results)

    def import_file(
        self,
        repository_root: Union[str, Path],
        source_path: Union[str, Path],
        *,
        provider_version: str,
        contract: Any,
        source_sequence: Optional[str] = None,
        site: Optional[str] = None,
    ) -> tuple[ReplayReadItem, ...]:
        """Read but never modify a repository artifact, recording path and hash."""
        try:
            root = Path(repository_root).resolve(strict=True)
            candidate = Path(source_path)
            candidate = (root / candidate).resolve(strict=True) if not candidate.is_absolute() else candidate.resolve(strict=True)
            relative = candidate.relative_to(root).as_posix()
            payload = candidate.read_bytes()
        except (OSError, ValueError):
            return (RecordRejection(record_index=-1, reason="legacy_replay_source_invalid"),)
        return self.import_payload(
            payload,
            source_repository_relative_path=relative,
            provider_version=provider_version,
            contract=contract,
            source_sequence=source_sequence,
            site=site,
        )


def create_openpifpaf_predictor(
    checkpoint: str,
    *,
    instance_threshold: float,
    seed_threshold: float,
) -> Any:
    """Create the provider predictor; all OpenPifPaf imports stop here."""
    import argparse
    import openpifpaf
    import openpifpaf.plugins.apollocar3d as apollocar3d

    apollocar3d.register()
    parser = argparse.ArgumentParser(add_help=False)
    openpifpaf.decoder.cli(parser)
    decoder_args = parser.parse_args([])
    decoder_args.instance_threshold = instance_threshold
    decoder_args.seed_threshold = seed_threshold
    openpifpaf.decoder.configure(decoder_args)
    return openpifpaf.Predictor(checkpoint=checkpoint)
