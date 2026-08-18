# Requirements Document

## Introduction

This specification defines a feasibility-first replacement for the proposed projected-point Procrustes and role-constraint-graph architectures. The new core is a detector-agnostic, image-space forward-model optimizer that generates multiple pose hypotheses, predicts template keypoints into calibrated CCTV image space, and scores robust reprojection residuals. When evidence-supported wheel or ground-contact cues are available, the optimizer uses their zero-height geometry first for initialization, anchoring, and hypothesis generation. Wheel-first is a preference rather than a wheel-only rule: non-wheel hypotheses remain eligible and can be selected.

The smallest credible MVP is an offline two-site pilot implemented under `trafficlab-project`. The pilot replays stored keypoints for the two named Acceptance_Sites (`kee-cc` and `taoyuan-tc` at the time of writing), compares a corrected frozen legacy baseline with the robust optimizer, uses independent ground truth and genuine tracker identities, and estimates effect size, uncertainty, view and track coverage, data sufficiency, and power. The power method, metric definitions, and the minimum effect of interest are frozen before outcome evaluation; final thresholds are derived from pilot evidence and frozen before a disjoint held-out evaluation. `taipei-cm` remains diagnostic-only. Current checked-in data are insufficient for final acceptance and do not prove improvement.

The whole system is an offline background batch: a full source video may take minutes to localize (Requirement 13 bounds it), and no clause in this specification implies real-time or per-frame latency. A weighted-Procrustes wheel-first estimator (the 2026-08-10 proposal) is carried as a Diagnostic_Candidate arm inside the pilot only (Requirement 12); it is never the production core.

The Corrected_Legacy_Baseline is what production runs today and will keep running until held-out `go`; therefore its status vocabulary (`ok`, `extrapolated`, `failed_insufficient_kp`) is bound to coordinate authority by an explicit Legacy_Status_Policy (Requirement 1.19) that exists before any pilot, and the scene-bundle last mile (`tools/build_scene.py`, `scenes/<code>/trajectory.json`) is bound by Requirement 7 even though it lives outside the Canonical_Implementation.

## Glossary

- **Localization_System**: The Haware vehicle-localization capability governed by this specification.
- **Canonical_Implementation**: The exclusive production boundary `trafficlab-project/**` for this feature.
- **Legacy_Input_Tree**: Either repository subtree `pifpaf/**` or `location/**` outside `trafficlab-project/**`, available only as read-only legacy or scratch input.
- **Frozen_Baseline**: A reproducibly identified output of legacy `localize()` or `localize_reprojection()` behavior used only for comparison, regression evidence, or tooling.
- **Corrected_Legacy_Baseline**: The Frozen_Baseline for existing `localize()` behavior with the applied handedness correction and configured spread behavior, used for MVP comparison and Optimizer_Disabled_Mode parity. Its status vocabulary is exactly `ok`, `extrapolated`, `failed_insufficient_kp`, `pre_gate_near_horizon` (Requirement 1.23; emitted in the legacy schema before fitting), and `ambiguous_heading` from `localize_reprojection()`.
- **Legacy_Status_Policy**: A versioned, content-identified artifact mapping each Corrected_Legacy_Baseline status to Accepted_Result or Rejected_Result with a decisive reason. It is defined independently of the Acceptance_Profile, exists before any pilot, and is required on the Optimizer_Disabled_Mode/production path.
- **Diagnostic_Candidate**: A named estimator arm (for the MVP: `wheel_weighted_procrustes`, a wheel-weighted fixed-scale Procrustes on the corrected baseline geometry with `n_wheel_kp < 2` fallback to the full-point fit) run by the Pilot_Harness on the same ordered Eligible_Detections for comparison only. It never participates in production dispatch, the Pilot_Feasibility_Gate, held-out decisions, or any improvement claim.
- **Batch_Runtime_Envelope**: The frozen wall-clock bound for localizing one complete source video in background batch mode, expressed as wall-clock seconds per second of source video (Requirement 13: at most `10 s / s`, i.e. 600 s for a 60 s clip).
- **Optimizer_Disabled_Mode**: Configuration that dispatches to the Corrected_Legacy_Baseline instead of the Pose_Optimizer.
- **Observation_Provider**: A replaceable detector or replay source that supplies keypoint observations; PifPaf is one Observation_Provider.
- **Observation_Adapter**: The detector-independent boundary that converts provider records into Image_Observations.
- **Replay_Reader**: The component that parses stored keypoint replay records.
- **Replay_Writer**: The component that emits stored keypoint replay records.
- **Image_Observation**: A finite CCTV image coordinate with confidence, candidate semantic label, frame identity, detection identity, provider provenance, and optional Real_Track_ID.
- **Vehicle_Template**: The versioned three-dimensional keypoint model with body axes `+x = vehicle left`, `+y = up`, and `+z = rear`.
- **Pose**: Vehicle planar position and heading in the preserved satellite-coordinate and heading conventions.
- **Calibrated_Forward_Model**: The mapping that transforms Vehicle_Template points by a Pose and projects the transformed points into CCTV image space using the Calibration_Profile.
- **Calibration_Profile**: Versioned calibration values, bounded nuisance intervals, coordinate conventions, and provenance used by the Calibrated_Forward_Model.
- **Nuisance_Profile**: Frozen finite closed intervals for keypoint-family heights, vehicle dimensions, and calibration quantities authorized for variation during optimization.
- **Cue_Family**: A documented semantic keypoint family, including wheel or ground-contact, glass or windshield, roof, mirror, and other evidence-supported cues.
- **Cue_Height_Interval**: A bounded physical-height interval and uncertainty assigned to a Cue_Family or keypoint by documented evidence.
- **Ground_Contact_Cue**: A wheel or other evidence-supported road-contact cue with height and height uncertainty fixed at `h=0`.
- **Cue_Evidence_Profile**: Versioned site/view evidence that defines supported Cue_Families, semantic mappings, Cue_Height_Intervals, and provenance.
- **Pose_Hypothesis**: A candidate Pose with semantic interpretation, correspondence mapping, evidence-supported cue subset, initialization source, nuisance values, and provenance.
- **Wheel_Seeded_Hypothesis**: A Pose_Hypothesis initialized or anchored first with evidence-supported Ground_Contact_Cues at `h=0`.
- **Non_Wheel_Seeded_Hypothesis**: A Pose_Hypothesis initialized without Ground_Contact_Cues from another evidence-supported Cue_Family.
- **Normal_Semantics_Hypothesis**: A Pose_Hypothesis that uses provider front/rear semantics without reversal.
- **Reversed_Semantics_Hypothesis**: A Pose_Hypothesis that evaluates the applicable front/rear swap or 180-degree alternative.
- **Robust_Procedure**: The frozen deterministic outlier procedure comprising minimal-hypothesis sampling and robust nonlinear refinement, or an evidence-equivalent deterministic procedure frozen before held-out evaluation.
- **Support_Set**: The Image_Observations retained as inliers for a Pose_Hypothesis after application of the frozen robust support rule.
- **Robust_Reprojection_Score**: The frozen robust aggregate of CCTV image-space residuals, Support_Set evidence, and documented penalties used to compare Pose_Hypotheses.
- **Pose_Optimizer**: The component that generates, robustly refines, scores, deduplicates, and selects Pose_Hypotheses using the Calibrated_Forward_Model.
- **Position_Equivalent_Ambiguity**: The state in which the tied-best Pose_Hypotheses disagree on heading beyond the frozen ambiguity tolerance but agree on position within `position_ambiguity_tolerance_m`. It yields an Accepted_Result carrying the Authoritative_Position with a null heading, because this repository consumes only the position half of localization.
- **Validity_Gate_Set**: The frozen subset of per-hypothesis gates whose survivors form the initial unique valid hypothesis set from which the Hypothesis_Margin requirement is latched. For the MVP it is exactly {support, non-finite, convergence}; rank, conditioning, uncertainty, and spread gates are evaluated on the selected representative after latching.
- **Hypothesis_Margin**: The frozen score difference or ratio between the selected unique hypothesis and the next-best unique valid hypothesis.
- **Conditioning_Metric**: A finite scalar derived from the optimized image-residual system whose ordering and rejection boundary quantify sensitivity of Pose to observation perturbations.
- **Observability_Diagnostics**: Jacobian, Hessian or information-matrix rank and conditioning measures, plus the resulting Pose covariance or uncertainty bounds.
- **Accepted_Result**: A usable localization that passes support, optimization, conditioning, uniqueness, uncertainty, spread, and numeric gates, contains one finite Authoritative_Position, and contains a null Diagnostic_Position. A Corrected_Legacy_Baseline record becomes an Accepted_Result only through the Legacy_Status_Policy.
- **Reference_Point**: The Vehicle_Template origin — the ground-plane point `(x=0, h=0, z=0)` midway between the four wheel ground contacts — transformed by a Pose into the satellite frame. Every Authoritative_Position, Diagnostic_Position, and Independent_Ground_Truth coordinate denotes this physical point.
- **Metric_Frame**: Satellite-image pixel coordinates of the site's Calibration_Profile reference image (`location/<code>/sat_<code>.png`) divided by its `px_per_meter`, origin at the image top-left, `+x` right, `+y` down, units metres. This is the frame `position_m` already uses.
- **Rejected_Result**: An unusable localization that fails a required gate, records one decisive machine-readable reason, contains a null Authoritative_Position, and may contain a Diagnostic_Position.
- **Authoritative_Position**: A finite accepted coordinate permitted for enrichment, velocity, scene geometry, and colliders.
- **Diagnostic_Position**: A coordinate retained for analysis and prohibited from downstream spatial authority.
- **Spread_Diagnostic**: The existing projected-keypoint spread measurement with a frozen computation and boundary policy.
- **Real_Track_ID**: A stable vehicle identity with tracker name, tracker version, Source_Sequence, association provenance, and consistent occurrence across more than one frame. The ByteTrack identities already produced by `scripts/eval_haware_replay.py` qualify once that script emits their provenance (Requirement 8.14).
- **Capture_ID**: The identity of one physical recording session (one camera, one continuous shoot) at one Acceptance_Site, derived from the source video path and its content digest.
- **Source_Sequence**: One contiguous span of frames within one Capture_ID. Time-disjoint spans of one capture are separate Source_Sequences only when separated by a temporal buffer of length `T` frozen in the Acceptance_Profile with no Real_Track_ID present on both sides of the buffer; otherwise the whole capture is one Source_Sequence. Splitting a capture never creates a second Capture_ID.
- **Pseudo_Track_ID**: A frame-local or unverified identity, including an identifier constructed in the `500+` range or any identifier with missing or inconsistent tracker provenance.
- **Motion_Tie_Breaker**: An optional Real_Track_ID motion diagnostic that cannot override a required frame-local ambiguity rejection.
- **Independent_Ground_Truth**: Reference vehicle positions created without access to baseline outputs, candidate outputs, Haware coordinates, or Haware overlays, produced under the GT_Annotation_Protocol.
- **GT_Annotation_Protocol**: The versioned annotation procedure (`gt-protocol-v1`, defined in design §8) fixing annotator blinding, annotation medium, the annotated physical point and its conversion to the Reference_Point, frame-sampling rule, repeat-annotation fraction, and how per-record `uncertainty` is measured rather than asserted.
- **Acceptance_Site**: One of exactly two Site_IDs named in `AcceptanceProfile.acceptance_sites`, drawn from the frozen candidate-site pool and subject to the pre-freeze calibration health check of Requirement 9.24. The pool and the two names are `kee-cc` and `taoyuan-tc` at the time of writing; substitution is governed by Requirement 9.25. `taipei-cm` is permanently ineligible.
- **Diagnostic_Site**: `taipei-cm`, which is excluded from acceptance decisions.
- **Eligible_Detection**: A detection that satisfies the frozen site, partition, replay, ground-truth, uncertainty, and identity rules before baseline or optimizer outcome is considered.
- **Pilot_Partition**: Data used to estimate effect size, uncertainty, track/view coverage, data sufficiency, and candidate thresholds.
- **Held_Out_Partition**: Data isolated from candidate, policy, nuisance, and threshold selection until the Acceptance_Profile is frozen.
- **Independent_View**: A stratum `(camera_id, Source_Sequence, scene_region)` where `scene_region` is a frozen band of ground-plane distance from the camera nadir (or of homography magnification `1/k`) computed from the Independent_Ground_Truth Reference_Point, never from baseline or candidate output; band edges are frozen in the Acceptance_Profile before outcomes.
- **Pilot_Harness**: The offline evaluator that replays observations, validates evidence, compares candidates, estimates uncertainty, and emits pilot and held-out reports.
- **Acceptance_Profile**: The immutable versioned candidate-configuration artifact (calibration, cue-evidence, nuisance, optimizer, replay contract, Legacy_Status_Policy identity, Pilot_Statistics_Method, GT_Annotation_Protocol identity, deterministic seed). Its pre-pilot version freezes methods, gates, and metric definitions; the post-`go` version additionally records per-site held-out thresholds and is identified by the git commit SHA of the committed profile file (Requirement 11.16).
- **Pilot_Statistics_Method**: The frozen statistical procedure (`pilot-stats-v1`, design §8): paired per-track effects, exact enumeration or seeded resampling, nearest-rank percentile intervals, variance and power method, methodological validity minimum of clusters, and the feasibility rule shape.
- **Minimum_Effect_Of_Interest**: A frozen per-effect magnitude in output units (metres for median-error and p90-error effects, coverage fraction for the Usable_Coverage effect), justified from the downstream sensitivity of the scene player's collision conclusion and fixed before any baseline or candidate outcome is read. It is not an acceptance threshold and is distinct from the derived per-site thresholds.
- **Paired_Accepted_Set**: The Eligible_Detections at one Acceptance_Site that received an Accepted_Result from both the Corrected_Legacy_Baseline and the compared candidate configuration; the fixed population for median-error and p90-error effects.
- **Usable_Coverage**: The number of Eligible_Detections with an Accepted_Result divided by the fixed Eligible_Detection count.
- **Effect_Interval**: A frozen-confidence interval for a candidate-minus-baseline metric effect that preserves Real_Track_ID clusters.
- **Pilot_Feasibility_Gate**: The go/no-go decision based on pilot effect estimates, Effect_Intervals, independent-track coverage, Independent_View coverage, and data sufficiency.
- **Deferred_Capability**: Detector replacement or retraining, generalized learned reliability, a full multi-provider schema platform, exhaustive artifact management, a selective-risk suite, calibration identification, temporal or multi-sensor fusion, or another capability not required by the MVP (see "Scope boundary and later phases").
- **Downstream_Consumer**: `scripts/filter_and_enrich_output.py`, `postprocess.py`, `trafficlab/trajectory/*`, `trafficlab/io/replay_writer.py`, and — outside the Canonical_Implementation but governed by Requirement 7 — `tools/build_scene.py` and the Scene_Export_Contract.
- **Scene_Export_Contract**: The `scenes/<code>/trajectory.json` shape consumed by `tools/build_scene.py` and the Three.js player: each object retains `tracked_id`, `status`, decisive reason, `sat_coords`, `position_m` (null for any non-Accepted_Result), and optional `diagnostic_position_sat_px`; the top level retains `localization_counts` and the applied Legacy_Status_Policy version. `trajectory.json` is copied verbatim into the scene bundle; the per-collider selected segment (`segment: {start_frame, end_frame}`) is recorded by `build_scene.py` in `scene.json`, which is the sole owner of segmentation.

## Requirements

## MVP and Pilot Requirements

### Requirement 1: Establish Canonical Scope and Preserve Proven Behavior

**User Story:** As a maintainer, I want one implementation boundary and explicit baseline behavior, so that feasibility work does not duplicate production code or regress established conventions.

#### Acceptance Criteria

1. THE Localization_System SHALL define the repository subtree `trafficlab-project/**` as the exclusive Canonical_Implementation boundary for the estimator, coordinate-authority, and enrichment production implementation of this feature; `tools/build_scene.py` and the Scene_Export_Contract are named governed downstream exceptions bound by Requirement 7 and are the only production files this feature may modify outside that subtree.
2. THE Localization_System SHALL define the repository subtrees `pifpaf/**` and `location/**` outside `trafficlab-project/**` as the complete Legacy_Input_Tree boundary.
3. THE Localization_System SHALL treat every Legacy_Input_Tree as read-only input.
4. WHEN the Localization_System reads a Legacy_Input_Tree artifact, THE Localization_System SHALL record the repository-relative source path and a deterministic content identity in replay provenance.
5. THE Localization_System SHALL exclude Legacy_Input_Tree modules from production imports, writes, and runtime dispatch.
6. THE Localization_System SHALL preserve the Vehicle_Template body-axis conventions.
7. THE Localization_System SHALL preserve the applied template-to-satellite handedness correction in the Corrected_Legacy_Baseline.
8. THE Localization_System SHALL preserve the Spread_Diagnostic computation used by the Corrected_Legacy_Baseline.
9. WHEN the Pose_Optimizer is selected AND a spread boundary is enabled, THE Localization_System SHALL classify a fitted result with non-finite spread or spread greater than or equal to the frozen boundary as a Rejected_Result with reason `spread_rejected`; the Corrected_Legacy_Baseline status `extrapolated` maps to `spread_rejected` only through the Legacy_Status_Policy.
10. WHEN the Spread_Diagnostic rejects a fitted result, THE Localization_System SHALL classify the fitted coordinate role as Diagnostic_Position.
11. THE Localization_System SHALL classify existing `localize()` behavior as the Corrected_Legacy_Baseline rather than the Pose_Optimizer architecture.
12. THE Localization_System SHALL classify existing `localize_reprojection()` behavior as a Frozen_Baseline rather than the Pose_Optimizer architecture.
13. WHEN configuration flag `optimizer_disabled_selected` is true, THE Localization_System SHALL reproduce each finite Corrected_Legacy_Baseline coordinate component and heading with absolute circular error no greater than `1e-9` in the corresponding output units.
14. WHEN configuration flag `optimizer_disabled_selected` is true, THE Localization_System SHALL reproduce every Corrected_Legacy_Baseline status, reason, null value, and non-finite classification exactly.
15. WHEN configuration flag `optimizer_disabled_selected` is true, THE Localization_System SHALL emit the frozen compatible baseline schema.
16. WHEN the Pose_Optimizer is selected, THE Pose_Optimizer SHALL generate, refine, score, deduplicate, and compare Pose_Hypotheses before selection.
17. WHERE wheel-seeded initialization is enabled (default true) AND eligible Ground_Contact_Cues exist, THE Pose_Optimizer SHALL begin hypothesis generation with Wheel_Seeded_Hypotheses before Non_Wheel_Seeded_Hypotheses.
18. WHEN a Non_Wheel_Seeded_Hypothesis has a strictly better frozen comparison value than every Wheel_Seeded_Hypothesis, THE Pose_Optimizer SHALL permit the Non_Wheel_Seeded_Hypothesis to win selection.
19. THE Localization_System SHALL freeze Legacy_Status_Policy version `legacy-localize-v1` before any pilot: status `ok` with finite `sat_coords` maps to Accepted_Result with Authoritative_Position equal to `sat_coords` — a non-finite or absent heading sets `heading=null` with `heading_status='ambiguous'` and never withdraws position authority, because this repository consumes only the position half; status `extrapolated` maps to Rejected_Result with decisive reason `spread_rejected` and Diagnostic_Position equal to `sat_coords`; status `pre_gate_near_horizon` maps to Rejected_Result with decisive reason `pre_gate_near_horizon` and null Diagnostic_Position; status `ok` with non-finite `sat_coords` maps to Rejected_Result with reason `legacy_status_evidence_insufficient` and null Diagnostic_Position; status `failed_insufficient_kp`, `ambiguous_heading`, any unknown status, or an absent status maps to Rejected_Result with reason `legacy_status_evidence_insufficient` and Diagnostic_Position equal to `sat_coords` when finite.
20. WHEN a Downstream_Consumer reads a record that carries legacy localization evidence (a `status` or `sat_coords`) but no new-contract authority fields, THE Downstream_Consumer SHALL apply Legacy_Status_Policy `legacy-localize-v1` by default and SHALL record the policy version applied; a consumer path on which no policy is resolvable SHALL be treated as a defect, not as missing localization.
21. WHEN a record carries neither new-contract authority fields nor any legacy localization evidence, THE Localization_System SHALL classify it as a missing localization rather than a Rejected_Result, so that a default policy cannot convert an unobserved track into a rejection reason.
22. THE Localization_System SHALL route a record to new-contract validation only when its `status` equals a defined localization status value, so that a legacy record carrying an incidental `decisive_gate` or `usable` key is still normalized through the Legacy_Status_Policy.
23. THE Corrected_Legacy_Baseline SHALL support a frozen pre-localization observability pre-gate per Calibration_Profile (`CalibrationProfile.pre_gate`: a CCTV image-row bound or a homography-magnification `1/k` bound) that emits the legacy-schema status `pre_gate_near_horizon` (null `sat_coords`) before fitting; the pre-gate is disabled unless `pre_gate` is set for the site, and it never alters the output of a detection that passes it.

### Requirement 2: Provide Detector-Independent Stored Replays

**User Story:** As an estimator developer, I want reproducible detector-independent observations, so that the optimizer can be evaluated without coupling to PifPaf inference.

#### Acceptance Criteria

1. THE Acceptance_Profile SHALL freeze one provider-neutral MVP Observation_Adapter contract before pilot outcome evaluation.
2. THE frozen Observation_Adapter contract SHALL define required and optional fields, field types, and numeric bounds (finite coordinates inside the image, confidence in `[0, 1]`).
3. THE Acceptance_Profile SHALL freeze one provider-neutral MVP replay schema before pilot outcome evaluation.
4. THE frozen replay schema SHALL define required and optional fields, field types, numeric bounds, schema version, and provenance fields.
5. THE Observation_Adapter SHALL normalize every contract-conforming provider record into Image_Observations before hypothesis generation.
6. THE Observation_Adapter SHALL preserve provider name, provider version, confidence, candidate semantic label, frame identity, detection identity, source provenance, and optional Real_Track_ID for each Image_Observation.
7. IF one observation has a non-finite coordinate or confidence or violates an observation-level bound, THEN THE Observation_Adapter SHALL exclude that observation with a machine-readable observation-level reason.
8. IF a record violates a record-level required field, type, identity, count, or provenance rule, THEN THE Observation_Adapter SHALL reject the complete record with a machine-readable record-level reason.
9. IF a record contains duplicate observation identities, THEN THE Observation_Adapter SHALL reject the complete record with reason `duplicate_observation_id`.
10. THE Observation_Adapter SHALL produce the same retained observations, exclusions, and reasons for every permutation of the input observations.
11. THE Observation_Adapter SHALL expose PifPaf through exactly one MVP adapter implementation.
12. THE Pose_Optimizer SHALL consume Image_Observations without importing an Observation_Provider implementation.
13. THE Replay_Reader SHALL parse contract-conforming records from the frozen replay schema.
14. IF one replay record violates the frozen replay schema, THEN THE Replay_Reader SHALL exclude only that replay record with a deterministic machine-readable reason.
15. THE Replay_Writer SHALL accept raw or partially valid records, SHALL serialize them as sorted-key UTF-8 JSON, and SHALL return, alongside the payload, every per-record observation exclusion and reason it applied; IF the Replay_Writer would drop an observation without reporting it, THEN it SHALL instead reject the complete record. Silent thinning is prohibited at the write scope as well as the read scope.
16. WHEN the Replay_Writer serializes a valid replay record and the Replay_Reader parses the result, THE parsed record SHALL equal the normalized input record by value.
17. WHEN equivalent valid replay records differ only in unordered input presentation, THE Observation_Adapter SHALL normalize them to equal records by value.
18. THE Localization_System SHALL treat a round-trip inequality under 2.16 as an implementation defect surfaced by tests, not as a record-level exclusion reason.
19. THE Pilot_Harness SHALL use stored keypoint replays for each named Acceptance_Site.
20. THE Pilot_Harness SHALL exclude any site absent from `AcceptanceProfile.acceptance_sites` from acceptance evidence.
21. THE Pilot_Harness SHALL replay stored keypoints without rerunning Observation_Provider inference.
22. WHEN provider labels enter hypothesis generation, THE Pose_Optimizer SHALL treat the labels as candidate evidence rather than confirmed correspondence truth.
23. THE Pose_Optimizer SHALL retain provider labels as candidate evidence without promotion to confirmed correspondence truth at any confidence value.

### Requirement 3: Optimize Pose in CCTV Image Space

**User Story:** As a localization user, I want pose estimated against the original image evidence, so that projection geometry and uncertain cue heights are represented coherently.

#### Acceptance Criteria

1. WHEN the Pose_Optimizer evaluates a Pose_Hypothesis, THE Calibrated_Forward_Model SHALL transform the applicable Vehicle_Template points using only the candidate planar position, heading, and nuisance variables authorized by the frozen Calibration_Profile and Nuisance_Profile.
2. WHEN the Pose_Optimizer evaluates a Pose_Hypothesis, THE Calibrated_Forward_Model SHALL project each transformed template point directly into CCTV image coordinates measured in pixels.
3. WHEN a predicted template point has a proposed correspondence, THE Pose_Optimizer SHALL compute the residual directly between predicted and observed CCTV pixel coordinates.
4. THE Pose_Optimizer SHALL refine Pose_Hypotheses by minimizing the frozen robust pixel-space reprojection objective.
5. THE Pose_Optimizer SHALL derive every Authoritative_Position from the selected optimized Pose.
6. THE Pose_Optimizer SHALL derive every accepted heading from the selected optimized Pose using the preserved heading convention.
7. WHILE the Pose_Optimizer performs hypothesis generation, refinement, scoring, deduplication, or selection, THE Pose_Optimizer SHALL exclude independently inverse-lifted per-keypoint ground-plane targets from estimator inputs and objectives.
8. WHILE the Pose_Optimizer performs hypothesis generation, refinement, scoring, deduplication, or selection, THE Pose_Optimizer SHALL exclude projected-point Procrustes from estimator inputs and objectives.
9. WHILE the Pose_Optimizer performs hypothesis generation, refinement, scoring, deduplication, or selection, THE Pose_Optimizer SHALL exclude RoleConstraintGraph inputs, constraints, scores, and decisions.
10. WHEN synthetic Image_Observations are generated by the Calibrated_Forward_Model from an in-domain Pose and the frozen minimum Support_Set, rank, conditioning, uncertainty, and uniqueness gates pass, THE Pose_Optimizer SHALL recover an equivalent Pose within the frozen synthetic position and heading tolerances.
11. IF a synthetic case fails a frozen support, observability, conditioning, uncertainty, or uniqueness gate, THEN THE Pose_Optimizer SHALL classify the synthetic case as ineligible for recovery acceptance rather than count the case as a successful recovery.

### Requirement 4: Bound Height and Calibration Nuisance Inputs

**User Story:** As an accuracy reviewer, I want physical uncertainty represented explicitly, so that no cue family receives unsupported geometric certainty.

#### Acceptance Criteria

1. THE Cue_Evidence_Profile SHALL assign every Ground_Contact_Cue the finite Cue_Height_Interval `[0, 0]`.
2. THE Cue_Evidence_Profile SHALL assign every non-ground Cue_Family a finite evidence-supported Cue_Height_Interval within the frozen physical bounds.
3. IF a non-ground Cue_Family lacks documented evidence for a fixed height, THEN THE Cue_Evidence_Profile SHALL assign the Cue_Family a Cue_Height_Interval whose upper bound is greater than its lower bound.
4. THE Nuisance_Profile SHALL define a finite closed lower and upper bound for every calibration quantity varied by the Pose_Optimizer.
5. THE Nuisance_Profile SHALL define a finite closed lower and upper bound for every vehicle dimension varied by the Pose_Optimizer.
6. WHEN the Pose_Optimizer evaluates a Pose_Hypothesis, THE Pose_Optimizer SHALL constrain every nuisance value to the applicable closed Nuisance_Profile interval.
7. THE Pose_Optimizer SHALL propagate Cue_Height_Interval uncertainty into refinement or Observability_Diagnostics.
8. THE Pose_Optimizer SHALL propagate varied calibration uncertainty into refinement or Observability_Diagnostics.
9. WHERE wheel-seeded initialization is enabled (default true) AND a sufficient Ground_Contact_Cue subset passes the frozen evidence and geometry checks, THE Pose_Optimizer SHALL use `h=0` wheel geometry for the first initialization and generate a Wheel_Seeded_Hypothesis before non-wheel alternatives.
10. WHERE non-wheel-seeded initialization is enabled (default true) AND sufficient non-ground observations pass the frozen evidence and geometry checks, THE Pose_Optimizer SHALL generate a Non_Wheel_Seeded_Hypothesis regardless of wheel presence, visibility, support, or outlier status.
11. WHERE both seed classes are enabled AND Wheel_Seeded_Hypotheses and Non_Wheel_Seeded_Hypotheses pass the frozen validity rules, THE Pose_Optimizer SHALL keep both seed classes eligible for scoring and selection.
12. IF Ground_Contact_Cues are rejected as outliers, THEN THE Pose_Optimizer SHALL continue generation, refinement, scoring, and selection for valid Non_Wheel_Seeded_Hypotheses.
13. IF every wheel-seeded and non-wheel-seeded hypothesis fails the frozen validity rules, THEN THE Pose_Optimizer SHALL return a Rejected_Result whose decisive reason is chosen by the frozen precedence over all recorded hypothesis-level failures; `insufficient_valid_hypothesis` is decisive only when no other listed reason was recorded (for example zero hypotheses generated or every path `minimal_seed_failed`).
14. WHERE the Cue_Evidence_Profile supports glass, windshield, roof, mirror, or another documented Cue_Family for the applicable site and view, THE Pose_Optimizer SHALL permit the supported Cue_Family to contribute to hypothesis generation and scoring.
15. THE Pose_Optimizer SHALL exclude `wheel_only` from the estimator-mode contract.
16. THE Pose_Optimizer SHALL exclude `wheel_weighted` from the estimator-mode contract; a wheel-weighted estimator is permitted only as a Diagnostic_Candidate under Requirement 12, implemented outside the Pose_Optimizer call graph.
17. THE Pose_Optimizer SHALL exclude wheel count as a sufficient condition for an Accepted_Result.
18. THE Pose_Optimizer SHALL retain visible wheel count only as a diagnostic value.

### Requirement 5: Generate and Compare Multiple Explicit Hypotheses

**User Story:** As an evaluator, I want semantic and geometric ambiguity represented as competing hypotheses, so that one detector labeling cannot silently determine pose.

#### Acceptance Criteria

1. THE Acceptance_Profile SHALL freeze a finite maximum generated-hypothesis count per replay record.
2. WHEN sufficient labeled observations exist, THE Pose_Optimizer SHALL include a Normal_Semantics_Hypothesis path in the authorized hypothesis combinations.
3. WHEN the frozen ambiguity trigger identifies plausible front/rear reversal, THE Pose_Optimizer SHALL include a Reversed_Semantics_Hypothesis path in the authorized hypothesis combinations.
4. WHEN the frozen ambiguity trigger identifies a plausible 180-degree pose alternative, THE Pose_Optimizer SHALL include the 180-degree alternative as a distinct semantic path.
5. WHEN the Cue_Evidence_Profile authorizes multiple robust cue subsets, THE Pose_Optimizer SHALL include each authorized cue subset in the authorized hypothesis combinations.
6. WHERE wheel-seeded initialization is enabled (default true) AND sufficient Ground_Contact_Cues exist, THE Pose_Optimizer SHALL include Wheel_Seeded_Hypotheses in the authorized hypothesis combinations.
7. WHERE non-wheel-seeded initialization is enabled (default true) AND sufficient non-ground evidence exists, THE Pose_Optimizer SHALL include Non_Wheel_Seeded_Hypotheses in the authorized hypothesis combinations.
8. WHEN authorized semantic paths, cue subsets, and seed classes exist, THE Pose_Optimizer SHALL cross the applicable semantic paths, cue subsets, and seed classes under the frozen finite hypothesis budget.
9. IF the authorized cross product exceeds the frozen hypothesis budget, THEN THE Pose_Optimizer SHALL apply the frozen deterministic budget-allocation rule and record every omitted combination with reason `hypothesis_budget_exceeded`.
10. THE Pose_Optimizer SHALL score every valid Pose_Hypothesis with the same frozen Robust_Reprojection_Score definition and parameter values.
11. THE Pose_Optimizer SHALL record semantic path, correspondence mapping, cue subset, seed class, initialization source, nuisance values, support, score, and rejection reason for every evaluated Pose_Hypothesis.
12. THE Pose_Optimizer SHALL record one terminal path state for every authorized semantic-path, cue-subset, and seed-class combination, including generated, invalid, refined, scored, merged, rejected, selected, or budget-excluded.
13. WHEN two optimized hypotheses represent the same pose within the frozen equivalence tolerances, THE Pose_Optimizer SHALL merge the hypotheses by the frozen permutation-invariant equivalence rule before computing Hypothesis_Margin.
14. WHEN hypotheses are merged, THE Pose_Optimizer SHALL preserve the provenance and terminal path state of every merged initialization, cue subset, seed class, and semantic path.
15. WHEN provider semantics conflict with a lower-scoring supported hypothesis, THE Pose_Optimizer SHALL retain both interpretations in diagnostics.
16. WHEN two valid unique hypotheses have equal comparison values within the frozen ambiguity tolerance AND their maximum pairwise position distance exceeds `position_ambiguity_tolerance_m` (frozen, default `0.25` m, inclusive at the boundary, and never greater than half the median-error Minimum_Effect_Of_Interest), THE Pose_Optimizer SHALL return a Rejected_Result with reason `ambiguous_equal_score`.
17. WHEN equal-score hypotheses are serialized for diagnostics, THE Pose_Optimizer SHALL apply the frozen canonical diagnostic order without using the order to authorize a pose.
18. IF no Pose_Hypothesis satisfies the frozen support and validity rules, THEN THE Pose_Optimizer SHALL return a Rejected_Result whose decisive reason follows the rule of Requirement 4.13.
19. WHEN two or more valid unique hypotheses are tied within the frozen ambiguity tolerance AND their maximum pairwise position distance is within `position_ambiguity_tolerance_m`, THE Pose_Optimizer SHALL return an Accepted_Result in Position_Equivalent_Ambiguity: THE Authoritative_Position SHALL be the position of the lowest-score canonical representative rather than an average of the tied poses, THE heading SHALL be null with `heading_status='ambiguous'`, THE reported position uncertainty SHALL include the within-cluster position dispersion, and THE result SHALL be Rejected if that combined uncertainty then reaches the frozen uncertainty boundary.
20. IF the tied hypotheses form two or more position clusters separated by more than `position_ambiguity_tolerance_m`, THEN THE Pose_Optimizer SHALL return a Rejected_Result with reason `ambiguous_equal_score` regardless of heading agreement.

### Requirement 6: Enforce Deterministic Robustness, Conditioning, and Ambiguity Gates

**User Story:** As a downstream user, I want outliers and non-identifiable poses rejected explicitly, so that a numerically returned pose is not mistaken for a trustworthy localization.

#### Acceptance Criteria

1. THE Acceptance_Profile SHALL freeze each permitted minimal observation configuration and the minimum support count for each configuration.
2. THE Acceptance_Profile SHALL freeze the maximum sampled-candidate count, maximum refinement-iteration count, convergence rule, and candidate-retention count.
3. THE Acceptance_Profile SHALL freeze the residual support boundary and whether residual equality at the boundary is included in the Support_Set.
4. THE Acceptance_Profile SHALL freeze the robust loss family, robust loss parameters, residual scale, support rule, and Robust_Reprojection_Score parameters.
5. THE Acceptance_Profile SHALL freeze optimization parameter units, parameter scaling, and finite lower and upper bounds.
6. THE Acceptance_Profile SHALL freeze the Jacobian definition, local-curvature definition, numeric rank tolerance, Conditioning_Metric formula and boundary, and covariance or uncertainty formula and boundaries.
7. THE Robust_Procedure SHALL generate pose candidates only from frozen minimal observation configurations.
8. THE Robust_Procedure SHALL stop candidate generation and refinement at the frozen candidate and iteration limits.
9. THE Robust_Procedure SHALL refine retained candidates with the frozen robust nonlinear pixel-space objective.
10. WHERE an evidence-equivalent robust procedure replaces minimal sampling and nonlinear refinement, THE Acceptance_Profile SHALL freeze the replacement procedure before held-out evaluation.
11. THE Robust_Procedure SHALL use the deterministic seed recorded in the Acceptance_Profile.
12. THE Robust_Procedure SHALL process normalized observations and authorized hypothesis paths in the stable order frozen in the Acceptance_Profile.
13. WHEN an Image_Observation falls outside the frozen robust support boundary under the frozen equality policy, THE Pose_Optimizer SHALL exclude the Image_Observation from the applicable Support_Set.
14. THE Pose_Optimizer SHALL record every excluded observation and exclusion residual in hypothesis diagnostics.
15. IF a Pose_Hypothesis has fewer supporting observations than the frozen minimum, THEN THE Pose_Optimizer SHALL reject the Pose_Hypothesis with reason `insufficient_support`.
16. THE Pose_Optimizer SHALL compute the frozen image-residual Jacobian and local-curvature diagnostics for every converged Pose_Hypothesis.
17. THE Pose_Optimizer SHALL report frozen rank and Conditioning_Metric values in Observability_Diagnostics.
18. THE Pose_Optimizer SHALL report Pose covariance or bounded position and heading uncertainty under the frozen formula in Observability_Diagnostics.
19. IF the optimized system fails the frozen rank requirement, THEN THE Pose_Optimizer SHALL reject the Pose_Hypothesis with reason `unobservable_pose`.
20. IF the Conditioning_Metric reaches or exceeds the frozen rejection boundary, THEN THE Pose_Optimizer SHALL reject the Pose_Hypothesis with reason `ill_conditioned_pose`.
21. IF Pose uncertainty reaches or exceeds a frozen rejection boundary, THEN THE Pose_Optimizer SHALL reject the Pose_Hypothesis with reason `pose_uncertainty_exceeded`.
22. WHEN the initial unique valid hypothesis set contains exactly one Pose_Hypothesis, THE Pose_Optimizer SHALL evaluate selection without requiring a Hypothesis_Margin after later gate evaluation.
23. WHEN the initial unique valid hypothesis set contains at least two Pose_Hypotheses, THE Pose_Optimizer SHALL require the frozen Hypothesis_Margin over the next-best unique valid hypothesis even if later gate evaluation rejects all but one hypothesis.
24. IF the selected hypothesis lacks the required frozen Hypothesis_Margin, THEN THE Pose_Optimizer SHALL return a Rejected_Result with reason `ambiguous_hypotheses`.
25. IF optimization produces a non-finite parameter, prediction, residual, derivative, score, covariance, or uncertainty value, THEN THE Pose_Optimizer SHALL return a Rejected_Result with reason `non_finite_optimization`.
26. IF optimization fails the frozen convergence rule, THEN THE Pose_Optimizer SHALL reject the Pose_Hypothesis with reason `optimization_not_converged`.
27. THE Acceptance_Profile SHALL freeze a total precedence order for every decisive rejection reason with `insufficient_support` at the highest precedence.
28. WHEN multiple required rejection gates fail, THE Pose_Optimizer SHALL report as decisive the failed reason with highest frozen precedence and retain the remaining failures as diagnostics.
29. WHEN a required rejection gate fails, THE Pose_Optimizer SHALL exclude tie-breakers and diagnostic order from changing the Rejected_Result into an Accepted_Result.
30. WHEN identical replay records, Acceptance_Profile, code revision, and runtime dependency identities are used, THE Pose_Optimizer SHALL reproduce exactly the normalized observations, hypothesis path states, selected hypothesis, Pose values, Support_Set, status, decisive reason, and diagnostics compared by value.
31. THE Pose_Optimizer SHALL permit non-decisive diagnostic reason codes on a valid Pose_Hypothesis without changing the hypothesis validity state.
32. THE Acceptance_Profile SHALL freeze the Validity_Gate_Set that forms the initial unique valid hypothesis set; for the MVP it is exactly {support, non-finite, convergence}, and rank, conditioning, uncertainty, and spread gates are evaluated on the selected representative after margin latching.
33. THE Acceptance_Profile SHALL freeze the robust loss as applied per scalar residual component (SciPy `least_squares` semantics) for the refinement objective, the Robust_Reprojection_Score, and the observability weights alike, so that one definition governs all three; image-space rotation invariance of the loss is explicitly not an MVP property, and the support rule remains per observation on `r_j = ||p_j - y_j||`.
34. WHEN a converged Pose_Hypothesis has numeric rank zero, THE Pose_Optimizer SHALL report `unobservable_pose`, SHALL report the Conditioning_Metric as null rather than a sentinel value, and SHALL NOT evaluate the `ill_conditioned_pose` gate for that hypothesis.

### Requirement 7: Preserve Coordinate Safety and Propagate Status Downstream

**User Story:** As a scene consumer, I want rejected localizations unable to influence spatial outputs, so that diagnostics cannot become accidental authority.

#### Acceptance Criteria

1. WHEN the Pose_Optimizer returns an Accepted_Result, THE Localization_System SHALL set usability to true, provide a finite Authoritative_Position, and set Diagnostic_Position to null; the heading MAY be null when `heading_status='ambiguous'` and a null heading SHALL NOT invalidate the Accepted_Result.
2. WHEN the Pose_Optimizer returns a Rejected_Result, THE Localization_System SHALL set usability to false and Authoritative_Position to null.
3. WHEN a Rejected_Result retains a finite fitted coordinate, THE Localization_System SHALL store the fitted coordinate only as a Diagnostic_Position.
4. IF a localization record combines an accepted status with unusable state, a null or non-finite Authoritative_Position, or a non-null Diagnostic_Position, THEN THE Localization_System SHALL reject the new record with reason `inconsistent_coordinate_state` and preserve every previously emitted output record unchanged.
5. IF a localization record combines a rejected status with usable state or a non-null Authoritative_Position, THEN THE Localization_System SHALL reject the new record with reason `inconsistent_coordinate_state` and preserve every previously emitted output record unchanged.
6. THE Localization_System SHALL record status, usability, decisive gate, and machine-readable reason for every localization attempt.
7. THE Localization_System SHALL propagate status, usability, Authoritative_Position, and Diagnostic_Position through replay output and compatibility mappings.
8. WHEN a Downstream_Consumer receives an Accepted_Result, THE Downstream_Consumer SHALL use only Authoritative_Position for spatial computation.
9. WHEN a Downstream_Consumer receives a Rejected_Result, THE Downstream_Consumer SHALL exclude the result from enrichment position, velocity, scene extent, interpolation, collider, and collision geometry.
10. THE Downstream_Consumer SHALL exclude Diagnostic_Position from every spatial computation.
11. THE Localization_System SHALL permit Diagnostic_Position in debugging visualization and non-spatial quality analysis.
12. WHEN a rejected or missing localization interrupts a Real_Track_ID sequence, THE Downstream_Consumer SHALL terminate the current velocity and interpolation segment at the last preceding Accepted_Result.
13. WHILE a Real_Track_ID sequence is interrupted by rejected or missing localization, THE Downstream_Consumer SHALL exclude velocity propagation and positional interpolation across the interruption.
14. WHEN a Downstream_Consumer reports accepted and rejected records, THE Downstream_Consumer SHALL group counts by status and decisive reason.
15. WHEN compatibility normalization reads a legacy record, THE Localization_System SHALL apply the explicit Legacy_Status_Policy of Requirement 1.19, recorded by identity in the Acceptance_Profile when one exists.
16. IF a legacy record lacks enough information to assign authoritative safety, THEN THE Localization_System SHALL classify the legacy coordinate as diagnostic-only.
17. WHEN `tools/build_scene.py` scans a track, THE scene builder SHALL treat any object lacking a non-null `position_m` derived from an Authoritative_Position (new contract or `legacy-localize-v1` policy) as missing, SHALL never read `diagnostic_position_sat_px`, and SHALL copy `localization_counts` (per collider track: accepted, rejected by reason, missing) into `scene.json` provenance.
18. WHEN a collider track in the Scene_Export_Contract is interrupted by more than `scene_export.max_gap_frames` (default `5`) consecutive rejected or missing samples, THE scene builder (`tools/build_scene.py`, sole owner of segmentation) SHALL split the track into segments, SHALL select the segment containing the `--source-collision` frame, SHALL refuse the build when that frame falls inside a gap for any collider (a scene whose collision moment is not covered by both colliders cannot support a collision conclusion; `--diagnostic-scene` may still produce a build, which SHALL be marked `diagnostic_only: true` in `scene.json` and SHALL NOT be used for any collision claim), SHALL record the selected `segment: {start_frame, end_frame}` per collider in `scene.json`, and SHALL never bridge samples across a segment boundary; the Three.js player receives one contiguous segment per collider and is otherwise unchanged. This segment rule is distinct from the velocity/interpolation gap rule of 7.12–7.13, which breaks at every rejected or missing sample.
19. IF a selected collider segment's accepted-sample share is below `scene_export.min_accepted_share` (default `0.5`), THEN the scene builder SHALL refuse the build unless `--allow-low-pass-rate` is given, and SHALL print the share and the dominant rejection reason.

### Requirement 8: Restrict Motion Evidence to Genuine Tracks

**User Story:** As an evaluator, I want temporal evidence based only on genuine identities, so that frame-local display IDs cannot create false motion support or invalid uncertainty estimates.

#### Acceptance Criteria

1. THE Observation_Adapter SHALL distinguish Real_Track_ID from Pseudo_Track_ID in every normalized record.
2. IF an identifier is constructed from a frame-local detection index in the `500+` range, THEN THE Observation_Adapter SHALL classify the identifier as a Pseudo_Track_ID.
3. IF an identifier has missing or inconsistent tracker name, tracker version, Source_Sequence, association provenance, or cross-frame evidence, THEN THE Observation_Adapter SHALL classify the identifier as a Pseudo_Track_ID.
4. WHEN an identifier has consistent tracker name, tracker version, Source_Sequence, association provenance, and occurrence in more than one frame, THE Observation_Adapter SHALL classify the identifier as a Real_Track_ID regardless of numeric range.
5. THE Pilot_Harness SHALL exclude every Pseudo_Track_ID from track counts, track clustering, track-clustered intervals, motion metrics, power calculations, bootstrap clusters, and partition grouping.
6. THE Pilot_Harness SHALL require tracker name, tracker version, Source_Sequence, association provenance, and more-than-one-frame evidence for every Real_Track_ID used by the pilot.
7. IF a claimed Real_Track_ID occurs in only one frame, THEN THE Pilot_Harness SHALL reclassify the identity as a Pseudo_Track_ID with reason `unverified_track_identity`.
8. WHERE Motion_Tie_Breaker is explicitly enabled in the Acceptance_Profile, THE Pose_Optimizer SHALL compute motion diagnostics only from Real_Track_ID motion that passes the frozen duration, displacement, and course-stability rules.
9. WHEN valid unique hypotheses are tied within the frozen ambiguity tolerance, THE Pose_Optimizer SHALL preserve the required ambiguity rejection regardless of Motion_Tie_Breaker output.
10. THE Motion_Tie_Breaker SHALL exclude every Rejected_Result and every Pseudo_Track_ID from motion computation.
11. WHERE Motion_Tie_Breaker is disabled, THE Pose_Optimizer SHALL complete hypothesis evaluation without temporal evidence.
12. WHERE the Acceptance_Profile permits a named non-track analysis, THE Pilot_Harness SHALL permit a frame-local detection without a Real_Track_ID only in that named non-track analysis.
13. THE Pilot_Harness SHALL exclude a frame-local detection without a Real_Track_ID from acceptance metrics, clustered uncertainty, power, motion, and partition evidence.
14. THE replay producer (`scripts/eval_haware_replay.py` and `trafficlab/io/replay_writer.py`) SHALL emit, for every tracker-matched detection, `tracker_name`, `tracker_version` (library version plus content identity of the tracker configuration), `source_sequence` (video path plus content identity), and `association_provenance` (the bbox-matching rule and its threshold), so that the one-way importer can classify ByteTrack identities as Real_Track_ID; synthesized `500+` identifiers remain frame-local Pseudo_Track_IDs.

### Requirement 9: Establish Independent Evidence and Disjoint Partitions

**User Story:** As an accuracy reviewer, I want independent references and leak-free partitions, so that pilot and held-out results measure localization rather than circular agreement.

#### Acceptance Criteria

1. THE Pilot_Harness SHALL require exactly one independently created Independent_Ground_Truth match for each Eligible_Detection used in position-error metrics.
2. THE Pilot_Harness SHALL record site, frame identity, detection identity, Real_Track_ID, Reference_Point conformance (annotated point identity and, where the annotated point is not the Reference_Point itself, the GT_Annotation_Protocol conversion version used), coordinates, units, calibration identity, source provenance, annotator provenance, independence attestation, GT_Annotation_Protocol version, annotation medium, repeat-annotation group, and uncertainty for each Independent_Ground_Truth record.
3. THE Pilot_Harness SHALL express Independent_Ground_Truth coordinates as Reference_Point coordinates in the Metric_Frame, frozen in the pre-outcome per-site ground-truth validation policy and carried unchanged into the Acceptance_Profile.
4. IF ground-truth creation used a baseline output, candidate output, Haware coordinate, Haware overlay, or derived localization artifact, THEN THE Pilot_Harness SHALL exclude the complete matching group with reason `ground_truth_contamination`; the frozen CalibrationSnapshot identified in the Acceptance_Profile is a permitted GT-creation input and is not a derived localization artifact.
5. IF ground-truth lineage, source provenance, annotator provenance, or independence attestation is missing or inconsistent, THEN THE Pilot_Harness SHALL exclude the complete matching group with reason `ground_truth_independence_unverified`.
6. IF a ground-truth coordinate or uncertainty value is missing, non-finite, or outside the frozen eligible range, THEN THE Pilot_Harness SHALL exclude the complete matching group with a machine-readable reason.
7. WHEN multiple ground-truth records share a site, frame, and detection identity, THE Pilot_Harness SHALL exclude the complete duplicate group under the frozen permutation-invariant duplicate rule.
8. WHEN zero or more than one eligible Independent_Ground_Truth match remains for a detection, THE Pilot_Harness SHALL exclude the detection from position-error metrics with reason `ground_truth_match_count_invalid`.
9. THE Pilot_Harness SHALL assign every record belonging to one Real_Track_ID to exactly one of the Pilot_Partition or Held_Out_Partition.
10. THE Pilot_Harness SHALL assign every record belonging to one Source_Sequence to exactly one of the Pilot_Partition or Held_Out_Partition.
11. IF whole-track and whole-Source_Sequence assignment cannot satisfy every frozen leakage-control rule, THEN THE Pilot_Harness SHALL fail partition creation with reason `partition_assignment_conflict` and require resolution before outcome evaluation.
12. THE Pilot_Harness SHALL record Independent_View membership for every Eligible_Detection.
13. THE Pilot_Harness SHALL freeze ground-truth match groups, eligibility, Real_Track_ID memberships, Source_Sequence memberships, Independent_View memberships, partition identities and, where a held-out Source_Sequence is not yet acquired, its acquisition rule, before reading baseline or candidate outcomes.
14. THE Pilot_Harness SHALL maintain separate ground-truth, track, Source_Sequence, view, partition, metric, and decision namespaces for each named Acceptance_Site.
15. THE Pilot_Harness SHALL exclude Diagnostic_Site records from Pilot_Feasibility_Gate and held-out acceptance decisions.
16. WHEN Diagnostic_Site records are added, removed, or reordered, THE Pilot_Harness SHALL preserve every Acceptance_Site decision exactly.
17. THE Pilot_Harness SHALL evaluate each named Acceptance_Site independently.
18. THE Pilot_Harness SHALL exclude pooled cross-site metrics from overriding a failed or insufficient site result.
19. IF detected ground-truth contamination cannot be excluded from the applicable matching group, THEN THE Pilot_Harness SHALL halt the affected site evaluation with reason `ground_truth_contamination_exclusion_failed`.
20. THE Pilot_Harness SHALL require, at each Acceptance_Site, that the Pilot_Partition and the Held_Out_Partition contain no Source_Sequence sharing a Capture_ID (the held-out evidence must come from a different recording session, not from another span of the same capture); IF a site has fewer than two Capture_IDs, THEN THE Pilot_Harness SHALL report that site as `insufficient_data` with reason `held_out_capture_unavailable` and the per-site shortfall (currently: one checked-in capture per site). Within-capture Source_Sequence splitting is permitted only for analysis inside one partition, never to manufacture a held-out partition.
21. THE Pilot_Harness SHALL permit the Held_Out_Partition to be populated by a Capture_ID acquired after the Pilot_Partition is frozen, provided its identity is recorded in the Acceptance_Profile before any held-out outcome is read and its outcomes have never been exposed.
22. THE Pilot_Harness SHALL accept only Independent_Ground_Truth records whose recorded GT_Annotation_Protocol version equals the version frozen in the Acceptance_Profile.
23. THE Pilot_Harness SHALL derive Independent_Ground_Truth uncertainty as a measured band-level quantity: the RMS disagreement over the repeat-annotated subset of each `(site, scene_region)` band is that band's `annotation_uncertainty_m`, every record in the band inherits it, and a repeat-annotated record additionally carries its own observed disagreement as `record_disagreement_m` (diagnostic). THE Pilot_Harness SHALL reject a band whose repeat-annotated subset is smaller than the frozen minimum with reason `gt_uncertainty_unmeasured`, SHALL reject any record carrying an asserted uncertainty not derived this way, and SHALL treat the frozen eligible range in 9.6 as a cap on the measured band value.
24. BEFORE population freeze, THE Pilot_Harness SHALL run the outcome-blind calibration health check of design §8 per Acceptance_Site — track-width in-band fraction `F_width >= 0.40` (primary), parallax amplification `A_max = z_cam / (z_cam - h_max) <= 1.6`, and conditional camera-height consistency `r_zcam <= 0.25` — reading only replay geometry, never ground truth, baseline, candidate, or localization status; THE Pilot_Harness SHALL classify a site failing any gate as `site_calibration_unfit`, and a site below the frozen minimum sample counts as `site_calibration_health_insufficient_data` (which is not a failure).
25. WHERE a named Acceptance_Site is `site_calibration_unfit` or lacks data availability, THE Localization_System SHALL permit substitution only by a site from the frozen candidate-site pool, only on those outcome-independent grounds, and only before any baseline or candidate outcome is read; THE Localization_System SHALL create a new Acceptance_Profile, population, and run identity when `acceptance_sites` changes, and SHALL exclude any substitution justified by an observed effect, error, or coverage value.
26. THE Pilot_Harness SHALL admit Independent_Ground_Truth produced by the calibration-independent medium (satellite or surveyed references) for both absolute-accuracy reporting and effect estimation, and SHALL admit GT produced by the calibration-conditional medium (CCTV wheel-contact annotation lifted through the frozen CalibrationSnapshot) for effect estimation and feasibility only.
27. WHEN any Acceptance_Site uses calibration-conditional GT, THE Pilot_Harness SHALL mark that site's per-arm absolute error values `calibration_conditional=true`, SHALL exclude any absolute-accuracy claim and any extrapolation beyond the evaluated Calibration_Profile, and SHALL run the calibration sensitivity sweep of Requirement 9.5c before the site may return anything other than `insufficient_data`.
28. THE calibration sensitivity sweep SHALL, for every calibration perturbation in the outcome-blind frozen perturbation set (nominal, each authorized calibration parameter at each of its bounded interval endpoints one at a time, and `256` seeded Sobol samples of the bounded box), **rebuild the calibration-conditional GT and rerun both the baseline and the candidate under that perturbation** rather than reuse fixed GT or existing arm outputs, and SHALL apply the full 10.34 classification to each perturbation: `go` requires every perturbation to classify `go`; any disagreement in classification across perturbations yields `insufficient_data`; unanimous failure yields `no_go`.
29. THE calibration sensitivity sweep SHALL be exempt from the Batch_Runtime_Envelope, which bounds one production localization pass and not a frozen offline analysis.

### Requirement 10: Run the Smallest Credible Offline Pilot

**User Story:** As a project owner, I want a bounded baseline-versus-optimizer pilot, so that feasibility is established before investment in generalized platform capabilities.

#### Acceptance Criteria

1. THE Pilot_Harness SHALL run the Corrected_Legacy_Baseline and the Pose_Optimizer on the same ordered Eligible_Detections at each Acceptance_Site.
2. THE Pilot_Harness SHALL preserve the fixed pre-outcome Eligible_Detection denominator when either system returns an Accepted_Result or a Rejected_Result.
3. WHEN an Accepted_Result and matching Independent_Ground_Truth exist, THE Pilot_Harness SHALL compute planar position error in metres as the Euclidean distance in the Metric_Frame between the Authoritative_Position Reference_Point (unrounded) and the Independent_Ground_Truth Reference_Point.
4. THE Pilot_Harness SHALL report baseline and optimizer accepted counts and rejected counts at each Acceptance_Site.
5. THE Pilot_Harness SHALL report, at each Acceptance_Site, (a) each arm's median and nearest-rank p90 planar position error over its own Accepted_Result set, labelled descriptive and non-comparable across arms, (b) both arms' median and nearest-rank p90 planar position error over the Paired_Accepted_Set, and (c) Usable_Coverage; error statistics are pooled over Eligible_Detections per site, and per-Real_Track_ID median error is additionally reported as a diagnostic.
6. THE Pilot_Harness SHALL define median-error and p90-error effects as candidate minus baseline computed over the Paired_Accepted_Set, where a negative value denotes lower candidate error.
7. THE Pilot_Harness SHALL define Usable_Coverage effect as candidate minus baseline, where a positive value denotes higher candidate coverage.
8. THE Pilot_Harness SHALL report the signed median-error, p90-error, and Usable_Coverage effects at each Acceptance_Site.
9. WHEN at least `8` independent genuine Real_Track_ID clusters are present in the cluster universe applicable to an effect — tracks contributing at least one Paired_Accepted_Set detection for the error effects, all Eligible tracks for the coverage effect — THE Pilot_Harness SHALL report a whole-track cluster-bootstrap Effect_Interval for that effect; the minimum is evaluated per effect and is distinct from the evidence-derived required track count of 10.22.
10. IF an effect has fewer than `8` clusters in its applicable universe, THEN THE Pilot_Harness SHALL mark that Effect_Interval and site sufficiency as `insufficient_data`; the single permitted interval method is fixed by 10.38.
11. THE Pilot_Harness SHALL report the number of independent genuine Real_Track_ID clusters represented at each Acceptance_Site.
12. THE Pilot_Harness SHALL report Eligible_Detection coverage by Independent_View at each Acceptance_Site.
13. THE Pilot_Harness SHALL report ground-truth uncertainty distribution at each Acceptance_Site.
14. THE Pilot_Harness SHALL report selected optimizer outcomes separately by Wheel_Seeded_Hypothesis and Non_Wheel_Seeded_Hypothesis provenance.
15. THE Pilot_Harness SHALL run a full optimizer configuration, a wheel-seeded-initialization-disabled ablation, and a non-wheel-seeded-initialization-disabled ablation at each Acceptance_Site.
16. WHEN the wheel-seeded-initialization-disabled ablation is compared with the full optimizer, THE Pilot_Harness SHALL vary only the `wheel_seeded_enabled` setting of the optimizer contract.
17. WHEN the non-wheel-seeded-initialization-disabled ablation is compared with the full optimizer, THE Pilot_Harness SHALL vary only the `non_wheel_seeded_enabled` setting of the optimizer contract; production and default configurations SHALL keep both settings enabled.
18. THE Pilot_Harness SHALL preserve the same replay inputs, candidate parameters, robust score, support rules, seed, and metric definitions across the full optimizer and both ablations.
19. THE Pilot_Harness SHALL record candidate configuration, Calibration_Profile, Cue_Evidence_Profile, Nuisance_Profile, replay identity, baseline identity, code revision, runtime dependency identities, and deterministic seed for every pilot run.
20. THE Pilot_Harness SHALL freeze the Pilot_Statistics_Method (power-analysis method, confidence level, clustering unit, effect definitions, methodological validity minimum of clusters, and the feasibility rule shape), the Minimum_Effect_Of_Interest for each required effect with its written justification, and the sufficiency decision rule before reading baseline or candidate outcomes.
21. THE Pilot_Harness SHALL derive pilot data-sufficiency findings from observed independent-track coverage, Independent_View coverage (including at least one near-field and one far-field `scene_region` band each holding no fewer than the methodological validity minimum of clusters), ground-truth uncertainty, effect variance, the frozen Minimum_Effect_Of_Interest, and the frozen power-analysis method.
22. THE Pilot_Harness SHALL derive required sample size and genuine-track coverage from pilot-observed track-clustered effect variance and the frozen Minimum_Effect_Of_Interest rather than from the observed effect estimate or fixed preclaimed counts (this does not preclude the fixed methodological validity minimum of 10.9).
23. THE Pilot_Harness SHALL derive median-error and p90-error thresholds from Pilot_Partition evidence rather than fixed `5%` or `2%` improvement values.
24. THE Pilot_Harness SHALL derive Usable_Coverage thresholds from Pilot_Partition evidence rather than fixed `5%` or `2%` allowance values.
25. THE Pilot_Harness SHALL classify the Pilot_Feasibility_Gate as `no_go` when either Acceptance_Site fails the frozen pilot data-sufficiency rule.
26. THE Pilot_Harness SHALL classify the Pilot_Feasibility_Gate as `no_go` when pilot effect estimates and Effect_Intervals fail the frozen feasibility decision rule.
27. WHEN the Pilot_Feasibility_Gate is `no_go`, THE Pilot_Harness SHALL report both evidence gaps and failed feasibility conditions.
28. WHEN both sites satisfy the frozen pilot sufficiency and feasibility rules, THE Pilot_Harness SHALL classify the Pilot_Feasibility_Gate as `go`.
29. THE Pilot_Harness SHALL treat selective-risk analysis as diagnostic rather than a required MVP acceptance gate; a Paired_Accepted_Set comparison is a fixed-population paired comparison and is not selective-risk analysis.
30. WHEN the evidence inventory contains only current checked-in data, THE Pilot_Harness SHALL classify final acceptance evidence as `insufficient_data`.
31. WHEN the evidence inventory contains only current checked-in data, THE Pilot_Harness SHALL exclude a claim of proven localization improvement.
32. THE Pilot_Harness SHALL require a validated Real_Track_ID for every Eligible_Detection at both Acceptance_Sites.
33. THE Pilot_Harness SHALL report Paired_Accepted_Set size, its share of each arm's accepted count, and its share of the fixed Eligible_Detection denominator, at each Acceptance_Site.
34. THE frozen feasibility rule SHALL classify the median-error Effect_Interval `[L, U]` against the Minimum_Effect_Of_Interest by this trichotomy: `U <= -MEI` is `go` (superiority by the material margin — this subsumes `U < 0`, so no separate superiority condition exists); `L > -MEI` is `no_go` (precise but immaterial, and this covers an interval lying entirely above zero); `L <= -MEI < U` is `insufficient_data` (the interval straddles the decision boundary). Site feasibility additionally requires Usable_Coverage non-inferiority (Effect_Interval lower bound above minus the pilot-derived allowance of 10.24) and the sufficiency rule of 10.21. THE p90-error effect SHALL be reported as secondary and SHALL NOT gate any decision. Pilot `go` requires both named Acceptance_Sites (10.28).
35. THE pilot report SHALL show each arm's error-versus-coverage operating point and SHALL print the cluster count and replicate count next to every Effect_Interval.
36. THE Pilot_Harness SHALL report achieved power at the frozen Minimum_Effect_Of_Interest, never at the observed effect.
37. THE Pilot_Harness SHALL derive per-site held-out thresholds by the frozen rule of the Pilot_Statistics_Method: the median-error threshold is the pilot Effect_Interval upper bound, and the held-out site passes when its median-error interval satisfies the same trichotomy of 10.34 at the frozen MEI and its point estimate is at or below the threshold; the coverage allowance is the half-width of the pilot coverage-effect Effect_Interval. THE Acceptance_Profile SHALL NOT freeze a p90-error threshold.
38. THE Pilot_Harness SHALL compute every Effect_Interval by one method only: `4096` seeded whole-track bootstrap resamples that draw `n_tracks` Real_Track_IDs with replacement and equal probability, carry every detection of a drawn track (a track drawn twice contributes its detections twice), and **recompute the detection-level statistic on each resample** rather than aggregating per-track effects; the interval is the nearest-rank percentile interval at the frozen confidence level. Exact sign-flip enumeration is not used, because inverting it into an interval is undefined.

## Held-Out Acceptance Requirements

### Requirement 11: Freeze Acceptance Before Held-Out Evaluation

**User Story:** As an independent reviewer, I want thresholds fixed before held-out outcomes are visible, so that the final result is not tuned to the evaluation set.

#### Acceptance Criteria

1. WHEN the Pilot_Feasibility_Gate is `go`, THE Pilot_Harness SHALL extend the Acceptance_Profile with per-site held-out thresholds and commit it before reading any Held_Out_Partition outcome.
2. THE Acceptance_Profile SHALL identify the exact Pose_Optimizer code revision, candidate configuration, Calibration_Profile, Cue_Evidence_Profile, Nuisance_Profile, replay schema, robust procedure, runtime dependency identities, and deterministic seed evaluated on the Held_Out_Partition.
3. THE Acceptance_Profile SHALL freeze per-site median-error (Paired_Accepted_Set) and Usable_Coverage thresholds derived from Pilot_Partition evidence before reading any held-out outcome; p90-error is reported, never thresholded (Requirement 10.34).
4. THE Acceptance_Profile SHALL freeze required Effect_Interval decision rules before reading any held-out outcome.
5. THE Acceptance_Profile SHALL freeze conditioning, observability, uncertainty, support, spread, uniqueness, hypothesis-budget, scoring, deterministic-order, and decisive-rejection boundaries before reading any held-out outcome.
6. THE Acceptance_Profile SHALL record the pilot effect estimate, uncertainty, sufficiency result, power result at the frozen Minimum_Effect_Of_Interest, and decision rationale supporting each final threshold.
7. THE Acceptance_Profile SHALL exclude Held_Out_Partition outcomes from every threshold rationale.
8. IF any Acceptance_Site fails a frozen held-out threshold or returns `no_go` under the 10.34 trichotomy, THEN THE Pilot_Harness SHALL report the final decision as `no_go`.
9. IF no Acceptance_Site fails and any Acceptance_Site has insufficient held-out data under the frozen sufficiency rule, THEN THE Pilot_Harness SHALL report the final decision as `insufficient_data`.
10. WHEN both Acceptance_Sites satisfy every frozen held-out rule, THE Pilot_Harness SHALL report the final decision as `go`.
11. WHEN held-out conditions include both threshold failure and insufficient data, THE Pilot_Harness SHALL apply decision precedence `no_go` over `insufficient_data` over `go`.
12. THE Pilot_Harness SHALL report per-site median error and p90 error (own-set descriptive and Paired_Accepted_Set), Usable_Coverage, signed effect estimates, Effect_Intervals, genuine Real_Track_ID coverage, and Independent_View coverage for held-out evaluation.
13. THE Pilot_Harness SHALL exclude pooled metrics from overriding an Acceptance_Site result.
14. THE Pilot_Harness SHALL exclude proxy metrics from overriding an Independent_Ground_Truth result.
15. THE Pilot_Harness SHALL exclude Diagnostic_Site outcomes from every held-out decision.
16. THE Pilot_Harness SHALL read held-out outcomes only from a command that takes the git commit SHA of the committed Acceptance_Profile file as an argument, and SHALL record that SHA and the profile content digest in the held-out report.
17. THE Pilot_Harness SHALL append one entry `{profile_sha, held_out_dataset_digest, exposed_at}` to the append-only exposure ledger `evidence/haware/held_out_ledger.jsonl` before emitting any held-out outcome, and SHALL never rewrite or delete an existing entry.
18. IF the ledger already contains an entry whose `held_out_dataset_digest` equals the requested dataset and whose `profile_sha` differs from the requested SHA, THEN THE Pilot_Harness SHALL refuse the run with reason `held_out_dataset_already_exposed` and SHALL require a Held_Out_Partition whose digest is absent from the ledger.
19. WHEN the requested `(profile_sha, held_out_dataset_digest)` pair is already present in the ledger, THE Pilot_Harness SHALL reproduce the recorded decision rather than evaluate a second time.

## Diagnostic Candidate and Runtime Requirements

### Requirement 12: Run Diagnostic Candidate Arms Without Authority

**User Story:** As the owner of the earlier weighted-Procrustes proposal, I want it measured side by side under the same evidence, so that its value is settled by data rather than discarded by fiat, without ever becoming production behavior by accident.

#### Acceptance Criteria

1. THE Pilot_Harness SHALL run every Diagnostic_Candidate named in the Acceptance_Profile on the same ordered Eligible_Detections and against the same Independent_Ground_Truth as the Corrected_Legacy_Baseline and the Pose_Optimizer, at each Acceptance_Site.
2. THE Pilot_Harness SHALL report for each Diagnostic_Candidate the same per-site descriptive statistics, Paired_Accepted_Set effects against the Corrected_Legacy_Baseline, Usable_Coverage, and provenance as for the Pose_Optimizer.
3. THE Pilot_Harness SHALL exclude every Diagnostic_Candidate from the Pilot_Feasibility_Gate, from every held-out decision, and from any improvement claim.
4. THE Localization_System SHALL implement each Diagnostic_Candidate in one named module outside the Pose_Optimizer call graph (`trafficlab/measurement/haware_diagnostic_candidates.py`), SHALL exclude it from production dispatch, and SHALL classify every Diagnostic_Candidate output as non-authoritative.
5. THE MVP Diagnostic_Candidate `wheel_weighted_procrustes` SHALL reuse the Corrected_Legacy_Baseline handedness correction, template, and spread diagnostic, SHALL apply the frozen diagonal weight `w_wheel` (`PilotPolicy.diagnostic_candidate_params['wheel_weighted_procrustes']['w_wheel']`, default `4.0`) to `WHEEL_KP_IDX` in the fixed-scale Procrustes cross-covariance with weighted centroids `q̄ = Σ w_i q_i / Σ w_i`, and SHALL fall back to the unweighted full-point fit with a recorded `fallback=true` flag when `n_wheel_kp < 2`.

### Requirement 13: Bound the Background Batch Runtime

**User Story:** As the product owner, I want the whole video localized in the background within a known bound, so that hypothesis budgets are chosen against a real envelope rather than cut later under time pressure.

#### Acceptance Criteria

1. THE Acceptance_Profile SHALL freeze a Batch_Runtime_Envelope of at most `10` seconds of wall-clock per second of source video (600 s for a 60 s clip) for localizing one complete source video (all detections, all frames) with the Pose_Optimizer on the reference machine recorded in the profile as a structured record (CPU model, core count, RAM, OS, Python/NumPy/SciPy/BLAS versions) with `OMP_NUM_THREADS=OPENBLAS_NUM_THREADS=MKL_NUM_THREADS=1`, single process.
2. THE Pilot_Harness SHALL record wall-clock time, source-video duration, total detection count, and per-detection mean and p95 optimizer time for every pilot run and SHALL report `wall_s / video_s`; because pilot runs cover only Eligible_Detections, a pilot figure is an indicative lower bound and SHALL be labelled `partial_population=true`.
3. WHEN the exact candidate is frozen, THE Localization_System SHALL measure the Batch_Runtime_Envelope by localizing one complete named reference source video end to end on the reference machine — every frame and every detection, including I/O, observation normalization, frames with no detection, and process start-up — and SHALL record the measured `wall_s / video_s` in the Acceptance_Profile.
4. IF the measured full-video value exceeds the Batch_Runtime_Envelope, THEN THE Localization_System SHALL withhold production authorization with reason `runtime_envelope_exceeded` even when the held-out decision is `go`; the envelope is a production-authorization gate and never alters an accuracy metric, effect, or held-out decision.
5. WHEN a hypothesis budget or refinement limit is chosen for the Acceptance_Profile, THE Localization_System SHALL record the measured runtime that justifies it.
6. THE Localization_System SHALL impose no per-frame or real-time latency requirement anywhere in this feature.

## Scope boundary and later phases

This section replaces the former Requirements 12 and 13 (production hardening and deferred-capability governance), which were decision rules rather than testable system behaviour.

- The Pose_Optimizer is default-off and non-authoritative until the exact candidate returns held-out `go` at both named Acceptance_Sites. A `go` authorizes only the two sites named in that Acceptance_Profile; a site that was substituted out receives no production authorization. Until then the Corrected_Legacy_Baseline (through `legacy-localize-v1`) is the production path, and Optimizer_Disabled_Mode parity (Requirement 1.13–1.15) must hold.
- Production authorization is scoped to the Calibration_Profile and Cue_Evidence_Profile identities evaluated; a site without frozen profiles dispatches to the Corrected_Legacy_Baseline. Authorization additionally requires the measured full-video Batch_Runtime_Envelope (Requirement 13.3–13.4) to be met.
- The hardening review that follows a `go` verifies the compatibility mapping into `sat_coords`/`position_m` consumed by `scripts/filter_and_enrich_output.py` and `tools/build_scene.py`, disabled-mode parity, and coordinate-authority safety. It does not retune or generalize the estimator.
- Each Deferred_Capability (detector replacement or retraining, generalized learned reliability, a full multi-provider schema platform, exhaustive artifact management, calibration identification or re-estimation, temporal or multi-sensor fusion, selective-risk acceptance) is out of scope for this specification and needs its own requirements and design, motivated by a measured pilot limitation. Temporal fusion, if ever specified, must consume only Real_Track_ID inputs and must keep every single-frame Rejected_Result non-authoritative.
