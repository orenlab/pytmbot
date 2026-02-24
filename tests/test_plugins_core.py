from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
import yaml

from pytmbot.plugins.models import PluginCoreModel
from pytmbot.plugins.plugins_core import PluginCore


class _PluginCfg(PluginCoreModel):
    enabled: bool
    retries: int


def test_get_config_path_resolves_existing_file_and_fails_for_missing() -> None:
    core = PluginCore()
    get_config_path = cast(Any, core)._PluginCore__get_config_path

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
        core, "_PluginCore__get_config_path", lambda config_name: str(config_file)
    )

    loaded = cast(
        _PluginCfg, core.load_plugin_external_config("plugin.yml", _PluginCfg)
    )
    assert loaded.enabled is True
    assert loaded.retries == 3

    invalid_config = tmp_path / "invalid.yml"
    invalid_config.write_text("enabled: [\n", encoding="utf-8")
    monkeypatch.setattr(
        core, "_PluginCore__get_config_path", lambda config_name: str(invalid_config)
    )
    with pytest.raises(yaml.YAMLError):
        core.load_plugin_external_config("invalid.yml", _PluginCfg)

    monkeypatch.setattr(
        core, "_PluginCore__get_config_path", lambda config_name: str(config_file)
    )
    monkeypatch.setattr(
        yaml,
        "safe_load",
        lambda stream: (_ for _ in ()).throw(RuntimeError("parse-fail")),
    )
    with pytest.raises(RuntimeError, match="parse-fail"):
        core.load_plugin_external_config("plugin.yml", _PluginCfg)


def test_build_plugin_keyboard_delegates_to_keyboards() -> None:
    core = PluginCore()
    calls: list[dict[str, str]] = []

    def _build_reply_keyboard(
        plugin_keyboard_data: dict[str, str] | None = None,
    ) -> str:
        if plugin_keyboard_data is not None:
            calls.append(plugin_keyboard_data)
        return "kbd"

    cast(Any, core).keyboard = SimpleNamespace(
        build_reply_keyboard=_build_reply_keyboard
    )

    keyboard = core.build_plugin_keyboard({"A": "a"})
    assert keyboard == "kbd"
    assert calls == [{"A": "a"}]
