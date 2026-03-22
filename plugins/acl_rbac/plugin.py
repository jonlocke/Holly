from __future__ import annotations

import time
from typing import Any

from plugins.shared_assurance import reason_details, validate_assurance_payload


class Plugin:
    id = "acl_rbac"
    version = "0.1.0"
    timeout_seconds = 1.0

    COMMAND_RISK_MAP = {
        "/git": "high",
        "/face-enroll": "low",
        "/face-verify": "low",
        "/face-status": "low",
        "/face-clear": "medium",
        "/policy-status": "low",
    }
    DEFAULT_RISK_LEVEL = "medium"

    def __init__(self):
        self.app_context: dict[str, Any] | None = None
        self.commands = {
            "/policy-status": "Show the active authorization policy summary.",
        }
        self._fail_closed = True
        self._default_role = "user"
        self._policy_file_path = ""

    def on_load(self, app_context):
        self.app_context = app_context
        config = ((app_context or {}).get("config", {}).get("plugins", {}).get("acl_rbac", {}))
        self._fail_closed = bool(config.get("fail_closed", True))
        self._default_role = str(config.get("default_role", "user"))
        self._policy_file_path = str(config.get("policy_file_path", "policy-inline"))

    def on_unload(self):
        self.app_context = None

    def on_command(self, command, args, context):
        if command == "/policy-status":
            return {
                "type": "command_response",
                "command": command,
                "content": (
                    f"acl_rbac active: default_role={self._default_role}, fail_closed={self._fail_closed}, "
                    f"default_risk={self.DEFAULT_RISK_LEVEL}."
                ),
            }
        return None

    def on_before_response(self, context):
        message = str((context or {}).get("message") or "").strip()
        if not message.startswith("/"):
            return None

        command = self._normalize_command(message.split()[0])
        risk = self.command_risk(command)
        if risk in {"low", "medium"}:
            return None

        assurance = self._resolve_face_assurance(context)
        valid, error = validate_assurance_payload(assurance)
        if not valid:
            return self._deny("invalid_assurance", f"{reason_details('invalid_assurance')['user_message']} {error}", risk)

        return self._evaluate_high_risk_assurance(assurance, risk)

    def command_risk(self, command: str) -> str:
        return self.COMMAND_RISK_MAP.get(self._normalize_command(command), self.DEFAULT_RISK_LEVEL)

    def _evaluate_high_risk_assurance(self, assurance: dict[str, Any], risk_level: str) -> dict[str, Any] | None:
        if "face_verify" not in assurance["factors_present"]:
            return self._deny("assurance_missing", reason_details("assurance_missing")["user_message"], risk_level)

        now = int(time.time())
        if int(assurance["expires_at"]) <= now:
            return self._deny("assurance_expired", reason_details("assurance_expired")["user_message"], risk_level)
        if assurance["liveness_status"] != "pass":
            return self._deny("liveness_failed", reason_details("liveness_failed")["user_message"], risk_level)
        return None

    def _resolve_face_assurance(self, context: dict[str, Any] | None) -> dict[str, Any] | None:
        if isinstance((context or {}).get("face_assurance"), dict):
            return context["face_assurance"]

        plugin_manager = (self.app_context or {}).get("plugin_manager")
        runtimes = getattr(plugin_manager, "runtimes", {}) if plugin_manager else {}
        runtime = runtimes.get("face_verify") if isinstance(runtimes, dict) else None
        instance = getattr(runtime, "instance", None)
        if instance and callable(getattr(instance, "build_assurance", None)):
            return instance.build_assurance(context)
        return None

    def _deny(self, reason_code: str, content: str, risk_level: str) -> dict[str, Any]:
        return {
            "type": "policy",
            "decision": "deny",
            "deny": True,
            "risk_level": risk_level,
            "reason_code": reason_code,
            "content": content,
            "operator_hint": reason_details(reason_code)["operator_hint"],
        }

    def _normalize_command(self, command: str) -> str:
        command = str(command or "").strip().lower()
        if command and not command.startswith("/"):
            command = f"/{command}"
        return command
