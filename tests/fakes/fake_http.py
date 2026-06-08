"""Reusable async HTTP client fakes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeHttpResponse:
    status_code: int = 200
    payload: Any = None
    text: str = ""

    def json(self) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload or {}


@dataclass
class FakeAsyncHttpClient:
    post_response: FakeHttpResponse = field(default_factory=FakeHttpResponse)
    get_response: FakeHttpResponse = field(
        default_factory=lambda: FakeHttpResponse(payload={"result": []})
    )
    post_error: Exception | None = None
    get_error: Exception | None = None
    delete_response: FakeHttpResponse = field(default_factory=FakeHttpResponse)
    delete_error: Exception | None = None
    requests: list[dict[str, Any]] = field(default_factory=list)

    async def __aenter__(self) -> "FakeAsyncHttpClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def aclose(self) -> None:
        return None

    async def post(self, url: str, json: Any = None, timeout: float | None = None) -> FakeHttpResponse:
        self.requests.append({"method": "POST", "url": url, "json": json, "timeout": timeout})
        if self.post_error:
            raise self.post_error
        return self.post_response

    async def get(self, url: str, params: dict[str, Any] | None = None) -> FakeHttpResponse:
        self.requests.append({"method": "GET", "url": url, "params": params})
        if self.get_error:
            raise self.get_error
        return self.get_response

    async def delete(self, url: str, params: dict[str, Any] | None = None) -> FakeHttpResponse:
        self.requests.append({"method": "DELETE", "url": url, "params": params})
        if self.delete_error:
            raise self.delete_error
        return self.delete_response
