from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class IdentityStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if not self.path.exists():
            self._write({"users": {}})
        logger.info(
            "IdentityStore initialized at path=%s exists=%s writable_parent=%s",
            self.path,
            self.path.exists(),
            self.path.parent.exists(),
        )

    def ensure_bootstrap_admin(self, username: str, password: str, display_name: str = "Bootstrap Admin") -> dict[str, Any]:
        normalized_username = self._normalize_username(username)
        with self._lock:
            store = self._read()
            for existing in store["users"].values():
                if existing.get("role") == "admin" and not existing.get("disabled", False):
                    return self._public_user(existing)

            user_id = self._user_id_for_username(normalized_username)
            now = int(time.time())
            store["users"][user_id] = {
                "user_id": user_id,
                "username": normalized_username,
                "display_name": display_name.strip() or normalized_username,
                "role": "admin",
                "disabled": False,
                "password_hash": self._hash_password(password),
                "created_at": now,
                "updated_at": now,
            }
            self._write(store)
            return self._public_user(store["users"][user_id])

    def authenticate_admin(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.get_user_by_username(username)
        if not user or user.get("role") != "admin" or user.get("disabled", False):
            return None
        if not self._verify_password(password, str(user.get("password_hash", ""))):
            return None
        return self._public_user(user)

    def authenticate_user(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.get_user_by_username(username)
        if not user or user.get("disabled", False):
            return None
        if not self._verify_password(password, str(user.get("password_hash", ""))):
            return None
        return self._public_user(user)

    def list_users(self) -> list[dict[str, Any]]:
        with self._lock:
            store = self._read()
            users = [self._public_user(user) for user in store["users"].values()]
        return sorted(users, key=lambda user: user["username"])

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        normalized_username = self._normalize_username(username)
        with self._lock:
            store = self._read()
            for user in store["users"].values():
                if user.get("username") == normalized_username:
                    return dict(user)
        return None

    def create_user(self, username: str, display_name: str, role: str = "user") -> dict[str, Any]:
        normalized_username = self._normalize_username(username)
        normalized_role = (role or "user").strip().lower()
        if normalized_role not in {"admin", "user"}:
            raise ValueError("Role must be either 'admin' or 'user'.")

        with self._lock:
            store = self._read()
            if any(existing.get("username") == normalized_username for existing in store["users"].values()):
                raise ValueError("User already exists.")

            user_id = self._user_id_for_username(normalized_username)
            now = int(time.time())
            user = {
                "user_id": user_id,
                "username": normalized_username,
                "display_name": (display_name or normalized_username).strip() or normalized_username,
                "role": normalized_role,
                "disabled": False,
                "password_hash": "",
                "created_at": now,
                "updated_at": now,
            }
            store["users"][user_id] = user
            self._write(store)
            return self._public_user(user)

    def set_user_password(self, username: str, password: str) -> dict[str, Any]:
        normalized_username = self._normalize_username(username)
        with self._lock:
            store = self._read()
            user = next((entry for entry in store["users"].values() if entry.get("username") == normalized_username), None)
            if not user:
                raise ValueError("User not found.")
            user["password_hash"] = self._hash_password(password)
            user["updated_at"] = int(time.time())
            self._write(store)
            return self._public_user(user)

    def change_user_password(self, username: str, current_password: str, new_password: str) -> dict[str, Any]:
        normalized_username = self._normalize_username(username)
        with self._lock:
            store = self._read()
            user = next((entry for entry in store["users"].values() if entry.get("username") == normalized_username), None)
            if not user:
                raise ValueError("User not found.")

            current_hash = str(user.get("password_hash", ""))
            if current_hash:
                if not self._verify_password(current_password, current_hash):
                    raise ValueError("Current password is incorrect.")
            elif current_password:
                raise ValueError("Current password is not set for this account.")

            user["password_hash"] = self._hash_password(new_password)
            user["updated_at"] = int(time.time())
            self._write(store)
            return self._public_user(user)

    def _public_user(self, user: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": user["user_id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
            "disabled": bool(user.get("disabled", False)),
            "has_password": bool(user.get("password_hash")),
            "created_at": int(user.get("created_at", 0)),
            "updated_at": int(user.get("updated_at", 0)),
        }

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {"users": {}}
        if not isinstance(payload, dict):
            payload = {"users": {}}
        payload.setdefault("users", {})
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        logger.info(
            "IdentityStore wrote %d user records to %s",
            len(payload.get("users", {})),
            self.path,
        )

    def _normalize_username(self, username: str) -> str:
        normalized = (username or "").strip().lower()
        if not normalized:
            raise ValueError("Username is required.")
        if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in normalized):
            raise ValueError("Username may contain only letters, numbers, dot, underscore, and hyphen.")
        return normalized

    def _user_id_for_username(self, username: str) -> str:
        return f"user:{username}"

    def _hash_password(self, password: str) -> str:
        if len(password or "") < 8:
            raise ValueError("Password must be at least 8 characters.")
        salt = secrets.token_hex(16)
        digest = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
        return f"{salt}${digest}"

    def _verify_password(self, password: str, encoded_password: str) -> bool:
        if "$" not in encoded_password:
            return False
        salt, expected_digest = encoded_password.split("$", 1)
        actual_digest = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
        return secrets.compare_digest(actual_digest, expected_digest)
