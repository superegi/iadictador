from __future__ import annotations

import time
from typing import Any


def now_ms() -> int:
    return int(time.time() * 1000)


def usage_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    out: dict[str, Any] = {}

    try:
        if hasattr(value, "model_dump"):
            dumped = value.model_dump()
            if isinstance(dumped, dict):
                out.update(dumped)
    except Exception:
        pass

    for key in [
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
    ]:
        try:
            v = getattr(value, key)
        except Exception:
            v = None
        if v is not None:
            out[key] = v

    return out


class UsageLog:
    def __init__(self, job_id: str = "", username: str = "", ot_id: str = "") -> None:
        self.job_id = job_id
        self.username = username
        self.ot_id = ot_id
        self.started_at_ms = now_ms()
        self.calls: list[dict[str, Any]] = []

    def add(
        self,
        *,
        stage: str,
        provider: str = "openai",
        model: str = "",
        started_at_ms: int,
        ended_at_ms: int,
        usage: Any = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.calls.append(
            {
                "stage": stage,
                "provider": provider,
                "model": model,
                "started_at_ms": started_at_ms,
                "ended_at_ms": ended_at_ms,
                "duration_ms": max(0, ended_at_ms - started_at_ms),
                "usage": usage_to_dict(usage),
                "extra": extra or {},
            }
        )

    def to_dict(self) -> dict[str, Any]:
        ended = now_ms()
        return {
            "job_id": self.job_id,
            "ot_id": self.ot_id,
            "username": self.username,
            "started_at_ms": self.started_at_ms,
            "ended_at_ms": ended,
            "duration_ms": max(0, ended - self.started_at_ms),
            "total_calls": len(self.calls),
            "calls": self.calls,
        }
