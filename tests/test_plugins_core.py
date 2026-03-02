from __future__ import annotations

from collections.abc import Callable, Generator
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
import yaml

import pytmbot.plugins.plugins_core as plugins_core_module
from pytmbot.keyboards.keyboards import Keyboards
from pytmbot.plugins.models import PluginCoreModel
from pytmbot.plugins.plugins_core import PluginCore


class _PluginCfg(PluginCoreModel):
    enabled: bool
    retries: int


@pytest.fixture(autouse=True)
def _clear_plugin_config_cache() -> Generator[None, None, None]:
    plugins_core_module._plugin_config_cache.clear()
    yield
    plugins_core_module._plugin_config_cache.clear()


def test_get_config_path_resolves_existing_file_and_fails_for_missing() -> None:
    core = PluginCore()
    method_name = "_PluginCore__get_config_path"
    get_config_path_obj = getattr(core, method_name)
    get_config_path = cast(Callable[[str], str], get_config_path_obj)

    with pytest.raises(FileNotFoundError):
        get_config_path("definitely-missing-plugin-config.yaml")

    repo_root = Path(__file__).resolve().parents[1]
    config_name = f"tmp-plugin-config-{uuid4().hex}.yaml"
    config_path = repo_root / config_name
    config_path.write_text("enabled: true\nretries: 2\n", encoding="utf-8")
    try:
        resolved = get_config_path(config_name)
        assert Path(resolved) == config_path
    finally:
        config_path.unlink(missing_ok=True)


def test_load_plugin_external_config_and_yaml_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    core = PluginCore()
    config_file = tmp_path / "plugin.yml"
    config_file.write_text("enabled: true\nretries: 3\n", encoding="utf-8")
    monkeypatch.setattr(
        "pytmbot.plugins.plugins_core.PluginCore._PluginCore__get_config_path",
        lambda self, config_name: str(config_file),
    )

    loaded = cast(
        _PluginCfg, core.load_plugin_external_config("plugin.yml", _PluginCfg)
    )
    assert loaded.enabled is True
    assert loaded.retries == 3

    invalid_config = tmp_path / "invalid.yml"
    invalid_config.write_text("enabled: [\n", encoding="utf-8")
    monkeypatch.setattr(
        "pytmbot.plugins.plugins_core.PluginCore._PluginCore__get_config_path",
        lambda self, config_name: str(invalid_config),
    )
    with pytest.raises(yaml.YAMLError):
        core.load_plugin_external_config("invalid.yml", _PluginCfg)

    monkeypatch.setattr(
        "pytmbot.plugins.plugins_core.PluginCore._PluginCore__get_config_path",
        lambda self, config_name: str(config_file),
    )
    plugins_core_module._plugin_config_cache.pop("plugin.yml", None)
    monkeypatch.setattr(
        yaml,
        "safe_load",
        lambda stream: (_ for _ in ()).throw(RuntimeError("parse-fail")),
    )
    with pytest.raises(RuntimeError, match="parse-fail"):
        core.load_plugin_external_config("plugin.yml", _PluginCfg)


def test_build_plugin_keyboard_delegates_to_keyboards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = PluginCore()
    calls: list[dict[str, str]] = []

    def _build_reply_keyboard(
        self: Keyboards,
        plugin_keyboard_data: dict[str, str] | None = None,
    ) -> str:
        del self
        if plugin_keyboard_data is not None:
            calls.append(plugin_keyboard_data)
        return "kbd"

    monkeypatch.setattr(Keyboards, "build_reply_keyboard", _build_reply_keyboard)

    keyboard = core.build_plugin_keyboard({"A": "a"})
    assert cast(str, keyboard) == "kbd"
    assert calls == [{"A": "a"}]
