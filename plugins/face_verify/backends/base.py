from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class BackendResponse:
    ok: bool
    reason_code: str
    face_score: float
    liveness_status: str
    model_version: str
    verified_until: int = 0
    detail: str = ""


class FaceBackend(Protocol):
    provider_name: str

    def enroll(self, session_id: str, token: str) -> str: ...
    def verify(self, session_id: str, token: str, liveness: str) -> BackendResponse: ...
    def enroll_capture(self, session_id: str, signature: list[int]) -> str: ...
    def verify_capture(self, session_id: str, signature: list[int], liveness: str) -> BackendResponse: ...
    def enroll_user_capture(self, user_id: str, signature: list[int]) -> str: ...
    def verify_user_capture(self, user_id: str, signature: list[int], liveness: str) -> BackendResponse: ...
    def clear(self, session_id: str) -> bool: ...
    def status(self, session_id: str) -> dict[str, int | bool]: ...
