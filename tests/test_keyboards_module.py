from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from telebot.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

import pytmbot.keyboards.keyboards as keyboards_module
from pytmbot.exceptions import KeyboardError
from pytmbot.keyboards.keyboards import ButtonData, Keyboards
from pytmbot.settings import KeyboardSettings


def _flatten_reply_texts(markup: ReplyKeyboardMarkup) -> list[str]:
    texts: list[str] = []
    for row in markup.keyboard:
        for button in row:
            if isinstance(button, str):
                texts.append(button)
                continue

            if isinstance(button, dict):
                text = button.get("text")
                if isinstance(text, str):
                    texts.append(text)
                continue

            text_attr = getattr(button, "text", None)
            if isinstance(text_attr, str):
                texts.append(text_attr)
    return texts


def _flatten_inline_callback_data(markup: InlineKeyboardMarkup) -> list[str]:
    callbacks: list[str] = []
    for row in markup.keyboard:
        for button in row:
            callback_data = getattr(button, "callback_data", None)
            if isinstance(callback_data, str):
                callbacks.append(callback_data)
    return callbacks


def test_button_data_validation_errors() -> None:
    with pytest.raises(ValueError):
        ButtonData(text="", callback_data="ok")
    with pytest.raises(ValueError):
        ButtonData(text="ok", callback_data="")


def test_resolve_keyboard_settings_type_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keyboards_module, "keyboard_settings", SimpleNamespace())
    with pytest.raises(KeyboardError):
        keyboards_module._resolve_keyboard_settings()


def test_get_keyboard_data_default_and_invalid_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyboards_module.Keyboards._get_keyboard_data.cache_clear()
    monkeypatch.setattr(keyboards_module, "keyboard_settings", KeyboardSettings())

    default_data = keyboards_module.Keyboards._get_keyboard_data(None)
    assert "rocket" in default_data

    with pytest.raises(KeyboardError):
        keyboards_module.Keyboards._get_keyboard_data("not_existing_keyboard")


def test_build_reply_keyboard_with_back_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyboards_module.Keyboards._get_keyboard_data.cache_clear()
    monkeypatch.setattr(keyboards_module, "keyboard_settings", KeyboardSettings())

    keyboard = Keyboards()
    markup = keyboard.build_reply_keyboard("server_keyboard")
    assert isinstance(markup, ReplyKeyboardMarkup)

    texts = _flatten_reply_texts(markup)
    assert Keyboards.BACK_BUTTON_TEXT in texts


def test_construct_keyboard_validation() -> None:
    keyboard = Keyboards()

    with pytest.raises(KeyboardError):
        keyboard._construct_keyboard(cast(dict[str, str], "not-a-dict"))

    with pytest.raises(KeyboardError):
        keyboard._construct_keyboard({})

    built = keyboard._construct_keyboard({"rocket": "Server", "": "Ignored"})
    assert any("Server" in value for value in built)


def test_build_inline_keyboard_truncates_and_validates_buttons() -> None:
    keyboard = Keyboards()

    long_payload = "x" * 120
    markup = keyboard.build_inline_keyboard(
        ButtonData(text="Open", callback_data=long_payload)
    )
    callbacks = _flatten_inline_callback_data(markup)
    assert callbacks
    assert len(callbacks[0]) == keyboard.MAX_CALLBACK_DATA_LENGTH

    with pytest.raises(KeyboardError):
        keyboard.build_inline_keyboard(
            cast(list[ButtonData], [ButtonData("A", "ok"), cast(ButtonData, "bad")])
        )


def test_build_referer_keyboards_validation_and_callback_size() -> None:
    keyboard = Keyboards()

    with pytest.raises(KeyboardError):
        keyboard.build_referer_main_keyboard("")
    with pytest.raises(KeyboardError):
        keyboard.build_referer_inline_keyboard("")

    inline = keyboard.build_referer_inline_keyboard("__get_logs__:container:123456")
    callbacks = _flatten_inline_callback_data(inline)
    assert callbacks
    assert len(callbacks[0]) <= keyboard.MAX_CALLBACK_DATA_LENGTH
