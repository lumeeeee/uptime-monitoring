from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

import httpx

from app.db.models import Status


@dataclass(frozen=True)
class CheckRequest:
    target_id: str
    url: str
    timeout_ms: int
    retry_count: int
    retry_backoff_ms: int


@dataclass(frozen=True)
class CheckResultDTO:
    target_id: str
    status: Status
    http_status: int | None
    latency_ms: int | None
    error: str | None
    checked_at: datetime


class Checker:
    def __init__(
        self,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        sleep_func: Callable[[float], Awaitable[Any]] | None = None,
    ) -> None:
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(follow_redirects=True))
        self._sleep = sleep_func or asyncio.sleep

    async def check(self, req: CheckRequest) -> CheckResultDTO:
        attempts = req.retry_count + 1
        timeout_seconds = req.timeout_ms / 1000
        backoff_seconds = req.retry_backoff_ms / 1000

        http_status: int | None = None
        error: str | None = None
        status = Status.DOWN
        started = asyncio.get_running_loop().time()

        async with self._client_factory() as client:
            for attempt in range(attempts):
                try:
                    response = await client.get(req.url, timeout=timeout_seconds)
                    http_status = response.status_code
                    status = Status.UP if 200 <= response.status_code < 400 else Status.DOWN
                    break
                except (httpx.TimeoutException, httpx.ConnectError, httpx.TransportError) as exc:
                    error = _normalize_error(exc)
                    if attempt < attempts - 1:
                        await self._sleep(backoff_seconds)
                        continue
                    status = Status.DOWN
                except Exception as exc:  # pragma: no cover - unexpected
                    error = _normalize_error(exc)
                    status = Status.DOWN
                    break

        elapsed_ms = int((asyncio.get_running_loop().time() - started) * 1000)
        latency_ms = elapsed_ms

        return CheckResultDTO(
            target_id=req.target_id,
            status=status,
            http_status=http_status,
            latency_ms=latency_ms,
            error=error,
            checked_at=datetime.now(timezone.utc),
        )


def _normalize_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error"
    if isinstance(exc, httpx.TransportError):
        return exc.__class__.__name__.lower()
    if isinstance(exc, socket.gaierror):
        return "dns_error"
    return str(exc)
