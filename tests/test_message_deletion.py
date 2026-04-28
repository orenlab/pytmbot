from __future__ import annotations

import weakref
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException

import pytmbot.utils.message_deletion as message_deletion_module

type _PayloadScalar = str | int | float | bool | None
type _PayloadValue = _PayloadScalar | list["_PayloadValue"] | dict[str, "_PayloadValue"]
type _PayloadDict = dict[str, _PayloadValue]
type _ThreadKwarg = str | int | float | bool | None


class _FakeBot(TeleBot):
    def __init__(self, *, fail: bool = False) -> None:
        super().__init__(token="12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
        self.fail = fail
        self.deleted: list[tuple[int, int]] = []

    def delete_message(
        self,
        chat_id: int | str,
        message_id: int,
        timeout: int | None = None,
    ) -> bool:
        del timeout
        if self.fail:
            api_exc_ctor = cast(
                Callable[..., ApiTelegramException], ApiTelegramException
            )
            raise api_exc_ctor(
                "deleteMessage",
                SimpleNamespace(status_code=400, text="bad"),
                {"error_code": 400, "description": "bad request"},
            )
        self.deleted.append((int(chat_id), message_id))
        return True


class _ImmediateThread:
    def __init__(
        self,
        *,
        target: Callable[..., None],
        args: tuple[message_deletion_module._DeletionTask, ...],
        **_kwargs: _ThreadKwarg,
    ) -> None:
        self._target = target
        self._args = args

    def start(self) -> None:
        self._target(*self._args)


class _NoopThread:
    def __init__(self, **_kwargs: _ThreadKwarg) -> None:
        return

    def start(self) -> None:
        return


@pytest.fixture
def manager() -> message_deletion_module._MessageDeletionManager:
    manager_instance = message_deletion_module.deletion_manager
    with manager_instance._deletion_lock:
        manager_instance._active_tasks.clear()
        manager_instance._user_pending_deletions.clear()
        manager_instance._max_pending_per_user = (
            manager_instance._DEFAULT_MAX_PENDING_PER_USER
        )
    with manager_instance._stats_lock:
        manager_instance._stats = {
            "scheduled": 0,
            "completed": 0,
            "failed": 0,
            "limit_exceeded": 0,
            "already_scheduled": 0,
        }
    return manager_instance


def _register_pending_task(
    manager: message_deletion_module._MessageDeletionManager,
    task: message_deletion_module._DeletionTask,
) -> None:
    with manager._deletion_lock:
        manager._active_tasks[(task.user_id, task.message_id)] = task
        manager._user_pending_deletions[task.user_id].add(task.message_id)


def _assert_failed_deletion_result(
    callback_results: list[message_deletion_module.DeletionResult],
    *,
    expected_error_fragment: str,
    pending_count: int,
) -> None:
    assert callback_results
    result = callback_results[0]
    assert result.status.name == "FAILED"
    assert expected_error_fragment in (result.error_message or "")
    assert pending_count == 0


def test_schedule_deletion_success_and_callback(
    manager: message_deletion_module._MessageDeletionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callback_results: list[message_deletion_module.DeletionResult] = []
    bot = _FakeBot()

    monkeypatch.setattr(
        "pytmbot.utils.message_deletion.threading.Thread", _ImmediateThread
    )
    monkeypatch.setattr("pytmbot.utils.message_deletion.time.sleep", lambda _s: None)

    result = manager.schedule_deletion(
        bot=bot,
        chat_id=100,
        message_id=200,
        user_id=1,
        delay_seconds=1,
        callback=callback_results.append,
    )

    assert result.status.name == "SCHEDULED"
    assert bot.deleted == [(100, 200)]
    assert len(callback_results) == 1
    assert callback_results[0].status.name == "SUCCESS"
    assert manager.get_pending_count(1) == 0


def test_execute_deletion_handles_api_error_and_callback(
    manager: message_deletion_module._MessageDeletionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callback_results: list[message_deletion_module.DeletionResult] = []
    failing_bot = _FakeBot(fail=True)
    task = message_deletion_module._DeletionTask(
        bot_ref=weakref.ref(failing_bot),
        chat_id=10,
        message_id=20,
        user_id=3,
        delay_seconds=1,
        callback=callback_results.append,
    )

    _register_pending_task(manager, task)

    monkeypatch.setattr("pytmbot.utils.message_deletion.time.sleep", lambda _s: None)
    manager._execute_deletion(task)

    _assert_failed_deletion_result(
        callback_results,
        expected_error_fragment="Telegram API error",
        pending_count=manager.get_pending_count(3),
    )


def test_execute_deletion_handles_missing_bot_reference(
    manager: message_deletion_module._MessageDeletionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callback_results: list[message_deletion_module.DeletionResult] = []
    dead_ref = cast(weakref.ReferenceType[TeleBot], lambda: None)

    task = message_deletion_module._DeletionTask(
        bot_ref=dead_ref,
        chat_id=11,
        message_id=21,
        user_id=4,
        delay_seconds=1,
        callback=callback_results.append,
    )

    _register_pending_task(manager, task)

    monkeypatch.setattr("pytmbot.utils.message_deletion.time.sleep", lambda _s: None)
    manager._execute_deletion(task)

    _assert_failed_deletion_result(
        callback_results,
        expected_error_fragment="Bot instance no longer available",
        pending_count=manager.get_pending_count(4),
    )


def test_cleanup_stale_references(
    manager: message_deletion_module._MessageDeletionManager,
) -> None:
    dead_ref = cast(weakref.ReferenceType[TeleBot], lambda: None)

    task = message_deletion_module._DeletionTask(
        bot_ref=dead_ref,
        chat_id=1,
        message_id=40,
        user_id=6,
        delay_seconds=1,
    )
    _register_pending_task(manager, task)

    manager._cleanup_stale_references()

    assert manager.get_pending_count(6) == 0


def test_create_post_delete_navigation_callback_sends_back_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NavBot:
        def __init__(self) -> None:
            self.messages: list[_PayloadDict] = []

        def send_message(
            self,
            chat_id: int | str,
            text: str,
            **kwargs: _PayloadValue,
        ) -> bool:
            self.messages.append({"chat_id": int(chat_id), "text": text, **kwargs})
            return True

    bot = _NavBot()
    callback_results: list[str] = []

    monkeypatch.setattr(
        message_deletion_module,
        "_build_back_navigation_keyboard",
        lambda: "back-kbd",
    )

    callback = message_deletion_module.create_post_delete_navigation_callback(
        lambda result: callback_results.append(result.status.name),
        bot=cast(TeleBot, bot),
        chat_id=77,
        navigation_text="deleted",
    )

    callback(
        message_deletion_module.DeletionResult(
            status=message_deletion_module.DeletionStatus.SUCCESS,
            message_id=1,
            user_id=1,
            pending_count=0,
        )
    )
    callback(
        message_deletion_module.DeletionResult(
            status=message_deletion_module.DeletionStatus.FAILED,
            message_id=2,
            user_id=1,
            pending_count=0,
            error_message="x",
        )
    )

    assert callback_results == ["SUCCESS", "FAILED"]
    assert len(bot.messages) == 1
    assert bot.messages[0]["chat_id"] == 77
    assert bot.messages[0]["reply_markup"] == "back-kbd"
