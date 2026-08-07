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
    assert any("Server" in button.text for button in built)
    assert built[0].style == "primary"


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


def test_build_reply_keyboard_is_persistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyboards_module.Keyboards._get_keyboard_data.cache_clear()
    monkeypatch.setattr(keyboards_module, "keyboard_settings", KeyboardSettings())

    markup = Keyboards().build_reply_keyboard("server_keyboard")
    assert markup.is_persistent is True


def test_main_reply_keyboard_applies_button_styles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyboards_module.Keyboards._get_keyboard_data.cache_clear()
    monkeypatch.setattr(keyboards_module, "keyboard_settings", KeyboardSettings())

    markup = Keyboards().build_reply_keyboard("main_keyboard")
    styles_by_title: dict[str, str | None] = {}
    for row in markup.keyboard:
        for button in row:
            if isinstance(button, dict):
                text = str(button.get("text") or "")
                style = button.get("style")
            else:
                text = str(getattr(button, "text", "") or "")
                style = getattr(button, "style", None)
            for title in (
                "Server",
                "Docker",
                "Quick view",
                "Health",
                "Back to main menu",
            ):
                if title in text:
                    styles_by_title[title] = style if isinstance(style, str) else None
    assert styles_by_title == {
        "Server": "primary",
        "Docker": "primary",
        "Quick view": "primary",
        "Health": "primary",
        "Back to main menu": "danger",
    }


def test_build_nav_keyboard_and_resolve_reply_markup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyboards_module.Keyboards._get_keyboard_data.cache_clear()
    monkeypatch.setattr(keyboards_module, "keyboard_settings", KeyboardSettings())

    nav = keyboards_module.build_nav_keyboard(keyboards_module.NAV_MAIN)
    assert isinstance(nav, ReplyKeyboardMarkup)
    assert nav.is_persistent is True

    inline = Keyboards().build_inline_keyboard(
        ButtonData(text="Open", callback_data="ok")
    )
    assert keyboards_module.resolve_reply_markup(inline) is inline
    assert keyboards_module.resolve_reply_markup(None) is None
    resolved = keyboards_module.resolve_reply_markup(
        None, nav_keyboard=keyboards_module.NAV_SERVER
    )
    assert isinstance(resolved, ReplyKeyboardMarkup)


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
