from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any

from .base import BackendResponse


class InsightFaceBackend:
    provider_name = "insightface"

    def __init__(self, *, store_path: Path, verify_ttl_seconds: int, model_version: str = "insightface-skeleton"):
        self.store_path = Path(store_path)
        self.verify_ttl_seconds = int(verify_ttl_seconds)
        self.model_version = model_version
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self._write_store({"sessions": {}})

    def enroll(self, session_id: str, token: str) -> str:
        store = self._read_store()
        salt = secrets.token_hex(16)
        store.setdefault("sessions", {})[session_id] = {
            "salt": salt,
            "token_hash": self._hash_token(token, salt),
            "verified_until": 0,
            "updated_at": int(time.time()),
        }
        self._write_store(store)
        return self.model_version

    def verify(self, session_id: str, token: str, liveness: str) -> BackendResponse:
        store = self._read_store()
        session_entry = store.get("sessions", {}).get(session_id)
        if not session_entry:
            return BackendResponse(False, "not_enrolled", 0.0, "unavailable", self.model_version, detail="missing session")
        if liveness == "fail":
            return BackendResponse(False, "liveness_failed", 0.0, "fail", self.model_version)
        if liveness == "unavailable":
            return BackendResponse(False, "liveness_unavailable", 0.0, "unavailable", self.model_version)
        if liveness != "pass":
            return BackendResponse(False, "liveness_indeterminate", 0.0, "indeterminate", self.model_version)

        expected = session_entry.get("token_hash", "")
        salt = session_entry.get("salt", "")
        provided = self._hash_token(token, salt)
        if not secrets.compare_digest(expected, provided):
            return BackendResponse(False, "token_mismatch", 0.0, "pass", self.model_version)

        now = int(time.time())
        verified_until = now + self.verify_ttl_seconds
        session_entry["verified_until"] = verified_until
        session_entry["updated_at"] = now
        self._write_store(store)
        return BackendResponse(True, "verified", 0.99, "pass", self.model_version, verified_until=verified_until)

    def clear(self, session_id: str) -> bool:
        store = self._read_store()
        removed = store.get("sessions", {}).pop(session_id, None)
        self._write_store(store)
        return bool(removed)

    def status(self, session_id: str) -> dict[str, int | bool]:
        store = self._read_store()
        session_entry = store.get("sessions", {}).get(session_id)
        now = int(time.time())
        if not session_entry:
            return {"verified": False, "seconds_remaining": 0}
        verified_until = int(session_entry.get("verified_until", 0))
        if verified_until <= now:
            return {"verified": False, "seconds_remaining": 0}
        return {"verified": True, "seconds_remaining": verified_until - now}

    def _read_store(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {"sessions": {}}
        if not isinstance(payload, dict):
            payload = {"sessions": {}}
        payload.setdefault("sessions", {})
        return payload

    def _write_store(self, payload: dict[str, Any]) -> None:
        self.store_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _hash_token(self, token: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{token}".encode("utf-8")).hexdigest()
