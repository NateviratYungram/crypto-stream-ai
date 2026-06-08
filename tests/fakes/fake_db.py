"""Simple DB cursor/connection fakes with execution history."""

from __future__ import annotations

from collections import deque
from typing import Any


class FakeCursor:
    def __init__(
        self,
        fetchone_results: list[Any] | None = None,
        fetchall_results: list[Any] | None = None,
    ):
        self.fetchone_results = deque(fetchone_results or [])
        self.fetchall_results = deque(fetchall_results or [])
        self.executed: list[tuple[str, Any]] = []
        self.closed = False

    def execute(self, query: str, params: Any = None) -> None:
        self.executed.append((query, params))

    def fetchone(self) -> Any:
        return self.fetchone_results.popleft() if self.fetchone_results else None

    def fetchall(self) -> Any:
        return self.fetchall_results.popleft() if self.fetchall_results else []

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


class FakeConnection:
    def __init__(self, cursor: FakeCursor | None = None):
        self.cursor_instance = cursor or FakeCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True
