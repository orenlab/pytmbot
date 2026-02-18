from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest
from telebot import TeleBot
from telebot.types import Message

import pytmbot.handlers.server_handlers.services as services_module
from pytmbot import exceptions
from pytmbot.handlers.server_handlers.services import ServicesAdapter


def _completed_process(
    stdout: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["cmd"],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


def _new_adapter(monkeypatch: pytest.MonkeyPatch, *, systemd_available: bool) -> ServicesAdapter:
    monkeypatch.setattr(
        ServicesAdapter,
        "_check_systemd_availability",
        lambda self: systemd_available,
    )
    return ServicesAdapter()


def _raw_handle_services_status() -> Callable[[Message, TeleBot], Message | None]:
    raw = getattr(
        services_module.handle_services_status,
        "__wrapped__",
        services_module.handle_services_status,
    )
    return cast(Callable[[Message, TeleBot], Message | None], raw)


@dataclass
class _DummyChat:
    id: int = 100


@dataclass
class _DummyUser:
    id: int = 200


@dataclass
class _DummyMessage:
    chat: _DummyChat = field(default_factory=_DummyChat)
    from_user: _DummyUser | None = field(default_factory=_DummyUser)


@dataclass
class _DummyBot:
    actions: list[tuple[int, str]] = field(default_factory=list)
    sent_messages: list[dict[str, object]] = field(default_factory=list)

    def send_chat_action(self, chat_id: int, action: str) -> bool:
        self.actions.append((chat_id, action))
        return True

    def send_message(self, chat_id: int, text: str, **kwargs: object) -> str:
        self.sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return "sent"


def test_safe_subprocess_run_validates_and_handles_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert ServicesAdapter._safe_subprocess_run([]) is None

    def _timeout_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=["cmd"], timeout=1)

    monkeypatch.setattr(services_module.subprocess, "run", _timeout_run)
    assert ServicesAdapter._safe_subprocess_run(["/bin/echo", "ok"]) is None

    monkeypatch.setattr(
        services_module.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed_process("ok", 0),
    )
    result = ServicesAdapter._safe_subprocess_run(["/bin/echo", "ok"])
    assert result is not None
    assert result.stdout == "ok"


def test_safe_subprocess_run_returns_none_on_os_or_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _value_error_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise ValueError("bad")

    monkeypatch.setattr(services_module.subprocess, "run", _value_error_run)
    assert ServicesAdapter._safe_subprocess_run(["/bin/echo", "ok"]) is None


def test_parse_rc_status_output_groups_services_by_runlevel() -> None:
    output = """
Runlevel: default
  nginx      [ started ]
  redis      [ stopped ]
Runlevel: boot
  udev       [ started ]
  badsvc     [ crashed ]
"""
    parsed = ServicesAdapter._parse_rc_status_output(output)
    assert parsed["total"] == 4
    assert parsed["started"] == 2
    assert parsed["stopped"] == 2
    assert parsed["by_runlevel"]["default"]["started"] == ["nginx"]
    assert parsed["by_runlevel"]["default"]["stopped"] == ["redis"]
    assert parsed["by_runlevel"]["boot"]["stopped"] == ["badsvc"]


def test_check_systemd_availability_tries_paths_and_nsenter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakePath:
        def __init__(self, value: str) -> None:
            self._value = value

        def exists(self) -> bool:
            return self._value == "/host/usr/bin/systemctl"

        def is_file(self) -> bool:
            return self._value == "/host/usr/bin/systemctl"

    monkeypatch.setattr(services_module, "Path", _FakePath)
    monkeypatch.setattr(ServicesAdapter, "_test_systemctl_command", lambda command: True)

    adapter = _new_adapter(monkeypatch, systemd_available=True)
    assert adapter._check_systemd_availability() is True


def test_check_systemd_availability_returns_false_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenPath:
        def __init__(self, value: str) -> None:
            del value

        def exists(self) -> bool:
            raise OSError("boom")

        def is_file(self) -> bool:
            return False

    monkeypatch.setattr(services_module, "Path", _BrokenPath)
    adapter = ServicesAdapter.__new__(ServicesAdapter)
    assert adapter._check_systemd_availability() is False


def test_get_systemctl_command_prefix_fallback_order(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakePath:
        def __init__(self, value: str) -> None:
            self._value = value

        def exists(self) -> bool:
            return self._value == "/bin/nsenter"

    monkeypatch.setattr(services_module, "Path", _FakePath)
    prefix = ServicesAdapter._get_systemctl_command_prefix()
    assert prefix == ["/bin/nsenter", "-t", "1", "-p", "-m", "systemctl"]


def test_get_systemd_services_returns_none_on_invalid_json_or_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter(monkeypatch, systemd_available=True)
    monkeypatch.setattr(adapter, "_get_systemctl_command_prefix", lambda: ["/bin/systemctl"])
    monkeypatch.setattr(adapter, "_safe_subprocess_run", lambda command, timeout=10: None)
    assert adapter.get_systemd_services() is None

    monkeypatch.setattr(
        adapter,
        "_safe_subprocess_run",
        lambda command, timeout=10: _completed_process("not-json", 0),
    )
    assert adapter.get_systemd_services() is None


def test_get_service_status_returns_none_when_subprocess_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter(monkeypatch, systemd_available=True)
    monkeypatch.setattr(adapter, "_get_systemctl_command_prefix", lambda: ["/bin/systemctl"])
    monkeypatch.setattr(
        adapter,
        "_safe_subprocess_run",
        lambda command, timeout=10: (_ for _ in ()).throw(RuntimeError("failed")),
    )
    assert adapter._get_service_status("nginx") is None


def test_get_alpine_services_returns_none_when_command_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter(monkeypatch, systemd_available=False)

    def _fake_exists(path_obj: Path) -> bool:
        return str(path_obj) == "/sbin/rc-status"

    monkeypatch.setattr(services_module.Path, "exists", _fake_exists, raising=False)
    monkeypatch.setattr(
        services_module.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed_process("", 1),
    )
    assert adapter.get_alpine_services() is None


def test_cache_cast_helpers_validate_shape() -> None:
    assert ServicesAdapter._as_systemd_services_info({"bad": "data"}) is None
    assert ServicesAdapter._as_alpine_services_info({"bad": "data"}) is None

    systemd = ServicesAdapter._as_systemd_services_info(
        {
            "total_services": 10,
            "active_services": 9,
            "failed_services": 1,
            "critical_services": {},
            "available": True,
        }
    )
    assert systemd is not None
    assert systemd["total_services"] == 10

    alpine = ServicesAdapter._as_alpine_services_info(
        {
            "total_services": 3,
            "started_services": 2,
            "stopped_services": 1,
            "services_by_runlevel": {"default": {"started": ["a"], "stopped": ["b"]}},
            "available": True,
            "type": "openrc",
        }
    )
    assert alpine is not None
    assert alpine["type"] == "openrc"


def test_get_service_status_validates_name_and_parses_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter(monkeypatch, systemd_available=True)
    assert adapter._get_service_status("invalid;name") is None

    monkeypatch.setattr(adapter, "_get_systemctl_command_prefix", lambda: ["/bin/systemctl"])

    def _fake_safe_run(command: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
        del timeout
        if "is-active" in command:
            return _completed_process("active\n", 0)
        return _completed_process("enabled\n", 0)

    monkeypatch.setattr(adapter, "_safe_subprocess_run", _fake_safe_run)
    status = adapter._get_service_status("nginx")
    assert status is not None
    assert status["active"] == "active"
    assert status["enabled"] == "enabled"
    assert status["exists"] is True


def test_get_systemd_services_parses_and_uses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter(monkeypatch, systemd_available=True)
    monkeypatch.setattr(adapter, "_get_systemctl_command_prefix", lambda: ["/bin/systemctl"])

    units_payload = [
        {"unit": "ssh.service", "active": "active"},
        {"unit": "nginx.service", "active": "failed"},
        {"unit": "cron.service", "active": "active"},
    ]

    def _fake_safe_run(command: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
        del timeout
        assert "--output=json" in command
        return _completed_process(json.dumps(units_payload), 0)

    monkeypatch.setattr(adapter, "_safe_subprocess_run", _fake_safe_run)
    monkeypatch.setattr(
        adapter,
        "_get_service_status",
        lambda service: {"active": "active", "enabled": "enabled", "exists": True}
        if service == "ssh"
        else None,
    )

    first = adapter.get_systemd_services()
    assert first is not None
    assert first["total_services"] == 3
    assert first["active_services"] == 2
    assert first["failed_services"] == 1
    assert "ssh" in first["critical_services"]

    monkeypatch.setattr(
        adapter,
        "_safe_subprocess_run",
        lambda _command, timeout=10: (_ for _ in ()).throw(AssertionError("cache miss")),
    )
    second = adapter.get_systemd_services()
    assert second == first


def test_get_alpine_services_parses_rc_status_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter(monkeypatch, systemd_available=False)

    def _fake_exists(path_obj: Path) -> bool:
        return str(path_obj) == "/sbin/rc-status"

    monkeypatch.setattr(services_module.Path, "exists", _fake_exists, raising=False)
    monkeypatch.setattr(
        services_module.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed_process(
            "Runlevel: default\n  nginx [ started ]\n  redis [ stopped ]\n",
            0,
        ),
    )

    info = adapter.get_alpine_services()
    assert info is not None
    assert info["available"] is True
    assert info["type"] == "openrc"
    assert info["total_services"] == 2
    assert info["started_services"] == 1
    assert info["stopped_services"] == 1


def test_get_services_summary_marks_available_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter(monkeypatch, systemd_available=True)
    monkeypatch.setattr(adapter, "get_systemd_services", lambda: {"available": True})
    monkeypatch.setattr(adapter, "get_alpine_services", lambda: None)

    summary = adapter.get_services_summary()
    assert summary["available_sources"] == ["systemd"]
    assert summary["cache_info"]["cache_ttl"] == adapter.CACHE_TTL


def test_handle_services_status_denies_unauthorized_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        services_module,
        "settings",
        type(
            "_Settings",
            (),
            {
                "access_control": type(
                    "_Access",
                    (),
                    {"allowed_user_ids": [123]},
                )()
            },
        )(),
    )
    monkeypatch.setattr(
        services_module,
        "em",
        type("_Emoji", (), {"get_emoji": staticmethod(lambda _name: "⚠️")})(),
    )
    message = _DummyMessage(from_user=_DummyUser(id=999))
    bot = _DummyBot()
    handler = _raw_handle_services_status()
    handler(
        cast(Message, message),
        cast(TeleBot, bot),
    )
    assert "do not have access rights" in str(bot.sent_messages[0]["text"])


def test_handle_services_status_returns_no_sources_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        services_module,
        "settings",
        type(
            "_Settings",
            (),
            {
                "access_control": type(
                    "_Access",
                    (),
                    {"allowed_user_ids": [200]},
                )()
            },
        )(),
    )
    monkeypatch.setattr(
        ServicesAdapter,
        "get_services_summary",
        lambda self: {"available_sources": []},
    )
    monkeypatch.setattr(
        services_module,
        "em",
        type(
            "_Emoji",
            (),
            {"get_emoji": staticmethod(lambda _name: {"warning": "⚠️", "gear": "⚙️"}.get(_name, "x"))},
        )(),
    )
    message = _DummyMessage(from_user=_DummyUser(id=200))
    bot = _DummyBot()
    handler = _raw_handle_services_status()
    handler(
        cast(Message, message),
        cast(TeleBot, bot),
    )
    assert "No services information available" in str(bot.sent_messages[-1]["text"])


def test_handle_services_status_successful_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        services_module,
        "settings",
        type(
            "_Settings",
            (),
            {
                "access_control": type(
                    "_Access",
                    (),
                    {"allowed_user_ids": [200]},
                )()
            },
        )(),
    )
    monkeypatch.setattr(
        ServicesAdapter,
        "get_services_summary",
        lambda self: {
            "available_sources": ["systemd"],
            "systemd": {"available": True},
            "alpine": None,
        },
    )
    monkeypatch.setattr(
        services_module.Compiler,
        "quick_render",
        lambda template_name, context, **kwargs: f"render:{template_name}:{context['has_systemd']}",
    )
    monkeypatch.setattr(
        services_module,
        "em",
        type("_Emoji", (), {"get_emoji": staticmethod(lambda _name: "•")})(),
    )

    message = _DummyMessage(from_user=_DummyUser(id=200))
    bot = _DummyBot()
    handler = _raw_handle_services_status()
    handler(
        cast(Message, message),
        cast(TeleBot, bot),
    )
    assert bot.actions == [(100, "typing")]
    assert str(bot.sent_messages[-1]["text"]).startswith("render:b_services_status.jinja2:True")


def test_handle_services_status_wraps_template_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        services_module,
        "settings",
        type(
            "_Settings",
            (),
            {
                "access_control": type(
                    "_Access",
                    (),
                    {"allowed_user_ids": [200]},
                )()
            },
        )(),
    )
    monkeypatch.setattr(
        ServicesAdapter,
        "get_services_summary",
        lambda self: {
            "available_sources": ["systemd"],
            "systemd": {"available": True},
            "alpine": None,
        },
    )
    monkeypatch.setattr(
        services_module.Compiler,
        "quick_render",
        lambda template_name, context, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        services_module,
        "em",
        type("_Emoji", (), {"get_emoji": staticmethod(lambda _name: "⚠️")})(),
    )

    message = _DummyMessage(from_user=_DummyUser(id=200))
    bot = _DummyBot()
    handler = _raw_handle_services_status()
    with pytest.raises(exceptions.HandlingException) as exc_info:
        handler(
            cast(Message, message),
            cast(TeleBot, bot),
        )
    assert exc_info.value.context.error_code == "HAND_SERVICES_001"
    assert "boom" in str(exc_info.value.context.metadata["exception"])
