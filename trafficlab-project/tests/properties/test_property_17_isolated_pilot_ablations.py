"""Property 17: pilot ablations isolate one initialization class."""
from __future__ import annotations

from dataclasses import fields, replace
import unittest

from hypothesis import given, strategies as st

from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.test_haware_pilot import (
    complete_fixture,
    policy,
)
from tests.test_haware_profile_validation import (
    profile as acceptance_profile,
    scope as mvp_scope,
)
from trafficlab.measurement.haware_pilot import (
    PilotArm,
    PilotCandidateConfiguration,
    PilotPopulationFreezer,
    run_frozen_pilot_arms,
)
from trafficlab.motion.haware_accuracy.models import (
    ContentIdentity,
    PartitionKind,
    canonical_order,
)
from trafficlab.motion.haware_accuracy.validation import (
    resolve_optimizer_dispatch,
    validate_before_read,
)


SITES = ("kee-cc", "taoyuan-tc")
OPTIMIZER_ARMS = (
    PilotArm.FULL_OPTIMIZER,
    PilotArm.WHEEL_INITIALIZATION_DISABLED,
    PilotArm.NON_WHEEL_INITIALIZATION_DISABLED,
)


def _content_identity(value: int) -> ContentIdentity:
    return ContentIdentity(f"{value:064x}")


def _frozen_evidence():
    records, ground_truth, assignments, views = complete_fixture()
    # Property 17 concerns all four pilot arms at both acceptance sites. Keep
    # every eligible fixture record in the pilot partition so execution order,
    # as well as arm identity, is exercised for each site.
    pilot_assignments = tuple(
        replace(value, partition=PartitionKind.PILOT) for value in assignments
    )
    return PilotPopulationFreezer().freeze(
        replay_records=records,
        ground_truth=ground_truth,
        policies=tuple(policy(site) for site in SITES),
        partition_assignments=pilot_assignments,
        independent_views=views,
    )


FROZEN_EVIDENCE = _frozen_evidence()


def _generated_profile(
    site: str,
    *,
    seed: int,
    loss: str,
    support_boundary_px: float,
    support_includes_equality: bool,
    outlier_penalty: float,
    nuisance_penalty: float,
):
    base = acceptance_profile(site)
    robust = replace(
        base.optimizer.robust,
        loss=loss,
        support_boundary_px=support_boundary_px,
        support_includes_equality=support_includes_equality,
        outlier_penalty=outlier_penalty,
        nuisance_penalty=nuisance_penalty,
    )
    return replace(
        base,
        optimizer=replace(
            base.optimizer,
            robust=robust,
            deterministic_seed=seed,
        ),
    )


def _ordered_eligible_ids(partition: PartitionKind) -> tuple[str, ...]:
    return tuple(
        item.eligible_detection_id
        for site in FROZEN_EVIDENCE.sites
        for item in site.eligible_detections
        if item.partition is partition
    )


@deterministic_property(17)
@given(
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    loss=st.sampled_from(("linear", "huber", "soft_l1", "cauchy", "arctan")),
    support_boundary_px=st.sampled_from((0.5, 2.0, 8.0, 32.0)),
    support_includes_equality=st.booleans(),
    outlier_penalty=st.sampled_from((0.0, 1.0, 7.5)),
    nuisance_penalty=st.sampled_from((0.0, 0.25, 3.0)),
    replay_values=st.tuples(
        st.integers(min_value=0, max_value=2**256 - 1),
        st.integers(min_value=0, max_value=2**256 - 1),
    ),
    template_value=st.integers(min_value=0, max_value=2**256 - 1),
    runtime_values=st.lists(
        st.integers(min_value=0, max_value=2**256 - 1),
        min_size=1,
        max_size=3,
        unique=True,
    ),
    code_revision=st.text(alphabet="abcdef0123456789-", min_size=1, max_size=16),
)
def test_pilot_ablations_isolate_one_initialization_class(
    seed,
    loss,
    support_boundary_px,
    support_includes_equality,
    outlier_penalty,
    nuisance_penalty,
    replay_values,
    template_value,
    runtime_values,
    code_revision,
) -> None:
    """**Validates: Requirements 10.15-10.19**"""
    profiles = {
        site: _generated_profile(
            site,
            seed=seed,
            loss=loss,
            support_boundary_px=support_boundary_px,
            support_includes_equality=support_includes_equality,
            outlier_penalty=outlier_penalty,
            nuisance_penalty=nuisance_penalty,
        )
        for site in SITES
    }
    scope = mvp_scope()
    tokens = {
        site: validate_before_read(profile, scope)
        for site, profile in profiles.items()
    }
    replays = {
        site: _content_identity(value)
        for site, value in zip(SITES, replay_values)
    }
    template = _content_identity(template_value)
    runtime = tuple(_content_identity(value) for value in runtime_values)
    baseline_calls: list[str] = []
    optimizer_calls: list[tuple[str, PilotArm]] = []

    def baseline(record):
        eligible_id = f"{record.site}:{record.frame_id}:{record.detection_id}"
        baseline_calls.append(eligible_id)
        return record.detection_id

    def optimizer(record, profile, configuration, identity):
        eligible_id = f"{record.site}:{record.frame_id}:{record.detection_id}"
        assert profile is profiles[record.site]
        assert configuration == identity.candidate_configuration
        optimizer_calls.append((eligible_id, identity.arm))
        return record.detection_id

    result = run_frozen_pilot_arms(
        frozen_evidence=FROZEN_EVIDENCE,
        outcome_access=FROZEN_EVIDENCE.outcome_access,
        profiles=profiles,
        validated_profiles=tokens,
        scope=scope,
        replay_identities=replays,
        template_identity=template,
        code_revision=code_revision,
        runtime_dependencies=runtime,
        baseline_localize=baseline,
        optimizer_localize=optimizer,
    )
    metadata_identity = result.for_site(SITES[0]).arms[1].identity
    record_failure_metadata(
        replay_identity=FROZEN_EVIDENCE.outcome_access,
        profile_identity=profiles[SITES[0]],
        run_identity=metadata_identity,
    )

    pilot_ids = _ordered_eligible_ids(PartitionKind.PILOT)
    held_out_ids = set(_ordered_eligible_ids(PartitionKind.HELD_OUT))
    assert tuple(baseline_calls) == pilot_ids
    assert not set(baseline_calls).intersection(held_out_ids)
    expected_optimizer_calls = tuple(
        (item.eligible_detection_id, arm)
        for site in FROZEN_EVIDENCE.sites
        for arm in OPTIMIZER_ARMS
        for item in site.eligible_detections
        if item.partition is PartitionKind.PILOT
    )
    assert tuple(optimizer_calls) == expected_optimizer_calls
    assert not {
        eligible_id for eligible_id, _arm in optimizer_calls
    }.intersection(held_out_ids)
    assert result.optimizer_default_off_outside_pilot

    for site in SITES:
        profile = profiles[site]
        dispatch = resolve_optimizer_dispatch(profile.content_identity)
        assert not dispatch.optimizer_enabled
        assert dispatch.production_path == "corrected_legacy_baseline"
        assert dispatch.optimizer_output_role == "diagnostic_only"
        assert dispatch.reason == "optimizer_default_off"

        site_runs = result.for_site(site)
        expected_site_ids = tuple(
            item.eligible_detection_id
            for item in FROZEN_EVIDENCE.for_site(site).eligible_detections
            if item.partition is PartitionKind.PILOT
        )
        assert tuple(arm.identity.arm for arm in site_runs.arms) == tuple(PilotArm)
        assert all(
            arm.ordered_eligible_ids == expected_site_ids for arm in site_runs.arms
        )
        by_arm = {arm.identity.arm: arm.identity for arm in site_runs.arms}
        full = by_arm[PilotArm.FULL_OPTIMIZER]

        for identity in by_arm.values():
            run = identity.run
            assert run.replay == replays[site]
            assert run.profile == profile.content_identity
            assert run.template == template
            assert run.calibration == profile.calibration.content_identity
            assert run.cue_evidence == profile.cue_evidence.content_identity
            assert run.nuisance == profile.nuisance.content_identity
            assert run.code_revision == code_revision
            assert run.runtime_dependencies == tuple(
                canonical_order(runtime, unique=True)
            )
            assert run.deterministic_seed == seed
            assert identity.baseline_identity == full.baseline_identity
            assert identity.candidate_configuration.optimizer_profile == (
                profile.optimizer.content_identity
            )

        for arm, named_flag in (
            (
                PilotArm.WHEEL_INITIALIZATION_DISABLED,
                "wheel_seeded_initialization_enabled",
            ),
            (
                PilotArm.NON_WHEEL_INITIALIZATION_DISABLED,
                "non_wheel_seeded_initialization_enabled",
            ),
        ):
            ablation = by_arm[arm]
            changed = {
                item.name
                for item in fields(PilotCandidateConfiguration)
                if getattr(full.candidate_configuration, item.name)
                != getattr(ablation.candidate_configuration, item.name)
            }
            assert changed == {named_flag}
            assert full.run == ablation.run
            assert full.eligible_ordering == ablation.eligible_ordering
            assert full.scoring == ablation.scoring == profile.optimizer.robust.content_identity
            assert full.support_rules == ablation.support_rules
            assert full.gates == ablation.gates == profile.optimizer.content_identity
            assert full.metric_definitions == ablation.metric_definitions


class IsolatedPilotAblationsPropertyTest(unittest.TestCase):
    def test_property_17(self) -> None:
        test_pilot_ablations_isolate_one_initialization_class()


if __name__ == "__main__":
    unittest.main()
