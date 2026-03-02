#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from importlib import import_module
from types import TracebackType
from typing import Literal, Protocol, TypeVar, runtime_checkable

from pytmbot.plugins.plugins_core import PluginCore

type OutlinePayload = dict[str, object] | list[dict[str, object]]
T = TypeVar("T")


@runtime_checkable
class _AsyncOutlineClient(Protocol):
    async def __aenter__(self) -> _AsyncOutlineClient: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...


type _AsyncOutlineClientFactory = Callable[..., _AsyncOutlineClient]


def _wrap_async_client_factory(
    constructor: Callable[..., object],
) -> _AsyncOutlineClientFactory:
    """Wrap dynamic constructor with runtime protocol validation."""

    def _factory(*args: object, **kwargs: object) -> _AsyncOutlineClient:
        client = constructor(*args, **kwargs)
        if not isinstance(client, _AsyncOutlineClient):
            raise TypeError(
                "Resolved AsyncOutlineClient does not implement async context manager protocol"
            )
        return client

    return _factory


class PluginMethods(PluginCore):
    __slots__ = (
        "plugin_config",
        "api_url",
        "cert",
        "verify_tls",
        "_async_client_cls",
        "_legacy_client",
    )

    def __init__(self) -> None:
        """
        Initializes the PluginMethods class and sets up the Outline API client.
        """
        super().__init__()
        plugins_config = self.settings.plugins_config
        outline_config = plugins_config.outline if plugins_config else None
        if outline_config is None:
            raise RuntimeError("Outline plugin configuration is missing")

        self.plugin_config = outline_config
        api_url_secret = self.plugin_config.api_url[0]
        cert_secret = self.plugin_config.cert[0]
        self.api_url = api_url_secret.get_secret_value()
        self.cert = cert_secret.get_secret_value()
        self.verify_tls = bool(getattr(self.plugin_config, "verify_tls", True))
        self._async_client_cls = self._resolve_async_client_class()
        self._legacy_client: object | None = None

        if self._async_client_cls is None:
            self._legacy_client = self._build_legacy_client()

    @staticmethod
    def _resolve_async_client_class() -> _AsyncOutlineClientFactory | None:
        """
        Resolve AsyncOutlineClient for pyoutlineapi>=0.4.0.
        Falls back to pyoutlineapi.client module when needed.
        """
        try:
            module = import_module("pyoutlineapi")
            async_client = getattr(module, "AsyncOutlineClient", None)
            if callable(async_client):
                return _wrap_async_client_factory(async_client)
        except ImportError:
            pass

        try:
            client_module = import_module("pyoutlineapi.client")
            async_client = getattr(client_module, "AsyncOutlineClient", None)
            if callable(async_client):
                return _wrap_async_client_factory(async_client)
        except ImportError:
            pass

        return None

    def _build_legacy_client(self) -> object:
        """Build legacy sync client for pyoutlineapi<0.4.0."""
        try:
            client_module = import_module("pyoutlineapi.client")
        except ImportError as error:
            raise RuntimeError(
                "pyoutlineapi client is unavailable. Install pyoutlineapi>=0.4.0 or legacy wrapper support."
            ) from error

        try:
            wrapper_cls = client_module.PyOutlineWrapper
        except AttributeError as error:
            raise RuntimeError(
                "pyoutlineapi client is unavailable. Install pyoutlineapi>=0.4.0 or legacy wrapper support."
            ) from error

        return wrapper_cls(
            self.api_url,
            self.cert,
            verify_tls=self.verify_tls,
        )

    def _create_async_client(self) -> _AsyncOutlineClient:
        """Create AsyncOutlineClient instance with compatibility-friendly arguments."""
        client_factory = self._async_client_cls
        if client_factory is None:
            raise RuntimeError("Async outline client is not initialized")

        try:
            return client_factory(
                api_url=self.api_url,
                cert_sha256=self.cert,
                json_format=True,
            )
        except TypeError:
            # Positional fallback for client variants that do not expose keyword args.
            return client_factory(
                self.api_url,
                self.cert,
                json_format=True,
            )

    @staticmethod
    def _normalize_payload(payload: object) -> OutlinePayload:
        """Normalize pyoutlineapi responses to dict/list[dict] payloads."""
        if isinstance(payload, dict):
            return {str(key): value for key, value in payload.items()}

        if isinstance(payload, list):
            normalized_items: list[dict[str, object]] = []
            for item in payload:
                if isinstance(item, dict):
                    normalized_items.append(
                        {str(key): value for key, value in item.items()}
                    )
                    continue

                model_dump = getattr(item, "model_dump", None)
                if callable(model_dump):
                    dumped_item = model_dump(by_alias=True)
                    if isinstance(dumped_item, dict):
                        normalized_items.append(
                            {str(key): value for key, value in dumped_item.items()}
                        )
            return normalized_items

        model_dump = getattr(payload, "model_dump", None)
        if callable(model_dump):
            dumped_payload = model_dump(by_alias=True)
            return PluginMethods._normalize_payload(dumped_payload)

        raise TypeError(f"Unsupported outline payload type: {type(payload)!r}")

    @staticmethod
    def _run_coroutine(
        coroutine_factory: Callable[[], Coroutine[object, object, T]],
    ) -> T:
        """Execute coroutine from sync context with running-loop fallback."""
        try:
            return asyncio.run(coroutine_factory())
        except RuntimeError as error:
            if "asyncio.run() cannot be called from a running event loop" not in str(
                error
            ):
                raise

        result_box: dict[str, T] = {}
        error_box: dict[str, BaseException] = {}

        def _thread_runner() -> None:
            try:
                result_box["value"] = asyncio.run(coroutine_factory())
            except BaseException as thread_error:  # noqa: BLE001
                error_box["error"] = thread_error

        worker = threading.Thread(
            target=_thread_runner,
            name="outline_async_bridge",
            daemon=True,
        )
        worker.start()
        worker.join()

        if "error" in error_box:
            raise error_box["error"]

        return result_box["value"]

    def _execute_async_action(self, method_names: tuple[str, ...]) -> OutlinePayload:
        """Execute async outline action and normalize the returned payload."""

        async def _call() -> OutlinePayload:
            async with self._create_async_client() as client:
                for method_name in method_names:
                    method = getattr(client, method_name, None)
                    if callable(method):
                        payload = await method()
                        return self._normalize_payload(payload)
                raise AttributeError(
                    f"Async outline client does not support methods: {method_names}"
                )

        return self._run_coroutine(_call)

    def _execute_legacy_action(self, method_name: str) -> OutlinePayload:
        """Execute legacy sync action and normalize the returned payload."""
        legacy_client = self._legacy_client
        if legacy_client is None:
            legacy_client = self._build_legacy_client()
            self._legacy_client = legacy_client

        method = getattr(legacy_client, method_name, None)
        if not callable(method):
            raise AttributeError(
                f"Legacy outline client does not support method: {method_name}"
            )

        payload = method()
        return self._normalize_payload(payload)

    def _execute_action(
        self, *, legacy_method: str, async_methods: tuple[str, ...]
    ) -> OutlinePayload:
        """Execute action against async client when available, otherwise legacy client."""
        if self._async_client_cls is not None:
            return self._execute_async_action(async_methods)
        return self._execute_legacy_action(legacy_method)

    def _fetch_server_information(self) -> dict[str, object]:
        """
        Fetches server information from the Outline API.

        Returns:
            Dict with outline server information.
        """
        payload = self._execute_action(
            legacy_method="get_server_info",
            async_methods=("get_server_info",),
        )
        if not isinstance(payload, dict):
            raise TypeError("Server information payload must be a dict")
        return payload

    def _fetch_traffic_information(self) -> dict[str, object]:
        """
        Fetches traffic information from the Outline API.

        Returns:
            Dict with transferred-data information.
        """
        payload = self._execute_action(
            legacy_method="get_metrics",
            async_methods=("get_transfer_metrics", "get_metrics"),
        )
        if not isinstance(payload, dict):
            raise TypeError("Traffic information payload must be a dict")
        return payload

    def _fetch_key_information(self) -> OutlinePayload:
        """
        Fetches key information from the Outline API.

        Returns:
            Dict/list payload with access key information.
        """
        return self._execute_action(
            legacy_method="get_access_keys",
            async_methods=("get_access_keys",),
        )

    def outline_action_manager(
        self,
        action: Literal["server_information", "traffic_information", "key_information"],
    ) -> OutlinePayload:
        """
        Manages actions based on the provided action string and returns the appropriate data.

        Args:
            action (str): The action to perform. Must be one of 'server_information', 'traffic_information', or 'key_information'.

        Returns:
            Dict/list payload from Outline API.

        Raises:
            ValueError: If an invalid action is provided.
        """
        action_map = {
            "server_information": self._fetch_server_information,
            "traffic_information": self._fetch_traffic_information,
            "key_information": self._fetch_key_information,
        }

        if action not in action_map:
            raise ValueError(f"Invalid action: {action}")

        try:
            return action_map[action]()
        except Exception:
            self.logger.exception("bot.plugins.outline.methods.plugin.fail")
            raise
