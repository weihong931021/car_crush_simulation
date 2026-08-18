"""Focused unit tests for Task 8.2 pilot and current-evidence decisions."""
from dataclasses import replace
import unittest

from trafficlab.measurement.haware_pilot import (
    ACCEPTANCE_SITES,
    MEDIAN_ERROR_EFFECT,
    P90_ERROR_EFFECT,
    USABLE_COVERAGE_EFFECT,
    PilotArm,
    compute_pilot_statistics,
    decide_pilot_feasibility,
    load_current_evidence_report,
)
from trafficlab.motion.haware_accuracy.models import DecisionStatus
from tests.test_haware_pilot_statistics import PilotStatisticsTest


class PilotDecisionTest(unittest.TestCase):
    def setUp(self):
        fixture = PilotStatisticsTest()
        fixture.setUp()
        self.runs = fixture.run_arms()
        self.statistics = compute_pilot_statistics(
            frozen_evidence=fixture.frozen,
            frozen_runs=self.runs,
            profiles=fixture.profiles,
        )

    def _replace_full_report(self, site, passing, gaps=()):
        site_statistics = self.statistics.for_site(site)
        full = site_statistics.for_arm(PilotArm.FULL_OPTIMIZER)
        effects = {
            MEDIAN_ERROR_EFFECT: -1.0 if passing else 1.0,
            P90_ERROR_EFFECT: -0.5 if passing else 0.5,
            USABLE_COVERAGE_EFFECT: 0.1 if passing else -0.1,
        }
        bounds = {
            MEDIAN_ERROR_EFFECT: (-1.5, -0.5) if passing else (-0.5, 1.5),
            P90_ERROR_EFFECT: (-1.0, -0.1) if passing else (-0.2, 0.8),
            USABLE_COVERAGE_EFFECT: (0.0, 0.2) if passing else (-0.3, 0.1),
        }
        intervals = tuple(
            (
                name,
                replace(
                    interval,
                    status=DecisionStatus.GO,
                    estimate=effects[name],
                    lower=bounds[name][0],
                    upper=bounds[name][1],
                ),
            )
            for name, interval in full.effect_intervals
        )
        power = replace(
            full.power_sufficiency,
            status=DecisionStatus.GO if passing else DecisionStatus.INSUFFICIENT_DATA,
            achieved_power=0.9 if passing else 0.2,
            required_sample_count=4,
            required_genuine_track_count=2,
            evidence_gaps=tuple(gaps),
        )
        replacement = replace(
            full,
            signed_effects=tuple((name, effects[name]) for name, _ in full.signed_effects),
            effect_intervals=intervals,
            power_sufficiency=power,
        )
        return replace(
            site_statistics,
            reports=tuple(
                replacement if value.arm is PilotArm.FULL_OPTIMIZER else value
                for value in site_statistics.reports
            ),
        )

    def _with_sites(self, kee_passing, taoyuan_passing, taoyuan_gaps=()):
        return replace(
            self.statistics,
            sites=(
                self._replace_full_report("kee-cc", kee_passing),
                self._replace_full_report(
                    "taoyuan-tc", taoyuan_passing, taoyuan_gaps
                ),
            ),
        )

    def test_go_requires_both_sites_to_pass_independently(self):
        both = decide_pilot_feasibility(
            statistics=self._with_sites(True, True), frozen_runs=self.runs
        )
        one = decide_pilot_feasibility(
            statistics=self._with_sites(True, False), frozen_runs=self.runs
        )
        self.assertIs(both.overall, DecisionStatus.GO)
        self.assertIs(one.overall, DecisionStatus.NO_GO)
        self.assertIs(one.kee_cc.status, DecisionStatus.GO)
        self.assertIs(one.taoyuan_tc.status, DecisionStatus.NO_GO)

    def test_no_go_reports_all_site_gaps_and_feasibility_failures(self):
        decision = decide_pilot_feasibility(
            statistics=self._with_sites(
                True, False, taoyuan_gaps=("track_gap", "view_gap")
            ),
            frozen_runs=self.runs,
        )
        self.assertEqual(
            decision.taoyuan_tc.evidence_gaps, ("track_gap", "view_gap")
        )
        self.assertEqual(len(decision.taoyuan_tc.failed_conditions), 6)
        self.assertEqual(
            set(decision.evidence_gaps),
            {"taoyuan-tc:track_gap", "taoyuan-tc:view_gap"},
        )

    def test_diagnostic_perturbations_cannot_rescue_or_change_decision(self):
        statistics = self._with_sites(True, False, ("power_gap",))
        first = decide_pilot_feasibility(
            statistics=statistics,
            frozen_runs=self.runs,
            diagnostic_values={"taipei-cm": "go", "pooled": "pass"},
        )
        second = decide_pilot_feasibility(
            statistics=statistics,
            frozen_runs=self.runs,
            diagnostic_values={"taipei-cm": "no_go", "pooled": "fail"},
        )
        self.assertEqual(first, second)

    def test_checked_in_current_evidence_is_insufficient(self):
        report = load_current_evidence_report()
        self.assertIs(report.final_evidence_status, DecisionStatus.INSUFFICIENT_DATA)
        self.assertFalse(report.proven_improvement_claim_allowed)
        self.assertFalse(report.held_out_acceptance_claim_allowed)
        self.assertFalse(report.optimizer_authoritative_dispatch_allowed)
        self.assertEqual(
            tuple(site for site, _ in report.per_site_evidence_gaps), ACCEPTANCE_SITES
        )


if __name__ == "__main__":
    unittest.main()