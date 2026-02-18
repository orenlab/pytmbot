from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest
from telebot import TeleBot

import pytmbot.plugins.plugin_manager as plugin_manager_module
from pytmbot.plugins.models import PluginsPermissionsModel
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.plugins.plugin_manager import PluginManager, _PluginInfo


class _TestPlugin(PluginInterface):
    registered_calls = 0
    cleanup_calls = 0

    def register(self) -> None:
        type(self).registered_calls += 1

    def cleanup(self) -> None:
        type(self).cleanup_calls += 1


@pytest.fixture(autouse=True)
def _reset_plugin_manager_singleton() -> None:
    PluginManager._instance = None
    PluginManager._index_keys.clear()
    PluginManager._plugin_names.clear()
    PluginManager._plugin_descriptions.clear()
    PluginManager._plugin_instances.clear()
    PluginManager._loaded_plugins.clear()
    _TestPlugin.registered_calls = 0
    _TestPlugin.cleanup_calls = 0


def _build_config_module(
    *,
    base_permission: bool = True,
    need_host: bool = False,
) -> ModuleType:
    module = ModuleType("test_plugin_config")
    module.__dict__.update(
        {
            "PLUGIN_NAME": "test_plugin",
            "PLUGIN_VERSION": "1.0.0",
            "PLUGIN_DESCRIPTION": "Test plugin",
            "PLUGIN_COMMANDS": {"/test": "Test command"},
            "PLUGIN_INDEX_KEY": {"test": "plugin"},
            "PLUGIN_RESOURCE_LIMITS": {
                "max_memory_mb": 10,
                "max_cpu_percent": 20,
                "execution_timeout_sec": 5,
            },
            "PLUGIN_PERMISSIONS": PluginsPermissionsModel(
                base_permission=base_permission,
                need_running_on_host_machine=need_host,
            ),
        }
    )
    return module


def test_plugin_name_validation_rules() -> None:
    assert PluginManager._validate_plugin_name("monitor") is True
    assert PluginManager._validate_plugin_name("outline_plugin") is True
    assert PluginManager._validate_plugin_name("bad-plugin") is False
    assert PluginManager._validate_plugin_name("../evil") is False
    assert PluginManager._validate_plugin_name("with space") is False
    assert PluginManager._validate_plugin_name("semi;colon") is False


def test_validate_plugin_path_rejects_traversal(tmp_path: Path) -> None:
    manager = PluginManager()
    manager._plugin_base_path = tmp_path / "plugins"
    manager._plugin_base_path.mkdir(parents=True, exist_ok=True)
    assert manager._validate_plugin_path("valid_plugin") is True
    assert manager._validate_plugin_path("../outside") is False


def test_extract_plugin_permissions_and_info(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = PluginManager()
    config = _build_config_module(base_permission=True, need_host=False)

    permissions = manager._extract_plugin_permissions(config)
    assert permissions.base_permission is True

    monkeypatch.setattr(plugin_manager_module, "is_running_in_docker", lambda: False)
    info = manager._extract_plugin_info(config)
    assert info is not None
    assert info.name == "test_plugin"
    assert info.commands == {"/test": "Test command"}

    config.__dict__["PLUGIN_PERMISSIONS"] = PluginsPermissionsModel(
        base_permission=True,
        need_running_on_host_machine=True,
    )
    monkeypatch.setattr(plugin_manager_module, "is_running_in_docker", lambda: True)
    assert manager._extract_plugin_info(config) is None

    invalid_config = ModuleType("invalid_config")
    invalid_config.__dict__["PLUGIN_PERMISSIONS"] = object()
    with pytest.raises(ValueError):
        manager._extract_plugin_permissions(invalid_config)


def test_register_plugins_splits_input_and_filters_invalid_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PluginManager()
    registered: list[str] = []

    monkeypatch.setattr(
        PluginManager,
        "_register_plugin",
        lambda self, plugin_name, bot=None: registered.append(plugin_name),
    )

    manager.register_plugins([" monitor,outline , bad-plugin , also_bad! "], bot=None)
    assert registered == ["monitor", "outline"]


def test_register_plugin_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = PluginManager()
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")

    plugin_module = ModuleType("plugin_module")
    config_module = _build_config_module(base_permission=True, need_host=False)

    monkeypatch.setattr(
        PluginManager,
        "_validate_plugin_name",
        staticmethod(lambda _name: True),
    )
    monkeypatch.setattr(PluginManager, "_module_exists", lambda self, _name: True)
    monkeypatch.setattr(PluginManager, "_import_module", lambda self, _name: plugin_module)
    monkeypatch.setattr(
        PluginManager,
        "_import_module_config",
        lambda self, _name: config_module,
    )
    monkeypatch.setattr(
        PluginManager,
        "_extract_plugin_info",
        lambda self, _module: _PluginInfo(
            name="test_plugin",
            version="1.0.0",
            description="Test plugin",
        ),
    )
    monkeypatch.setattr(
        PluginManager,
        "_extract_plugin_permissions",
        lambda self, _module: PluginsPermissionsModel(base_permission=True),
    )
    monkeypatch.setattr(
        PluginManager,
        "_find_plugin_classes",
        staticmethod(lambda _module: [_TestPlugin]),
    )

    manager._register_plugin("test_plugin", bot)
    assert _TestPlugin.registered_calls == 1
    assert manager.is_plugin_loaded("test_plugin") is True
    assert "test_plugin" in manager._plugin_instances


def test_register_plugin_handles_permission_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = PluginManager()
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    config_module = _build_config_module(base_permission=False, need_host=False)

    monkeypatch.setattr(
        PluginManager,
        "_validate_plugin_name",
        staticmethod(lambda _name: True),
    )
    monkeypatch.setattr(PluginManager, "_module_exists", lambda self, _name: True)
    monkeypatch.setattr(
        PluginManager,
        "_import_module",
        lambda self, _name: ModuleType("plugin"),
    )
    monkeypatch.setattr(
        PluginManager,
        "_import_module_config",
        lambda self, _name: config_module,
    )
    monkeypatch.setattr(
        PluginManager,
        "_extract_plugin_info",
        lambda self, _module: _PluginInfo(
            name="test_plugin",
            version="1.0.0",
            description="Test plugin",
        ),
    )
    monkeypatch.setattr(
        PluginManager,
        "_extract_plugin_permissions",
        lambda self, _module: PluginsPermissionsModel(base_permission=False),
    )
    monkeypatch.setattr(
        PluginManager,
        "_find_plugin_classes",
        staticmethod(lambda _module: [_TestPlugin]),
    )

    manager._register_plugin("test_plugin", bot)
    assert _TestPlugin.registered_calls == 0
    assert manager.is_plugin_loaded("test_plugin") is False


def test_cleanup_plugin_and_cleanup_all_plugins() -> None:
    manager = PluginManager()
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    plugin_instance = _TestPlugin(bot)

    manager._plugin_instances["test_plugin"] = plugin_manager_module.weakref.ref(
        plugin_instance
    )
    manager._loaded_plugins.add("test_plugin")

    manager._cleanup_plugin("test_plugin")
    assert _TestPlugin.cleanup_calls == 1
    assert "test_plugin" not in manager._plugin_instances
    assert "test_plugin" not in manager._loaded_plugins

    manager._loaded_plugins.update({"a", "b"})
    manager.cleanup_all_plugins()
    assert manager._loaded_plugins == set()


def test_module_exists_uses_import_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = PluginManager()
    monkeypatch.setattr(
        plugin_manager_module.importlib.util,
        "find_spec",
        lambda module_path: object() if module_path.endswith(".ok.config") else None,
    )
    assert manager._module_exists("ok") is True
    assert manager._module_exists("missing") is False
