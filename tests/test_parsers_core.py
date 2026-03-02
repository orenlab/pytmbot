from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import pytmbot.parsers._parser as parser_module
from pytmbot.exceptions import TemplateError


@pytest.fixture(autouse=True)
def _clear_parser_caches() -> None:
    parser_module._clear_template_cache()
    parser_module._precompile_templates()


def test_resolve_template_subdirectory_for_standard_and_plugin_templates() -> None:
    parser_module._resolve_template_subdirectory.cache_clear()

    assert (
        parser_module._resolve_template_subdirectory("d_images.jinja2")
        == "docker_templates"
    )
    assert (
        parser_module._resolve_template_subdirectory("plugin_monitor_index.jinja2")
        == "plugins_template/monitor_index"
    )

    with pytest.raises(TemplateError):
        parser_module._resolve_template_subdirectory("")


def test_hash_context_handles_non_sortable_keys() -> None:
    assert isinstance(parser_module._hash_context({"a": 1}), str)
    assert parser_module._hash_context({1: "x", "a": "b"}) is None  # type: ignore[dict-item]


def test_load_template_and_render_template_paths() -> None:
    template = parser_module._load_template("b_none.jinja2")
    rendered = template.render()
    assert isinstance(rendered, str)

    cached_render = parser_module._render_template("b_none.jinja2", trusted=True)
    assert isinstance(cached_render, str)

    with pytest.raises(TemplateError):
        parser_module._load_template("does_not_exist.jinja2")


def test_render_template_strict_validation_rejects_untrusted_name() -> None:
    with pytest.raises(TemplateError):
        parser_module._render_template("../evil.jinja2", trusted=False)


def test_environment_missing_template_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_module._clear_template_cache()
    missing_dir = Path.cwd() / "definitely_missing_templates_dir_for_tests"
    monkeypatch.setattr(
        parser_module,
        "var_config",
        SimpleNamespace(template_path=str(missing_dir)),
    )
    with pytest.raises(TemplateError):
        parser_module._get_jinja_environment()


def test_cache_stats_and_clear_flow() -> None:
    parser_module._render_template("b_none.jinja2", trusted=True)
    parser_module._render_template("b_none.jinja2", trusted=True)

    stats = parser_module._get_cache_stats()
    assert "template_cache_size" in stats
    assert "result_cache_size" in stats
    assert "validation" in stats

    parser_module._clear_template_cache()
    stats_after_clear = parser_module._get_cache_stats()
    assert stats_after_clear["template_cache_size"] == 0
