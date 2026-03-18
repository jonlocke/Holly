Face Verify Implementation Backlog

Status
Ready for engineering kickoff

Last updated
2026-03-18

Scope
Implements accepted ADRs for Holly face verification step-up architecture.

Priority 0: Contracts and policy foundation

P0-1 Define canonical enums and contracts
Deliverables
- assurance object schema definition
- decision enum values
- reason_code enum values
- risk_level enum values
- liveness_status enum values
Files to touch
- plugins/face_verify/ARCHITECTURE_SPEC.md
- plugins/face_verify/ADR_LOG.md
- plugin_system.py or shared policy contract module
Acceptance
- Contract documented and referenced by face_verify and acl_rbac
- Unit tests validate schema shape and required fields

P0-2 Authoritative command risk map
Deliverables
- single source of truth risk map for commands
- explicit mapping for low medium high critical
- include reboot-class examples in high or critical
Files to touch
- plugins/acl_rbac/plugin.py
- config sample docs if applicable
Acceptance
- Integration tests confirm risk map lookup and deterministic fallback behavior

P0-3 Enforce authorization boundary
Deliverables
- acl_rbac as sole final allow deny gate
- face_verify returns assurance only
Files to touch
- plugins/acl_rbac/plugin.py
- plugins/face_verify/plugin.py
- main.py stream policy path if needed
Acceptance
- Integration tests prove face_verify cannot directly authorize sensitive commands

Priority 1: Face verify core behavior

P1-1 Backend adapter interface
Deliverables
- FaceBackend interface with methods enroll verify clear status
- InsightFace backend adapter skeleton
Files to touch
- plugins/face_verify/plugin.py
- plugins/face_verify/backends/base.py
- plugins/face_verify/backends/insightface_backend.py
Acceptance
- Plugin works against interface with backend selected by config

P1-2 Liveness required for all face verification
Deliverables
- required liveness check in verify flow
- reason codes for liveness unavailable fail indeterminate
Files to touch
- plugins/face_verify/plugin.py
- backend adapter response schema
Acceptance
- Tests fail verification when liveness signal missing or invalid

P1-3 Step-up TTL default 120 seconds
Deliverables
- default verify_ttl_seconds set to 120
- reliable expires_at handling
Files to touch
- plugins/face_verify/plugin.py
- config defaults docs
Acceptance
- Boundary tests at active and expired windows

P1-4 High-risk hard deny no fallback
Deliverables
- deterministic hard deny branch for missing required face or liveness on high-risk commands
- clear deny messages and reason codes
Files to touch
- plugins/acl_rbac/plugin.py
- plugins/face_verify/plugin.py
- main.py deny response path if needed
Acceptance
- Integration tests prove MFA plus RBAC cannot override high-risk hard deny when biometric requirements are unmet

Priority 2: Thresholding and profile policy

P2-1 Two-threshold model with uncertainty band
Deliverables
- threshold_low threshold_high profile config
- outcomes pass fail uncertain
Files to touch
- plugins/face_verify/plugin.py
- config docs and defaults
Acceptance
- Tests for boundary values and uncertain handling

P2-2 Risk-tier threshold profiles
Deliverables
- stricter profile for higher-impact commands
- acl_rbac selects profile by risk tier
Files to touch
- plugins/acl_rbac/plugin.py
- plugins/face_verify/plugin.py
Acceptance
- Integration tests verify profile selection and enforcement by command risk

P2-3 Uncertain-band handling policy
Deliverables
- explicit handling sequence per risk tier
- retry and or additional factor requirements
Files to touch
- plugins/acl_rbac/plugin.py
- plugins/face_verify/plugin.py
Acceptance
- End-to-end tests for uncertain outcomes by risk tier

Priority 3: Storage, audit, and operations

P3-1 Embedding-only persistence guardrails
Deliverables
- persistence schema for embeddings and metadata only
- explicit prevention of raw image writes
Files to touch
- plugins/face_verify/plugin.py
- storage helper module if added
Acceptance
- Tests verify no raw image payload reaches persistent store

P3-2 Strict versioned audit schema
Deliverables
- schema validator for required audit fields
- schema version management
- event builders for enrollment verification policy decisions
Files to touch
- plugins/face_verify/plugin.py
- plugins/acl_rbac/plugin.py
- audit module if present
Acceptance
- Malformed events rejected and alerted
- All required fields present in valid events

P3-3 Observability and tuning telemetry
Deliverables
- metrics for verify latency uncertain rate fail rate deny rate by command
- tuning notes for threshold updates
Files to touch
- logging and metrics hooks in plugins
Acceptance
- Dashboard-ready structured logs and periodic threshold review process

Priority 4: Rollout and safeguards

P4-1 Shadow mode and controlled enforcement
Deliverables
- optional shadow checks for tuning where policy permits
- staged enablement plan by command group
Files to touch
- plugin config and rollout docs
Acceptance
- rollout checklist with entry and exit criteria

P4-2 Rollback strategy
Deliverables
- rollback controls documented
- clear limitations where ADRs mandate hard deny
Files to touch
- ARCHITECTURE_SPEC.md
- deployment and runbook docs
Acceptance
- one-step rollback procedure documented and tested

Definition of done for initial release
- ADR 01 through ADR 08 behavior implemented and tested
- strict audit schema active with required fields
- high-risk hard deny no-fallback path verified
- liveness mandatory for all face verification paths
- embedding-only storage policy enforced
- command risk map published and versioned

Open implementation decisions to resolve before coding starts
- initial numeric threshold values per profile
- exact uncertain-band handling sequence
- final command-to-risk mapping
- reason_code enum finalization
- plugin_versions canonical format
