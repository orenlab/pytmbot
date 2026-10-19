from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

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
    parse_container_runtime_info,
    sanitize_environment_variables,
    show_handler_info,
)

type _PayloadScalar = str | int | float | bool | None
type _PayloadValue = _PayloadScalar | list["_PayloadValue"] | dict[str, "_PayloadValue"]
type _PayloadDict = dict[str, _PayloadValue]
type _ObjectDict = dict[str, object]


def _build_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TeleBot, list[_PayloadDict]]:
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    answers: list[_PayloadDict] = []

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
    attrs: _ObjectDict
    stats: _ObjectDict | None = None


def _build_callback_query(data: str, user_id: int = 101) -> CallbackQuery:
    user_ctor = cast(Callable[..., User], User)
    user = user_ctor(
        id=user_id,
        is_bot=False,
        first_name="Test",
        username="test_user",
    )
    callback_query_ctor = cast(Callable[..., CallbackQuery], CallbackQuery)
    return callback_query_ctor(
        id=1,
        from_user=user,
        data=data,
        chat_instance="chat-1",
        json_string="{}",
    )


def _container_attrs() -> _ObjectDict:
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
    assert _extract_container_attrs(("invalid",)) == {}


def test_sanitize_environment_variables_masks_and_limits() -> None:
    env_list = [
        "DB_PASSWORD=secret",
        "API_KEY=abcd",
        "FLAG",
        *[f"KEY{i}=value" for i in range(30)],
    ]
    sanitized = sanitize_environment_variables(env_list)
    assert len(sanitized) == 20
    assert "DB_PASSWORD=\u2022\u2022\u2022\u2022" in sanitized
    assert "API_KEY=\u2022\u2022\u2022\u2022" in sanitized
    assert "FLAG" in sanitized
    assert all("value" not in item for item in sanitized)


def test_parse_container_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    attrs = _container_attrs()
    container = _FakeContainer(status="running", attrs=attrs)

    monkeypatch.setattr(docker_utils, "set_naturaltime", lambda _dt: "10 minutes ago")
    monkeypatch.setattr(docker_utils, "set_naturalsize", lambda value: f"{value}B")

    basic = parse_container_basic_info(container, attrs=attrs)
    assert basic["name"] == "pytmbot"
    assert basic["image_name"] == "orenlab/pytmbot"
    assert (
        basic["image_tag"],
        basic["uptime"],
        basic["status_badge"],
        basic["health_badge"],
    ) == ("alpine-dev", "10 minutes ago", "🟢 Running", "N/A")
    assert "health_last_log" not in basic

    resources = parse_container_resources(container, attrs=attrs)
    assert resources["memory_limit"] == f"{1024 * 1024 * 512}B"
    assert resources["cpu_quota"] == "200000/100000"
    assert resources["restart_policy"] == "always"

    network = parse_container_network_info(container, attrs=attrs)
    assert network["network_mode"] == "bridge"
    ports = network.get("ports")
    assert isinstance(ports, list)
    assert "0.0.0.0:8080->80/tcp" in ports
    assert "443/tcp" in ports
    assert network["published_ports"] == 1
    assert network["declared_ports"] == 2

    environment = parse_container_environment(container, attrs=attrs)
    assert environment["working_dir"] == "/opt/app"
    assert environment["user"] == "pytmbot"
    assert environment["entrypoint"] == "tini -s -- ./entrypoint.sh"
    assert environment["env_count"] == 3
    env_vars = environment.get("environment_vars")
    assert isinstance(env_vars, list)
    assert "DB_PASSWORD=\u2022\u2022\u2022\u2022" in env_vars
    assert "PUBLIC_FLAG=\u2022\u2022\u2022\u2022" in env_vars
    assert all("secret" not in str(item) for item in env_vars)

    runtime = parse_container_runtime_info(container, attrs=attrs)
    assert runtime["started_at"] == "2026-02-15 12:00:00 UTC"
    assert runtime["stop_signal"] == "SIGTERM"
    assert runtime["privileged"] is False


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
    assert (
        network["rx_bytes"],
        network["tx_bytes"],
        network["rx_dropped"],
        network["tx_errors"],
    ) == ("150B", "260B", 1, 5)


def test_normalize_memory_stats_parses_percent_variants() -> None:
    normalized = normalize_memory_stats(
        {"mem_usage": "100 MiB", "mem_limit": "1 GiB", "mem_percent": "12.5%"}
    )
    assert normalized["mem_percent"] == 12.5
    assert normalize_memory_stats({}) == {}
    assert normalize_memory_stats({"mem_percent": "invalid"})["mem_percent"] == "N/A"


def test_get_sanitized_logs_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    call = _build_callback_query("__get_logs__:pytmbot:101")
    monkeypatch.setattr(docker_utils, "fetch_container_logs", lambda _name: "raw logs")
    monkeypatch.setattr(
        docker_utils, "sanitize_logs", lambda logs, _call, _token: f"san:{logs}"
    )
    assert get_sanitized_logs("pytmbot", call, "TOKEN") == "san:raw logs"


def test_get_comprehensive_container_details_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docker_utils, "get_container_full_details", lambda _name: None)
    assert get_comprehensive_container_details("missing") is None

    attrs = _container_attrs()
    container = _FakeContainer(status="running", attrs=attrs)
    monkeypatch.setattr(
        docker_utils, "get_container_full_details", lambda _name: container
    )
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
        lambda _container: {
            "mem_usage": "fallback",
            "mem_limit": "fallback",
            "mem_percent": "9%",
        },
    )

    details = get_comprehensive_container_details("pytmbot")
    assert details is not None
    assert details["name"] == "pytmbot"
    stats = details.get("stats")
    assert isinstance(stats, dict)
    memory_stats = stats.get("memory")
    assert isinstance(memory_stats, dict)
    assert memory_stats.get("mem_usage") == "256B"
    cpu_stats = stats.get("cpu")
    assert isinstance(cpu_stats, dict)
    assert isinstance(cpu_stats.get("cpu_percent"), float)
    network_stats = stats.get("network")
    assert isinstance(network_stats, dict)
    assert network_stats.get("rx_bytes") == "10B"

    # Force runtime memory parsing miss to cover fallback provider path
    monkeypatch.setattr(
        "pytmbot.handlers.handlers_util.docker.time.sleep", lambda _seconds: None
    )
    monkeypatch.setattr(
        docker_utils,
        "get_container_stats_snapshot",
        lambda _container: {"memory_stats": {"usage": 0, "limit": 0}},
    )
    monkeypatch.setattr(docker_utils, "parse_container_memory_stats", lambda _stats: {})
    fallback_details = get_comprehensive_container_details("pytmbot")
    assert fallback_details is not None
    fallback_stats = fallback_details.get("stats")
    assert isinstance(fallback_stats, dict)
    fallback_memory = fallback_stats.get("memory")
    assert isinstance(fallback_memory, dict)
    assert fallback_memory.get("mem_percent") == 9.0


def _cpu_sample(total: int, system: int, **extra: object) -> _ObjectDict:
    return {"cpu_usage": {"total_usage": total}, "system_cpu_usage": system, **extra}


def test_cpu_percent_uses_online_cpus_and_is_cgroup_v2_safe() -> None:
    # cgroup v2: no percpu_usage, online_cpus present.
    cpu = parse_container_cpu_stats(
        {
            "cpu_stats": _cpu_sample(300, 2000, online_cpus=4),
            "precpu_stats": _cpu_sample(100, 1000, online_cpus=4),
        }
    )
    assert cpu["cpu_percent"] == 80.0  # 200/1000 * 4 cores * 100


def test_cpu_percent_without_previous_sample_is_not_since_boot_average() -> None:
    one_shot: _ObjectDict = {
        "cpu_stats": _cpu_sample(5_000, 10_000, online_cpus=8),
        "precpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 0},
    }
    assert parse_container_cpu_stats(one_shot)["cpu_percent"] == 0.0
    assert docker_utils.has_cpu_baseline(one_shot) is False


def test_runtime_stats_take_second_sample_when_precpu_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples = iter(
        [
            {
                "cpu_stats": _cpu_sample(1_000, 10_000, online_cpus=2),
                "precpu_stats": {},
            },
            {
                "cpu_stats": _cpu_sample(1_500, 11_000, online_cpus=2),
                "precpu_stats": {},
                "memory_stats": {"usage": 1, "limit": 2},
            },
        ]
    )
    sleeps: list[float] = []
    monkeypatch.setattr(
        docker_utils, "get_container_stats_snapshot", lambda _c: next(samples)
    )
    monkeypatch.setattr(
        "pytmbot.handlers.handlers_util.docker.time.sleep", sleeps.append
    )

    stats = docker_utils.collect_container_runtime_stats(object())

    assert sleeps == [docker_utils.CPU_SAMPLE_INTERVAL_SECONDS]
    assert parse_container_cpu_stats(stats)["cpu_percent"] == 100.0
    assert stats["memory_stats"] == {"usage": 1, "limit": 2}


def test_runtime_stats_reuse_daemon_precpu_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = {
        "cpu_stats": _cpu_sample(300, 2_000),
        "precpu_stats": _cpu_sample(100, 1_000),
    }
    monkeypatch.setattr(docker_utils, "get_container_stats_snapshot", lambda _c: sample)
    monkeypatch.setattr(
        "pytmbot.handlers.handlers_util.docker.time.sleep",
        lambda _s: pytest.fail("no second sample"),
    )
    assert docker_utils.collect_container_runtime_stats(object()) is sample


@pytest.mark.parametrize(
    ("state", "badge"),
    [
        ({"Status": "running", "Running": True}, "🟢 Running"),
        ({"Status": "paused", "Running": True, "Paused": True}, "🟡 Paused"),
        (
            {"Status": "restarting", "Running": True, "Restarting": True},
            "🔄 Restarting",
        ),
        ({"Status": "created"}, "⚪ Created"),
        ({"Status": "exited"}, "🔴 Stopped"),
        ({"Running": True, "Paused": True}, "🟡 Paused"),
        ({}, "🔴 Stopped"),
    ],
)
def test_status_badge_follows_state_status(state: _ObjectDict, badge: str) -> None:
    info = parse_container_basic_info(object(), attrs={"State": state})
    assert info["status_badge"] == badge
    assert info["running"] is (badge == "🟢 Running")


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("nginx", ("nginx", "latest")),
        ("nginx:1.25", ("nginx", "1.25")),
        ("registry:5000/team/app", ("registry:5000/team/app", "latest")),
        ("registry:5000/team/app:2.1", ("registry:5000/team/app", "2.1")),
        ("app:1@sha256:" + "a" * 64, ("app", "1")),
        ("app@sha256:" + "b" * 64, ("app", "sha256:" + "b" * 12)),
    ],
)
def test_split_image_reference_keeps_registry_port(
    reference: str, expected: tuple[str, str]
) -> None:
    assert docker_utils.split_image_reference(reference) == expected


def test_comprehensive_details_propagates_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pytmbot.exceptions import DockerConnectionError

    def _down(_name: str) -> object:
        raise DockerConnectionError("docker down")

    monkeypatch.setattr(docker_utils, "get_container_full_details", _down)
    with pytest.raises(DockerConnectionError):
        get_comprehensive_container_details("pytmbot")
