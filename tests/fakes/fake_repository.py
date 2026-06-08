"""Small in-memory repository fake for service and policy tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class FakeRepository:
    def __init__(self, initial: dict[str, Any] | None = None):
        self.storage: dict[str, Any] = deepcopy(initial or {})
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def put(self, key: str, value: Any) -> Any:
        self.calls.append(("put", (key, deepcopy(value)), {}))
        self.storage[key] = deepcopy(value)
        return value

    def get(self, key: str, default: Any = None) -> Any:
        self.calls.append(("get", (key,), {"default": default}))
        return deepcopy(self.storage.get(key, default))

    def delete(self, key: str) -> Any:
        self.calls.append(("delete", (key,), {}))
        return self.storage.pop(key, None)

    def list(self) -> dict[str, Any]:
        self.calls.append(("list", (), {}))
        return deepcopy(self.storage)

    def clear(self) -> None:
        self.calls.append(("clear", (), {}))
        self.storage.clear()
