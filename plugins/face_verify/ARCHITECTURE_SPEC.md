Holly Face Verify Architecture Spec v1

Document status
Draft

Owner
Jon

Date
2026-03-18

Related components
auth_local, mfa_totp, face_verify, acl_rbac, audit_log, rate_limit_guardian

1. Purpose
Define the architecture for biometric face verification as a step-up assurance factor for sensitive actions in Holly.
This spec covers trust model, policy boundaries, data model, decisioning, failure behavior, security controls, and rollout.
This spec does not cover implementation details or code.

2. Scope
In scope
- Face enrollment and verification flow
- Integration contract with plugin system
- Policy evaluation for sensitive commands
- Storage and retention rules for biometric templates
- Audit and observability requirements
- Rollout and rollback strategy

Out of scope
- UI design details
- Vendor specific model tuning procedures
- Full legal review text
- Incident response runbooks

3. Trust model
Face verification proves
- The current user likely matches the enrolled template for this account
- Verification is recent and within a short TTL window
- Required liveness proves presence at verification time

Face verification does not prove
- Absolute identity
- Authorization by itself
- Safety against all spoofing attacks

4. Security principles
- Deny first for sensitive actions
- Fail closed when policy or biometric backend is unavailable
- Least privilege for all plugin operations
- Short lived step-up windows
- Minimize and protect biometric data
- Full audit trail for enrollment and verification outcomes

5. Architecture boundaries
Policy plane
- acl_rbac is the final decision point for allow or deny
- It evaluates command risk plus assurance state
- It enforces step-up requirements

Biometric plane
- face_verify performs enrollment and match
- It returns assurance signals, score, freshness, reason codes
- It does not make authorization decisions

Identity and factor plane
- auth_local handles primary identity
- mfa_totp provides second factor
- face_verify provides biometric factor and optional liveness factor

6. Shared assurance contract
Assurance object fields
- subject_id
- session_id
- factors_present list
- factor_freshness timestamps per factor
- face_score latest numeric score
- liveness_status pass fail unavailable indeterminate
- assurance_level low medium high
- expires_at
- issuer plugin id
- model_version
- reason_code for last decision

7. Command risk policy
Risk levels
- low
- medium
- high
- critical

Example policy mapping
- low requires auth_local
- medium requires auth_local plus mfa_totp
- high requires auth_local plus mfa_totp plus fresh face_verify
- critical requires auth_local plus mfa_totp plus fresh face_verify plus liveness

Policy precedence
- Explicit deny overrides allow
- Unknown policy state denies high and critical commands

8. Enrollment policy
Enrollment prerequisites
- User authenticated with auth_local and mfa_totp
- Explicit consent captured

Enrollment quality
- 3 to 5 samples minimum
- Face detected and quality above threshold
- Optional pose and lighting diversity checks

Enrollment output
- Template embedding set
- Model version
- Quality metrics summary
- Enrollment timestamp

Re-enrollment
- Allowed only after primary auth and mfa_totp
- Old template invalidated atomically
- Audit event required

9. Verification policy
Verification steps
- Detect face
- Required liveness challenge
- Generate embedding
- Compare against enrolled template
- Return outcome allow deny uncertain with score and reason code

Decision bands
- Pass above high threshold
- Fail below low threshold
- Uncertain in middle band triggers retry or extra factor

Threshold profiles by command impact
- Use risk-tier threshold profiles selected by acl_rbac.
- Higher-impact commands must use stricter threshold profiles than medium-impact commands.
- Example intent: a reboot-class command uses stricter thresholds than routine privileged operations.

Step-up TTL
- Default 120 seconds
- Critical commands may require 30 to 60 second freshness

10. Data handling and retention
Persisted data
- Embeddings and minimal metadata only
- No raw images by default

Optional data with explicit policy
- Temporary probe images for debugging with strict short retention

Retention
- Templates kept until user clears or account removal
- Verification event logs kept per security retention policy

Deletion
- face-clear removes templates and active step-up state
- Deletion is auditable and verifiable

11. Failure and degraded mode behavior
Backend unavailable
- High and critical commands denied
- Low and medium follow configured policy
- User receives actionable reason and next step

Model mismatch or corruption
- Verification fails safe
- Re-enrollment path offered after re-authentication

Timeouts
- Verification request times out deterministically
- No implicit success on timeout

12. Abuse prevention and hardening
- Rate limit verify attempts by session and subject
- Progressive cooldown after repeated failures
- Replay defense with liveness and nonce based challenges where possible
- Alerting for anomaly patterns

13. Audit and observability
Required events
- Enrollment started succeeded failed
- Verification started succeeded failed uncertain
- Step-up granted expired revoked
- Policy deny due to missing assurance
- Manual clear and re-enroll actions

Audit schema policy
- Use a strict, versioned audit schema.
- Required fields must be present for ingestion acceptance.
- Schema evolution requires explicit version bump and ADR.

Required core audit fields
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

Operational metrics
- Verify latency
- False reject trend
- Uncertain rate
- Backend error rate
- Step-up deny rate by command

14. Privacy and governance
- Explicit user consent required before enrollment
- Biometric data use limited to defined security purpose
- Access to templates restricted by role
- Data subject deletion path documented
- Region specific legal basis confirmed before production rollout

15. Configuration model
Core config keys
- provider
- model_pack
- verify_ttl_seconds
- threshold_low
- threshold_high
- require_liveness_for_risk_levels
- sensitive_commands
- max_verify_attempts
- cooldown_seconds
- store_path
- retention_policy

Environment separation
- Development settings allow fallback mode
- Production disables insecure fallback modes

16. Rollout plan
Phase 1 architecture validation
- Finalize this spec
- Freeze contract fields and reason codes

Phase 2 shadow mode
- Run biometric checks without enforcing for selected commands
- Collect scores and tune thresholds

Phase 3 controlled enforcement
- Enforce for high risk commands only
- Keep rollback switch active

Phase 4 full policy activation
- Expand to critical commands with liveness
- Remove token fallback in production

Rollback
- Single config switch reverts to non-biometric step-up path
- All rollback actions audited

17. Open decisions
- Exact command to risk mapping
- Final threshold values per camera environment
- Liveness requirement by risk tier
- Retention periods and legal review outcome
- Whether uncertain band triggers retry or mandatory mfa escalation

18. Acceptance criteria
- No authorization decisions inside face_verify plugin
- acl_rbac consumes shared assurance object only
- Deny first and fail closed confirmed in tests
- Audit events complete for all auth outcomes
- Production rollout supports immediate rollback
- Privacy and consent requirements documented and approved

19. Decision snapshot
Accepted ADRs
- ADR-2026-03-18-01 Authorization boundary: acl_rbac is final allow deny gate.
- ADR-2026-03-18-02 Biometric storage policy: embeddings and metadata only, no raw images by default.
- ADR-2026-03-18-03 Threshold strategy: two-threshold model with uncertainty band and risk-tier profiles.
- ADR-2026-03-18-04 Liveness policy: required for all facial recognition events.
- ADR-2026-03-18-05 Failure mode by risk: high fail-closed, medium RBAC-only, low session-auth baseline.
- ADR-2026-03-18-06 Step-up freshness: default TTL 120 seconds.
- ADR-2026-03-18-07 Fallback policy: high-risk hard deny, no fallback.
- ADR-2026-03-18-08 Audit schema: strict versioned schema with required core fields.

20. Engineering kickoff
Implementation backlog is maintained in
- plugins/face_verify/IMPLEMENTATION_BACKLOG.md


15. Implementation notes (current codebase)
- Canonical assurance schema is implemented in plugins/shared_assurance.py and consumed by both face_verify and acl_rbac.
- acl_rbac owns the command risk map and remains the final allow or deny gate for high-risk commands such as /git.
- face_verify now depends on a backend interface with an InsightFace adapter skeleton entry point.
- Mandatory liveness is enforced for every verify command.
- Default step-up TTL is 120 seconds and high-risk policy checks treat expired assurance as invalid.
