"""Property 18: held-out decisions preserve precedence and site independence."""
from __future__ import annotations

from dataclasses import dataclass, replace
import unittest

from hypothesis import given, strategies as st

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.test_haware_held_out import HeldOutControlsTest
from tests.test_haware_pilot_statistics import accepted, rejected
from trafficlab.measurement.haware_held_out import (
    HeldOutAccessError,
    HeldOutDecisionController,
    HeldOutOutcomeBatch,
    default_off_dispatch_evidence,
    freeze_held_out_acceptance,
)
from trafficlab.measurement.haware_pilot import (
    ACCEPTANCE_SITES,
    PilotArm,
    decide_pilot_feasibility,
)
from trafficlab.motion.haware_accuracy.models import (
    DecisionStatus,
    PartitionKind,
    SeedClass,
)
from trafficlab.motion.haware_accuracy.validation import resolve_optimizer_dispatch


@dataclass(frozen=True)
class SiteState:
    threshold_failed: bool
    sufficient: bool


_SITE_STATES = tuple(
    SiteState(threshold_failed=threshold_failed, sufficient=sufficient)
    for threshold_failed in (False, True)
    for sufficient in (False, True)
)
_CONTEXTS = {}
_POST_EXPOSURE_CONTEXTS = {}


def _context(kee_sufficient: bool, taoyuan_sufficient: bool):
    key = (kee_sufficient, taoyuan_sufficient)
    if key not in _CONTEXTS:
        fixture = HeldOutControlsTest(
            methodName="test_site_failure_is_not_rescued_by_other_site"
        )
        fixture.build_context(
            kee_held_out_tracks=2 if kee_sufficient else 1,
            taoyuan_held_out_tracks=2 if taoyuan_sufficient else 1,
        )
        _CONTEXTS[key] = fixture
    return _CONTEXTS[key]


def _post_exposure_context(fixture):
    key = (
        len(fixture.grant.acceptance_profile.partition_for_site("kee-cc").ordered_eligible_ids),
        len(
            fixture.grant.acceptance_profile.partition_for_site(
                "taoyuan-tc"
            ).ordered_eligible_ids
        ),
    )
    if key not in _POST_EXPOSURE_CONTEXTS:
        site = fixture.statistics.for_site("kee-cc")
        full = site.for_arm(PilotArm.FULL_OPTIMIZER)
        changed_full = replace(
            full,
            candidate_thresholds=replace(
                full.candidate_thresholds,
                maximum_median_error_m=(
                    full.candidate_thresholds.maximum_median_error_m + 0.125
                ),
            ),
        )
        changed_statistics = replace(
            fixture.statistics,
            sites=tuple(
                replace(
                    value,
                    reports=tuple(
                        changed_full
                        if report.arm is PilotArm.FULL_OPTIMIZER
                        else report
                        for report in value.reports
                    ),
                )
                if value.site == "kee-cc"
                else value
                for value in fixture.statistics.sites
            ),
        )
        changed_decision = decide_pilot_feasibility(
            statistics=changed_statistics,
            frozen_runs=fixture.runs,
        )
        changed_grant = freeze_held_out_acceptance(
            pilot_decision=changed_decision,
            statistics=changed_statistics,
            frozen_runs=fixture.runs,
            frozen_evidence=fixture.frozen,
            profiles=fixture.profiles,
            validated_profiles=fixture.tokens,
            scope=fixture.scope,
        )
        _POST_EXPOSURE_CONTEXTS[key] = (
            changed_statistics,
            changed_decision,
            changed_grant,
        )
    return _POST_EXPOSURE_CONTEXTS[key]


def _loader(fixture, threshold_failed_sites):
    failed = frozenset(threshold_failed_sites)

    def load(grant):
        batches = []
        for site in ACCEPTANCE_SITES:
            partition = grant.acceptance_profile.partition_for_site(site)
            scale = fixture.profiles[site].calibration.snapshot.pixels_per_metre
            count = len(partition.ordered_eligible_ids)
            baseline = tuple(
                {
                    "status": "ok",
                    "sat_coords": (14.0 * scale, 20.0 * scale),
                    "heading": 0.0,
                }
                for _ in range(count)
            )
            candidate = tuple(
                rejected()
                if site in failed
                else accepted(
                    (11.0 * scale, 20.0 * scale), SeedClass.NON_WHEEL
                )
                for _ in range(count)
            )
            batches.append(
                HeldOutOutcomeBatch(
                    site=site,
                    final_decision_identity=grant.final_decision_identity,
                    partition_identity=partition.partition.content_identity,
                    ordered_eligible_ids=partition.ordered_eligible_ids,
                    baseline_outcomes=baseline,
                    candidate_outcomes=candidate,
                )
            )
        return tuple(batches)

    return load


def _evaluate(
    fixture,
    controller,
    loader,
    diagnostics,
    *,
    grant=None,
    pilot_decision=None,
    statistics=None,
):
    return controller.evaluate(
        grant=fixture.grant if grant is None else grant,
        pilot_decision=(
            fixture.pilot_decision if pilot_decision is None else pilot_decision
        ),
        statistics=fixture.statistics if statistics is None else statistics,
        frozen_runs=fixture.runs,
        frozen_evidence=fixture.frozen,
        profiles=fixture.profiles,
        validated_profiles=fixture.tokens,
        scope=fixture.scope,
        outcome_loader=loader,
        diagnostic_values=diagnostics,
    )


def _expected_site_status(state: SiteState) -> DecisionStatus:
    if state.threshold_failed:
        return DecisionStatus.NO_GO
    if not state.sufficient:
        return DecisionStatus.INSUFFICIENT_DATA
    return DecisionStatus.GO


def _expected_overall(*statuses: DecisionStatus) -> DecisionStatus:
    if DecisionStatus.NO_GO in statuses:
        return DecisionStatus.NO_GO
    if DecisionStatus.INSUFFICIENT_DATA in statuses:
        return DecisionStatus.INSUFFICIENT_DATA
    return DecisionStatus.GO


_diagnostic_value = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-10_000, max_value=10_000),
    st.text(max_size=24),
    st.lists(st.integers(min_value=-5, max_value=5), max_size=5),
)
_diagnostics = st.fixed_dictionaries(
    {
        "taipei-cm": _diagnostic_value,
        "pooled": _diagnostic_value,
        "proxy": _diagnostic_value,
        "selective_risk": _diagnostic_value,
    }
)


@deterministic_property(18)
@given(
    kee_state=st.sampled_from(_SITE_STATES),
    taoyuan_state=st.sampled_from(_SITE_STATES),
    diagnostics=_diagnostics,
    perturbed_diagnostics=_diagnostics,
)
def test_held_out_precedence_and_site_independence(
    kee_state: SiteState,
    taoyuan_state: SiteState,
    diagnostics,
    perturbed_diagnostics,
) -> None:
    # Feature: haware-localization-accuracy, Property 18: Held-out decisions preserve precedence and site independence
    """**Validates: Requirements 11.12-11.19**"""
    fixture = _context(kee_state.sufficient, taoyuan_state.sufficient)
    failed_sites = {
        site
        for site, state in zip(
            ACCEPTANCE_SITES, (kee_state, taoyuan_state), strict=True
        )
        if state.threshold_failed
    }
    loader = _loader(fixture, failed_sites)

    controller = HeldOutDecisionController()
    decision = _evaluate(fixture, controller, loader, diagnostics)
    perturbed = _evaluate(
        fixture,
        HeldOutDecisionController(),
        loader,
        perturbed_diagnostics,
    )
    record_failure_metadata(
        replay_identity=fixture.grant.acceptance_profile,
        profile_identity=fixture.grant.acceptance_profile.candidate,
        run_identity=decision,
    )

    expected_sites = (
        _expected_site_status(kee_state),
        _expected_site_status(taoyuan_state),
    )
    reports = (decision.kee_cc, decision.taoyuan_tc)
    assert tuple(report.site for report in reports) == ACCEPTANCE_SITES
    assert tuple(report.status for report in reports) == expected_sites
    assert decision.overall is _expected_overall(*expected_sites)
    assert decision == perturbed
    assert not hasattr(decision, "taipei_cm")

    acceptance = fixture.grant.acceptance_profile
    assert tuple(value.site for value in fixture.frozen.sites) == ACCEPTANCE_SITES
    assert tuple(value.site for value in fixture.runs.sites) == ACCEPTANCE_SITES
    assert tuple(value.site for value in fixture.statistics.sites) == ACCEPTANCE_SITES
    assert tuple(value.site for value in acceptance.candidates) == ACCEPTANCE_SITES
    assert tuple(value.site for value in acceptance.partitions) == ACCEPTANCE_SITES
    assert tuple(value.site for value in acceptance.site_policies) == ACCEPTANCE_SITES
    assert decision.final_decision_identity == fixture.grant.final_decision_identity
    assert decision.candidate_identity == acceptance.candidate.content_identity
    assert acceptance.candidate.sites == acceptance.candidates

    assert fixture.runs.current_evidence_status is DecisionStatus.INSUFFICIENT_DATA
    assert fixture.statistics.current_evidence_status is DecisionStatus.INSUFFICIENT_DATA
    assert not fixture.runs.proven_improvement_claim_allowed
    assert not fixture.statistics.proven_improvement_claim_allowed
    assert not fixture.statistics.held_out_acceptance_claim_allowed
    assert fixture.runs.optimizer_default_off_outside_pilot

    for site, report in zip(ACCEPTANCE_SITES, reports, strict=True):
        manifest = next(
            value for value in acceptance.candidates if value.site == site
        )
        partition = acceptance.partition_for_site(site)
        policy = acceptance.for_site(site)
        assert manifest.profile_snapshot == fixture.profiles[site]
        assert (
            manifest.pilot_run_identity.run.profile
            == manifest.profile_snapshot.content_identity
        )
        assert (
            partition.population_identity
            == fixture.frozen.for_site(site).population.content_identity
        )
        assert report.denominator == len(partition.ordered_eligible_ids)
        assert report.accepted_count + report.rejected_count == report.denominator
        assert tuple(name for name, _ in report.signed_effects) == (
            "median_error_m",
            "p90_error_m",
            "usable_coverage",
        )
        assert tuple(name for name, _ in report.effect_intervals) == (
            "median_error_m",
            "p90_error_m",
            "usable_coverage",
        )

        held_out = tuple(
            value
            for value in fixture.frozen.for_site(site).eligible_detections
            if value.partition is PartitionKind.HELD_OUT
        )
        expected_view_ids = tuple(
            sorted({value.independent_view_id for value in held_out})
        )
        reported_view_ids = tuple(
            value.view_id for value in report.independent_view_coverage
        )
        assert partition.independent_view_ids == expected_view_ids
        assert reported_view_ids == expected_view_ids
        assert all(
            view_id.startswith(f"{site}:camera:") for view_id in reported_view_ids
        )
        view_counts = {
            value.view_id: value.eligible_count
            for value in report.independent_view_coverage
        }
        for required in policy.required_view_coverage:
            assert required.view_id.startswith(f"{site}:camera:")
            gap = (
                "independent_view_coverage_below_frozen_requirement:"
                f"{required.view_id}"
            )
            assert (view_counts.get(required.view_id, 0) < required.required_count) == (
                gap in report.evidence_gaps
            )

    assert controller.decision_for(fixture.grant.final_decision_identity) == decision
    try:
        _evaluate(fixture, controller, loader, perturbed_diagnostics)
    except HeldOutAccessError as error:
        assert "final_decision_identity_already_evaluated" in str(error)
    else:
        raise AssertionError("a final-decision identity was evaluated more than once")

    changed_statistics, changed_decision, changed_grant = _post_exposure_context(
        fixture
    )
    assert changed_grant.final_decision_identity != fixture.grant.final_decision_identity
    assert tuple(
        value.partition.content_identity
        for value in changed_grant.acceptance_profile.partitions
    ) == tuple(
        value.partition.content_identity for value in acceptance.partitions
    )
    post_exposure_loader_calls = []
    try:
        _evaluate(
            fixture,
            controller,
            lambda grant: post_exposure_loader_calls.append(grant),
            perturbed_diagnostics,
            grant=changed_grant,
            pilot_decision=changed_decision,
            statistics=changed_statistics,
        )
    except HeldOutAccessError as error:
        assert "held_out_partition_previously_exposed" in str(error)
    else:
        raise AssertionError("an exposed held-out partition was reused")
    assert post_exposure_loader_calls == []

    authorization = default_off_dispatch_evidence(decision)
    if decision.overall is DecisionStatus.GO:
        assert authorization is not None
        assert tuple(
            value.site for value in authorization.held_out_site_decisions
        ) == ACCEPTANCE_SITES
        assert not authorization.hardening_reviewed
        assert not authorization.hardening_authorized
    else:
        assert authorization is None
    dispatch = resolve_optimizer_dispatch(decision.candidate_identity, authorization)
    assert not dispatch.optimizer_enabled
    assert dispatch.production_path == "corrected_legacy_baseline"
    assert dispatch.optimizer_output_role == "diagnostic_only"
    expected_reason = (
        "hardening_authorization_incomplete"
        if decision.overall is DecisionStatus.GO
        else "optimizer_default_off"
    )
    assert dispatch.reason == expected_reason


class HeldOutPrecedenceAndSiteIndependencePropertyTest(unittest.TestCase):
    def test_property_18(self) -> None:
        test_held_out_precedence_and_site_independence()


if __name__ == "__main__":
    unittest.main()
