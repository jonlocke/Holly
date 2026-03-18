Face Verify ADR Decision Log Template

Document title
Face Verify ADR Log

Project
Holly plugin architecture

Owner
Jon

Status
Active

How to use this log
Record one ADR per major decision.
Do not overwrite old ADRs.
If a decision changes, create a new ADR that supersedes the old one.
Link each ADR to the architecture spec section it affects.

ADR Entry Template

ADR ID
ADR-YYYY-MM-DD-XX

Title
Short decision name

Date
YYYY-MM-DD

Status
Proposed | Accepted | Rejected | Superseded

Supersedes
ADR ID or None

Superseded by
ADR ID or None

Decision owner
Name

Reviewers
Names

Context
What problem are we solving
What constraints exist
What risks matter most

Decision
State the decision in one sentence first
Then list the exact policy or rule chosen

Options considered
Option A
Pros
Cons

Option B
Pros
Cons

Option C
Pros
Cons

Rationale
Why this option was chosen over others
What tradeoffs were accepted

Security impact
How this affects confidentiality, integrity, availability
Any new attack surface
Fail-open or fail-closed behavior

Privacy and compliance impact
What biometric or personal data is affected
Consent implications
Retention and deletion implications

Operational impact
Runbook changes
Monitoring and alerting changes
Expected performance impact
Cost impact

Developer impact
Files or modules expected to change
Test impact
Migration complexity

Configuration impact
New config keys
Default values
Backward compatibility behavior

Data model impact
New fields
Schema changes
Migration needed yes or no

Failure mode behavior
What happens if dependency fails
User-facing error behavior
Recovery path

Rollout plan
Shadow mode yes or no
Canary scope
Success metrics
Abort and rollback criteria

Test and validation plan
Unit tests
Integration tests
Security tests
Load and latency tests
Acceptance criteria

Open questions
List unresolved points

Decision outcome summary
One short paragraph for future readers

References
Links to spec sections, issues, commits, and test reports

Starter ADRs to create first for face verify

ADR 01
Authorization boundary
Decision target
acl_rbac is the only final allow deny engine, face_verify only emits assurance signals

ADR 02
Biometric storage policy
Decision target
Store embeddings only, no raw images by default

ADR 03
Threshold strategy
Decision target
Two-threshold band with uncertain outcome handling

ADR 04
Liveness by risk tier
Decision target
Which risk levels require liveness

ADR 05
Failure mode policy
Decision target
Fail-closed for high and critical commands when backend is unavailable

ADR 06
Step-up freshness
Decision target
TTL and freshness requirements per risk level

ADR 07
Fallback policy
Decision target
If and when token fallback is allowed, and in which environments only

ADR 08
Audit schema
Decision target
Mandatory event fields and retention period
