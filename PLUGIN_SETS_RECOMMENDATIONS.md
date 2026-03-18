Plugin sets recommendations for Holly hook-based plugin architecture

Goal
Build a secure, composable plugin stack with a simple baseline and clear upgrade path.

Recommended plugin sets

Set A: baseline security and control
1. auth_local
2. mfa_totp
3. acl_rbac

Why
Provides identity, second-factor verification, and centralized authorization.

Set B: baseline plus step-up verification
1. auth_local
2. mfa_totp
3. acl_rbac
4. face_verify

Why
Adds time-bound step-up checks before sensitive commands such as /git.

Set C: operational hardening
1. auth_local
2. mfa_totp
3. acl_rbac
4. face_verify
5. audit_log
6. rate_limit_guardian
7. notify_security

Why
Adds traceability, abuse protection, and proactive alerting.

Architecture recommendations

1. Deny-first policy path
Any plugin returning { deny: true, content: "..." } should block execution immediately.

2. Fail-closed behavior
If policy or auth state is unavailable, deny privileged actions.

3. Short-lived step-up windows
Face verify and MFA checks should grant temporary access, not permanent bypass.

4. Role + command policy model
Use role mappings and explicit command permissions with deny precedence.

5. Unified plugin result contract
Use a shared shape across plugins:
- type
- content
- deny
- prompt_prefix
- risk_level
- code

6. Minimal sensitive command bootstrap
Start with /git in sensitive_commands. Expand later to config-change or outbound actions.

7. Progressive rollout
Phase 1: auth_local + mfa_totp + acl_rbac
Phase 2: face_verify step-up
Phase 3: audit and notifications

Current implementation status in this branch

Implemented
- face_verify plugin with commands:
  - /face-enroll <token>
  - /face-verify <token>
  - /face-status
  - /face-clear
- before_response deny handling in main streaming flow
- deny response handling for plugin-dispatched command results

Scaffolded
- auth_local plugin skeleton
- mfa_totp plugin skeleton
- acl_rbac plugin skeleton

Notes
The current face_verify plugin is intentionally adapter-friendly and token-based for now.
It is designed as a step-up verification gate. A real biometric backend can be integrated later behind the same command/hook contract.
