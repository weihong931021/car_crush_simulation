"""Focused tests for atomic localization coordinate authority."""
from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trafficlab.motion.haware_accuracy.models import (  # noqa: E402
    LegacyStatusPolicy,
    LocalizationResult,
    LocalizationStatus,
)
from trafficlab.motion.localization_authority import (  # noqa: E402
    authoritative_position,
    authority_status_reason,
    diagnostic_visualization_position,
    sanitize_spatial_record_for_export,
    INCONSISTENT_COORDINATE_STATE,
    LEGACY_STATUS_EVIDENCE_INSUFFICIENT,
    LocalizationAuthority,
    LocalizationAuthorityError,
)


def policy() -> LegacyStatusPolicy:
    return LegacyStatusPolicy(
        version="frozen-legacy-v1",
        accepted_statuses=("ok",),
        rejected_statuses=("spread_rejected", "failed"),
    )


def accepted() -> LocalizationResult:
    return LocalizationResult(
        status=LocalizationStatus.ACCEPTED,
        usable=True,
        authoritative_position_sat_px=(10.0, 20.0),
        diagnostic_position_sat_px=None,
        heading_deg=45.0,
        decisive_gate="accepted",
        reason=None,
    )


def rejected() -> LocalizationResult:
    return LocalizationResult(
        status=LocalizationStatus.REJECTED,
        usable=False,
        authoritative_position_sat_px=None,
        diagnostic_position_sat_px=(11.0, 21.0),
        heading_deg=46.0,
        decisive_gate="spread_rejected",
        reason="spread_rejected",
    )


class LocalizationAuthorityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = LocalizationAuthority()

    def test_accepted_result_is_authoritative_in_compatibility_mapping(self):
        result = accepted()
        self.assertIs(self.authority.validate_new(result), result)
        mapped = self.authority.compatibility_mapping(result)
        self.assertTrue(mapped["usable"])
        self.assertEqual(mapped["sat_coords"], (10.0, 20.0))
        self.assertEqual(mapped["authoritative_position_sat_px"], (10.0, 20.0))
        self.assertIsNone(mapped["diagnostic_position_sat_px"])
        self.assertEqual(mapped["heading"], 45.0)

    def test_rejected_optimizer_fit_is_diagnostic_only(self):
        original = {"sat_coords": (999.0, 888.0), "source": "optimizer"}
        mapped = self.authority.compatibility_mapping(rejected(), original)
        self.assertEqual(original["sat_coords"], (999.0, 888.0))
        self.assertIsNone(mapped["sat_coords"])
        self.assertIsNone(mapped["authoritative_position_sat_px"])
        self.assertEqual(mapped["diagnostic_position_sat_px"], (11.0, 21.0))
        self.assertFalse(mapped["usable"])

    def test_inconsistent_new_record_is_rejected_atomically(self):
        inconsistent = accepted()
        object.__setattr__(inconsistent, "diagnostic_position_sat_px", (1.0, 2.0))
        output = [{"frame_id": "prior", "sat_coords": (3.0, 4.0)}]
        before = [dict(item) for item in output]
        with self.assertRaises(LocalizationAuthorityError) as caught:
            self.authority.append_compatibility(output, inconsistent)
        self.assertEqual(caught.exception.reason, INCONSISTENT_COORDINATE_STATE)
        self.assertEqual(output, before)

    def test_defensive_validation_rejects_all_authority_role_conflicts(self):
        mutations = (
            (accepted(), "usable", False),
            (accepted(), "authoritative_position_sat_px", None),
            (accepted(), "heading_deg", math.nan),
            (rejected(), "usable", True),
            (rejected(), "authoritative_position_sat_px", (1.0, 2.0)),
            (rejected(), "diagnostic_position_sat_px", (math.inf, 2.0)),
        )
        for result, attribute, value in mutations:
            with self.subTest(attribute=attribute, value=value):
                object.__setattr__(result, attribute, value)
                with self.assertRaisesRegex(
                    LocalizationAuthorityError, INCONSISTENT_COORDINATE_STATE
                ):
                    self.authority.validate_new(result)


    def test_legacy_acceptance_requires_a_frozen_policy_and_a_finite_coordinate(self):
        """Position authority follows the coordinate, not the heading.

        Superseded 2026-08-17 (Requirement 1.19): this test previously pinned
        ``heading=None`` to REJECTED. The player derives heading from the path
        itself, so discarding a usable position over a missing heading threw
        away the only half of the output this repository consumes.
        """
        normalized = self.authority.normalize_legacy(
            {"status": "ok", "sat_coords": [5, 6], "heading": 90}, policy()
        )
        self.assertEqual(normalized.status, LocalizationStatus.ACCEPTED)
        self.assertEqual(normalized.authoritative_position_sat_px, (5.0, 6.0))
        self.assertIsNone(normalized.diagnostic_position_sat_px)

        headless = self.authority.normalize_legacy(
            {"status": "ok", "sat_coords": [5, 6], "heading": None}, policy()
        )
        self.assertEqual(headless.status, LocalizationStatus.ACCEPTED)
        self.assertEqual(headless.authoritative_position_sat_px, (5.0, 6.0))
        self.assertIsNone(headless.heading_deg)
        self.assertEqual(headless.heading_status, "ambiguous")

        no_coordinate = self.authority.normalize_legacy(
            {"status": "ok", "sat_coords": [math.nan, 6], "heading": 90}, policy()
        )
        self.assertEqual(no_coordinate.status, LocalizationStatus.REJECTED)
        self.assertEqual(no_coordinate.reason, LEGACY_STATUS_EVIDENCE_INSUFFICIENT)

    def test_unknown_legacy_status_never_infers_authority_from_other_fields(self):
        normalized = self.authority.normalize_legacy(
            {
                "status": "unknown",
                "usable": True,
                "authoritative_position_sat_px": (100.0, 200.0),
                "sat_coords": (7.0, 8.0),
                "heading": 180.0,
            },
            policy(),
        )
        self.assertFalse(normalized.usable)
        self.assertIsNone(normalized.authoritative_position_sat_px)
        self.assertEqual(normalized.diagnostic_position_sat_px, (7.0, 8.0))
        self.assertEqual(normalized.reason, LEGACY_STATUS_EVIDENCE_INSUFFICIENT)
        self.assertIsNone(self.authority.compatibility_mapping(normalized)["sat_coords"])

    def test_explicit_legacy_rejection_retains_only_finite_diagnostic_fit(self):
        finite = self.authority.normalize_legacy(
            {
                "status": "spread_rejected",
                "sat_coords": (7.0, 8.0),
                "heading": 30.0,
                "reason": "spread_rejected",
            },
            policy(),
        )
        self.assertEqual(finite.diagnostic_position_sat_px, (7.0, 8.0))
        self.assertIsNone(finite.authoritative_position_sat_px)

        non_finite = self.authority.normalize_legacy(
            {"status": "failed", "sat_coords": (math.nan, 8.0)}, policy()
        )
        self.assertIsNone(non_finite.diagnostic_position_sat_px)
        self.assertIsNone(self.authority.compatibility_mapping(non_finite)["sat_coords"])

    def test_ambiguous_legacy_policy_is_rejected(self):
        ambiguous = LegacyStatusPolicy(
            version="bad-frozen-policy",
            accepted_statuses=("same",),
            rejected_statuses=("same",),
        )
        with self.assertRaisesRegex(
            LocalizationAuthorityError, INCONSISTENT_COORDINATE_STATE
        ):
            self.authority.normalize_legacy(
                {"status": "same", "sat_coords": (1.0, 2.0), "heading": 0.0},
                ambiguous,
            )


if __name__ == "__main__":
    unittest.main()


class LegacyLocalizeV1PolicyTest(unittest.TestCase):
    """Requirements 1.19-1.20: the frozen legacy policy and its default application.

    The pre-2026-08-17 module had no default policy, so every real
    ``eval_haware_replay.py`` record read as "missing localization" and every
    scene bundle silently lost ``position_m``.
    """

    def setUp(self):
        self.authority = LocalizationAuthority()

    def test_legacy_localize_v1_is_a_frozen_module_constant(self):
        from trafficlab.motion.localization_authority import LEGACY_LOCALIZE_V1

        self.assertEqual(LEGACY_LOCALIZE_V1.version, "legacy-localize-v1")
        self.assertEqual(LEGACY_LOCALIZE_V1.accepted_statuses, ("ok",))
        self.assertEqual(
            set(LEGACY_LOCALIZE_V1.rejected_statuses),
            {
                "ambiguous_heading",
                "extrapolated",
                "failed_insufficient_kp",
                "pre_gate_near_horizon",
            },
        )
        self.assertEqual(
            LEGACY_LOCALIZE_V1.unknown_status_reason,
            LEGACY_STATUS_EVIDENCE_INSUFFICIENT,
        )
        # Content identity is derived, never stored as a field (a stored digest
        # would be circular); it must be stable across equal policies.
        self.assertEqual(
            LEGACY_LOCALIZE_V1.content_identity,
            LEGACY_LOCALIZE_V1.content_identity,
        )

    def test_legacy_ok_record_is_accepted_without_an_explicit_policy_argument(self):
        record = {"sat_coords": [100, 200], "heading": 45, "status": "ok"}

        self.assertEqual(authoritative_position(record), (100.0, 200.0))
        self.assertEqual(
            authority_status_reason(record), ("accepted", "legacy_status_policy")
        )
        self.assertIsNone(diagnostic_visualization_position(record))

    def test_legacy_ok_without_a_finite_heading_keeps_position_authority(self):
        """Requirement 1.19: this repository consumes only the position half."""
        for label, record in (
            ("nan heading", {"status": "ok", "sat_coords": [100, 200], "heading": math.nan}),
            ("absent heading", {"status": "ok", "sat_coords": [100, 200]}),
        ):
            with self.subTest(label):
                self.assertEqual(authoritative_position(record), (100.0, 200.0))
                normalized = self.authority.from_mapping(record)
                self.assertEqual(normalized.status, LocalizationStatus.ACCEPTED)
                self.assertIsNone(normalized.heading_deg)
                self.assertEqual(normalized.heading_status, "ambiguous")
                self.assertIsNone(normalized.diagnostic_position_sat_px)

    def test_legacy_extrapolated_maps_to_the_frozen_spread_rejected_reason(self):
        record = {
            "status": "extrapolated",
            "sat_coords": [100, 200],
            "heading": 45,
            "reason": "some_upstream_reason",
            "decisive_gate": "some_upstream_gate",
        }
        self.assertIsNone(authoritative_position(record))
        # The frozen policy wins over whatever the record claims for itself.
        self.assertEqual(authority_status_reason(record), ("rejected", "spread_rejected"))
        self.assertEqual(diagnostic_visualization_position(record), (100.0, 200.0))

    def test_legacy_pre_gate_near_horizon_retains_no_diagnostic_coordinate(self):
        for label, record in (
            ("no coordinate", {"status": "pre_gate_near_horizon", "sat_coords": None}),
            ("stray coordinate", {"status": "pre_gate_near_horizon", "sat_coords": [10, 20]}),
        ):
            with self.subTest(label):
                self.assertEqual(
                    authority_status_reason(record), ("rejected", "pre_gate_near_horizon")
                )
                self.assertIsNone(diagnostic_visualization_position(record))

    def test_statuses_without_position_evidence_share_one_decisive_reason(self):
        for status in ("failed_insufficient_kp", "ambiguous_heading", "totally_unknown", None):
            with self.subTest(status=status):
                record = {"sat_coords": [100, 200], "heading": 45}
                if status is not None:
                    record["status"] = status
                self.assertIsNone(authoritative_position(record))
                self.assertEqual(
                    authority_status_reason(record),
                    ("rejected", LEGACY_STATUS_EVIDENCE_INSUFFICIENT),
                )
                self.assertEqual(diagnostic_visualization_position(record), (100.0, 200.0))

    def test_legacy_ok_with_a_non_finite_coordinate_retains_no_diagnostic(self):
        record = {"status": "ok", "sat_coords": [math.nan, 200], "heading": 45}
        self.assertIsNone(authoritative_position(record))
        self.assertEqual(
            authority_status_reason(record), ("rejected", LEGACY_STATUS_EVIDENCE_INSUFFICIENT)
        )
        self.assertIsNone(diagnostic_visualization_position(record))

    def test_the_applied_legacy_policy_version_is_recorded(self):
        """Requirement 1.20: a consumer must record which policy it applied."""
        for record in (
            {"status": "ok", "sat_coords": [100, 200], "heading": 45},
            {"status": "extrapolated", "sat_coords": [100, 200]},
        ):
            with self.subTest(status=record["status"]):
                normalized = self.authority.from_mapping(record)
                self.assertEqual(
                    normalized.diagnostics.legacy_policy_version, "legacy-localize-v1"
                )
                mapping = self.authority.compatibility_mapping(normalized)
                self.assertEqual(mapping["legacy_policy_version"], "legacy-localize-v1")

    def test_export_sanitizer_applies_the_default_policy_to_legacy_records(self):
        rejected = sanitize_spatial_record_for_export(
            {"tracked_id": 2, "status": "extrapolated", "sat_coords": [3.0, 4.0], "position_m": [1, 2]}
        )
        self.assertIsNone(rejected["sat_coords"])
        self.assertIsNone(rejected["position_m"])

        accepted_record = sanitize_spatial_record_for_export(
            {"tracked_id": 2, "status": "ok", "sat_coords": [3.0, 4.0], "heading": 10.0}
        )
        self.assertEqual(accepted_record["sat_coords"], (3.0, 4.0))

    def test_a_record_with_no_localization_evidence_stays_missing(self):
        """A default policy must not turn "no record at all" into a rejection.

        ``{}`` carries neither new-contract fields nor legacy evidence, so it is
        a missing localization. A record that does carry legacy evidence (even
        with an absent status) is the policy's business.
        """
        self.assertIsNone(self.authority.from_mapping({}))
        self.assertEqual(authority_status_reason({}), ("missing", "missing_localization"))
        self.assertEqual(
            authority_status_reason({"tracked_id": 7, "class": "car"}),
            ("missing", "missing_localization"),
        )
        self.assertEqual(
            authority_status_reason({"sat_coords": [1, 2]}),
            ("rejected", LEGACY_STATUS_EVIDENCE_INSUFFICIENT),
        )
