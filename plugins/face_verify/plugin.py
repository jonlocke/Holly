from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from plugins.face_verify.backends.base import FaceBackend
from plugins.face_verify.backends.insightface import InsightFaceBackend
from plugins.shared_assurance import build_assurance_payload, reason_details


class Plugin:
    id = "face_verify"
    version = "0.1.0"
    timeout_seconds = 1.5

    def __init__(self):
        self.app_context: dict[str, Any] | None = None
        self.commands = {
            "/face-enroll": "Enroll a face token for the current session: /face-enroll <token>",
            "/face-verify": "Verify face token for privileged actions: /face-verify <token> --liveness=pass",
            "/face-status": "Show current face verification status for this session.",
            "/face-clear": "Clear enrolled face token and verification cache for this session.",
        }
        self._store_path: Path | None = None
        self._verify_ttl_seconds = 120
        self._provider = "insightface"
        self._backend: FaceBackend | None = None

    def on_load(self, app_context):
        self.app_context = app_context
        config = ((app_context or {}).get("config", {}).get("plugins", {}).get("face_verify", {}))
        self._store_path = Path(config.get("store_path", "face_verify_store.json"))
        self._verify_ttl_seconds = int(config.get("verify_ttl_seconds", 120))
        self._provider = str(config.get("provider", "insightface")).strip().lower() or "insightface"
        self._backend = self._build_backend()

    def on_unload(self):
        self.app_context = None
        self._backend = None

    def on_command(self, command, args, context):
        command = self._normalize_command(command)
        session_id = self._session_id(context)

        if command == "/face-enroll":
            if not args:
                return self._response(command, "Usage: /face-enroll <token>")
            token = self._parse_token(args)
            if len(token) < 4:
                return self._response(command, "Token is too short. Use at least 4 characters.")
            assert self._backend is not None
            self._backend.enroll(session_id, token)
            return self._response(
                command,
                "Face token enrolled for this session. Run /face-verify <token> --liveness=pass before sensitive commands.",
            )

        if command == "/face-verify":
            if not args:
                return self._response(command, "Usage: /face-verify <token> --liveness=pass")
            token = self._parse_token(args)
            liveness = self._parse_liveness(args)
            assert self._backend is not None
            result = self._backend.verify(session_id, token, liveness)
            if not result.ok:
                return self._response(command, reason_details(result.reason_code)["user_message"])
            assurance = self.build_assurance(context)
            message = f"Face verification successful. Step-up window active for {self._verify_ttl_seconds} seconds."
            return {
                "type": "command_response",
                "command": command,
                "content": message,
                "assurance": assurance,
            }

        if command == "/face-status":
            assert self._backend is not None
            status = self._backend.status(session_id)
            if status["verified"]:
                msg = f"Face verification active for this session ({status['seconds_remaining']}s remaining)."
            else:
                msg = "Face verification is not currently active for this session."
            return self._response(command, msg)

        if command == "/face-clear":
            assert self._backend is not None
            removed = self._backend.clear(session_id)
            msg = "Face session state cleared." if removed else "No face session state found."
            return self._response(command, msg)

        return None

    def on_before_response(self, context):
        context["face_assurance"] = self.build_assurance(context)
        return None

    def on_after_response(self, response, context):
        return None

    def build_assurance(self, context: dict[str, Any] | None) -> dict[str, Any]:
        session_id = self._session_id(context)
        now = int(time.time())
        assert self._backend is not None
        status = self._backend.status(session_id)
        verified = bool(status["verified"])
        expires_at = now + int(status["seconds_remaining"]) if verified else 0
        reason_code = "verified" if verified else "assurance_missing"
        return build_assurance_payload(
            subject_id=str((context or {}).get("user_id") or session_id),
            session_id=session_id,
            factors_present=["face_verify"] if verified else [],
            factor_freshness={"face_verify": expires_at if verified else 0},
            face_score=0.99 if verified else 0.0,
            liveness_status="pass" if verified else "unavailable",
            assurance_level="high" if verified else "low",
            expires_at=expires_at,
            issuer=self.id,
            model_version=getattr(self._backend, "model_version", self._provider),
            reason_code=reason_code,
        )

    def _build_backend(self) -> FaceBackend:
        if self._provider != "insightface":
            raise ValueError(f"Unsupported face_verify provider '{self._provider}'.")
        assert self._store_path is not None
        return InsightFaceBackend(store_path=self._store_path, verify_ttl_seconds=self._verify_ttl_seconds)

    def _response(self, command: str, content: str) -> dict[str, Any]:
        return {"type": "command_response", "command": command, "content": content}

    def _session_id(self, context: dict[str, Any] | None) -> str:
        return str((context or {}).get("session_id") or "unknown")

    def _normalize_command(self, command: str) -> str:
        command = str(command or "").strip().lower()
        if command and not command.startswith("/"):
            command = f"/{command}"
        return command

    def _parse_token(self, args: list[str]) -> str:
        return " ".join(arg for arg in args if not str(arg).startswith("--liveness=")).strip()

    def _parse_liveness(self, args: list[str]) -> str:
        for arg in args:
            if str(arg).startswith("--liveness="):
                return str(arg).split("=", 1)[1].strip().lower() or "indeterminate"
        return "unavailable"
