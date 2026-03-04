from __future__ import annotations

import json
import time
from types import FunctionType

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.types import Scope
from telebot import TeleBot
from telebot.types import Update

from pytmbot.models.updates_model import UpdateModel
from pytmbot.webhook import WebhookServer

type _PayloadScalar = str | int | float | bool | None
type _PayloadValue = _PayloadScalar | list["_PayloadValue"] | dict[str, "_PayloadValue"]
type _PayloadDict = dict[str, _PayloadValue]


class _FakeBot(TeleBot):
    def __init__(self, token: str) -> None:
        super().__init__(token=token)
        self.token = token

    def process_new_updates(self, updates: list[Update]) -> None:
        del updates
        return


def _build_update_payload() -> _PayloadDict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": 1, "type": "private"},
            "from": {
                "id": 123,
                "is_bot": False,
                "first_name": "Test",
                "username": "tester",
            },
            "text": "hello",
        },
    }


def _build_request_without_client() -> Request:
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "client": None,
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


def _get_webhook_endpoint(server: WebhookServer) -> FunctionType:
    for route in server.app.routes:
        methods: set[str] = set(getattr(route, "methods", set()))
        path = getattr(route, "path", "")
        if path == server.WEBHOOK_ROUTE_PATH and "POST" in methods:
            endpoint = getattr(route, "endpoint", None)
            if isinstance(endpoint, FunctionType):
                return endpoint
    raise AssertionError("Webhook endpoint was not registered")


def _build_update_model() -> UpdateModel:
    return UpdateModel.model_validate(_build_update_payload())


def test_resolve_client_ip_requires_peer_address() -> None:
    server = _build_server()
    with pytest.raises(HTTPException) as exc_info:
        server._resolve_client_ip(_build_request_without_client(), None)
    assert exc_info.value.status_code == 400


def test_webhook_endpoint_preserves_guard_status_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _build_server()
    endpoint = _get_webhook_endpoint(server)
    update = _build_update_model()

    with pytest.raises(HTTPException) as token_exc:
        endpoint(
            path_token=server.webhook_path_token,
            update=update,
            client_ip="149.154.167.220",
            x_telegram_bot_api_secret_token="invalid",
        )
    assert token_exc.value.status_code == 403
    assert token_exc.value.detail == "Invalid secret token"

    monkeypatch.setattr(
        type(server.rate_limiter),
        "is_rate_limited",
        lambda self, _ip: True,
    )
    with pytest.raises(HTTPException) as rate_exc:
        endpoint(
            path_token=server.webhook_path_token,
            update=update,
            client_ip="149.154.167.220",
            x_telegram_bot_api_secret_token=server.secret_token,
        )
    assert rate_exc.value.status_code == 429
    assert rate_exc.value.detail == "Rate limit exceeded"


def test_webhook_endpoint_value_error_and_unexpected_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _build_server()
    endpoint = _get_webhook_endpoint(server)
    update = _build_update_model()

    monkeypatch.setattr(
        server.bot,
        "process_new_updates",
        lambda updates: (_ for _ in ()).throw(ValueError("bad")),
    )
    with pytest.raises(HTTPException) as value_error_exc:
        endpoint(
            path_token=server.webhook_path_token,
            update=update,
            client_ip="149.154.167.220",
            x_telegram_bot_api_secret_token=server.secret_token,
        )
    assert value_error_exc.value.status_code == 400
    assert value_error_exc.value.detail == "Invalid update format"

    monkeypatch.setattr(
        server.bot,
        "process_new_updates",
        lambda updates: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(HTTPException) as runtime_exc:
        endpoint(
            path_token=server.webhook_path_token,
            update=update,
            client_ip="149.154.167.220",
            x_telegram_bot_api_secret_token=server.secret_token,
        )
    assert runtime_exc.value.status_code == 500
    assert runtime_exc.value.detail == "Internal server error"


def test_webhook_endpoint_success_and_request_counter_increments() -> None:
    server = _build_server()
    endpoint = _get_webhook_endpoint(server)

    server.request_counter = 100

    response = endpoint(
        path_token=server.webhook_path_token,
        update=_build_update_model(),
        client_ip="149.154.167.220",
        x_telegram_bot_api_secret_token=server.secret_token,
    )
    parsed_body = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 200
    assert parsed_body["status"] == "ok"
    assert server.request_counter == 101


def test_webhook_endpoint_returns_404_for_unknown_path() -> None:
    server = _build_server()
    endpoint = _get_webhook_endpoint(server)

    with pytest.raises(HTTPException) as exc_info:
        endpoint(
            path_token="unknown-path-token",
            update=_build_update_model(),
            client_ip="149.154.167.220",
            x_telegram_bot_api_secret_token=server.secret_token,
        )

    assert exc_info.value.status_code == 404


def test_webhook_endpoint_rotates_credentials_at_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _build_server()
    endpoint = _get_webhook_endpoint(server)
    previous_path_token = server.webhook_path_token
    previous_secret_token = server.secret_token
    setup_calls: list[_PayloadDict] = []

    def _fake_setup_webhook(
        _self: WebhookServer,
        webhook_path: str,
        *,
        secret_token: str | None = None,
        drop_pending_updates: bool = True,
        reset_existing: bool = True,
    ) -> None:
        setup_calls.append(
            {
                "webhook_path": webhook_path,
                "secret_token": secret_token,
                "drop_pending_updates": drop_pending_updates,
                "reset_existing": reset_existing,
            }
        )

    monkeypatch.setattr(
        type(server.webhook_manager), "setup_webhook", _fake_setup_webhook
    )
    monkeypatch.setattr(type(server), "WEBHOOK_ROTATION_REQUEST_THRESHOLD", 101)

    server.request_counter = 100
    response = endpoint(
        path_token=previous_path_token,
        update=_build_update_model(),
        client_ip="149.154.167.220",
        x_telegram_bot_api_secret_token=previous_secret_token,
    )

    deadline = time.monotonic() + 1.0
    while not setup_calls and time.monotonic() < deadline:
        time.sleep(0.01)

    assert response.status_code == 200
    assert setup_calls
    assert setup_calls[0]["drop_pending_updates"] is False
    assert setup_calls[0]["reset_existing"] is False
    assert server.webhook_path_token != previous_path_token
    assert server.secret_token != previous_secret_token
    assert server.request_counter == 0

    grace_response = endpoint(
        path_token=previous_path_token,
        update=_build_update_model(),
        client_ip="149.154.167.220",
        x_telegram_bot_api_secret_token=previous_secret_token,
    )
    assert grace_response.status_code == 200
