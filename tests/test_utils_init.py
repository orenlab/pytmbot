from __future__ import annotations

import pytest

import pytmbot.utils as utils_module


def test_utils_getattr_resolves_known_exports() -> None:
    assert callable(utils_module.parse_cli_args)
    assert callable(utils_module.round_up_tuple)
    assert callable(utils_module.set_naturalsize)
    assert callable(utils_module.get_message_full_info)
    assert callable(utils_module.is_new_name_valid)
    assert callable(utils_module.generate_secret_token)


def test_utils_getattr_unknown_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        _ = utils_module.not_existing_name
