"""
modules/interfaces/http_client.py - HTTP client backend ABC for STONE (默行者)

Allows swapping the underlying HTTP library (httpx → aiohttp, etc.)
without changing tool code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class HttpResponse:
    """Standardised HTTP response container."""
    status_code: int
    text: str
    headers: dict[str, str]
    url: str
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class HttpClientInterface(ABC):
    """
    Abstract interface for HTTP client backends.

    Security contract (all implementations must enforce):
      - Block private/loopback IP ranges (SSRF prevention)
      - Max response size: 1 MB
      - Allowed content-types: text/* and application/json only
      - No Host header override
      - Configurable timeout (default 30s)
    """

    @abstractmethod
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        timeout: int = 30,
    ) -> HttpResponse:
        """Send an HTTP request and return a standardised response."""
        ...

    async def get(self, url: str, **kwargs: Any) -> HttpResponse:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, body: str = "", **kwargs: Any) -> HttpResponse:
        return await self.request("POST", url, body=body, **kwargs)


__all__ = ["HttpResponse", "HttpClientInterface"]
