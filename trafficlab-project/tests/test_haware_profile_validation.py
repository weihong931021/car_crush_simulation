"""Focused tests for fail-fast MVP profile validation and scope guards."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trafficlab.motion.haware_accuracy.models import (  # noqa: E402
    ModelValidationError,
    PreGateBound,
    SceneExportSettings,
    AcceptanceProfile,
    AmbiguitySettings,
    CalibrationProfile,
    CalibrationSnapshot,
    ClosedInterval,
    ContentIdentity,
    CueEvidenceProfile,
    CueFamily,
    CueHeightSpec,
    DecisionStatus,
    LegacyStatusPolicy,
    LeastSquaresSettings,
    MinimalConfiguration,
    NuisanceField,
    NuisanceProfile,
    ObservabilitySettings,
    OptimizerProfile,
    PilotPolicy,
    PoseEquivalenceSettings,
    ReplayContract,
    RobustSettings,
    SemanticPath,
    SemanticPathSpec,
    SiteDecision,
    SourceProvenance,
)
from trafficlab.motion.haware_accuracy.validation import (  # noqa: E402
    validate_estimator_contract,
    ACCEPTANCE_SITES,
    HYPOTHESIS_STABLE_ORDER,
    OBSERVATION_STABLE_ORDER,
    REQUIRED_GATE_PRECEDENCE,
    AcceptanceSiteNamespace,
    DispatchAuthorization,
    MvpScopeGuard,
    ProfileValidationError,
    require_validated_profile,
    resolve_optimizer_dispatch,
    validate_before_read,
    validate_estimator_contract,
)


IDENTITY = ContentIdentity("0" * 64)


def source(name: str = "fixture") -> SourceProvenance:
    return SourceProvenance(
        source_id=name,
        repository_relative_path=f"evidence/{name}.json",
        source_content_identity=IDENTITY,
    )


def calibration() -> CalibrationProfile:
    snapshot = CalibrationSnapshot(
        version="cal-v1",
        camera_matrix=((1000.0, 0.0, 640.0), (0.0, 1000.0, 360.0), (0.0, 0.0, 1.0)),
        distortion=(0.0, 0.0, 0.0, 0.0, 0.0),
        homography=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        inverse_homography=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        camera_sat_px=(100.0, 200.0),
        camera_height_m=12.0,
        pixels_per_metre=4.0,
        provenance=source("calibration"),
    )
    return CalibrationProfile(
        version="cal-profile-v1",
        snapshot=snapshot,
        authorized_nuisance_fields=("delta_z_cam",),
    )


def configurations() -> tuple[MinimalConfiguration, ...]:
    return (
        MinimalConfiguration(configuration_id="roof-pair", cue_families=(CueFamily.ROOF,), minimum_support=2),
        MinimalConfiguration(configuration_id="wheel-pair", cue_families=(CueFamily.WHEEL,), minimum_support=2),
    )


def optimizer(minimal: tuple[MinimalConfiguration, ...]) -> OptimizerProfile:
    return OptimizerProfile(
        version="optimizer-v1",
        hypothesis_budget=4,
        sampled_candidate_budget=8,
        retained_candidate_count=4,
        minimal_configurations=minimal,
        semantic_paths=(
            SemanticPathSpec(semantic_path=SemanticPath.NORMAL),
            SemanticPathSpec(semantic_path=SemanticPath.REVERSED, front_rear_mapping=(("front", "rear"),)),
        ),
        robust=RobustSettings(
            loss="huber", loss_scale=2.0, support_boundary_px=8.0,
            support_includes_equality=True, outlier_penalty=3.0, nuisance_penalty=1.0,
        ),
        optimizer=LeastSquaresSettings(
            method="trf", max_evaluations=100, ftol=1e-8, xtol=1e-8, gtol=1e-8,
            finite_difference_step=1e-6, parameter_scale=(1.0, 1.0, 1.0, 1.0, 1.0),
        ),
        observability=ObservabilitySettings(
            jacobian_version="pixel-residual-v1", curvature_version="schur-v1",
            rank_tolerance=1e-9, minimum_rank=3, condition_rejection_boundary=1e8,
            position_uncertainty_boundary_m=3.0, heading_uncertainty_boundary_rad=0.5,
        ),
        equivalence=PoseEquivalenceSettings(
            position_tolerance_m=0.1, heading_tolerance_rad=0.01, prediction_tolerance_px=1.0,
        ),
        ambiguity=AmbiguitySettings(equal_score_tolerance=1e-9, margin_absolute=0.1, margin_ratio=None),
        rejection_precedence=(*REQUIRED_GATE_PRECEDENCE, "insufficient_valid_hypothesis", "inconsistent_coordinate_state"),
        deterministic_seed=1729,
    )


def profile(site: str = "kee-cc") -> AcceptanceProfile:
    minimal = configurations()
    cue_evidence = CueEvidenceProfile(
        version="cue-v1",
        site=site,
        view="camera-1",
        semantic_mappings=(("wheel", "wheel"), ("roof", "roof")),
        height_specs=(
            CueHeightSpec(cue_family=CueFamily.WHEEL, height_m=ClosedInterval(lower=0.0, upper=0.0), evidence=source("wheel")),
            CueHeightSpec(cue_family=CueFamily.ROOF, height_m=ClosedInterval(lower=1.2, upper=1.8), evidence=source("roof")),
        ),
        minimal_configurations=minimal,
        provenance=(source("cue"),),
    )
    return AcceptanceProfile(
        profile_id="candidate-v1",
        calibration=calibration(),
        cue_evidence=cue_evidence,
        nuisance=NuisanceProfile(
            version="nuisance-v1",
            fields=(
                NuisanceField(name="vehicle_width", unit="m", bounds=ClosedInterval(lower=1.5, upper=2.5), scale=1.0),
                NuisanceField(name="delta_z_cam", unit="m", bounds=ClosedInterval(lower=-0.2, upper=0.2), scale=0.1),
            ),
        ),
        optimizer=optimizer(minimal),
        replay_contract=ReplayContract(
            version="replay-v1", maximum_observations=24, maximum_labels_per_observation=4,
            maximum_string_length=128, confidence_bounds=ClosedInterval(lower=0.0, upper=1.0),
        ),
        legacy_status_policy=LegacyStatusPolicy(
            version="legacy-v1", accepted_statuses=("ok",), rejected_statuses=("rejected",),
        ),
        pilot_policy=PilotPolicy(
            version="pilot-v1", confidence_level=0.95, cluster_unit="real_track",
            power_method="cluster-bootstrap-v1", sufficiency_rule_version="sufficiency-v1",
            metric_definition_version="metrics-v1",
        ),
    )


def namespace(site: str) -> AcceptanceSiteNamespace:
    return AcceptanceSiteNamespace(
        site=site,
        ground_truth=f"{site}:ground_truth",
        track=f"{site}:track",
        source_sequence=f"{site}:source_sequence",
        view=f"{site}:view",
        partition=f"{site}:partition",
        metric=f"{site}:metric",
        decision=f"{site}:decision",
    )


def scope() -> MvpScopeGuard:
    return MvpScopeGuard(
        acceptance_namespaces=tuple(namespace(site) for site in ACCEPTANCE_SITES),
        diagnostic_sites=("taipei-cm",),
        observation_stable_order=OBSERVATION_STABLE_ORDER,
        hypothesis_stable_order=HYPOTHESIS_STABLE_ORDER,
        scipy_version="1.14.1",
        jacobian_method="2-point",
        numeric_threads=1,
        production_imports=("trafficlab.motion.haware_optimizer",),
        estimator_contract_terms=("image_space_forward_model", "wheel", "non_wheel"),
        calibration_variation_scope="fit_local",
        publish_fitted_calibration=False,
        feed_back_fitted_calibration=False,
        enabled_deferred_capabilities=(),
        selective_risk_role="diagnostic_only",
        pooled_cross_site_override=False,
        diagnostic_site_decision_input=False,
        current_evidence_status=DecisionStatus.INSUFFICIENT_DATA,
        proven_improvement_claim_allowed=False,
    )


class ProfileValidationTest(unittest.TestCase):
    def test_valid_profile_issues_identity_bound_pre_read_token(self):
        value, guard = profile(), scope()
        token = validate_before_read(value, guard)
        require_validated_profile(token, value, guard)
        with self.assertRaisesRegex(ProfileValidationError, "profile_changed_after_validation"):
            require_validated_profile(token, replace(value, profile_id="changed"), guard)

    def test_ground_contact_must_be_present_and_exactly_zero(self):
        value = profile()
        bad_spec = replace(value.cue_evidence.height_specs[1], height_m=ClosedInterval(lower=0.0, upper=0.1))
        bad_cues = replace(value.cue_evidence, height_specs=(bad_spec, value.cue_evidence.height_specs[0]))
        with self.assertRaisesRegex(ProfileValidationError, "invalid_ground_contact_height"):
            validate_before_read(replace(value, cue_evidence=bad_cues), scope())

    def test_distortion_homography_and_explicit_scipy_settings_fail_fast(self):
        value = profile()
        bad_snapshot = replace(value.calibration.snapshot, distortion=(0.0, 0.0, 0.0))
        with self.assertRaisesRegex(ProfileValidationError, "unsupported_distortion_layout"):
            validate_before_read(replace(value, calibration=replace(value.calibration, snapshot=bad_snapshot)), scope())

        for field in ("max_evaluations", "ftol", "xtol", "gtol", "finite_difference_step"):
            bad_settings = replace(value.optimizer.optimizer, **{field: 0})
            with self.subTest(field=field), self.assertRaisesRegex(ProfileValidationError, "implicit_scipy_setting"):
                validate_before_read(replace(value, optimizer=replace(value.optimizer, optimizer=bad_settings)), scope())

        with self.assertRaises(TypeError):
            LeastSquaresSettings(
                method="trf", max_evaluations=100, xtol=1e-8, gtol=1e-8,
                finite_difference_step=1e-6, parameter_scale=(1.0, 1.0, 1.0),
            )
        with self.assertRaisesRegex(ProfileValidationError, "implicit_runtime_setting"):
            validate_before_read(value, replace(scope(), scipy_version=""))

    def test_budgets_gate_precedence_and_replay_bounds_are_complete(self):
        value = profile()
        with self.assertRaisesRegex(ProfileValidationError, "insufficient_hypothesis_budget"):
            validate_before_read(replace(value, optimizer=replace(value.optimizer, hypothesis_budget=3)), scope())
        with self.assertRaisesRegex(ProfileValidationError, "invalid_gate_precedence"):
            validate_before_read(replace(value, optimizer=replace(value.optimizer, rejection_precedence=tuple(reversed(value.optimizer.rejection_precedence)))), scope())
        incomplete = value.optimizer.rejection_precedence[:-1]
        with self.assertRaisesRegex(ProfileValidationError, "incomplete_gate_precedence"):
            validate_before_read(replace(value, optimizer=replace(value.optimizer, rejection_precedence=incomplete)), scope())
        bad_replay = replace(value.replay_contract, maximum_labels_per_observation=25)
        with self.assertRaisesRegex(ProfileValidationError, "invalid_replay_bounds"):
            validate_before_read(replace(value, replay_contract=bad_replay), scope())

    def test_prohibited_estimator_contracts_and_legacy_imports_are_rejected(self):
        prohibited_contracts = (
            {"mode": "wheel_only"},
            {"mode": "wheel_weighted"},
            {"call_path": "projected_point_procrustes.fit"},
            {"pipeline": {"call_path": "RoleConstraintGraph.solve"}},
            {"objective": ("image_residual", "inverse-lifted targets")},
        )
        for contract in prohibited_contracts:
            with self.subTest(contract=contract), self.assertRaisesRegex(ProfileValidationError, "prohibited_estimator_contract"):
                validate_estimator_contract(contract)
        for legacy_import in ("location.old_fitter", "pifpaf.decoder"):
            with self.subTest(legacy_import=legacy_import), self.assertRaisesRegex(ProfileValidationError, "prohibited_production_import"):
                validate_before_read(profile(), replace(scope(), production_imports=(legacy_import,)))

    def test_scope_keeps_calibration_local_and_deferred_capabilities_absent(self):
        with self.assertRaisesRegex(ProfileValidationError, "nonlocal_calibration_variation"):
            validate_before_read(profile(), replace(scope(), publish_fitted_calibration=True))
        with self.assertRaisesRegex(ProfileValidationError, "deferred_capability_enabled"):
            validate_before_read(profile(), replace(scope(), enabled_deferred_capabilities=("temporal_fusion",)))
        with self.assertRaisesRegex(ProfileValidationError, "deferred_capability_configured"):
            validate_before_read(profile(), replace(scope(), estimator_contract_terms=("temporal_fusion",)))
        with self.assertRaisesRegex(ProfileValidationError, "unsupported_current_evidence_claim"):
            validate_before_read(profile(), replace(scope(), proven_improvement_claim_allowed=True))

    def test_acceptance_namespaces_and_diagnostic_site_are_isolated(self):
        with self.assertRaisesRegex(ProfileValidationError, "diagnostic_site_profile"):
            validate_before_read(profile("taipei-cm"), scope())
        duplicate = replace(namespace("taoyuan-tc"), metric="kee-cc:metric")
        with self.assertRaisesRegex(ProfileValidationError, "non_isolated_acceptance_namespace"):
            validate_before_read(profile(), replace(scope(), acceptance_namespaces=(namespace("kee-cc"), duplicate)))
        for override in ("pooled_cross_site_override", "diagnostic_site_decision_input"):
            with self.subTest(override=override), self.assertRaisesRegex(ProfileValidationError, "non_isolated_site_decision"):
                validate_before_read(profile(), replace(scope(), **{override: True}))


class DispatchGuardTest(unittest.TestCase):
    def authorization(self, *, candidate=IDENTITY, taoyuan=DecisionStatus.GO, hardening=True):
        return DispatchAuthorization(
            candidate_identity=candidate,
            held_out_site_decisions=(
                SiteDecision(site="kee-cc", status=DecisionStatus.GO),
                SiteDecision(site="taoyuan-tc", status=taoyuan),
            ),
            hardening_reviewed=hardening,
            hardening_authorized=hardening,
            hardening_candidate_identity=candidate if hardening else None,
            hardening_scope=("accepted_mvp_input_validation", "coordinate_authority_safety"),
        )

    def test_dispatch_is_default_off_and_non_authoritative(self):
        result = resolve_optimizer_dispatch(IDENTITY)
        self.assertFalse(result.optimizer_enabled)
        self.assertEqual(result.production_path, "corrected_legacy_baseline")
        self.assertEqual(result.optimizer_output_role, "diagnostic_only")
        self.assertEqual(result.reason, "optimizer_default_off")

    def test_dispatch_requires_exact_dual_site_go_and_hardening(self):
        insufficient = resolve_optimizer_dispatch(
            IDENTITY, self.authorization(taoyuan=DecisionStatus.INSUFFICIENT_DATA)
        )
        self.assertFalse(insufficient.optimizer_enabled)
        self.assertEqual(insufficient.reason, "dual_site_held_out_go_missing")

        one_site = replace(
            self.authorization(),
            held_out_site_decisions=(SiteDecision(site="kee-cc", status=DecisionStatus.GO),),
        )
        self.assertEqual(resolve_optimizer_dispatch(IDENTITY, one_site).reason, "dual_site_held_out_go_missing")

        hardening_missing = resolve_optimizer_dispatch(IDENTITY, self.authorization(hardening=False))
        self.assertFalse(hardening_missing.optimizer_enabled)
        self.assertEqual(hardening_missing.reason, "hardening_authorization_incomplete")

        other = ContentIdentity("1" * 64)
        mismatch = resolve_optimizer_dispatch(other, self.authorization())
        self.assertFalse(mismatch.optimizer_enabled)
        self.assertEqual(mismatch.reason, "candidate_identity_mismatch")
        self.assertTrue(resolve_optimizer_dispatch(IDENTITY, self.authorization()).optimizer_enabled)
        with self.assertRaisesRegex(ProfileValidationError, "invalid_hardening_scope"):
            resolve_optimizer_dispatch(
                IDENTITY,
                replace(self.authorization(), hardening_scope=("threshold_retuning",)),
            )

    def test_taipei_cannot_contribute_to_authorization(self):
        authorization = replace(
            self.authorization(),
            held_out_site_decisions=(
                SiteDecision(site="kee-cc", status=DecisionStatus.GO),
                SiteDecision(site="taipei-cm", status=DecisionStatus.GO),
            ),
        )
        with self.assertRaisesRegex(ProfileValidationError, "diagnostic_site_authorization"):
            resolve_optimizer_dispatch(IDENTITY, authorization)


if __name__ == "__main__":
    unittest.main()


class NarrowedEstimatorProhibitionTest(unittest.TestCase):
    """Requirement 4.16 / 12.4: prohibited as a production core, legal as a pilot arm.

    The pre-2026-08-17 matcher was a substring scan, so it rejected the frozen
    diagnostic-candidate name `wheel_weighted_procrustes` — the one place the
    token is legal — while never actually reaching the OptimizerProfile it was
    supposed to police.
    """

    def test_prohibited_estimator_modes_are_still_rejected(self):
        for term in ("wheel_only", "wheel_weighted", "RoleConstraintGraph", "projected-point procrustes"):
            with self.subTest(term=term):
                with self.assertRaises(ProfileValidationError):
                    validate_estimator_contract({"mode": term})

    def test_the_diagnostic_candidate_name_is_not_a_prohibited_mode(self):
        validate_estimator_contract({"diagnostic_candidates": ("wheel_weighted_procrustes",)})
        validate_estimator_contract(("wheel_weighted_procrustes",))

    def test_prohibited_terms_are_rejected_inside_the_optimizer_profile(self):
        tainted = replace(profile(), optimizer=replace(profile().optimizer, version="wheel_weighted-v1"))
        with self.assertRaises(ProfileValidationError):
            validate_before_read(tainted, scope())


class RevisedProfileFieldsTest(unittest.TestCase):
    """The frozen fields the 2026-08-16/17 spec revision added to design section 1."""

    def test_optimizer_profile_freezes_the_validity_gate_set_and_seed_class_flags(self):
        optimizer = profile().optimizer
        self.assertEqual(optimizer.validity_gate_set, ("support", "non_finite", "convergence"))
        self.assertTrue(optimizer.wheel_seeded_enabled)
        self.assertTrue(optimizer.non_wheel_seeded_enabled)
        ablation = replace(optimizer, wheel_seeded_enabled=False)
        self.assertFalse(ablation.wheel_seeded_enabled)

    def test_optimizer_profile_rejects_an_empty_validity_gate_set(self):
        with self.assertRaises(ModelValidationError):
            replace(profile().optimizer, validity_gate_set=())

    def test_optimizer_profile_rejects_disabling_both_seed_classes(self):
        with self.assertRaises(ModelValidationError):
            replace(profile().optimizer, wheel_seeded_enabled=False, non_wheel_seeded_enabled=False)

    def test_pilot_policy_may_name_the_wheel_weighted_procrustes_diagnostic_candidate(self):
        policy = replace(
            profile().pilot_policy,
            diagnostic_candidates=("wheel_weighted_procrustes",),
            diagnostic_candidate_params=(("wheel_weighted_procrustes", (("w_wheel", 4.0),)),),
        )
        self.assertEqual(policy.diagnostic_candidates, ("wheel_weighted_procrustes",))
        self.assertEqual(policy.parameters_for("wheel_weighted_procrustes"), {"w_wheel": 4.0})
        validate_before_read(replace(profile(), pilot_policy=policy), scope())

    def test_pilot_policy_rejects_a_diagnostic_candidate_without_parameters(self):
        with self.assertRaises(ModelValidationError):
            replace(
                profile().pilot_policy,
                diagnostic_candidates=("wheel_weighted_procrustes",),
                diagnostic_candidate_params=(),
            )

    def test_acceptance_profile_names_exactly_two_sites_from_a_frozen_pool(self):
        accepted = profile()
        self.assertEqual(len(accepted.acceptance_sites), 2)
        self.assertTrue(set(accepted.acceptance_sites) <= set(accepted.candidate_site_pool))
        with self.assertRaises(ModelValidationError):
            replace(accepted, acceptance_sites=("kee-cc",))
        with self.assertRaises(ModelValidationError):
            replace(accepted, acceptance_sites=("kee-cc", "taipei-cm"))


class FrozenRuntimeAndSweepFieldsTest(unittest.TestCase):
    """Design section 1 "Pre-outcome constants": every value the spec says is frozen
    must have somewhere to live, or it is not actually frozen."""

    def test_calibration_profile_carries_an_optional_near_horizon_pre_gate(self):
        calibration = profile().calibration
        self.assertIsNone(calibration.pre_gate)  # Requirement 1.23: disabled unless set
        gated = replace(calibration, pre_gate=PreGateBound(kind="image_row", bound=420.0))
        self.assertEqual(gated.pre_gate.kind, "image_row")
        with self.assertRaises(ModelValidationError):
            PreGateBound(kind="not_a_kind", bound=1.0)

    def test_acceptance_profile_freezes_the_runtime_envelope_and_scene_export_bounds(self):
        accepted = profile()
        self.assertEqual(accepted.batch_runtime_envelope_s_per_s, 10.0)
        self.assertEqual(accepted.scene_export.max_gap_frames, 5)
        self.assertEqual(accepted.scene_export.min_accepted_share, 0.5)
        with self.assertRaises(ModelValidationError):
            replace(accepted, batch_runtime_envelope_s_per_s=0.0)
        with self.assertRaises(ModelValidationError):
            SceneExportSettings(max_gap_frames=-1, min_accepted_share=0.5)
        with self.assertRaises(ModelValidationError):
            SceneExportSettings(max_gap_frames=5, min_accepted_share=1.5)

    def test_pilot_policy_freezes_the_statistics_constants(self):
        policy = profile().pilot_policy
        self.assertEqual(policy.interval_method, "whole_track_cluster_bootstrap_v1")
        self.assertEqual(policy.minimum_valid_clusters, 8)
        self.assertEqual(policy.resample_budget, 4096)
        self.assertEqual(policy.minimum_effect_of_interest_for("median_error_m"), 0.5)
        with self.assertRaises(ModelValidationError):
            replace(policy, minimum_valid_clusters=1)
        with self.assertRaises(ModelValidationError):
            replace(policy, interval_method="exact_sign_flip")

    def test_position_ambiguity_tolerance_may_not_exceed_half_the_median_mei(self):
        """Requirement 5.19: the tolerance is bounded by materiality, not taste."""
        policy = profile().pilot_policy
        self.assertEqual(policy.position_ambiguity_tolerance_m, 0.25)
        with self.assertRaises(ModelValidationError):
            replace(policy, position_ambiguity_tolerance_m=0.4)
