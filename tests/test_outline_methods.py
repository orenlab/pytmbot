from __future__ import annotations

from collections.abc import Callable
from types import ModuleType, SimpleNamespace, TracebackType
from typing import cast

import pytest

import pytmbot.plugins.outline.methods as outline_methods_module
from pytmbot.logs import Logger
from pytmbot.models.settings_model import SettingsModel
from pytmbot.plugins.outline.methods import OutlinePayload, PluginMethods


class _SecretStub:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


def _patch_plugin_core_init() -> Callable[[PluginMethods], None]:
    def _fake_init(self: PluginMethods) -> None:
        self.settings = cast(
            SettingsModel,
            SimpleNamespace(
                plugins_config=SimpleNamespace(
                    outline=SimpleNamespace(
                        api_url=[_SecretStub("https://outline.example/api")],
                        cert=[_SecretStub("CERT_SHA256")],
                        verify_tls=True,
                    )
                )
            ),
        )
        self.logger = cast(
            Logger,
            SimpleNamespace(exception=lambda *_args, **_kwargs: None),
        )

    return _fake_init


def test_outline_methods_uses_async_client_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pytmbot.plugins.plugins_core.PluginCore.__init__",
        _patch_plugin_core_init(),
    )

    class _AsyncClient:
        def __init__(
            self, *, api_url: str, cert_sha256: str, json_format: bool
        ) -> None:
            assert api_url == "https://outline.example/api"
            assert cert_sha256 == "CERT_SHA256"
            assert json_format is True

        async def __aenter__(self) -> _AsyncClient:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc_val: BaseException | None,
            _exc_tb: TracebackType | None,
        ) -> None:
            return None

        @staticmethod
        async def get_server_info() -> OutlinePayload:
            return {"name": "server", "metricsEnabled": True}

        @staticmethod
        async def get_transfer_metrics() -> OutlinePayload:
            return {"bytesTransferredByUserId": {"1": 1024}}

        @staticmethod
        async def get_access_keys() -> OutlinePayload:
            return [{"id": "1", "name": "Alice"}]

    def _fake_import_module(module_name: str) -> ModuleType:
        if module_name == "pyoutlineapi":
            module = ModuleType("pyoutlineapi")
            module.__dict__["AsyncOutlineClient"] = _AsyncClient
            return module
        raise ImportError(module_name)

    monkeypatch.setattr(outline_methods_module, "import_module", _fake_import_module)

    plugin_methods = PluginMethods()
    assert plugin_methods.outline_action_manager("server_information") == {
        "name": "server",
        "metricsEnabled": True,
    }
    assert plugin_methods.outline_action_manager("traffic_information") == {
        "bytesTransferredByUserId": {"1": 1024}
    }
    assert plugin_methods.outline_action_manager("key_information") == [
        {"id": "1", "name": "Alice"}
    ]


def test_outline_methods_traffic_fallback_to_get_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pytmbot.plugins.plugins_core.PluginCore.__init__",
        _patch_plugin_core_init(),
    )

    class _AsyncClient:
        def __init__(
            self, *, api_url: str, cert_sha256: str, json_format: bool
        ) -> None:
            del api_url, cert_sha256, json_format

        async def __aenter__(self) -> _AsyncClient:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc_val: BaseException | None,
            _exc_tb: TracebackType | None,
        ) -> None:
            return None

        @staticmethod
        async def get_metrics() -> OutlinePayload:
            return {"bytes_transferred_by_user_id": {"42": 2048}}

        @staticmethod
        async def get_server_info() -> OutlinePayload:
            return {"name": "server"}

        @staticmethod
        async def get_access_keys() -> OutlinePayload:
            return []

    def _fake_import_module(module_name: str) -> ModuleType:
        if module_name == "pyoutlineapi":
            module = ModuleType("pyoutlineapi")
            module.__dict__["AsyncOutlineClient"] = _AsyncClient
            return module
        raise ImportError(module_name)

    monkeypatch.setattr(outline_methods_module, "import_module", _fake_import_module)

    plugin_methods = PluginMethods()
    assert plugin_methods.outline_action_manager("traffic_information") == {
        "bytes_transferred_by_user_id": {"42": 2048}
    }


def test_outline_methods_falls_back_to_legacy_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pytmbot.plugins.plugins_core.PluginCore.__init__",
        _patch_plugin_core_init(),
    )

    class _LegacyWrapper:
        def __init__(self, api_url: str, cert: str, verify_tls: bool) -> None:
            assert api_url == "https://outline.example/api"
            assert cert == "CERT_SHA256"
            assert verify_tls is True

        @staticmethod
        def get_server_info() -> OutlinePayload:
            return {"name": "legacy"}

        @staticmethod
        def get_metrics() -> OutlinePayload:
            return {"bytesTransferredByUserId": {"2": 512}}

        @staticmethod
        def get_access_keys() -> OutlinePayload:
            return {"accessKeys": [{"id": "2", "name": "Bob"}]}

    def _fake_import_module(module_name: str) -> ModuleType:
        if module_name == "pyoutlineapi":
            raise ImportError(module_name)
        if module_name == "pyoutlineapi.client":
            module = ModuleType("pyoutlineapi.client")
            module.__dict__["PyOutlineWrapper"] = _LegacyWrapper
            return module
        raise ImportError(module_name)

    monkeypatch.setattr(outline_methods_module, "import_module", _fake_import_module)

    plugin_methods = PluginMethods()
    assert plugin_methods.outline_action_manager("server_information") == {
        "name": "legacy"
    }
    assert plugin_methods.outline_action_manager("traffic_information") == {
        "bytesTransferredByUserId": {"2": 512}
    }
    assert plugin_methods.outline_action_manager("key_information") == {
        "accessKeys": [{"id": "2", "name": "Bob"}]
    }


def test_outline_methods_rejects_unknown_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pytmbot.plugins.plugins_core.PluginCore.__init__",
        _patch_plugin_core_init(),
    )

    class _AsyncClient:
        def __init__(
            self, *, api_url: str, cert_sha256: str, json_format: bool
        ) -> None:
            del api_url, cert_sha256, json_format

        async def __aenter__(self) -> _AsyncClient:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc_val: BaseException | None,
            _exc_tb: TracebackType | None,
        ) -> None:
            return None

        @staticmethod
        async def get_server_info() -> OutlinePayload:
            return {"name": "server"}

    def _fake_import_module(module_name: str) -> ModuleType:
        if module_name == "pyoutlineapi":
            module = ModuleType("pyoutlineapi")
            module.__dict__["AsyncOutlineClient"] = _AsyncClient
            return module
        raise ImportError(module_name)

    monkeypatch.setattr(outline_methods_module, "import_module", _fake_import_module)

    plugin_methods = PluginMethods()
    action_name = "outline_action_manager"
    action_manager = getattr(plugin_methods, action_name)
    with pytest.raises(ValueError):
        action_manager("bad_action")
