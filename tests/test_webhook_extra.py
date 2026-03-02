from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from starlette.requests import Request
from starlette.types import Scope
from telebot import TeleBot

import pytmbot.webhook as webhook_module
from pytmbot.exceptions import InitializationError
from pytmbot.models.updates_model import Chat, Message, UpdateModel, User
from pytmbot.webhook import RATELIMIT_EXCEEDED_MESSAGE, RateLimit, WebhookServer

type _PayloadScalar = str | int | float | bool | None
type _PayloadValue = (
    _PayloadScalar | list[str] | list["_PayloadValue"] | dict[str, "_PayloadValue"]
)
type _PayloadDict = dict[str, _PayloadValue]


class _FakeBot(TeleBot):
    def __init__(self, token: str) -> None:
        super().__init__(token=token)
        self.token = token


def _build_request(host: str) -> Request:
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "client": (host, 12345),
        "scheme": "http",
        "query_string": b"",
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_rate_limit_ban_and_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = RateLimit(limit=10, period=10, ban_threshold=2)
    ip = "10.10.10.10"

    assert limiter.is_rate_limited(ip) is False
    assert limiter.is_rate_limited(ip) is False
    assert limiter.is_rate_limited(ip) is True
    assert limiter.is_banned(ip) is True

    limiter.banned_ips[ip] = datetime.now() - timedelta(hours=2)
    assert limiter.is_banned(ip) is False
    assert ip not in limiter.banned_ips
    assert RATELIMIT_EXCEEDED_MESSAGE == "Rate limit exceeded"


def test_rate_limit_cleanup_and_evict_oldest() -> None:
    limiter = RateLimit(limit=5, period=5, max_tracked_ips=2)
    limiter.requests = {
        "1.1.1.1": deque([]),
        "2.2.2.2": deque([1.0]),
        "3.3.3.3": deque([2.0]),
    }
    limiter._last_seen = {
        "1.1.1.1": 1.0,
        "2.2.2.2": 2.0,
        "3.3.3.3": 3.0,
    }
    limiter._cleanup_state(1000.0)
    assert "1.1.1.1" not in limiter._last_seen
    assert len(limiter._last_seen) <= 2


def test_webhook_server_proxy_helpers_and_resolve_errors() -> None:
    server = WebhookServer(
        bot=_FakeBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"),
        token="12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE",
        host="127.0.0.1",
        port=8443,
    )
    server.trusted_proxy_networks = server._parse_proxy_networks(
        ["10.0.0.0/8", "127.0.0.1"]
    )
    assert server._is_trusted_proxy("10.1.1.1") is True
    assert server._is_trusted_proxy("invalid-ip") is False

    with pytest.raises(HTTPException) as no_proxy_cfg:
        server.trusted_proxy_networks = []
        server._resolve_client_ip(_build_request("10.0.0.5"), "149.154.167.220")
    assert no_proxy_cfg.value.status_code == 403

    with pytest.raises(HTTPException) as untrusted_proxy:
        server.trusted_proxy_networks = server._parse_proxy_networks(["10.0.0.0/8"])
        server._resolve_client_ip(_build_request("8.8.8.8"), "149.154.167.220")
    assert untrusted_proxy.value.status_code == 403

    with pytest.raises(HTTPException) as too_long:
        server._resolve_client_ip(_build_request("10.0.0.5"), "a" * 513)
    assert too_long.value.status_code == 400

    with pytest.raises(HTTPException) as invalid_forwarded:
        server._resolve_client_ip(_build_request("10.0.0.5"), "bad-ip-value")
    assert invalid_forwarded.value.status_code == 400


def test_get_webhook_config_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        webhook_module, "settings", SimpleNamespace(webhook_config=None)
    )
    with pytest.raises(InitializationError) as exc_info:
        webhook_module._get_webhook_config()
    assert exc_info.value.context.error_code == "WEBHOOK_CONFIG_MISSING"


def test_webhook_manager_setup_and_remove(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    remove_calls = {"count": 0}
    set_calls: list[_PayloadDict] = []

    monkeypatch.setattr(bot, "get_webhook_info", lambda timeout=None: "webhook-info")

    def _remove_webhook() -> bool:
        remove_calls["count"] += 1
        return True

    def _set_webhook(
        url: str | None = None,
        certificate: str | None = None,
        max_connections: int | None = None,
        allowed_updates: list[str] | None = None,
        ip_address: str | None = None,
        drop_pending_updates: bool | None = None,
        timeout: int | None = None,
        secret_token: str | None = None,
    ) -> bool:
        del max_connections, ip_address
        set_calls.append(
            {
                "url": url,
                "certificate": certificate,
                "allowed_updates": allowed_updates,
                "drop_pending_updates": drop_pending_updates,
                "timeout": timeout,
                "secret_token": secret_token,
            }
        )
        return True

    monkeypatch.setattr(bot, "remove_webhook", _remove_webhook)
    monkeypatch.setattr(bot, "set_webhook", _set_webhook)

    manager = webhook_module.WebhookManager(bot=bot, url="example.com", port=8443)

    monkeypatch.setattr(
        webhook_module,
        "_get_webhook_config",
        lambda: SimpleNamespace(cert=[SecretStr("cert.pem")]),
    )

    manager.setup_webhook("/webhook/path/")
    assert remove_calls["count"] == 1
    assert len(set_calls) == 1
    assert str(set_calls[0]["url"]).startswith("https://example.com:8443/webhook/path/")
    assert set_calls[0]["certificate"] == "cert.pem"

    manager.remove_webhook()
    assert remove_calls["count"] == 2


def test_webhook_server_update_error_context() -> None:
    server = WebhookServer(
        bot=_FakeBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"),
        token="12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE",
        host="127.0.0.1",
        port=8443,
    )
    update = UpdateModel(
        update_id=1,
        message=Message.model_validate(
            {
                "message_id": 1,
                "date": 1,
                "chat": Chat(id=1, type="private").model_dump(),
                "from": User(id=1, is_bot=False, first_name="Test").model_dump(),
                "text": "hello",
            }
        ),
    )
    assert server._get_update_error_context(update) == {
        "update_id": 1,
        "update_type": "message",
    }


def test_webhook_server_start_port_and_uvicorn_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = WebhookServer(
        bot=_FakeBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"),
        token="12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE",
        host="127.0.0.1",
        port=8443,
    )

    privileged = WebhookServer(
        bot=_FakeBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"),
        token="12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE",
        host="127.0.0.1",
        port=443,
    )
    with pytest.raises(InitializationError):
        privileged.start()

    uvicorn_calls: list[_PayloadDict] = []

    def _fake_uvicorn_run(_app: SimpleNamespace, **kwargs: _PayloadValue) -> None:
        uvicorn_calls.append(kwargs)

    monkeypatch.setattr("pytmbot.webhook.uvicorn.run", _fake_uvicorn_run)
    monkeypatch.setattr(
        webhook_module,
        "_get_webhook_config",
        lambda: SimpleNamespace(cert=None, cert_key=None),
    )
    server.start()
    assert uvicorn_calls[-1]["proxy_headers"] is False
    assert "ssl_certfile" not in uvicorn_calls[-1]

    monkeypatch.setattr(
        webhook_module,
        "_get_webhook_config",
        lambda: SimpleNamespace(
            cert=[SecretStr("/tmp/test.crt")],
            cert_key=[SecretStr("/tmp/test.key")],
        ),
    )
    server.start()
    assert uvicorn_calls[-1]["ssl_certfile"] == "/tmp/test.crt"
    assert uvicorn_calls[-1]["ssl_keyfile"] == "/tmp/test.key"
