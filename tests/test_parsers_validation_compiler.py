from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

import pytmbot.parsers.compiler as compiler_module
import pytmbot.parsers.validation as validation_module
from pytmbot.exceptions import ErrorContext, TemplateError
from pytmbot.parsers.compiler import (
    Compiler,
    TemplateType,
    render_auth_template,
    render_base_template,
    render_docker_template,
)
from pytmbot.parsers.validation import (
    TemplateValidator,
    is_safe_context_key,
    is_safe_context_value,
    is_safe_template_name,
    validate_context_basic,
    validate_context_strict,
    validate_template_name_cached,
    validate_template_name_fast,
    validate_template_render,
)


def test_validation_helpers_reject_unsafe_input() -> None:
    assert is_safe_template_name("d_ok.jinja2") is True
    assert is_safe_template_name("../secret.jinja2") is False
    assert is_safe_template_name("bad/name.jinja2") is False

    assert is_safe_context_key("service_name") is True
    assert is_safe_context_key("self") is False
    assert is_safe_context_key("invalid-key") is False

    assert is_safe_context_value("ok") is True
    assert is_safe_context_value(lambda: None) is False


def test_validation_paths_for_fast_and_strict_modes() -> None:
    assert validate_template_name_fast("b_main.jinja2") == "b_main.jinja2"
    with pytest.raises(TemplateError):
        validate_template_name_fast("../evil.jinja2")

    assert validate_template_name_cached("d_images.jinja2") == "d_images.jinja2"
    with pytest.raises(TemplateError):
        validate_template_name_cached("..")

    context = {"service": "nginx", "count": 1}
    assert validate_context_basic(context) == context
    assert validate_context_strict(context) == context
    with pytest.raises(TemplateError):
        validate_context_strict({"bad-key": "value"})
    with pytest.raises(TemplateError):
        validate_context_strict({"ok": lambda: None})


def test_template_validator_tracks_stats() -> None:
    validator = TemplateValidator()
    valid_name, valid_context = validator.validate_render_params(
        "b_test.jinja2",
        {"name": "ok"},
        strict=True,
    )
    assert valid_name == "b_test.jinja2"
    assert valid_context == {"name": "ok"}

    with pytest.raises(TemplateError):
        validator.validate_render_params("..", {"name": "ok"}, strict=False)

    stats = validator.get_stats()
    assert stats["strict_validations"] == 1
    assert stats["validation_errors"] == 1


def test_validate_template_render_switches_mode() -> None:
    assert validate_template_render("b_x.jinja2", {"key": "v"}, trusted=True)[0] == "b_x.jinja2"
    with pytest.raises(TemplateError):
        validate_template_render("b_x.jinja2", {"bad-key": "v"}, trusted=False)


def test_compiler_template_type_detection() -> None:
    assert Compiler("a_login.jinja2").template_type == TemplateType.AUTH
    assert Compiler("b_menu.jinja2").template_type == TemplateType.BASE
    assert Compiler("d_stats.jinja2").template_type == TemplateType.DOCKER
    assert Compiler("plugin_metrics.jinja2").template_type == TemplateType.PLUGIN
    assert Compiler("unknown.jinja2").template_type == TemplateType.DOCKER


def test_compiler_compile_success_and_quick_render(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    def _fake_render(template_name: str, *, trusted: bool, **context: Any) -> str:
        calls["template_name"] = template_name
        calls["trusted"] = trusted
        calls["context"] = context
        return "rendered"

    monkeypatch.setattr(compiler_module, "_render_template", _fake_render)

    compiler = Compiler("d_demo.jinja2", trusted=False, value=42)
    assert compiler.compile() == "rendered"
    assert calls["template_name"] == "d_demo.jinja2"
    assert calls["trusted"] is False
    assert calls["context"] == {"value": 42}

    assert Compiler.quick_render("b_demo.jinja2", v=1) == "rendered"
    assert calls["trusted"] is True


def test_compiler_compile_error_wrapping(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_generic(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(compiler_module, "_render_template", _raise_generic)

    with pytest.raises(TemplateError) as exc_info:
        Compiler("d_demo.jinja2", trusted=True).compile()

    assert exc_info.value.context.error_code == "TEMPLATE_COMPILATION_ERROR"
    assert exc_info.value.context.metadata["template_name"] == "d_demo.jinja2"


def test_compiler_compile_reraises_template_error(monkeypatch: pytest.MonkeyPatch) -> None:
    original = TemplateError(
        ErrorContext(
            message="bad template",
            error_code="TEMPLATE_FAIL",
            metadata={"key": "value"},
        )
    )

    def _raise_template_error(*_args: Any, **_kwargs: Any) -> str:
        raise original

    monkeypatch.setattr(compiler_module, "_render_template", _raise_template_error)

    with pytest.raises(TemplateError) as exc_info:
        Compiler("d_demo.jinja2").compile()
    assert exc_info.value is original


def test_compiler_stats_and_cache_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compiler_module, "_get_cache_stats", lambda: {"templates": 2})
    clear_called = {"value": False}

    def _clear_cache() -> None:
        clear_called["value"] = True

    monkeypatch.setattr(compiler_module, "_clear_template_cache", _clear_cache)

    assert Compiler("d_demo.jinja2").get_compiler_stats() == {"templates": 2}
    Compiler.clear_all_caches()
    assert clear_called["value"] is True


def test_compiler_validate_template_params_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_validate(
        template_name: str,
        context: dict[str, Any],
        trusted: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        assert template_name == "b_template.jinja2"
        assert context == {"x": 1}
        assert trusted is True
        return template_name, context

    monkeypatch.setattr(validation_module, "validate_template_render", _fake_validate)
    assert Compiler.validate_template_params("b_template.jinja2", {"x": 1}, trusted=True) == (
        "b_template.jinja2",
        {"x": 1},
    )


@pytest.mark.parametrize(
    ("func", "template_name", "expected_error"),
    [
        (render_docker_template, "b_wrong.jinja2", "INVALID_DOCKER_TEMPLATE"),
        (render_auth_template, "d_wrong.jinja2", "INVALID_AUTH_TEMPLATE"),
        (render_base_template, "a_wrong.jinja2", "INVALID_BASE_TEMPLATE"),
    ],
)
def test_render_helpers_validate_template_prefix(
    func: Callable[..., str],
    template_name: str,
    expected_error: str,
) -> None:
    with pytest.raises(TemplateError) as exc_info:
        func(template_name, key="value")
    assert exc_info.value.context.error_code == expected_error


def test_render_helpers_call_compiler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Compiler, "compile", lambda self: f"rendered:{self.template_name}")

    assert render_docker_template("d_ok.jinja2") == "rendered:d_ok.jinja2"
    assert render_auth_template("a_ok.jinja2") == "rendered:a_ok.jinja2"
    assert render_base_template("b_ok.jinja2") == "rendered:b_ok.jinja2"
