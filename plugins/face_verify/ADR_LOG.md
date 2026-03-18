Face Verify ADR Log

Project
Holly plugin architecture

Owner
Jon

Status
Active

ADR-2026-03-18-01
Title
Authorization boundary

Date
2026-03-18

Status
Accepted

Supersedes
None

Superseded by
None

Decision owner
Jon

Reviewers
Holly assistant

Context
We need a clear and enforceable separation between biometric verification and authorization so policy stays centralized and auditable.

Decision
acl_rbac is the final allow or deny engine for command execution.
face_verify only emits assurance signals and reason codes. It must not directly authorize command execution.

Policy rules
- face_verify can return assurance state, score, freshness, liveness result, and reason codes.
- acl_rbac evaluates risk policy and all assurance factors, then decides allow or deny.
- Any direct allow from face_verify is ignored by policy flow.
- Deny-first precedence remains in effect.

Options considered
Option A
Make face_verify decide allow/deny for sensitive commands.
Pros
Simple plugin-local logic.
Cons
Authorization logic becomes fragmented and harder to audit.

Option B
Use acl_rbac as sole authorization gate and keep face_verify as assurance provider.
Pros
Clear separation of concerns, centralized policy, easier auditability, safer evolution.
Cons
Requires clear assurance contract integration.

Rationale
Option B chosen for policy clarity, maintainability, and security control centralization.

Security impact
Improves integrity of authorization decisions by preventing plugin-local bypass paths.
Supports fail-closed policy behavior.

Privacy and compliance impact
No direct change to biometric storage, but central policy handling simplifies governance review.

Operational impact
Policy troubleshooting is centralized in acl_rbac logs and rules.

Developer impact
Requires strict interface contract between face_verify outputs and acl_rbac inputs.

Configuration impact
No new config keys required by this decision.

Data model impact
Requires consistent assurance object fields for acl_rbac consumption.

Failure mode behavior
If face_verify is unavailable, acl_rbac applies risk policy and denies high-risk actions when assurance is missing.

Rollout plan
Adopt immediately in architecture spec and all future plugin implementation.

Test and validation plan
- Unit test that face_verify cannot independently allow sensitive command execution.
- Integration test that acl_rbac denies when assurance is missing.
- Integration test that valid assurance enables allow only through acl_rbac.

Open questions
- Final assurance object schema and reason code taxonomy.

Decision outcome summary
Authorization is centralized in acl_rbac. face_verify provides evidence, not final decisions.

References
ARCHITECTURE_SPEC.md section 5 and section 7

---

ADR-2026-03-18-05
Title
Failure mode policy by risk tier

Date
2026-03-18

Status
Accepted

Supersedes
None

Superseded by
None

Decision owner
Jon

Reviewers
Holly assistant

Context
We need deterministic behavior when face verification is unavailable so privilege escalation paths remain safe while normal operations stay usable.

Decision
Fail-closed for high-risk actions when face assurance is required and unavailable.
Medium-risk actions may proceed with RBAC policy only.
Low-risk actions may proceed with baseline session authentication.

Policy rules
- low risk: session auth is sufficient.
- medium risk: acl_rbac determines allow/deny without requiring face verification.
- high risk: requires step-up factors; if required assurance is unavailable, deny.
- critical risk: inherits high-risk fail-closed behavior unless explicitly changed by later ADR.

Options considered
Option A
Fail-closed for all privileged actions.
Pros
Maximum security consistency.
Cons
Higher operational friction and lower availability.

Option B
Tiered policy: fail-closed for high, RBAC-only for medium, session auth for low.
Pros
Balances security and usability by protecting escalation paths while preserving routine flow.
Cons
Requires clear risk classification discipline.

Rationale
Option B chosen to prevent high-risk privilege escalation without over-constraining medium and low-risk operations.

Security impact
Strong protection for escalation paths through mandatory fail-closed handling at high risk.
Maintains policy integrity by keeping decisions in acl_rbac.

Privacy and compliance impact
No direct change to biometric data handling.

Operational impact
Improves continuity for medium-risk operations during biometric backend incidents.

Developer impact
Requires stable risk-tier mapping and explicit policy checks in acl_rbac.

Configuration impact
Requires risk-tier command mapping to be defined and maintained.

Data model impact
Assurance object should include availability and freshness indicators for risk-aware policy evaluation.

Failure mode behavior
- If face backend unavailable and command is high or critical: deny.
- If command is medium: evaluate via acl_rbac without face requirement.
- If command is low: allow under valid session auth policy.

Rollout plan
Apply with risk-tier mapping rollout and validation tests.

Test and validation plan
- Integration test: high-risk command denied when face backend unavailable.
- Integration test: medium-risk command still gated by acl_rbac and can proceed when allowed.
- Integration test: low-risk command proceeds under valid session auth.

Open questions
- Final list of medium versus high-risk commands.
- Whether any critical commands require additional hard controls beyond high-risk behavior.

Decision outcome summary
Adopt tiered failure behavior: fail-closed for high-risk escalation paths, RBAC-only for medium, and session-auth baseline for low.

References
ARCHITECTURE_SPEC.md section 7 and section 11

---

ADR-2026-03-18-06
Title
Step-up freshness TTL

Date
2026-03-18

Status
Accepted

Supersedes
None

Superseded by
None

Decision owner
Jon

Reviewers
Holly assistant

Context
We need an initial step-up TTL that balances usability and security, while current hardware performance expectations are still uncertain.

Decision
Set initial face step-up TTL to 120 seconds for high-risk command execution windows.

Policy rules
- Default face verification freshness window is 120 seconds.
- High-risk commands require a valid face assurance within this window.
- TTL is intentionally provisional and will be tuned after operational measurement.

Options considered
Option A
60 seconds.
Pros
Stronger security freshness.
Cons
Higher user friction and re-verification frequency.

Option B
120 seconds.
Pros
Balanced midpoint between security and usability during early rollout.
Cons
May still be too short or too long depending on real-world latency and workflow.

Option C
300 seconds.
Pros
Lower friction.
Cons
Wider exposure window for step-up reuse.

Rationale
Option B chosen as a reasonable midpoint until hardware and workflow characteristics are validated in production-like conditions.

Security impact
Provides bounded step-up reuse window with moderate exposure.

Privacy and compliance impact
No direct change.

Operational impact
Reduces repeated prompts compared with shorter TTL while preserving manageable re-auth cadence.

Developer impact
Requires TTL config default set to 120 and policy tests aligned.

Configuration impact
Default verify_ttl_seconds should be 120.

Data model impact
Assurance records require accurate expires_at handling.

Failure mode behavior
If TTL expires, high-risk command requires fresh step-up verification before proceeding.

Rollout plan
Start with 120 seconds and review after telemetry on verification latency, user friction, and deny rates.

Test and validation plan
- Unit test for expiry boundary at 120 seconds.
- Integration test that high-risk commands deny after TTL expiry.
- Integration test that commands succeed within active TTL when other policy requirements are met.

Open questions
- Whether critical commands should use shorter TTL than high-risk defaults.

Decision outcome summary
Initial step-up TTL is set to 120 seconds as a deliberate midpoint, with planned tuning once hardware and runtime behavior are better understood.

References
ARCHITECTURE_SPEC.md section 9

---

ADR-2026-03-18-04
Title
Liveness requirement by risk tier

Date
2026-03-18

Status
Accepted

Supersedes
None

Superseded by
None

Decision owner
Jon

Reviewers
Holly assistant

Context
Face matching without liveness can be bypassed with presented photos or replay media. We need a consistent anti-spoof posture.

Decision
Liveness is required for all face verification events, regardless of risk tier.

Policy rules
- Any face verification attempt must include liveness validation.
- If liveness is unavailable, fails, or returns indeterminate, face verification fails.
- No tier-based liveness exemptions are allowed.

Options considered
Option A
Require liveness only for high and critical risk tiers.
Pros
Lower friction for lower tiers.
Cons
Leaves replay risk in lower-tier face flows.

Option B
Require liveness only for critical tier.
Pros
Simpler for most flows.
Cons
Inconsistent security model and broader spoofing surface.

Option C
Require liveness for all facial recognition.
Pros
Consistent anti-spoof baseline and reduced replay risk.
Cons
Higher implementation complexity and potential UX friction.

Rationale
Option C chosen to ensure that any use of facial recognition validates real user presence and resists static-image attacks.

Security impact
Improves integrity of biometric factor by reducing spoof and replay feasibility.

Privacy and compliance impact
May increase sensitivity of biometric processing operations; consent and transparency requirements remain mandatory.

Operational impact
Potentially higher verification latency and more challenge failures in poor camera conditions.

Developer impact
Requires liveness checks to be first-class in face_verify flow and error taxonomy.

Configuration impact
Liveness should default to required with no risk-tier override in production policy.

Data model impact
Assurance object must include liveness_status and liveness_failure_reason fields.

Failure mode behavior
If liveness subsystem is unavailable, face verification fails and any command requiring face step-up cannot proceed.

Rollout plan
Enforce from first biometric rollout; validate camera and challenge UX during shadow and pilot phases.

Test and validation plan
- Integration test: static photo replay attempt fails.
- Integration test: face match without liveness result is denied.
- Integration test: valid live challenge plus face match succeeds under policy.

Open questions
- Preferred liveness method set for low-resource hardware profiles.

Decision outcome summary
All facial recognition in Holly requires liveness. No exemptions by risk tier.

References
ARCHITECTURE_SPEC.md section 3 and section 9

---

ADR-2026-03-18-02
Title
Biometric storage policy

Date
2026-03-18

Status
Accepted

Supersedes
None

Superseded by
None

Decision owner
Jon

Reviewers
Holly assistant

Context
We need to minimize biometric privacy risk while preserving enough data for reliable verification and auditability.

Decision
Store embeddings and metadata only.
Do not store raw face images by default.

Policy rules
- Persisted biometric artifacts are limited to embeddings and required metadata.
- Raw enrollment and probe images are not retained by default.
- Any future temporary image retention requires a separate explicit ADR and environment-scoped controls.

Options considered
Option A
Store raw images plus embeddings.
Pros
Easier debugging and post-hoc model analysis.
Cons
Higher privacy risk and larger compliance burden.

Option B
Store embeddings and metadata only.
Pros
Data minimization, lower breach impact, cleaner governance posture.
Cons
Less direct forensic replay for debugging.

Rationale
Option B chosen to enforce privacy-by-design and reduce sensitive biometric data retention.

Security impact
Reduces impact radius if storage is compromised by excluding raw facial imagery.

Privacy and compliance impact
Improves compliance posture through minimization of sensitive personal data.

Operational impact
Debugging relies on logs and metrics rather than retained imagery by default.

Developer impact
Storage layer must enforce schema that excludes raw images from persistence paths.

Configuration impact
Default storage configuration should not include image retention toggles enabled.

Data model impact
Required persisted fields include embedding vector, model version, quality metrics, timestamps, and assurance metadata.

Failure mode behavior
No change to command policy; verification operates without image persistence.

Rollout plan
Apply as default policy immediately and validate through storage integration tests.

Test and validation plan
- Unit test ensuring raw image payloads are not written to persistent store.
- Integration test validating enrollment and verify succeed with embedding-only persistence.
- Compliance test verifying stored record schema contains no raw image fields.

Open questions
- Exact metadata field list and retention durations per field.

Decision outcome summary
Holly will persist only embeddings and metadata for face verification. Raw images are excluded by default.

References
ARCHITECTURE_SPEC.md section 10 and section 14

---

ADR-2026-03-18-03
Title
Threshold strategy with uncertainty band and risk-tier tuning

Date
2026-03-18

Status
Accepted

Supersedes
None

Superseded by
None

Decision owner
Jon

Reviewers
Holly assistant

Context
Face comparison scores vary by lighting, camera quality, and pose. A single hard cutoff is brittle and does not adapt well to command risk.

Decision
Use a two-threshold model with a middle uncertainty band.
Apply stricter threshold profiles for higher-impact commands.

Policy rules
- Scores above threshold_high pass.
- Scores below threshold_low fail.
- Scores between threshold_low and threshold_high are uncertain and require additional handling.
- Higher-impact commands use stricter threshold profiles than medium-impact commands.
- acl_rbac maps command risk to threshold profile selection.

Options considered
Option A
Single hard threshold.
Pros
Simple to implement and explain.
Cons
Higher false accept or false reject pressure and poor risk differentiation.

Option B
Two-threshold model with uncertainty band and risk-tier threshold profiles.
Pros
Better security-usability balance and explicit handling of ambiguous scores.
Cons
Requires policy/profile management and extra handling path.

Rationale
Option B chosen to support nuanced decisions and stricter controls for high-impact actions while keeping medium-risk workflows practical.

Security impact
Reduces false-accept risk on high-impact commands by using stricter thresholds and explicit uncertain handling.

Privacy and compliance impact
No direct change to data retention policy.

Operational impact
Uncertain-band events require fallback action paths and observability to tune thresholds.

Developer impact
Requires threshold profile configuration and acl_rbac risk-to-profile mapping.

Configuration impact
Define threshold_low and threshold_high per profile, with profile selection by command risk.

Data model impact
Verification results should persist score, selected profile, and reason code for audit and tuning.

Failure mode behavior
If score is uncertain, command is not auto-approved; policy must require retry and or additional factor based on risk profile.

Rollout plan
Start with conservative default profiles and tune using observed uncertain and failure rates.

Test and validation plan
- Unit tests for pass fail uncertain boundaries.
- Integration tests ensuring high-impact commands use stricter profile.
- Integration tests ensuring uncertain outcomes trigger policy-defined additional checks.

Open questions
- Initial numeric threshold values per profile.
- Exact uncertain-band handling sequence per risk tier.

Decision outcome summary
Holly uses a two-threshold strategy with a middle uncertainty band and stricter threshold profiles for higher-impact commands.

References
ARCHITECTURE_SPEC.md section 7 and section 9

---

ADR-2026-03-18-07
Title
Fallback policy for high-risk commands

Date
2026-03-18

Status
Accepted

Supersedes
None

Superseded by
None

Decision owner
Jon

Reviewers
Holly assistant

Context
Fallback behavior on high-risk commands can create bypass paths during biometric or liveness outages. We need a clear non-bypass rule.

Decision
High-risk commands are hard deny when required face or liveness assurance is unavailable or fails.
No fallback path is permitted for high-risk commands.

Policy rules
- If a high-risk command requires face plus liveness and either signal is unavailable, indeterminate, expired, or failed, deny.
- MFA plus RBAC is not a substitute fallback for high-risk commands.
- Deny response must clearly state hard-deny policy and required recovery action.

Options considered
Option A
Allow fallback to MFA plus RBAC for high-risk commands.
Pros
Higher availability during biometric outages.
Cons
Creates escalation bypass risk and weakens high-risk control posture.

Option B
Hard deny high-risk commands with no fallback.
Pros
Strong anti-bypass guarantee for privilege escalation paths.
Cons
Lower availability during subsystem outages.

Rationale
Option B chosen to preserve strict control over high-risk actions and prevent policy erosion via fallback paths.

Security impact
Significantly reduces privilege escalation bypass opportunities.

Privacy and compliance impact
No direct data-retention change.

Operational impact
Requires clear operator runbooks for recovery when high-risk actions are blocked.

Developer impact
Must implement deterministic hard-deny branch and explicit user-facing reason codes.

Configuration impact
High-risk policy should not expose fallback toggles in production.

Data model impact
Audit records should include deny reason codes for unavailable or failed face/liveness dependencies.

Failure mode behavior
On any missing or failed required assurance for high-risk actions, deny immediately with no alternative factor substitution.

Rollout plan
Apply immediately with policy tests and runbook messaging.

Test and validation plan
- Integration test: high-risk command denied when face backend unavailable.
- Integration test: high-risk command denied when liveness unavailable or failed.
- Integration test: MFA plus RBAC cannot override high-risk hard-deny condition.

Open questions
- Exact operator-facing remediation messages for each deny reason.

Decision outcome summary
High-risk commands are hard-deny only when required biometric assurance is not satisfied. No fallback is allowed.

References
ARCHITECTURE_SPEC.md section 7 and section 11

---

ADR-2026-03-18-08
Title
Strict audit schema

Date
2026-03-18

Status
Accepted

Supersedes
None

Superseded by
None

Decision owner
Jon

Reviewers
Holly assistant

Context
Authentication and authorization outcomes for biometric step-up need high-integrity traceability for security review, tuning, and incident response.

Decision
Adopt a strict auditing schema now, using a defined required core field set.
Schema can evolve later through new ADRs.

Policy rules
- Audit events for enrollment, verification, step-up state transitions, and policy decisions must follow the strict schema.
- Missing required fields is a schema violation and must be treated as an ingestion error.
- Schema changes require explicit versioning and ADR approval.

Required core fields
- timestamp
- subject_id
- session_id
- command
- risk_level
- decision
- reason_code
- face_score
- liveness_status
- ttl_state
- policy_version
- plugin_versions
- correlation_id

Options considered
Option A
Minimal schema initially, expand later.
Pros
Faster initial implementation.
Cons
Inconsistent records and weaker forensic value.

Option B
Strict schema from the start with required fields and versioning.
Pros
Strong audit quality, easier incident analysis, predictable downstream processing.
Cons
Higher upfront implementation discipline.

Rationale
Option B chosen to ensure reliable and consistent security evidence from first rollout.

Security impact
Improves detection, investigation, and policy-verification integrity.

Privacy and compliance impact
Requires careful control of field content to avoid accidental over-collection.

Operational impact
Enables robust dashboards and alerting with stable field contracts.

Developer impact
Requires strict event builders, validators, and test fixtures aligned to schema version.

Configuration impact
Requires audit schema version tracking and validator enforcement configuration.

Data model impact
Defines stable event record shape and versioned evolution path.

Failure mode behavior
If audit event fails schema validation, event ingestion fails and must trigger operational alerting; command policy behavior remains governed by acl_rbac and risk rules.

Rollout plan
Implement strict schema and validation in initial biometric rollout and monitor ingestion errors.

Test and validation plan
- Unit tests validating required fields for each event type.
- Integration tests confirming all face_verify and acl_rbac decision events serialize with full schema.
- Negative tests ensuring malformed events are rejected and alerted.

Open questions
- Field enum values for decision and reason_code.
- Canonical format for plugin_versions field.

Decision outcome summary
Holly adopts a strict, versioned audit schema now with required core fields, providing high-integrity traceability and controlled evolution.

References
ARCHITECTURE_SPEC.md section 13
