"""Property 19: disabled mode preserves the corrected baseline exactly."""
from __future__ import annotations

from dataclasses import fields, is_dataclass
import hashlib
import json
import math
from pathlib import Path
import unittest

from hypothesis import given, strategies as st

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.test_haware_localization import IdentityEngine, place_vehicle
from trafficlab.motion.haware_baseline_dispatch import (
    FrozenBaselineIdentity,
    HawareDispatchConfig,
    localize_dispatch,
)
from trafficlab.motion.haware_localization import (
    HawareLocalizer,
    HawareResult,
    _FALLBACK_DIMS,
    build_car_template,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "haware_corrected_baseline_golden.json"
)
_FIXTURE_BYTES = FIXTURE_PATH.read_bytes()
_FIXTURE = json.loads(_FIXTURE_BYTES.decode("utf-8"))
_TEMPLATE = build_car_template(_FALLBACK_DIMS)
_INVENTORY = tuple(
    [("baseline", index) for index in range(len(_FIXTURE["cases"]))]
    + [
        ("classification", index)
        for index in range(len(_FIXTURE["classification_cases"]))
    ]
)


def _number_class(value: float) -> str:
    value = float(value)
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "positive_infinity" if value > 0.0 else "negative_infinity"
    return "finite"


def _fingerprint(value):
    """Compare every legacy value exactly while making NaN equality meaningful."""
    if is_dataclass(value):
        return tuple(
            (item.name, _fingerprint(getattr(value, item.name)))
            for item in fields(value)
        )
    if isinstance(value, float):
        classification = _number_class(value)
        return (classification, value) if classification == "finite" else (classification,)
    if isinstance(value, dict):
        return tuple(
            (str(key), _fingerprint(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (tuple, list)):
        return tuple(_fingerprint(item) for item in value)
    return value


def _circular_error(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _forbidden_optimizer():
    raise AssertionError("optimizer must remain isolated from disabled dispatch")


def _assert_schema_reason_and_exact_dispatch(direct, dispatched) -> None:
    assert type(dispatched) is HawareResult
    assert [item.name for item in fields(dispatched)] == _FIXTURE["legacy_schema"]
    reason_contract = _FIXTURE["parity_contract"]["reason"]
    assert hasattr(dispatched, "reason") is reason_contract["present"]
    assert _fingerprint(dispatched) == _fingerprint(direct)


def _check_baseline_case(case) -> None:
    expected = case["expected"]
    direct_localizer = HawareLocalizer(
        IdentityEngine(),
        _TEMPLATE,
        kp_conf=0.2,
        max_spread_m=case["max_spread_m"],
    )
    keypoints = place_vehicle(
        _TEMPLATE, case["center"], case["heading"], case["subset"]
    )
    direct = direct_localizer.localize(keypoints)

    dispatch_localizer = HawareLocalizer(
        IdentityEngine(),
        _TEMPLATE,
        kp_conf=0.2,
        max_spread_m=case["max_spread_m"],
    )
    dispatched = localize_dispatch(
        keypoints,
        HawareDispatchConfig(optimizer_disabled_selected=True),
        dispatch_localizer,
        optimizer_localize=_forbidden_optimizer,
    )
    _assert_schema_reason_and_exact_dispatch(direct, dispatched)

    assert dispatched.status == expected["status"]
    assert dispatched.n_keypoints == expected["n_keypoints"]
    assert dispatched.n_wheel_kp == expected["n_wheel_kp"]
    assert dispatched.method is expected["method"]
    assert (dispatched.sat_coords is None) is (expected["sat_coords"] is None)
    assert (dispatched.heading is None) is (expected["heading"] is None)

    if expected["sat_coords"] is not None:
        tolerance = _FIXTURE["parity_contract"]["coordinate_abs_tolerance"]
        assert all(_number_class(value) == "finite" for value in dispatched.sat_coords)
        for actual, golden in zip(dispatched.sat_coords, expected["sat_coords"]):
            assert abs(actual - golden) <= tolerance
        heading_tolerance = _FIXTURE["parity_contract"][
            "heading_circular_abs_tolerance"
        ]
        assert _number_class(dispatched.heading) == "finite"
        assert _circular_error(dispatched.heading, expected["heading"]) <= heading_tolerance
    if "spread_m" in expected:
        assert abs(dispatched.spread_m - expected["spread_m"]) <= 1e-9


def _decode_number(value):
    if not isinstance(value, str):
        return value
    return {
        "nan": float("nan"),
        "positive_infinity": float("inf"),
        "negative_infinity": float("-inf"),
    }[value]


def _non_finite_result(raw) -> HawareResult:
    return HawareResult(
        sat_coords=tuple(_decode_number(value) for value in raw["sat_coords"]),
        heading=_decode_number(raw["heading"]),
        confidence=_decode_number(raw["confidence"]),
        n_keypoints=raw["n_keypoints"],
        status=raw["status"],
        p_sat={
            int(key): tuple(_decode_number(value) for value in pair)
            for key, pair in raw["p_sat"].items()
        },
        spread_m=_decode_number(raw["spread_m"]),
        n_wheel_kp=raw["n_wheel_kp"],
        method=raw["method"],
    )


def _check_classification_case(case) -> None:
    raw = case["expected"]
    direct = _non_finite_result(raw)

    class FrozenFixtureBaseline:
        def localize(self, keypoints):
            self.received = keypoints
            return direct

        def localize_reprojection(self, keypoints):
            raise AssertionError("diagnostic baseline must remain isolated")

    keypoints = object()
    localizer = FrozenFixtureBaseline()
    dispatched = localize_dispatch(
        keypoints,
        HawareDispatchConfig(optimizer_disabled_selected=True),
        localizer,
        optimizer_localize=_forbidden_optimizer,
    )
    assert dispatched is direct
    assert localizer.received is keypoints
    _assert_schema_reason_and_exact_dispatch(direct, dispatched)

    assert tuple(_number_class(value) for value in dispatched.sat_coords) == tuple(
        raw["sat_coords"]
    )
    assert _number_class(dispatched.heading) == raw["heading"]
    assert _number_class(dispatched.confidence) == raw["confidence"]
    assert _number_class(dispatched.spread_m) == raw["spread_m"]
    assert {
        str(key): tuple(_number_class(value) for value in pair)
        for key, pair in dispatched.p_sat.items()
    } == {key: tuple(pair) for key, pair in raw["p_sat"].items()}
    assert dispatched.status == raw["status"]
    assert dispatched.method is None


# Feature: haware-localization-accuracy, Property 19: Disabled mode preserves the corrected baseline exactly
@deterministic_property(19)
@given(case_order=st.permutations(_INVENTORY))
def test_disabled_mode_preserves_corrected_baseline_exactly(case_order) -> None:
    """**Validates: Requirements 1.13-1.15, 12.6**"""
    record_failure_metadata(
        replay_identity=hashlib.sha256(_FIXTURE_BYTES).hexdigest(),
        profile_identity=FrozenBaselineIdentity.CORRECTED_LOCALIZE.value,
        run_identity="|".join(f"{kind}:{index}" for kind, index in case_order),
    )
    for kind, index in case_order:
        if kind == "baseline":
            _check_baseline_case(_FIXTURE["cases"][index])
        else:
            _check_classification_case(_FIXTURE["classification_cases"][index])


class DisabledModeCorrectedBaselineParityPropertyTest(unittest.TestCase):
    def test_property_19(self) -> None:
        test_disabled_mode_preserves_corrected_baseline_exactly()


if __name__ == "__main__":
    unittest.main()
