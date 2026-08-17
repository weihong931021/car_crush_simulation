"""Property 7: hypothesis budget allocation is deterministic and accountable."""
from __future__ import annotations

from dataclasses import dataclass, replace

from hypothesis import given, strategies as st
import numpy as np

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.test_haware_hypotheses import provenance, scope, seed_profile
from tests.test_haware_profile_validation import profile as base_profile
from trafficlab.motion.haware_accuracy.models import (
    CueFamily,
    CueHeightSpec,
    HypothesisState,
    ImageObservation,
    MinimalConfiguration,
    ObservationRecord,
    Pose2D,
    ProviderProvenance,
    SeedClass,
    SemanticPath,
    SemanticPathSpec,
    VehicleTemplate,
    VehicleTemplatePoint,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read
from trafficlab.motion.haware_hypotheses import DirectImageHypothesisGenerator
from trafficlab.projection.haware_forward import HawareForwardProjector


_NON_WHEEL_FAMILIES = (
    CueFamily.GLASS,
    CueFamily.WINDSHIELD,
    CueFamily.ROOF,
    CueFamily.MIRROR,
)
_TRUE_POSE = Pose2D(center_sat_px=(20.0, 30.0), heading_rad_unwrapped=0.35)
_SCOPE = scope()
_PROJECTOR = HawareForwardProjector()


@dataclass(frozen=True)
class BudgetCase:
    profile: object
    template: VehicleTemplate
    canonical_record: ObservationRecord
    permuted_record: ObservationRecord
    expected_combinations: frozenset[tuple[SemanticPath, tuple[CueFamily, ...], SeedClass]]


def _configured_case(family_count: int, semantic_count: int, budget: int):
    families = _NON_WHEEL_FAMILIES[:family_count]
    points = [
        VehicleTemplatePoint(
            semantic_id="wheel-left",
            position_m=(-1.0, 0.0, -1.4),
            cue_family=CueFamily.WHEEL,
        ),
        VehicleTemplatePoint(
            semantic_id="wheel-right",
            position_m=(1.0, 0.0, 1.4),
            cue_family=CueFamily.WHEEL,
        ),
    ]
    for family_index, family in enumerate(families):
        height = 0.8 + 0.1 * family_index
        points.extend((
            VehicleTemplatePoint(
                semantic_id=f"{family.value}-front",
                position_m=(-0.8 + 0.1 * family_index, height, -1.1),
                cue_family=family,
            ),
            VehicleTemplatePoint(
                semantic_id=f"{family.value}-rear",
                position_m=(0.8 - 0.1 * family_index, height, 1.1),
                cue_family=family,
            ),
        ))
    template = VehicleTemplate(version="property-7-template-v1", points=tuple(points))

    configurations = (
        MinimalConfiguration(
            configuration_id="non-wheel-pair",
            cue_families=families,
            minimum_support=2,
        ),
        MinimalConfiguration(
            configuration_id="wheel-pair",
            cue_families=(CueFamily.WHEEL,),
            minimum_support=2,
        ),
    )
    semantic_paths = tuple(
        SemanticPathSpec(semantic_path=semantic_path)
        for semantic_path in tuple(SemanticPath)[:semantic_count]
    )
    value = base_profile()
    mappings = tuple(
        (f"label-{point.semantic_id}", point.semantic_id) for point in points
    )
    height_specs = (
        CueHeightSpec(
            cue_family=CueFamily.WHEEL,
            height_m=replace_interval(0.0, 0.0),
            evidence=provenance("property-7-wheel-height"),
        ),
        *(CueHeightSpec(
            cue_family=family,
            height_m=replace_interval(0.7 + 0.1 * index, 0.9 + 0.1 * index),
            evidence=provenance(f"property-7-{family.value}-height"),
        ) for index, family in enumerate(families)),
    )
    cue_evidence = replace(
        value.cue_evidence,
        semantic_mappings=mappings,
        height_specs=height_specs,
        minimal_configurations=configurations,
    )
    optimizer = replace(
        value.optimizer,
        hypothesis_budget=budget,
        minimal_configurations=configurations,
        semantic_paths=semantic_paths,
    )
    return replace(value, cue_evidence=cue_evidence, optimizer=optimizer), template


def replace_interval(lower: float, upper: float):
    from trafficlab.motion.haware_accuracy.models import ClosedInterval

    return ClosedInterval(lower=lower, upper=upper)


def _record(profile, template: VehicleTemplate) -> ObservationRecord:
    height_by_family = {
        spec.cue_family: 0.5 * (spec.height_m.lower + spec.height_m.upper)
        for spec in profile.cue_evidence.height_specs
    }
    direct_points = np.asarray([
        (point.position_m[0], height_by_family[point.cue_family], point.position_m[2])
        for point in template.points
    ], dtype=np.float64)
    pixels = _PROJECTOR.predict_pixels(
        _TRUE_POSE, direct_points, profile.calibration.snapshot
    ).pixels
    observations = tuple(
        ImageObservation(
            observation_id=f"obs-{index:02d}",
            pixel=(float(pixel[0]), float(pixel[1])),
            confidence=1.0,
            candidate_labels=(f"label-{point.semantic_id}",),
            provider_key=f"provider-{index:02d}",
        )
        for index, (point, pixel) in enumerate(zip(template.points, pixels))
    )
    return ObservationRecord(
        site="kee-cc",
        source_sequence="property-7-sequence",
        frame_id="property-7-frame",
        detection_id="property-7-detection",
        image_size_px=(1920, 1080),
        observations=observations,
        provider=ProviderProvenance(
            provider_name="property-provider",
            provider_version="1",
            adapter_version="1",
        ),
        source=provenance("property-7-record"),
    )


def _expected_combinations(families, semantic_paths):
    cue_subsets = tuple((family,) for family in families) + tuple(
        tuple(sorted((families[left], families[right]), key=lambda item: item.value))
        for left in range(len(families))
        for right in range(left + 1, len(families))
    )
    return frozenset(
        (
            semantic_path,
            (CueFamily.WHEEL,),
            SeedClass.WHEEL,
        )
        for semantic_path in semantic_paths
    ) | frozenset(
        (semantic_path, cue_subset, SeedClass.NON_WHEEL)
        for semantic_path in semantic_paths
        for cue_subset in cue_subsets
    )


@st.composite
def oversized_budget_cases(draw):
    family_count = draw(st.integers(min_value=2, max_value=len(_NON_WHEEL_FAMILIES)))
    semantic_count = draw(st.integers(min_value=1, max_value=len(SemanticPath)))
    families = _NON_WHEEL_FAMILIES[:family_count]
    semantic_paths = tuple(SemanticPath)[:semantic_count]
    expected = _expected_combinations(families, semantic_paths)
    reserve = 2 * semantic_count
    budget = draw(st.integers(min_value=reserve, max_value=len(expected) - 1))
    profile, template = _configured_case(family_count, semantic_count, budget)
    canonical_record = _record(profile, template)
    permutation = draw(st.permutations(canonical_record.observations))
    permuted_record = replace(canonical_record, observations=tuple(permutation))
    return BudgetCase(
        profile=profile,
        template=template,
        canonical_record=canonical_record,
        permuted_record=permuted_record,
        expected_combinations=expected,
    )


def _combination(path):
    return path.semantic_path, path.cue_subset, path.seed_class


def _generate(case: BudgetCase, record_value: ObservationRecord):
    token = validate_before_read(case.profile, _SCOPE)
    return DirectImageHypothesisGenerator(_PROJECTOR).generate(
        record_value,
        case.template,
        token=token,
        profile=case.profile,
        scope=_SCOPE,
        seed_profile=seed_profile(),
    )


@deterministic_property(7)
@given(case=oversized_budget_cases())
def test_deterministic_accountable_hypothesis_budgets(case: BudgetCase) -> None:
    """**Validates: Requirements 5.1, 5.8-5.9, 5.12, 6.2, 6.8**"""
    result = _generate(case, case.permuted_record)
    canonical_result = _generate(case, case.canonical_record)
    report = result.report
    budget = case.profile.optimizer.hypothesis_budget
    record_failure_metadata(
        replay_identity=case.permuted_record,
        profile_identity=case.profile,
        run_identity=report,
    )

    assert len(case.expected_combinations) > budget
    assert len(report.stable_order) == budget
    assert len(report.generated_paths) == budget
    assert len(result.hypotheses) == budget
    assert not result.invalid_paths
    assert tuple(path.path_id for path in report.generated_paths) == report.stable_order

    terminal_by_combination = {
        _combination(path): path for path in report.authorized_paths
    }
    assert len(terminal_by_combination) == len(report.authorized_paths)
    assert set(terminal_by_combination) == set(case.expected_combinations)

    generated = {
        combination
        for combination, path in terminal_by_combination.items()
        if path.terminal_state is HypothesisState.GENERATED
    }
    excluded = {
        combination
        for combination, path in terminal_by_combination.items()
        if path.terminal_state is HypothesisState.BUDGET_EXCLUDED
    }
    assert generated == {_combination(path) for path in report.generated_paths}
    assert excluded == {_combination(path) for path in report.budget_exclusions}
    assert generated.isdisjoint(excluded)
    assert generated | excluded == set(case.expected_combinations)
    assert all(
        path.terminal_state is HypothesisState.BUDGET_EXCLUDED
        and path.terminal_reason == "hypothesis_budget_exceeded"
        for path in report.budget_exclusions
    )

    for semantic_spec in case.profile.optimizer.semantic_paths:
        surviving_seed_classes = {
            seed_class
            for semantic_path, _cue_subset, seed_class in generated
            if semantic_path is semantic_spec.semantic_path
        }
        assert surviving_seed_classes == {SeedClass.WHEEL, SeedClass.NON_WHEEL}

    assert result.canonical_bytes() == canonical_result.canonical_bytes()


import unittest


class DeterministicAccountableHypothesisBudgetsPropertyTest(unittest.TestCase):
    def test_property_7(self) -> None:
        test_deterministic_accountable_hypothesis_budgets()


if __name__ == "__main__":
    unittest.main()
