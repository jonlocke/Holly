from __future__ import annotations

import hashlib
import json
import logging
import math
import secrets
import time
from pathlib import Path
from typing import Any

from .base import BackendResponse

logger = logging.getLogger(__name__)


class InsightFaceBackend:
    provider_name = "insightface"

    def __init__(self, *, store_path: Path, verify_ttl_seconds: int, model_version: str = "insightface-skeleton"):
        self.store_path = Path(store_path)
        self.verify_ttl_seconds = int(verify_ttl_seconds)
        self.model_version = model_version
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self._write_store({"sessions": {}})
        logger.info(
            "InsightFaceBackend initialized with store_path=%s exists=%s verify_ttl_seconds=%s",
            self.store_path,
            self.store_path.exists(),
            self.verify_ttl_seconds,
        )

    def enroll(self, session_id: str, token: str) -> str:
        store = self._read_store()
        salt = secrets.token_hex(16)
        store.setdefault("sessions", {})[session_id] = {
            "salt": salt,
            "token_hash": self._hash_token(token, salt),
            "capture_signature": [],
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

    def enroll_capture(self, session_id: str, signature: list[int]) -> str:
        normalized_signature = self._normalize_signature(signature)
        store = self._read_store()
        session_entry = store.setdefault("sessions", {}).setdefault(session_id, {})
        session_entry.update(
            {
                "capture_signature": normalized_signature,
                "verified_until": 0,
                "updated_at": int(time.time()),
            }
        )
        self._write_store(store)
        return self.model_version

    def verify_capture(self, session_id: str, signature: list[int], liveness: str) -> BackendResponse:
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

        enrolled_signature = session_entry.get("capture_signature") or []
        if not enrolled_signature:
            return BackendResponse(False, "not_enrolled", 0.0, "unavailable", self.model_version, detail="missing capture signature")

        probe_signature = self._normalize_signature(signature)
        similarity = self._cosine_similarity(enrolled_signature, probe_signature)
        if similarity < 0.82:
            return BackendResponse(False, "token_mismatch", similarity, "pass", self.model_version, detail="capture signature mismatch")

        now = int(time.time())
        verified_until = now + self.verify_ttl_seconds
        session_entry["verified_until"] = verified_until
        session_entry["updated_at"] = now
        self._write_store(store)
        return BackendResponse(True, "verified", similarity, "pass", self.model_version, verified_until=verified_until)

    def enroll_user_capture(self, user_id: str, signature: list[int]) -> str:
        normalized_signature = self._normalize_signature(signature)
        store = self._read_store()
        user_entry = store.setdefault("users", {}).setdefault(user_id, {})
        user_entry["capture_signatures"] = [normalized_signature]
        user_entry["updated_at"] = int(time.time())
        self._write_store(store)
        return self.model_version

    def verify_user_capture(self, user_id: str, signature: list[int], liveness: str) -> BackendResponse:
        store = self._read_store()
        user_entry = store.get("users", {}).get(user_id)
        if not user_entry:
            return BackendResponse(False, "not_enrolled", 0.0, "unavailable", self.model_version, detail="missing user")

        if liveness == "fail":
            return BackendResponse(False, "liveness_failed", 0.0, "fail", self.model_version)
        if liveness == "unavailable":
            return BackendResponse(False, "liveness_unavailable", 0.0, "unavailable", self.model_version)
        if liveness != "pass":
            return BackendResponse(False, "liveness_indeterminate", 0.0, "indeterminate", self.model_version)

        probe_signature = self._normalize_signature(signature)
        enrolled_signatures = user_entry.get("capture_signatures") or []
        if not enrolled_signatures:
            return BackendResponse(False, "not_enrolled", 0.0, "unavailable", self.model_version, detail="missing enrolled signatures")

        similarity = max(self._cosine_similarity(enrolled_signature, probe_signature) for enrolled_signature in enrolled_signatures)
        if similarity < 0.82:
            return BackendResponse(False, "token_mismatch", similarity, "pass", self.model_version, detail="user capture signature mismatch")
        return BackendResponse(True, "verified", similarity, "pass", self.model_version)

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
            payload = {"sessions": {}, "users": {}}
        if not isinstance(payload, dict):
            payload = {"sessions": {}, "users": {}}
        payload.setdefault("sessions", {})
        payload.setdefault("users", {})
        return payload

    def _write_store(self, payload: dict[str, Any]) -> None:
        self.store_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "InsightFaceBackend wrote store_path=%s sessions=%d users=%d",
            self.store_path,
            len(payload.get("sessions", {})),
            len(payload.get("users", {})),
        )

    def _hash_token(self, token: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{token}".encode("utf-8")).hexdigest()

    def _normalize_signature(self, signature: list[int]) -> list[float]:
        if not isinstance(signature, list) or len(signature) < 64:
            raise ValueError("Capture signature must include at least 64 numeric samples.")

        samples: list[float] = []
        for value in signature:
            try:
                sample = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("Capture signature values must be numeric.") from exc
            samples.append(max(0.0, min(255.0, sample)) / 255.0)

        mean = sum(samples) / len(samples)
        centered = [sample - mean for sample in samples]
        magnitude = math.sqrt(sum(sample * sample for sample in centered))
        if magnitude <= 1e-9:
            raise ValueError("Capture signature is too uniform to verify.")
        return [sample / magnitude for sample in centered]

    def _cosine_similarity(self, enrolled_signature: list[float], probe_signature: list[float]) -> float:
        if len(enrolled_signature) != len(probe_signature):
            raise ValueError("Capture signature size mismatch.")
        similarity = sum(left * right for left, right in zip(enrolled_signature, probe_signature))
        return max(0.0, min(1.0, similarity))
