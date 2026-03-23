from __future__ import annotations

import types

import pytest

from pytmbot.utils.emoji import EmojiConverter


def test_emoji_converter_uses_emojize_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    converter = EmojiConverter()
    fake_module = types.SimpleNamespace(emojize=lambda text: f"ok:{text}")
    monkeypatch.setattr("pytmbot.utils.emoji.import_module", lambda _name: fake_module)

    assert converter.get_emoji("house") == "ok::house:"


def test_emoji_converter_rejects_missing_emojize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    converter = EmojiConverter()
    fake_module = types.SimpleNamespace()
    monkeypatch.setattr("pytmbot.utils.emoji.import_module", lambda _name: fake_module)

    with pytest.raises(TypeError, match="emojize"):
        _ = converter.emoji_library
