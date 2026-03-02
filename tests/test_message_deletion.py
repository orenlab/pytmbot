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
    stats = manager.get_statistics()
    assert stats["scheduled"] == 1
    assert stats["completed"] == 1


def test_schedule_deletion_duplicate_and_limit(
    manager: message_deletion_module._MessageDeletionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _FakeBot()
    monkeypatch.setattr("pytmbot.utils.message_deletion.threading.Thread", _NoopThread)

    first = manager.schedule_deletion(
        bot=bot,
        chat_id=100,
        message_id=201,
        user_id=2,
        delay_seconds=1,
    )
    second_same = manager.schedule_deletion(
        bot=bot,
        chat_id=100,
        message_id=201,
        user_id=2,
        delay_seconds=1,
    )
    assert first.status.name == "SCHEDULED"
    assert second_same.status.name == "ALREADY_SCHEDULED"

    manager.configure(1)
    limited = manager.schedule_deletion(
        bot=bot,
        chat_id=100,
        message_id=202,
        user_id=2,
        delay_seconds=1,
    )
    assert limited.status.name == "LIMIT_EXCEEDED"
    assert manager.get_statistics()["limit_exceeded"] >= 1


def test_schedule_deletion_validates_inputs(
    manager: message_deletion_module._MessageDeletionManager,
) -> None:
    bot = _FakeBot()
    with pytest.raises(ValueError):
        manager.schedule_deletion(bot, 1, 1, 1, delay_seconds=0)
    with pytest.raises(TypeError):
        manager.schedule_deletion(bot, 1, cast(int, "x"), 1, delay_seconds=1)
    with pytest.raises(ValueError):
        manager.configure(0)


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

    with manager._deletion_lock:
        manager._active_tasks[(3, 20)] = task
        manager._user_pending_deletions[3].add(20)

    monkeypatch.setattr("pytmbot.utils.message_deletion.time.sleep", lambda _s: None)
    manager._execute_deletion(task)

    assert callback_results
    result = callback_results[0]
    assert result.status.name == "FAILED"
    assert "Telegram API error" in (result.error_message or "")
    assert manager.get_pending_count(3) == 0


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

    with manager._deletion_lock:
        manager._active_tasks[(4, 21)] = task
        manager._user_pending_deletions[4].add(21)

    monkeypatch.setattr("pytmbot.utils.message_deletion.time.sleep", lambda _s: None)
    manager._execute_deletion(task)

    assert callback_results
    assert callback_results[0].status.name == "FAILED"
    assert "Bot instance no longer available" in (
        callback_results[0].error_message or ""
    )


def test_cancel_get_status_and_repr(
    manager: message_deletion_module._MessageDeletionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _FakeBot()
    monkeypatch.setattr("pytmbot.utils.message_deletion.threading.Thread", _NoopThread)
    manager.schedule_deletion(
        bot=bot, chat_id=1, message_id=30, user_id=5, delay_seconds=1
    )
    manager.schedule_deletion(
        bot=bot, chat_id=1, message_id=31, user_id=5, delay_seconds=1
    )

    assert manager.get_pending_count(5) == 2
    cancelled = manager.cancel_user_deletions(5)
    assert cancelled == 2
    assert manager.get_pending_count(5) == 0

    status = manager.get_system_status()
    assert "total_pending_deletions" in status
    assert "statistics" in status
    assert "_MessageDeletionManager" in repr(manager)


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
    with manager._deletion_lock:
        manager._active_tasks[(6, 40)] = task
        manager._user_pending_deletions[6].add(40)

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
