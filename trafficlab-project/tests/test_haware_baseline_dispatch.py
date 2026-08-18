"""Golden and isolation tests for corrected frozen-baseline dispatch.

The JSON fixture is synthetic regression evidence only.  It is deliberately
marked as non-acceptance evidence and does not substitute for the externally
blocked two-site replay/ground-truth artifacts.
"""
from __future__ import annotations

from dataclasses import fields
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trafficlab.motion.haware_baseline_dispatch import (  # noqa: E402
    FrozenBaselineIdentity,
    HawareDispatchConfig,
    diagnostic_reprojection_baseline,
    localize_dispatch,
)
from trafficlab.motion.haware_localization import (  # noqa: E402
    HawareLocalizer,
    HawareResult,
    _FALLBACK_DIMS,
    build_car_template,
)
from tests.test_haware_localization import IdentityEngine, place_vehicle  # noqa: E402


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "haware_corrected_baseline_golden.json"


def circular_error(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


class CorrectedBaselineGoldenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.template = build_car_template(_FALLBACK_DIMS)

    def test_fixture_is_explicitly_non_acceptance_regression_evidence(self):
        self.assertEqual(self.fixture["fixture_kind"], "synthetic_regression_only")
        self.assertIs(self.fixture["acceptance_evidence"], False)

    def test_disabled_dispatch_matches_checked_in_corrected_baseline_goldens(self):
        self.assertEqual(
            self.fixture["legacy_schema"],
            [field.name for field in fields(HawareResult)],
        )
        config = HawareDispatchConfig(optimizer_disabled_selected=True)

        for case in self.fixture["cases"]:
            with self.subTest(case=case["id"]):
                localizer = HawareLocalizer(
                    IdentityEngine(),
                    self.template,
                    kp_conf=0.2,
                    max_spread_m=case["max_spread_m"],
                )
                keypoints = place_vehicle(
                    self.template,
                    case["center"],
                    case["heading"],
                    case["subset"],
                )
                direct = localizer.localize(keypoints)
                dispatched = localize_dispatch(keypoints, config, localizer)
                expected = case["expected"]

                self.assertEqual(dispatched, direct)
                self.assertEqual(dispatched.status, expected["status"])
                self.assertEqual(dispatched.n_keypoints, expected["n_keypoints"])
                self.assertEqual(dispatched.n_wheel_kp, expected["n_wheel_kp"])
                self.assertEqual(dispatched.method, expected["method"])
                self.assertEqual(dispatched.sat_coords is None, expected["sat_coords"] is None)
                self.assertEqual(dispatched.heading is None, expected["heading"] is None)
                if expected["sat_coords"] is not None:
                    for actual, golden in zip(dispatched.sat_coords, expected["sat_coords"]):
                        self.assertTrue(math.isfinite(actual))
                        self.assertLessEqual(abs(actual - golden), 1e-9)
                    self.assertTrue(math.isfinite(dispatched.heading))
                    self.assertLessEqual(circular_error(dispatched.heading, expected["heading"]), 1e-9)
                if "spread_m" in expected:
                    self.assertLessEqual(abs(dispatched.spread_m - expected["spread_m"]), 1e-9)

    def test_frozen_baselines_have_distinct_stable_identities(self):
        self.assertNotEqual(
            FrozenBaselineIdentity.CORRECTED_LOCALIZE,
            FrozenBaselineIdentity.DIAGNOSTIC_REPROJECTION,
        )


class DispatchIsolationTest(unittest.TestCase):
    def test_disabled_branch_returns_legacy_object_unchanged(self):
        sentinel = {
            "sat_coords": (float("nan"), float("inf")),
            "heading": float("nan"),
            "status": "legacy_non_finite",
            "reason": None,
        }

        class Legacy:
            def localize(self, keypoints):
                self.keypoints = keypoints
                return sentinel

            def localize_reprojection(self, keypoints):
                raise AssertionError("diagnostic baseline must not be called")

        legacy = Legacy()
        keypoints = object()
        result = localize_dispatch(
            keypoints,
            HawareDispatchConfig(optimizer_disabled_selected=True),
            legacy,
            optimizer_localize=lambda: self.fail("optimizer must not be called"),
        )
        self.assertIs(result, sentinel)
        self.assertIs(legacy.keypoints, keypoints)
        self.assertTrue(math.isnan(result["sat_coords"][0]))
        self.assertTrue(math.isinf(result["sat_coords"][1]))
        self.assertTrue(math.isnan(result["heading"]))
        self.assertIsNone(result["reason"])

    def test_optimizer_selection_calls_only_optimizer(self):
        class ForbiddenBaseline:
            def localize(self, keypoints):
                raise AssertionError("optimizer selection reached corrected baseline")

            def localize_reprojection(self, keypoints):
                raise AssertionError("optimizer selection reached diagnostic baseline")

        optimizer_result = object()
        result = localize_dispatch(
            object(),
            HawareDispatchConfig(optimizer_disabled_selected=False),
            ForbiddenBaseline(),
            optimizer_localize=lambda: optimizer_result,
        )
        self.assertIs(result, optimizer_result)

    def test_optimizer_selection_never_falls_back_to_a_baseline(self):
        class ForbiddenBaseline:
            def localize(self, keypoints):
                raise AssertionError("baseline fallback is forbidden")

            def localize_reprojection(self, keypoints):
                raise AssertionError("diagnostic fallback is forbidden")

        with self.assertRaisesRegex(RuntimeError, "without an optimizer entry point"):
            localize_dispatch(
                object(),
                HawareDispatchConfig(optimizer_disabled_selected=False),
                ForbiddenBaseline(),
            )

    def test_reprojection_is_only_an_explicit_diagnostic_call(self):
        diagnostic_result = object()

        class DiagnosticLegacy:
            def localize(self, keypoints):
                raise AssertionError("corrected baseline must not be called")

            def localize_reprojection(self, keypoints):
                self.keypoints = keypoints
                return diagnostic_result

        legacy = DiagnosticLegacy()
        keypoints = object()
        self.assertIs(diagnostic_reprojection_baseline(legacy, keypoints), diagnostic_result)
        self.assertIs(legacy.keypoints, keypoints)

    def test_dispatch_flag_requires_an_actual_bool(self):
        with self.assertRaisesRegex(TypeError, "must be a bool"):
            HawareDispatchConfig(optimizer_disabled_selected=1)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
