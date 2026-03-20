from __future__ import annotations

import pytest

import pytmbot.parsers.compiler as compiler_module
from pytmbot.exceptions import ErrorContext, TemplateError
from pytmbot.parsers.compiler import (
    Compiler,
    TemplateType,
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

type _ContextScalar = str | int | float | bool | None
type _ContextValue = _ContextScalar | dict[str, "_ContextValue"] | list["_ContextValue"]
type _ContextDict = dict[str, _ContextValue]


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
    assert (
        validate_template_render("b_x.jinja2", {"key": "v"}, trusted=True)[0]
        == "b_x.jinja2"
    )
    with pytest.raises(TemplateError):
        validate_template_render("b_x.jinja2", {"bad-key": "v"}, trusted=False)


def test_compiler_template_type_detection() -> None:
    assert Compiler("a_login.jinja2").template_type == TemplateType.AUTH
    assert Compiler("b_menu.jinja2").template_type == TemplateType.BASE
    assert Compiler("d_stats.jinja2").template_type == TemplateType.DOCKER
    assert Compiler("plugin_metrics.jinja2").template_type == TemplateType.PLUGIN
    with pytest.raises(TemplateError):
        _ = Compiler("unknown.jinja2").template_type


def test_compiler_compile_success_and_quick_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: _ContextDict = {}

    def _fake_render(
        template_name: str, *, trusted: bool, **context: _ContextValue
    ) -> str:
        calls["template_name"] = template_name
        calls["trusted"] = trusted
        calls["context"] = context
        return "rendered"

    monkeypatch.setattr(compiler_module, "_render_template", _fake_render)

    compiler = Compiler("d_demo.jinja2", trusted=False, value=42)
    assert compiler.compile() == "rendered"
    assert calls["template_name"] == "d_demo.jinja2"
    assert calls["trusted"] is False
    assert calls["context"] in ({"value": 42}, {"context": {"value": 42}})

    assert Compiler.quick_render("b_demo.jinja2", v=1) == "rendered"
    assert calls["trusted"] is True


def test_compiler_compile_error_wrapping(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_generic(*_args: _ContextValue, **_kwargs: _ContextValue) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(compiler_module, "_render_template", _raise_generic)

    with pytest.raises(TemplateError) as exc_info:
        Compiler("d_demo.jinja2", trusted=True).compile()

    assert exc_info.value.context.error_code == "TEMPLATE_COMPILATION_ERROR"
    assert exc_info.value.context.metadata["template_name"] == "d_demo.jinja2"


def test_compiler_compile_reraises_template_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = TemplateError(
        ErrorContext(
            message="bad template",
            error_code="TEMPLATE_FAIL",
            metadata={"key": "value"},
        )
    )

    def _raise_template_error(*_args: _ContextValue, **_kwargs: _ContextValue) -> str:
        raise original

    monkeypatch.setattr(compiler_module, "_render_template", _raise_template_error)

    with pytest.raises(TemplateError) as exc_info:
        Compiler("d_demo.jinja2").compile()
    assert exc_info.value is original
