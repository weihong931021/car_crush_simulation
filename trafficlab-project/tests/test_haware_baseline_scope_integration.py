"""Integration and static scope checks for frozen Haware dispatch.

These tests use synthetic regression goldens only; they are not acceptance
site evidence and cannot authorize optimizer production dispatch.
"""
from __future__ import annotations

import ast
from dataclasses import fields, replace
import json
import math
from pathlib import Path
import re
import sys
import unittest

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from trafficlab.motion.haware_accuracy.models import (  # noqa: E402
    ContentIdentity,
    DecisionStatus,
    SiteDecision,
)
from trafficlab.motion.haware_accuracy.validation import (  # noqa: E402
    DEFERRED_CAPABILITIES,
    DispatchAuthorization,
    ProfileValidationError,
    resolve_optimizer_dispatch,
    validate_before_read,
)
from trafficlab.motion.haware_baseline_dispatch import (  # noqa: E402
    HawareDispatchConfig,
    localize_dispatch,
)
from trafficlab.motion.haware_localization import (  # noqa: E402
    HawareLocalizer,
    HawareResult,
    _FALLBACK_DIMS,
    build_car_template,
)
from tests.test_haware_localization import IdentityEngine, place_vehicle  # noqa: E402
from tests.test_haware_profile_validation import profile, scope  # noqa: E402

FIXTURE_PATH = PROJECT_ROOT / "tests/fixtures/haware_corrected_baseline_golden.json"
ADAPTER_PATH = Path("trafficlab/inference/pifpaf_haware_adapter.py")


def _circular_error(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _classified(value):
    if isinstance(value, np.ndarray):
        return [_classified(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): _classified(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_classified(item) for item in value]
    if isinstance(value, (float, np.floating)):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "positive_infinity" if value > 0 else "negative_infinity"
        return float(value)
    return value


def _authorization(candidate, decisions, *, reviewed=False, authorized=False):
    return DispatchAuthorization(
        candidate_identity=candidate,
        held_out_site_decisions=decisions,
        hardening_reviewed=reviewed,
        hardening_authorized=authorized,
        hardening_candidate_identity=candidate if reviewed else None,
        hardening_scope=("optimizer_disabled_mode_parity",) if reviewed else (),
    )


def _production_sources():
    return tuple(sorted((PROJECT_ROOT / "trafficlab").rglob("*.py"))) + tuple(
        sorted((PROJECT_ROOT / "scripts").rglob("*.py"))
    )


def _absolute_imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


class BaselineDispatchIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.template = build_car_template(_FALLBACK_DIMS)

    def test_default_off_guard_dispatches_every_corrected_baseline_golden(self):
        candidate = ContentIdentity.for_bytes(b"candidate")
        guard = resolve_optimizer_dispatch(candidate)
        self.assertFalse(guard.optimizer_enabled)
        self.assertEqual(guard.production_path, "corrected_legacy_baseline")
        self.assertEqual(guard.optimizer_output_role, "diagnostic_only")
        self.assertEqual([field.name for field in fields(HawareResult)], self.fixture["legacy_schema"])

        for case in self.fixture["cases"]:
            with self.subTest(case=case["id"]):
                localizer = HawareLocalizer(
                    IdentityEngine(), self.template, kp_conf=0.2,
                    max_spread_m=case["max_spread_m"],
                )
                keypoints = place_vehicle(
                    self.template, case["center"], case["heading"], case["subset"],
                )
                result = localize_dispatch(
                    keypoints,
                    HawareDispatchConfig(optimizer_disabled_selected=not guard.optimizer_enabled),
                    localizer,
                    optimizer_localize=lambda: self.fail("default-off dispatch reached optimizer"),
                )
                expected = case["expected"]
                self.assertEqual(result.status, expected["status"])
                self.assertEqual(result.n_keypoints, expected["n_keypoints"])
                self.assertEqual(result.n_wheel_kp, expected["n_wheel_kp"])
                self.assertEqual(result.method, expected["method"])
                self.assertEqual(result.sat_coords is None, expected["sat_coords"] is None)
                self.assertEqual(result.heading is None, expected["heading"] is None)
                if expected["sat_coords"] is not None:
                    for actual, golden in zip(result.sat_coords, expected["sat_coords"]):
                        self.assertLessEqual(abs(actual - golden), 1e-9)
                    self.assertLessEqual(_circular_error(result.heading, expected["heading"]), 1e-9)

    def test_disabled_dispatch_preserves_non_finite_golden_classifications(self):
        expected = self.fixture["classification_cases"][0]["expected"]
        legacy_result = HawareResult(
            sat_coords=(float("nan"), float("inf")),
            heading=float("-inf"),
            confidence=float("nan"),
            n_keypoints=2,
            status="extrapolated",
            p_sat={0: np.asarray((float("nan"), float("-inf")))},
            spread_m=float("inf"),
            n_wheel_kp=0,
            method=None,
        )

        class Legacy:
            def localize(self, keypoints):
                return legacy_result

            def localize_reprojection(self, keypoints):
                raise AssertionError("diagnostic baseline must remain isolated")

        result = localize_dispatch(object(), HawareDispatchConfig(), Legacy())
        self.assertIs(result, legacy_result)
        actual = {field.name: _classified(getattr(result, field.name)) for field in fields(result)}
        self.assertEqual(actual, expected)

    def test_optimizer_remains_diagnostic_without_dual_site_go_and_hardening(self):
        candidate = ContentIdentity.for_bytes(b"exact-candidate")
        go = DecisionStatus.GO
        blocked = (
            ("no_authorization", None, "optimizer_default_off"),
            ("one_site", _authorization(candidate, (SiteDecision(site="kee-cc", status=go),)),
             "dual_site_held_out_go_missing"),
            ("site_no_go", _authorization(candidate, (
                SiteDecision(site="kee-cc", status=go),
                SiteDecision(site="taoyuan-tc", status=DecisionStatus.NO_GO),
            )), "dual_site_held_out_go_missing"),
            ("no_hardening", _authorization(candidate, (
                SiteDecision(site="kee-cc", status=go),
                SiteDecision(site="taoyuan-tc", status=go),
            )), "hardening_authorization_incomplete"),
            ("hardening_not_authorized", _authorization(candidate, (
                SiteDecision(site="kee-cc", status=go),
                SiteDecision(site="taoyuan-tc", status=go),
            ), reviewed=True, authorized=False), "hardening_authorization_incomplete"),
        )
        for label, authorization, reason in blocked:
            with self.subTest(label=label):
                guard = resolve_optimizer_dispatch(candidate, authorization)
                self.assertFalse(guard.optimizer_enabled)
                self.assertEqual(guard.production_path, "corrected_legacy_baseline")
                self.assertEqual(guard.optimizer_output_role, "diagnostic_only")
                self.assertEqual(guard.reason, reason)


class StaticProductionScopeTest(unittest.TestCase):
    def test_legacy_root_trees_are_import_and_write_protected(self):
        """production 程式碼不得 import 或寫入 pifpaf/ 與 location/ 這兩棵舊樹。

        2026-08-20 目錄重整已刪除這兩棵頂層樹（location/ 的 11 個追蹤檔與 4 支 footage
        都與 trafficlab-project/location/ 逐位元相同；pifpaf/ 的 3 支是缺 spread 邊界
        修正的過時副本）。原本這裡先斷言兩棵樹存在，樹刪掉後那兩行必然失敗，已移除。
        守衛本身保留——它防的是「未來有人重新引入這種相依」，樹存不存在不影響這個目的。
        """
        forbidden_imports = []
        literal_writes = []
        write_methods = {"write_bytes", "write_text"}
        for path in _production_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            for module in _absolute_imports(tree):
                if module == "pifpaf" or module.startswith("pifpaf.") or module == "location" or module.startswith("location."):
                    forbidden_imports.append((relative, module))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in write_methods or not node.args:
                    continue
                target = node.args[0].value if isinstance(node.args[0], ast.Constant) else None
                if isinstance(target, str) and target.replace("\\", "/").lstrip("./").startswith(("pifpaf/", "location/")):
                    literal_writes.append((relative, target))
        self.assertEqual(forbidden_imports, [])
        self.assertEqual(literal_writes, [])

    def test_exactly_one_pifpaf_adapter_and_provider_import_boundary(self):
        adapter_definitions = []
        provider_import_files = set()
        for path in _production_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            relative = path.relative_to(PROJECT_ROOT)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "PifPafObservationAdapter":
                    adapter_definitions.append(relative)
            if any(name == "openpifpaf" or name.startswith("openpifpaf.")
                   for name in _absolute_imports(tree)):
                provider_import_files.add(relative)
        self.assertEqual(adapter_definitions, [ADAPTER_PATH])
        self.assertEqual(provider_import_files, {ADAPTER_PATH})

        for path in (
            PROJECT_ROOT / "trafficlab/motion/haware_optimizer.py",
            PROJECT_ROOT / "trafficlab/motion/haware_hypotheses.py",
            PROJECT_ROOT / "trafficlab/projection/haware_forward.py",
        ):
            text = path.read_text(encoding="utf-8").casefold()
            self.assertNotIn("openpifpaf", text)
            self.assertNotIn("pifpaf_haware_adapter", text)

    def test_baselines_are_isolated_from_optimizer_and_result_mapping(self):
        optimizer_graph = (
            PROJECT_ROOT / "trafficlab/motion/haware_optimizer.py",
            PROJECT_ROOT / "trafficlab/motion/haware_hypotheses.py",
            PROJECT_ROOT / "trafficlab/projection/haware_forward.py",
        )
        for path in optimizer_graph:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("haware_localization", text)
            self.assertNotIn("haware_baseline_dispatch", text)
            self.assertNotIn("localize_reprojection", text)

        dispatch_path = PROJECT_ROOT / "trafficlab/motion/haware_baseline_dispatch.py"
        tree = ast.parse(dispatch_path.read_text(encoding="utf-8"), filename=str(dispatch_path))
        imports = set(_absolute_imports(tree))
        self.assertFalse(any(name.startswith("trafficlab.") for name in imports))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        corrected_calls = [node for node in ast.walk(functions["corrected_legacy_baseline"])
                           if isinstance(node, ast.Call)]
        diagnostic_calls = [node for node in ast.walk(functions["diagnostic_reprojection_baseline"])
                            if isinstance(node, ast.Call)]
        self.assertEqual([call.func.attr for call in corrected_calls if isinstance(call.func, ast.Attribute)], ["localize"])
        self.assertEqual([call.func.attr for call in diagnostic_calls if isinstance(call.func, ast.Attribute)], ["localize_reprojection"])

    def test_every_deferred_capability_is_guarded_and_has_no_implementation_symbol(self):
        expected = {
            "detector_replacement", "detector_retraining",
            "generalized_learned_reliability", "full_multi_provider_schema_platform",
            "exhaustive_artifact_management", "calibration_identification",
            "calibration_re_estimation", "temporal_fusion", "multi_sensor_fusion",
            "selective_risk_acceptance",
        }
        self.assertEqual(DEFERRED_CAPABILITIES, expected)
        base_scope = scope()
        self.assertEqual(base_scope.enabled_deferred_capabilities, ())
        self.assertEqual(base_scope.selective_risk_role, "diagnostic_only")
        validate_before_read(profile(), base_scope)
        for capability in sorted(expected):
            with self.subTest(capability=capability):
                with self.assertRaises(ProfileValidationError) as raised:
                    validate_before_read(
                        profile(),
                        replace(base_scope, enabled_deferred_capabilities=(capability,)),
                    )
                self.assertEqual(raised.exception.code, "deferred_capability_enabled")

        implementations = []
        for path in (PROJECT_ROOT / "trafficlab").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", node.name).casefold()
                    if normalized in expected:
                        implementations.append((path.relative_to(PROJECT_ROOT).as_posix(), node.name))
        self.assertEqual(implementations, [])


if __name__ == "__main__":
    unittest.main()
