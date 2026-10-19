"""Docker update check against a local fake Docker Hub (no real network)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import pytmbot.adapters.docker.updates as updates_module
from pytmbot.adapters.docker.updates import (
    CheckFailure,
    DockerImageUpdater,
    UpdaterResponse,
    UpdaterStatus,
    parse_retry_after,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64

type _Reply = tuple[int, dict[str, str], bytes]


def _tags_reply(*names: str) -> _Reply:
    body = json.dumps(
        {
            "results": [
                {
                    "name": name,
                    "tag_last_pushed": "2026-02-01T00:00:00Z",
                    "digest": DIGEST_B,
                }
                for name in names
            ]
        }
    ).encode()
    return 200, {"Content-Type": "application/json"}, body


@dataclass
class FakeDockerHub:
    """Serve scripted replies and record every request path."""

    port: int = 0
    paths: list[str] = field(default_factory=list)
    replies: dict[str, list[_Reply]] = field(default_factory=dict)
    delay: float = 0.0
    release: threading.Event = field(default_factory=threading.Event)
    active: int = 0
    max_active: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def reply_for(self, path: str) -> _Reply:
        with self.lock:
            self.paths.append(path)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                self.release.wait(self.delay)
            repository = path.split("/v2/repositories/", 1)[1].split("/tags/", 1)[0]
            scripted = self.replies.get(repository) or [_tags_reply("1.0.0", "1.0.1")]
            return scripted.pop(0) if len(scripted) > 1 else scripted[0]
        finally:
            with self.lock:
                self.active -= 1

    def requests_for(self, repository: str) -> list[str]:
        return [path for path in self.paths if f"/{repository}/tags/" in path]


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeDockerHub]:
    fake = FakeDockerHub()

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            del format, args

        def do_GET(self) -> None:  # noqa: N802
            status, headers, body = fake.reply_for(self.path)
            try:
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                return  # the client gave up (deadline or timeout)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    fake.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        updates_module,
        "_DOCKER_HUB_TAGS_URL",
        f"http://127.0.0.1:{fake.port}/v2/repositories/{{path}}/tags/"
        "?page_size={page_size}&ordering=last_updated",
    )
    monkeypatch.setattr(updates_module, "RETRY_DELAY", 0.0)
    try:
        yield fake
    finally:
        fake.release.set()
        server.shutdown()
        server.server_close()


def _local(*repositories: str) -> dict[str, list[dict[str, str | None]]]:
    return {
        repository: [
            {"tag": "1.0.0", "created_at": "2026-01-01T00:00:00Z", "digest": DIGEST_A}
        ]
        for repository in repositories
    }


def _run(updater: DockerImageUpdater, deadline: float = 30.0) -> UpdaterResponse:
    return asyncio.run(updater._check_updates(deadline))


def _results(response: UpdaterResponse) -> dict[str, dict[str, object]]:
    assert isinstance(response.data, dict)
    return response.data


def test_single_request_per_repository_with_paging(hub: FakeDockerHub) -> None:
    updater = DockerImageUpdater()
    updater.local_images = _local("nginx", "acme/app")

    response = _run(updater)

    assert response.status == UpdaterStatus.SUCCESS
    assert sorted(hub.paths) == [
        "/v2/repositories/acme/app/tags/?page_size=100&ordering=last_updated",
        "/v2/repositories/library/nginx/tags/?page_size=100&ordering=last_updated",
    ]
    updates = _results(response)["nginx:1.0.0"]["updates"]
    assert isinstance(updates, list)
    # 1.0.1 is newer; 1.0.0 itself was republished with another digest.
    assert [update["newer_tag"] for update in updates] == ["1.0.1", "1.0.0"]


def test_requests_do_not_queue_for_pooled_connections(hub: FakeDockerHub) -> None:
    hub.delay = 0.3
    updater = DockerImageUpdater()
    updater.local_images = _local(*(f"acme/app{index}" for index in range(5)))

    _run(updater)

    assert hub.max_active == updates_module.MAX_CONCURRENT_REPOS


def test_rate_limit_keeps_other_results_and_reports_the_wait(
    hub: FakeDockerHub,
) -> None:
    retry_at = datetime.now(UTC) + timedelta(minutes=10)
    hub.replies["acme/limited"] = [
        (429, {"Retry-After": format_datetime(retry_at, usegmt=True)}, b"")
    ]
    updater = DockerImageUpdater()
    updater.local_images = _local("acme/limited", "acme/ok")

    response = _run(updater)

    assert response.status == UpdaterStatus.PARTIAL_SUCCESS
    results = _results(response)
    assert results["acme/ok:1.0.0"]["updates"]
    limited = results["acme/limited:1.0.0"]
    assert limited["error"] == CheckFailure.RATE_LIMITED.value
    retry_after = limited["retry_after"]
    assert isinstance(retry_after, int) and 590 <= retry_after <= 600
    assert response.metadata["retry_after"] == retry_after
    assert response.metadata["rate_limited_repos"] == ["acme/limited:1.0.0"]

    # The shared backoff and cache persist: the next check sends nothing.
    requests_before = len(hub.paths)
    again = _run(updater)
    assert len(hub.paths) == requests_before
    assert _results(again)["acme/ok:1.0.0"]["updates"]
    assert _results(again)["acme/limited:1.0.0"]["reason"] == "RATE_LIMITED"


def test_retry_after_in_seconds_is_honoured(hub: FakeDockerHub) -> None:
    hub.replies["acme/limited"] = [(429, {"Retry-After": "120"}, b"")]
    updater = DockerImageUpdater()
    updater.local_images = _local("acme/limited")

    response = _run(updater)

    assert response.status == UpdaterStatus.RATE_LIMITED
    assert response.metadata["retry_after"] in {119, 120}
    assert updater.rate_limiter.retry_after() in {119, 120}


def test_errors_are_not_cached(hub: FakeDockerHub) -> None:
    hub.replies["acme/flaky"] = [
        (503, {}, b"down"),
        (503, {}, b"down"),
        _tags_reply("1.0.0", "1.0.2"),
    ]
    updater = DockerImageUpdater()
    updater.local_images = _local("acme/flaky")

    first = _results(_run(updater))["acme/flaky:1.0.0"]
    assert first["error"] == "registry error (HTTP 503)"
    assert len(hub.requests_for("acme/flaky")) == 2  # one retry

    second = _results(_run(updater))["acme/flaky:1.0.0"]
    assert "error" not in second
    assert len(hub.requests_for("acme/flaky")) == 3


_JSON = {"Content-Type": "application/json"}


@pytest.mark.parametrize(
    ("reply", "reason", "cached"),
    [
        ((404, {}, b"{}"), CheckFailure.NOT_FOUND, False),
        ((401, {}, b"{}"), CheckFailure.ACCESS_DENIED, False),
        (
            (200, {"Content-Type": "text/html"}, b"<html>"),
            CheckFailure.INVALID_RESPONSE,
            False,
        ),
        ((200, _JSON, b"{oops"), CheckFailure.INVALID_RESPONSE, False),
        ((200, _JSON, b'{"results": []}'), CheckFailure.NO_TAGS, False),
        # The lookup worked, but the local tag is not among the listed tags.
        (_tags_reply("2.0.0", "latest"), CheckFailure.TAG_NOT_FOUND, True),
    ],
)
def test_failures_are_reported_per_image(
    hub: FakeDockerHub, reply: _Reply, reason: CheckFailure, cached: bool
) -> None:
    hub.replies["acme/app"] = [reply]
    updater = DockerImageUpdater()
    updater.local_images = _local("acme/app")

    result = _results(_run(updater))["acme/app:1.0.0"]

    assert result["error"] == reason.value
    assert len(hub.requests_for("acme/app")) == 1
    assert ("docker.io/acme/app" in updater._cache.entries) is cached


def test_timeouts_are_retried_once(hub: FakeDockerHub) -> None:
    hub.delay = 5.0
    updater = DockerImageUpdater(timeout=1)
    updater.local_images = _local("acme/slow")

    started = time.monotonic()
    result = _results(_run(updater))["acme/slow:1.0.0"]

    assert result["error"] == CheckFailure.TIMEOUT.value
    assert len(hub.requests_for("acme/slow")) == 2
    assert time.monotonic() - started < 4


def test_deadline_cancels_outstanding_lookups(hub: FakeDockerHub) -> None:
    hub.delay = 30.0
    updater = DockerImageUpdater()
    updater.local_images = _local(*(f"acme/app{index}" for index in range(8)))

    started = time.monotonic()
    response = _run(updater, deadline=0.5)

    assert time.monotonic() - started < 3
    assert response.metadata["deadline_exceeded"] is True
    results = _results(response)
    assert len(results) == 8
    assert {result["error"] for result in results.values()} == {"timeout"}


def test_sync_bridge_gives_up_after_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = DockerImageUpdater()
    monkeypatch.setattr(updates_module, "BRIDGE_GRACE_SECONDS", 0.2)

    async def _stuck(_deadline: float) -> UpdaterResponse:
        await asyncio.sleep(30)
        raise AssertionError("not cancelled")

    monkeypatch.setattr(updater, "_check_updates", _stuck)
    started = time.monotonic()
    response = updater._run_check_safely(0.1)
    loop = updater._sync_bridge.loop
    assert loop is not None
    # Let the bridge loop finish cancelling the abandoned check.
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0.05), loop).result(timeout=1)
    updater._stop_sync_bridge()

    assert time.monotonic() - started < 2
    assert response.status == UpdaterStatus.ERROR
    assert response.metadata["deadline_exceeded"] is True


def test_check_updates_reports_docker_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = DockerImageUpdater()

    def _docker_down() -> dict[str, list[dict[str, str | None]]]:
        raise RuntimeError("docker socket unavailable")

    monkeypatch.setattr(updater, "_get_local_images", _docker_down)
    assert updater.check_updates().status == UpdaterStatus.DOCKER_ERROR


def test_check_updates_refreshes_local_images_then_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = DockerImageUpdater()
    seen: list[float] = []
    expected = UpdaterResponse(status=UpdaterStatus.SUCCESS, message="ok")

    def _check(deadline: float) -> UpdaterResponse:
        seen.append(deadline)
        return expected

    monkeypatch.setattr(updater, "_get_local_images", lambda: _local("acme/app"))
    monkeypatch.setattr(updater, "_run_check_updates_sync", _check)

    assert updater.check_updates(deadline=20.0) is expected
    assert list(updater.local_images) == ["acme/app"]
    assert 19.0 < seen[0] <= 20.0


def test_shared_updater_is_reused() -> None:
    assert updates_module.get_image_updater() is updates_module.get_image_updater()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("120", 120),
        (" 7 ", 7),
        ("Wed, 21 Oct 2026 07:28:00 GMT", 600),
        ("Wed, 21 Oct 2026 07:00:00 GMT", 0),  # already passed
        ("soon", None),
        ("-5", None),
        ("99999999999", None),
        ("１２０", None),  # non-ASCII digits
    ],
)
def test_parse_retry_after(value: str | None, expected: int | None) -> None:
    now = datetime(2026, 10, 21, 7, 18, tzinfo=UTC)
    assert parse_retry_after(value, now=now) == expected


def test_retry_after_defaults_to_backoff_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock: list[float] = [1000.0]

    def _now() -> float:
        return clock[0]

    monkeypatch.setattr("pytmbot.adapters.docker.updates.time.time", _now)
    limiter = updates_module.RateLimitHandler()

    limiter.handle_rate_limit(None)
    assert limiter.retry_after() == updates_module.RATE_LIMIT_BACKOFF
    limiter.handle_rate_limit(10**9)
    assert limiter.retry_after() == updates_module.MAX_RATE_LIMIT_BACKOFF
    clock[0] += updates_module.MAX_RATE_LIMIT_BACKOFF
    assert limiter.retry_after() is None
