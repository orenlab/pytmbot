from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import pytest
from telebot.types import CallbackQuery, Message

import pytmbot.handlers.handler_manager as factory_module
from pytmbot.models.handlers_model import HandlerManager


def test_handler_manager_model_execute_and_repr() -> None:
    calls: dict[str, object] = {}

    def _callback(**kwargs: object) -> str:
        calls.update(kwargs)
        return "ok"

    manager = HandlerManager(callback=_callback, kwargs={"a": 1})
    result = manager.execute(a=2, b=3)
    assert result == "ok"
    assert calls == {"a": 2, "b": 3}
    assert "HandlerManager" in repr(manager)
    assert "_callback" in repr(manager)

    with pytest.raises(ValueError):
        HandlerManager(callback="not-callable")  # type: ignore[arg-type]


def test_handler_config_create_handler_populates_filters() -> None:
    def _callback(**_kwargs: object) -> None:
        return None

    def _filter(message: object) -> bool:
        return bool(message)

    config = factory_module.HandlerConfig(
        callback=_callback,
        commands=["start"],
        regexp="^/start$",
        filter_func=_filter,
    )
    handler = config.create_handler()
    assert isinstance(handler, HandlerManager)
    assert handler.kwargs["commands"] == ["start"]
    assert handler.kwargs["regexp"] == "^/start$"
    assert handler.kwargs["func"] is _filter


def test_handler_config_rejects_non_callable_values() -> None:
    with pytest.raises(TypeError):
        factory_module.HandlerConfig(
            callback=cast(factory_module.HandlerCallback, "bad")
        )

    with pytest.raises(TypeError):
        factory_module.HandlerConfig(
            callback=lambda **_kwargs: None,
            filter_func=cast(factory_module.FilterFunc, "bad"),
        )


@dataclass(slots=True)
class _AccessControl:
    allowed_user_ids: set[int]
    allowed_admins_ids: set[int]


@dataclass(slots=True)
class _Settings:
    access_control: _AccessControl


def test_admin_filter_and_inline_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    factory_module.AdminFilter._get_admin_ids.cache_clear()
    monkeypatch.setattr(
        factory_module,
        "settings",
        _Settings(_AccessControl(allowed_user_ids={1}, allowed_admins_ids={7})),
    )

    assert (
        factory_module.AdminFilter.is_admin(
            cast(Message, SimpleNamespace(from_user=None))
        )
        is False
    )
    assert (
        factory_module.AdminFilter.is_admin(
            cast(Message, SimpleNamespace(from_user=SimpleNamespace(id=7)))
        )
        is True
    )
    assert (
        factory_module.AdminFilter.is_admin(
            cast(Message, SimpleNamespace(from_user=SimpleNamespace(id=8)))
        )
        is False
    )

    query = cast(CallbackQuery, SimpleNamespace(data=None))
    assert factory_module.InlineFilters.swap_info(query) is False
    assert factory_module.InlineFilters.process_info(query) is False
    assert factory_module.InlineFilters.cpu_info(query) is False
    assert factory_module.InlineFilters.cpu_per_core(query) is False
    assert factory_module.InlineFilters.cpu_times(query) is False
    assert factory_module.InlineFilters.update_info(query) is False
    assert factory_module.InlineFilters.get_logs(query) is False
    assert factory_module.InlineFilters.containers_full_info(query) is False
    assert factory_module.InlineFilters.back_to_containers(query) is False
    assert factory_module.InlineFilters.manage_container(query) is False
    assert factory_module.InlineFilters.container_extra_info(query) is False
    assert factory_module.InlineFilters.image_updates(query) is False
    assert factory_module.InlineFilters.images_page(query) is False
    assert factory_module.InlineFilters.image_info(query) is False
    assert factory_module.InlineFilters.image_extra(query) is False
    assert factory_module.InlineFilters.network_overview(query) is False
    assert factory_module.InlineFilters.network_interfaces(query) is False
    assert factory_module.InlineFilters.network_connections(query) is False
    assert factory_module.InlineFilters.filesystem_overview(query) is False
    assert factory_module.InlineFilters.disk_io(query) is False
    assert factory_module.InlineFilters.users_info(query) is False
    assert factory_module.InlineFilters.sensors_overview(query) is False
    assert factory_module.InlineFilters.fan_speeds(query) is False
    assert factory_module.InlineFilters.quickview_overview(query) is False
    assert factory_module.InlineFilters.quickview_memory(query) is False
    assert factory_module.InlineFilters.quickview_sensors(query) is False
    assert factory_module.InlineFilters.quickview_cpu(query) is False
    assert factory_module.InlineFilters.quickview_disk(query) is False

    query.data = "__swap_info__:abc"
    assert factory_module.InlineFilters.swap_info(query) is True
    query.data = "__process_info__:abc"
    assert factory_module.InlineFilters.process_info(query) is True
    query.data = "__cpu_info__:abc"
    assert factory_module.InlineFilters.cpu_info(query) is True
    query.data = "__cpu_per_core__:abc"
    assert factory_module.InlineFilters.cpu_per_core(query) is True
    query.data = "__cpu_times__:abc"
    assert factory_module.InlineFilters.cpu_times(query) is True
    query.data = "__how_update__"
    assert factory_module.InlineFilters.update_info(query) is True
    query.data = "__get_logs__:abc"
    assert factory_module.InlineFilters.get_logs(query) is True
    query.data = "__get_full__:abc"
    assert factory_module.InlineFilters.containers_full_info(query) is True
    query.data = "__containers_page__:2:1"
    assert factory_module.InlineFilters.back_to_containers(query) is True
    query.data = "__manage__:abc"
    assert factory_module.InlineFilters.manage_container(query) is True
    query.data = "__container_extra__:volumes:abc:1"
    assert factory_module.InlineFilters.container_extra_info(query) is True
    query.data = "__check_updates__:abc"
    assert factory_module.InlineFilters.image_updates(query) is True
    query.data = "__images_page__:3:1"
    assert factory_module.InlineFilters.images_page(query) is True
    query.data = "__image_info__:0:1:1"
    assert factory_module.InlineFilters.image_info(query) is True
    query.data = "__image_extra__:history:0:1:1"
    assert factory_module.InlineFilters.image_extra(query) is True
    query.data = "__network_overview__:1"
    assert factory_module.InlineFilters.network_overview(query) is True
    query.data = "__network_interfaces__:1"
    assert factory_module.InlineFilters.network_interfaces(query) is True
    query.data = "__network_connections__:1"
    assert factory_module.InlineFilters.network_connections(query) is True
    query.data = "__filesystem_overview__:1"
    assert factory_module.InlineFilters.filesystem_overview(query) is True
    query.data = "__disk_io__:1"
    assert factory_module.InlineFilters.disk_io(query) is True
    query.data = "__users_info__:1"
    assert factory_module.InlineFilters.users_info(query) is True
    query.data = "__sensors_overview__:1"
    assert factory_module.InlineFilters.sensors_overview(query) is True
    query.data = "__fan_speeds__:1"
    assert factory_module.InlineFilters.fan_speeds(query) is True
    query.data = "__quickview_overview__:1"
    assert factory_module.InlineFilters.quickview_overview(query) is True
    query.data = "__quickview_memory__:1"
    assert factory_module.InlineFilters.quickview_memory(query) is True
    query.data = "__quickview_sensors__:1"
    assert factory_module.InlineFilters.quickview_sensors(query) is True
    query.data = "__quickview_cpu__:1"
    assert factory_module.InlineFilters.quickview_cpu(query) is True
    query.data = "__quickview_disk__:1"
    assert factory_module.InlineFilters.quickview_disk(query) is True


def test_handler_factories_are_cached_and_produce_handlers() -> None:
    factory_module.handler_factory.cache_clear()
    factory_module.inline_handler_factory.cache_clear()

    message_handlers = factory_module.handler_factory()
    inline_handlers = factory_module.inline_handler_factory()

    assert message_handlers is factory_module.handler_factory()
    assert inline_handlers is factory_module.inline_handler_factory()

    assert "start" in message_handlers
    assert "cpu" in message_handlers
    assert "health" in message_handlers
    assert "get_logs" in inline_handlers
    assert "cpu_info" in inline_handlers
    assert "disk_io" in inline_handlers
    assert "quickview_overview" in inline_handlers
    assert "container_extra_info" in inline_handlers
    assert "image_info" in inline_handlers
    assert "image_extra" in inline_handlers
    assert all(isinstance(item, HandlerManager) for item in message_handlers["start"])
    assert all(isinstance(item, HandlerManager) for item in inline_handlers["get_logs"])
