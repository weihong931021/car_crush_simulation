"""Complete-replay finalization for genuine versus pseudo track provenance.

Partition and pilot code receives only :attr:`FinalizedTrackReplay.real_track_records`.
Pseudo and untracked records are intentionally available only through the
explicitly named :meth:`FinalizedTrackReplay.frame_local_diagnostic` API.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Iterable

from trafficlab.motion.haware_accuracy.models import (
    CanonicalModel,
    ObservationRecord,
    TrackKind,
    TrackProvenance,
    canonical_order,
)


FRAME_LOCAL_TRACK_ID = "frame_local_track_identity"
INCOMPLETE_TRACK_PROVENANCE = "incomplete_track_provenance"
INCONSISTENT_TRACK_PROVENANCE = "inconsistent_track_provenance"
UNVERIFIED_TRACK_IDENTITY = "unverified_track_identity"
NO_TRACK_IDENTITY = "no_track_identity"

_TRACK_FIELDS = (
    "tracker_name",
    "tracker_version",
    "source_sequence",
    "association_provenance",
)
_FRAME_LOCAL_MARKERS = (
    "frame-local",
    "frame local",
    "detection-index",
    "detection index",
)


@dataclass(frozen=True, kw_only=True)
class FrameLocalDiagnosticEntry(CanonicalModel):
    """One pseudo or untracked record exposed for non-track diagnostics only."""

    record: ObservationRecord
    reason: str


@dataclass(frozen=True, kw_only=True)
class FrameLocalDiagnosticReport(CanonicalModel):
    """An explicitly named diagnostic containing no acceptance-eligible data."""

    diagnostic_name: str
    entries: tuple[FrameLocalDiagnosticEntry, ...]

    def __post_init__(self) -> None:
        if not self.diagnostic_name.strip():
            raise ValueError("frame_local_diagnostic_name_required")
        object.__setattr__(self, "entries", canonical_order(self.entries))
        super().__post_init__()


class FinalizedTrackReplay:
    """Opaque finalized replay boundary presented to later partitioning code."""

    __slots__ = ("_real_track_records", "_frame_local_entries")

    def __init__(
        self,
        real_track_records: tuple[ObservationRecord, ...],
        frame_local_entries: tuple[FrameLocalDiagnosticEntry, ...],
    ) -> None:
        self._real_track_records = canonical_order(real_track_records)
        self._frame_local_entries = canonical_order(frame_local_entries)

    @property
    def real_track_records(self) -> tuple[ObservationRecord, ...]:
        """Return the only records authorized for partition/eligibility inputs."""
        return self._real_track_records

    def frame_local_diagnostic(self, *, diagnostic_name: str) -> FrameLocalDiagnosticReport:
        """Expose pseudo/no-track records only under an explicit diagnostic name."""
        return FrameLocalDiagnosticReport(
            diagnostic_name=diagnostic_name,
            entries=self._frame_local_entries,
        )


def _is_missing(value: object) -> bool:
    return value is None or not isinstance(value, str) or not value.strip()


def _is_frame_local_500(track: TrackProvenance) -> bool:
    match = re.fullmatch(r"\s*([0-9]+)\s*", track.claimed_id)
    if match is None or int(match.group(1)) < 500:
        return False
    association = (track.association_provenance or "").casefold()
    return any(marker in association for marker in _FRAME_LOCAL_MARKERS)


def _classification_reason(
    claims: tuple[tuple[ObservationRecord, TrackProvenance], ...],
    observed_frames: tuple[str, ...],
) -> str | None:
    if any(_is_frame_local_500(track) for _, track in claims):
        return FRAME_LOCAL_TRACK_ID
    if any(_is_missing(getattr(track, field)) for _, track in claims for field in _TRACK_FIELDS):
        return INCOMPLETE_TRACK_PROVENANCE
    for field in _TRACK_FIELDS:
        if len({getattr(track, field) for _, track in claims}) != 1:
            return INCONSISTENT_TRACK_PROVENANCE
    if any(track.source_sequence != record.source_sequence for record, track in claims):
        return INCONSISTENT_TRACK_PROVENANCE
    if len({record.source_sequence for record, _ in claims}) != 1:
        return INCONSISTENT_TRACK_PROVENANCE
    if len(observed_frames) <= 1:
        return UNVERIFIED_TRACK_IDENTITY
    return None

def finalize_track_provenance(records: Iterable[ObservationRecord]) -> FinalizedTrackReplay:
    """Finalize track kinds from all replay occurrences before partitioning.

    Input ``kind``, ``reason``, and claimed ``observed_frames`` are not trusted.
    Actual record occurrences supply cross-frame evidence, and every occurrence
    of a site-scoped claimed ID receives the same final classification.
    """
    complete_replay = tuple(records)
    if any(not isinstance(record, ObservationRecord) for record in complete_replay):
        raise TypeError("track finalization requires ObservationRecord values")

    grouped: dict[tuple[str, str], list[tuple[ObservationRecord, TrackProvenance]]] = {}
    no_track: list[ObservationRecord] = []
    for record in complete_replay:
        if record.track is None:
            no_track.append(record)
            continue
        grouped.setdefault((record.site, record.track.claimed_id), []).append((record, record.track))

    real_records: list[ObservationRecord] = []
    diagnostic_entries = [
        FrameLocalDiagnosticEntry(record=record, reason=NO_TRACK_IDENTITY)
        for record in no_track
    ]
    for claims_list in grouped.values():
        claims = tuple(claims_list)
        observed_frames = canonical_order(
            tuple(record.frame_id for record, _ in claims), unique=True
        )
        reason = _classification_reason(claims, observed_frames)
        kind = TrackKind.REAL if reason is None else TrackKind.PSEUDO
        for record, claim in claims:
            finalized_track = replace(
                claim,
                observed_frames=observed_frames,
                kind=kind,
                reason=reason,
            )
            finalized_record = replace(record, track=finalized_track)
            if kind is TrackKind.REAL:
                real_records.append(finalized_record)
            else:
                diagnostic_entries.append(
                    FrameLocalDiagnosticEntry(
                        record=finalized_record,
                        reason=reason or UNVERIFIED_TRACK_IDENTITY,
                    )
                )

    return FinalizedTrackReplay(tuple(real_records), tuple(diagnostic_entries))
