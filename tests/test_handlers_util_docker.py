from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery, User

import pytmbot.handlers.handlers_util.docker as docker_utils
from pytmbot.handlers.handlers_util.docker import (
    AuthorizedContainerCallbackContext,
    _extract_container_attrs,
    authorize_docker_callback_request,
    get_authorized_container_callback_context,
    get_comprehensive_container_details,
    get_sanitized_logs,
    normalize_memory_stats,
    parse_container_basic_info,
    parse_container_cpu_stats,
    parse_container_environment,
    parse_container_memory_stats,
    parse_container_network_info,
    parse_container_network_stats,
    parse_container_resources,
    sanitize_environment_variables,
    show_handler_info,
)


def _build_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TeleBot, list[dict[str, object]]]:
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    answers: list[dict[str, object]] = []

    def _answer_callback_query(
        callback_query_id: int,
        text: str | None = None,
        show_alert: bool | None = None,
        url: str | None = None,
        cache_time: int | None = None,
    ) -> bool:
        del url, cache_time
        answers.append(
            {
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert,
            }
        )
        return True

    monkeypatch.setattr(bot, "answer_callback_query", _answer_callback_query)
    return bot, answers


@dataclass
class _FakeContainer:
    status: str
    attrs: dict[str, Any]
    stats: object | None = None


def _build_callback_query(data: str, user_id: int = 101) -> CallbackQuery:
    user = User(
        id=user_id,
        is_bot=False,
        first_name="Test",
        username="test_user",
    )
    return CallbackQuery(
        id=1,
        from_user=user,
        data=data,
        chat_instance="chat-1",
        json_string="{}",
    )


def _container_attrs() -> dict[str, Any]:
    return {
        "Id": "abcdef1234567890",
        "Name": "/pytmbot",
        "Created": "2026-02-01T00:00:00Z",
        "Config": {
            "Image": "orenlab/pytmbot:alpine-dev",
            "Env": [
                "PUBLIC_FLAG=true",
                "DB_PASSWORD=secret",
                "VERY_LONG=abcdefghijklmnopqrstuvwxyz" * 10,
            ],
            "WorkingDir": "/opt/app",
            "User": "pytmbot",
            "Cmd": ["--mode", "dev"],
            "Entrypoint": ["tini", "-s", "--", "./entrypoint.sh"],
        },
        "State": {
            "Status": "running",
            "Running": True,
            "Paused": False,
            "Restarting": False,
            "RestartCount": 2,
            "ExitCode": 0,
            "StartedAt": "2026-02-15T12:00:00Z",
        },
        "HostConfig": {
            "Memory": 1024 * 1024 * 512,
            "MemorySwap": 1024 * 1024 * 1024,
            "CpuShares": 512,
            "CpuQuota": 200000,
            "CpuPeriod": 100000,
            "CpusetCpus": "0-1",
            "NetworkMode": "bridge",
            "PortBindings": {
                "80/tcp": [{"HostPort": "8080"}],
                "443/tcp": None,
            },
            "RestartPolicy": {"Name": "always", "MaximumRetryCount": 5},
        },
        "NetworkSettings": {
            "Networks": {"bridge": {}},
        },
    }


def test_show_handler_info_returns_bot_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = _build_callback_query("__get__:pytmbot:101")
    bot, answers = _build_bot(monkeypatch)
    result = show_handler_info(call, "Info message", bot)
    assert result is True
    assert answers[0]["text"] == "Info message"
    assert answers[0]["show_alert"] is True


def test_authorize_docker_callback_request_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = _build_callback_query("__get__:pytmbot:101")
    assert authorize_docker_callback_request(call, "bad") == (
        False,
        "Invalid target user id",
    )

    monkeypatch.setattr(
        docker_utils,
        "authorize_callback_request",
        lambda *_args, **_kwargs: (True, ""),
    )
    assert authorize_docker_callback_request(call, 101) == (True, "")


def test_get_authorized_container_callback_context_authorizes_and_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = _build_callback_query("__get_logs__:pytmbot:101")
    bot, answers = _build_bot(monkeypatch)

    monkeypatch.setattr(
        docker_utils,
        "authorize_docker_callback_request",
        lambda *_args, **_kwargs: (True, ""),
    )
    context = get_authorized_container_callback_context(
        call,
        bot,
        operation_label="Logs",
        missing_user_event="missing.user",
        denied_event="denied",
    )
    assert isinstance(context, AuthorizedContainerCallbackContext)
    assert context.container_name == "pytmbot"
    assert context.user_id == 101

    monkeypatch.setattr(
        docker_utils,
        "authorize_docker_callback_request",
        lambda *_args, **_kwargs: (False, "Not authenticated user"),
    )
    denied = get_authorized_container_callback_context(
        call,
        bot,
        operation_label="Logs",
        missing_user_event="missing.user",
        denied_event="denied",
    )
    assert denied is None
    assert "Not authenticated user" in str(answers[-1]["text"])


def test_extract_container_attrs_for_supported_shapes() -> None:
    attrs = _container_attrs()
    container = _FakeContainer(status="running", attrs=attrs)
    assert _extract_container_attrs(container) == attrs
    assert _extract_container_attrs({"attrs": attrs}) == attrs
    assert _extract_container_attrs(attrs) == attrs
    assert _extract_container_attrs({"attrs": "invalid"}) == {}
    assert _extract_container_attrs(object()) == {}


def test_sanitize_environment_variables_masks_and_limits() -> None:
    env_list = [
        "DB_PASSWORD=secret",
        "API_KEY=abcd",
        "FLAG",
        *[f"KEY{i}=value" for i in range(30)],
    ]
    sanitized = sanitize_environment_variables(env_list)
    assert len(sanitized) == 20
    assert any(item.startswith("DB_PASSWORD=<HIDDEN>") for item in sanitized)
    assert any(item.startswith("API_KEY=<HIDDEN>") for item in sanitized)


def test_parse_container_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    attrs = _container_attrs()
    container = _FakeContainer(status="running", attrs=attrs)

    monkeypatch.setattr(docker_utils, "set_naturaltime", lambda _dt: "10 minutes ago")
    monkeypatch.setattr(docker_utils, "set_naturalsize", lambda value: f"{value}B")

    basic = parse_container_basic_info(container, attrs=attrs)
    assert basic["name"] == "pytmbot"
    assert basic["image_name"] == "orenlab/pytmbot"
    assert basic["image_tag"] == "alpine-dev"
    assert basic["uptime"] == "10 minutes ago"

    resources = parse_container_resources(container, attrs=attrs)
    assert resources["memory_limit"] == f"{attrs['HostConfig']['Memory']}B"
    assert resources["cpu_quota"] == "200000/100000"
    assert resources["restart_policy"] == "always"

    network = parse_container_network_info(container, attrs=attrs)
    assert network["network_mode"] == "bridge"
    assert "8080:80/tcp" in network["ports"]
    assert "443/tcp" in network["ports"]
    assert network["published_ports"] == 2

    environment = parse_container_environment(container, attrs=attrs)
    assert environment["working_dir"] == "/opt/app"
    assert environment["user"] == "pytmbot"
    assert environment["entrypoint"] == "tini -s -- ./entrypoint.sh"
    assert environment["env_count"] == 3
    assert any("DB_PASSWORD=<HIDDEN>" in item for item in environment["environment_vars"])


def test_parse_container_memory_cpu_network_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docker_utils, "set_naturalsize", lambda value: f"{value}B")

    memory = parse_container_memory_stats(
        {"memory_stats": {"usage": 512, "limit": 1024}}
    )
    assert memory["mem_usage"] == "512B"
    assert memory["mem_limit"] == "1024B"
    assert memory["mem_percent"] == 50.0

    cpu = parse_container_cpu_stats(
        {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 300, "percpu_usage": [1, 2]},
                "system_cpu_usage": 1000,
                "throttling_data": {
                    "periods": 10,
                    "throttled_periods": 2,
                    "throttled_time": 50,
                },
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 500,
            },
        }
    )
    assert cpu["periods"] == 10
    assert cpu["throttled_periods"] == 2
    assert float(cpu["cpu_percent"]) > 0

    network = parse_container_network_stats(
        {
            "networks": {
                "eth0": {
                    "rx_bytes": 100,
                    "tx_bytes": 200,
                    "rx_dropped": 1,
                    "tx_dropped": 2,
                    "rx_errors": 3,
                    "tx_errors": 4,
                },
                "eth1": {
                    "rx_bytes": 50,
                    "tx_bytes": 60,
                    "rx_dropped": 0,
                    "tx_dropped": 1,
                    "rx_errors": 0,
                    "tx_errors": 1,
                },
            }
        }
    )
    assert network["rx_bytes"] == "150B"
    assert network["tx_bytes"] == "260B"
    assert network["rx_dropped"] == 1
    assert network["tx_errors"] == 5


def test_normalize_memory_stats_parses_percent_variants() -> None:
    normalized = normalize_memory_stats(
        {"mem_usage": "100 MiB", "mem_limit": "1 GiB", "mem_percent": "12.5%"}
    )
    assert normalized["mem_percent"] == 12.5
    assert normalize_memory_stats({}) == {}
    assert normalize_memory_stats({"mem_percent": object()})["mem_percent"] == "N/A"


def test_get_sanitized_logs_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    call = _build_callback_query("__get_logs__:pytmbot:101")
    monkeypatch.setattr(docker_utils, "fetch_container_logs", lambda _name: "raw logs")
    monkeypatch.setattr(docker_utils, "sanitize_logs", lambda logs, _call, _token: f"san:{logs}")
    assert get_sanitized_logs("pytmbot", call, "TOKEN") == "san:raw logs"


def test_get_comprehensive_container_details_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docker_utils, "get_container_full_details", lambda _name: None)
    assert get_comprehensive_container_details("missing") is None

    attrs = _container_attrs()
    container = _FakeContainer(status="running", attrs=attrs)
    monkeypatch.setattr(docker_utils, "get_container_full_details", lambda _name: container)
    monkeypatch.setattr(docker_utils, "set_naturalsize", lambda value: f"{value}B")
    monkeypatch.setattr(docker_utils, "set_naturaltime", lambda _dt: "just now")
    monkeypatch.setattr(
        docker_utils,
        "get_container_stats_snapshot",
        lambda _container: {
            "memory_stats": {"usage": 256, "limit": 512},
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200, "percpu_usage": [1]},
                "system_cpu_usage": 1000,
                "throttling_data": {},
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 900,
            },
            "networks": {"eth0": {"rx_bytes": 10, "tx_bytes": 20}},
        },
    )
    monkeypatch.setattr(
        docker_utils,
        "parse_container_memory_stats",
        lambda _stats: {"mem_usage": "256B", "mem_limit": "512B", "mem_percent": 50.0},
    )
    monkeypatch.setattr(
        docker_utils,
        "get_container_memory_stats",
        lambda _container: {"mem_usage": "fallback", "mem_limit": "fallback", "mem_percent": "9%"},
    )

    details = get_comprehensive_container_details("pytmbot")
    assert details is not None
    assert details["name"] == "pytmbot"
    assert details["stats"]["memory"]["mem_usage"] == "256B"
    assert isinstance(details["stats"]["cpu"]["cpu_percent"], float)
    assert details["stats"]["network"]["rx_bytes"] == "10B"

    # Force runtime memory parsing miss to cover fallback provider path
    monkeypatch.setattr(
        docker_utils,
        "get_container_stats_snapshot",
        lambda _container: {"memory_stats": {"usage": 0, "limit": 0}},
    )
    monkeypatch.setattr(docker_utils, "parse_container_memory_stats", lambda _stats: {})
    fallback_details = get_comprehensive_container_details("pytmbot")
    assert fallback_details is not None
    assert fallback_details["stats"]["memory"]["mem_percent"] == 9.0
