Face Verify Engineering Ticket Packs

Status
Ready for pickup

Last updated
2026-03-18

Scope
Tracker-ready tickets for P0 and P1 implementation phases.

---

Ticket
FV-P0-001
Title
Define shared assurance contract and enums

Description
Create one canonical assurance contract shared by face_verify and acl_rbac. This contract must define required fields and enum values so policy evaluation is deterministic and auditable.

Scope
- Define assurance schema with required fields
- Define enums:
  - decision
  - reason_code
  - risk_level
  - liveness_status
- Add schema validation helpers
- Wire both plugins to consume the same schema

Implementation checklist
- Add shared contract module or shared section in plugin_system
- Define required assurance fields:
  subject_id, session_id, factors_present, factor_freshness, face_score, liveness_status, assurance_level, expires_at, issuer, model_version, reason_code
- Define decision enum and reason_code enum with documented values
- Refactor face_verify outputs to match schema
- Refactor acl_rbac inputs to validate and consume schema

Test checklist
- Unit test valid assurance payload passes
- Unit test missing required field fails
- Unit test invalid enum value fails
- Integration test face_verify output accepted by acl_rbac without transformation errors

Acceptance criteria
- One canonical schema source exists
- Both plugins use the same contract
- Invalid payloads are rejected deterministically
- Enum values documented in code comments or docs

Merge checklist
- Tests green
- No duplicate schema definitions
- Docs updated in ARCHITECTURE_SPEC or linked contract doc

---

Ticket
FV-P0-002
Title
Implement authoritative command risk map

Description
Create a single source of truth for command-to-risk mapping used by acl_rbac. This must classify commands into low medium high critical with deterministic default behavior.

Scope
- Add command risk map
- Add lookup function and precedence rules
- Include high-impact command examples such as reboot-class actions
- Add tests for known and unknown commands

Implementation checklist
- Create risk map structure in acl_rbac policy layer
- Define explicit mappings for current command set
- Define default class for unknown commands
- Add profile selection hook for threshold policies by risk tier
- Ensure mapping is easy to review and version

Test checklist
- Unit test each mapped command returns expected risk
- Unit test unknown command follows default policy
- Integration test risk tier influences policy branch
- Regression test for deny-first precedence with risk mapping

Acceptance criteria
- Every evaluated command has deterministic risk
- High-impact commands are explicitly mapped
- Default handling is defined and tested
- Mapping is readable and maintainable

Merge checklist
- Risk map documented
- Tests green
- No hidden fallback behavior

---

Ticket
FV-P0-003
Title
Enforce authorization boundary with acl_rbac as sole gate

Description
Guarantee that face_verify cannot directly authorize sensitive command execution. acl_rbac must remain the only final allow/deny decision point.

Scope
- Remove or neutralize any direct allow semantics in face_verify
- Ensure final decision always occurs in acl_rbac
- Preserve deny-first short-circuit handling in main flow

Implementation checklist
- Review face_verify return shapes and strip allow semantics
- Ensure acl_rbac consumes assurance signals and returns final decision
- Validate main policy pipeline order
- Add explicit guard against plugin-local authorization bypass

Test checklist
- Integration test face_verify success does not execute high-risk command without acl_rbac allow
- Integration test high-risk command denied when required assurance missing
- Integration test medium-risk command follows RBAC-only logic
- Regression test deny-first short-circuit still works

Acceptance criteria
- face_verify emits assurance only
- acl_rbac is sole final gate
- No bypass path exists via plugin-local allow
- Policy pipeline remains deterministic

Merge checklist
- Integration tests green
- Code review confirms separation of concerns
- ADR alignment verified against ADR-01 and ADR-05

---

Ticket
FV-P0-004
Title
Publish reason_code taxonomy and policy error messages

Description
Lock a first version of reason_code values and user/operator messages for consistency across deny paths and audit logs.

Scope
- Finalize reason_code enum list
- Map reason_code to user-safe message
- Map reason_code to operator remediation hint
- Ensure audit events include reason_code consistently

Acceptance criteria
- reason_code list versioned
- message mapping implemented
- tests ensure reason_code always present on deny and uncertain outcomes

---

Ticket
FV-P1-001
Title
Introduce FaceBackend interface and InsightFace adapter skeleton

Description
Create a backend abstraction for face verification so plugin logic is stable while biometric engine implementation can evolve. First backend target is InsightFace.

Scope
- Define FaceBackend interface
- Implement backend selection via config
- Add InsightFace adapter skeleton with stubbed enroll verify clear status
- Wire face_verify plugin to call backend through interface only

Implementation checklist
- Add backends base module with interface contract
- Add insightface backend module with typed response model
- Add config key provider and backend init path
- Refactor plugin flow to remove direct engine coupling
- Add startup validation for provider selection

Test checklist
- Unit test backend factory selects configured provider
- Unit test plugin fails safely on invalid provider
- Unit test backend method response shape validation
- Integration smoke test plugin loads with InsightFace backend configured

Acceptance criteria
- face_verify plugin depends on interface, not concrete engine
- InsightFace backend is pluggable through config
- Invalid provider is fail-safe and observable
- Tests cover selection and error paths

---

Ticket
FV-P1-002
Title
Enforce mandatory liveness in all face verification flows

Description
Implement liveness as a required precondition for every face verification event. No risk-tier exemptions.

Scope
- Add required liveness check in verify flow
- Define liveness result states and reason codes
- Deny verify when liveness unavailable fail or indeterminate
- Ensure this policy applies across all command tiers where face is invoked

Implementation checklist
- Insert liveness gate before match acceptance
- Add reason codes for liveness_unavailable liveness_failed liveness_indeterminate
- Return deterministic outcomes for each liveness state
- Update docs and inline comments to reflect required liveness

Test checklist
- Integration test static photo replay fails
- Integration test missing liveness result fails verify
- Integration test valid liveness plus valid match succeeds
- Regression test no tier path bypasses liveness requirement

Acceptance criteria
- No verification success without liveness pass
- Liveness failure paths are explicit and test-covered
- Reason codes are emitted consistently

---

Ticket
FV-P1-003
Title
Set step-up TTL default to 120 seconds with strict expiry behavior

Description
Implement ADR-defined initial step-up freshness window at 120 seconds and ensure boundary-safe expiry handling for high-risk policy checks.

Scope
- Set default verify_ttl_seconds to 120
- Ensure expires_at is created and validated consistently
- Deny high-risk commands on expired assurance
- Keep TTL configurable for later tuning

Implementation checklist
- Update face_verify default TTL to 120
- Normalize timestamp handling in UTC epoch seconds
- Ensure acl_rbac freshness check uses same clock basis
- Add safe handling for clock skew and missing expiry fields

Test checklist
- Unit test fresh assurance within 120 seconds passes freshness check
- Unit test expiry boundary denies after timeout
- Integration test high-risk command denied after TTL expiry
- Regression test medium policy unaffected by face TTL when face not required

Acceptance criteria
- Default TTL is 120
- Expired assurance is never treated as valid
- Boundary behavior deterministic and tested

---

Ticket
FV-P1-004
Title
Implement high-risk hard-deny no-fallback policy

Description
Enforce no-fallback behavior for high-risk commands when required face or liveness assurance is missing failed expired or indeterminate.

Scope
- Hard deny branch for high-risk missing assurance conditions
- Explicitly block MFA+RBAC substitution on high-risk when biometric requirement applies
- Return clear user-safe deny reason and operator remediation hint

Implementation checklist
- Add high-risk hard-deny policy branch in acl_rbac
- Map deny outcomes to reason codes
- Ensure policy pipeline cannot downgrade high-risk requirement at runtime
- Add clear denial messaging contract

Test checklist
- Integration test high-risk denied when face backend unavailable
- Integration test high-risk denied when liveness fails
- Integration test high-risk denied when assurance expired
- Integration test MFA+RBAC cannot override high-risk hard deny

Acceptance criteria
- High-risk no-fallback behavior is enforced
- Deny reasons are deterministic and auditable
- No bypass via alternate factors

---

Ticket
FV-P1-005
Title
Add deterministic deny messaging and remediation mapping

Description
Standardize user-facing and operator-facing messages for all deny outcomes in P1 paths, keyed by reason_code.

Scope
- Define message map by reason_code
- Provide concise user message text
- Provide operator remediation guidance
- Ensure audit records include same reason_code

Implementation checklist
- Create central reason_code to message mapping module
- Reference mapping in face_verify and acl_rbac deny responses
- Add operator remediation hints for backend unavailable liveness fail ttl expired policy deny
- Keep sensitive internals out of user text

Test checklist
- Unit test each reason_code resolves to user and operator message
- Integration test deny responses include mapped text
- Regression test unknown reason_code falls back safely

Acceptance criteria
- Consistent messaging across deny paths
- No raw internal error leakage to user
- Audit and response reason_code alignment maintained

---

P0 definition of done
- P0-1, P0-2, P0-3 merged
- Tests passing for contract, risk map, and authorization boundary
- No behavior regressions in existing command routing

P1 definition of done
- Backend abstraction in place and InsightFace adapter wired
- Liveness required globally in face verification
- TTL default 120 with tested expiry behavior
- High-risk hard deny no-fallback enforced
- Reason-code-driven deny messaging consistent and auditable
