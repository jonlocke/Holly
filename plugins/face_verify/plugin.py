from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any


class Plugin:
    id = "face_verify"
    version = "0.1.0"
    timeout_seconds = 1.5

    def __init__(self):
        self.app_context: dict[str, Any] | None = None
        self.commands = {
            "/face-enroll": "Enroll a face token for the current session: /face-enroll <token>",
            "/face-verify": "Verify face token for privileged actions: /face-verify <token>",
            "/face-status": "Show current face verification status for this session.",
            "/face-clear": "Clear enrolled face token and verification cache for this session.",
        }
        self._store_path: Path | None = None
        self._verify_ttl_seconds = 300
        self._sensitive_commands: set[str] = {"/git"}

    def on_load(self, app_context):
        self.app_context = app_context
        config = (
            (app_context or {})
            .get("config", {})
            .get("plugins", {})
            .get("face_verify", {})
        )

        self._store_path = Path(config.get("store_path", "face_verify_store.json"))
        self._verify_ttl_seconds = int(config.get("verify_ttl_seconds", 300))
        self._sensitive_commands = {
            self._normalize_command(cmd)
            for cmd in config.get("sensitive_commands", ["/git"])
            if str(cmd).strip()
        }
        self._ensure_store_initialized()

    def on_unload(self):
        self.app_context = None

    def on_command(self, command, args, context):
        command = self._normalize_command(command)
        session_id = self._session_id(context)

        if command == "/face-enroll":
            if not args:
                return {
                    "type": "command_response",
                    "command": command,
                    "content": "Usage: /face-enroll <token>",
                }

            token = " ".join(args).strip()
            if len(token) < 4:
                return {
                    "type": "command_response",
                    "command": command,
                    "content": "Token is too short. Use at least 4 characters.",
                }

            store = self._read_store()
            salt = secrets.token_hex(16)
            token_hash = self._hash_token(token, salt)
            store.setdefault("sessions", {})[session_id] = {
                "salt": salt,
                "token_hash": token_hash,
                "verified_until": 0,
                "updated_at": int(time.time()),
            }
            self._write_store(store)

            return {
                "type": "command_response",
                "command": command,
                "content": "Face token enrolled for this session. Run /face-verify <token> before sensitive commands.",
            }

        if command == "/face-verify":
            if not args:
                return {
                    "type": "command_response",
                    "command": command,
                    "content": "Usage: /face-verify <token>",
                }

            token = " ".join(args).strip()
            store = self._read_store()
            session_entry = store.get("sessions", {}).get(session_id)
            if not session_entry:
                return {
                    "type": "command_response",
                    "command": command,
                    "content": "No enrollment found for this session. Run /face-enroll first.",
                }

            expected = session_entry.get("token_hash", "")
            salt = session_entry.get("salt", "")
            provided = self._hash_token(token, salt)
            if not secrets.compare_digest(expected, provided):
                return {
                    "type": "command_response",
                    "command": command,
                    "content": "Face verification failed. Token did not match.",
                }

            verified_until = int(time.time()) + self._verify_ttl_seconds
            session_entry["verified_until"] = verified_until
            session_entry["updated_at"] = int(time.time())
            self._write_store(store)
            return {
                "type": "command_response",
                "command": command,
                "content": f"Face verification successful. Step-up window active for {self._verify_ttl_seconds} seconds.",
            }

        if command == "/face-status":
            verified, seconds_remaining = self._is_verified(session_id)
            if verified:
                msg = f"Face verification active for this session ({seconds_remaining}s remaining)."
            else:
                msg = "Face verification is not currently active for this session."
            return {
                "type": "command_response",
                "command": command,
                "content": msg,
            }

        if command == "/face-clear":
            store = self._read_store()
            removed = store.get("sessions", {}).pop(session_id, None)
            self._write_store(store)
            msg = "Face session state cleared." if removed else "No face session state found."
            return {
                "type": "command_response",
                "command": command,
                "content": msg,
            }

        return None

    def on_before_response(self, context):
        message = str((context or {}).get("message") or "").strip()
        if not message.startswith("/"):
            return None

        command = self._normalize_command(message.split()[0])
        if command not in self._sensitive_commands:
            return None

        session_id = self._session_id(context)
        verified, _ = self._is_verified(session_id)
        if verified:
            return None

        return {
            "type": "policy",
            "deny": True,
            "content": (
                "Step-up verification required before sensitive command. "
                "Run /face-verify <token> first."
            ),
        }

    def on_after_response(self, response, context):
        return None

    def _session_id(self, context: dict[str, Any] | None) -> str:
        return str((context or {}).get("session_id") or "unknown")

    def _ensure_store_initialized(self) -> None:
        if not self._store_path:
            return
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        if self._store_path.exists():
            return
        self._write_store({"sessions": {}})

    def _read_store(self) -> dict[str, Any]:
        if not self._store_path:
            return {"sessions": {}}
        try:
            payload = json.loads(self._store_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {"sessions": {}}
        if not isinstance(payload, dict):
            payload = {"sessions": {}}
        payload.setdefault("sessions", {})
        return payload

    def _write_store(self, payload: dict[str, Any]) -> None:
        if not self._store_path:
            return
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _hash_token(self, token: str, salt: str) -> str:
        digest = hashlib.sha256(f"{salt}:{token}".encode("utf-8")).hexdigest()
        return digest

    def _is_verified(self, session_id: str) -> tuple[bool, int]:
        now = int(time.time())
        store = self._read_store()
        session_entry = store.get("sessions", {}).get(session_id)
        if not session_entry:
            return False, 0
        verified_until = int(session_entry.get("verified_until", 0))
        if verified_until <= now:
            return False, 0
        return True, verified_until - now

    def _normalize_command(self, command: str) -> str:
        command = str(command or "").strip().lower()
        if command and not command.startswith("/"):
            command = f"/{command}"
        return command
