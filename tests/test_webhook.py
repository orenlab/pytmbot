from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from starlette.requests import Request
from starlette.types import Scope
from telebot import TeleBot
from telebot.types import Update

from pytmbot.models.updates_model import Chat, Message, UpdateModel, User
from pytmbot.webhook import (
    RATELIMIT_EXCEEDED_MESSAGE,
    RateLimit,
    WebhookServer,
    _first_secret,
)


class _FakeBot(TeleBot):
    def __init__(self, token: str) -> None:
        super().__init__(token=token)
        self.token = token

    def process_new_updates(self, _updates: list[Update]) -> None:
        return


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


def test_first_secret_extracts_first_value() -> None:
    assert _first_secret([SecretStr("abc"), SecretStr("def")]) == "abc"
    assert _first_secret(None) is None
    assert _first_secret([]) is None


def test_rate_limit_basic_and_ban_flow() -> None:
    limiter = RateLimit(limit=2, period=10, ban_threshold=3)
    ip = "10.0.0.1"
    assert limiter.is_rate_limited(ip) is False
    assert limiter.is_rate_limited(ip) is False
    assert limiter.is_rate_limited(ip) is True
    assert limiter.is_rate_limited(ip) is True
    assert RATELIMIT_EXCEEDED_MESSAGE == "Rate limit exceeded"


def test_webhook_server_proxy_network_and_ip_resolution() -> None:
    server = WebhookServer(
        bot=_FakeBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"),
        token="12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE",
        host="127.0.0.1",
        port=8443,
    )

    # No forwarded header -> direct client IP
    peer_ip, client_ip = server._resolve_client_ip(
        request=_build_request("149.154.167.220"),
        x_forwarded_for=None,
    )
    assert peer_ip == "149.154.167.220"
    assert client_ip == "149.154.167.220"

    # Configure trusted proxies and resolve forwarded IP
    server.trusted_proxy_networks = server._parse_proxy_networks(["10.0.0.0/8"])
    peer_ip, client_ip = server._resolve_client_ip(
        request=_build_request("10.0.0.5"),
        x_forwarded_for="149.154.167.220",
    )
    assert peer_ip == "10.0.0.5"
    assert client_ip == "149.154.167.220"


def test_webhook_server_rejects_untrusted_forwarded_source() -> None:
    server = WebhookServer(
        bot=_FakeBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"),
        token="12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE",
        host="127.0.0.1",
        port=8443,
    )
    server.trusted_proxy_networks = server._parse_proxy_networks(["10.0.0.0/8"])

    with pytest.raises(HTTPException) as exc:
        server._resolve_client_ip(
            request=_build_request("8.8.8.8"),
            x_forwarded_for="149.154.167.220",
        )
    assert exc.value.status_code == 403


def test_webhook_server_get_update_type() -> None:
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
                "from": User(id=1, is_bot=False, first_name="Den").model_dump(),
                "text": "hi",
            }
        ),
    )
    assert server._get_update_type(update) == "message"
