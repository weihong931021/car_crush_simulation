# Implementation Plan: Haware Localization Accuracy

## Overview

Implement the approved Python design in strict measurement-first order: Phase 0A canonical artifacts and schemas, frozen baselines and independent ground truth, deterministic metrics and the Phase-0 gate, the wheel-first single-frame estimator, downstream enforcement, and two-site acceptance. Fallback is a primary usable path. Calibration eta analysis proceeds on a parallel non-blocking branch. Temporal fusion is optional and may start only when its explicit permission predicate passes.

All commands below are validation commands to run during implementation; none were run while creating this plan. Unless noted otherwise, run Python commands with working directory `trafficlab-project`.

## Tasks

- [ ] 1. Build Phase 0A canonical contracts and test infrastructure
  - [ ] 1.1 Implement typed failures and immutable acceptance-profile models
    - Add Python models for observation validity, geometry, conditioning, spread, metrics, diagnostics, schema compatibility, calibration, and optional fusion configuration; validate finite values, inclusive boundaries, non-overlapping mode predicates, supported versions, and per-calibration thresholds before record processing.
    - Add stable typed error payloads with code, field/gate, and optional detection identity, and prohibit authoritative coordinates on failures.
    - Use a test-first cycle with focused invalid-profile and typed-error examples before implementation.
    - **Depends on:** none
    - **Validation:** `python -m pytest tests/haware_accuracy/test_profiles.py -q`
    - _Requirements: 6.1, 6.2, 6.3, 6.22, 6.23, 9.3, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 13.10, 13.11, 13.12, 13.13, 13.14, 15.34, 15.35, 15.36_

  - [ ] 1.2 Implement Canonical JSON and artifact hashing utilities
    - Create finite-number-only UTF-8 canonical serialization with sorted object keys, compact separators, preserved array order, one LF terminator, exact-byte SHA-256 hashing, and atomic content-addressed writes.
    - Add exact-byte and mutation examples before implementation.
    - **Depends on:** none
    - **Validation:** `python -m pytest tests/haware_accuracy/test_canonical_artifacts.py -q`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.13, 2.14, 2.15, 2.16_

  - [ ] 1.3 Implement versioned profile, result, diagnostics, baseline, ground-truth, and report schema repositories
    - Define deterministic readers/writers and field-path validation for every frozen artifact; reject unsupported versions and non-finite metric inputs without processing payloads.
    - Freeze the ordered schema-compatibility profile and diagnostics zero-denominator representation.
    - **Depends on:** 1.1, 1.2
    - **Validation:** `python -m pytest tests/haware_accuracy/test_schema_contracts.py -q`
    - _Requirements: 2.6, 3.1, 3.12, 3.13, 3.14, 5.19, 12.23, 12.24, 12.25, 12.26, 12.27, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 13.10, 13.11, 13.12, 13.13, 13.14_

  - [ ]* 1.4 Write the property test for canonical baseline identity and comparability
    - **Property 16: Canonical baseline identity and comparability**
    - Cover deterministic canonical bytes, identity-field/artifact-hash sensitivity, and exact comparability of presence, JSON type, value, and array order.
    - **Depends on:** 1.2, 1.3
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_16_baseline_identity.py -q`
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.13, 2.14, 2.17, 2.18, 2.19, 2.20, 2.21**

  - [ ] 1.5 Configure the reproducible Hypothesis property runner
    - Add an exact pinned Hypothesis dependency to the project environment/lock, a `property` test marker, reusable PBT-profile strategies, all four required seeds, at least 100 cases per seed, boundary/`nextafter` generation, minimized-failure recording, and no-generation replay support.
    - Keep every numbered property in its own test module with the required feature/property comment.
    - **Depends on:** 1.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_property_runner.py -q`
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

  - [ ]* 1.6 Write profile and schema validation smoke tests
    - Test absent calibration thresholds, overlapping predicates, malformed enum/status values, non-finite fields, unsupported schemas, and deterministic supported-version error details.
    - **Depends on:** 1.1, 1.2, 1.3
    - **Validation:** `python -m pytest tests/haware_accuracy/test_profiles.py tests/haware_accuracy/test_schema_contracts.py -q`
    - _Requirements: 6.1, 6.2, 6.3, 9.3, 13.31, 13.32, 13.33, 13.34, 13.35, 13.36, 15.34, 15.35, 15.36_

  - [ ]* 1.7 Write the property test for property-runner reproducibility
    - **Property 26: Property-runner reproducibility**
    - Verify the four seeds, minimum case count, frozen generator domains, complete failure metadata, and exact minimized-example replay without generation.
    - **Depends on:** 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_26_runner_reproducibility.py -q`
    - **Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5**

- [ ] 2. Create immutable frozen baselines and disabled-mode golden inputs
  - [ ] 2.1 Implement the frozen-baseline store, comparability diff, and reproduction verifier
    - Implement manifest identity construction, publish/verify/rerun APIs, immutable exact-byte storage, ordered artifact verification, canonical-path comparability differences, and scalar-metric tolerance checks.
    - Add tamper and forbidden-replacement examples before implementation.
    - **Depends on:** 1.2, 1.3
    - **Validation:** `python -m pytest tests/haware_accuracy/test_baseline_store.py -q`
    - _Requirements: 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.15, 2.16, 2.17, 2.18, 2.19, 2.20, 2.21, 2.22, 2.23, 2.24, 2.25_

  - [ ] 2.2 [EXTERNALLY BLOCKED: frozen site inputs/profile/calibrations] Materialize both frozen legacy baselines and compatibility goldens
    - Once exact `kee-cc` and `taoyuan-tc` input inventories, calibration artifacts, dependency lock, and effective profile values are supplied, use code-backed artifact builders to create content-addressed baseline manifests, outputs, and disabled-mode golden fixtures with handedness correction and the existing spread gate enabled.
    - Do not infer missing values from `taipei-cm`; if any prerequisite artifact is absent or hash-invalid, leave this task blocked and Phase 0 failed.
    - **Depends on:** 2.1; external supplied-and-frozen artifacts
    - **Validation:** `python -m trafficlab.measurement baseline verify --site kee-cc --baseline-id <id>` and the same command for `taoyuan-tc`
    - _Requirements: 1.14, 1.15, 1.16, 1.17, 2.6, 2.7, 2.8, 2.9, 2.10, 2.15, 2.22, 2.23, 2.24, 2.25, 2.29, 2.30_

  - [ ]* 2.3 Write frozen-store integration tests
    - In a temporary content-addressed store, cover publish, verify, comparable rerun, tampering, changed artifact identity, partial staging, immutable overwrite/mutation rejection, ordered output hash mismatch, and scalar metric mismatch.
    - **Depends on:** 2.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_baseline_store_integration.py -q`
    - _Requirements: 2.3, 2.4, 2.5, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14, 2.15, 2.16, 2.22, 2.23, 2.24, 2.25_

- [ ] 3. Validate independent ground truth and freeze evaluation populations
  - [ ] 3.1 Implement the ground-truth validator, annotation isolation contract, and population builder
    - Validate complete metadata, calibrated metre coordinates, frozen reference point, source lineage, independence/contamination, uncertainty, partition exclusivity, track IDs, duplicate groups, and deterministic exclusion audits.
    - Implement annotation-tool guards that make Haware-derived overlays unavailable and require hash-verifiable source lineage.
    - Build stable per-site populations and reject insufficient counts/tracks or missing/ambiguous matches without shrinking denominators.
    - **Depends on:** 1.1, 1.3
    - **Validation:** `python -m pytest tests/haware_accuracy/test_ground_truth.py -q`
    - _Requirements: 3.1-3.37, 5.1, 5.2, 5.3, 5.4, 15.50, 15.57, 15.58_

  - [ ] 3.2 [EXTERNALLY BLOCKED: independent GT acquisition] Import, validate, and freeze GT/population artifacts for both acceptance sites
    - Acquisition/annotation is external and is not a coding task. After independently produced `kee-cc` and `taoyuan-tc` records and lineage artifacts are supplied, run the coded validator and write frozen partition/population artifacts only if each site retains at least 30 eligible detections and 3 independent non-null tracks.
    - Reject Haware-derived, contaminated, unverifiable, incomplete, duplicate, or excessive-uncertainty records; never substitute diagnostic-site data.
    - **Depends on:** 3.1; external independent GT and lineage artifacts
    - **Validation:** `python -m trafficlab.measurement ground-truth validate --site kee-cc --input <gt.json>` and the same command for `taoyuan-tc`
    - _Requirements: 3.1-3.37, 4.9-4.18_

  - [ ]* 3.3 Write the property test for deterministic ground-truth exclusion
    - **Property 17: Ground-truth exclusion is deterministic**
    - Generate independence, metadata, coordinate, uncertainty, partition, track, and duplicate-group cases; require permutation-invariant whole-group exclusion and frozen codes.
    - **Depends on:** 3.1, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_17_ground_truth_exclusion.py -q`
    - **Validates: Requirements 3.1-3.30, 15.50, 15.57, 15.58**

  - [ ]* 3.4 Write ground-truth and annotation integration tests
    - Add annotation-view smoke coverage for unavailable prohibited layers and mandatory lineage, plus sufficiency, partition disjointness, ambiguous join, and denominator-preservation fixtures.
    - **Depends on:** 3.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_ground_truth_integration.py -q`
    - _Requirements: 3.4-3.37, 5.1-5.4, 15.50_

- [ ] 4. Implement fixed-population metrics and the Phase-0 gate
  - [ ] 4.1 Implement planar error, percentile, coverage, status, and per-mode accounting
    - Compute unrounded finite metre errors, nearest-rank statistics, null empty samples, fixed-denominator usable coverage, and per-mode contributions with fallback included as a usable primary path.
    - Start with hand-computed tables for empty, fallback-heavy, and unequal usable-subset cases.
    - **Depends on:** 1.3, 3.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_metrics.py -q`
    - _Requirements: 4.1-4.8, 5.1-5.31, 15.50, 15.51, 15.53_

  - [ ] 4.2 Implement deterministic selective-risk curves
    - Sort only finite-confidence usable matches by descending confidence then frame/detection identity; use `k=ceil(cN)`, fixed population `N`, the required schedule, and explicit matched/null point behavior.
    - **Depends on:** 4.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_selective_risk.py -q`
    - _Requirements: 5.32-5.45, 15.52, 15.53_

  - [ ] 4.3 Implement paired-track confidence intervals
    - Sample the population's distinct track count with replacement, apply identical track sequences/multiplicities to both systems, recompute complete metrics, and emit frozen interval metadata and undefined-replicate handling.
    - **Depends on:** 4.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_paired_track_intervals.py -q`
    - _Requirements: 5.46-5.56_

  - [ ] 4.4 Implement per-site evidence enforcement and acceptance decisions
    - Enforce ground-truth error as primary evidence; report proxies only in strict hierarchy; filter `taipei-cm` before tuning, metrics, resampling, and decisions; evaluate all accuracy/coverage/risk gates independently at both sites; never allow pooled/proxy rescue.
    - **Depends on:** 4.1, 4.2, 4.3
    - **Validation:** `python -m pytest tests/haware_accuracy/test_acceptance_evaluator.py -q`
    - _Requirements: 4.1-4.18, 5.57-5.65, 15.37, 15.38, 15.39, 15.40_

  - [ ] 4.5 Implement the conjunctive Phase-0 gate and preliminary/finality policy
    - Require verified baseline, sufficient independent GT, and reproducible baseline metrics for each acceptance site; otherwise label wheel-first results preliminary and omit every final pass/acceptance decision.
    - **Depends on:** 2.1, 3.1, 4.4
    - **Validation:** `python -m pytest tests/haware_accuracy/test_phase0_gate.py -q`
    - _Requirements: 2.26-2.35, 3.31-3.37, 15.55, 15.56_

  - [ ]* 4.6 Write the property test for the conjunctive Phase-0 finality gate
    - **Property 18: Phase 0 is a conjunctive finality gate**
    - Generate every per-site prerequisite combination and verify exact pass versus preliminary/no-final-decision behavior.
    - **Depends on:** 4.5, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_18_phase0_gate.py -q`
    - **Validates: Requirements 2.26-2.35, 3.31-3.37, 15.55, 15.56**

  - [ ]* 4.7 Write the property test for fixed-population metric accounting
    - **Property 19: Fixed-population metric accounting**
    - Generate differing usable subsets, empty samples/modes, and fallback-heavy populations; preserve fixed denominators and require mode contributions to sum to coverage.
    - **Depends on:** 4.1, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_19_fixed_population_metrics.py -q`
    - **Validates: Requirements 5.1-5.34, 15.50, 15.51, 15.53**

  - [ ]* 4.8 Write the property test for selective-risk determinism
    - **Property 20: Selective-risk determinism**
    - Verify tie ordering, `ceil(cN)`, schedule endpoints, matched/null points, and empty curves.
    - **Depends on:** 4.2, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_20_selective_risk.py -q`
    - **Validates: Requirements 5.32-5.45, 15.52, 15.53**

  - [ ]* 4.9 Write the property test for paired-track resampling
    - **Property 21: Paired-track resampling remains paired**
    - Verify identical sampled track sequence/multiplicity, whole-metric recomputation, deterministic seeds, and interval null metadata.
    - **Depends on:** 4.3, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_21_paired_track_resampling.py -q`
    - **Validates: Requirements 5.46-5.56**

  - [ ]* 4.10 Write the property test for site-separated, proxy-proof acceptance
    - **Property 22: Acceptance is site-separate and proxy-proof**
    - Generate both acceptance sites, pooled/proxy values, and diagnostic-site add/remove/permutation cases; require both sites to pass independently.
    - **Depends on:** 4.4, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_22_site_acceptance.py -q`
    - **Validates: Requirements 4.1-4.18, 5.57-5.65, 15.37, 15.38, 15.39, 15.40**

  - [ ] 4.11 [EXTERNALLY BLOCKED: Tasks 2.2 and 3.2 artifacts] Materialize reproducible baseline metric reports and Phase-0 evidence
    - With both verified frozen baselines and sufficient frozen GT populations, use the automated harness to write deterministic per-site baseline reports and a Phase-0 evidence artifact; keep the gate failed if either site cannot reproduce.
    - **Depends on:** 2.2, 3.2, 4.5
    - **Validation:** `python -m trafficlab.measurement evaluate --phase baseline --site kee-cc --profile <profile-id>` and the same command for `taoyuan-tc`
    - _Requirements: 2.22-2.35, 3.31-3.37, 5.1-5.56_

  - [ ]* 4.12 Write metric and Phase-0 integration fixtures
    - Add known nearest-rank tables, one hand-computed paired-track fixture, fallback-heavy accounting, missing/ambiguous match failures, diagnostic invariance, and every Phase-0 prerequisite combination.
    - **Depends on:** 4.4, 4.5
    - **Validation:** `python -m pytest tests/haware_accuracy/test_metrics.py tests/haware_accuracy/test_acceptance_evaluator.py tests/haware_accuracy/test_phase0_gate.py -q`
    - _Requirements: 2.26-2.35, 4.1-4.18, 5.1-5.65_

- [ ] 5. Checkpoint — verify Phase 0 code and identify external blockers
  - Ensure all available Phase 0 tests pass, ask the user if questions arise. Do not claim Phase 0 passed while Tasks 2.2, 3.2, or 4.11 remain blocked.

- [ ] 6. Implement projection conditioning and mathematically correct weighted fitting
  - [ ] 6.1 Implement the calibrated projection-conditioning metric
    - Extend projection code with the versioned analytic homography-Jacobian metric in metres per undistorted pixel; reject invalid calibration, undistortion, denominator, Jacobian, singular value, or scale with `invalid_conditioning_metric`.
    - Add exact below/equal/above threshold examples before implementation; never use projection fallback defaults in acceptance execution.
    - **Depends on:** 1.1, 1.3
    - **Validation:** `python -m pytest tests/haware_accuracy/test_projection_conditioning.py -q`
    - _Requirements: 9.1-9.10, 15.45, 15.46, 15.47_

  - [ ] 6.2 Implement pure weighted proper-rigid Procrustes with local handedness correction
    - Preserve the Apollo-24 template and `+x=vehicle left`; mirror only the local source x column before fitting; use positive-weight centroids/covariance, proper rotation, fixed scale, profile-frozen rank/uniqueness checks, stable typed failures, and finite outputs.
    - Begin with existing north/east/arbitrary-angle examples and malformed-weight/shape cases.
    - **Depends on:** 1.1, 1.3
    - **Validation:** `python -m pytest tests/haware_accuracy/test_weighted_procrustes.py tests/test_haware_localization.py -q`
    - _Requirements: 1.1, 1.2, 7.1-7.34, 15.6-15.18, 15.23, 15.30-15.33, 15.59_

  - [ ] 6.3 Implement wheel-only, wheel-weighted, and fallback fit adapters
    - Build profile-approved supports and weights, use consistent weighted centering, compute finite residual/heading/confidence, and return reduced-confidence usable fallback without calling unresolved reprojection semantics.
    - Keep fallback behavior explicit and independently testable rather than embedding it as an exception path.
    - **Depends on:** 6.1, 6.2
    - **Validation:** `python -m pytest tests/haware_accuracy/test_mode_fitters.py -q`
    - _Requirements: 6.31-6.38, 7.1-7.34, 8.17, 8.18, 8.19, 8.20, 15.19, 15.20, 15.53_

  - [ ]* 6.4 Write the property test for handed proper-rigid recovery and equivariance
    - **Property 1: Handed proper-rigid recovery and equivariance**
    - Generate nondegenerate Apollo-24 supports, translations, and rotations; verify recovery, translation equivariance, rotation equivariance, unchanged template convention, status, and mode.
    - **Depends on:** 6.2, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_01_handed_recovery.py -q`
    - **Validates: Requirements 1.1, 1.2, 7.15-7.18, 15.6-15.12**

  - [ ]* 6.5 Write the property test for weighted Procrustes solution correctness
    - **Property 2: Weighted Procrustes solution correctness**
    - Verify positive-weight centroids/covariance, orthogonality, positive determinant, translation equation, and objective optimality against generated comparison rotations.
    - **Depends on:** 6.2, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_02_weighted_solution.py -q`
    - **Validates: Requirements 7.1-7.18, 15.17**

  - [ ]* 6.6 Write the property test for weight representation invariance
    - **Property 3: Weight representation invariance**
    - Verify positive uniform scaling and finite zero-weight additions preserve centroid, covariance, objective, rank, position, and heading; cover non-finite scaled total as `numeric_failure`.
    - **Depends on:** 6.2, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_03_weight_invariance.py -q`
    - **Validates: Requirements 7.19-7.22, 15.16, 15.18, 15.59**

  - [ ]* 6.7 Write the property test for authoritative-safe estimator validation
    - **Property 4: Typed estimator validation is authoritative-safe**
    - Generate malformed shapes, non-finite coordinates, invalid weights/totals, deficient ranks, ambiguous fits, and non-finite outputs; require exact typed codes and no authoritative position.
    - **Depends on:** 6.2, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_04_estimator_validation.py -q`
    - **Validates: Requirements 7.23-7.34, 15.23, 15.30-15.33, 15.59**

  - [ ]* 6.8 Write targeted fitter and conditioning boundary tests
    - Cover handedness regressions, exact/adjacent conditioning boundaries, invalid homography/scale, zero weights, ambiguous support, proper determinant, and finite confidence/residual for all three fit paths.
    - **Depends on:** 6.1, 6.2, 6.3
    - **Validation:** `python -m pytest tests/haware_accuracy/test_projection_conditioning.py tests/haware_accuracy/test_weighted_procrustes.py tests/haware_accuracy/test_mode_fitters.py -q`
    - _Requirements: 1.1, 1.2, 7.23-7.34, 9.1-9.16, 15.23, 15.30-15.33, 15.45-15.47_

- [ ] 7. Implement geometry-aware selection and the deterministic gate state machine
  - [ ] 7.1 Implement observation normalization and exact-seven-check wheel geometry selection
    - Validate and deterministically deduplicate/sort observations, preserve original diagnostic order, calculate diagnostic-only `n_wheel_kp`, evaluate exactly seven checks per candidate mode, enforce inclusive minima and non-overlap, and select by frozen priority without reading wheel count.
    - **Depends on:** 6.1, 6.3
    - **Validation:** `python -m pytest tests/haware_accuracy/test_mode_selector.py -q`
    - _Requirements: 1.7, 1.8, 6.1-6.30, 6.39-6.49, 15.13-15.15, 15.21, 15.22, 15.48, 15.49_

  - [ ] 7.2 Implement fallback as the primary non-wheel support path
    - Inspect fallback evidence only when every wheel mode is geometry-ineligible; cover zero-wheel, one-wheel, degenerate-wheel, and fallback-heavy traffic; condition the selected fallback support and prohibit fallback after safety rejection or fit failure.
    - **Depends on:** 7.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_fallback_selection.py -q`
    - _Requirements: 6.31-6.38, 8.6-8.11, 8.17, 8.18, 15.19-15.21, 15.53, 15.54_

  - [ ] 7.3 Implement gate precedence, inclusive spread rejection, and result finalization
    - Encode observation → support → conditioning → fit/numeric → spread → completion; first failure owns status/reason/mode, later gates become `not_evaluated`, and unsafe fit coordinates remain diagnostic-only.
    - Preserve spread after fitting but change its boundary to inclusive rejection; map successful wheel modes to `ok` and successful fallback to `fallback`.
    - **Depends on:** 7.2
    - **Validation:** `python -m pytest tests/haware_accuracy/test_gate_state_machine.py -q`
    - _Requirements: 1.3-1.6, 8.1-8.32, 9.11-9.16, 15.42-15.47, 15.54_

  - [ ]* 7.4 Write the property test for deterministic geometry-based selection
    - **Property 5: Deterministic geometry-based mode selection**
    - Generate permutations and equivalent duplicates; preserve validation, mode, reasons, status, pose, and heading while proving selection uses labeled geometry/exact checks rather than wheel count or iteration order.
    - **Depends on:** 7.1, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_05_mode_selection.py -q`
    - **Validates: Requirements 1.7, 1.8, 6.4-6.6, 6.22, 6.39-6.49, 15.13-15.15**

  - [ ]* 7.5 Write the property test for geometry boundaries and eligibility
    - **Property 6: Geometry boundary and eligibility semantics**
    - Verify eligibility iff all seven checks pass, exact inclusive minima pass, adjacent-below values fail, and validated predicates never overlap.
    - **Depends on:** 7.1, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_06_geometry_boundaries.py -q`
    - **Validates: Requirements 6.7-6.23, 6.30, 15.21, 15.22, 15.48, 15.49**

  - [ ]* 7.6 Write the property test for deterministic primary fallback
    - **Property 7: Fallback is a deterministic primary support path**
    - Generate zero/one/degenerate wheels and geometry-ineligible wheel modes; require fallback exactly when frozen non-wheel evidence and conditioning pass, otherwise `none`.
    - **Depends on:** 7.2, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_07_fallback_path.py -q`
    - **Validates: Requirements 6.31-6.38, 8.6, 8.7, 8.17, 8.18, 15.19-15.21, 15.53**

  - [ ]* 7.7 Write the property test for inclusive terminal conditioning
    - **Property 8: Conditioning rejection is inclusive and terminal**
    - Generate exact and adjacent thresholds plus invalid metrics; verify rejection before fitting and no fallback replacement.
    - **Depends on:** 7.3, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_08_conditioning_terminal.py -q`
    - **Validates: Requirements 6.24-6.29, 6.32, 6.33, 6.37, 8.8-8.11, 9.1-9.20, 15.45-15.47, 15.54**

  - [ ]* 7.8 Write the property test for first-failure gate precedence
    - **Property 9: Gate precedence is first-failure deterministic**
    - Generate simultaneous failures at all stages; require the earliest stage to determine status/reason/mode and all later stages to be `not_evaluated`.
    - **Depends on:** 7.3, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_09_gate_precedence.py -q`
    - **Validates: Requirements 8.1-8.16, 8.30-8.32, 9.11-9.14, 15.54**

  - [ ]* 7.9 Write the property test for inclusive post-fit spread rejection
    - **Property 10: Spread rejection is inclusive and post-fit**
    - Generate greatest-below, exact, and least-above spread values; verify only below passes and rejected fit positions are diagnostic-only.
    - **Depends on:** 7.3, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_10_spread_gate.py -q`
    - **Validates: Requirements 1.3-1.6, 8.14-8.16, 9.12-9.14, 15.42-15.44**

  - [ ]* 7.10 Write targeted fallback and status-state tests
    - Add a fallback-heavy matrix, equal wheel count/different geometry cases, all statuses, first-failure combinations, no-late-fallback assertions, and exact gate traces/reason codes.
    - **Depends on:** 7.1, 7.2, 7.3
    - **Validation:** `python -m pytest tests/haware_accuracy/test_mode_selector.py tests/haware_accuracy/test_fallback_selection.py tests/haware_accuracy/test_gate_state_machine.py -q`
    - _Requirements: 6.24-6.49, 8.1-8.32, 9.11-9.20_

- [ ] 8. Introduce LocalizationResultV2 and opt-in compatibility
  - [ ] 8.1 Implement V2 result invariants and deterministic serialization
    - Define all approved status/mode/gate/coordinate-role fields; require `usable` iff `ok|fallback`, alias usable `sat_coords` to authoritative coordinates, null both on unusable results, and mark retained unsafe coordinates diagnostic-only.
    - **Depends on:** 1.3, 7.3
    - **Validation:** `python -m pytest tests/haware_accuracy/test_result_v2.py -q`
    - _Requirements: 8.17-8.32, 12.1-12.14, 13.15-13.18, 13.22-13.30_

  - [ ] 8.2 Implement configuration dispatch and legacy compatibility mappings
    - Validate configuration before payloads; absent/false dispatches unchanged legacy behavior and originating unversioned schema, enabled supported versions dispatch to V2, and unsupported types/versions fail deterministically.
    - Require explicit legacy status policy before downstream normalization and record that policy in output metadata.
    - **Depends on:** 2.1, 8.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_compatibility.py -q`
    - _Requirements: 1.14-1.17, 10.27-10.29, 13.1-13.36_

  - [ ]* 8.3 Write the property test for coherent result states and coordinate roles
    - **Property 11: Result state and coordinate roles are coherent**
    - Generate every supported state; verify usable modes/finite authoritative positions and unusable `none`/null authoritative aliases with diagnostic-only retention.
    - **Depends on:** 8.1, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_11_result_coherence.py -q`
    - **Validates: Requirements 8.17-8.29, 13.16-13.18, 15.24, 15.26, 15.41**

  - [ ]* 8.4 Write the property test for versioned schema round trips
    - **Property 14: Versioned schema round trip**
    - Generate valid records across every supported schema/status/mode and preserve fields, finite values, enums, nulls, arrays, object meaning, and originating legacy mapping.
    - **Depends on:** 8.1, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_14_schema_roundtrip.py -q`
    - **Validates: Requirements 13.15-13.18, 13.22-13.30, 15.26, 15.28, 15.34, 15.35**

  - [ ]* 8.5 Write the property test for disabled-mode frozen parity
    - **Property 15: Disabled-mode frozen parity**
    - Against the frozen inventory, verify absent/false dispatch preserves every finite component within `1e-9`, heading within angular `1e-9`, exact statuses/nulls, and legacy-only schema.
    - **Depends on:** 2.2, 8.2, 1.5; externally blocked until goldens exist
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_15_disabled_parity.py -q`
    - **Validates: Requirements 1.14-1.17, 13.1, 13.2, 13.19-13.21, 15.29**

  - [ ]* 8.6 Write targeted V2, invalid-config, and compatibility golden tests
    - Cover all valid status/mode combinations, malformed statuses, unsupported versions and supported-list details, exact legacy null/status behavior, and explicit legacy policy metadata.
    - **Depends on:** 8.2
    - **Validation:** `python -m pytest tests/haware_accuracy/test_result_v2.py tests/haware_accuracy/test_compatibility.py -q`
    - _Requirements: 1.14-1.17, 10.27-10.29, 13.1-13.36, 15.28, 15.29, 15.34, 15.35_

- [ ] 9. Add replayable diagnostics and auditability
  - [ ] 9.1 Upgrade the replay adapter and ordered per-attempt diagnostics recorder
    - Assign stable site/frame/detection identifiers, retain non-null acceptance track IDs, serialize raw and normalized observations without metric rounding, and record every accepted/rejected attempt with supports, weights, seven checks, fallback evidence, conditioning, fit details, gates, coordinate roles, and artifact/profile/run provenance.
    - **Depends on:** 8.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_replay_adapter.py -q`
    - _Requirements: 6.43-6.47, 9.17-9.20, 12.1-12.22_

  - [ ] 9.2 Implement deterministic aggregate reports, diagnostics replay, and threshold audits
    - Derive canonical aggregate reports and human summaries solely from ordered records; name every denominator predicate and apply frozen zero-denominator rules.
    - Verify source hashes and replay validation/selection/fitting without PifPaf; reproduce decisions, gate outcomes, statuses, roles, report hashes, and summaries; record old/new threshold, reason, and run ID without editing published profiles.
    - **Depends on:** 1.2, 9.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_diagnostics_replay.py -q`
    - _Requirements: 12.23-12.41_

  - [ ]* 9.3 Write the property test for replay-deterministic diagnostics
    - **Property 23: Diagnostics are replay-deterministic**
    - Generate hash-matching replay artifacts and require exact mode/gate/status/usability/reason/role/aggregate/report-hash/summary reproduction.
    - **Depends on:** 9.2, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_23_diagnostics_replay.py -q`
    - **Validates: Requirements 6.43-6.47, 9.17-9.20, 12.1-12.36, 12.38-12.41**

  - [ ]* 9.4 Write a fallback-heavy replay integration test
    - Replay stored keypoints through wheel and fallback modes, V2 serialization, deterministic diagnostics replay, and report generation without inference; include rejected attempts and artifact-tamper failure.
    - **Depends on:** 9.2
    - **Validation:** `python -m pytest tests/haware_accuracy/test_replay_integration.py -q`
    - _Requirements: 8.17-8.32, 12.1-12.41_

- [ ] 10. Enforce authoritative coordinates in enrichment and scene building
  - [ ] 10.1 Implement compatibility-normalized enrichment and interruption-safe velocity
    - Normalize every input through compatibility policy; derive `position_m` only from finite authoritative positions on usable records; copy status/mode/confidence/reasons unchanged; close segments on every defined interruption and null the first subsequent velocity.
    - Start with unusable/diagnostic-only and interruption table tests.
    - **Depends on:** 8.2
    - **Validation:** `python -m pytest tests/haware_accuracy/test_enrichment.py -q`
    - _Requirements: 8.32, 10.1-10.18, 10.27-10.29, 15.24, 15.41, 15.60_

  - [ ] 10.2 Enforce usable authoritative positions in scene scanning and collider creation
    - Include only usable finite authoritative `position_m`; exclude diagnostic coordinates from extents, frame ranges, interpolation, collision geometry, and collider eligibility; report accepted/excluded counts by status/mode and fail empty requested tracks with `no_usable_collider_observations` plus status counts.
    - **Depends on:** 10.1
    - **Validation:** `python -m pytest ../tools/tests/test_build_scene.py ../tools/tests/test_build_scene_edges.py -q`
    - _Requirements: 10.19-10.26, 15.25, 15.41_

  - [ ]* 10.3 Write the property test for authoritative-only downstream propagation
    - **Property 12: Authoritative-only downstream propagation**
    - Generate V2 usable/unusable/diagnostic-only records and require null spatial outputs and exclusion for every non-authoritative coordinate across enrichment, scene, collider, and enabled-fusion interfaces.
    - **Depends on:** 10.2, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_12_authoritative_only.py -q`
    - **Validates: Requirements 8.32, 10.1-10.3, 10.19-10.26, 11.11-11.13, 15.24, 15.25, 15.27, 15.41**

  - [ ]* 10.4 Write the property test for interruption-safe velocity
    - **Property 13: Track interruptions prevent velocity bridging**
    - Generate ordered streams and require finite delta/time velocity only for consecutive usable observations in one uninterrupted non-null track; every interruption makes the first subsequent velocity null.
    - **Depends on:** 10.1, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_13_track_interruptions.py -q`
    - **Validates: Requirements 10.4-10.13, 15.60**

  - [ ]* 10.5 Write replay-to-scene authoritative-gating integration tests
    - Carry a fallback-heavy V2 replay through enrichment and scene scanning; prove usable fallback is measured/enriched/scene-eligible while extrapolated, near-horizon, abstained, insufficient-keypoint, and diagnostic-only positions cannot affect scenes or colliders.
    - **Depends on:** 9.2, 10.2
    - **Validation:** `python -m pytest tests/haware_accuracy/test_replay_to_scene.py ../tools/tests/test_build_scene*.py -q`
    - _Requirements: 8.17-8.32, 10.1-10.29, 12.1-12.41, 15.24, 15.25, 15.41, 15.53_

- [ ] 11. Wire and evaluate two-site unfused single-frame acceptance
  - [ ] 11.1 Implement the single-frame candidate evaluation command and immutable report package
    - Wire verified artifacts, fixed populations, V2 candidate outputs, diagnostics, per-site metrics, paired intervals, mode/fallback contributions, risk curves, and finality policy into one deterministic command.
    - Keep `kee-cc` and `taoyuan-tc` decisions separate; emit pooled values only as informational and `taipei-cm` only as diagnostic.
    - **Depends on:** 4.5, 9.2, 10.2
    - **Validation:** `python -m pytest tests/haware_accuracy/test_single_frame_acceptance.py -q`
    - _Requirements: 2.26-2.35, 4.1-4.18, 5.1-5.65, 8.17-8.32, 10.1-10.26, 12.1-12.41_

  - [ ] 11.2 [EXTERNALLY BLOCKED: passed Phase 0 and frozen candidate artifacts] Materialize two-site single-frame acceptance results
    - Once Task 4.11 proves Phase 0 and frozen V2 candidate outputs exist, generate immutable separate `kee-cc` and `taoyuan-tc` reports over identical fixed populations; reject the candidate if either site fails median, p90, coverage, required 20%/all matched risk points, or any integrity gate.
    - If profile thresholds change, create a new profile artifact and complete threshold audit records; never mutate the approved artifact or tune from `taipei-cm`.
    - **Depends on:** 4.11, 11.1; external candidate replay artifacts
    - **Validation:** `python -m trafficlab.measurement evaluate --phase candidate --site kee-cc --profile <profile-id> --candidate <artifact-id>` and the same command for `taoyuan-tc`
    - _Requirements: 4.1-4.18, 5.57-5.65, 12.37-12.41_

  - [ ]* 11.3 Write two-site single-frame acceptance integration tests
    - Use deterministic fixtures to prove independent site decisions, required matched 20% risk, no pooled/proxy rescue, diagnostic invariance, Phase-0 preliminary behavior, and fallback participation in every relevant metric.
    - **Depends on:** 11.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_single_frame_acceptance.py -q`
    - _Requirements: 2.26-2.35, 4.1-4.18, 5.1-5.65, 15.37-15.40, 15.50-15.56_

- [ ] 12. Run eta calibration analysis on a parallel, non-blocking branch
  - [ ] 12.1 Implement site/family-specific effective-eta analysis and identifiability labels
    - Reject degenerate/non-finite rays; compute and aggregate eta only within site/height family; emit finite ordered intervals and complete provenance; never infer separate `h` and `z_cam` from image-only data or zero-height wheels.
    - Emit direct or jointly identified physical quantities only under the approved independent-positive-evidence conditions, using distinct authoritative field names.
    - **Depends on:** 1.1, 1.3
    - **Validation:** `python -m pytest tests/haware_accuracy/test_calibration_analyzer.py -q`
    - _Requirements: 14.1-14.30, 15.36, 15.61, 15.62_

  - [ ]* 12.2 Write the property test for explicit calibration identifiability
    - **Property 25: Calibration identifiability is explicit**
    - Generate site/family samples, zero-inclusive intervals, independent height/metrology cases, and finite positive quotients; prohibit unsupported authoritative camera-height claims.
    - **Depends on:** 12.1, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_25_calibration_identifiability.py -q`
    - **Validates: Requirements 14.1-14.30, 15.36, 15.61, 15.62**

  - [ ]* 12.3 Write targeted calibration interval and provenance tests
    - Cover zero eta, positive eta with strictly positive interval, zero-inclusive/invalid intervals, direct metrology, missing calibration IDs, cross-site/family pooling rejection, and independence from localization acceptance.
    - **Depends on:** 12.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_calibration_analyzer.py -q`
    - _Requirements: 14.1-14.30, 15.36, 15.61, 15.62_

  - [ ] 12.4 [EXTERNALLY BLOCKED: independent calibration samples/metrology] Materialize eta analysis artifacts without blocking acceptance
    - When calibrated camera/target points, documented height-family provenance, and any claimed direct metrology are supplied with valid hashes, generate separate site/family eta reports. Leave unsupported physical fields omitted and clearly label missing artifacts.
    - This branch may execute in parallel with baseline, GT, estimator, and acceptance work; its blocked or failed state must not replace or block wheel-first position-accuracy evidence.
    - **Depends on:** 12.1; external independent calibration artifacts
    - **Validation:** `python -m trafficlab.measurement calibration analyze --site <kee-cc|taoyuan-tc> --family <name> --input <samples.json>`
    - _Requirements: 14.1-14.30_

- [ ] 13. Conditionally evaluate optional temporal fusion
  - [ ] 13.1 Implement and record the temporal-fusion permission predicate
    - Permit fusion only when every single-frame prerequisite gate from Requirements 1–10 (excluding Requirement 5 candidate-improvement thresholds) passes and at least one single-frame Requirement 5 target remains unmet; otherwise record `unnecessary` or `not_permitted` and skip all later temporal waves.
    - Keep fusion disabled by default and require a distinct versioned algorithm/configuration artifact before use.
    - **Depends on:** 4.5, 11.1
    - **Validation:** `python -m pytest tests/haware_accuracy/test_fusion_permission.py -q`
    - _Requirements: 11.1-11.10_

  - [ ]* 13.2 [CONDITIONAL: only if Task 13.1 returns permitted] Implement offline temporal fusion with immutable source provenance
    - Segment only uninterrupted equal non-null tracks using enrichment gap rules; pass unusable records through unchanged/null and terminate segments; retain unfused coordinates and complete fusion provenance for every changed usable result.
    - Never mutate single-frame artifacts or use diagnostic positions; issue a distinct fusion candidate and re-evaluate both sites against the identified source candidate.
    - **Depends on:** 10.1, 13.1; permitted predicate and frozen fusion algorithm/configuration
    - **Validation:** `python -m pytest tests/haware_accuracy/test_temporal_fusion.py -q`
    - _Requirements: 11.1-11.26_

  - [ ]* 13.3 [CONDITIONAL: only if Task 13.2 executes] Write the property test for fusion safety and non-regression
    - **Property 24: Fusion preserves source safety and cannot regress site gates**
    - Generate interruptions, unusable records, changed usable results, and per-site regressions; require immutable source, complete provenance, no coverage decrease, and no p90 increase.
    - **Depends on:** 13.2, 1.5
    - **Validation:** `python -m pytest tests/haware_accuracy/properties/test_property_24_fusion_safety.py -q`
    - **Validates: Requirements 11.1-11.26, 15.27**

  - [ ]* 13.4 [CONDITIONAL: only if Task 13.2 executes] Write optional fusion end-to-end tests
    - Cover permission denied/unnecessary/permitted fixtures, interruption segmentation, unusable pass-through, provenance completeness, identical-population source comparison, and independent `kee-cc`/`taoyuan-tc` coverage/p90 rejection.
    - **Depends on:** 13.2
    - **Validation:** `python -m pytest tests/haware_accuracy/test_temporal_fusion.py tests/haware_accuracy/test_fusion_acceptance.py -q`
    - _Requirements: 11.1-11.26, 15.27_

- [ ] 14. Final checkpoint — validate all applicable scopes
  - Ensure all tests pass, ask the user if questions arise. Run temporal scopes only when Task 13.1 permits them; report externally blocked artifacts separately from code/test failures.

## Notes

- Tasks marked with `*` are optional test tasks, except conditional Tasks 13.2–13.4, which are optional by product design and must be skipped unless Task 13.1 records `permitted`.
- Every implementation task should use a red-green-refactor cycle for the targeted examples named in its bullets; property tests add universal generated coverage and do not replace examples.
- External acquisition, annotation, metrology, and candidate production are not coding tasks. Tasks 2.2, 3.2, 4.11, 11.2, and 12.4 are code-backed artifact materialization steps that remain explicitly blocked until supplied artifacts are hash-valid and complete.
- Fallback is a primary usable mode throughout fitting, diagnostics, accuracy, coverage, selective risk, enrichment, and scene tests; it is never treated as an exception-only path.
- `taipei-cm` is diagnostic-only and cannot provide missing acceptance inputs, tune thresholds, or rescue either acceptance site.
- Recommended one-shot scopes after targeted tests exist (do not use watch mode):
  - Phase 0: `python -m pytest tests/haware_accuracy/test_canonical_artifacts.py tests/haware_accuracy/test_schema_contracts.py tests/haware_accuracy/test_baseline_store*.py tests/haware_accuracy/test_ground_truth*.py tests/haware_accuracy/test_metrics.py tests/haware_accuracy/test_selective_risk.py tests/haware_accuracy/test_paired_track_intervals.py tests/haware_accuracy/test_phase0_gate.py -q`
  - Single-frame core: `python -m pytest tests/test_haware_localization.py tests/haware_accuracy/test_projection_conditioning.py tests/haware_accuracy/test_weighted_procrustes.py tests/haware_accuracy/test_mode_fitters.py tests/haware_accuracy/test_mode_selector.py tests/haware_accuracy/test_fallback_selection.py tests/haware_accuracy/test_gate_state_machine.py tests/haware_accuracy/test_result_v2.py tests/haware_accuracy/test_compatibility.py -q`
  - Replay/downstream: `python -m pytest tests/haware_accuracy/test_replay*.py tests/haware_accuracy/test_diagnostics_replay.py tests/haware_accuracy/test_enrichment.py tests/haware_accuracy/test_replay_to_scene.py ../tools/tests/test_build_scene.py ../tools/tests/test_build_scene_edges.py -q`
  - All properties: `python -m pytest tests/haware_accuracy/properties -m property -q`
  - Full affected suite: `python -m pytest tests ../tools/tests -q`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.5"] },
    { "id": 2, "tasks": ["1.4", "1.6", "1.7", "2.1", "3.1", "6.1", "6.2", "12.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "3.2", "3.3", "3.4", "4.1", "6.3", "6.4", "6.5", "6.6", "6.7", "12.2", "12.3", "12.4"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.7", "6.8", "7.1"] },
    { "id": 5, "tasks": ["4.8", "4.9", "7.2", "7.4", "7.5"] },
    { "id": 6, "tasks": ["4.4", "7.3", "7.6"] },
    { "id": 7, "tasks": ["4.5", "4.10", "7.7", "7.8", "7.9", "7.10"] },
    { "id": 8, "tasks": ["4.6", "4.12", "8.1"] },
    { "id": 9, "tasks": ["4.11", "8.2", "8.3", "8.4"] },
    { "id": 10, "tasks": ["8.5", "8.6", "9.1", "10.1"] },
    { "id": 11, "tasks": ["9.2", "10.2", "10.4"] },
    { "id": 12, "tasks": ["9.3", "9.4", "10.3", "10.5", "11.1"] },
    { "id": 13, "tasks": ["11.2", "11.3", "13.1"] },
    { "id": 14, "condition": "Task 13.1 == permitted", "tasks": ["13.2"] },
    { "id": 15, "condition": "Task 13.2 executed", "tasks": ["13.3", "13.4"] }
  ]
}
```
