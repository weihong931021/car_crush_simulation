"""Property 2: deterministic complete hypothesis generation."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from itertools import combinations, product
import math
import unittest

from hypothesis import given, strategies as st

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.test_haware_hypotheses import (
    configured_profile,
    record,
    scope,
    seed_profile,
    template,
)
from trafficlab.motion.haware_accuracy.models import (
    CueFamily,
    CueHeightSpec,
    HypothesisState,
    MinimalConfiguration,
    SeedClass,
    SemanticPath,
    VehicleTemplate,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read
from trafficlab.motion.haware_hypotheses import DirectImageHypothesisGenerator
from trafficlab.projection.haware_forward import HawareForwardProjector


_GROUND_FAMILIES = frozenset((CueFamily.WHEEL, CueFamily.GROUND_CONTACT))
_SEMANTIC_ORDER = {
    SemanticPath.NORMAL: 0,
    SemanticPath.REVERSED: 1,
    SemanticPath.HEADING_PI: 2,
}


@dataclass(frozen=True)
class GenerationCase:
    profile: object
    vehicle_template: VehicleTemplate
    canonical_record: object
    presented_record: object


def _semantic_specs(include_reversed: bool, include_heading_pi: bool):
    specs = configured_profile().optimizer.semantic_paths
    included = {SemanticPath.NORMAL}
    if include_reversed:
        included.add(SemanticPath.REVERSED)
    if include_heading_pi:
        included.add(SemanticPath.HEADING_PI)
    return tuple(spec for spec in specs if spec.semantic_path in included)


@st.composite
def generation_cases(draw):
    """Generate valid profiles with varied semantic, cue, and evidence strata."""
    profile_value = configured_profile()
    vehicle_template = template()
    semantic_specs = _semantic_specs(
        draw(st.booleans()), draw(st.booleans())
    )
    split_elevated_cues = draw(st.booleans())
    if split_elevated_cues:
        vehicle_template = replace(
            vehicle_template,
            points=tuple(
                replace(point, cue_family=CueFamily.GLASS)
                if point.semantic_id == "roof_front"
                else point
                for point in vehicle_template.points
            ),
        )
        minimal = (
            MinimalConfiguration(
                configuration_id="elevated-single",
                cue_families=(CueFamily.GLASS, CueFamily.ROOF),
                minimum_support=1,
            ),
            MinimalConfiguration(
                configuration_id="wheel-pair",
                cue_families=(CueFamily.WHEEL,),
                minimum_support=2,
            ),
        )
        cue_evidence = replace(
            profile_value.cue_evidence,
            height_specs=(
                *profile_value.cue_evidence.height_specs,
                CueHeightSpec(
                    cue_family=CueFamily.GLASS,
                    height_m=replace_interval(0.8, 1.4),
                    evidence=profile_value.cue_evidence.provenance[0],
                ),
            ),
            minimal_configurations=minimal,
        )
    else:
        minimal = profile_value.optimizer.minimal_configurations
        cue_evidence = profile_value.cue_evidence

    profile_value = replace(
        profile_value,
        cue_evidence=cue_evidence,
        optimizer=replace(
            profile_value.optimizer,
            hypothesis_budget=2 * len(semantic_specs),
            minimal_configurations=minimal,
            semantic_paths=semantic_specs,
        ),
    )
    complete_record = record(profile_value, vehicle_template)
    evidence = draw(st.sampled_from(("both", "wheel", "elevated")))
    retained = tuple(
        observation
        for observation in complete_record.observations
        if evidence == "both"
        or (evidence == "wheel" and observation.observation_id in {"obs-0", "obs-1"})
        or (evidence == "elevated" and observation.observation_id in {"obs-2", "obs-3"})
    )
    presentation = draw(st.permutations(retained))
    presentation = tuple(
        replace(
            observation,
            candidate_labels=tuple(reversed(observation.candidate_labels)),
        )
        if draw(st.booleans())
        else observation
        for observation in presentation
    )
    return GenerationCase(
        profile=profile_value,
        vehicle_template=vehicle_template,
        canonical_record=replace(complete_record, observations=retained),
        presented_record=replace(complete_record, observations=presentation),
    )


def replace_interval(lower: float, upper: float):
    from trafficlab.motion.haware_accuracy.models import ClosedInterval

    return ClosedInterval(lower=lower, upper=upper)


def _expected_combinations(case: GenerationCase):
    """Derive authorized aggregate combinations independently from observations."""
    profile_value = case.profile
    template_by_id = {
        point.semantic_id: point for point in case.vehicle_template.points
    }
    candidate_map: dict[str, set[str]] = {}
    for label, semantic_id in profile_value.cue_evidence.semantic_mappings:
        candidate_map.setdefault(label, set()).add(semantic_id)

    expected = set()
    for semantic_spec in profile_value.optimizer.semantic_paths:
        reversal = dict(semantic_spec.front_rear_mapping)
        for configuration in profile_value.optimizer.minimal_configurations:
            for seed_class in SeedClass:
                options = []
                for observation in case.canonical_record.observations:
                    semantic_ids = set()
                    for label in observation.candidate_labels:
                        for normal_id in candidate_map.get(label, ()):
                            semantic_id = (
                                reversal.get(normal_id, normal_id)
                                if semantic_spec.semantic_path is SemanticPath.REVERSED
                                else normal_id
                            )
                            point = template_by_id.get(semantic_id)
                            if point is None or point.cue_family not in configuration.cue_families:
                                continue
                            is_ground = point.cue_family in _GROUND_FAMILIES
                            if (seed_class is SeedClass.WHEEL) == is_ground:
                                semantic_ids.add(semantic_id)
                    if semantic_ids:
                        options.append((observation, tuple(sorted(semantic_ids))))

                for selected in combinations(options, configuration.minimum_support):
                    for semantic_ids in product(*(item[1] for item in selected)):
                        if len(set(semantic_ids)) != len(semantic_ids):
                            continue
                        families = frozenset(
                            template_by_id[semantic_id].cue_family.value
                            for semantic_id in semantic_ids
                        )
                        expected.add((
                            semantic_spec.semantic_path.value,
                            families,
                            seed_class.value,
                        ))
    return expected


def _combination(path):
    return (
        path.semantic_path.value,
        frozenset(family.value for family in path.cue_subset),
        path.seed_class.value,
    )


def _generate(case: GenerationCase, observation_record):
    scope_value = scope()
    token = validate_before_read(case.profile, scope_value)
    return DirectImageHypothesisGenerator(HawareForwardProjector()).generate(
        observation_record,
        case.vehicle_template,
        token=token,
        profile=case.profile,
        scope=scope_value,
        seed_profile=seed_profile(),
    )


def _canonical_attempt_key(path):
    source = path.initialization_source
    return (
        0 if path.seed_class is SeedClass.WHEEL else 1,
        _SEMANTIC_ORDER[path.semantic_path],
        tuple(family.value for family in path.cue_subset),
        path.minimal_observations,
        source.source_cell or "",
        source.start_heading_rad if source.start_heading_rad is not None else -math.inf,
        path.path_id,
    )


def _assert_frozen_minimal_seeds(case: GenerationCase, result) -> None:
    configurations = {
        configuration.configuration_id: configuration
        for configuration in case.profile.optimizer.minimal_configurations
    }
    template_by_id = {
        point.semantic_id: point for point in case.vehicle_template.points
    }
    height_intervals = {
        spec.cue_family: spec.height_m
        for spec in case.profile.cue_evidence.height_specs
    }
    generated_ids = {path.path_id for path in result.report.generated_paths}
    assert generated_ids == {item.path.path_id for item in result.hypotheses}
    assert tuple(item.seed.generation_ordinal for item in result.hypotheses) == tuple(
        range(len(result.hypotheses))
    )

    for hypothesis in result.hypotheses:
        path = hypothesis.path
        prefix = "direct_cctv_minimal:"
        assert path.initialization_source.method.startswith(prefix)
        configuration_id = path.initialization_source.method[len(prefix):]
        assert configuration_id in configurations
        configuration = configurations[configuration_id]
        assert len(path.minimal_observations) == configuration.minimum_support
        assert set(path.cue_subset).issubset(configuration.cue_families)
        assert path.initialization_source.observation_ids == path.minimal_observations
        assert {item.observation_id for item in path.correspondence} == set(
            path.minimal_observations
        )
        assert path.initialization_source.source_cell in {
            cell.cell_id for cell in seed_profile().search_cells
        }
        assert path.initialization_source.start_heading_rad is not None
        assert hypothesis.seed.nuisance.values == ()
        assert hypothesis.seed.path_id == path.path_id

        expected_heights = {}
        for correspondence in path.correspondence:
            family = template_by_id[correspondence.template_semantic_id].cue_family
            assert family in configuration.cue_families
            assert (path.seed_class is SeedClass.WHEEL) == (
                family in _GROUND_FAMILIES
            )
            interval = height_intervals[family]
            expected_heights[correspondence.observation_id] = (
                0.0
                if family in _GROUND_FAMILIES
                else 0.5 * (interval.lower + interval.upper)
            )
        assert dict(hypothesis.cue_heights_m) == expected_heights


@deterministic_property(2)
@given(case=generation_cases())
def test_deterministic_complete_hypothesis_generation(case: GenerationCase) -> None:
    """**Validates: Requirements 1.16, 5.2-5.8, 5.11-5.12, 6.7, 6.11-6.12**"""
    result = _generate(case, case.presented_record)
    canonical_result = _generate(case, case.canonical_record)
    record_failure_metadata(
        replay_identity=case.canonical_record,
        profile_identity=case.profile,
        run_identity=result.report,
    )

    terminal_counts = Counter(
        _combination(path) for path in result.report.authorized_paths
    )
    expected = _expected_combinations(case)
    assert set(terminal_counts) == expected
    assert all(count == 1 for count in terminal_counts.values())
    assert all(
        path.terminal_state in HypothesisState
        for path in result.report.authorized_paths
    )
    assert all(
        path.terminal_state is HypothesisState.BUDGET_EXCLUDED
        and path.terminal_reason == "hypothesis_budget_exceeded"
        for path in result.report.budget_exclusions
    )

    attempts = {
        path.path_id: path
        for path in (*result.report.generated_paths, *result.invalid_paths)
    }
    assert set(attempts) == set(result.report.stable_order)
    ordered_paths = tuple(attempts[path_id] for path_id in result.report.stable_order)
    assert ordered_paths == tuple(sorted(ordered_paths, key=_canonical_attempt_key))
    _assert_frozen_minimal_seeds(case, result)

    assert result.canonical_bytes() == canonical_result.canonical_bytes()


class DeterministicCompleteHypothesisGenerationPropertyTest(unittest.TestCase):
    def test_property_2(self) -> None:
        test_deterministic_complete_hypothesis_generation()


if __name__ == "__main__":
    unittest.main()
