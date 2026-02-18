from __future__ import annotations

import warnings

import pytest

import pytmbot.globals as globals_module
from pytmbot.middleware.session_manager import SessionManager


def test_require_instance_type_guard() -> None:
    assert globals_module._require_instance("ok", str, "v") == "ok"
    with pytest.raises(TypeError):
        globals_module._require_instance("ok", int, "v")


def test_global_getters_are_cached_singletons() -> None:
    globals_module.get_session_manager.cache_clear()
    globals_module.get_keyboards.cache_clear()
    globals_module.get_emoji_converter.cache_clear()
    globals_module.get_psutil_adapter.cache_clear()
    globals_module.is_docker_environment.cache_clear()

    assert isinstance(globals_module.get_session_manager(), SessionManager)
    assert globals_module.get_session_manager() is globals_module.get_session_manager()
    assert globals_module.get_keyboards() is globals_module.get_keyboards()
    assert globals_module.get_emoji_converter() is globals_module.get_emoji_converter()
    assert globals_module.get_psutil_adapter() is globals_module.get_psutil_adapter()
    assert isinstance(globals_module.is_docker_environment(), bool)


def test_globals_deprecated_aliases_and_unknown_attribute() -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", DeprecationWarning)
        assert globals_module.__getattr__("button_data") is globals_module.ButtonDataType
        assert globals_module.__getattr__("keyboards") is globals_module.get_keyboards()
        assert globals_module.__getattr__("em") is globals_module.get_emoji_converter()
        assert (
            globals_module.__getattr__("psutil_adapter")
            is globals_module.get_psutil_adapter()
        )
        assert (
            globals_module.__getattr__("running_in_docker")
            == globals_module.is_docker_environment()
        )
        assert globals_module.__getattr__("session_manager") is globals_module.get_session_manager()

    assert len(captured) >= 6
    assert all(isinstance(item.message, DeprecationWarning) for item in captured)

    with pytest.raises(AttributeError):
        globals_module.__getattr__("missing_attribute")
