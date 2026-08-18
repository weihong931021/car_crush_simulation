# Implementation Plan: Haware Localization Accuracy

## Overview

Build the smallest credible Python feasibility-first MVP under `trafficlab-project/**`: deterministic provider-neutral stored observations, a pure calibrated CCTV image-space forward model, deterministic wheel-first/non-wheel-inclusive hypothesis generation, bounded robust refinement, strict coordinate authority, and a leak-free offline pilot for `kee-cc` and `taoyuan-tc`. Existing `localize()` and `localize_reprojection()` remain frozen baselines only; optimizer-disabled dispatch preserves the corrected `localize()` behavior and legacy schema exactly.

The Pose_Optimizer call graph must not introduce inverse-lifted per-keypoint ground targets, projected-point Procrustes, `RoleConstraintGraph`, geometry-mode selection, `wheel_only`, `wheel_weighted`, a wheel score bonus, or a wheel-based acceptance shortcut. Wheel-first means only generation/initialization order with `h=0`; valid non-wheel hypotheses are always generated and compete under the same score. A wheel-weighted Procrustes **is** implemented — as the diagnostic candidate arm `wheel_weighted_procrustes` in `trafficlab/measurement/haware_diagnostic_candidates.py` (Requirement 12), outside the optimizer call graph and outside production dispatch.

**2026-08-16 revision.** The spec critique (see `design.md` Overview) added: the standalone `legacy-localize-v1` status policy (production would otherwise lose every `position_m`), the `tools/build_scene.py` last-mile binding, tracker-provenance emission from `eval_haware_replay.py`, the GT annotation protocol, `pilot-stats-v1` with a Minimum_Effect_Of_Interest and Paired_Accepted_Set, Source_Sequence-based held-out feasibility, the diagnostic candidate arm, the 600 s batch runtime envelope, and three simplifications (held-out access-control layer removed in favour of a commit-SHA rule; the former production-hardening/deferred-capability requirements replaced by the "Scope boundary and later phases" section — the numbers 12/13 now denote the diagnostic-candidate and runtime requirements; byte-exact replay weakened to value equality). Tasks touched by those changes are re-opened as `[-]` with a "re-opened" note; new tasks are `[ ]`.

**2026-08-17 second review.** An independent reviewer found 15 further problems (design.md Appendix A.2); all are now applied. The ones that change how work is done: one estimand and one inference method (whole-track bootstrap, ≥ 8 clusters per effect, no sign-flip); the MEI decision trichotomy; `Capture_ID`-disjoint held-out partitions; a calibration sensitivity sweep whenever GT is calibration-conditional; a measured full-video runtime gate on production authorization; an append-only held-out exposure ledger; `Position_Equivalent_Ambiguity` so a heading tie no longer discards a usable position; and a fully specified site calibration health check.

## Tasks

- [-] 1. Establish immutable MVP contracts and validated profiles
  - [x] 1.1 Implement canonical immutable models and serialization primitives
    - Create `trafficlab/motion/haware_accuracy/models.py` with frozen Python dataclasses/enums for observations, provenance, profiles, calibration snapshots, templates, poses, nuisances, hypotheses, diagnostics, localization results, populations, and decisions.
    - Implement finite-number validation, canonical set-like ordering, semantic-array preservation, version/content identities, and accepted/rejected coordinate-role invariants without building a generalized artifact platform.
    - **Depends on:** none
    - _Requirements: 1.1-1.6, 2.1-2.6, 4.1-4.8, 5.1, 6.1-6.6, 7.1-7.7, 10.19, 11.2, 11.5_

  - [x] 1.2 Implement fail-fast profile validation and default-off scope guards
    - Validate all closed nuisance bounds, ground-contact `[0,0]`, supported distortion/homography data, explicit SciPy settings, budgets, stable ordering, gate precedence, replay bounds, and acceptance-site namespaces before records or outcomes are read.
    - Reject prohibited estimator contracts (`wheel_only`, `wheel_weighted`, projected-point Procrustes, `RoleConstraintGraph`, inverse-lifted targets) **within `OptimizerProfile` / estimator contracts only**; permit `wheel_weighted_procrustes` under `PilotPolicy.diagnostic_candidates`; keep calibration variation local to a fit.
    - Encode `taipei-cm` as diagnostic-only and optimizer dispatch as default-off unless the exact candidate has held-out `go` at both `kee-cc` and `taoyuan-tc`.
    - **Depends on:** 1.1
    - _Requirements: 3.7-3.9, 4.15-4.18, 6.1-6.12, 9.14-9.18, 10.29-10.31, 11.1-11.7, 12.4; Scope boundary section_
    - **Partly delivered 2026-08-17** (`tests/test_haware_profile_validation.py::NarrowedEstimatorProhibitionTest`, `::RevisedProfileFieldsTest`, 9 tests). Done: the prohibition now matches with an explicit `ALLOWED_ESTIMATOR_TERMS = ('wheel_weighted_procrustes',)` allowlist instead of a bare substring scan, and `validate_before_read` finally scans `profile.optimizer` itself — the old scan reached only the scope guard's declared terms, so a prohibited mode could ride in on the very profile it was meant to police (verified: it did not raise). `OptimizerProfile` gained `validity_gate_set` / `wheel_seeded_enabled` / `non_wheel_seeded_enabled` (rejecting an empty gate set and both-classes-disabled), `PilotPolicy` gained `diagnostic_candidates` + `diagnostic_candidate_params` (tuple-of-pairs, since a Mapping field makes the frozen model unhashable) with a both-ways consistency check, and `AcceptanceProfile` gained `acceptance_sites` / `candidate_site_pool` (exactly two, drawn from the pool, `taipei-cm` permanently ineligible).
    - **Completed 2026-08-17** (`::FrozenRuntimeAndSweepFieldsTest`, 4 more tests; suite 245, OK): new `PreGateBound` / `SceneExportSettings` / `ReferenceMachine` models, `CalibrationProfile.pre_gate`, `AcceptanceProfile.scene_export` / `batch_runtime_envelope_s_per_s` / `reference_machine`, and the whole `PilotPolicy` statistics block (interval method pinned to `whole_track_cluster_bootstrap_v1`, cluster floor 8, resample budget, MEI table, `position_ambiguity_tolerance_m` validated at `<= MEI/2`, ascending `scene_region_bands_m`, calibration-health constants). Deleting the deferred-capability machinery (`DEFERRED_CAPABILITIES`, `MvpScopeGuard.enabled_deferred_capabilities`, `EvidenceGateDecision`) belongs to task 6.7.
  - [x] 1.3 Configure deterministic property-test support
    - Pin the exact Hypothesis version in the project dependency/lock files and add bounded strategies for valid/degenerate calibrations, poses, nuisances, observations, semantic alternatives, support boundaries, track provenance, populations, and decisions.
    - Configure at least 100 successful examples per deterministic CI seed and replayable failure metadata; keep each numbered design property in its own test module.
    - **Depends on:** 1.1
    - _Requirements: 6.30; Design Testing Strategy_

  - [-]* 1.4 Write unit tests for model, profile, and scope validation
    - Cover immutable/canonical values, non-finite data, open or inverted bounds, invalid ground heights, insufficient stratified budgets, implicit optimizer defaults, incomplete gate precedence, authority-state contradictions, prohibited modes/call paths, diagnostic-site isolation, and default-off behavior.
    - **Depends on:** 1.2
    - _Requirements: 3.7-3.9, 4.1-4.8, 4.15-4.18, 6.1-6.6, 6.27-6.29, 7.1-7.7, 12.4; Scope boundary section_

- [-] 2. Implement the narrow observation, replay, adapter, and track boundary
  - [-] 2.1 Implement the provider-neutral observation schema and deterministic replay reader/writer
    - Create `trafficlab/io/haware_observation_replay.py` with the frozen required/optional fields and numeric bounds (finite in-image coordinates, confidence in `[0,1]`); isolate invalid observations and invalid records at their required scopes with stable reasons.
    - Reject records with duplicate observation identities (`duplicate_observation_id`); normalize permutation-invariantly; write sorted-key UTF-8 JSON; **return per-record observation exclusions and reasons alongside the payload**; verify read/write equivalence by value in tests; record source path/content identity for read-only legacy inputs.
    - **Depends on:** 1.1, 1.2
    - _Requirements: 1.2-1.5, 2.1-2.10, 2.13-2.18_
    - **Re-opened 2026-08-16:** drop string/collection/max-observation bounds and the `non_deterministic_duplicate_resolution` / `replay_round_trip_mismatch` reasons; add the writer's exclusion return (the tasks.md finding "writer silently thins records" is now a requirement, 2.15).

  - [-] 2.2 Implement the sole PifPaf MVP adapter and one-way replay import
    - Create `trafficlab/inference/pifpaf_haware_adapter.py` as the only production module allowed to import PifPaf and map Apollo-24 records to candidate semantic labels without promoting confidence or labels to correspondence truth.
    - Add a one-way importer for existing TrafficLab replay records that records provider/source provenance and produces the narrow provider-neutral schema; the optimizer must depend only on normalized models/protocols.
    - **Depends on:** 2.1
    - _Requirements: 1.3-1.5, 2.5-2.12, 2.19-2.23_

  - [-] 2.3 Implement genuine-versus-pseudo track provenance finalization
    - Classify a track as real only with consistent tracker name/version, Source_Sequence, association provenance, and occurrence in more than one frame; classify frame-local `500+`, incomplete, inconsistent, and one-frame claims as pseudo with stable reasons.
    - Finalize classification over a complete replay before partitioning and expose pseudo/no-track data only to explicitly named frame-local diagnostics.
    - **Depends on:** 2.1, 2.7
    - _Requirements: 8.1-8.7, 8.10-8.13, 10.32_

  - [-]* 2.4 Write the property test for value-exact provider-neutral replay
    - **Property 11: Provider-neutral replay round trip is value-exact**
    - Generate bounded records and unordered equivalent presentations; verify value-equal round trips, `duplicate_observation_id` rejection, record isolation, and preservation of provider, semantic, frame, detection, source, and track provenance.
    - **Depends on:** 1.3, 2.1
    - **Validates: Requirements 1.4, 2.5, 2.6, 2.9, 2.10, 2.13, 2.15, 2.16, 2.17**
    - **Re-opened 2026-08-16:** relax byte-identity assertions to value equality.

  - [x]* 2.5 Write the property test for genuine track classification and exclusion
    - **Property 14: Genuine track classification and exclusion**
    - Generate complete/incomplete/inconsistent/one-frame and frame-local `500+` claims; prove pseudo-track changes cannot affect acceptance metrics, clustered intervals, power, partitions, or motion diagnostics.
    - **Depends on:** 1.3, 2.3
    - **Validates: Requirements 8.1-8.8, 8.10, 8.13, 10.32**

  - [x]* 2.6 Write replay/adapter integration tests
    - Import representative existing PifPaf replay fixtures, prove `500+` display IDs are pseudo, write/read replays, isolate malformed records, and replay without importing or invoking OpenPifPaf.
    - Verify production imports and writes never target root `pifpaf/**` or `location/**`.
    - **Depends on:** 2.2, 2.3
    - _Requirements: 1.2-1.5, 2.11-2.21, 8.1-8.7_

  - [ ] 2.7 Emit tracker provenance from the replay producer
    - Extend `scripts/eval_haware_replay.py` (its `ReplayWriter` payload) and `TrafficLabReplayImporter._legacy_track_claim` so every ByteTrack-matched detection carries `tracker_name='bytetrack'`, `tracker_version=<ultralytics.__version__>+sha256(Path(ultralytics.__file__).parent/'cfg/trackers/bytetrack.yaml')`, `source_sequence=<video path>+sha256`, `association_provenance='yolo_bbox_iou_match iou>=<--iou-threshold>'`; keep synthesized `500+` IDs frame-local; `finalize_track_provenance` must classify these REAL.
    - **Depends on:** 2.2
    - _Requirements: 8.1-8.4, 8.6, 8.14, 10.32_

  - [ ] 2.8 Generate, import, and content-address stored replays for kee-cc and taoyuan-tc
    - Command (per site, under `.venv-pifpaf`): `python scripts/eval_haware_replay.py --method geometric --yolo models/yolo11l-visdrone-ft.pt --g-proj location/<code>/G_projection_<code>.json --video location/<code>/footage/<code>.mp4 --out evidence/haware/replays/<code>/replay.json.gz` (adjust flag names to the script's actual CLI; the default `--yolo models/best.pt` does not exist); import through the one-way importer; record source lineage and sha256 in `evidence/haware/current_evidence_inventory.json`. These were wrongly listed as external blockers; the tools and the footage are in the repo.
    - **Depends on:** 2.7, 6.9
    - _Requirements: 2.19-2.21_

- [x] 3. Implement pure calibrated forward projection and bounded parameters
  - [x] 3.1 Implement immutable calibration snapshots and pure forward projection
    - Create `trafficlab/projection/haware_forward.py`; copy and validate `K`, `D`, `H`, `H_inv`, camera satellite point, camera height, and pixel scale from `GProjection` without mutating it.
    - Vectorize pose/template/nuisance transformation, camera-radial parallax, inverse homography, and repository-compatible distortion; return per-point validity and explicit failures for unsupported distortion, singular denominators, non-finite intermediates, or `h >= z_cam`.
    - **Depends on:** 1.1, 1.2
    - _Requirements: 1.6-1.8, 3.1-3.6, 4.1-4.8_

  - [x] 3.2 Implement scaled pose and bounded nuisance parameterization
    - Encode position in metres, an unwrapped local heading delta, bounded positive dimensions, non-ground cue heights, and only profile-authorized calibration deltas in frozen order/units/scales; keep ground-contact heights constant at zero.
    - Convert position back to satellite pixels once and normalize heading only at output; never publish fitted calibration or feed it back into site calibration.
    - **Depends on:** 1.2, 3.1
    - _Requirements: 3.1, 3.5, 3.6, 4.1-4.8_

  - [x]* 3.3 Write forward-projection parity and parameter-bound tests
    - Compare nominal predictions point-by-point with `GProjection.sat_to_cctv()` for `h=0`, nonzero heights, distortion, `kee-cc`, and `taoyuan-tc` calibration fixtures; cover invalid homographies, distortion layouts, height limits, exact nuisance endpoints, and north/east/arbitrary headings.
    - **Depends on:** 3.2
    - _Requirements: 1.6-1.8, 3.1-3.6, 4.1-4.8_

- [x] 4. Implement deterministic semantic and seed hypothesis generation
  - [x] 4.1 Implement semantic paths, cue subsets, and direct image-space seeds
    - Create `trafficlab/motion/haware_hypotheses.py` with normal, profile-defined front/rear reversed, and explicit heading-plus-180 paths; preserve correspondence and candidate-label provenance for every path.
    - Generate eligible wheel seeds first from frozen minimal CCTV-pixel equations with `h=0`, then generate eligible non-wheel seeds regardless of wheel presence, support, visibility, or later outlier status; permit all evidence-supported cue families.
    - Do not call baseline localizers or construct inverse-lifted ground points, projected-point fits, role constraints, geometry modes, or wheel-exclusive paths.
    - **Depends on:** 2.1, 3.2
    - _Requirements: 1.16-1.18, 2.22-2.23, 3.7-3.9, 4.9-4.18, 5.2-5.8, 6.7_

  - [x] 4.2 Implement deterministic stratified hypothesis budgeting and terminal-state accounting
    - Reserve budget across eligible semantic paths and both seed classes before canonical round-robin filling; wheel precedence controls emission order only and cannot consume the non-wheel stratum.
    - Record exactly one terminal state for every authorized semantic-path/cue-subset/seed-class combination and mark each omitted combination `hypothesis_budget_exceeded`.
    - **Depends on:** 4.1
    - _Requirements: 5.1, 5.8-5.12, 6.2, 6.8, 6.11-6.12_
  - [x]* 4.3 Write the property test for deterministic complete hypothesis generation
    - **Property 2: Deterministic complete hypothesis generation**
    - Verify every authorized combination has one terminal state, every generated seed uses a frozen minimal configuration, and equivalent observation permutations preserve canonical generation.
    - **Depends on:** 1.3, 4.2
    - **Validates: Requirements 1.16, 5.2-5.8, 5.11-5.12, 6.7, 6.11-6.12**

  - [x]* 4.4 Write the property test for non-exclusive wheel-first ordering
    - **Property 3: Wheel-first ordering is non-exclusive**
    - Verify the first eligible seed is wheel-seeded at exact `h=0` while applicable non-wheel paths are always generated and remain equally eligible despite wheel presence, support, or outlier status.
    - **Depends on:** 1.3, 4.2
    - **Validates: Requirements 1.17, 4.1, 4.9-4.12, 5.6-5.7**

  - [x]* 4.5 Write the property test for deterministic accountable hypothesis budgets
    - **Property 7: Hypothesis budget allocation is deterministic and accountable**
    - Generate oversized cross products; prove the budget is respected, semantic and seed strata survive, and generated plus budget-excluded paths exactly partition the authorized combinations under every permutation.
    - **Depends on:** 1.3, 4.2
    - **Validates: Requirements 5.1, 5.8-5.9, 5.12, 6.2, 6.8**

- [-] 5. Implement bounded robust refinement, scoring, observability, and selection
  - [x] 5.1 Implement deterministic minimal solving and bounded SciPy refinement
    - Create `trafficlab/motion/haware_optimizer.py` with direct image-space minimal seed solving and `scipy.optimize.least_squares(method='trf')` robust refinement under explicit finite bounds.
    - Freeze and pass every loss, scale, derivative, tolerance, step, iteration/candidate limit, retention key, parameter scale, seed, and runtime setting; translate numerical exceptions into typed non-authoritative failures.
    - **Depends on:** 3.2, 4.2
    - _Requirements: 3.1-3.10, 4.6-4.8, 6.2-6.12, 6.25-6.26_

  - [x] 5.2 Implement support/outlier diagnostics and one common comparison score
    - Apply the frozen pixel residual support boundary and equality policy, record every outlier/residual, reject insufficient support, and compute one robust score from residual loss, outlier penalty, and bounded nuisance prior cost.
    - Prohibit score terms or acceptance conditions based on wheel count, seed class, generation order, provider, or semantic-label confidence; retain visible wheel count only as diagnostics.
    - **Depends on:** 5.1
    - _Requirements: 1.18, 4.11-4.18, 5.10-5.12, 6.3-6.4, 6.13-6.15_

  - [x] 5.3 Implement Jacobian, information, marginalized covariance, and conditioning
    - Compute the frozen robust image-residual Jacobian and information matrix in scaled units, nuisance-marginalized pose information via the frozen Schur/pseudoinverse rule, rank, singular values, condition, covariance, position ellipse, heading uncertainty, and active-bound diagnostics.
    - Include every varied height/dimension/calibration nuisance and reject rank, condition, uncertainty, and non-finite failures at the exact frozen boundaries.
    - **Depends on:** 5.1
    - _Requirements: 4.7-4.8, 6.5-6.6, 6.16-6.21, 6.25_

  - [x] 5.4 Implement pose-equivalence deduplication, ambiguity handling, and ordered gates
    - Build permutation-invariant equivalence components from pose and prediction tolerances, select the lowest common-score representative, and retain all merged provenance/path states.
    - Latch margin necessity from the initial deduplicated valid set; reject distinct equal-score alternatives as `ambiguous_equal_score`, insufficient margin as `ambiguous_hypotheses`, and choose one decisive reason by total precedence while retaining all failures.
    - Finalize selected pose coordinates/headings only after support, numeric, convergence, observability, conditioning, uncertainty, spread, equality, and margin gates; return `insufficient_valid_hypothesis` when no higher-precedence failure applies.
    - **Depends on:** 5.2, 5.3
    - _Requirements: 3.5-3.6, 5.13-5.18, 6.19-6.31, 7.1-7.7_

  - [x]* 5.5 Write the property test for image-space recovery and coordinate equivariance
    - **Property 1: Image-space recovery and coordinate equivariance**
    - Generate observable synthetic forward projections and valid transforms; verify pose recovery, circular heading, coordinate equivariance, body-axis preservation, and ineligibility rather than success when required gates fail.
    - **Depends on:** 1.3, 5.4
    - **Validates: Requirements 1.6-1.7, 3.1-3.6, 3.10-3.11**

  - [-]* 5.6 Write the property test that common scoring permits a non-wheel winner
    - **Property 4: Common scoring permits a non-wheel winner**
    - Verify identical predictions/support/nuisance cost score identically across seed classes and a uniquely lower non-wheel score wins without any wheel bonus or shortcut.
    - **Depends on:** 1.3, 5.14
    - **Validates: Requirements 1.18, 4.11, 4.17-4.18, 5.10, 6.33**

  - [x]* 5.7 Write the property test for robust support and outliers
    - **Property 5: Robust outliers cannot displace sufficient clean support**
    - Add residuals immediately below/equal/above the support boundary; verify exclusion diagnostics and equivalent recovery with sufficient clean support, or decisive `insufficient_support` otherwise.
    - **Depends on:** 1.3, 5.4
    - **Validates: Requirements 4.12, 6.3-6.4, 6.13-6.15, 6.27**

  - [x]* 5.8 Write the property test for semantic ambiguity and pose deduplication
    - **Property 6: Front/rear alternatives never resolve ambiguity by order**
    - Generate normal/reversed/180 alternatives and equivalent-pose clusters; verify complete evaluation, provenance-preserving merge, equal-score and margin rejection, and invariance to diagnostic order or motion output.
    - **Depends on:** 1.3, 5.4
    - **Validates: Requirements 2.22-2.23, 5.2-5.4, 5.13-5.17, 6.22-6.24, 6.29, 8.9**

  - [x]* 5.9 Write the property test for nuisance bounds and uncertainty propagation
    - **Property 8: Nuisance bounds and uncertainty propagation**
    - Verify every varied nuisance stays in its closed interval, ground heights remain zero, and diagnostics include every authorized nuisance and frozen prior/interval treatment.
    - **Depends on:** 1.3, 5.3
    - **Validates: Requirements 4.1-4.8, 6.5**

  - [-]* 5.10 Write the property test for observability rejection
    - **Property 9: Unobservable, ill-conditioned, or uncertain poses are rejected**
    - Compare reported rank, condition, and covariance/uncertainty with a reference calculation and verify exact-boundary rejection with no authoritative coordinate.
    - **Depends on:** 1.3, 5.14
    - **Validates: Requirements 6.6, 6.16-6.21, 6.33-6.34, 7.2-7.3**

  - [-]* 5.11 Write the property test for deterministic decisive-gate precedence
    - **Property 10: Decisive gate precedence is deterministic**
    - Generate simultaneous gate failures; require the highest frozen precedence (`insufficient_support` first), retention of all other diagnostics, and no acceptance change from tie-breakers, diagnostic codes, or ordering.
    - **Depends on:** 1.3, 5.14
    - **Validates: Requirements 4.13, 5.18, 6.25-6.29, 6.31-6.32**

  - [x]* 5.12 Write optimizer boundary and call-graph tests
    - Cover convergence limits, support equality, active nuisance endpoints, rank/condition/uncertainty equality, score and margin equality, inclusive spread rejection, all-invalid paths, and numerical exceptions.
    - Add a static AST import-graph test: modules `trafficlab/motion/haware_optimizer.py`, `haware_hypotheses.py`, `haware_accuracy/models.py`, `projection/haware_forward.py` import neither `haware_localization`, `haware_baseline_dispatch`, nor `measurement/haware_diagnostic_candidates`, and contain no **identifier** (`ast.Name`/`ast.Attribute`; string literals and substrings do not count) equal to `RoleConstraintGraph` / `wheel_only` / `wheel_weighted`; `haware_accuracy/validation.py` is excluded because it holds those strings as the prohibited list (design "Static and smoke checks").
    - **Depends on:** 5.4
    - _Requirements: 1.9-1.12, 3.7-3.9, 4.13-4.18, 5.16-5.18, 6.13-6.31_
    - **Delivered 2026-08-17.** `tests/test_haware_optimizer.py::OptimizerCallGraphStaticTest` (5 tests) with a module-level `scan_module()` AST helper. The four in-scope modules are clean today, so the only genuinely red arm is the scanner's own self-test against a synthetic violating module — without it the real-module arms would pass no matter how the scanner was written. That self-test immediately earned its keep: the first scanner missed `from trafficlab.measurement import haware_diagnostic_candidates`, because for `ImportFrom` the module name sits in `node.names`, not `node.module`. A second arm pins that string literals are not identifiers, so `haware_accuracy/validation.py` can keep holding the prohibited list and `wheel_weighted_procrustes` stays legal.

  - [-]* 5.13 Write the property test for exact optimizer replay
    - **Property 12: Complete optimizer replay is exact**
    - With fixed replay/profile/code/runtime identities and seed, verify exact normalized observations, terminal path states, selected hypothesis, floating pose values, support, status, reason, and diagnostics **by value** across repeated runs. Drop the byte-identity leg; keep the permuted-presentation leg. (This module was 49 % of suite time.)
    - **Depends on:** 1.3, 2.1, 5.4
    - **Validates: Requirements 6.11, 6.12, 6.30**
    - **Re-opened 2026-08-16:** value equality instead of canonical bytes.

  - [ ] 5.14 Reconcile the frozen objective, observability, validity-gate set, rank-zero rule, and position-equivalent ambiguity with the implementation
    - Score = per-component `rho` over image **and prior** residual components (matches `least_squares` semantics); `_robust_observation_loss` moves to per-component; `_robust_weights` applies `rho'` to prior components so `P_nuis = diag(rho'(e_a^2)/sigma_a^2)`; add the invariant `Score - lambda_out*(N-|Support|) == 2*cost` within `1e-9` relative.
    - Rank zero: report `condition=None`, decisive `unobservable_pose`, do not evaluate `ill_conditioned_pose`; update Property 9 to assert this instead of skipping it.
    - Make `validity_gate_set = ('support','non_finite','convergence')` explicit in `OptimizerProfile` and `OrderedGateSelector`; decisive reason for the all-invalid case per Requirement 4.13.
    - Implement Position_Equivalent_Ambiguity (Requirements 5.19-5.20, 7.1): tied hypotheses whose max pairwise position distance ≤ `position_ambiguity_tolerance_m` (0.25 m) accept with the lowest-score representative position, `heading=null`, `heading_status='ambiguous'`, and cluster dispersion folded into position uncertainty; two or more position clusters still reject `ambiguous_equal_score`.
    - Wire `wheel_seeded_enabled` / `non_wheel_seeded_enabled` through `HypothesisGenerator` and profile validation (strata reservation only for enabled classes).
    - **Depends on:** 5.4, 1.2
    - _Requirements: 4.9-4.13, 5.7, 5.18-5.21, 6.32-6.34, 10.16-10.17_
    - **Partly delivered 2026-08-17** (suite 253, OK). Done: (a) rank zero now reports `condition=None` and skips the `ill_conditioned_pose` gate entirely — `ObservabilityDiagnostics.condition` became `Optional[float]` (`tests/test_haware_optimizer.py::RankZeroConditioningTest`, 2 tests); (b) Position_Equivalent_Ambiguity — `resolve_equal_score_positions()` plus its wiring in `OrderedGateSelector.select`, so tied hypotheses whose maximum pairwise centre distance is within `position_ambiguity_tolerance_m` accept with the lowest-score representative's position, `heading_deg=None`, `heading_status='ambiguous'` (5 unit tests + one selector test). The tolerance is measured in **metres** via `CalibrationSnapshot.pixels_per_metre`, not pixels; the pre-existing far-apart case (10 px) still rejects `ambiguous_equal_score`, so the guard works in both directions.
    - A first attempt at the selector test silently proved nothing: two candidates 0.05 px apart with the same heading were merged by pose equivalence before selection, so the tie never occurred. The test now uses a 180-degree heading swap, which is the real front/rear case.
    - **Still open:** (c) the per-component robust loss across score/refinement/observability with the `Score - lambda_out*(N-|Support|) == 2*cost` invariant, and (d) wiring `wheel_seeded_enabled` / `non_wheel_seeded_enabled` through `HypothesisGenerator`.
- [-] 6. Enforce coordinate authority and preserve frozen baseline behavior
  - [x] 6.1 Implement atomic localization authority and compatibility policies
    - Create `trafficlab/motion/localization_authority.py` to validate new result invariants, normalize legacy records only through the frozen explicit policy, and reject inconsistent records atomically without mutating prior output.
    - Map accepted authoritative coordinates to compatibility `sat_coords`; keep rejected optimizer `sat_coords` null and retained fits diagnostic-only.
    - Ship `LEGACY_LOCALIZE_V1: LegacyStatusPolicy` (design §6 table) as a module constant with content identity; `authoritative_position()` defaults to it when a record lacks new-contract fields, and records the applied policy version in its result. A legacy `ok` record with finite `sat_coords` is Accepted even when its heading is non-finite (`heading=null`, `heading_status='ambiguous'`).
    - **Depends on:** 1.1, 5.4
    - _Requirements: 1.19-1.20, 7.1-7.7, 7.15-7.16_
    - **Delivered 2026-08-17.** `LEGACY_LOCALIZE_V1` ships in `trafficlab/motion/localization_authority.py`; `LegacyStatusPolicy` gained `unknown_status_reason`, `rejection_reasons` ((status, reason) pairs — a Mapping field would make the frozen dataclass unhashable) and `null_diagnostic_statuses`; `LocalizationResult` gained `heading_status` and now accepts a null heading; `LocalizationDiagnostics` gained `legacy_policy_version`. Tests: `tests/test_localization_authority.py::LegacyLocalizeV1PolicyTest` (10) and `tests/test_downstream_localization_authority.py::RealLegacyReplayEnrichmentTest` (3). Suite: 224 tests, OK.
    - Two defects the tests found that the scout had not predicted: (a) routing keyed on *field presence* sent a legacy `extrapolated` record carrying `decisive_gate` into new-contract validation, where `LocalizationStatus('extrapolated')` raised `inconsistent_coordinate_state` — routing now keys on the status value (Requirement 1.22); (b) defaulting the policy turned a record with **no** localization evidence (`{}`, an unobserved track) into `legacy_status_evidence_insufficient`, destroying the enrichment `missing` count — missing and rejected are now distinguished (Requirement 1.21).
    - One superseded assertion updated, not deleted: `test_legacy_acceptance_requires_frozen_policy_coordinate_and_heading` pinned `heading=None` to REJECTED; Requirement 1.19 inverts that, and the test now documents why in its docstring.
    - Mutation-verified: reverting the `from_mapping` default to `None` turns all three end-to-end enrichment tests red.

  - [-] 6.2 Enforce authority and segment gaps in downstream consumers
    - Update `scripts/filter_and_enrich_output.py` and the trajectory, replay, collider, and export adapters to consume only validated Authoritative_Position for enrichment and spatial computation; load `legacy-localize-v1` by default (`--legacy-policy PATH` to a policy JSON overrides) and write the applied version into the output. Do **not** assign `segment_id` here — segmentation is owned by `build_scene.py` (6.8); this script only breaks velocity/interpolation at every rejected/missing sample (7.12–7.13).
    - Clear per-real-track state at rejected/missing records so velocity and interpolation never bridge gaps; allow Diagnostic_Position only in debugging visualization/non-spatial analysis and group output counts by status/decisive reason.
    - Golden regression: a real `eval_haware_replay.py` output and a taipei-cm-shaped legacy `trajectory.json` — `status=ok` keeps `position_m` parity with the pre-authority output; `status=extrapolated` nulls `sat_coords`/`position_m`.
    - **Depends on:** 6.1
    - _Requirements: 1.20, 7.8-7.16_
    - **Re-opened 2026-08-16:** `filter_and_enrich_output.py:138` calls `authoritative_position(enriched)` with no policy → every real record becomes `missing_localization`. This is a live regression on the only production path.

  - [-] 6.3 Implement corrected frozen baseline and exact disabled dispatch
    - Add explicit dispatch in the canonical tree so disabled mode calls corrected `localize()` directly and emits its frozen legacy schema without passing through optimizer models, adapters, or result mapping.
    - Keep `localize_reprojection()` as a separately identified diagnostic frozen baseline only; optimizer selection must never call either baseline.
    - Preserve corrected handedness, configured spread behavior, status/reason/null/non-finite classifications, finite coordinates, and circular heading exactly within the required tolerance.
    - Implement the per-Calibration_Profile near-horizon pre-gate (Requirement 1.23): emit legacy status `pre_gate_near_horizon` with null `sat_coords` before fitting; disabled unless `CalibrationProfile.pre_gate` is set; unit test that a passing detection is bit-identical to the ungated output.
    - **Depends on:** 1.2
    - _Requirements: 1.6-1.15; Scope boundary section_

  - [-]* 6.4 Write the property test for coordinate authority and downstream safety
    - **Property 13: Coordinate authority is coherent and downstream-safe**
    - Generate every accepted/rejected state and diagnostic-coordinate mutation; verify authority invariants, atomic rejection, unchanged spatial outputs, segment breaks, reason-grouped counts, every row of the `legacy-localize-v1` table, and that a scene export carries `position_m` only for accepted objects.
    - **Depends on:** 1.3, 6.2, 6.8
    - **Validates: Requirements 1.9, 1.10, 1.19, 1.20, 7.1-7.10, 7.12-7.18**
    - **Re-opened 2026-08-16:** legacy-table and scene-export legs.

  - [-]* 6.5 Write the property test for disabled-mode corrected-baseline parity
    - **Property 19: Disabled mode preserves the corrected baseline exactly**
    - Against deterministic golden fixtures, verify coordinate components and circular heading within `1e-9` plus exact statuses, reasons, nulls, non-finite classifications, and compatible legacy schema.
    - **Depends on:** 1.3, 6.3
    - **Validates: Requirements 1.13-1.15**

  - [-]* 6.6 Write downstream authority integration tests
    - Run mixed accepted/rejected/missing fixtures through enrichment, scene construction, trajectories, visualization, collider, and export paths; assert only visualization/non-spatial diagnostics can consume diagnostic coordinates and no velocity/interpolation crosses a gap.
    - **Depends on:** 6.2, 6.8
    - _Requirements: 7.4-7.19_

  - [-]* 6.7 Write baseline-dispatch and static scope integration tests
    - Compare disabled dispatch with corrected-baseline goldens and verify optimizer-enabled output stays diagnostic outside the pilot while dual-site held-out authorization is absent.
    - Inspect production imports and dispatch to prove legacy trees are read-only, PifPaf has one adapter, and baselines are isolated. Remove the "every deferred capability is guarded and has no implementation symbol" assertion and the `enabled_deferred_capabilities` / `EvidenceGateDecision` machinery it tests (the former production-hardening/deferred-capability requirements are now the "Scope boundary and later phases" section).
    - **Depends on:** 6.3
    - _Requirements: 1.1-1.5, 1.11-1.16; Scope boundary section_
    - **Re-opened 2026-08-16:** delete deferred-capability guard tests and models.

  - [ ] 6.8 Bind the scene-bundle last mile: `tools/build_scene.py` and the Scene_Export_Contract
    - `build_scene.py` (sole owner of segmentation): treat objects without non-null `position_m` as missing; never read `diagnostic_position_sat_px`; split each collider track at runs > `scene_export.max_gap_frames` (default 5) of rejected/missing samples; select the segment containing `--source-collision` and refuse the build when that frame falls inside a gap for either collider (`--diagnostic-scene` still builds, marked `diagnostic_only: true`); write `segment: {start_frame, end_frame}` and `localization_counts` per collider into `scene.json`; refuse the build when the selected segment's accepted share < `scene_export.min_accepted_share` (default `0.5`) unless `--allow-low-pass-rate`, printing share and dominant rejection reason. `trajectory.json` stays a verbatim copy.
    - `filter_and_enrich_output.py` output carries `status`, reason, `localization_counts`, and `legacy_policy_version` per the Scene_Export_Contract (no `segment_id`).
    - Tests in `tools/tests/` (segment split, collider segment selection, refusal + override, counts in scene.json); rerun `node tools/verify_scenes.mjs` after rebuilding one real scene.
    - **Depends on:** 6.2
    - _Requirements: 7.17-7.19_

  - [ ] 6.9 Route `eval_haware_replay.py` through `localize_dispatch`
    - Default path = corrected `localize()` with the exact legacy schema; `--localizer optimizer` emits diagnostic, non-authoritative output only.
    - **Depends on:** 6.3
    - _Requirements: 1.23; Scope boundary section_

- [-] 7. Build outcome-blind evidence populations and comparable pilot runs
  - [-] 7.1 Implement independent-GT validation and pre-outcome population freezing
    - Create `trafficlab/measurement/haware_pilot.py` validators for exact GT matching, Reference_Point coordinates in the Metric_Frame (validated against the Glossary definition, not an opaque string), band-level measured uncertainty from repeat annotation, `protocol_version == gt-protocol-v1`, `annotation_medium` with its admissibility role (calibration-conditional vs calibration-independent), `lift_method`, `repeat_annotation_group`, source/annotator lineage, independence attestation, contamination, duplicate groups, genuine tracks, Capture_IDs and Source_Sequences (with the frozen temporal-buffer rule), independent views `(camera_id, Source_Sequence, scene_region)`, and the design §8 calibration health check with all three gates (`site_calibration_unfit` / `site_calibration_health_insufficient_data`).
    - Freeze per-site eligibility, denominator, GT groups, real-track/source/view/band memberships, and whole-group pilot/held-out assignments before outcome APIs are accessible; report `held_out_capture_unavailable` when a site has < 2 Capture_IDs (a within-capture split never counts); permit a held-out Capture_ID to be registered after pilot freeze but before any held-out outcome is read.
    - Keep `kee-cc` and `taoyuan-tc` namespaces separate and exclude `taipei-cm`, pseudo/no-track records, pooled rescue, and outcome-dependent inclusion.
    - **Depends on:** 1.1, 2.3
    - _Requirements: 8.5-8.7, 8.12-8.13, 9.1-9.24, 10.2, 10.32_
    - **Re-opened 2026-08-16:** GT protocol fields, Source_Sequence definition and minimum, scene_region bands, site health check.

  - [-] 7.2 Implement baseline/full/ablation/diagnostic-candidate pilot orchestration and run identity
    - Run the corrected baseline, full optimizer, wheel-seeded-initialization-disabled ablation (`wheel_seeded_enabled=False`), non-wheel-seeded-initialization-disabled ablation (`non_wheel_seeded_enabled=False`), and every `PilotPolicy.diagnostic_candidates` arm on the same stable eligible ordering; record wall-clock and per-detection runtime per arm.
    - Make each ablation change exactly one enable flag while preserving replay, candidate, calibration/cue/nuisance profiles, score/support rules, metric definitions, code/runtime identities, and deterministic seed. Tag each report with `arm_kind`.
    - Add the calibration sensitivity sweep (Requirement 9.28) for any site using calibration-conditional GT: for each perturbation in `nominal + per-parameter endpoints + 256 seeded Sobol samples`, rebuild the medium-(a) GT and rerun both arms, then classify each perturbation under the 10.34 trichotomy and combine (unanimous go → go; disagreement → insufficient_data; unanimous failure → no_go). Exempt from the runtime envelope.
    - **Depends on:** 5.14, 6.3, 7.1, 10.1
    - _Requirements: 9.26-9.29, 10.1-10.2, 10.14-10.19, 12.1-12.2, 13.2_
    - **Re-opened 2026-08-16:** ablation flags now exist in the contract; diagnostic candidate arm; runtime capture.

  - [-]* 7.3 Write the property test for leak-free site-isolated evidence
    - **Property 15: Independent evidence and partitions are leak-free and site-isolated**
    - Generate GT duplicate/contamination groups and track/source incidence constraints; verify whole-group assignments, deterministic exclusions/failures, and invariance to `taipei-cm` or the other acceptance-site namespace.
    - **Depends on:** 1.3, 7.1
    - **Validates: Requirements 9.1, 9.4, 9.5, 9.7-9.12, 9.14-9.18**

  - [-]* 7.4 Write the property test for isolated pilot ablations
    - **Property 17: Pilot ablations isolate one initialization class**
    - Verify the two ablation profiles differ from full only in `wheel_seeded_enabled` / `non_wheel_seeded_enabled` and preserve every replay, candidate, score/support, seed, metric, and run identity field.
    - **Depends on:** 1.3, 5.14, 7.2
    - **Validates: Requirements 10.15-10.19**
    - **Re-opened 2026-08-16:** the shipped test asserts `wheel_seeded_initialization_enabled`; rename to the contract fields introduced by 5.14.

  - [-]* 7.5 Write GT/population/orchestration integration tests
    - Verify outcome APIs remain unavailable until independent GT, track classification, views, denominator, and partitions are frozen; cover exact-one joins, whole-group contamination/duplicates, assignment conflicts, pseudo exclusion, site isolation, and identical ordered inputs across all four core configurations plus the diagnostic candidate arm.
    - **Depends on:** 7.2
    - _Requirements: 8.5-8.13, 9.1-9.24, 10.1-10.2, 10.15-10.19, 10.32, 12.1_
    - **Re-opened 2026-08-16:** GT protocol / health-check fixtures and the diagnostic candidate arm (needs 10.1).

  - [ ] 7.6 Add the pilot driver `scripts/run_haware_pilot.py`
    - Reads stored replays (`evidence/haware/replays/<code>/replay.json.gz`) + GT (`evidence/haware/gt/<code>/gt.json`, GroundTruthRecord schema), runs population freeze → baseline/full/two ablations/diagnostic candidate → statistics → decision; emits `insufficient_data` (with `held_out_capture_unavailable` per site) on the current inventory; reports `wall_s / video_s` and the projected full-video value against the `10 s/s` Batch_Runtime_Envelope and flags `runtime_envelope_exceeded`.
    - **Depends on:** 8.2, 2.8
    - _Requirements: 10.1-10.36, 13.1-13.4_
- [-] 8. Implement pilot statistics, feasibility decisions, and held-out controls
  - [-] 8.1 Implement per-site metrics, clustered intervals, power, and sufficiency (`pilot-stats-v1`)
    - Compute accepted/rejected counts; own-set median/p90 (descriptive); **Paired_Accepted_Set** median/p90 for both arms, paired-set size and shares; fixed-denominator usable coverage; signed effects (median/p90 on the paired set, coverage on the denominator); selected seed provenance; genuine-track count; independent-view and `scene_region` band coverage; GT uncertainty; each arm's error-vs-coverage operating point.
    - Implement `pilot-stats-v1` exactly as design §8: detection-level estimands (paired median, paired p90, fixed-denominator coverage); one inference method — 4096 seeded whole-track bootstrap that recomputes the detection-level statistic per resample; per-effect cluster universe and a per-effect minimum of 8 clusters → else `insufficient_data`; nearest-rank 0.95 interval; variance incl. GT uncertainty; `n_req` from the frozen MEI; power reported at the MEI; the 10.34 trichotomy (`U ≤ −MEI` go / `L > −MEI` no_go / straddle insufficient_data) with p90 non-gating; print cluster and replicate counts next to every interval.
    - **Depends on:** 7.2
    - _Requirements: 10.3-10.24, 10.33-10.36_
    - **Re-opened 2026-08-16:** the harness froze a cluster minimum of 2 and computed post-hoc power (`directional_signal = max(0, -effect)`); both are replaced.

  - [-] 8.2 Implement pilot go/no-go and current-evidence insufficiency reporting
    - Require each acceptance site independently to satisfy frozen sufficiency and the three-condition feasibility rule (10.34: superiority, MEI materiality, coverage non-inferiority); emit `no_go` with all gaps/failures when either site is insufficient or infeasible, and `go` only when both pass.
    - Add the checked-in evidence inventory path that must emit final-evidence `insufficient_data` and no proven-improvement claim; keep selective-risk, pooled, proxy, diagnostic-candidate, and `taipei-cm` values diagnostic-only.
    - **Depends on:** 8.1
    - _Requirements: 9.14-9.18, 10.20-10.31, 10.34-10.37, 12.3_
    - **Re-opened 2026-08-16:** MEI materiality condition and `pilot-stats-v1` sufficiency inputs.

  - [-] 8.3 Implement the commit-SHA-bound held-out decision
    - After pilot `go`, extend the Acceptance Profile with per-site thresholds by the `pilot_upper_bound_v1` rule (Requirement 10.37) and commit it; the held-out command `scripts/run_haware_held_out.py --profile-sha <sha>` takes the commit SHA, records SHA + profile digest in the report, applies `no_go > insufficient_data > go` independently across `kee-cc` and `taoyuan-tc`, and refuses to reuse an outcome exposed under a different SHA; never allow `taipei-cm`, pooled, proxy, diagnostic-candidate, or selective-risk rescue.
    - **Delete** `OutcomeAccessToken`, `HeldOutAccessGrant`, `HeldOutDecisionController` and their tamper-refusal tests from `trafficlab/measurement/haware_held_out.py`; keep the threshold freeze, precedence, and site-independence logic.
    - Feed only a dual-site held-out `go` into the default-off authorization guard; do not implement production hardening or enable authoritative optimizer dispatch in this plan.
    - **Depends on:** 1.2, 8.2
    - _Requirements: 11.1-11.16; Scope boundary section_
    - **Re-opened 2026-08-16:** access-control layer removed (F14).

  - [-]* 8.4 Write the property test for fixed pilot accounting and decisions
    - **Property 16: Pilot accounting and decision rules use fixed evidence**
    - Generate paired outcomes over frozen populations; compare all metrics/intervals to a reference implementation; include the "candidate rejects the worst-error detections" case (own-set effect negative, paired effect zero, decision uses paired); verify `go` only when both sites satisfy sufficiency and feasibility, otherwise complete `no_go` evidence.
    - **Depends on:** 1.3, 8.2
    - **Validates: Requirements 10.1-10.14, 10.21-10.29, 10.33-10.36**
    - **Re-opened 2026-08-16:** paired set, MEI, validity minimum.

  - [-]* 8.5 Write the property test for held-out precedence and site independence
    - **Property 18: Held-out decisions preserve precedence and site independence**
    - Generate all per-site threshold/sufficiency states and diagnostic/pooled/proxy/diagnostic-candidate perturbations; verify `no_go > insufficient_data > go`, both-site conjunction, and decision invariance.
    - **Depends on:** 1.3, 8.3
    - **Validates: Requirements 11.8-11.16**

  - [-]* 8.6 Write pilot and held-out integration tests
    - Use hand-computed fixtures for metric/interval/power calculations (cluster minimum at n=7 → `insufficient_data` and n=8; seeded bootstrap reproducibility; the three trichotomy branches; power at MEI vs observed), current checked-in evidence, all four core configurations plus the diagnostic candidate, per-site reports, pilot decisions, commit-SHA recording, refusal to reuse an exposed outcome under a new SHA, and default-off enforcement.
    - **Depends on:** 8.3
    - _Requirements: 10.1-10.36, 11.1-11.16, 12.1-12.3_
    - **Re-opened 2026-08-16:** drop tamper-refusal tests; add stats-v1 fixtures.

- [ ] 9. Checkpoint — Ensure all tests pass, ask the user if questions arise.
  - Ensure all available unit, property, integration, import-graph, and diagnostics checks pass (`(cd trafficlab-project && .venv-pifpaf/bin/python -m unittest discover -s tests)`, plus `python3 -m unittest discover -s tools/tests` and `node tools/verify_scenes.mjs` after 6.8). Report external evidence blockers as `insufficient_data`; do not claim pilot feasibility or held-out acceptance.
  - **Re-opened 2026-08-16:** re-run after the re-opened and new tasks land.

- [ ] 10. Implement the diagnostic candidate arm (the 2026-08-10 weighted-Procrustes proposal, measured, never authoritative)
  - [ ] 10.1 Implement `wheel_weighted_procrustes` in `trafficlab/measurement/haware_diagnostic_candidates.py`
    - Reuse the corrected baseline template, handedness correction (`Q[:,0] = -Q[:,0]`), and spread diagnostic; weighted fixed-scale Procrustes `Hc = (Q-q̄)ᵀ W (P-p̄)` with weighted centroids `q̄ = Σ w_i q_i / Σ w_i` and diagonal `w_wheel` (`PilotPolicy.diagnostic_candidate_params`, default `4.0`, module constant `W_WHEEL_DEFAULT`) on `WHEEL_KP_IDX`; when `n_wheel_kp < 2` fall back to the unweighted full-point fit and set `fallback=true`; output the legacy schema plus `arm='wheel_weighted_procrustes'`, `w_wheel`, `fallback`, `n_wheel_kp`, `spread_m`. Never imported by the optimizer or by production dispatch.
    - **Depends on:** 6.3
    - _Requirements: 12.4-12.5_
  - [ ]* 10.2 Write the property test that diagnostic candidate arms never influence a decision
    - **Property 20: Diagnostic candidate arms never influence a decision**
    - Perturb/add/remove diagnostic-candidate outputs; assert every optimizer/baseline metric, threshold, pilot gate, and held-out decision is unchanged, and that the candidate's own report uses the paired definitions.
    - **Depends on:** 1.3, 7.2, 10.1
    - **Validates: Requirements 12.1-12.4**

- [ ] 11. Synchronize documentation with the 2026-08-16 spec revision
  - [ ] 11.1 Update `CLAUDE.md` haware section: 214-test count and command, pointer to this Kiro spec, `legacy-localize-v1`, the `build_scene.py` binding (closes priority #2), and the diagnostic-candidate status of weighted Procrustes.
  - [ ] 11.2 Confirm the superseded banner on `docs/specs/2026-08-10-haware-localization-accuracy-design.md` (added 2026-08-16) and add a decision record `docs/decisions/2026-08-16-haware-spec-critique.md` from design.md Appendix A (the F1–F18 table).
  - **Depends on:** 9

## External Data Blockers (Not Executable Coding Tasks)

Stored replays and tracker provenance for `kee-cc`/`taoyuan-tc` are **not** external: they are produced in-repo by tasks 2.7/2.8 from `location/<code>/footage/<code>.mp4` (this list previously claimed otherwise). What genuinely remains external:

- Independently created GT for both sites under `gt-protocol-v1` (design §8): blinded annotator, ≥ 0.5 s frame spacing per genuine track stratified by `scene_region`, ≥ 20 % (and ≥ 8 records) repeat-annotated per band for measured uncertainty, content-hashed before any outcome is read. The calibration-conditional medium (CCTV wheel-contact clicks lifted through the frozen calibration) is admissible for the effect and feasibility but obliges the 256-sample calibration sensitivity sweep and forbids any absolute-accuracy claim; only calibration-independent GT (satellite or surveyed/GNSS references) can support an absolute claim.
- A second Capture_ID per acceptance site (a separate recording session, not another span of the same clip) so a Held_Out_Partition can exist at all; today each site has exactly one checked-in clip (kee-cc 5.3 s, taoyuan-tc 3.0 s) → `held_out_capture_unavailable`. It may be acquired after the pilot partition is frozen.
- Enough genuine tracks per site per partition to reach the `pilot-stats-v1` minimum of 8 clusters per effect and the MEI-derived `n_req`; the current clips are far below this.
- A `taoyuan-tc` calibration health check pass (it has never been measured; kee-cc passed the track-width check at 53.2 %).

Current checked-in evidence must therefore produce `insufficient_data`, keep the optimizer default-off/non-authoritative outside the pilot, and prohibit any claim of proven improvement.

## Notes

- Tasks marked with `*` are test tasks. The numbered-property tests (Properties 1–20) are **required**, one module each, per the Design Testing Strategy — the `*` never authorizes skipping them. Only non-property `*` tests (extra unit/integration coverage) may be deferred for a faster implementation pass. All core implementation tasks remain required.
- This plan implements only the narrow PifPaf-backed provider-neutral MVP contract, not a full multi-provider platform or exhaustive artifact-management system.
- Explicitly deferred and excluded: generalized learned reliability, detector retraining/replacement, calibration identification/re-estimation, selective-risk acceptance, temporal fusion, multi-sensor fusion, and unrelated production hardening.
- `localize()` and `localize_reprojection()` are frozen baselines only. The optimizer call graph must remain independent of both methods and all stale projected-point/role-graph/mode-selection architectures.
- Wheel-first is strictly an ordering/initialization preference at `h=0`; it is never exclusivity, a score bonus, an acceptance shortcut, or a substitute for non-wheel hypothesis generation.

## Status Audit (2026-08-16)

Rule: **a checkbox may only flip when the row cites a file path and a passing test; audits never contradict checkboxes — they replace them.** Verified 2026-08-16 with `(cd trafficlab-project && .venv-pifpaf/bin/python -m unittest discover -s tests)` → **214 tests, OK** (167 s). The 2026-08-12 audit below is history: everything it reported missing now exists in the tree.

| Task | Deliverable path(s) | Test module(s) | State |
|---|---|---|---|
| 1.1 | `trafficlab/motion/haware_accuracy/models.py` | `tests/test_haware_accuracy_models.py` | [x] |
| 1.2 | `trafficlab/motion/haware_accuracy/validation.py` | `tests/test_haware_profile_validation.py` | [-] re-opened: narrow prohibition scan; new profile fields |
| 1.3 | `tests/property_support/` | `tests/test_haware_property_support.py` | [x] |
| 2.1 | `trafficlab/io/haware_observation_replay.py` | `tests/test_haware_observation_replay.py`, `tests/properties/test_property_11_*` | [-] re-opened: value round-trip, `duplicate_observation_id`, writer exclusions |
| 2.2 | `trafficlab/inference/pifpaf_haware_adapter.py` | `tests/test_pifpaf_haware_adapter.py`, `tests/test_haware_replay_adapter_integration.py` | [x] |
| 2.3 | track provenance in `haware_accuracy/` | `tests/test_haware_track_provenance.py`, `tests/properties/test_property_14_*` | [x] |
| 2.7, 2.8 | `scripts/eval_haware_replay.py`, `evidence/haware/` | — | [ ] new |
| 3.1–3.2 | `trafficlab/projection/haware_forward.py` | `tests/test_haware_forward.py`, `tests/properties/test_property_01_*` | [x] |
| 4.1–4.2 | `trafficlab/motion/haware_hypotheses.py` | `tests/test_haware_hypotheses.py`, `tests/properties/test_property_02/03/07_*` | [x] |
| 5.1–5.4 | `trafficlab/motion/haware_optimizer.py` | `tests/test_haware_optimizer.py`, `tests/properties/test_property_04/05/06/08/09/10_*` | [x] |
| 5.12 | — | `tests/test_haware_optimizer.py` (runtime spies only) | [-] static AST proof missing |
| 5.13 | — | `tests/properties/test_property_12_*` | [-] re-opened: value equality |
| 5.14 | `haware_optimizer.py`, `haware_hypotheses.py` | Property 9 update, new invariant test | [ ] new |
| 6.1 | `trafficlab/motion/localization_authority.py` (396 lines) | `tests/test_localization_authority.py`, `tests/properties/test_property_13_*` | [-] re-opened: no default legacy policy |
| 6.2 | `scripts/filter_and_enrich_output.py` | `tests/test_downstream_localization_authority.py` | [-] re-opened: calls authority with no policy → all real records missing |
| 6.3 | `trafficlab/motion/haware_baseline_dispatch.py` | `tests/test_haware_baseline_dispatch.py`, `tests/properties/test_property_19_*` | [x] |
| 6.4 | — | `tests/properties/test_property_13_*` | [-] re-opened: legacy-table and scene-export legs |
| 6.7 | — | `tests/test_haware_baseline_scope_integration.py` | [-] re-opened: remove deferred-capability guard tests |
| 6.8, 6.9 | `tools/build_scene.py`, `scripts/eval_haware_replay.py` | `tools/tests/` | [ ] new |
| 7.1–7.2 | `trafficlab/measurement/haware_pilot.py` | `tests/test_haware_pilot.py`, `tests/properties/test_property_15_*` | [-] re-opened: GT protocol, Source_Sequence, bands, diagnostic arm, flags |
| 7.4, 7.5 | — | `tests/properties/test_property_17_*`, `tests/test_haware_gt_population_orchestration_integration.py` | [-] re-opened: flag names; diagnostic arm fixtures |
| 7.6 | `scripts/run_haware_pilot.py` | — | [ ] new |
| 8.1–8.2 | `haware_pilot.py` statistics | `tests/test_haware_pilot_statistics.py`, `tests/test_haware_pilot_decision.py`, `tests/properties/test_property_16_*` | [-] re-opened: `pilot-stats-v1`, paired set, MEI |
| 8.3 | `trafficlab/measurement/haware_held_out.py` (728 lines) | `tests/test_haware_held_out.py`, `tests/properties/test_property_18_*` | [-] re-opened: replace access control with commit SHA |
| 10.1 | `trafficlab/measurement/haware_diagnostic_candidates.py` | Property 20 | [ ] new |
| 11 | `CLAUDE.md`, `docs/decisions/2026-08-16-*.md` | — | [ ] new |

### Cascade re-opened 2026-08-17 (dependents of a changed contract)

- **1.4** — 1.2 narrows the prohibited-contract scan and adds profile fields; the prohibited-mode assertions must be rewritten.
- **2.2** — 2.1 changes the record contract and 2.7 adds tracker-provenance fields the importer must carry.
- **2.3** — 2.7 supplies the provenance that `finalize_track_provenance` must classify REAL; re-verify against real ByteTrack records.
- **6.3** — the pre-gate (6.9) adds legacy status `pre_gate_near_horizon`, which Requirements 1.14-1.15 parity must now cover.
- **6.5** — golden fixtures must include a `pre_gate_near_horizon` record.
- **6.6** — 6.2 (default legacy policy) and 6.8 (scene builder) change what these fixtures must prove.
- **7.3** — 7.1 introduces Capture_ID, Source_Sequence spans, and scene_region bands that partition assignment now depends on.
- **5.6** — Property 4 now also validates Requirement 6.33 (per-component robust loss, Score == 2*cost).
- **5.10** — Property 9 now asserts the rank-zero rule (condition null, no `ill_conditioned_pose`) instead of skipping it.
- **5.11** — Property 10 now also validates Requirements 4.13, 5.18, and 6.32 (Validity_Gate_Set, all-invalid decisive reason).

`3.1` and `3.2` are deliberately **not** cascaded: they depend on `1.2` only for profile validation, and the forward-projection contract (`K`, `D`, `H`, `z_cam`, pose/nuisance parameterization) is untouched by the 2026-08-16/17 revisions.

### Adjudicated 2026-08-16 (formerly "Findings for follow-up")

- Robust loss per-component vs per-observation → **per-component everywhere** (Requirement 6.33, design "Robust refinement"); task 5.14.
- Priors robustified in refinement but Gaussian in observability → **robustified in both**; observability weights `rho'(e_a^2)/sigma_a^2`; task 5.14.
- Rank-zero condition sentinel → **`condition=null`, `ill_conditioned_pose` not evaluated** (Requirement 6.34); task 5.14.
- Writer silently drops invalid observations → **writer returns exclusions** (Requirement 2.15); task 2.1.

### History: audit of 2026-08-12 (superseded)

`.venv-pifpaf/bin/python -m unittest discover -s tests` reported 132 tests with 1 failure at that time (144 after the 5.9 fix), and `tests/properties/` contained modules for Properties 1, 3, 8, 11, and 14 only. Everything below this line described that state and is retained only as history.

- **Reset `[x]` -> `[ ]` (claimed, no deliverable):** 4.3 (Property 2), 4.5 (Property 7), 5.6 (Property 4), 5.7 (Property 5), 5.8 (Property 6), 5.11 (Property 10). No test module exists for any of these numbered properties, and the Design Testing Strategy requires one module per numbered property.
- **Reset `[x]` -> `[-]` (started, not delivering):**
  - 4.4 (Property 3): `tests/properties/test_property_03_non_exclusive_wheel_first_ordering.py` exists but defines zero test functions; the file ends mid-class.
  - 5.9 (Property 8): **resolved 2026-08-12, now `[x]`.** The module failed at `test_property_08_nuisance_bounds_and_uncertainty_propagation.py:296` on `assert set(fields) == set(published_nuisance)`. Triage found the defect in the test, not the optimizer: `RefinedCandidate.nuisance` publishes template geometry only, while fit-local calibration deltas are applied to the fit's `CalibrationSnapshot` and reported through `parameter_values` and `observability.nuisance_treatments` (verified: `delta_z_cam` appears there with `role='calibration'`, its closed interval, prior treatment, and `jacobian_schur_marginalized`). That satisfies Requirement 4.8 and the Design Property 8 clause, which constrains the *observability calculation*, not the published vector; `_bounded_nuisance_prior_cost` independently encodes the subset contract via `unknown_nuisance_value`, and Design "Parameterization and bounded nuisances" states the MVP never publishes a fitted calibration. The assertion now pins the published set to `fields - calibration.authorized_nuisance_fields`; a mutation that publishes `delta_z_cam` makes it fail, so the check retains its teeth.
  - 5.12: optimizer boundary tests exist in `tests/test_haware_optimizer.py`, but the required static/import call-graph proof is absent. Prohibited-contract rejection is only config-level (`tests/test_haware_profile_validation.py`) and baseline isolation is only runtime spies (`tests/test_haware_baseline_dispatch.py`).
- 5.13 (Property 12): **delivered 2026-08-12, now `[x]`.** `tests/properties/test_property_12_complete_optimizer_replay_is_exact.py` replays one generated content variant per example and asserts exact reproduction across a repeated identical run and an equivalent permuted presentation: canonical result bytes, status/usable/decisive gate/reason, verbatim pose floats, normalized observations, selected path, margin, spread, gate failures, merged components, exclusions, per-path terminal states, and per-path support/outlier/score. Two fixture traps were hit and fixed while writing it: unclamped pixel jitter pushed a coordinate out of the image so the replay layer legitimately dropped it, and `configured_profile()` is a generation-only fixture whose missing `roof_height_m` nuisance and mismatched `parameter_scale` made every hypothesis fail at `invalid_refinement_parameterization`, leaving nothing to compare. The module therefore builds its own refinement-ready profile and carries `test_the_replayed_fixture_reaches_a_selected_pose`, which fails loudly if the property ever degenerates into comparing empty runs. Mutation-verified: a call-count-dependent initial value fails the repeated-run leg, and removing `canonical_order` from `ObservationRecord` fails the presentation leg.
- 5.10 (Property 9): **delivered 2026-08-12, now `[x]`.** `tests/properties/test_property_09_observability_rejection.py` targets the pose spectrum directly (`J = W^-1/2 Q diag(sqrt(eig)) V^T`, so `J^T W J` reproduces the drawn eigenvalues) and checks three legs: an independent numpy re-derivation of weights/information/Schur/singular values/covariance/ellipse/heading, exact-boundary rejection for all three gates using the reported value as the boundary, and a real generate/refine/score/select run proving each gate yields `status=rejected`, `usable=False`, no authoritative position, a retained diagnostic position, and the reason present on the *selected* candidate rather than only in the aggregate. Measured coverage over 300 draws: rank 0/1/2/3 = 38/60/88/114, all three losses, 0-2 nuisance parameters, 38 coupled Schur cases. Mutation-verified: `>=` to `>` on the condition gate, dropping `rank` from the degrees of freedom, un-reversing the ellipse axes, and `or` to `and` on the uncertainty gate each fail the property.
  - Three design decisions worth keeping: comparisons are scaled by the array magnitude rather than element-wise, because entries that are mathematically zero carry cancellation noise from whichever decomposition produced them; the closed-form robust weights are cross-checked against a central difference of `rho` itself, so a wrong hand differentiation cannot cancel between reference and production; and coupling is never combined with a below-tolerance eigenvalue in one case, because a rotation puts eigenvalues nobody chose into the nuisance block and the pseudoinverse is discontinuous there. Coupled cases draw every eigenvalue above the tolerance, which Cauchy interlacing then propagates to every principal submatrix and to the Schur complement.
  - The rank-zero `condition := condition_rejection_boundary` sentinel is deliberately **not** asserted. It makes `condition >= boundary` self-fulfilling, so a rank-zero case always reports `ill_conditioned_pose` alongside `unobservable_pose`, and raising the boundary can never clear it. That coupling is absent from the design's `sigma_max / sigma_min_retained` definition; see the findings below.
- **Parent tasks 4 and 5 reset to `[-]`:** their implementation subtasks are complete, but their test subtasks are not, and 5.10 remains `[-]`.

(Historical, 2026-08-12:) Core (non-`*`) implementation tasks complete: 16 of 22. Remaining core work: 6.1, 6.2, 7.2, 8.1, 8.2, 8.3. — All of these modules exist as of 2026-08-16; see the table above for what is re-opened and why.

### Findings for follow-up (2026-08-12; all four adjudicated above)

- **Robust loss is applied per residual component in observability but per 2D observation in scoring.** `design.md` freezes `L(q) = sum_j rho(||e_j(q)||^2)`, i.e. one rho per observation pair. `_robust_observation_loss` (`haware_optimizer.py:1075`) matches that. `_robust_weights` (`haware_optimizer.py:524`), which builds the information matrix, squares each scalar component independently, so reported curvature is not rotation-invariant in image space: two residual pairs of equal norm get different weights depending on how the norm splits across x and y. SciPy's `least_squares(loss=...)` also applies rho per element, so the refinement being measured agrees with `_robust_weights` and disagrees with both the design formula and the score.
- **Nuisance priors are robustified in refinement but enter observability as un-robustified Gaussian precision.** `residual()` concatenates `_prior_residuals(...)` into the vector handed to `least_squares(loss=huber)` (`haware_optimizer.py:908-935`), so SciPy applies the robust loss to the prior residuals. `design.md` places the prior term outside `rho` as a plain quadratic, and observability adds it as `diag(prior_precision)` (`haware_optimizer.py:618`). Observability matches the design; the refinement does not. For a large fitted prior residual under a non-linear loss, the reported curvature is not the curvature of the objective that was actually minimized.
- **Rank-zero condition sentinel.** With no retained direction, `condition` is set to `settings.condition_rejection_boundary` (`haware_optimizer.py:648-652`), which makes the `ill_conditioned_pose` gate fire unconditionally and makes the reported condition depend on the boundary being tested against. Property 9 asserts only `unobservable_pose` in that regime.
- `ObservationReplayWriter._normalized_mappings` reads only `result.record` from `normalize_record_mapping` and discards `result.exclusions`, so writing a record whose observation violates the replay contract (verified with `observation_coordinate_out_of_bounds`) emits a payload with that observation silently removed and no signal to the caller. The reader path does surface the same exclusion. Whether the write scope owes the caller a reason is a Requirement 2 question, so it is recorded here rather than changed.


## Task Dependency Graph

Remaining work only (completed `[x]` tasks omitted). Order respects every `Depends on` line above.

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.2", "5.12", "6.1"] },
    { "id": 1, "tasks": ["1.4", "2.1", "5.14", "6.2", "6.3"] },
    { "id": 2, "tasks": ["2.2", "2.4", "5.6", "5.10", "5.11", "5.13", "6.5", "6.7", "6.8", "6.9", "10.1"] },
    { "id": 3, "tasks": ["2.7", "6.4", "6.6"] },
    { "id": 4, "tasks": ["2.3", "2.8"] },
    { "id": 5, "tasks": ["7.1"] },
    { "id": 6, "tasks": ["7.2", "7.3"] },
    { "id": 7, "tasks": ["7.4", "7.5", "8.1", "10.2"] },
    { "id": 8, "tasks": ["8.2"] },
    { "id": 9, "tasks": ["7.6", "8.3", "8.4"] },
    { "id": 10, "tasks": ["8.5", "8.6"] },
    { "id": 11, "tasks": ["9"] },
    { "id": 12, "tasks": ["11.1", "11.2"] }
  ]
}
```
