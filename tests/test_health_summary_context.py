from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

import pytmbot.handlers.server_handlers.health_summary as health_module


def test_health_summary_value_normalizers_and_level_helpers() -> None:
    assert health_module._metric_level(10.0, 70.0, 85.0) == "healthy"
    assert health_module._metric_level(70.0, 70.0, 85.0) == "elevated"
    assert health_module._metric_level(90.0, 70.0, 85.0) == "critical"
    assert health_module._health_badge(90.0, 70.0, 85.0) == "🔴"
    assert health_module._worst_level("healthy", "critical", "elevated") == "critical"

    assert health_module._to_int(True) == 1
    assert health_module._to_int("  42  ") == 42
    assert health_module._to_int("bad", default=7) == 7

    assert health_module._to_float(True) == 1.0
    assert health_module._to_float("  19.5% ") == 19.5
    assert health_module._to_float("bad", default=2.5) == 2.5

    assert health_module._normalize_monitor_level("healthy") == "healthy"
    assert health_module._normalize_monitor_level("BAD") == "unknown"
    assert (
        health_module._format_component_label("unknown_component")
        == "Unknown Component"
    )


def test_sanitize_component_insights_by_component_type() -> None:
    assert health_module._sanitize_component_insights(
        "polling", {"polling_active": True, "thread_alive": False}
    ) == ["Polling active: yes", "Worker thread: stopped"]

    assert health_module._sanitize_component_insights(
        "sessions",
        {"total_sessions": "3", "blocked_sessions": 1, "authenticated_sessions": 2},
    ) == [
        "Total sessions: 3",
        "Authenticated sessions: 2",
        "Blocked sessions: 1",
    ]

    assert health_module._sanitize_component_insights(
        "system_resources", {"memory_percent": "12.3", "cpu": "5.6"}
    ) == ["Bot memory usage: 12.3%", "Bot CPU usage: 5.6%"]

    assert health_module._sanitize_component_insights(
        "template_parser",
        {"cache_size": 4, "validation_errors": 1, "total_validations": 9},
    ) == ["Template cache size: 4", "Validation errors: 1/9"]

    assert health_module._sanitize_component_insights(
        "telegram_api", {"error_code": 429}
    ) == ["Telegram API error code: 429"]

    assert health_module._sanitize_component_insights(
        "unknown_component", {"error": "boom"}
    ) == ["Checker reported an internal error."]
    assert health_module._sanitize_component_insights("unknown_component", {}) == [
        "No additional issues detected."
    ]


def test_build_monitor_context_handles_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        health_module,
        "HealthStatus",
        lambda: SimpleNamespace(get_summary=lambda: {"status": "no_data"}),
    )
    context = health_module._build_monitor_context()
    assert context["available"] is False
    assert context["overall_status"] == "Initializing"
    assert context["attention_count"] == 0


def test_build_monitor_context_builds_sorted_component_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = {
        "status": "ok",
        "overall": "degraded",
        "operational": "4",
        "total": "5",
        "health_ratio": "0.8",
        "duration_ms": "12.5",
        "components": {
            "sessions": {
                "level": "healthy",
                "latency_ms": 2.0,
                "details": {"total_sessions": 3},
            },
            "polling": {
                "level": "critical",
                "latency_ms": 5.0,
                "details": {"polling_active": False},
            },
            "template_parser": {"level": "unknown", "latency_ms": 1.0, "details": {}},
        },
    }
    monkeypatch.setattr(
        health_module,
        "HealthStatus",
        lambda: SimpleNamespace(get_summary=lambda: summary),
    )
    context = health_module._build_monitor_context()
    assert context["available"] is True
    assert context["overall_level"] == "degraded"
    assert context["health_ratio_percent"] == 80.0
    assert context["attention_count"] == 1
    assert "Watch highlighted components" in str(context["action"])
    components = context["components"]
    assert isinstance(components, list)
    assert components[0]["component_name"] == "polling"


@pytest.mark.parametrize(
    ("counters", "expected_level", "expected_trend"),
    [
        (
            {
                "containers_count": 0,
                "running_containers": 0,
                "stopped_containers": 0,
                "images_count": 1,
            },
            "healthy",
            "No containers deployed",
        ),
        (
            {
                "containers_count": 3,
                "running_containers": 3,
                "stopped_containers": 0,
                "images_count": 2,
            },
            "healthy",
            "All containers are running",
        ),
        (
            {
                "containers_count": 10,
                "running_containers": 8,
                "stopped_containers": 2,
                "images_count": 2,
            },
            "elevated",
            "Mostly healthy, but has stopped workloads",
        ),
        (
            {
                "containers_count": 10,
                "running_containers": 2,
                "stopped_containers": 8,
                "images_count": 2,
            },
            "critical",
            "Many containers are currently stopped",
        ),
    ],
)
def test_build_docker_context_variants(
    monkeypatch: pytest.MonkeyPatch,
    counters: dict[str, int],
    expected_level: str,
    expected_trend: str,
) -> None:
    monkeypatch.setattr(health_module, "fetch_docker_counters", lambda: counters)
    context = health_module._build_docker_context(cpu_count=4)
    assert context["available"] is True
    assert context["level"] == expected_level
    assert context["trend_text"] == expected_trend


def test_build_docker_context_handles_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health_module,
        "fetch_docker_counters",
        lambda: (_ for _ in ()).throw(RuntimeError("docker-fail")),
    )
    context = health_module._build_docker_context(cpu_count=4)
    assert context["available"] is False
    assert context["status_label"] == "Unavailable"


def test_build_health_context_with_pressure_recommendations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health_module,
        "_build_monitor_context",
        lambda: {
            "overall_level": "critical",
            "overall_status": "Critical",
            "operational": 1,
            "total": 5,
            "attention_count": 2,
        },
    )
    monkeypatch.setattr(
        health_module,
        "psutil_adapter",
        SimpleNamespace(
            get_cpu_usage=lambda: {"cpu_percent": 95.0},
            get_memory=lambda: {
                "percent": 92.0,
                "used": "3 GiB",
                "available": "256 MiB",
            },
            get_load_average=lambda: (8.0, 6.0, 4.0),
            get_process_counts=lambda: {"total": 123},
            get_cpu_count=lambda: 4,
            get_uptime=lambda: "2:00:00",
        ),
    )
    monkeypatch.setattr(
        health_module,
        "_build_docker_context",
        lambda cpu_count: {
            "available": False,
            "level": "elevated",
            "stopped_containers": 0,
        },
    )
    context = health_module._build_health_context()
    assert context["overall_status"] == "Immediate attention"
    assert cast(int, context["health_score"]) < 100
    assert context["dominant_metric"] in {"CPU", "RAM", "Load"}
    recommendations = cast(list[str], context["recommendations"])
    assert any(
        "Review non-healthy monitor components" in item for item in recommendations
    )
    assert any("Docker metrics are unavailable" in item for item in recommendations)


def test_build_health_context_healthy_path_has_default_recommendation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health_module,
        "_build_monitor_context",
        lambda: {
            "overall_level": "healthy",
            "overall_status": "Healthy",
            "operational": 5,
            "total": 5,
            "attention_count": 0,
        },
    )
    monkeypatch.setattr(
        health_module,
        "psutil_adapter",
        SimpleNamespace(
            get_cpu_usage=lambda: {"cpu_percent": 10.0},
            get_memory=lambda: {"percent": 20.0, "used": "1 GiB", "available": "3 GiB"},
            get_load_average=lambda: (0.4, 0.3, 0.2),
            get_process_counts=lambda: {"total": 10},
            get_cpu_count=lambda: 8,
            get_uptime=lambda: "00:30:00",
        ),
    )
    monkeypatch.setattr(
        health_module,
        "_build_docker_context",
        lambda cpu_count: {
            "available": True,
            "level": "healthy",
            "stopped_containers": 0,
        },
    )
    context = health_module._build_health_context()
    assert context["overall_status"] == "Stable"
    assert context["recommendations"] == [
        "No immediate action required. Continue routine monitoring."
    ]
