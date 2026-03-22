from __future__ import annotations

from typing import Any

ASSURANCE_SCHEMA_VERSION = "2026-03-18"
REQUIRED_ASSURANCE_FIELDS = {
    "subject_id",
    "session_id",
    "factors_present",
    "factor_freshness",
    "face_score",
    "liveness_status",
    "assurance_level",
    "expires_at",
    "issuer",
    "model_version",
    "reason_code",
}

DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_UNCERTAIN = "uncertain"
DECISION_ENUM = {DECISION_ALLOW, DECISION_DENY, DECISION_UNCERTAIN}
RISK_LEVEL_ENUM = {"low", "medium", "high", "critical"}
LIVENESS_STATUS_ENUM = {"pass", "fail", "unavailable", "indeterminate"}
ASSURANCE_LEVEL_ENUM = {"low", "medium", "high"}
REASON_CODE_ENUM = {
    "verified",
    "not_enrolled",
    "token_mismatch",
    "liveness_failed",
    "liveness_unavailable",
    "liveness_indeterminate",
    "backend_unavailable",
    "assurance_missing",
    "assurance_expired",
    "invalid_assurance",
    "policy_denied",
    "policy_allowed",
    "command_not_sensitive",
}

REASON_MESSAGES = {
    "verified": {
        "user_message": "Verification succeeded and a fresh step-up assurance is available.",
        "operator_hint": "Proceed with the policy evaluation using the fresh assurance payload.",
    },
    "not_enrolled": {
        "user_message": "No face enrollment was found for this session.",
        "operator_hint": "Require enrollment before retrying verification.",
    },
    "token_mismatch": {
        "user_message": "Verification failed because the submitted face token did not match.",
        "operator_hint": "Investigate whether the user needs to retry or re-enroll.",
    },
    "liveness_failed": {
        "user_message": "Verification failed because the liveness check did not pass.",
        "operator_hint": "Reject replay attempts and require a live retry.",
    },
    "liveness_unavailable": {
        "user_message": "Verification could not continue because liveness was unavailable.",
        "operator_hint": "Fail closed and restore the liveness dependency before retrying.",
    },
    "liveness_indeterminate": {
        "user_message": "Verification could not determine liveness with enough confidence.",
        "operator_hint": "Require another live capture or a stronger factor.",
    },
    "backend_unavailable": {
        "user_message": "Verification is temporarily unavailable and the request cannot continue.",
        "operator_hint": "Restore the face verification backend and retry the high-risk operation.",
    },
    "assurance_missing": {
        "user_message": "A fresh face verification is required before this command can run.",
        "operator_hint": "Ask the user to complete face verification before retrying the command.",
    },
    "assurance_expired": {
        "user_message": "The face verification window expired and must be refreshed.",
        "operator_hint": "Require a new face verification because the TTL elapsed.",
    },
    "invalid_assurance": {
        "user_message": "The verification result was rejected because its assurance payload was invalid.",
        "operator_hint": "Inspect schema validation errors and plugin version compatibility.",
    },
    "policy_denied": {
        "user_message": "Policy denied the requested command.",
        "operator_hint": "Review the command risk map and assurance requirements.",
    },
    "policy_allowed": {
        "user_message": "Policy allowed the requested command.",
        "operator_hint": "Audit the command with the mapped risk tier and assurance details.",
    },
    "command_not_sensitive": {
        "user_message": "The command did not require face verification.",
        "operator_hint": "Continue normal RBAC checks without biometric step-up.",
    },
}


def reason_details(reason_code: str) -> dict[str, str]:
    return REASON_MESSAGES.get(reason_code, REASON_MESSAGES["invalid_assurance"])


def build_assurance_payload(**kwargs: Any) -> dict[str, Any]:
    payload = dict(kwargs)
    payload.setdefault("schema_version", ASSURANCE_SCHEMA_VERSION)
    return payload


def validate_assurance_payload(payload: dict[str, Any] | None) -> tuple[bool, str | None]:
    if not isinstance(payload, dict):
        return False, "Payload must be a dict."

    missing = sorted(REQUIRED_ASSURANCE_FIELDS - payload.keys())
    if missing:
        return False, f"Missing required assurance fields: {', '.join(missing)}"

    if payload.get("liveness_status") not in LIVENESS_STATUS_ENUM:
        return False, "Invalid liveness_status enum value."
    if payload.get("assurance_level") not in ASSURANCE_LEVEL_ENUM:
        return False, "Invalid assurance_level enum value."
    if payload.get("reason_code") not in REASON_CODE_ENUM:
        return False, "Invalid reason_code enum value."
    if not isinstance(payload.get("factors_present"), list):
        return False, "factors_present must be a list."
    if not isinstance(payload.get("factor_freshness"), dict):
        return False, "factor_freshness must be a dict."
    try:
        float(payload.get("face_score"))
        int(payload.get("expires_at"))
    except (TypeError, ValueError):
        return False, "face_score and expires_at must be numeric."
    return True, None
