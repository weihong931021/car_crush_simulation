"""Property 16: pilot accounting and decision rules use fixed evidence."""
from __future__ import annotations

from dataclasses import dataclass, replace
import itertools
import math
from statistics import NormalDist
import unittest

from hypothesis import given, strategies as st

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.test_haware_pilot_statistics import (
    accepted,
    acceptance_profile,
    mvp_scope,
    rejected,
    statistics_fixture,
)
from trafficlab.measurement.haware_pilot import (
    ACCEPTANCE_SITES,
    MEDIAN_ERROR_EFFECT,
    P90_ERROR_EFFECT,
    USABLE_COVERAGE_EFFECT,
    PilotArm,
    compute_pilot_statistics,
    decide_pilot_feasibility,
    load_current_evidence_report,
    run_frozen_pilot_arms,
)
from trafficlab.motion.haware_accuracy.models import (
    ContentIdentity,
    DecisionStatus,
    SeedClass,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read


_EFFECTS = (MEDIAN_ERROR_EFFECT, P90_ERROR_EFFECT, USABLE_COVERAGE_EFFECT)
_FROZEN = statistics_fixture()
_SCOPE = mvp_scope()
_PROFILES = {site: acceptance_profile(site) for site in ACCEPTANCE_SITES}
_TOKENS = {
    site: validate_before_read(profile, _SCOPE)
    for site, profile in _PROFILES.items()
}
_DETECTIONS = tuple(
    detection
    for site in ACCEPTANCE_SITES
    for detection in _FROZEN.for_site(site).eligible_detections
)
_KEYS = tuple(
    (item.record.site, item.record.frame_id, item.record.detection_id)
    for item in _DETECTIONS
)


@dataclass(frozen=True)
class PairedOutcome:
    baseline_accepted: bool
    candidate_accepted: bool
    baseline_delta_m: tuple[float, float]
    candidate_delta_m: tuple[float, float]
    seed_class: SeedClass


@dataclass(frozen=True)
class SiteRuleState:
    sufficient: bool
    sufficiency_gaps: tuple[str, ...]
    median_estimate_passes: bool
    median_interval_passes: bool
    p90_estimate_passes: bool
    p90_interval_passes: bool
    coverage_estimate_passes: bool
    coverage_interval_passes: bool


@dataclass(frozen=True)
class PilotCase:
    outcomes: tuple[PairedOutcome, ...]
    site_rules: tuple[SiteRuleState, SiteRuleState]


def _delta_strategy():
    # Division by seven deliberately produces non-round decimal binary floats.
    return st.tuples(
        st.integers(min_value=-35, max_value=35).map(lambda value: value / 7.0),
        st.integers(min_value=-35, max_value=35).map(lambda value: value / 7.0),
    )


@st.composite
def pilot_cases(draw):
    outcomes = tuple(draw(st.lists(
        st.builds(
            PairedOutcome,
            baseline_accepted=st.booleans(),
            candidate_accepted=st.booleans(),
            baseline_delta_m=_delta_strategy(),
            candidate_delta_m=_delta_strategy(),
            seed_class=st.sampled_from(tuple(SeedClass)),
        ),
        min_size=len(_DETECTIONS),
        max_size=len(_DETECTIONS),
    )))
    rule_states = []
    for site_index in range(len(ACCEPTANCE_SITES)):
        sufficient = draw(st.booleans())
        gaps = () if sufficient else tuple(draw(st.lists(
            st.from_regex(f"site_{site_index}_gap_[a-z]{{1,5}}", fullmatch=True),
            min_size=0,
            max_size=3,
            unique=True,
        )))
        rule_states.append(SiteRuleState(
            sufficient=sufficient,
            sufficiency_gaps=gaps,
            median_estimate_passes=draw(st.booleans()),
            median_interval_passes=draw(st.booleans()),
            p90_estimate_passes=draw(st.booleans()),
            p90_interval_passes=draw(st.booleans()),
            coverage_estimate_passes=draw(st.booleans()),
            coverage_interval_passes=draw(st.booleans()),
        ))
    return PilotCase(outcomes=outcomes, site_rules=tuple(rule_states))


def _case_runs(case: PilotCase):
    by_key = dict(zip(_KEYS, case.outcomes))
    detection_by_key = dict(zip(_KEYS, _DETECTIONS))

    def position(record, delta):
        key = (record.site, record.frame_id, record.detection_id)
        detection = detection_by_key[key]
        scale = _PROFILES[record.site].calibration.snapshot.pixels_per_metre
        gt_x, gt_y = detection.ground_truth.metric_coordinate_m
        return ((gt_x + delta[0]) * scale, (gt_y + delta[1]) * scale)

    def baseline(record):
        spec = by_key[(record.site, record.frame_id, record.detection_id)]
        if not spec.baseline_accepted:
            return {"status": "rejected", "sat_coords": None, "heading": None}
        return {
            "status": "ok",
            "sat_coords": position(record, spec.baseline_delta_m),
            "heading": 0.0,
        }

    def optimizer(record, _profile, _configuration, _identity):
        spec = by_key[(record.site, record.frame_id, record.detection_id)]
        if not spec.candidate_accepted:
            return rejected()
        return accepted(position(record, spec.candidate_delta_m), spec.seed_class)

    return run_frozen_pilot_arms(
        frozen_evidence=_FROZEN,
        outcome_access=_FROZEN.outcome_access,
        profiles=_PROFILES,
        validated_profiles=_TOKENS,
        scope=_SCOPE,
        replay_identities={
            "kee-cc": ContentIdentity("c" * 64),
            "taoyuan-tc": ContentIdentity("d" * 64),
        },
        template_identity=ContentIdentity("e" * 64),
        code_revision="property-16",
        runtime_dependencies=(ContentIdentity("f" * 64),),
        baseline_localize=baseline,
        optimizer_localize=optimizer,
    )


def _nearest_rank(values, probability):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[max(1, math.ceil(probability * len(ordered))) - 1]


def _median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _reference_metrics(indices, specs, detections, scale, candidate):
    errors = []
    accepted_count = 0
    for index in indices:
        spec = specs[index]
        is_accepted = spec.candidate_accepted if candidate else spec.baseline_accepted
        if not is_accepted:
            continue
        accepted_count += 1
        delta = spec.candidate_delta_m if candidate else spec.baseline_delta_m
        gt_x, gt_y = detections[index].ground_truth.metric_coordinate_m
        x_px, y_px = (gt_x + delta[0]) * scale, (gt_y + delta[1]) * scale
        errors.append(math.hypot(x_px / scale - gt_x, y_px / scale - gt_y))
    denominator = len(indices)
    return {
        "accepted": accepted_count,
        "errors": tuple(errors),
        "median": _median(errors),
        "p90": _nearest_rank(errors, 0.90),
        "coverage": accepted_count / denominator if denominator else 0.0,
    }


def _effect(candidate, baseline, name):
    if name == MEDIAN_ERROR_EFFECT:
        values = candidate["median"], baseline["median"]
    elif name == P90_ERROR_EFFECT:
        values = candidate["p90"], baseline["p90"]
    else:
        return candidate["coverage"] - baseline["coverage"]
    return None if None in values else values[0] - values[1]


def _sample_variance(values):
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _reference_interval(name, estimate, specs, detections, scale, method):
    by_track = {}
    for index, detection in enumerate(detections):
        by_track.setdefault(detection.real_track_id, []).append(index)
    tracks = tuple(sorted(by_track))
    if len(tracks) < method.minimum_analyzable_clusters or estimate is None:
        return {
            "status": DecisionStatus.INSUFFICIENT_DATA,
            "estimate": estimate,
            "lower": None,
            "upper": None,
            "variance": None,
            "clusters": len(tracks),
            "replicates": 0,
        }
    if len(tracks) ** len(tracks) <= method.bootstrap_replicates:
        samples = itertools.product(tracks, repeat=len(tracks))
    else:  # This fixture stays exhaustive; fail rather than copy production RNG.
        raise AssertionError("Property 16 reference fixture exceeded exhaustive bootstrap")
    effects = []
    for sample in samples:
        indices = tuple(index for track in sample for index in by_track[track])
        baseline = _reference_metrics(indices, specs, detections, scale, False)
        candidate = _reference_metrics(indices, specs, detections, scale, True)
        value = _effect(candidate, baseline, name)
        if value is not None:
            effects.append(value)
    if len(effects) < 2:
        return {
            "status": DecisionStatus.INSUFFICIENT_DATA,
            "estimate": estimate,
            "lower": None,
            "upper": None,
            "variance": None,
            "clusters": len(tracks),
            "replicates": len(effects),
        }
    tail = (1.0 - method.confidence_level) / 2.0
    return {
        "status": DecisionStatus.GO,
        "estimate": estimate,
        "lower": _nearest_rank(effects, tail),
        "upper": _nearest_rank(effects, 1.0 - tail),
        "variance": _sample_variance(effects),
        "clusters": len(tracks),
        "replicates": len(effects),
    }


def _reference_power(effects, intervals, detections, method):
    tracks = len({item.real_track_id for item in detections})
    sample_count = len(detections)
    gt_noise = sum(item.ground_truth.uncertainty_m ** 2 for item in detections) / sample_count
    z_alpha = NormalDist().inv_cdf(1.0 - (1.0 - method.confidence_level) / 2.0)
    z_power = NormalDist().inv_cdf(method.target_power)
    required_tracks = []
    achieved_powers = []
    gaps = []
    for name in _EFFECTS:
        interval = intervals[name]
        effect = effects[name]
        signal = max(0.0, effect or 0.0)
        if name != USABLE_COVERAGE_EFFECT and effect is not None:
            signal = max(0.0, -effect)
        variance = interval["variance"]
        if interval["status"] is not DecisionStatus.GO or variance is None:
            gaps.append(f"{name}:clustered_interval_unavailable")
            continue
        if name != USABLE_COVERAGE_EFFECT:
            variance += gt_noise
        if signal <= 0.0:
            gaps.append(f"{name}:no_observed_directional_effect")
            continue
        if variance <= 0.0:
            required, achieved = method.minimum_analyzable_clusters, 1.0
        else:
            required = max(
                method.minimum_analyzable_clusters,
                math.ceil(((z_alpha + z_power) ** 2) * variance / signal ** 2),
            )
            achieved = NormalDist().cdf(
                math.sqrt(tracks) * signal / math.sqrt(variance) - z_alpha
            )
        required_tracks.append(required)
        achieved_powers.append(achieved)
    view_counts = {}
    for detection in detections:
        view_counts[detection.independent_view_id] = (
            view_counts.get(detection.independent_view_id, 0) + 1
        )
    if len(required_tracks) != len(_EFFECTS):
        return {
            "status": DecisionStatus.INSUFFICIENT_DATA,
            "achieved": min(achieved_powers) if achieved_powers else None,
            "required_samples": None,
            "required_tracks": None,
            "required_views": tuple((view, count, 0) for view, count in sorted(view_counts.items())),
            "gaps": tuple(sorted(set(gaps))),
        }
    required_track_count = max(required_tracks)
    required_sample_count = math.ceil(sample_count * required_track_count / tracks)
    required_views = tuple(
        (view, count, math.ceil(required_sample_count * count / sample_count))
        for view, count in sorted(view_counts.items())
    )
    if tracks < required_track_count:
        gaps.append("genuine_track_coverage_below_power_requirement")
    if sample_count < required_sample_count:
        gaps.append("eligible_sample_coverage_below_power_requirement")
    if any(observed < required for _, observed, required in required_views):
        gaps.append("independent_view_coverage_below_power_requirement")
    achieved = min(achieved_powers)
    if achieved < method.target_power:
        gaps.append("achieved_power_below_frozen_target")
    return {
        "status": DecisionStatus.GO if not gaps else DecisionStatus.INSUFFICIENT_DATA,
        "achieved": achieved,
        "required_samples": required_sample_count,
        "required_tracks": required_track_count,
        "required_views": required_views,
        "gaps": tuple(sorted(set(gaps))),
    }


def _assert_optional_close(actual, expected):
    if expected is None:
        assert actual is None
    else:
        assert actual is not None and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


def _assert_accounting(case, statistics):
    offset = 0
    for site in ACCEPTANCE_SITES:
        detections = _FROZEN.for_site(site).eligible_detections
        specs = case.outcomes[offset:offset + len(detections)]
        offset += len(detections)
        scale = _PROFILES[site].calibration.snapshot.pixels_per_metre
        method = statistics.method.for_site(site)
        baseline = _reference_metrics(tuple(range(len(detections))), specs, detections, scale, False)
        candidate = _reference_metrics(tuple(range(len(detections))), specs, detections, scale, True)
        effects = {name: _effect(candidate, baseline, name) for name in _EFFECTS}
        intervals = {
            name: _reference_interval(name, effects[name], specs, detections, scale, method)
            for name in _EFFECTS
        }
        report = statistics.for_site(site).for_arm(PilotArm.FULL_OPTIMIZER)
        assert report.pilot_denominator == len(detections) == 4
        assert report.accepted_count == candidate["accepted"]
        assert report.rejected_count == len(detections) - candidate["accepted"]
        assert report.unrounded_planar_errors_m == candidate["errors"]
        _assert_optional_close(report.median_error_m, candidate["median"])
        _assert_optional_close(report.p90_error_m, candidate["p90"])
        assert report.usable_coverage == candidate["coverage"]
        for name, actual in report.signed_effects:
            _assert_optional_close(actual, effects[name])
        for name, actual in report.effect_intervals:
            expected = intervals[name]
            assert actual.status is expected["status"]
            _assert_optional_close(actual.estimate, expected["estimate"])
            _assert_optional_close(actual.lower, expected["lower"])
            _assert_optional_close(actual.upper, expected["upper"])
            _assert_optional_close(actual.bootstrap_variance, expected["variance"])
            assert actual.cluster_count == expected["clusters"]
            assert actual.replicate_count == expected["replicates"]

        assert report.genuine_track_count == len({item.real_track_id for item in detections})
        assert report.selected_seed_provenance.wheel == sum(
            spec.candidate_accepted and spec.seed_class is SeedClass.WHEEL for spec in specs
        )
        assert report.selected_seed_provenance.non_wheel == sum(
            spec.candidate_accepted and spec.seed_class is SeedClass.NON_WHEEL for spec in specs
        )
        assert report.selected_seed_provenance.unavailable == sum(
            not spec.candidate_accepted for spec in specs
        )
        for coverage in report.independent_view_coverage:
            indices = tuple(
                index for index, detection in enumerate(detections)
                if detection.independent_view_id == coverage.view_id
            )
            accepted_count = sum(specs[index].candidate_accepted for index in indices)
            assert coverage.eligible_count == len(indices)
            assert coverage.accepted_count == accepted_count
            assert coverage.usable_coverage == accepted_count / len(indices)
        uncertainty = tuple(sorted(item.ground_truth.uncertainty_m for item in detections))
        assert report.ground_truth_uncertainty.values == uncertainty
        assert report.ground_truth_uncertainty.median == _median(uncertainty)
        assert report.ground_truth_uncertainty.p90 == _nearest_rank(uncertainty, 0.90)

        thresholds = report.candidate_thresholds
        assert thresholds is not None
        _assert_optional_close(
            thresholds.maximum_median_error_m,
            None if baseline["median"] is None or intervals[MEDIAN_ERROR_EFFECT]["upper"] is None
            else baseline["median"] + intervals[MEDIAN_ERROR_EFFECT]["upper"],
        )
        _assert_optional_close(
            thresholds.maximum_p90_error_m,
            None if baseline["p90"] is None or intervals[P90_ERROR_EFFECT]["upper"] is None
            else baseline["p90"] + intervals[P90_ERROR_EFFECT]["upper"],
        )
        coverage_lower = intervals[USABLE_COVERAGE_EFFECT]["lower"]
        _assert_optional_close(
            thresholds.minimum_usable_coverage,
            None if coverage_lower is None
            else min(1.0, max(0.0, baseline["coverage"] + coverage_lower)),
        )
        expected_power = _reference_power(effects, intervals, detections, method)
        power = report.power_sufficiency
        assert power is not None and power.status is expected_power["status"]
        _assert_optional_close(power.achieved_power, expected_power["achieved"])
        assert power.required_sample_count == expected_power["required_samples"]
        assert power.required_genuine_track_count == expected_power["required_tracks"]
        assert tuple(
            (item.view_id, item.observed_count, item.required_count)
            for item in power.required_view_coverage
        ) == expected_power["required_views"]
        assert power.evidence_gaps == expected_power["gaps"]


def _statistics_with_rule_states(statistics, states):
    sites = []
    for site, state in zip(ACCEPTANCE_SITES, states):
        site_statistics = statistics.for_site(site)
        full = site_statistics.for_arm(PilotArm.FULL_OPTIMIZER)
        values = {
            MEDIAN_ERROR_EFFECT: -1.0 if state.median_estimate_passes else 0.0,
            P90_ERROR_EFFECT: -1.0 if state.p90_estimate_passes else 0.0,
            USABLE_COVERAGE_EFFECT: 0.0 if state.coverage_estimate_passes else -0.1,
        }
        intervals = []
        for name, interval in full.effect_intervals:
            if name == MEDIAN_ERROR_EFFECT:
                lower, upper = -2.0, (-0.1 if state.median_interval_passes else 0.0)
            elif name == P90_ERROR_EFFECT:
                lower, upper = -2.0, (-0.1 if state.p90_interval_passes else 0.0)
            else:
                lower, upper = (0.0 if state.coverage_interval_passes else -0.1), 0.2
            intervals.append((name, replace(
                interval,
                status=DecisionStatus.GO,
                estimate=values[name],
                lower=lower,
                upper=upper,
                bootstrap_variance=0.1,
            )))
        power = replace(
            full.power_sufficiency,
            status=DecisionStatus.GO if state.sufficient else DecisionStatus.INSUFFICIENT_DATA,
            evidence_gaps=state.sufficiency_gaps,
        )
        replacement = replace(
            full,
            signed_effects=tuple((name, values[name]) for name in _EFFECTS),
            effect_intervals=tuple(intervals),
            power_sufficiency=power,
        )
        sites.append(replace(
            site_statistics,
            reports=tuple(
                replacement if report.arm is PilotArm.FULL_OPTIMIZER else report
                for report in site_statistics.reports
            ),
        ))
    return replace(statistics, sites=tuple(sites))


def _expected_site_decision(state):
    gaps = state.sufficiency_gaps
    if not state.sufficient and not gaps:
        gaps = ("power_sufficiency_not_satisfied",)
    failures = []
    if not state.median_estimate_passes:
        failures.append(f"{MEDIAN_ERROR_EFFECT}:estimate_not_improved")
    if not state.median_interval_passes:
        failures.append(f"{MEDIAN_ERROR_EFFECT}:interval_does_not_support_improvement")
    if not state.p90_estimate_passes:
        failures.append(f"{P90_ERROR_EFFECT}:estimate_not_improved")
    if not state.p90_interval_passes:
        failures.append(f"{P90_ERROR_EFFECT}:interval_does_not_support_improvement")
    if not state.coverage_estimate_passes:
        failures.append(f"{USABLE_COVERAGE_EFFECT}:estimate_degrades_coverage")
    if not state.coverage_interval_passes:
        failures.append(f"{USABLE_COVERAGE_EFFECT}:interval_allows_coverage_degradation")
    return (
        DecisionStatus.GO if state.sufficient and not failures else DecisionStatus.NO_GO,
        tuple(sorted(set(gaps))),
        tuple(sorted(set(failures))),
    )


@deterministic_property(16)
@given(case=pilot_cases())
def test_pilot_accounting_and_decision_rules_use_fixed_evidence(case: PilotCase) -> None:
    # Feature: haware-localization-accuracy, Property 16: Pilot accounting and decision rules use fixed evidence
    """**Validates: Requirements 10.1-10.14, 10.21-10.29**"""
    runs = _case_runs(case)
    statistics = compute_pilot_statistics(
        frozen_evidence=_FROZEN,
        frozen_runs=runs,
        profiles=_PROFILES,
    )
    metadata_run_identity = next(
        arm.identity
        for arm in runs.for_site(ACCEPTANCE_SITES[0]).arms
        if arm.identity.arm is PilotArm.FULL_OPTIMIZER
    )
    record_failure_metadata(
        replay_identity=_FROZEN.outcome_access,
        profile_identity=statistics.method,
        run_identity=metadata_run_identity,
    )
    _assert_accounting(case, statistics)

    controlled = _statistics_with_rule_states(statistics, case.site_rules)
    first = decide_pilot_feasibility(
        statistics=controlled,
        frozen_runs=runs,
        diagnostic_values={"taipei-cm": "go", "pooled": "go", "selective-risk": "go"},
    )
    second = decide_pilot_feasibility(
        statistics=controlled,
        frozen_runs=runs,
        diagnostic_values={"taipei-cm": "no_go", "pooled": "no_go", "selective-risk": "no_go"},
    )
    assert first == second
    expected_by_site = {}
    for site, state in zip(ACCEPTANCE_SITES, case.site_rules):
        expected = _expected_site_decision(state)
        expected_by_site[site] = expected
        actual = first.kee_cc if site == "kee-cc" else first.taoyuan_tc
        assert actual.status is expected[0]
        assert actual.evidence_gaps == expected[1]
        assert actual.failed_conditions == expected[2]
    expected_overall = (
        DecisionStatus.GO
        if all(expected_by_site[site][0] is DecisionStatus.GO for site in ACCEPTANCE_SITES)
        else DecisionStatus.NO_GO
    )
    assert first.overall is expected_overall
    assert first.evidence_gaps == tuple(sorted(
        f"{site}:{gap}"
        for site in ACCEPTANCE_SITES
        for gap in expected_by_site[site][1]
    ))
    assert first.failed_conditions == tuple(sorted(
        f"{site}:{failure}"
        for site in ACCEPTANCE_SITES
        for failure in expected_by_site[site][2]
    ))

    current = load_current_evidence_report()
    assert current.final_evidence_status is DecisionStatus.INSUFFICIENT_DATA
    assert not current.proven_improvement_claim_allowed
    assert not current.held_out_acceptance_claim_allowed
    assert not current.optimizer_authoritative_dispatch_allowed
    assert current.diagnostic_inputs_role == "diagnostic_only"


class FixedPilotAccountingAndDecisionsPropertyTest(unittest.TestCase):
    def test_property_16(self) -> None:
        test_pilot_accounting_and_decision_rules_use_fixed_evidence()


if __name__ == "__main__":
    unittest.main()
