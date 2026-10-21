from __future__ import annotations

import hmac
from collections.abc import Callable
from types import FunctionType

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
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
    _secret_token_matches,
)

_TELEGRAM_IP = "149.154.167.220"
_TOKEN = "12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"


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
    assert server.token not in server.webhook_path
    assert server.webhook_path.startswith("/webhook/")
    assert server.webhook_path.endswith("/")

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


def _server_behind(*trusted_proxies: str) -> WebhookServer:
    server = WebhookServer(
        bot=_FakeBot(_TOKEN), token=_TOKEN, host="127.0.0.1", port=8443
    )
    server.trusted_proxy_networks = server._parse_proxy_networks(list(trusted_proxies))
    return server


def _resolved_client(server: WebhookServer, peer: str, forwarded: str | None) -> str:
    _, client_ip = server._resolve_client_ip(_build_request(peer), forwarded)
    return client_ip


def _resolve_status(server: WebhookServer, peer: str, forwarded: str) -> int:
    with pytest.raises(HTTPException) as error_info:
        server._resolve_client_ip(_build_request(peer), forwarded)
    return error_info.value.status_code


def _telegram_ip_dependency(server: WebhookServer) -> Callable[..., str]:
    """The route's IP check: client resolution plus the Telegram allowlist."""
    for route in server.app.routes:
        if isinstance(route, APIRoute) and route.path == server.WEBHOOK_ROUTE_PATH:
            call = route.dependant.dependencies[0].call
            if isinstance(call, FunctionType):
                return call
    raise AssertionError("Telegram IP dependency was not registered")


def test_spoofed_leftmost_forwarded_entry_is_not_the_client() -> None:
    # nginx `$proxy_add_x_forwarded_for` appends the real peer to whatever the
    # sender put in the header: only the rightmost entry comes from the proxy.
    server = _server_behind("10.0.0.0/8")
    spoofed = f"{_TELEGRAM_IP}, 203.0.113.7"

    assert _resolved_client(server, "10.0.0.5", spoofed) == "203.0.113.7"

    check_ip = _telegram_ip_dependency(server)
    with pytest.raises(HTTPException) as denied:
        check_ip(request=_build_request("10.0.0.5"), x_forwarded_for=spoofed)
    assert denied.value.status_code == 403

    genuine = f"203.0.113.7, {_TELEGRAM_IP}"
    assert check_ip(request=_build_request("10.0.0.5"), x_forwarded_for=genuine) == (
        _TELEGRAM_IP
    )


def test_multi_hop_chain_skips_every_trusted_proxy() -> None:
    server = _server_behind("10.0.0.0/8", "172.16.0.0/12")
    chain = f"198.51.100.1, {_TELEGRAM_IP}, 172.16.0.2, 10.1.1.1"

    assert _resolved_client(server, "10.0.0.5", chain) == _TELEGRAM_IP


def test_untrusted_hop_between_proxies_is_the_client() -> None:
    # 198.51.100.9 is not a configured proxy, so anything left of it is untrusted.
    server = _server_behind("10.0.0.0/8")
    chain = f"{_TELEGRAM_IP}, 198.51.100.9, 10.0.0.7"

    assert _resolved_client(server, "10.0.0.5", chain) == "198.51.100.9"


def test_all_trusted_chain_resolves_to_leftmost_entry() -> None:
    server = _server_behind("10.0.0.0/8")

    assert _resolved_client(server, "10.0.0.5", "10.0.0.7, 10.0.0.8") == "10.0.0.7"
    assert _resolved_client(server, "10.0.0.5", "10.0.0.7") == "10.0.0.7"


@pytest.mark.parametrize(
    "forwarded",
    [
        f"{_TELEGRAM_IP}, not-an-ip",  # the nearest hop is malformed
        "not-an-ip, 10.0.0.7",  # every hop is trusted: the leftmost is walked
        "bad-ip-value",
    ],
)
def test_malformed_entry_in_walked_part_is_rejected(forwarded: str) -> None:
    server = _server_behind("10.0.0.0/8")
    assert _resolve_status(server, "10.0.0.5", forwarded) == 400


def test_garbage_left_of_the_client_is_ignored() -> None:
    server = _server_behind("10.0.0.0/8")
    chain = f"<script>, 999.1.1.1, , {_TELEGRAM_IP}, 10.0.0.7"

    assert _resolved_client(server, "10.0.0.5", chain) == _TELEGRAM_IP


def test_ipv4_mapped_addresses_are_normalized() -> None:
    server = _server_behind("10.0.0.0/8")

    # Dual-stack listeners report IPv4 peers as ::ffff:a.b.c.d.
    assert server._resolve_client_ip(
        _build_request(f"::ffff:{_TELEGRAM_IP}"), None
    ) == (_TELEGRAM_IP, _TELEGRAM_IP)
    assert server._is_trusted_proxy("::ffff:10.0.0.5") is True

    peer_ip, client_ip = server._resolve_client_ip(
        _build_request("::ffff:10.0.0.5"),
        f"::ffff:{_TELEGRAM_IP}, ::ffff:10.0.0.9",
    )
    assert (peer_ip, client_ip) == ("10.0.0.5", _TELEGRAM_IP)

    # A mapped spoof of a trusted proxy does not hide the real client either.
    assert (
        _resolved_client(server, "10.0.0.5", f"::ffff:{_TELEGRAM_IP}, 203.0.113.7")
        == "203.0.113.7"
    )


def test_forwarded_header_guards_are_preserved() -> None:
    server = _server_behind()
    # No trusted proxies configured: a forwarded header is refused outright.
    assert _resolve_status(server, "10.0.0.5", _TELEGRAM_IP) == 403

    server = _server_behind("10.0.0.0/8")
    assert _resolve_status(server, "8.8.8.8", _TELEGRAM_IP) == 403
    assert _resolve_status(server, "testclient", _TELEGRAM_IP) == 403
    assert _resolve_status(server, "10.0.0.5", " , ,") == 400
    assert _resolve_status(server, "10.0.0.5", f"{_TELEGRAM_IP}," * 40) == 400

    # Without a forwarded header the peer is the client, trusted proxy or not.
    assert _resolved_client(server, "10.0.0.5", None) == "10.0.0.5"
    assert _resolved_client(server, "testclient", None) == "testclient"


def test_secret_token_comparison_is_constant_time_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compared: list[tuple[bytes, bytes]] = []
    original_compare = hmac.compare_digest

    def _spy(first: bytes, second: bytes) -> bool:
        compared.append((first, second))
        return original_compare(first, second)

    monkeypatch.setattr(hmac, "compare_digest", _spy)

    assert _secret_token_matches("s3cret", "s3cret") is True
    assert compared == [(b"s3cret", b"s3cret")]
    assert _secret_token_matches("s3creT", "s3cret") is False
    assert _secret_token_matches(None, "s3cret") is False
    assert _secret_token_matches("", "s3cret") is False
    # Non-ASCII and lone surrogates are compared as bytes, not raised on.
    assert _secret_token_matches("сикрет", "s3cret") is False
    assert _secret_token_matches("\udcff", "s3cret") is False
