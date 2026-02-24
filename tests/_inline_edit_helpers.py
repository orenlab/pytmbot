from __future__ import annotations

from typing import Protocol

import pytest

import pytmbot.handlers.server_handlers.inline.common as inline_common_module

NOT_MODIFIED_DESCRIPTION = (
    "Bad Request: message is not modified: specified new message content and reply "
    "markup are exactly the same as a current content and reply markup of the message"
)


class SupportsEditMessageText(Protocol):
    def edit_message_text(self, **kwargs: object) -> str: ...


def install_api_exception_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> type[Exception]:
    class _ApiTelegramExceptionStub(Exception):
        def __init__(self, description: str, error_code: int = 400) -> None:
            super().__init__(description)
            self.description = description
            self.error_code = error_code

    monkeypatch.setattr(
        inline_common_module, "ApiTelegramException", _ApiTelegramExceptionStub
    )
    return _ApiTelegramExceptionStub


def patch_not_modified_edit_error(
    monkeypatch: pytest.MonkeyPatch,
    bot: SupportsEditMessageText,
) -> None:
    api_exception_stub = install_api_exception_stub(monkeypatch)
    bot.edit_message_text = lambda **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        api_exception_stub(NOT_MODIFIED_DESCRIPTION)
    )
