from __future__ import annotations

import builtins
from types import ModuleType

import pytest

from pytmbot.health_system import HealthLevel
from pytmbot.parsers.health_checker import TemplateParserChecker

type _ImportValue = str | int | float | bool | None


def test_template_parser_checker_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = TemplateParserChecker(cache_ttl=30.0)
    calls = {"count": 0}

    def _fake_cache_stats() -> dict[str, int]:
        calls["count"] += 1
        return {"template_cache_size": 10}

    def _fake_validation_stats() -> dict[str, int]:
        return {"validation_errors": 0, "fast_validations": 3, "strict_validations": 1}

    now = {"value": 1000.0}
    perf = {"value": 10.0}

    def _fake_time() -> float:
        return now["value"]

    def _fake_perf_counter() -> float:
        perf["value"] += 0.01
        return perf["value"]

    monkeypatch.setattr("pytmbot.parsers._parser._get_cache_stats", _fake_cache_stats)
    monkeypatch.setattr(
        "pytmbot.parsers.validation.get_validation_stats",
        _fake_validation_stats,
    )
    monkeypatch.setattr("pytmbot.parsers.health_checker.time.time", _fake_time)
    monkeypatch.setattr(
        "pytmbot.parsers.health_checker.time.perf_counter",
        _fake_perf_counter,
    )

    first = checker.check_sync()
    now["value"] = 1005.0
    second = checker.check_sync()

    assert first.level == HealthLevel.HEALTHY
    assert second is first
    assert calls["count"] == 1


@pytest.mark.parametrize(
    ("cache_size", "validation_errors", "fast", "strict", "expected"),
    [
        (90, 0, 0, 0, HealthLevel.DEGRADED),
        (10, 3, 10, 0, HealthLevel.DEGRADED),
        (10, 1, 20, 0, HealthLevel.HEALTHY),
        (10, 0, 0, 0, HealthLevel.HEALTHY),
    ],
)
def test_template_parser_checker_health_levels(
    monkeypatch: pytest.MonkeyPatch,
    cache_size: int,
    validation_errors: int,
    fast: int,
    strict: int,
    expected: HealthLevel,
) -> None:
    checker = TemplateParserChecker(cache_ttl=0.0)
    monkeypatch.setattr(
        "pytmbot.parsers._parser._get_cache_stats",
        lambda: {"template_cache_size": cache_size},
    )
    monkeypatch.setattr(
        "pytmbot.parsers.validation.get_validation_stats",
        lambda: {
            "validation_errors": validation_errors,
            "fast_validations": fast,
            "strict_validations": strict,
        },
    )

    result = checker.check_sync()
    assert result.level == expected
    assert result.component == "template_parser"


def test_template_parser_checker_returns_offline_on_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = TemplateParserChecker(cache_ttl=0.0)
    real_import = builtins.__import__

    def _fake_import(
        name: str,
        globals_dict: dict[str, _ImportValue] | None = None,
        locals_dict: dict[str, _ImportValue] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> ModuleType:
        if name == "pytmbot.parsers._parser":
            raise ImportError("parser unavailable")
        return real_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    result = checker.check_sync()

    assert result.level == HealthLevel.OFFLINE
    assert result.details["error"] == "parser_unavailable"


def test_template_parser_checker_returns_critical_on_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = TemplateParserChecker(cache_ttl=0.0)

    def _broken_cache_stats() -> dict[str, int]:
        raise RuntimeError("failed to read parser cache")

    monkeypatch.setattr("pytmbot.parsers._parser._get_cache_stats", _broken_cache_stats)
    result = checker.check_sync()

    assert result.level == HealthLevel.CRITICAL
    error_message = result.details["error"]
    assert isinstance(error_message, str)
    assert "failed to read parser cache" in error_message
