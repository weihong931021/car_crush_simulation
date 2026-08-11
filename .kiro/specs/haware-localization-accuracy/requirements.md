# Requirements Document

## Introduction

This specification defines measurable requirements for improving Haware vehicle localization accuracy. A reliability-aware multi-cue estimator is the core new algorithm and depends on a Phase 0 measurement system. The estimator may use wheel or ground-contact cues, windshield or glass-corner cues, roof-corner cues, mirror cues, and other documented keypoint families when the available view provides reliable evidence. Wheel and ground-contact cues are preferred zero-height anchors for position because `h=0` removes the vertical-parallax correction term, but no cue family is globally exclusive. Existing handedness correction, spread gating, and `n_wheel_kp` behavior remain in scope as preserved capabilities. Reduced-evidence fallback and explicit abstention are primary operating outcomes. Historical taipei-cm observations motivate the work but are diagnostic-only; acceptance uses kee-cc and taoyuan-tc independently.

## Glossary

- **Localization_Improvement_System**: The complete Haware localization measurement, estimation, filtering, enrichment, and scene-building capability governed by this specification.
- **Measurement_Harness**: The reproducible evaluation capability that creates baselines, evaluates candidates, and produces metric reports.
- **Canonical_JSON**: UTF-8 JSON encoded with sorted object keys, no insignificant whitespace, normalized line feed termination, preserved array order, and finite JSON numbers.
- **Artifact_Hash**: The lowercase 64-character hexadecimal SHA-256 digest of an artifact's exact byte sequence.
- **Baseline_Manifest**: A Canonical_JSON document containing `baseline_id`, source revision, clean-or-dirty source state, dependency-lock Artifact_Hash, runtime and platform versions, every effective configuration value, ordered input inventory with Artifact_Hashes, invocation commands, random seeds, ordered output inventory with Artifact_Hashes, metric-definition version, and creation timestamp.
- **Baseline_Identity_Payload**: The Baseline_Manifest object with the `baseline_id` and creation timestamp fields removed, encoded as Canonical_JSON without changing any remaining value or array order.
- **Baseline_ID**: The Artifact_Hash of the exact Baseline_Identity_Payload bytes.
- **Comparability_Fields**: Source revision, clean-or-dirty source state, dependency-lock Artifact_Hash, runtime and platform versions, every effective configuration value, ordered input inventory with Artifact_Hashes, invocation commands, random seeds, and metric-definition version. Baseline identifier, creation timestamp, ordered output inventory, and output metrics are reproduction results and are excluded from comparability classification.
- **Comparable_Rerun**: A rerun for which every Comparability_Field has the same Canonical_JSON type and value, including array order, as the Frozen_Baseline.
- **Frozen_Baseline**: A published Baseline_Manifest and content-addressed artifacts. Publication makes the Baseline_ID immutable: existing bytes remain addressable by the Baseline_ID, replacement is prohibited, and any manifest or artifact byte change creates a different Baseline_ID.
- **Phase_0_Gate**: The prerequisite requiring a verified Frozen_Baseline, a sufficient Ground_Truth_Dataset, and a reproducible baseline metric report for both Acceptance_Sites.
- **Ground_Truth_Dataset**: Independently produced vehicle reference positions in the calibrated satellite coordinate frame together with complete Ground_Truth_Metadata.
- **Ground_Truth_Metadata**: Satellite-image Artifact_Hash, calibration identifier and Artifact_Hash, coordinate origin, axis directions, units, vehicle reference-point definition, site, frame identifier, detection identifier, track identifier, source timestamp, annotation timestamp, annotator identifier, annotation method and tool version, source-artifact Artifact_Hashes, uncertainty in metres, uncertainty-estimation method, independence declaration, and contamination declaration.
- **Ground_Truth_Contamination**: Use or display during reference-position creation of Haware satellite coordinates, fitted centers, headings, projected keypoints, localization overlays, candidate outputs, or metrics derived from those values.
- **Independence_Violation**: Ground_Truth_Contamination, a false or missing independence declaration, use of a source artifact derived from a Haware baseline or candidate localization, or inability to verify recorded source-artifact lineage.
- **Acceptance_Site**: One of `kee-cc` or `taoyuan-tc`.
- **Diagnostic_Site**: `taipei-cm`, whose records may appear only in diagnostic outputs.
- **Eligible_Detection**: A detection satisfying the frozen site, partition, timestamp, matching, annotation-quality, uncertainty, independence, and inclusion rules before baseline or candidate status is considered.
- **Evaluation_Population**: The identical ordered set of Eligible_Detections used as the fixed denominator for a baseline and candidate at one Acceptance_Site; every record has one non-null track identifier used as the paired resampling cluster.
- **Matched_Detection**: An Eligible_Detection joined to exactly one reference position by site, frame identifier, and detection identifier.
- **Planar_Position_Error**: `sqrt((x_est - x_gt)^2 + (y_est - y_gt)^2)` in metres, computed without rounding from finite coordinates in the same calibrated satellite frame, for a Matched_Detection with a Usable_Localization.
- **Error_Sample**: The ordered Planar_Position_Error values for every usable Matched_Detection produced by exactly one system, baseline or candidate, over one fixed Evaluation_Population; unusable detections remain in coverage denominators but do not contribute an error value.
- **Usable_Localization**: A localization with status `ok` or `fallback`, `usable=true`, and a finite Authoritative_Position.
- **Unusable_Localization**: A localization with status `extrapolated`, `near_horizon`, `abstained`, or `failed_insufficient_kp`, `usable=false`, and no Authoritative_Position.
- **Authoritative_Position**: The coordinate field permitted for enrichment, velocity calculation, scene positions, and colliders.
- **Diagnostic_Position**: An optional coordinate field retained for analysis and prohibited from downstream spatial use.
- **Estimator_Mode**: One of `single_family`, `complementary_multi_cue`, `fallback`, or `none`.
- **Cue_Family**: A documented semantic group of Apollo-24 keypoints with common physical role and height treatment; required families are `wheel_ground_contact`, `windshield_glass_corner`, `roof_corner`, `mirror`, and `other_documented`.
- **Height_Family**: A Cue_Family subset whose members share one documented height prior and Effective_Eta uncertainty model for orientation estimation.
- **Zero_Height_Anchor**: A wheel or other validated ground-contact cue with documented height `h=0`, for which the vertical-parallax correction term is zero.
- **Cue_Reliability_Factors**: Visibility, projected baseline or leverage for the proposed constraint, Projection_Conditioning_Metric, keypoint confidence, label and semantic consistency, Height_Family uncertainty, and frozen Site_View_Evidence.
- **Site_View_Evidence**: Versioned evidence associated with one site and documented view region that records validated cue behavior, including semantic anomalies and applicable sample provenance, without authorizing global conclusions from one site or view.
- **Cue_Eligibility_Checks**: The frozen checks for Cue_Family membership, required visibility, minimum template and observed projected baseline or leverage, required centered-template and centered-observation rank where applicable, minimum confidence, label and semantic consistency, Height_Family uncertainty, Site_View_Evidence, and projection conditioning.
- **Observation_Validity_Profile**: The versioned Acceptance_Profile section that freezes valid coordinate and confidence domains, required identifiers and labels, missing-value treatment, and the Duplicate_Keypoint_Policy before evaluation.
- **Duplicate_Keypoint_Policy**: The frozen deterministic rule for repeated keypoint identifiers, including the result for equal duplicate values and conflicting duplicate values.
- **Geometry_Profile**: The versioned Acceptance_Profile section that freezes Cue_Family definitions, Height_Family definitions, candidate constraint roles, topology rules, projected baseline and leverage thresholds, rank tolerances, confidence thresholds, semantic-consistency rules, height-family uncertainty rules, Site_View_Evidence gates, fallback-evidence rules, non-overlapping mode predicates, deterministic mode priority, and fit-uniqueness tolerance before evaluation.
- **Reliability_Aware_Multi_Cue_Estimator**: The estimator that selects and weights eligible cue constraints by Cue_Reliability_Factors, prefers Zero_Height_Anchors for parallax-free position support, permits complementary cue roles, and otherwise emits an explicit fallback or unusable outcome.
- **Mode_Selector**: The deterministic component that evaluates observation validity, Cue_Eligibility_Checks, Cue_Reliability_Factors, constraint role, projection conditioning, and frozen priority rules to select one Estimator_Mode.
- **Primary_Support_Path**: An eligible `single_family` or `complementary_multi_cue` estimator path selected from reliability-qualified cue constraints.
- **Fallback_Path**: A usable reduced-confidence estimator path selected only when every Primary_Support_Path is ineligible and valid reduced evidence satisfies the frozen fallback predicate.
- **Orientation_Constraint**: A heading constraint estimated within one Height_Family; constraints from different Height_Families may be combined only after each family is estimated separately and the combination accounts for Effective_Eta uncertainty.
- **Position_Bearing_Constraint**: A cue-derived constraint on position, centerline, or camera-relative bearing that does not by itself imply reliable heading.
- **Projection_Conditioning_Metric**: A finite scalar derived only from calibrated projection geometry and one observation coordinate, ordered so that larger values represent greater near-horizon amplification.
- **Near_Horizon_Threshold**: The frozen inclusive rejection boundary for the Projection_Conditioning_Metric: finite values below the boundary pass and finite values equal to or above the boundary fail.
- **Spread_Gate**: The existing post-projection keypoint-spread check with a frozen inclusive rejection boundary: finite spread strictly below the boundary passes and finite spread equal to or above the boundary fails.
- **Gate_Order**: The deterministic status-decision order: (1) observation validity and count; (2) cue eligibility and role assignment followed, only when every Primary_Support_Path is ineligible, by fallback-evidence eligibility; (3) projection conditioning for the selected support path; (4) fit and numeric validation; (5) Spread_Gate; and (6) usable mode completion. The first failing stage determines status, and a later fallback cannot replace an earlier safety rejection.
- **Weighted_Procrustes_Estimator**: A fixed-scale two-dimensional proper-rigid estimator for paired points `Q_i` and `P_i` with nonnegative weights `w_i`; zero-weight points are excluded from centroids, covariance, objective, and rank; positive-weight total `W = sum_i(w_i)`; weighted centroids `q_bar = sum_i(w_i Q_i)/W` and `p_bar = sum_i(w_i P_i)/W`; covariance `H = sum_i(w_i (Q_i-q_bar)(P_i-p_bar)^T)`; proper rotation `R` minimizing `sum_i(w_i ||P_i-(R Q_i+t)||^2)` subject to `R^T R = I` and `det(R)=+1`; and translation `t = p_bar - R q_bar`.
- **Ambiguous_Fit**: A fit for which the positive-weight correspondences do not identify one proper rotation within the frozen fit-uniqueness tolerance.
- **Typed_Validation_Failure**: A machine-readable failure with a stable error code, detection identifier, failed field or gate, and no Authoritative_Position.
- **Proxy_Metric**: A non-ground-truth diagnostic: wheelbase consistency, track-width consistency, motion-course heading consistency, fit residual, or keypoint spread.
- **Evidence_Hierarchy**: The strict order: Ground_Truth_Dataset Planar_Position_Error; ground-plane wheelbase and track-width consistency; motion-course heading consistency; fit residual and keypoint spread.
- **Usable_Coverage**: At one Acceptance_Site, the count of Evaluation_Population records with a Usable_Localization divided by the Evaluation_Population count.
- **Per_Mode_Coverage_Contribution**: For one Estimator_Mode at one Acceptance_Site, the count of Evaluation_Population records that are usable and have the Estimator_Mode divided by the Evaluation_Population count; the three usable-mode contributions sum to Usable_Coverage.
- **Nearest_Rank_Percentile**: For `m > 0` values sorted in nondecreasing order, percentile `p` is the value at one-based rank `ceil(p*m)`.
- **Selective_Risk**: At retained count `k > 0`, the arithmetic mean Planar_Position_Error of the first `k` usable Matched_Detections after descending finite-confidence sort, with confidence ties ordered by frame identifier and detection identifier; requested coverage is `k/N`, where `N` is the fixed Evaluation_Population count. Non-finite-confidence records remain in `N` and coverage metrics but are ineligible for retention.
- **Matched_Coverage_Point**: A requested coverage `c` for which `k = ceil(cN)` and both baseline and candidate contain at least `k` finite-confidence usable Matched_Detections.
- **Paired_Track_Confidence_Interval**: A percentile confidence interval for a candidate-minus-baseline metric difference. Every replicate samples, with replacement, exactly as many distinct track identifiers as occur in the Evaluation_Population, applies the same sampled identifier sequence and multiplicities to baseline and candidate records, recomputes the complete metric, and records candidate value minus baseline value. The Acceptance_Profile freezes replicate count, confidence level, random seed, percentile endpoints, and handling of an undefined replicate metric.
- **Acceptance_Profile**: The immutable, versioned metric definitions, thresholds, partitions, Observation_Validity_Profile, Geometry_Profile, conditioning and spread boundaries, confidence-interval procedure, temporal gap, and deterministic tie rules frozen before candidate evaluation.
- **Enrichment_Pipeline**: The replay filtering and enrichment stage that derives metric positions and velocities.
- **Track_Interruption**: An unusable or missing localization, null or changed track identifier, non-increasing timestamp, or frame gap greater than the Acceptance_Profile maximum frame gap.
- **Consecutive_Usable_Observations**: Two usable observations adjacent within one uninterrupted track segment, with equal non-null track identifiers, strictly increasing timestamps, and no intervening unusable or missing observation.
- **Velocity_Mps**: For Consecutive_Usable_Observations, `(current_position_m - previous_position_m) / (current_timestamp - previous_timestamp)` with timestamp difference expressed in seconds.
- **Scene_Builder**: The stage that scans enriched tracks and creates scene packages.
- **Temporal_Fusion_Module**: An optional offline replay postprocessor that combines usable observations from one uninterrupted tracked vehicle segment.
- **Single_Frame_Prerequisite_Gates**: Every Requirement 1 through 10 criterion governing baseline validity, evidence validity, computation correctness, estimator behavior, safety status, downstream exclusion, and observability, excluding Requirement 5 candidate-improvement thresholds and pass-fail criteria.
- **Fusion_Provenance**: Fusion algorithm and version, configuration Artifact_Hash, evaluation-run identifier, source frame and detection identifiers, source statuses, source coordinates, source confidences, fusion weights or gains, frame gaps, unfused result, fused result, and fusion status.
- **Diagnostics_Recorder**: The capability that records replayable per-detection provenance and deterministic aggregate localization reports.
- **Diagnostics_Report_Schema**: The immutable versioned report schema frozen before candidate evaluation that defines every aggregate-rate denominator predicate and the null-or-omitted representation for every zero-denominator rate.
- **Compatibility_Layer**: The opt-in capability that supports versioned reliability-aware multi-cue records while preserving frozen legacy behavior when multi-cue functionality is disabled.
- **Schema_Compatibility_Profile**: The immutable ordered list of supported schema versions, including any explicitly named unversioned legacy schema, with required fields, optional fields, field types, enum domains, nullability, and deterministic read/write mappings for every version.
- **Calibration_Analyzer**: The capability that estimates calibration-related quantities without overstating identifiability.
- **Effective_Eta**: The dimensionless ratio `eta = h / z_cam` inferred for one site and one documented keypoint-height family; image observations identify the ratio rather than `h` and `z_cam` separately.
- **Effective_Eta_Interval**: A finite ordered pair `[lower, upper]` with `lower <= upper`; the interval includes zero exactly when `lower <= 0 <= upper`.
- **Direct_Z_Cam**: A positive physical camera height measured by independent metrology without using Effective_Eta or Haware localization outputs.
- **Jointly_Identified_Z_Cam**: A positive physical camera height computed as `h / eta` from independently measured positive `h` and an Effective_Eta_Interval that excludes zero.
- **Validation_Suite**: Automated example-based and property-based tests for estimator, status, serialization, evaluation, and downstream correctness.
- **PBT_Profile**: Property-test configuration using seeds `104729`, `130363`, `155921`, and `196613`, at least 100 generated cases per property per seed, point counts from 2 through 24, finite source coordinates in `[-100, 100]`, translations in `[-10000, 10000]` pixels, rotations in `[-180, 180)` degrees, positive weights in `[2^-10, 2^10]`, positive uniform weight multipliers in `[2^-10, 2^10]`, minimum distinct-point separation `1e-3`, and required normalized singular value at least `1e-6`.
- **Angular_Difference**: The absolute shortest signed difference between two headings after normalization to `[-180, 180)` degrees.

## Requirements

### Requirement 1: Preserve Existing Corrections and Define Change Scope

**User Story:** As a localization maintainer, I want existing corrections distinguished from new work, so that implementation effort targets unresolved accuracy problems.

#### Acceptance Criteria

1. THE Localization_Improvement_System SHALL preserve the existing template-to-satellite handedness correction.
2. THE Localization_Improvement_System SHALL preserve the template convention `+x = vehicle left`.
3. THE Localization_Improvement_System SHALL preserve the existing Spread_Gate position after pose fitting.
4. WHEN finite projected spread is strictly below the frozen Spread_Gate boundary, THE Spread_Gate SHALL return `pass`.
5. WHEN finite projected spread equals the frozen Spread_Gate boundary, THE Spread_Gate SHALL return `fail`.
6. WHEN finite projected spread exceeds the frozen Spread_Gate boundary, THE Spread_Gate SHALL return `fail`.
7. THE Localization_Improvement_System SHALL preserve `n_wheel_kp` as the count of observation-valid visible keypoints with Apollo-24 index `7`, `8`, `18`, or `19`.
8. THE Mode_Selector SHALL exclude `n_wheel_kp` from every mode-eligibility predicate.
9. THE Localization_Improvement_System SHALL classify reliability-aware multi-cue estimation as the core new localization algorithm.
10. THE Localization_Improvement_System SHALL classify status propagation as supporting reliability-aware multi-cue work.
11. THE Localization_Improvement_System SHALL classify near-horizon conditioning as supporting reliability-aware multi-cue work.
12. THE Localization_Improvement_System SHALL classify measurement as supporting reliability-aware multi-cue work.
13. THE Localization_Improvement_System SHALL classify conditional temporal fusion as supporting reliability-aware multi-cue work.
14. WHEN multi-cue functionality is disabled, THE Compatibility_Layer SHALL reproduce every finite Frozen_Baseline satellite-coordinate component within absolute error `1e-9` pixels.
15. WHEN multi-cue functionality is disabled, THE Compatibility_Layer SHALL reproduce every finite Frozen_Baseline heading within Angular_Difference `1e-9` degrees.
16. WHEN multi-cue functionality is disabled, THE Compatibility_Layer SHALL reproduce every Frozen_Baseline status exactly.
17. WHEN multi-cue functionality is disabled, THE Compatibility_Layer SHALL reproduce every Frozen_Baseline null value exactly.

### Requirement 2: Create a Frozen Reproducible Baseline

**User Story:** As an evaluator, I want an immutable and reproducible baseline, so that candidate improvements are compared against the same reference.

#### Acceptance Criteria

1. THE Measurement_Harness SHALL encode every Baseline_Manifest as Canonical_JSON.
2. THE Measurement_Harness SHALL encode every Baseline_Identity_Payload as Canonical_JSON.
3. THE Measurement_Harness SHALL compute every Baseline_ID as the Artifact_Hash of exact Baseline_Identity_Payload bytes.
4. WHEN a Baseline_Manifest is loaded, THE Measurement_Harness SHALL recompute the Baseline_ID from exact Baseline_Identity_Payload bytes.
5. IF a recorded `baseline_id` differs from the recomputed Baseline_ID, THEN THE Measurement_Harness SHALL reject the Baseline_Manifest with code `baseline_id_mismatch`.
6. THE Baseline_Manifest SHALL record every field listed in the Baseline_Manifest glossary definition.
7. THE Measurement_Harness SHALL generate Frozen_Baseline outputs with the handedness correction enabled.
8. THE Measurement_Harness SHALL generate Frozen_Baseline outputs with the existing Spread_Gate enabled.
9. WHEN a Frozen_Baseline is published, THE Measurement_Harness SHALL preserve exact Baseline_Manifest bytes under the published Baseline_ID.
10. WHEN a Frozen_Baseline is published, THE Measurement_Harness SHALL preserve exact referenced-artifact bytes under the published Baseline_ID.
11. IF a write would replace bytes published under a Baseline_ID, THEN THE Measurement_Harness SHALL reject the write with code `frozen_baseline_immutable`.
12. IF a write would mutate bytes published under a Baseline_ID, THEN THE Measurement_Harness SHALL reject the write with code `frozen_baseline_immutable`.
13. WHEN any Baseline_Manifest byte changes, THE Measurement_Harness SHALL assign the Baseline_ID recomputed from the changed Baseline_Identity_Payload.
14. WHEN any referenced-artifact byte changes, THE Measurement_Harness SHALL assign the Baseline_ID recomputed from the changed Baseline_Identity_Payload containing the changed Artifact_Hash.
15. WHEN a Frozen_Baseline artifact is read, THE Measurement_Harness SHALL verify exact artifact bytes against the recorded Artifact_Hash before use.
16. IF Frozen_Baseline artifact verification fails, THEN THE Measurement_Harness SHALL reject the artifact with code `artifact_hash_mismatch`.
17. WHEN every Comparability_Field matches the Frozen_Baseline in Canonical_JSON type, value, presence, and array order, THE Measurement_Harness SHALL classify the rerun as a Comparable_Rerun.
18. IF any Comparability_Field differs from the Frozen_Baseline in Canonical_JSON type, value, presence, or array order, THEN THE Measurement_Harness SHALL classify the rerun as non-comparable.
19. WHEN a rerun is non-comparable, THE Measurement_Harness SHALL report every differing Comparability_Field canonical path.
20. WHEN a rerun is non-comparable, THE Measurement_Harness SHALL report baseline presence and rerun presence for every differing Comparability_Field.
21. WHEN a rerun is non-comparable, THE Measurement_Harness SHALL report baseline value and rerun value for every differing Comparability_Field.
22. WHEN a Comparable_Rerun completes, THE Measurement_Harness SHALL compare every rerun output Artifact_Hash with the same ordered Frozen_Baseline output Artifact_Hash.
23. WHEN a Comparable_Rerun completes, THE Measurement_Harness SHALL reproduce every Frozen_Baseline scalar metric within absolute error `1e-9`.
24. IF any Comparable_Rerun output Artifact_Hash differs from the same ordered Frozen_Baseline output Artifact_Hash, THEN THE Measurement_Harness SHALL classify artifact reproduction as failed.
25. IF any Comparable_Rerun scalar metric differs from the Frozen_Baseline scalar metric by more than `1e-9`, THEN THE Measurement_Harness SHALL classify metric reproduction as failed.
26. WHILE the Phase_0_Gate is incomplete, THE Measurement_Harness SHALL label every multi-cue acceptance result `preliminary`.
27. WHILE the Phase_0_Gate is incomplete, THE Measurement_Harness SHALL prohibit every final multi-cue pass decision.
28. WHILE the Phase_0_Gate is incomplete, THE Measurement_Harness SHALL prohibit every final multi-cue acceptance decision.
29. IF `kee-cc` lacks a verified Frozen_Baseline, THEN THE Measurement_Harness SHALL keep the Phase_0_Gate failed.
30. IF `taoyuan-tc` lacks a verified Frozen_Baseline, THEN THE Measurement_Harness SHALL keep the Phase_0_Gate failed.
31. IF `kee-cc` lacks a sufficient Ground_Truth_Dataset, THEN THE Measurement_Harness SHALL keep the Phase_0_Gate failed.
32. IF `taoyuan-tc` lacks a sufficient Ground_Truth_Dataset, THEN THE Measurement_Harness SHALL keep the Phase_0_Gate failed.
33. IF `kee-cc` lacks a reproducible baseline metric report, THEN THE Measurement_Harness SHALL keep the Phase_0_Gate failed.
34. IF `taoyuan-tc` lacks a reproducible baseline metric report, THEN THE Measurement_Harness SHALL keep the Phase_0_Gate failed.
35. WHEN both Acceptance_Sites have a verified Frozen_Baseline, a sufficient Ground_Truth_Dataset, and a reproducible baseline metric report, THE Measurement_Harness SHALL mark the Phase_0_Gate `passed`.
### Requirement 3: Establish Independent Ground Truth

**User Story:** As an accuracy reviewer, I want independently produced reference positions, so that evaluation measures correctness rather than internal consistency.

#### Acceptance Criteria

1. THE Ground_Truth_Dataset SHALL record every Ground_Truth_Metadata field for every reference position.
2. THE Ground_Truth_Dataset SHALL express every reference position in metres in the calibrated satellite coordinate frame named by the recorded calibration identifier and Artifact_Hash.
3. THE Ground_Truth_Dataset SHALL use the frozen vehicle reference-point definition for every reference position.
4. WHEN annotation imagery is displayed, THE Ground_Truth_Dataset SHALL exclude every Ground_Truth_Contamination item from the annotation view.
5. IF an independence declaration is false or missing, THEN THE Measurement_Harness SHALL classify the reference position as an Independence_Violation.
6. IF source-artifact lineage includes a Haware baseline localization derivative, THEN THE Measurement_Harness SHALL classify the reference position as an Independence_Violation.
7. IF source-artifact lineage includes a Haware candidate localization derivative, THEN THE Measurement_Harness SHALL classify the reference position as an Independence_Violation.
8. IF Ground_Truth_Contamination is detected or declared, THEN THE Measurement_Harness SHALL classify the reference position as an Independence_Violation.
9. IF source-artifact lineage cannot be verified from recorded Artifact_Hashes, THEN THE Measurement_Harness SHALL classify the reference position as an Independence_Violation.
10. WHEN an Independence_Violation occurs, THE Measurement_Harness SHALL exclude the reference position from every acceptance partition with code `ground_truth_independence_violation`.
11. WHEN a reference position lacks any Ground_Truth_Metadata field, THE Measurement_Harness SHALL exclude the reference position from every acceptance partition with code `missing_ground_truth_metadata`.
12. THE Ground_Truth_Dataset SHALL freeze one absent-coordinate exclusion code before candidate evaluation.
13. THE Ground_Truth_Dataset SHALL freeze one non-finite-coordinate exclusion code before candidate evaluation.
14. THE Ground_Truth_Dataset SHALL freeze one duplicate-reference-identity exclusion code before candidate evaluation.
15. WHEN a reference position lacks an `x` or `y` ground-truth coordinate component, THE Measurement_Harness SHALL exclude the reference position from every acceptance partition with the frozen absent-coordinate exclusion code.
16. WHEN an `x` or `y` ground-truth coordinate component is non-finite, THE Measurement_Harness SHALL exclude the reference position from every acceptance partition with the frozen non-finite-coordinate exclusion code.
17. WHEN two or more reference positions have identical site, frame identifier, and detection identifier values, THE Measurement_Harness SHALL exclude every reference position in the duplicate-reference-identity group from every acceptance partition with the frozen duplicate-reference-identity exclusion code.
18. WHEN records in a duplicate-reference-identity group are permuted, THE Measurement_Harness SHALL preserve the excluded reference-position set and exclusion code exactly.
19. WHEN annotation uncertainty is non-finite, THE Measurement_Harness SHALL exclude the reference position from every acceptance partition with code `invalid_ground_truth_uncertainty`.
20. WHEN annotation uncertainty is negative, THE Measurement_Harness SHALL exclude the reference position from every acceptance partition with code `invalid_ground_truth_uncertainty`.
21. WHEN annotation uncertainty exceeds the frozen per-record uncertainty limit, THE Measurement_Harness SHALL exclude the reference position from every acceptance partition with code `ground_truth_uncertainty_exceeded`.
22. WHEN annotation uncertainty equals the frozen per-record uncertainty limit, THE Measurement_Harness SHALL retain the reference position subject to every other frozen inclusion rule.
23. WHEN a reference position is excluded, THE Measurement_Harness SHALL record the site, frame identifier, detection identifier, failed field, failed rule, and exclusion code.
24. THE Ground_Truth_Dataset SHALL freeze the per-record uncertainty limit before candidate evaluation.
25. THE Ground_Truth_Dataset SHALL freeze every inclusion rule before candidate evaluation.
26. THE Ground_Truth_Dataset SHALL freeze train, validation, and acceptance partitions before candidate evaluation.
27. THE Ground_Truth_Dataset SHALL assign every detection to at most one partition.
28. THE Ground_Truth_Dataset SHALL exclude every train record from the acceptance partition.
29. THE Ground_Truth_Dataset SHALL exclude every validation record from the acceptance partition.
30. THE Ground_Truth_Dataset SHALL assign a non-null track identifier to every Eligible_Detection in an acceptance partition.
31. THE Ground_Truth_Dataset SHALL contain at least 30 Eligible_Detections after quality exclusions at `kee-cc`.
32. THE Ground_Truth_Dataset SHALL contain at least 30 Eligible_Detections after quality exclusions at `taoyuan-tc`.
33. THE Ground_Truth_Dataset SHALL contain at least 3 distinct non-null independently tracked vehicle identifiers after quality exclusions at `kee-cc`.
34. THE Ground_Truth_Dataset SHALL contain at least 3 distinct non-null independently tracked vehicle identifiers after quality exclusions at `taoyuan-tc`.
35. IF an Acceptance_Site has fewer than 30 Eligible_Detections after quality exclusions, THEN THE Measurement_Harness SHALL reject acceptance evaluation for the Acceptance_Site.
36. IF an Acceptance_Site has fewer than 3 distinct non-null independently tracked vehicle identifiers after quality exclusions, THEN THE Measurement_Harness SHALL reject acceptance evaluation for the Acceptance_Site.
37. IF acceptance evaluation is rejected for either Acceptance_Site, THEN THE Measurement_Harness SHALL keep the Phase_0_Gate failed.
### Requirement 4: Enforce the Evidence Hierarchy and Acceptance Sites

**User Story:** As a reviewer, I want a formal evidence hierarchy, so that proxy improvements cannot be mistaken for localization accuracy.

#### Acceptance Criteria

1. THE Measurement_Harness SHALL use Ground_Truth_Dataset Planar_Position_Error as the only primary accuracy evidence.
2. THE Measurement_Harness SHALL classify ground-plane wheelbase consistency as secondary evidence.
3. THE Measurement_Harness SHALL classify ground-plane track-width consistency as secondary evidence.
4. WHEN two observations are Consecutive_Usable_Observations and planar displacement is strictly greater than the frozen nonzero-motion threshold, THE Measurement_Harness SHALL classify motion-course heading consistency as tertiary evidence.
5. THE Measurement_Harness SHALL classify fit residual as an internal-consistency diagnostic.
6. THE Measurement_Harness SHALL classify keypoint spread as an internal-consistency diagnostic.
7. IF primary accuracy evidence fails for an Acceptance_Site, THEN THE Measurement_Harness SHALL reject the candidate for the Acceptance_Site.
8. IF primary accuracy evidence fails for an Acceptance_Site, THEN THE Measurement_Harness SHALL prohibit Proxy_Metric evidence from changing the failed result.
9. THE Measurement_Harness SHALL compute every acceptance metric separately for `kee-cc`.
10. THE Measurement_Harness SHALL compute every acceptance metric separately for `taoyuan-tc`.
11. THE Measurement_Harness SHALL exclude Diagnostic_Site records from every acceptance numerator.
12. THE Measurement_Harness SHALL exclude Diagnostic_Site records from every acceptance denominator.
13. THE Measurement_Harness SHALL exclude Diagnostic_Site records from every acceptance confidence interval.
14. THE Measurement_Harness SHALL exclude Diagnostic_Site records from every acceptance pass-fail decision.
15. WHERE a report contains a Diagnostic_Site record, THE Diagnostics_Recorder SHALL label the record `diagnostic_only=true`.
16. IF a Diagnostic_Site record lacks `diagnostic_only=true`, THEN THE Diagnostics_Recorder SHALL reject the report as invalid.
17. THE Measurement_Harness SHALL exclude Diagnostic_Site data from every acceptance-threshold selection.
18. THE Measurement_Harness SHALL exclude every metric derived from Diagnostic_Site data from every acceptance-threshold tuning operation.
### Requirement 5: Measure Accuracy, Coverage, and Risk

**User Story:** As a product owner, I want accuracy evaluated together with coverage and risk, so that abstention cannot create a misleading accuracy gain.

#### Acceptance Criteria

1. THE Measurement_Harness SHALL construct one fixed Evaluation_Population from the frozen acceptance partition for each Acceptance_Site.
2. THE Measurement_Harness SHALL use the identical ordered Evaluation_Population as the baseline denominator and candidate denominator at one Acceptance_Site.
3. IF an Eligible_Detection joins zero reference positions, THEN THE Measurement_Harness SHALL fail site evaluation with code `missing_ground_truth_match`.
4. IF an Eligible_Detection joins more than one reference position, THEN THE Measurement_Harness SHALL fail site evaluation with code `ambiguous_ground_truth_match`.
5. IF site evaluation fails because of a ground-truth join, THEN THE Measurement_Harness SHALL retain the failed Eligible_Detection in the recorded fixed Evaluation_Population inventory.
6. IF the baseline produces a localization-result count other than one for the site, frame identifier, and detection identifier of any Evaluation_Population record, THEN THE Measurement_Harness SHALL reject site evaluation.
7. IF the candidate produces a localization-result count other than one for the site, frame identifier, and detection identifier of any Evaluation_Population record, THEN THE Measurement_Harness SHALL reject site evaluation.
8. IF site evaluation is rejected because of baseline or candidate localization-result cardinality, THEN THE Measurement_Harness SHALL preserve the complete ordered fixed Evaluation_Population inventory.
9. WHEN a Matched_Detection has a Usable_Localization, THE Measurement_Harness SHALL compute Planar_Position_Error from unrounded finite coordinates in the common calibrated frame.
10. THE Measurement_Harness SHALL form the baseline Error_Sample only from baseline Usable_Localizations in the fixed Evaluation_Population.
11. THE Measurement_Harness SHALL form the candidate Error_Sample only from candidate Usable_Localizations in the fixed Evaluation_Population.
12. THE Measurement_Harness SHALL keep baseline and candidate Error_Samples separate.
13. WHEN an Error_Sample is nonempty, THE Measurement_Harness SHALL report the Error_Sample count.
14. WHEN an Error_Sample is nonempty, THE Measurement_Harness SHALL report the Error_Sample median Planar_Position_Error in metres.
15. WHEN an Error_Sample is nonempty, THE Measurement_Harness SHALL report the Error_Sample Nearest_Rank_Percentile at `p=0.90` in metres.
16. WHEN an Error_Sample is nonempty, THE Measurement_Harness SHALL report the Error_Sample maximum Planar_Position_Error in metres.
17. IF a baseline Error_Sample is empty, THEN THE Measurement_Harness SHALL report baseline position-error statistics as null.
18. IF a candidate Error_Sample is empty, THEN THE Measurement_Harness SHALL report candidate position-error statistics as null.
19. IF a baseline Error_Sample is empty, THEN THE Measurement_Harness SHALL fail the accuracy gate for the Acceptance_Site.
20. IF a candidate Error_Sample is empty, THEN THE Measurement_Harness SHALL fail the accuracy gate for the Acceptance_Site.
21. THE Measurement_Harness SHALL compute baseline Usable_Coverage over the fixed Evaluation_Population denominator.
22. THE Measurement_Harness SHALL compute candidate Usable_Coverage over the fixed Evaluation_Population denominator.
23. THE Measurement_Harness SHALL include usable `fallback` records in overall Error_Samples.
24. THE Measurement_Harness SHALL include usable `fallback` records in Usable_Coverage.
25. THE Measurement_Harness SHALL include usable `fallback` records in Selective_Risk inputs.
26. THE Measurement_Harness SHALL report every status count divided by the fixed Evaluation_Population count.
27. THE Measurement_Harness SHALL report every Estimator_Mode count divided by the fixed Evaluation_Population count.
28. THE Measurement_Harness SHALL report count, median, 90th-percentile error, and maximum separately for `single_family`, `complementary_multi_cue`, and `fallback`.
29. IF a per-mode Error_Sample is empty, THEN THE Measurement_Harness SHALL report the per-mode position-error statistics as null.
30. THE Measurement_Harness SHALL report Per_Mode_Coverage_Contribution separately for `single_family`, `complementary_multi_cue`, and `fallback`.
31. THE Measurement_Harness SHALL verify that the three Per_Mode_Coverage_Contribution values sum to Usable_Coverage within absolute error `1e-12`.
32. THE Measurement_Harness SHALL retain every usable non-finite-confidence record in the fixed Evaluation_Population denominator.
33. THE Measurement_Harness SHALL include every usable non-finite-confidence record in Usable_Coverage.
34. THE Measurement_Harness SHALL exclude every non-finite-confidence record from Selective_Risk retention.
35. THE Measurement_Harness SHALL sort Selective_Risk inputs by descending finite confidence, ascending frame identifier, and ascending detection identifier.
36. WHEN requested coverage is `c`, THE Measurement_Harness SHALL set Selective_Risk retained count to `k=ceil(cN)`.
37. WHEN baseline and candidate each contain at least `k` finite-confidence usable Matched_Detections, THE Measurement_Harness SHALL classify requested coverage `c` as a Matched_Coverage_Point.
38. WHEN requested coverage `c` is a Matched_Coverage_Point, THE Measurement_Harness SHALL compute baseline Selective_Risk from exactly the first `k` sorted baseline errors.
39. WHEN requested coverage `c` is a Matched_Coverage_Point, THE Measurement_Harness SHALL compute candidate Selective_Risk from exactly the first `k` sorted candidate errors.
40. IF baseline lacks `k` finite-confidence usable Matched_Detections at requested coverage `c`, THEN THE Measurement_Harness SHALL report baseline Selective_Risk at `c` as null.
41. IF candidate lacks `k` finite-confidence usable Matched_Detections at requested coverage `c`, THEN THE Measurement_Harness SHALL report candidate Selective_Risk at `c` as null.
42. IF no finite-confidence usable Matched_Detections exist for a system, THEN THE Measurement_Harness SHALL report the system Selective_Risk curve as empty.
43. THE Measurement_Harness SHALL request Selective_Risk at `5` percentage-point increments beginning at `20%`.
44. THE Measurement_Harness SHALL stop requested Selective_Risk points above the lower maximum finite-confidence usable coverage of baseline and candidate.
45. IF either baseline or candidate lacks a Matched_Coverage_Point at `20%`, THEN THE Measurement_Harness SHALL fail the Selective_Risk gate for the Acceptance_Site.
46. WHEN baseline and candidate median-error point estimates are non-null, THE Measurement_Harness SHALL compute a Paired_Track_Confidence_Interval for candidate-minus-baseline median error.
47. WHEN baseline and candidate 90th-percentile-error point estimates are non-null, THE Measurement_Harness SHALL compute a Paired_Track_Confidence_Interval for candidate-minus-baseline 90th-percentile error.
48. WHEN baseline and candidate Usable_Coverage point estimates are non-null, THE Measurement_Harness SHALL compute a Paired_Track_Confidence_Interval for candidate-minus-baseline Usable_Coverage.
49. WHEN baseline and candidate point estimates for a per-mode position-error statistic are non-null, THE Measurement_Harness SHALL compute a Paired_Track_Confidence_Interval for the candidate-minus-baseline statistic.
50. WHEN baseline and candidate Per_Mode_Coverage_Contribution point estimates are non-null, THE Measurement_Harness SHALL compute a Paired_Track_Confidence_Interval for candidate-minus-baseline Per_Mode_Coverage_Contribution.
51. WHEN baseline and candidate Selective_Risk point estimates are non-null at a Matched_Coverage_Point, THE Measurement_Harness SHALL compute a Paired_Track_Confidence_Interval for the candidate-minus-baseline Selective_Risk value.
52. THE Measurement_Harness SHALL apply the Paired_Track_Confidence_Interval procedure from the Glossary without baseline-candidate resampling divergence.
53. THE Acceptance_Profile SHALL freeze replicate count, confidence level, random seed, percentile endpoints, and undefined-replicate handling.
54. THE Measurement_Harness SHALL report metric name, site, mode or coverage point, point estimate, interval endpoints, replicate count, confidence level, and seed for every paired interval.
55. IF either baseline or candidate point estimate is null for a required paired metric, THEN THE Measurement_Harness SHALL skip Paired_Track_Confidence_Interval computation for the metric.
56. IF either baseline or candidate point estimate is null for a required paired metric, THEN THE Measurement_Harness SHALL report the metric interval as null.
57. THE Acceptance_Profile SHALL require candidate median Planar_Position_Error to be at most `0.95` times the Frozen_Baseline median at each Acceptance_Site.
58. THE Acceptance_Profile SHALL require candidate 90th-percentile Planar_Position_Error to be no greater than the Frozen_Baseline 90th percentile at each Acceptance_Site.
59. THE Acceptance_Profile SHALL require candidate Usable_Coverage to be at least Frozen_Baseline Usable_Coverage minus `0.02` at each Acceptance_Site.
60. THE Acceptance_Profile SHALL require candidate Selective_Risk to be no greater than Frozen_Baseline Selective_Risk at every Matched_Coverage_Point.
61. IF any per-site accuracy gate fails, THEN THE Measurement_Harness SHALL reject the candidate.
62. IF any per-site coverage gate fails, THEN THE Measurement_Harness SHALL reject the candidate.
63. IF any per-site Selective_Risk gate fails, THEN THE Measurement_Harness SHALL reject the candidate.
64. IF a pooled result passes while `kee-cc` fails, THEN THE Measurement_Harness SHALL reject the candidate.
65. IF a pooled result passes while `taoyuan-tc` fails, THEN THE Measurement_Harness SHALL reject the candidate.
### Requirement 6: Select and Weight Reliable Multi-Cue Constraints

**User Story:** As a localization engineer, I want estimator support selected from view-specific cue reliability and geometric observability, so that each visible keypoint family contributes only constraints supported by available evidence.

#### Acceptance Criteria

1. THE Acceptance_Profile SHALL freeze the Observation_Validity_Profile before candidate evaluation.
2. THE Observation_Validity_Profile SHALL define validity for every coordinate, confidence, identifier, and label consumed by mode selection.
3. THE Observation_Validity_Profile SHALL freeze one Duplicate_Keypoint_Policy before candidate evaluation.
4. WHEN duplicate keypoint identifiers are present, THE Mode_Selector SHALL apply the frozen Duplicate_Keypoint_Policy before evaluating Cue_Eligibility_Checks.
5. IF duplicate keypoint values conflict under a rejecting Duplicate_Keypoint_Policy, THEN THE Mode_Selector SHALL return the duplicate-conflict reason code frozen by the Observation_Validity_Profile.
6. WHEN equivalent duplicate keypoint records are permuted, THE Mode_Selector SHALL return the same observation-validity result.
7. THE Geometry_Profile SHALL define `wheel_ground_contact`, `windshield_glass_corner`, `roof_corner`, `mirror`, and `other_documented` Cue_Families before candidate evaluation.
8. THE Geometry_Profile SHALL assign every keypoint eligible for estimation to exactly one documented Cue_Family.
9. THE Geometry_Profile SHALL assign every orientation-eligible keypoint to exactly one Height_Family.
10. THE Geometry_Profile SHALL freeze candidate `orientation`, `position`, and `bearing` roles for every Cue_Family before candidate evaluation.
11. THE Geometry_Profile SHALL freeze minimum visibility rules for every candidate cue constraint before candidate evaluation.
12. THE Geometry_Profile SHALL freeze minimum projected baseline or leverage boundaries for every candidate cue constraint before candidate evaluation.
13. THE Geometry_Profile SHALL freeze centered-template and centered-observation rank requirements for every candidate cue constraint that requires rank evaluation.
14. THE Geometry_Profile SHALL freeze minimum per-keypoint confidence for every candidate cue constraint before candidate evaluation.
15. THE Geometry_Profile SHALL freeze label and semantic-consistency rules for every Cue_Family before candidate evaluation.
16. THE Geometry_Profile SHALL freeze Height_Family uncertainty rules for every nonzero-height candidate cue constraint before candidate evaluation.
17. THE Geometry_Profile SHALL freeze versioned Site_View_Evidence gates before candidate evaluation.
18. THE Geometry_Profile SHALL freeze fallback-evidence rules before candidate evaluation.
19. THE Geometry_Profile SHALL freeze non-overlapping Estimator_Mode predicates before candidate evaluation.
20. THE Geometry_Profile SHALL freeze deterministic mode priority before candidate evaluation.
21. THE Geometry_Profile SHALL freeze a deterministic weighting function over Cue_Reliability_Factors before candidate evaluation.
22. WHEN a minimum-bound cue value equals the associated frozen minimum boundary, THE Mode_Selector SHALL pass the associated Cue_Eligibility_Check.
23. WHEN a minimum-bound cue value is below the associated frozen minimum boundary, THE Mode_Selector SHALL fail the associated Cue_Eligibility_Check.
24. WHEN a cue constraint is evaluated, THE Mode_Selector SHALL evaluate visibility for the cue constraint.
25. WHEN a cue constraint is evaluated, THE Mode_Selector SHALL evaluate projected baseline or leverage for the cue constraint's proposed role.
26. WHEN a cue constraint is evaluated, THE Mode_Selector SHALL evaluate Projection_Conditioning_Metric values for every observation required by the cue constraint.
27. WHEN a cue constraint is evaluated, THE Mode_Selector SHALL evaluate keypoint confidence for the cue constraint.
28. WHEN a cue constraint is evaluated, THE Mode_Selector SHALL evaluate label and semantic consistency for the cue constraint.
29. WHEN a nonzero-height cue constraint is evaluated, THE Mode_Selector SHALL evaluate Height_Family uncertainty for the cue constraint.
30. WHEN a cue constraint is evaluated, THE Mode_Selector SHALL evaluate applicable Site_View_Evidence for the detection site and documented view region.
31. WHEN every Cue_Eligibility_Check for a candidate cue constraint passes, THE Mode_Selector SHALL classify the cue constraint as reliability-eligible.
32. WHEN any Cue_Eligibility_Check for a candidate cue constraint fails, THE Mode_Selector SHALL classify the cue constraint as reliability-ineligible.
33. WHEN a cue constraint is reliability-eligible, THE Mode_Selector SHALL compute the cue constraint weight from the frozen weighting function and recorded Cue_Reliability_Factors.
34. WHEN a cue constraint has stronger projected baseline or leverage under otherwise equal Cue_Reliability_Factors, THE Mode_Selector SHALL assign a weight no lower than the weaker cue constraint's weight.
35. WHEN a cue constraint has greater Height_Family uncertainty under otherwise equal Cue_Reliability_Factors, THE Mode_Selector SHALL assign a weight no higher than the lower-uncertainty cue constraint's weight.
36. WHEN a valid wheel or documented ground-contact cue has `h=0`, THE Mode_Selector SHALL classify the cue as a Zero_Height_Anchor candidate.
37. WHEN a Zero_Height_Anchor is reliability-eligible for position, THE Reliability_Aware_Multi_Cue_Estimator SHALL prefer the Zero_Height_Anchor over a nonzero-height position cue with otherwise equal reliability evidence.
38. WHEN the Reliability_Aware_Multi_Cue_Estimator projects a Zero_Height_Anchor, THE Reliability_Aware_Multi_Cue_Estimator SHALL use `eta=0` for the vertical-parallax correction term.
39. THE Geometry_Profile SHALL classify mirror cues with a documented estimated-height prior and Height_Family uncertainty.
40. THE Geometry_Profile SHALL reserve Zero_Height_Anchor classification for documented `h=0` ground-contact cues.
41. WHEN a windshield or glass-corner cue has reliable camera-relative bearing evidence, THE Mode_Selector SHALL permit the cue to contribute a Position_Bearing_Constraint.
42. WHEN a windshield or glass-corner pair has projected heading leverage below the frozen heading-leverage boundary, THE Mode_Selector SHALL classify the pair as orientation-ineligible.
43. WHEN a short or predominantly lateral cue pair has projected heading leverage below the frozen heading-leverage boundary, THE Mode_Selector SHALL preserve any separately eligible Position_Bearing_Constraint from the pair.
44. WHERE the site is `kee-cc`, WHEN Apollo-24 keypoint `front_up_right` index `0` is considered, THE Mode_Selector SHALL apply the frozen kee-cc semantic-misplacement Site_View_Evidence gate before assigning any constraint role.
45. WHERE the site is `kee-cc`, IF Apollo-24 keypoint `front_up_right` index `0` fails the semantic-misplacement Site_View_Evidence gate, THEN THE Mode_Selector SHALL exclude index `0` from estimator support with a stable reason code.
46. WHERE a site and view lack evidence of the kee-cc index `0` anomaly, THE Mode_Selector SHALL evaluate index `0` from the Site_View_Evidence applicable to that site and view.
47. WHEN a Cue_Family contributes an Orientation_Constraint, THE Reliability_Aware_Multi_Cue_Estimator SHALL estimate the Orientation_Constraint only from keypoints in one Height_Family.
48. WHEN orientation evidence exists in multiple Height_Families, THE Reliability_Aware_Multi_Cue_Estimator SHALL estimate one separate Orientation_Constraint per Height_Family before combining orientation evidence.
49. WHEN separately estimated Orientation_Constraints from multiple Height_Families are combined, THE Reliability_Aware_Multi_Cue_Estimator SHALL weight the combination by each Height_Family's Effective_Eta uncertainty and recorded reliability evidence.
50. IF a Height_Family lacks the frozen uncertainty information required for cross-family orientation combination, THEN THE Reliability_Aware_Multi_Cue_Estimator SHALL retain that family's Orientation_Constraint as diagnostic-only for the combination.
51. WHEN one reliability-eligible Cue_Family constrains orientation and another reliability-eligible Cue_Family constrains position or bearing, THE Mode_Selector SHALL permit a `complementary_multi_cue` Primary_Support_Path.
52. WHEN exactly one reliability-eligible Cue_Family supplies every required pose constraint, THE Mode_Selector SHALL select `single_family`.
53. WHEN two or more reliability-eligible Cue_Families supply complementary required pose constraints, THE Mode_Selector SHALL select `complementary_multi_cue`.
54. WHEN zero wheel keypoints are visible and a non-wheel Primary_Support_Path is reliability-eligible, THE Mode_Selector SHALL select the applicable `single_family` or `complementary_multi_cue` mode.
55. WHEN zero wheel keypoints are visible and no Primary_Support_Path is reliability-eligible, THE Mode_Selector SHALL evaluate the frozen fallback-evidence predicate.
56. WHEN every Primary_Support_Path is ineligible and fallback evidence passes every required evidence and conditioning check, THE Mode_Selector SHALL select `fallback`.
57. WHEN every Primary_Support_Path is ineligible and fallback evidence fails any required evidence check, THE Mode_Selector SHALL select `none`.
58. IF any required conditioning value for a selected support path is non-finite, THEN THE Mode_Selector SHALL return Typed_Validation_Failure code `invalid_conditioning_metric`.
59. IF any required conditioning value for a selected support path is non-finite, THEN THE Mode_Selector SHALL prohibit Fallback_Path substitution for the detection.
60. IF Estimator_Mode predicates overlap for any Observation_Validity_Profile-valid input, THEN THE Mode_Selector SHALL fail Geometry_Profile validation before detection evaluation.
61. THE Mode_Selector SHALL derive every mode decision from keypoint identifiers, keypoint values, Cue_Reliability_Factors, and frozen profile evidence.
62. THE Mode_Selector SHALL exclude input iteration order from every mode decision.
63. WHEN equivalent keypoint records are permuted, THE Mode_Selector SHALL preserve Estimator_Mode exactly.
64. WHEN equivalent keypoint records are permuted, THE Mode_Selector SHALL preserve the selection-reason code exactly.
65. THE Mode_Selector SHALL record every Cue_Eligibility_Check value, threshold, and outcome for every candidate cue constraint.
66. THE Mode_Selector SHALL record every Cue_Reliability_Factor and resulting weight used for every candidate cue constraint.
67. THE Mode_Selector SHALL record each selected cue's Cue_Family, Height_Family, and constraint role.
68. THE Mode_Selector SHALL record one stable machine-readable selection-reason code for every detection.
69. THE Mode_Selector SHALL use `n_wheel_kp` only as a diagnostic output.
70. WHEN two detections have equal `n_wheel_kp` and different cue reliability evidence, THE Mode_Selector SHALL evaluate each detection from the detection's cue reliability evidence.
### Requirement 7: Ensure Correct Weighted Estimation

**User Story:** As an algorithm reviewer, I want mathematically correct weighting, so that reliability weighting does not bias the estimated center through inconsistent centering.

#### Acceptance Criteria

1. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL require `len(Q)=len(P)=len(w)`.
2. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL require at least two positive-weight correspondences.
3. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL require every `Q_i` and `P_i` to contain exactly two components.
4. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL require every point component to be finite.
5. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL require every weight to be finite and nonnegative.
6. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL require positive total weight `W`.
7. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL exclude every zero-weight point from `q_bar`.
8. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL exclude every zero-weight point from `p_bar`.
9. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL exclude every zero-weight point from covariance `H`.
10. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL exclude every zero-weight point from the weighted objective.
11. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL exclude every zero-weight point from geometry-rank evaluation.
12. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL compute `q_bar = sum_i(w_i Q_i)/W` over positive-weight points.
13. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL compute `p_bar = sum_i(w_i P_i)/W` over positive-weight points.
14. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL compute `H = sum_i(w_i (Q_i-q_bar)(P_i-p_bar)^T)` over positive-weight points.
15. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL compute a rotation satisfying `R^T R = I`.
16. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL compute a rotation satisfying `det(R)=+1`.
17. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL minimize `sum_i(w_i ||P_i-(R Q_i+t)||^2)` at fixed scale.
18. WHERE Weighted_Procrustes_Estimator is selected, THE Weighted_Procrustes_Estimator SHALL compute `t = p_bar - R q_bar`.
19. WHEN every weight is multiplied by one finite positive scalar and every scaled weight and scaled total weight `W` remain finite, THE Weighted_Procrustes_Estimator SHALL preserve every fitted-position component within absolute error `1e-9` pixels.
20. WHEN every weight is multiplied by one finite positive scalar and every scaled weight and scaled total weight `W` remain finite, THE Weighted_Procrustes_Estimator SHALL preserve fitted heading within Angular_Difference `1e-9` degrees.
21. WHEN any zero-weight correspondence is added, THE Weighted_Procrustes_Estimator SHALL preserve every fitted-position component within absolute error `1e-9` pixels.
22. WHEN any zero-weight correspondence is added, THE Weighted_Procrustes_Estimator SHALL preserve fitted heading within Angular_Difference `1e-9` degrees.
23. IF `len(Q)`, `len(P)`, and `len(w)` are unequal, THEN THE Weighted_Procrustes_Estimator SHALL return Typed_Validation_Failure code `invalid_shape`.
24. IF fewer than two positive-weight correspondences remain, THEN THE Weighted_Procrustes_Estimator SHALL return Typed_Validation_Failure code `invalid_shape`.
25. IF any point coordinate is non-finite, THEN THE Weighted_Procrustes_Estimator SHALL return Typed_Validation_Failure code `non_finite_coordinate`.
26. IF any weight is negative or non-finite, THEN THE Weighted_Procrustes_Estimator SHALL return Typed_Validation_Failure code `invalid_weight`.
27. IF total weight is zero, THEN THE Weighted_Procrustes_Estimator SHALL return Typed_Validation_Failure code `zero_total_weight`.
28. IF total weight `W` is non-finite, THEN THE Weighted_Procrustes_Estimator SHALL return Typed_Validation_Failure code `numeric_failure`.
29. IF positive-weight geometry fails the selected mode rank requirement, THEN THE Weighted_Procrustes_Estimator SHALL return Typed_Validation_Failure code `degenerate_geometry`.
30. IF positive-weight correspondences produce an Ambiguous_Fit, THEN THE Weighted_Procrustes_Estimator SHALL return Typed_Validation_Failure code `degenerate_geometry`.
31. IF any fitted rotation component is non-finite, THEN THE Weighted_Procrustes_Estimator SHALL return Typed_Validation_Failure code `numeric_failure`.
32. IF any fitted translation component is non-finite, THEN THE Weighted_Procrustes_Estimator SHALL return Typed_Validation_Failure code `numeric_failure`.
33. IF fitted residual or heading is non-finite, THEN THE Weighted_Procrustes_Estimator SHALL return Typed_Validation_Failure code `numeric_failure`.
34. WHEN any Typed_Validation_Failure occurs, THE Weighted_Procrustes_Estimator SHALL omit an Authoritative_Position.
### Requirement 8: Define Primary Modes, Fallback, Abstention, and Coordinate Semantics

**User Story:** As a downstream consumer, I want explicit primary-mode, fallback, and abstention semantics, so that reliable and reduced-confidence estimates remain distinguishable from unsafe estimates.

#### Acceptance Criteria

1. THE Reliability_Aware_Multi_Cue_Estimator SHALL evaluate status-producing stages in Gate_Order.
2. WHEN multiple failure conditions are present, THE Reliability_Aware_Multi_Cue_Estimator SHALL assign the status mapped to the earliest failed Gate_Order stage.
3. WHEN a Gate_Order stage fails, THE Reliability_Aware_Multi_Cue_Estimator SHALL mark every later Gate_Order stage `not_evaluated`.
4. IF fewer than two observation-valid pose observations remain, THEN THE Reliability_Aware_Multi_Cue_Estimator SHALL emit status `failed_insufficient_kp`.
5. IF fewer than two observation-valid pose observations remain, THEN THE Reliability_Aware_Multi_Cue_Estimator SHALL emit Estimator_Mode `none`.
6. IF observation count is sufficient and no support path passes the cue-eligibility stage, THEN THE Reliability_Aware_Multi_Cue_Estimator SHALL emit status `abstained`.
7. IF observation count is sufficient and no support path passes the cue-eligibility stage, THEN THE Reliability_Aware_Multi_Cue_Estimator SHALL emit Estimator_Mode `none`.
8. WHEN a selected Primary_Support_Path has a finite conditioning value equal to or above the Near_Horizon_Threshold, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit status `near_horizon`.
9. WHEN a selected Primary_Support_Path has a finite conditioning value equal to or above the Near_Horizon_Threshold, THE Reliability_Aware_Multi_Cue_Estimator SHALL prohibit Fallback_Path evaluation.
10. WHEN a selected Fallback_Path has a finite conditioning value equal to or above the Near_Horizon_Threshold, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit status `near_horizon`.
11. IF a selected support path has a non-finite conditioning value, THEN THE Reliability_Aware_Multi_Cue_Estimator SHALL emit status `abstained` with reason code `invalid_conditioning_metric`.
12. WHEN a selected support path fails fit validation, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit status `abstained`.
13. WHEN a selected support path fails numeric validation, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit status `abstained`.
14. WHEN finite projected spread is strictly below the Spread_Gate boundary, THE Reliability_Aware_Multi_Cue_Estimator SHALL continue to usable mode completion.
15. WHEN finite projected spread equals or exceeds the Spread_Gate boundary, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit status `extrapolated`.
16. WHEN a fitted pose fails the Spread_Gate, THE Reliability_Aware_Multi_Cue_Estimator SHALL prohibit Fallback_Path substitution.
17. WHEN the Fallback_Path returns a valid pose and passes every later usability gate, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit status `fallback`.
18. WHEN the Fallback_Path returns a valid pose and passes every later usability gate, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit Estimator_Mode `fallback`.
19. WHEN a `single_family` Primary_Support_Path returns a valid pose and passes every later usability gate, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit status `ok`.
20. WHEN a `single_family` Primary_Support_Path returns a valid pose and passes every later usability gate, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit Estimator_Mode `single_family`.
21. WHEN a `complementary_multi_cue` Primary_Support_Path returns a valid pose and passes every later usability gate, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit status `ok`.
22. WHEN a `complementary_multi_cue` Primary_Support_Path returns a valid pose and passes every later usability gate, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit Estimator_Mode `complementary_multi_cue`.
23. WHEN status is `ok` or `fallback`, THE Reliability_Aware_Multi_Cue_Estimator SHALL set `usable=true`.
24. WHEN status is `ok` or `fallback`, THE Reliability_Aware_Multi_Cue_Estimator SHALL populate a finite Authoritative_Position.
25. WHEN status is an Unusable_Localization status, THE Reliability_Aware_Multi_Cue_Estimator SHALL set `usable=false`.
26. WHEN status is an Unusable_Localization status, THE Reliability_Aware_Multi_Cue_Estimator SHALL set every Authoritative_Position field to null.
27. WHEN status is an Unusable_Localization status, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit Estimator_Mode `none`.
28. WHERE an unusable computed coordinate is retained, THE Reliability_Aware_Multi_Cue_Estimator SHALL store the coordinate only as a Diagnostic_Position.
29. WHERE a Diagnostic_Position is retained, THE Reliability_Aware_Multi_Cue_Estimator SHALL label the coordinate `diagnostic_only=true`.
30. WHEN the Reliability_Aware_Multi_Cue_Estimator emits a status, THE Reliability_Aware_Multi_Cue_Estimator SHALL record the earliest decisive Gate_Order stage.
31. WHEN the Reliability_Aware_Multi_Cue_Estimator emits a status, THE Reliability_Aware_Multi_Cue_Estimator SHALL record one stable machine-readable reason code.
32. WHEN an Unusable_Localization is emitted, THE Reliability_Aware_Multi_Cue_Estimator SHALL prevent every later stage from promoting a Diagnostic_Position to an Authoritative_Position.
### Requirement 9: Gate Near-Horizon Ill-Conditioning

**User Story:** As a localization consumer, I want unstable near-horizon projections rejected before fitting, so that small pixel errors do not become large ground-plane errors.

#### Acceptance Criteria

1. THE Localization_Improvement_System SHALL compute one Projection_Conditioning_Metric for every observation required by a candidate mode.
2. THE Projection_Conditioning_Metric SHALL depend only on calibrated projection geometry and the observation coordinate.
3. THE Acceptance_Profile SHALL freeze the Projection_Conditioning_Metric equation before candidate evaluation.
4. THE Acceptance_Profile SHALL freeze one Near_Horizon_Threshold per calibrated projection identifier before candidate evaluation.
5. WHEN a required Projection_Conditioning_Metric is finite and strictly below the Near_Horizon_Threshold, THE Mode_Selector SHALL pass the observation conditioning check.
6. WHEN a required Projection_Conditioning_Metric equals the exact representable Near_Horizon_Threshold, THE Mode_Selector SHALL reject the candidate mode before pose fitting.
7. WHEN a required Projection_Conditioning_Metric exceeds the Near_Horizon_Threshold, THE Mode_Selector SHALL reject the candidate mode before pose fitting.
8. IF a required Projection_Conditioning_Metric is non-finite, THEN THE Mode_Selector SHALL return Typed_Validation_Failure code `invalid_conditioning_metric`.
9. IF a required Projection_Conditioning_Metric is non-finite, THEN THE Mode_Selector SHALL prohibit Fallback_Path substitution for the detection.
10. WHEN every reliability-eligible mode is rejected only by projection conditioning, THE Reliability_Aware_Multi_Cue_Estimator SHALL emit status `near_horizon`.
11. THE Localization_Improvement_System SHALL evaluate projection conditioning before pose fitting.
12. THE Localization_Improvement_System SHALL evaluate the Spread_Gate after projection and pose fitting.
13. WHEN pose fitting reaches the Spread_Gate, THE Localization_Improvement_System SHALL record the conditioning outcome separately from the Spread_Gate outcome.
14. WHEN projection conditioning rejects a support path before fitting, THE Localization_Improvement_System SHALL record the Spread_Gate outcome as `not_evaluated`.
15. WHEN the Projection_Conditioning_Metric is the greatest representable finite value below the Near_Horizon_Threshold, THE Mode_Selector SHALL pass conditioning.
16. WHEN the Projection_Conditioning_Metric is the least representable finite value above the Near_Horizon_Threshold, THE Mode_Selector SHALL reject conditioning.
17. THE Diagnostics_Recorder SHALL record every computed conditioning value.
18. THE Diagnostics_Recorder SHALL record every conditioning value's Near_Horizon_Threshold.
19. THE Diagnostics_Recorder SHALL record every conditioning value's calibrated projection identifier.
20. THE Diagnostics_Recorder SHALL record the conditioning outcome for every candidate mode.
### Requirement 10: Propagate Status Through Enrichment and Scene Building

**User Story:** As a scene author, I want localization status honored by every downstream stage, so that extrapolated or abstained positions cannot affect reconstructed collisions.

#### Acceptance Criteria

1. WHEN an input localization has status `ok` or `fallback`, THE Enrichment_Pipeline SHALL derive `position_m` only from the Authoritative_Position.
2. WHEN an input localization has an Unusable_Localization status, THE Enrichment_Pipeline SHALL set `position_m` to null.
3. WHEN an input localization has an Unusable_Localization status, THE Enrichment_Pipeline SHALL set `velocity_mps` to null.
4. WHEN two observations are Consecutive_Usable_Observations, THE Enrichment_Pipeline SHALL compute Velocity_Mps from the Glossary equation.
5. WHEN a Track_Interruption occurs, THE Enrichment_Pipeline SHALL terminate the current track segment before the interruption.
6. WHEN a Track_Interruption occurs, THE Enrichment_Pipeline SHALL start a new track segment after the interruption.
7. WHEN a Track_Interruption occurs, THE Enrichment_Pipeline SHALL omit velocity across the interruption.
8. WHEN a usable observation is the first usable observation after a Track_Interruption, THE Enrichment_Pipeline SHALL set `velocity_mps` to null.
9. WHEN an unusable observation lies between two usable observations, THE Enrichment_Pipeline SHALL omit velocity between the two usable observations.
10. WHEN a frame gap exceeds the frozen maximum frame gap, THE Enrichment_Pipeline SHALL omit velocity across the frame gap.
11. WHEN timestamps are non-increasing, THE Enrichment_Pipeline SHALL omit velocity for the timestamp pair.
12. WHEN track identifiers differ, THE Enrichment_Pipeline SHALL omit velocity for the track-identifier pair.
13. WHEN either track identifier is null, THE Enrichment_Pipeline SHALL omit velocity for the track-identifier pair.
14. THE Enrichment_Pipeline SHALL preserve localization status in enriched output.
15. THE Enrichment_Pipeline SHALL preserve Estimator_Mode in enriched output.
16. THE Enrichment_Pipeline SHALL preserve usability in enriched output.
17. THE Enrichment_Pipeline SHALL preserve confidence in enriched output.
18. THE Enrichment_Pipeline SHALL preserve the diagnostic-reason code in enriched output.
19. WHEN an observation has an Unusable_Localization status, THE Scene_Builder SHALL exclude the observation from track positions.
20. WHEN an observation has an Unusable_Localization status, THE Scene_Builder SHALL exclude the observation from collider eligibility.
21. WHEN an observation has only a Diagnostic_Position, THE Scene_Builder SHALL exclude the Diagnostic_Position from every spatial calculation.
22. THE Scene_Builder SHALL report accepted observation counts by status and Estimator_Mode.
23. THE Scene_Builder SHALL report excluded observation counts by status and Estimator_Mode.
24. IF a requested collider has zero usable observations, THEN THE Scene_Builder SHALL return Typed_Validation_Failure code `no_usable_collider_observations`.
25. IF a requested collider has zero usable observations, THEN THE Scene_Builder SHALL include the requested track identifier in the Typed_Validation_Failure.
26. IF a requested collider has zero usable observations, THEN THE Scene_Builder SHALL include status counts in the Typed_Validation_Failure.
27. WHEN `status` is absent from a supported legacy record and a legacy-status policy is selected, THE Compatibility_Layer SHALL apply the selected legacy-status policy.
28. WHEN a legacy-status policy is applied, THE Compatibility_Layer SHALL record `legacy_status_policy` in output metadata.
29. IF `status` is absent and no legacy-status policy is selected, THEN THE Compatibility_Layer SHALL return Typed_Validation_Failure code `legacy_status_policy_required`.
### Requirement 11: Apply Temporal Fusion Only Conditionally

**User Story:** As an evaluator, I want temporal fusion introduced only when single-frame improvements are insufficient, so that smoothing cannot conceal unresolved estimator errors.

#### Acceptance Criteria

1. THE Temporal_Fusion_Module SHALL remain disabled by default.
2. WHILE any Single_Frame_Prerequisite_Gates criterion fails, THE Measurement_Harness SHALL prohibit temporal-fusion candidate evaluation.
3. WHILE any Single_Frame_Prerequisite_Gates criterion remains unevaluated, THE Measurement_Harness SHALL prohibit temporal-fusion candidate evaluation.
4. WHEN every Single_Frame_Prerequisite_Gates criterion passes and at least one Requirement 5 candidate-improvement target remains unmet, THE Measurement_Harness SHALL permit temporal-fusion candidate evaluation.
5. WHEN every Requirement 5 candidate-improvement target passes without temporal fusion, THE Measurement_Harness SHALL classify temporal fusion as unnecessary for `haware-localization-accuracy`.
6. WHEN temporal-fusion candidate evaluation is permitted, THE Measurement_Harness SHALL assign a candidate identifier distinct from every single-frame candidate identifier.
7. WHEN temporal-fusion candidate evaluation is permitted, THE Measurement_Harness SHALL record the source single-frame candidate identifier in Fusion_Provenance.
8. WHEN temporal fusion is enabled, THE Temporal_Fusion_Module SHALL combine observations only with equal non-null track identifiers.
9. WHEN temporal fusion is enabled, THE Temporal_Fusion_Module SHALL combine observations only within one uninterrupted track segment.
10. WHEN a frame gap exceeds the frozen maximum frame gap, THE Temporal_Fusion_Module SHALL start a new fusion segment.
11. WHEN temporal fusion encounters an Unusable_Localization, THE Temporal_Fusion_Module SHALL preserve the source status for the frame.
12. WHEN temporal fusion encounters an Unusable_Localization, THE Temporal_Fusion_Module SHALL preserve `usable=false` for the frame.
13. WHEN temporal fusion encounters an Unusable_Localization, THE Temporal_Fusion_Module SHALL preserve a null Authoritative_Position for the frame.
14. WHEN temporal fusion evaluates a Usable_Localization, THE Temporal_Fusion_Module SHALL preserve the complete source localization record unchanged.
15. WHEN temporal fusion evaluates a Usable_Localization, THE Temporal_Fusion_Module SHALL retain the unfused Authoritative_Position.
16. WHEN temporal fusion changes a usable position, THE Temporal_Fusion_Module SHALL retain the fused position separately from the unfused Authoritative_Position.
17. WHEN temporal fusion changes a usable position, THE Temporal_Fusion_Module SHALL record every Fusion_Provenance field.
18. WHEN temporal fusion leaves a usable position unchanged, THE Temporal_Fusion_Module SHALL record a fusion-status reason code.
19. IF any Fusion_Provenance field is missing, THEN THE Measurement_Harness SHALL reject the temporal-fusion candidate.
20. THE Measurement_Harness SHALL apply every Requirement 5 accuracy gate to a temporal-fusion candidate.
21. THE Measurement_Harness SHALL apply every Requirement 5 coverage gate to a temporal-fusion candidate.
22. THE Measurement_Harness SHALL apply every Requirement 5 Selective_Risk gate to a temporal-fusion candidate.
23. IF temporal fusion reduces Usable_Coverage relative to the unfused single-frame source candidate separately identified in Fusion_Provenance on the identical fixed Evaluation_Population at `kee-cc`, THEN THE Measurement_Harness SHALL reject the temporal-fusion candidate.
24. IF temporal fusion reduces Usable_Coverage relative to the unfused single-frame source candidate separately identified in Fusion_Provenance on the identical fixed Evaluation_Population at `taoyuan-tc`, THEN THE Measurement_Harness SHALL reject the temporal-fusion candidate.
25. IF temporal fusion increases 90th-percentile Planar_Position_Error relative to the unfused single-frame source candidate separately identified in Fusion_Provenance on the identical fixed Evaluation_Population at `kee-cc`, THEN THE Measurement_Harness SHALL reject the temporal-fusion candidate.
26. IF temporal fusion increases 90th-percentile Planar_Position_Error relative to the unfused single-frame source candidate separately identified in Fusion_Provenance on the identical fixed Evaluation_Population at `taoyuan-tc`, THEN THE Measurement_Harness SHALL reject the temporal-fusion candidate.
### Requirement 12: Provide Replayable Observability and Diagnostics

**User Story:** As an operator, I want complete localization provenance, so that failures and estimator-path distributions can be diagnosed without rerunning inference.

#### Acceptance Criteria

1. THE Diagnostics_Recorder SHALL record one ordered per-detection record for every localization attempt.
2. THE Diagnostics_Recorder SHALL include rejected localization attempts in ordered per-detection records.
3. THE Diagnostics_Recorder SHALL record status, usability, Estimator_Mode, selection-reason code, failure-reason code, and earliest decisive Gate_Order stage for every detection.
4. THE Diagnostics_Recorder SHALL record localization confidence for every detection.
5. THE Diagnostics_Recorder SHALL record every input keypoint identifier, label, coordinate, confidence, weight, and original order required for deterministic replay.
6. THE Diagnostics_Recorder SHALL record total observation-valid keypoint count for every detection.
7. THE Diagnostics_Recorder SHALL record `n_wheel_kp` for every detection.
8. THE Diagnostics_Recorder SHALL record visible Cue_Family membership and candidate constraint roles for every evaluated cue constraint.
9. THE Diagnostics_Recorder SHALL record every Cue_Eligibility_Check value, threshold, and outcome for every evaluated cue constraint.
10. THE Diagnostics_Recorder SHALL record every Cue_Reliability_Factor, cue weight, fallback-evidence value, fallback threshold, and fallback outcome used for every detection.
11. THE Diagnostics_Recorder SHALL record every Projection_Conditioning_Metric value, Near_Horizon_Threshold, calibrated projection identifier, and outcome for every candidate support path.
12. WHEN a detection reaches the Spread_Gate, THE Diagnostics_Recorder SHALL record projected spread, Spread_Gate boundary, and Spread_Gate outcome.
13. WHEN an earlier Gate_Order stage fails, THE Diagnostics_Recorder SHALL record every skipped later gate as `not_evaluated`.
14. THE Diagnostics_Recorder SHALL record every coordinate with coordinate role and `diagnostic_only` value.
15. THE Diagnostics_Recorder SHALL record Baseline_ID, Acceptance_Profile identifier, Acceptance_Profile Artifact_Hash, Geometry_Profile version, estimator version, source revision, effective-configuration Artifact_Hash, template Artifact_Hash, and calibration Artifact_Hash for every evaluated detection.
16. THE Diagnostics_Recorder SHALL record site, frame identifier, detection identifier, track identifier, source timestamp, schema version, evaluation-run identifier, and ordered-record index for every detection.
17. THE Diagnostics_Recorder SHALL record the Artifact_Hash of every source detection input.
18. THE Diagnostics_Recorder SHALL use one immutable versioned Diagnostics_Report_Schema frozen before candidate evaluation.
19. THE Diagnostics_Recorder SHALL aggregate counts and rates by site.
20. THE Diagnostics_Recorder SHALL aggregate counts and rates by status.
21. THE Diagnostics_Recorder SHALL aggregate counts and rates by Estimator_Mode.
22. THE Diagnostics_Recorder SHALL aggregate counts and rates by frozen conditioning band.
23. THE Diagnostics_Recorder SHALL aggregate counts and rates by Cue_Family, Height_Family, constraint role, and frozen cue-reliability class.
24. THE Diagnostics_Report_Schema SHALL define the exact ordered-record denominator predicate for every aggregate rate field.
25. WHEN an aggregate rate denominator is nonzero, THE Diagnostics_Recorder SHALL compute the aggregate rate as the matching ordered-record count divided by the ordered-record count selected by the frozen denominator predicate.
26. IF an aggregate rate denominator is zero, THEN THE Diagnostics_Recorder SHALL report the rate as null or omit the rate field exactly as specified by the frozen Diagnostics_Report_Schema.
27. IF a required diagnostic field is missing, THEN THE Diagnostics_Recorder SHALL reject the report with a field-path validation error.
28. IF a finite-required diagnostic number is non-finite, THEN THE Diagnostics_Recorder SHALL reject the report with a field-path validation error.
29. THE Diagnostics_Recorder SHALL produce the machine-readable report from ordered per-detection records.
30. THE Diagnostics_Recorder SHALL produce the human-readable summary from the same ordered per-detection records used for the machine-readable report.
31. WHEN referenced replay artifacts match recorded Artifact_Hashes, THE Diagnostics_Recorder SHALL regenerate diagnostics without keypoint inference.
32. WHEN diagnostics are regenerated from hash-matching replay artifacts, THE Diagnostics_Recorder SHALL reproduce every mode decision exactly.
33. WHEN diagnostics are regenerated from hash-matching replay artifacts, THE Diagnostics_Recorder SHALL reproduce every gate outcome exactly.
34. WHEN diagnostics are regenerated from hash-matching replay artifacts, THE Diagnostics_Recorder SHALL reproduce every status, usability value, reason code, and coordinate role exactly.
35. WHEN diagnostics are regenerated from hash-matching replay artifacts, THE Diagnostics_Recorder SHALL reproduce the Canonical_JSON machine-readable report Artifact_Hash exactly.
36. WHEN diagnostics are regenerated from hash-matching replay artifacts, THE Diagnostics_Recorder SHALL reproduce every human-readable summary value exactly.
37. IF any replay artifact fails Artifact_Hash verification, THEN THE Diagnostics_Recorder SHALL reject replay with code `diagnostic_replay_artifact_mismatch`.
38. WHEN any threshold changes, THE Diagnostics_Recorder SHALL record the previous threshold value.
39. WHEN any threshold changes, THE Diagnostics_Recorder SHALL record the new threshold value.
40. WHEN any threshold changes, THE Diagnostics_Recorder SHALL record the change reason.
41. WHEN any threshold changes, THE Diagnostics_Recorder SHALL record the evaluation-run identifier.
### Requirement 13: Preserve Opt-In Backward Compatibility

**User Story:** As an integrator, I want opt-in behavior and stable data contracts, so that existing Haware consumers continue to operate during rollout.

#### Acceptance Criteria

1. WHEN the versioned multi-cue configuration flag is absent, THE Compatibility_Layer SHALL keep multi-cue functionality disabled.
2. WHEN the versioned multi-cue configuration flag is `false`, THE Compatibility_Layer SHALL keep multi-cue functionality disabled.
3. WHEN the versioned multi-cue configuration flag contains the documented enabled value, THE Compatibility_Layer SHALL enable multi-cue functionality.
4. IF the multi-cue configuration flag has an unsupported version, THEN THE Compatibility_Layer SHALL return Typed_Validation_Failure code `invalid_multi_cue_configuration` before record processing.
5. IF the multi-cue configuration flag has an unsupported type or value, THEN THE Compatibility_Layer SHALL return Typed_Validation_Failure code `invalid_multi_cue_configuration` before record processing.
6. THE Compatibility_Layer SHALL preserve Apollo-24 template indices.
7. THE Compatibility_Layer SHALL preserve Apollo-24 template dimensions.
8. THE Compatibility_Layer SHALL preserve coordinate convention `+x = vehicle left`.
9. THE Compatibility_Layer SHALL preserve coordinate convention `+y = up`.
10. THE Compatibility_Layer SHALL preserve coordinate convention `+z = rear`.
11. THE Compatibility_Layer SHALL preserve the meaning of `sat_coords`.
12. THE Compatibility_Layer SHALL preserve the meaning of `heading`.
13. THE Compatibility_Layer SHALL preserve the meaning of `confidence`, `n_keypoints`, and `n_wheel_kp`.
14. THE Compatibility_Layer SHALL preserve the meaning of `status`, `p_sat`, and `spread_m`.
15. THE Schema_Compatibility_Profile SHALL define required fields, optional fields, types, enum domains, nullability, and deterministic mappings for every supported schema version.
16. WHERE multi-cue functionality is enabled, THE Compatibility_Layer SHALL emit an explicit multi-cue schema version listed in the Schema_Compatibility_Profile.
17. WHERE multi-cue functionality is enabled, THE Compatibility_Layer SHALL emit versioned usability, Estimator_Mode, status-reason, cue-role, cue-family, and diagnostic fields required by the emitted schema version.
18. WHERE multi-cue functionality is enabled, THE Compatibility_Layer SHALL preserve the semantic meaning of every legacy field emitted by the emitted schema version.
19. WHERE multi-cue functionality is disabled, THE Compatibility_Layer SHALL emit the Frozen_Baseline legacy schema.
20. WHERE multi-cue functionality is disabled, THE Compatibility_Layer SHALL omit every field classified as multi-cue-only by the Schema_Compatibility_Profile.
21. WHEN multi-cue functionality is disabled, THE Compatibility_Layer SHALL satisfy Requirement 1 disabled-mode parity tolerances.
22. WHEN a supported-schema record is serialized and deserialized, THE Compatibility_Layer SHALL preserve every required field name exactly.
23. WHEN a supported-schema record is serialized and deserialized, THE Compatibility_Layer SHALL preserve every required field type exactly.
24. WHEN a supported-schema record is serialized and deserialized, THE Compatibility_Layer SHALL preserve every finite numeric value within absolute error `1e-12`.
25. WHEN a supported-schema record is serialized and deserialized, THE Compatibility_Layer SHALL preserve every enum value exactly.
26. WHEN a supported-schema record is serialized and deserialized, THE Compatibility_Layer SHALL preserve every null value exactly.
27. WHEN a supported-schema record is serialized and deserialized, THE Compatibility_Layer SHALL preserve array order exactly.
28. WHEN a supported-schema record is serialized and deserialized, THE Compatibility_Layer SHALL preserve object-key meaning exactly.
29. WHEN a supported legacy record is read, THE Compatibility_Layer SHALL produce a valid internal record without multi-cue-only fields.
30. WHEN a supported internal legacy record is written to the originating schema version, THE Compatibility_Layer SHALL satisfy every supported-schema round-trip rule.
31. IF a supported-schema record lacks a required field, THEN THE Compatibility_Layer SHALL return Typed_Validation_Failure code `missing_required_schema_field` with the field path.
32. IF a supported-schema field has an invalid type, enum value, or nullability, THEN THE Compatibility_Layer SHALL return Typed_Validation_Failure code `invalid_schema_field` with the field path.
33. IF an input schema version is unsupported, THEN THE Compatibility_Layer SHALL fail before record-payload processing.
34. IF an input schema version is unsupported, THEN THE Compatibility_Layer SHALL return Typed_Validation_Failure code `unsupported_schema_version`.
35. IF an input schema version is unsupported, THEN THE Compatibility_Layer SHALL include the observed version in the Typed_Validation_Failure.
36. IF an input schema version is unsupported, THEN THE Compatibility_Layer SHALL include the ordered supported-version list in the Typed_Validation_Failure.
### Requirement 14: Preserve Calibration Identifiability Boundaries

**User Story:** As a calibration reviewer, I want effective parallax mismatch separated from physical camera height, so that evaluation does not claim an unidentifiable calibration result.

#### Acceptance Criteria

1. THE Calibration_Analyzer SHALL estimate Effective_Eta separately for every Acceptance_Site and documented keypoint-height family.
2. THE Calibration_Analyzer SHALL represent Effective_Eta as `eta = h / z_cam`.
3. THE Calibration_Analyzer SHALL record site and height-family identifier with every Effective_Eta estimate.
4. THE Calibration_Analyzer SHALL record height prior and height-prior uncertainty with every Effective_Eta estimate.
5. THE Calibration_Analyzer SHALL represent every Effective_Eta_Interval with finite lower and upper bounds.
6. THE Calibration_Analyzer SHALL require `lower <= upper` for every Effective_Eta_Interval.
7. THE Calibration_Analyzer SHALL require every Effective_Eta point estimate to be finite.
8. THE Calibration_Analyzer SHALL require every Effective_Eta point estimate to satisfy `lower <= eta <= upper` for the associated Effective_Eta_Interval.
9. WHEN only image observations and height priors are available, THE Calibration_Analyzer SHALL classify `h` and `z_cam` as not separately identifiable.
10. WHEN `h = 0` and Effective_Eta equals zero, THE Calibration_Analyzer SHALL classify `z_cam` as unidentifiable from the zero-height family.
11. WHEN `lower <= 0 <= upper`, THE Calibration_Analyzer SHALL classify the Effective_Eta_Interval as including zero.
12. WHEN `upper < 0` or `lower > 0`, THE Calibration_Analyzer SHALL classify the Effective_Eta_Interval as excluding zero.
13. WHEN independently measured `h` is positive, Effective_Eta is positive, and the Effective_Eta_Interval lower bound is positive, THE Calibration_Analyzer SHALL compute candidate `Jointly_Identified_Z_Cam = h / eta`.
14. WHEN candidate Jointly_Identified_Z_Cam is finite and positive, THE Calibration_Analyzer SHALL include Jointly_Identified_Z_Cam in authoritative calibration outputs.
15. IF candidate Jointly_Identified_Z_Cam is non-finite or non-positive, THEN THE Calibration_Analyzer SHALL omit Jointly_Identified_Z_Cam from authoritative calibration outputs.
16. IF an Effective_Eta_Interval upper bound is negative, THEN THE Calibration_Analyzer SHALL omit Jointly_Identified_Z_Cam from authoritative calibration outputs.
17. WHEN independently measured Direct_Z_Cam is finite and positive, THE Calibration_Analyzer SHALL compute candidate `h = eta * z_cam`.
18. WHEN candidate `h = eta * z_cam` is finite and positive, THE Calibration_Analyzer SHALL include derived `h` in authoritative calibration outputs.
19. IF candidate `h = eta * z_cam` is non-finite or non-positive, THEN THE Calibration_Analyzer SHALL omit derived `h` from authoritative calibration outputs.
20. WHEN Direct_Z_Cam is supplied by independent metrology, THE Calibration_Analyzer SHALL label Direct_Z_Cam `metrology_derived`.
21. WHEN Jointly_Identified_Z_Cam is authoritative, THE Calibration_Analyzer SHALL label the value `jointly_identified_z_cam`.
22. WHEN independent metrology provides uncertainty, THE Calibration_Analyzer SHALL propagate uncertainty by the frozen uncertainty procedure.
23. WHEN independent metrology omits uncertainty, THE Calibration_Analyzer SHALL label the identified parameter `uncertainty_unavailable`.
24. IF an Effective_Eta_Interval includes zero, THEN THE Calibration_Analyzer SHALL omit Jointly_Identified_Z_Cam from authoritative calibration outputs.
25. IF independent metrology is absent, THEN THE Calibration_Analyzer SHALL omit Direct_Z_Cam from authoritative calibration outputs.
26. THE Calibration_Analyzer SHALL prohibit pooling Effective_Eta estimates across sites for an authoritative estimate.
27. THE Calibration_Analyzer SHALL prohibit pooling Effective_Eta estimates across height families for an authoritative estimate.
28. THE Diagnostics_Recorder SHALL use distinct field names for Effective_Eta, configured `z_cam`, Direct_Z_Cam, and Jointly_Identified_Z_Cam.
29. THE Measurement_Harness SHALL exclude Effective_Eta improvement as evidence of Direct_Z_Cam correction.
30. THE Measurement_Harness SHALL evaluate reliability-aware multi-cue position accuracy independently of every Direct_Z_Cam claim.
### Requirement 15: Verify Executable Correctness Properties

**User Story:** As a maintainer, I want automated correctness properties, so that estimator and pipeline invariants hold across broad generated input sets.

#### Acceptance Criteria

1. THE Validation_Suite SHALL execute every property-based criterion with seeds `104729`, `130363`, `155921`, and `196613`.
2. THE Validation_Suite SHALL execute at least 100 generated cases per property per PBT_Profile seed.
3. THE Validation_Suite SHALL generate point counts, coordinates, transforms, weights, separations, and rank conditions within every PBT_Profile range.
4. WHEN a property fails, THE Validation_Suite SHALL record the property name, PBT_Profile version, seed, generated-case index, minimized counterexample, and exact replay command.
5. WHEN a recorded failing seed and minimized counterexample are replayed, THE Validation_Suite SHALL reproduce the same property failure without generating new cases.
6. WHEN a nondegenerate noise-free synthetic wheel pose is generated, THE Validation_Suite SHALL recover every position component within absolute error `1e-9` pixels.
7. WHEN a nondegenerate noise-free synthetic wheel pose is generated, THE Validation_Suite SHALL recover heading within Angular_Difference `1e-9` degrees.
8. WHEN a PBT_Profile translation is applied to every observation, THE Validation_Suite SHALL verify equal translation of every usable Estimator_Mode position within absolute error `1e-9` pixels.
9. WHEN a PBT_Profile translation is applied to every observation, THE Validation_Suite SHALL preserve status exactly.
10. WHEN a PBT_Profile translation is applied to every observation, THE Validation_Suite SHALL preserve Estimator_Mode exactly.
11. WHEN a PBT_Profile rotation is applied to every source and observation point about one origin, THE Validation_Suite SHALL verify rotation equivariance of every usable position within absolute error `1e-9` pixels.
12. WHEN a PBT_Profile rotation is applied to every source and observation point about one origin, THE Validation_Suite SHALL verify the matching heading change within Angular_Difference `1e-9` degrees.
13. WHEN generated keypoint records are permuted, THE Validation_Suite SHALL preserve Estimator_Mode, status, usability, and reason code exactly.
14. WHEN generated keypoint records are permuted, THE Validation_Suite SHALL preserve center components within absolute error `1e-9` pixels.
15. WHEN generated keypoint records are permuted, THE Validation_Suite SHALL preserve heading within Angular_Difference `1e-9` degrees.
16. WHERE Weighted_Procrustes_Estimator is enabled, THE Validation_Suite SHALL verify positive uniform weight-scale invariance over PBT_Profile weights and multipliers.
17. WHERE Weighted_Procrustes_Estimator is enabled, THE Validation_Suite SHALL verify `t = p_bar - R q_bar` over generated nondegenerate point sets.
18. WHERE Weighted_Procrustes_Estimator is enabled, THE Validation_Suite SHALL verify zero-weight-point invariance for centroids, covariance, objective, rank, position, and heading.
19. WHEN a generated detection has zero visible wheels and a reliability-eligible non-wheel Primary_Support_Path, THE Validation_Suite SHALL verify the frozen `single_family` or `complementary_multi_cue` result.
20. WHEN a generated detection has zero visible wheels and no reliability-eligible Primary_Support_Path, THE Validation_Suite SHALL verify the frozen fallback-or-none result.
21. WHEN a generated cue constraint has projected baseline or leverage below the frozen role boundary, THE Validation_Suite SHALL verify exclusion of the cue constraint from that role.
22. WHEN generated cue constraints satisfy every applicable Cue_Eligibility_Check, THE Validation_Suite SHALL verify the Geometry_Profile mode and weight result.
23. WHEN an Ambiguous_Fit is generated, THE Validation_Suite SHALL verify Typed_Validation_Failure code `degenerate_geometry`.
24. WHEN an Unusable_Localization passes through enrichment, THE Validation_Suite SHALL verify null Authoritative_Position, `position_m`, and `velocity_mps`.
25. WHEN an Unusable_Localization passes through scene scanning, THE Validation_Suite SHALL verify exclusion from track positions and collider eligibility.
26. WHEN an Unusable_Localization is serialized and deserialized in a supported schema, THE Validation_Suite SHALL preserve unusable status and null Authoritative_Position.
27. WHERE temporal fusion is enabled, WHEN an Unusable_Localization passes through temporal fusion, THE Validation_Suite SHALL preserve unusable status, `usable=false`, and null Authoritative_Position.
28. WHEN every supported status and Estimator_Mode combination is serialized and deserialized, THE Validation_Suite SHALL verify every Requirement 13 round-trip rule.
29. WHEN multi-cue functionality is disabled, THE Validation_Suite SHALL verify every Requirement 1 disabled-mode parity rule.
30. WHEN non-finite keypoints are generated, THE Validation_Suite SHALL verify Typed_Validation_Failure code `non_finite_coordinate`.
31. WHEN negative weights are generated, THE Validation_Suite SHALL verify Typed_Validation_Failure code `invalid_weight`.
32. WHEN non-finite weights are generated, THE Validation_Suite SHALL verify Typed_Validation_Failure code `invalid_weight`.
33. WHEN zero-total weights are generated, THE Validation_Suite SHALL verify Typed_Validation_Failure code `zero_total_weight`.
34. WHEN unsupported schemas are generated, THE Validation_Suite SHALL verify Typed_Validation_Failure code `unsupported_schema_version`.
35. WHEN malformed status values are generated, THE Validation_Suite SHALL verify a typed status-validation failure.
36. WHEN calibration identifiers are missing, THE Validation_Suite SHALL verify a typed calibration-validation failure.
37. WHEN a generated report substitutes any Proxy_Metric for Planar_Position_Error, THE Validation_Suite SHALL verify candidate rejection.
38. WHEN Diagnostic_Site records are added to an acceptance input, THE Validation_Suite SHALL preserve every acceptance numerator, denominator, confidence interval, and pass-fail result exactly.
39. WHEN Diagnostic_Site records are removed from an acceptance input, THE Validation_Suite SHALL preserve every acceptance numerator, denominator, confidence interval, and pass-fail result exactly.
40. WHEN Diagnostic_Site records are permuted within an acceptance input, THE Validation_Suite SHALL preserve every acceptance numerator, denominator, confidence interval, and pass-fail result exactly.
41. WHEN an Unusable_Localization contains a finite Diagnostic_Position, THE Validation_Suite SHALL verify null Authoritative_Position outputs for enrichment, velocity, scene, collider, and fusion processing.
42. WHEN finite spread is the greatest representable value below the Spread_Gate boundary, THE Validation_Suite SHALL verify Spread_Gate acceptance.
43. WHEN finite spread equals the exact representable Spread_Gate boundary, THE Validation_Suite SHALL verify Spread_Gate rejection.
44. WHEN finite spread is the least representable value above the Spread_Gate boundary, THE Validation_Suite SHALL verify Spread_Gate rejection.
45. WHEN a Projection_Conditioning_Metric is the greatest representable value below the Near_Horizon_Threshold, THE Validation_Suite SHALL verify conditioning acceptance.
46. WHEN a Projection_Conditioning_Metric equals the exact representable Near_Horizon_Threshold, THE Validation_Suite SHALL verify conditioning rejection.
47. WHEN a Projection_Conditioning_Metric is the least representable value above the Near_Horizon_Threshold, THE Validation_Suite SHALL verify conditioning rejection.
48. WHEN a minimum geometry value equals the frozen minimum boundary, THE Validation_Suite SHALL verify geometry acceptance.
49. WHEN a minimum geometry value is below the frozen minimum boundary, THE Validation_Suite SHALL verify geometry rejection.
50. WHEN fixed Evaluation_Population matching is missing or ambiguous, THE Validation_Suite SHALL verify site-evaluation failure without denominator shrinkage.
51. WHEN baseline and candidate usable subsets differ, THE Validation_Suite SHALL verify separate Error_Samples over one fixed Evaluation_Population denominator.
52. WHEN finite-confidence Selective_Risk inputs are empty, THE Validation_Suite SHALL verify an empty curve and null requested-point values.
53. WHEN fallback outputs are usable, THE Validation_Suite SHALL verify fallback participation in overall accuracy, coverage, and Selective_Risk.
54. WHEN a safety gate rejects a detection, THE Validation_Suite SHALL verify that no later Fallback_Path produces a usable result.
55. WHILE the Phase_0_Gate is incomplete, THE Validation_Suite SHALL verify that no final multi-cue pass decision is emitted.
56. WHILE the Phase_0_Gate is incomplete, THE Validation_Suite SHALL verify that no final multi-cue acceptance decision is emitted.
57. WHEN duplicate ground-truth reference identities are generated, THE Validation_Suite SHALL verify exclusion of every reference position in each duplicate-reference-identity group with the frozen duplicate-reference-identity exclusion code.
58. WHEN records in a generated duplicate-reference-identity group are permuted, THE Validation_Suite SHALL preserve the excluded reference-position set and exclusion code exactly.
59. WHEN uniformly scaled weights remain finite and scaled total weight `W` is non-finite, THE Validation_Suite SHALL verify Typed_Validation_Failure code `numeric_failure`.
60. WHEN a usable observation is generated as the first usable observation after a Track_Interruption, THE Validation_Suite SHALL verify null `velocity_mps`.
61. WHEN Effective_Eta equals zero, THE Validation_Suite SHALL verify omission of Jointly_Identified_Z_Cam from authoritative calibration outputs.
62. WHEN Effective_Eta is positive, the Effective_Eta_Interval lower bound is positive, independently measured `h` is positive, and `h / eta` is finite, THE Validation_Suite SHALL verify inclusion of Jointly_Identified_Z_Cam in authoritative calibration outputs.
63. WHEN generated cue records are permuted, THE Validation_Suite SHALL preserve selected Cue_Families, constraint roles, Cue_Eligibility_Check outcomes, and cue weights exactly.
64. WHEN generated windshield or glass-corner cues have reliable bearing evidence and insufficient heading leverage, THE Validation_Suite SHALL verify an eligible Position_Bearing_Constraint and an ineligible Orientation_Constraint.
65. WHEN generated mirror cues are evaluated, THE Validation_Suite SHALL verify application of the mirror Height_Family uncertainty model and exclusion from Zero_Height_Anchor classification.
66. WHERE the generated site is `kee-cc`, WHEN `front_up_right` index `0` fails the frozen semantic-misplacement gate, THE Validation_Suite SHALL verify exclusion of index `0` from estimator support.
67. WHERE a generated site and view lack evidence of the kee-cc index `0` anomaly, THE Validation_Suite SHALL verify evaluation under the generated site-view evidence rather than the kee-cc gate.
68. WHEN generated orientation evidence belongs to one Height_Family, THE Validation_Suite SHALL verify heading invariance under one common finite Effective_Eta perturbation applied to that Height_Family.
69. WHEN generated orientation evidence belongs to multiple Height_Families, THE Validation_Suite SHALL verify separate per-family Orientation_Constraints before uncertainty-aware combination.
70. WHEN generated Height_Families have unequal Effective_Eta errors, THE Validation_Suite SHALL verify that raw cross-family point pooling is absent from orientation estimation.
71. WHEN one generated Cue_Family supplies reliable orientation and another generated Cue_Family supplies reliable position or bearing, THE Validation_Suite SHALL verify selection of `complementary_multi_cue`.
72. WHEN generated Zero_Height_Anchor and nonzero-height position cues have otherwise equal reliability evidence, THE Validation_Suite SHALL verify preference for the Zero_Height_Anchor.
73. WHEN generated cue constraints differ only in projected baseline or leverage, THE Validation_Suite SHALL verify a nondecreasing weight as projected baseline or leverage increases.
74. WHEN generated cue constraints differ only in Height_Family uncertainty, THE Validation_Suite SHALL verify a nonincreasing weight as Height_Family uncertainty increases.