Plugin Sets Recommendations For Holly

Goal
Document the current architecture direction for Holly's route-driven identity model and hook-based policy/plugin system.

Current architectural stance
- Identity, session creation, admin bootstrap, and browser login UX live in app routes in `main.py`.
- Plugins are used for assurance, authorization, and feature extension, not as the primary session framework.
- The app now supports multi-user face enrollment and sign-in, with admin-managed user enrollment and separate step-up verification for sensitive commands.

Why identity moved into app routes
- Multi-user browser login needs tight coordination between Flask session state, UI gating, and face capture endpoints.
- Admin bootstrap and user management are simpler and more auditable when handled centrally in the app layer.
- This avoids splitting session truth across multiple partially implemented plugins.

Recommended active stack

Set A: current baseline
1. acl_rbac
2. face_verify
3. weather

Why
- `face_verify` provides user-scoped face enrollment, sign-in verification, and step-up verification signals.
- `acl_rbac` remains the centralized allow/deny gate for sensitive commands such as `/git`.
- Identity and session management are handled by app routes, not `auth_local`.

Set B: baseline plus app-layer identity
1. app routes for identity and session management
2. acl_rbac
3. face_verify
4. weather

Why
- This reflects the real system today.
- The browser session is unlocked by a pre-enrolled face for a named user.
- Sensitive commands require fresh step-up verification.

Set C: operational hardening target
1. app routes for identity and session management
2. acl_rbac
3. face_verify
4. audit_log
5. rate_limit_guardian
6. notify_security

Why
- Adds traceability, abuse detection, and operational response without moving core session state back into plugins.

Plugin responsibilities

`face_verify`
- Owns biometric assurance logic.
- Stores user-scoped face templates and session-scoped step-up artifacts.
- Exposes verification outcomes and assurance payloads.
- Must not make final authorization decisions.

`acl_rbac`
- Owns final authorization decisions for sensitive commands.
- Consumes assurance produced by `face_verify`.
- Applies deny-first policy and risk-tier rules.

App routes in `main.py`
- Own admin bootstrap and admin login.
- Own user creation and current browser session identity.
- Own face sign-in flow for unlocking chat.
- Own logout and session expiry handling.

Architecture recommendations

1. Deny-first policy path
- Any plugin returning `{ deny: true, content: "..." }` should block execution immediately.

2. Fail-closed behavior
- If policy, face assurance, or session identity is unavailable, deny privileged actions.

3. Two assurance windows
- Session verification unlocks chat for a moderate TTL.
- Step-up verification unlocks sensitive commands for a short TTL.

4. Authorization boundary
- `face_verify` emits assurance only.
- `acl_rbac` is the sole final allow/deny gate for sensitive command execution.

5. Role + command policy model
- Role and user identity originate from app-managed session state.
- `acl_rbac` should consume that state and apply explicit command policy with deny precedence.

6. Minimal sensitive command bootstrap
- Start with `/git` as the primary step-up protected command.
- Expand later to config mutation, outbound integrations, or reboot-class actions.

7. Plugin contract guidance
- Keep plugin responses predictable.
- Prefer shared keys such as:
  - `type`
  - `content`
  - `deny`
  - `prompt_prefix`
  - `risk_level`
  - `reason_code`
- Where route-specific payloads exist, document them explicitly rather than assuming a universal contract already exists.

8. Progressive rollout
- Phase 1: route-based identity and `acl_rbac`
- Phase 2: user-scoped `face_verify` sign-in and step-up
- Phase 3: audit, notifications, and stronger operational controls

Current implementation status in this branch

Implemented
- App-layer admin bootstrap, admin login/logout, and user creation
- App-layer browser session login/logout and expiry handling
- `face_verify` user-scoped face enrollment and verification flows
- `face_verify` step-up verification flow for sensitive commands
- `acl_rbac` command risk mapping and deny-first enforcement
- before-response deny handling in the main streaming flow
- browser `/git` path protected by authenticated session plus fresh step-up
- API `/git` path still supports token-based protection

Scaffolded or not yet implemented
- `auth_local` plugin remains a scaffold
- `mfa_totp` plugin remains a scaffold
- `audit_log` plugin is not implemented
- `rate_limit_guardian` plugin is not implemented as a plugin
- `notify_security` plugin is not implemented

Notes
- The older recommendation that `auth_local` and `mfa_totp` form the baseline no longer reflects the current codebase.
- Session and identity management intentionally moved into app routes to support multi-user browser login and admin-managed enrollment cleanly.
- Future work can still reintroduce richer plugin participation in identity flows, but the current source of truth for browser auth is the app layer.
