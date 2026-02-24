from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from types import FunctionType, SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Scope
from telebot import TeleBot

import pytmbot.webhook as webhook_module
from pytmbot.exceptions import BotException, InitializationError
from pytmbot.webhook import RateLimit, WebhookServer


class _FakeBot(TeleBot):
    def __init__(self, token: str) -> None:
        super().__init__(token=token)
        self.token = token


def _build_request(host: str, path: str = "/") -> Request:
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [],
        "client": (host, 12345),
        "scheme": "http",
        "query_string": b"",
        "server": ("testserver", 80),
    }
    return Request(scope)


def _build_server() -> WebhookServer:
    return WebhookServer(
        bot=_FakeBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"),
        token="12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE",
        host="127.0.0.1",
        port=8443,
    )


def test_rate_limit_cleanup_and_evict_paths() -> None:
    limiter = RateLimit(limit=1, period=1, max_tracked_ips=2)
    limiter._evict_oldest_ip()  # no state path

    limiter.banned_ips["10.0.0.1"] = datetime.now() - timedelta(hours=2)
    limiter.requests["10.0.0.2"] = deque()
    limiter.requests["10.0.0.3"] = deque()
    limiter._last_seen["10.0.0.1"] = 1.0
    limiter._last_seen["10.0.0.2"] = 2.0
    limiter._last_seen["10.0.0.3"] = 3.0

    limiter._cleanup_state(current_time=10_000.0)
    assert "10.0.0.1" not in limiter.banned_ips
    assert len(limiter._last_seen) <= limiter.max_tracked_ips


def test_not_found_exception_handler_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _build_server()
    handler = cast(
        Callable[[Request, HTTPException], Awaitable[Response]],
        server.app.exception_handlers.get(404),
    )
    assert callable(handler)

    request = _build_request("149.154.167.220", "/missing")
    not_found = HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(
        type(server.rate_limiter_404), "is_rate_limited", lambda self, _ip: False
    )

    async def _call_not_found() -> Response:
        return await handler(request, not_found)

    response: Response = asyncio.run(_call_not_found())
    assert response.status_code == 404

    monkeypatch.setattr(
        type(server.rate_limiter_404), "is_rate_limited", lambda self, _ip: True
    )
    limited_response: Response = asyncio.run(_call_not_found())
    assert limited_response.status_code == 429


def test_webhook_verify_telegram_dependency_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _build_server()
    dependency_call: FunctionType | None = None
    for route in server.app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path == server.WEBHOOK_ROUTE_PATH and "POST" in route.methods:
            dependencies = route.dependant.dependencies
            dependency = dependencies[0] if dependencies else None
            call = getattr(dependency, "call", None)
            if isinstance(call, FunctionType):
                dependency_call = call
                break

    assert dependency_call is not None
    request = _build_request("149.154.167.220", server.webhook_path)

    monkeypatch.setattr(
        server.telegram_ip_validator,
        "is_telegram_ip",
        lambda _ip: False,
    )
    with pytest.raises(HTTPException) as denied:
        dependency_call(request=request, x_forwarded_for=None)
    assert denied.value.status_code == 403

    monkeypatch.setattr(
        server.telegram_ip_validator,
        "is_telegram_ip",
        lambda _ip: True,
    )
    assert dependency_call(request=request, x_forwarded_for=None) == "149.154.167.220"


@pytest.mark.parametrize(
    ("error", "expected_exception"),
    [
        (FileNotFoundError("missing"), InitializationError),
        (PermissionError("denied"), InitializationError),
        (OSError("os"), InitializationError),
        (RuntimeError("unexpected"), BotException),
    ],
)
def test_webhook_start_exception_mapping(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_exception: type[Exception],
) -> None:
    server = _build_server()
    monkeypatch.setattr(
        webhook_module,
        "_get_webhook_config",
        lambda: SimpleNamespace(cert=None, cert_key=None),
    )
    monkeypatch.setattr(
        webhook_module.uvicorn,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(expected_exception):
        server.start()
