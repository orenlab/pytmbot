from __future__ import annotations

from collections.abc import Callable

type PayloadScalar = str | int | float | bool | None
type PayloadValue = PayloadScalar | list["PayloadValue"] | dict[str, "PayloadValue"]
type PayloadDict = dict[str, PayloadValue]


def telegram_object_from_payload[T](
    payload: PayloadDict,
    *,
    parser: Callable[[PayloadDict], T],
    expected_type: type[T],
) -> T:
    """Build a Telegram object from a JSON-like payload."""
    parsed_object = parser(payload)
    if not isinstance(parsed_object, expected_type):
        raise AssertionError(f"Expected {expected_type.__name__} instance")
    return parsed_object


def unwrap_handler(handler: object, *, depth: int) -> object:
    """Unwrap decorated handlers for direct invocation in tests."""
    unwrapped = handler
    for _ in range(depth):
        unwrapped = getattr(unwrapped, "__wrapped__", unwrapped)
    return unwrapped


def record_callback_answer(
    storage: list[PayloadDict],
    callback_query_id: str,
    **kwargs: PayloadValue,
) -> PayloadDict:
    """Append a captured callback answer payload to test storage."""
    payload: PayloadDict = {"callback_query_id": callback_query_id, **kwargs}
    storage.append(payload)
    return payload


def record_edited_message(
    storage: list[PayloadDict],
    **kwargs: PayloadValue,
) -> PayloadDict:
    """Append a captured edit payload to test storage."""
    payload = dict(kwargs)
    storage.append(payload)
    return payload
