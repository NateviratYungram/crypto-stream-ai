"""Configurable MT5 client fake for connector and bridge tests."""

from __future__ import annotations

from typing import Any


class FakeMt5Client:
    def __init__(self, **responses: Any):
        self.responses = responses
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _reply(self, name: str, default: Any = None) -> Any:
        value = self.responses.get(name, default)
        return value() if callable(value) else value

    def initialize(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("initialize", args, kwargs))
        return self._reply("initialize", True)

    def login(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("login", args, kwargs))
        return self._reply("login", True)

    def shutdown(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("shutdown", args, kwargs))
        return self._reply("shutdown", True)

    def order_send(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("order_send", args, kwargs))
        return self._reply("order_send", {"retcode": 0})

    def positions_get(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("positions_get", args, kwargs))
        return self._reply("positions_get", [])

    def symbol_info_tick(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("symbol_info_tick", args, kwargs))
        return self._reply("symbol_info_tick", None)

    def copy_rates_from_pos(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("copy_rates_from_pos", args, kwargs))
        return self._reply("copy_rates_from_pos", [])
