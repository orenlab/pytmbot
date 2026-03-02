from __future__ import annotations

from typing import Protocol

import pytest

import pytmbot.handlers.server_handlers.inline.common as inline_common_module

NOT_MODIFIED_DESCRIPTION = (
    "Bad Request: message is not modified: specified new message content and reply "
    "markup are exactly the same as a current content and reply markup of the message"
)
RATE_LIMIT_DESCRIPTION = "Too Many Requests: retry after 11"


class SupportsEditMessageText(Protocol):
    def edit_message_text(self, **kwargs: str | int | float | bool | None) -> str: ...


def assert_reply_markup_has_callbacks(
    reply_markup: object | None,
    *,
    expected_callbacks: list[str],
) -> None:
    assert reply_markup is not None
    keyboard_rows = getattr(reply_markup, "keyboard", [])
    callback_values = [
        getattr(button, "callback_data", "") for row in keyboard_rows for button in row
    ]
    for callback in expected_callbacks:
        assert callback in callback_values


class _ApiTelegramExceptionStubBase(Exception):
    def __init__(
        self,
        description: str,
        error_code: int = 400,
        *,
        result_json: dict[str, object] | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(description)
        self.description = description
        self.error_code = error_code
        self.result_json = result_json
        self.retry_after = retry_after


def install_api_exception_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> type[_ApiTelegramExceptionStubBase]:
    monkeypatch.setattr(
        inline_common_module, "ApiTelegramException", _ApiTelegramExceptionStubBase
    )
    return _ApiTelegramExceptionStubBase


def patch_not_modified_edit_error(
    monkeypatch: pytest.MonkeyPatch,
    bot: SupportsEditMessageText,
) -> None:
    api_exception_stub = install_api_exception_stub(monkeypatch)
    bot.edit_message_text = lambda **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        api_exception_stub(NOT_MODIFIED_DESCRIPTION)
    )


def patch_rate_limited_edit_error(
    monkeypatch: pytest.MonkeyPatch,
    bot: SupportsEditMessageText,
    *,
    retry_after: int = 11,
) -> None:
    api_exception_stub = install_api_exception_stub(monkeypatch)
    bot.edit_message_text = lambda **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        api_exception_stub(
            RATE_LIMIT_DESCRIPTION,
            429,
            result_json={"parameters": {"retry_after": retry_after}},
        )
    )
