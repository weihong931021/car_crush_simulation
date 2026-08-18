"""Property 8: nuisance bounds and uncertainty propagation."""
from __future__ import annotations

from dataclasses import replace
import unittest

from hypothesis import given, strategies as st
import numpy as np

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.property_support.strategies import bounded_floats
from tests.test_haware_hypotheses import (
    configured_profile,
    record,
    scope,
    seed_profile,
    template,
)
from tests.test_haware_optimizer import refinement_bounds
from trafficlab.motion.haware_accuracy.models import (
    ClosedInterval,
    CueFamily,
    GaussianPrior,
    NuisanceField,
    NuisanceProfile,
    SeedClass,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read
from trafficlab.motion.haware_hypotheses import DirectImageHypothesisGenerator
from trafficlab.motion.haware_optimizer import (
    BoundedScipyRefiner,
    RefinedCandidate,
    RefinementFailure,
    _parameterization,
)
from trafficlab.projection.haware_forward import HawareForwardProjector


_TEMPLATE = template()
_SCOPE = scope()
_PROJECTOR = HawareForwardProjector()


def _prior(mean: float | None, standard_deviation: float):
    if mean is None:
        return None
    return GaussianPrior(mean=mean, standard_deviation=standard_deviation)


def _profile(
    *,
    width_bounds: ClosedInterval,
    calibration_bounds: ClosedInterval,
    width_prior_mean: float | None,
    calibration_prior_mean: float | None,
    roof_prior_mean: float | None,
    nuisance_penalty: float,
):
    value = configured_profile()
    roof_bounds = ClosedInterval(lower=1.2, upper=1.8)
    fields = (
        NuisanceField(
            name="vehicle_width",
            unit="m",
            bounds=width_bounds,
            scale=0.25,
            prior=_prior(width_prior_mean, max((width_bounds.upper - width_bounds.lower) / 3.0, 0.05)),
        ),
        NuisanceField(
            name="delta_z_cam",
            unit="m",
            bounds=calibration_bounds,
            scale=0.05,
            prior=_prior(
                calibration_prior_mean,
                max((calibration_bounds.upper - calibration_bounds.lower) / 3.0, 0.01),
            ),
        ),
        NuisanceField(
            name="roof_height_m",
            unit="m",
            bounds=roof_bounds,
            scale=0.1,
            prior=_prior(roof_prior_mean, 0.2),
        ),
    )
    optimizer = replace(
        value.optimizer,
        sampled_candidate_budget=4,
        retained_candidate_count=4,
        robust=replace(value.optimizer.robust, nuisance_penalty=nuisance_penalty),
        optimizer=replace(
            value.optimizer.optimizer,
            parameter_scale=(1.0, 1.0, 1.0, 0.25, 0.05, 0.1),
        ),
    )
    return replace(
        value,
        nuisance=NuisanceProfile(version="property-8-nuisance-v1", fields=fields),
        optimizer=optimizer,
    )


_BASE_PROFILE = _profile(
    width_bounds=ClosedInterval(lower=1.0, upper=2.5),
    calibration_bounds=ClosedInterval(lower=-0.3, upper=0.3),
    width_prior_mean=None,
    calibration_prior_mean=None,
    roof_prior_mean=None,
    nuisance_penalty=1.0,
)
_BASE_TOKEN = validate_before_read(_BASE_PROFILE, _SCOPE)
_BASE_RECORD = record(_BASE_PROFILE, _TEMPLATE)
_BASE_GENERATION = DirectImageHypothesisGenerator(_PROJECTOR).generate(
    _BASE_RECORD,
    _TEMPLATE,
    token=_BASE_TOKEN,
    profile=_BASE_PROFILE,
    scope=_SCOPE,
    seed_profile=seed_profile(),
)


@st.composite
def nuisance_profiles(draw):
    width_lower = draw(bounded_floats(0.9, 1.2))
    width_upper = draw(bounded_floats(2.1, 2.8))
    calibration_lower = draw(bounded_floats(-0.4, -0.05))
    calibration_upper = draw(bounded_floats(0.05, 0.4))
    width_bounds = ClosedInterval(lower=width_lower, upper=width_upper)
    calibration_bounds = ClosedInterval(
        lower=calibration_lower, upper=calibration_upper
    )
    width_mean = draw(st.one_of(st.none(), bounded_floats(width_lower, width_upper)))
    calibration_mean = draw(st.one_of(
        st.none(), bounded_floats(calibration_lower, calibration_upper)
    ))
    roof_mean = draw(st.one_of(st.none(), bounded_floats(1.2, 1.8)))
    return _profile(
        width_bounds=width_bounds,
        calibration_bounds=calibration_bounds,
        width_prior_mean=width_mean,
        calibration_prior_mean=calibration_mean,
        roof_prior_mean=roof_mean,
        nuisance_penalty=draw(bounded_floats(0.25, 2.0)),
    )


def _schur_pose_information(information: np.ndarray, tolerance: float) -> np.ndarray:
    nuisance = 0.5 * (information[3:, 3:] + information[3:, 3:].T)
    eigenvalues, eigenvectors = np.linalg.eigh(nuisance)
    inverse_values = np.zeros_like(eigenvalues)
    retained = eigenvalues > tolerance
    inverse_values[retained] = 1.0 / eigenvalues[retained]
    nuisance_inverse = (eigenvectors * inverse_values) @ eigenvectors.T
    result = (
        information[:3, :3]
        - information[:3, 3:] @ nuisance_inverse @ information[3:, :3]
    )
    return 0.5 * (result + result.T)


def _bounded_parameterization(generated, profile_value):
    """Return the codec after checking every available pre-fit value and bound."""
    fields = {field.name: field for field in profile_value.nuisance.fields}
    seed_values = dict(generated.seed.nuisance.values)
    unknown_seed_names = set(seed_values).difference(fields)
    assert not unknown_seed_names, (
        f"seed published unknown nuisance names: {sorted(unknown_seed_names)}"
    )
    for name, value in seed_values.items():
        assert fields[name].bounds.contains(value)

    parameterization = _parameterization(
        generated, _TEMPLATE, profile_value, refinement_bounds()
    )
    specs = parameterization.parameter_specs
    nuisance_specs = specs[3:]
    assert tuple(spec.name for spec in nuisance_specs) == tuple(fields)
    assert len(specs) == 3 + len(fields)
    for spec, field in zip(nuisance_specs, profile_value.nuisance.fields):
        assert spec.name == field.name
        assert spec.unit == field.unit
        assert spec.bounds == field.bounds
        assert spec.scale == field.scale

    initial = parameterization.initial_values
    lower = parameterization.lower_bounds
    upper = parameterization.upper_bounds
    assert initial.shape == lower.shape == upper.shape == (len(specs),)
    assert np.isfinite(initial).all()
    assert np.isfinite(lower).all()
    assert np.isfinite(upper).all()
    assert np.all(lower <= initial)
    assert np.all(initial <= upper)
    assert np.all(lower <= upper)
    for index, spec in enumerate(specs):
        assert lower[index] == spec.bounds.lower
        assert upper[index] == spec.bounds.upper
    for index, field in enumerate(profile_value.nuisance.fields, start=3):
        assert field.bounds.contains(initial[index])

    decoded = parameterization.decode(initial)
    point_by_id = {point.semantic_id: point for point in _TEMPLATE.points}
    for index, correspondence in enumerate(generated.path.correspondence):
        family = point_by_id[correspondence.template_semantic_id].cue_family
        if family in (CueFamily.WHEEL, CueFamily.GROUND_CONTACT):
            assert decoded.template_points[index, 1] == 0.0
    return parameterization


@deterministic_property(8)
@given(profile_value=nuisance_profiles())
def test_nuisance_bounds_and_uncertainty_propagation(profile_value) -> None:
    """**Validates: Requirements 4.1-4.8, 6.5**"""
    token = validate_before_read(profile_value, _SCOPE)
    report = BoundedScipyRefiner(_PROJECTOR).refine(
        _BASE_GENERATION,
        _BASE_RECORD,
        _TEMPLATE,
        token=token,
        profile=profile_value,
        scope=_SCOPE,
        bounds=refinement_bounds(),
    )
    record_failure_metadata(
        replay_identity=_BASE_RECORD,
        profile_identity=profile_value,
        run_identity=report,
    )

    fields = {field.name: field for field in profile_value.nuisance.fields}
    expected_roles = {
        "vehicle_width": "dimension",
        "delta_z_cam": "calibration",
        "roof_height_m": "height",
    }
    ground_specs = tuple(
        spec for spec in profile_value.cue_evidence.height_specs
        if spec.cue_family in (CueFamily.WHEEL, CueFamily.GROUND_CONTACT)
    )
    assert ground_specs
    assert all(
        spec.height_m == ClosedInterval(lower=0.0, upper=0.0)
        for spec in ground_specs
    )
    assert not any(
        ("wheel" in name.casefold() or "ground" in name.casefold())
        and "height" in name.casefold()
        for name in fields
    )

    generated_by_id = {
        hypothesis.path.path_id: hypothesis
        for hypothesis in _BASE_GENERATION.hypotheses
    }
    outcomes = (*report.refined, *report.failures)
    outcome_ids = tuple(outcome.path.path_id for outcome in outcomes)
    assert len(outcome_ids) == len(set(outcome_ids))
    assert set(outcome_ids) == set(report.retained_path_ids)
    assert {
        generated_by_id[path_id].path.seed_class
        for path_id in report.retained_path_ids
    } == set(SeedClass)

    allowed_failure_reasons = {
        "invalid_projection",
        "non_finite_optimization",
        "numerical_optimization_failure",
        "optimization_not_converged",
    }
    for failure in report.failures:
        assert isinstance(failure, RefinementFailure)
        assert not failure.authoritative
        assert failure.reason in allowed_failure_reasons
        assert failure.detail.strip()
        assert failure.settings is not None
        if failure.exception_type is not None:
            assert failure.exception_type.strip()
        generated = generated_by_id[failure.path.path_id]
        parameterization = _bounded_parameterization(generated, profile_value)
        assert failure.settings.parameter_names == tuple(
            spec.name for spec in parameterization.parameter_specs
        )

    point_by_id = {point.semantic_id: point for point in _TEMPLATE.points}
    for candidate in report.refined:
        assert isinstance(candidate, RefinedCandidate)
        assert not candidate.authoritative
        generated = generated_by_id[candidate.path.path_id]
        parameterization = _bounded_parameterization(generated, profile_value)

        values = dict(candidate.parameter_values)
        published_nuisance = dict(candidate.nuisance.values)
        assert set(fields).issubset(values)
        # The published nuisance vector carries template geometry only. Fit-local
        # calibration deltas are applied to the fit's CalibrationSnapshot and reported
        # through parameter_values and observability.nuisance_treatments, because the
        # MVP never publishes a fitted calibration (design, "Parameterization and
        # bounded nuisances"). Requirement 4.8 is satisfied by that propagation, and the
        # observability assertions below check it for every authorized nuisance.
        calibration_names = set(profile_value.calibration.authorized_nuisance_fields)
        assert set(published_nuisance) == set(fields) - calibration_names
        for name, field in fields.items():
            assert field.bounds.contains(values[name])
            if name in published_nuisance:
                assert published_nuisance[name] == values[name]

        ordered_values = tuple(
            values[spec.name] for spec in parameterization.parameter_specs
        )
        decoded = parameterization.decode(ordered_values)
        for index, correspondence in enumerate(candidate.path.correspondence):
            family = point_by_id[correspondence.template_semantic_id].cue_family
            if family in (CueFamily.WHEEL, CueFamily.GROUND_CONTACT):
                assert decoded.template_points[index, 1] == 0.0

        diagnostics = candidate.observability
        assert diagnostics.parameter_names == tuple(
            spec.name for spec in parameterization.parameter_specs
        )
        assert not any(
            "wheel_height" in name or "ground_height" in name
            for name in diagnostics.parameter_names
        )
        treatment_by_name = {
            item.name: item for item in diagnostics.nuisance_treatments
        }
        assert set(treatment_by_name) == set(fields)
        precision_by_name = dict(zip(
            diagnostics.parameter_names,
            diagnostics.nuisance_prior_precision_scaled,
        ))
        for name, field in fields.items():
            treatment = treatment_by_name[name]
            assert treatment.role == expected_roles[name]
            assert treatment.unit == field.unit
            assert treatment.bounds == field.bounds
            assert treatment.prior == field.prior
            assert treatment.interval_treatment == "finite_closed_interval"
            assert treatment.uncertainty_propagation == "jacobian_schur_marginalized"
            expected_prior_treatment = (
                "none" if field.prior is None else "gaussian_quadratic"
            )
            assert treatment.prior_treatment == expected_prior_treatment
            expected_precision = 0.0 if field.prior is None else (
                profile_value.optimizer.robust.nuisance_penalty
                * (field.scale / field.prior.standard_deviation) ** 2
            )
            assert np.isclose(treatment.prior_precision_scaled, expected_precision)
            assert np.isclose(precision_by_name[name], expected_precision)

        information = np.asarray(diagnostics.information_scaled)
        expected_pose = _schur_pose_information(
            information, profile_value.optimizer.observability.rank_tolerance
        )
        np.testing.assert_allclose(
            diagnostics.information_pose, expected_pose, rtol=1e-10, atol=1e-10
        )
        assert np.asarray(diagnostics.image_residual_jacobian_scaled).shape[1] == 6
        covariance = np.asarray(diagnostics.covariance_pose)
        assert covariance.shape == (3, 3)
        assert np.isfinite(covariance).all()


class NuisanceBoundsAndUncertaintyPropagationPropertyTest(unittest.TestCase):
    def test_nuisance_bounds_and_uncertainty_propagation(self) -> None:
        test_nuisance_bounds_and_uncertainty_propagation()


if __name__ == "__main__":
    unittest.main()
