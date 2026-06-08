"""Deterministic clock helpers for tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class FrozenClock:
    current: datetime

    @classmethod
    def utc(cls, value: datetime | None = None) -> "FrozenClock":
        base = value or datetime(2026, 1, 1, tzinfo=timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        return cls(base)

    def now(self) -> datetime:
        return self.current

    def time(self) -> float:
        return self.current.timestamp()

    def tick(self, seconds: float = 1.0) -> datetime:
        self.current = self.current + timedelta(seconds=seconds)
        return self.current

    def set(self, value: datetime) -> datetime:
        self.current = value
        return self.current
