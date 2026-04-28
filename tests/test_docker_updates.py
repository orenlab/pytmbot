from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Coroutine, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace, TracebackType
from typing import Never, cast

import pytest
from aiohttp import ClientError, ClientResponseError, ClientSession
from aiohttp.client_reqrep import RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy
from packaging import version
from packaging.version import InvalidVersion
from yarl import URL

import pytmbot.adapters.docker.updates as updates_module
from pytmbot.adapters.docker.updates import (
    MAX_TAGS_PER_REPO,
    DockerImageUpdater,
    EnhancedTagInfo,
    TagAnalyzer,
    TagType,
    UpdaterResponse,
    UpdaterStatus,
    dict_to_tag_info,
    normalize_created_at,
)
from pytmbot.models.docker_models import TagInfo

type _DockerHubResult = dict[str, str | None]
type _DockerHubResults = list[_DockerHubResult]
type _DockerHubPayload = dict[str, _DockerHubResults]
type _DockerHubMixedPayload = dict[str, list[str | _DockerHubResult]]
type _DockerHubAnyPayload = dict[str, _DockerHubResults | list[str | _DockerHubResult]]


def test_enhanced_tag_info_comparison_edges() -> None:
    base = EnhancedTagInfo(
        tag_info=TagInfo(name="v1.0.0", created_at="2026-01-01T00:00:00Z", digest=None),
        tag_type=TagType.SEMVER,
        version_info=version.parse("1.0.0"),
    )
    newer = EnhancedTagInfo(
        tag_info=TagInfo(name="v1.1.0", created_at="2026-01-02T00:00:00Z", digest=None),
        tag_type=TagType.SEMVER,
        version_info=version.parse("1.1.0"),
    )
    assert base < newer
    assert (base.__lt__(cast(EnhancedTagInfo, 0))) is NotImplemented

    left_date = EnhancedTagInfo(
        tag_info=TagInfo(
            name="2026-01-01", created_at="2026-01-01T00:00:00Z", digest=None
        ),
        tag_type=TagType.DATE,
        date_info=datetime(2026, 1, 1, tzinfo=UTC),
    )
    right_date = EnhancedTagInfo(
        tag_info=TagInfo(
            name="2026-01-02", created_at="2026-01-02T00:00:00Z", digest=None
        ),
        tag_type=TagType.DATE,
        date_info=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert left_date < right_date

    broken_left = EnhancedTagInfo(
        tag_info=TagInfo(name="alpha", created_at="bad-date", digest=None),
        tag_type=TagType.CUSTOM,
    )
    broken_right = EnhancedTagInfo(
        tag_info=TagInfo(name="beta", created_at="also-bad", digest=None),
        tag_type=TagType.CUSTOM,
    )
    assert broken_left < broken_right


def test_tag_analyzer_extended_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    analyzer = TagAnalyzer()
    assert (
        analyzer.analyze_tag(
            TagInfo(name="abcdef0", created_at="", digest=None)
        ).tag_type
        == TagType.SHA
    )
    assert (
        analyzer.analyze_tag(
            TagInfo(name="release-1.2.3", created_at="", digest=None)
        ).tag_type
        == TagType.SEMVER
    )
    assert analyzer.analyze_tag(
        TagInfo(name="2026-13-01", created_at="", digest=None)
    ).parse_error
    assert analyzer.analyze_tag(
        TagInfo(name="2026-12-01-25-00-00", created_at="", digest=None)
    ).parse_error
    assert (
        analyzer.analyze_tag(TagInfo(name="  ", created_at="", digest=None)).tag_type
        == TagType.INVALID
    )

    with monkeypatch.context() as local_patch:
        local_patch.setattr(
            "pytmbot.adapters.docker.updates.version.parse",
            lambda _v: (_ for _ in ()).throw(InvalidVersion("bad")),
        )
        semver_custom = analyzer.analyze_tag(
            TagInfo(name="v1.2.3", created_at="2026-01-01T00:00:00Z", digest=None)
        )
        numeric_custom = analyzer.analyze_tag(
            TagInfo(name="1.2.3", created_at="2026-01-01T00:00:00Z", digest=None)
        )
        assert semver_custom.tag_type == TagType.CUSTOM
        assert numeric_custom.tag_type == TagType.CUSTOM

    with monkeypatch.context() as local_patch:
        local_patch.setattr(
            TagAnalyzer,
            "SEMVER_PATTERN",
            SimpleNamespace(
                match=lambda _value: (_ for _ in ()).throw(RuntimeError("boom"))
            ),
        )
        invalid = analyzer.analyze_tag(
            TagInfo(name="v1.0.0", created_at="2026-01-01T00:00:00Z", digest=None)
        )
        assert invalid.tag_type == TagType.INVALID


def test_normalize_and_dict_conversion_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    assert normalize_created_at(5_000_000_000) is None
    assert normalize_created_at("2026-01-01T00:00:00Z") is not None
    assert normalize_created_at("unparseable") == "unparseable"
    assert normalize_created_at("   ") is None

    with pytest.raises(ValueError, match="dictionary"):
        dict_to_tag_info(cast(dict[str, str], "not-dict"))
    with pytest.raises(ValueError, match="Missing required field"):
        dict_to_tag_info({"tag": "latest", "created_at": "2026"})


def test_rate_limiter_and_cache_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytmbot.adapters.docker.updates as updates_module

    limiter = updates_module.RateLimitHandler()
    clock = [1000.0]
    monkeypatch.setattr("pytmbot.adapters.docker.updates.time.time", lambda: clock[0])
    limiter.handle_rate_limit()
    assert limiter.should_skip_request() is True
    limiter.handle_success()
    clock[0] = updates_module.RATE_LIMIT_BACKOFF + 1001
    assert limiter.should_skip_request() is False

    limiter._consecutive_limits = 6  # noqa: SLF001
    limiter._last_rate_limit = 1000.0  # noqa: SLF001
    clock[0] = 1200.0
    assert limiter.should_skip_request() is True

    updater = DockerImageUpdater()
    now = 2000.0
    tags = [
        updater.analyzer.analyze_tag(
            TagInfo(name="latest", created_at="2026-01-01T00:00:00Z", digest=None)
        )
    ]
    updater._cache.set("repo/app", tags, now)
    assert updater._cache.get_valid("repo/app", now + 1) == tags
    assert (
        updater._cache.get_valid("repo/app", now + updates_module.CACHE_TTL + 1) is None
    )


def test_updater_initialize_local_images_and_digest_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = DockerImageUpdater()

    with monkeypatch.context() as local_patch:
        local_patch.setattr(
            updater,
            "_get_local_images",
            lambda: (_ for _ in ()).throw(RuntimeError("init fail")),
        )
        with pytest.raises(RuntimeError, match="init fail"):
            updater.initialize()

    image_valid = SimpleNamespace(
        tags=["repo/app:1.0"],
        attrs={
            "Created": "2026-01-01T00:00:00Z",
            "RepoDigests": ["repo/app@sha256:" + "a" * 64],
        },
    )
    image_no_tags = SimpleNamespace(tags=[], attrs={})
    image_bad = SimpleNamespace(tags=["bad"], attrs={"Created": "bad"})

    @contextmanager
    def _client_context() -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(
            images=SimpleNamespace(
                list=lambda all=False: [image_valid, image_no_tags, image_bad]
            )
        )  # noqa: FBT002

    monkeypatch.setattr(updates_module, "docker_client_context", _client_context)
    original_process_image_tags = updates_module._process_local_image_tags
    monkeypatch.setattr(
        updates_module,
        "_process_local_image_tags",
        lambda image, digest, local, *, log, parse_tag: (
            (_ for _ in ()).throw(RuntimeError("tag fail"))
            if image is image_bad
            else original_process_image_tags(
                image, digest, local, log=log, parse_tag=parse_tag
            )
        ),
    )
    parsed = updater._get_local_images()
    assert "repo/app" in parsed

    assert (
        updates_module._extract_image_digest(
            SimpleNamespace(attrs={"RepoDigests": ["bad-format"]}),
            log=updater._log,
        )
        is None
    )
    bad_digest_image = SimpleNamespace(attrs=cast(dict[str, str], None))
    assert (
        updates_module._extract_image_digest(bad_digest_image, log=updater._log) is None
    )


def test_process_tags_parse_and_bridge_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    updater = DockerImageUpdater()
    local: dict[str, list[dict[str, str | None]]] = {}
    image = SimpleNamespace(
        tags=["repo/app:1.0", " ", cast(str, None), "too/" + "x" * 300 + ":1.0"],
        attrs={"Created": "2026-01-01T00:00:00Z"},
    )
    updates_module._process_local_image_tags(
        image,
        "sha256:" + "a" * 64,
        local,
        log=updater._log,
        parse_tag=updates_module._parse_image_tag,
    )
    assert "repo/app" in local

    with pytest.raises(ValueError):
        updates_module._parse_image_tag("repo/:")
    assert updates_module._parse_image_tag("docker.io/library/nginx:1.2") == (
        "library/nginx",
        "1.2",
    )

    # _ensure_sync_bridge early-return path.
    async def _run_ensure_sync_bridge_early_return() -> None:
        updater._sync_bridge.thread = threading.current_thread()
        updater._sync_bridge.loop = asyncio.get_running_loop()
        updater._ensure_sync_bridge()

    asyncio.run(_run_ensure_sync_bridge_early_return())

    # _ensure_sync_bridge start failure path.
    updater._sync_bridge.thread = None
    updater._sync_bridge.loop = None
    monkeypatch.setattr(
        updates_module, "Thread", lambda *a, **k: SimpleNamespace(start=lambda: None)
    )
    monkeypatch.setattr(updater._sync_bridge.ready, "wait", lambda timeout: False)
    with pytest.raises(RuntimeError, match="failed to start"):
        updater._ensure_sync_bridge()


def test_sync_bridge_stop_and_sync_runner_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = DockerImageUpdater()

    stop_called = {"value": False}

    def _call_soon_threadsafe(callback: Callable[[], None]) -> None:
        stop_called["value"] = True
        callback()

    loop = asyncio.new_event_loop()
    monkeypatch.setattr(loop, "is_running", lambda: True)
    monkeypatch.setattr(loop, "call_soon_threadsafe", _call_soon_threadsafe)
    monkeypatch.setattr(loop, "stop", lambda: None)
    join_called = {"value": False}
    thread = threading.Thread(name="docker-updater-test-bridge")
    monkeypatch.setattr(thread, "is_alive", lambda: True)
    monkeypatch.setattr(
        thread,
        "join",
        lambda timeout: join_called.__setitem__("value", timeout is not None),
    )
    updater._sync_bridge.loop = loop
    updater._sync_bridge.thread = thread
    updater._stop_sync_bridge()
    assert join_called["value"] is True

    updater._ensure_sync_bridge = lambda: None  # type: ignore[method-assign]
    updater._sync_bridge.loop = None
    with pytest.raises(RuntimeError, match="unavailable"):
        updater._run_check_updates_sync()

    updater._sync_bridge.loop = asyncio.new_event_loop()

    def _fake_run_coroutine_threadsafe(
        coro: Coroutine[None, None, UpdaterResponse],
        _loop: asyncio.AbstractEventLoop,
    ) -> SimpleNamespace:
        coro.close()
        return SimpleNamespace(
            result=lambda: UpdaterResponse(status=UpdaterStatus.SUCCESS, message="ok")
        )

    monkeypatch.setattr(
        "pytmbot.adapters.docker.updates.asyncio.run_coroutine_threadsafe",
        _fake_run_coroutine_threadsafe,
    )
    assert updater._run_check_updates_sync().status == UpdaterStatus.SUCCESS
    if updater._sync_bridge.loop is not None:
        updater._sync_bridge.loop.close()


def test_normalize_created_at_supports_timestamp_and_iso() -> None:
    iso = normalize_created_at(1700000000)
    assert isinstance(iso, str)
    assert normalize_created_at("2026-02-17T12:00:00Z") is not None
    assert normalize_created_at("bad date") == "bad date"
    assert normalize_created_at(None) is None


def test_dict_to_tag_info_validation() -> None:
    info = dict_to_tag_info(
        {"tag": "latest", "created_at": "2026-01-01T00:00:00Z", "digest": "sha256:1"}
    )
    assert info.name == "latest"
    with pytest.raises(ValueError):
        dict_to_tag_info(cast(dict[str, str], {"tag": "latest"}))


def test_tag_analyzer_classifies_core_formats() -> None:
    analyzer = TagAnalyzer()
    assert (
        analyzer.analyze_tag(
            TagInfo(name="latest", created_at="2026-01-01T00:00:00Z", digest=None)
        ).tag_type
        == TagType.LATEST
    )
    assert (
        analyzer.analyze_tag(
            TagInfo(name="v1.2.3", created_at="2026-01-01T00:00:00Z", digest=None)
        ).tag_type
        == TagType.SEMVER
    )
    assert (
        analyzer.analyze_tag(
            TagInfo(name="2026-02-17", created_at="2026-02-17T00:00:00Z", digest=None)
        ).tag_type
        == TagType.DATE
    )
    assert (
        analyzer.analyze_tag(TagInfo(name="", created_at="", digest=None)).tag_type
        == TagType.INVALID
    )


def test_build_repository_urls_handles_namespaced_and_library() -> None:
    assert updates_module._build_repository_urls("orenlab/pytmbot") == [
        "https://registry.hub.docker.com/v2/repositories/orenlab/pytmbot/tags/"
    ]
    assert updates_module._build_repository_urls("nginx") == [
        "https://registry.hub.docker.com/v2/repositories/nginx/tags/",
        "https://registry.hub.docker.com/v2/repositories/library/nginx/tags/",
    ]


def test_parse_tag_handles_registry_prefix_and_default_latest() -> None:
    assert updates_module._parse_image_tag("docker.io/library/nginx:1.27") == (
        "library/nginx",
        "1.27",
    )
    assert updates_module._parse_image_tag("redis") == ("redis", "latest")
    with pytest.raises(ValueError):
        updates_module._parse_image_tag("")


def test_compare_versions_and_digest_equality() -> None:
    analyzer = TagAnalyzer()
    local = analyzer.analyze_tag(
        TagInfo(
            name="v1.2.0",
            created_at=datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            digest="sha256:a",
        )
    )
    remote = analyzer.analyze_tag(
        TagInfo(
            name="v1.3.0",
            created_at=datetime(2026, 2, 1, tzinfo=UTC).isoformat(),
            digest="sha256:b",
        )
    )
    assert updates_module._compare_enhanced_tags(local, remote) is True
    assert updates_module._tag_digests_equal(local, remote) is False

    remote_same_digest = analyzer.analyze_tag(
        TagInfo(
            name="v1.3.0",
            created_at=datetime(2026, 2, 1, tzinfo=UTC).isoformat(),
            digest="sha256:a",
        )
    )
    assert updates_module._tag_digests_equal(local, remote_same_digest) is True


def test_find_compatible_updates_respects_digest_and_semver_major() -> None:
    updater = DockerImageUpdater()
    analyzer = TagAnalyzer()

    local = analyzer.analyze_tag(
        TagInfo(
            name="v1.2.0",
            created_at=datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            digest="sha256:old",
        )
    )
    remote_tags = [
        analyzer.analyze_tag(
            TagInfo(
                name="v1.2.0",
                created_at=datetime(2026, 2, 1, tzinfo=UTC).isoformat(),
                digest="sha256:new",
            )
        ),
        analyzer.analyze_tag(
            TagInfo(
                name="v1.3.0",
                created_at=datetime(2026, 2, 2, tzinfo=UTC).isoformat(),
                digest="sha256:x",
            )
        ),
        analyzer.analyze_tag(
            TagInfo(
                name="v2.0.0",
                created_at=datetime(2026, 2, 3, tzinfo=UTC).isoformat(),
                digest="sha256:y",
            )
        ),
    ]
    updates = updates_module._find_compatible_tag_updates(
        local,
        remote_tags,
        log=updater._log,
        compare_versions=updates_module._compare_enhanced_tags,
        digests_equal=updates_module._tag_digests_equal,
    )
    newer_tags = {update.newer_tag for update in updates}
    assert "v1.3.0" in newer_tags
    assert "v2.0.0" not in newer_tags


def test_updater_to_json_and_cache_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    updater = DockerImageUpdater()

    async def _failing_check_updates() -> UpdaterResponse:
        raise RuntimeError("failed")

    monkeypatch.setattr(
        updater,
        "_check_updates",
        _failing_check_updates,
    )
    payload = updater.to_dict()
    assert payload["status"] == "ERROR"
    message = payload.get("message")
    assert isinstance(message, str)
    assert "failed" in message
    assert "performance" in updater.get_stats()
    updater.clear_cache()
    cache_stats = updater.get_stats().get("cache")
    assert isinstance(cache_stats, dict)
    assert cache_stats.get("size") == 0


def _make_client_response_error(status: int, message: str) -> ClientResponseError:
    request_info = RequestInfo(
        url=URL("https://registry.hub.docker.com/v2/repositories/test/tags/"),
        method="GET",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url=URL("https://registry.hub.docker.com/v2/repositories/test/tags/"),
    )
    return ClientResponseError(
        request_info=request_info,
        history=(),
        status=status,
        message=message,
        headers=CIMultiDictProxy(CIMultiDict()),
    )


def test_fetch_tags_from_url_parses_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    updater = DockerImageUpdater()

    class _FakeResponse:
        def __init__(self, payload: Mapping[str, _DockerHubResults]) -> None:
            self._payload = dict(payload)

        async def __aenter__(self) -> _FakeResponse:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def json(self) -> _DockerHubPayload:
            return self._payload

    results: _DockerHubResults = [
        {
            "name": "v1.2.0",
            "tag_last_pushed": "2026-02-01T00:00:00Z",
            "digest": "sha256:a",
        },
        {
            "name": "latest",
            "tag_last_pushed": "2026-02-02T00:00:00Z",
            "digest": "sha256:b",
        },
        {"name": "", "tag_last_pushed": "bad", "digest": None},
    ]
    payload: _DockerHubPayload = {"results": results}
    calls = {"count": 0}

    def _fake_get(self: ClientSession, _url: str, timeout: float) -> _FakeResponse:
        del self
        assert timeout is not None
        calls["count"] += 1
        return _FakeResponse(payload)

    monkeypatch.setattr(
        "pytmbot.adapters.docker.updates.ClientSession.get",
        _fake_get,
    )

    async def _run_fetch() -> list[EnhancedTagInfo] | None:
        async with ClientSession() as session:
            return await updater._fetch_tags_from_url(
                session,
                "https://registry.hub.docker.com/v2/repositories/repo/app/tags/",
                "repo/app",
            )

    parsed = asyncio.run(_run_fetch())

    assert calls["count"] == 1
    assert parsed is not None
    assert len(parsed) == 2
    assert {item.name for item in parsed} == {"v1.2.0", "latest"}


def test_fetch_tags_from_url_limits_large_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = DockerImageUpdater()

    class _FakeResponse:
        def __init__(self, payload: _DockerHubPayload) -> None:
            self._payload = payload

        async def __aenter__(self) -> _FakeResponse:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def json(self) -> _DockerHubPayload:
            return self._payload

    results: _DockerHubResults = [
        {
            "name": f"v1.0.{idx}",
            "tag_last_pushed": "2026-02-01T00:00:00Z",
            "digest": f"sha256:{idx:064x}",
        }
        for idx in range(MAX_TAGS_PER_REPO + 5)
    ]

    def _fake_get_success(
        self: ClientSession, _url: str, timeout: float
    ) -> _FakeResponse:
        del self
        assert timeout is not None
        return _FakeResponse({"results": results})

    monkeypatch.setattr(
        "pytmbot.adapters.docker.updates.ClientSession.get",
        _fake_get_success,
    )

    async def _run_fetch() -> list[EnhancedTagInfo] | None:
        async with ClientSession() as session:
            return await updater._fetch_tags_from_url(
                session,
                "https://registry.hub.docker.com/v2/repositories/repo/app/tags/",
                "repo/app",
            )

    parsed = asyncio.run(_run_fetch())
    assert parsed is not None
    assert len(parsed) == MAX_TAGS_PER_REPO

    async def _always_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("pytmbot.adapters.docker.updates.asyncio.sleep", _always_sleep)

    class _FailingResponse:
        async def __aenter__(self) -> _FailingResponse:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

        def raise_for_status(self) -> None:
            raise _make_client_response_error(500, "server error")

        async def json(self) -> dict[str, str]:
            return {}

    def _fake_get_failing(
        self: ClientSession, _url: str, timeout: float
    ) -> _FailingResponse:
        del self
        assert timeout is not None
        return _FailingResponse()

    monkeypatch.setattr(
        "pytmbot.adapters.docker.updates.ClientSession.get",
        _fake_get_failing,
    )

    async def _run_failing() -> list[EnhancedTagInfo] | None:
        async with ClientSession() as session:
            return await updater._fetch_tags_from_url(
                session,
                "https://registry.hub.docker.com/v2/repositories/repo/app/tags/",
                "repo/app",
            )

    with pytest.raises(ClientResponseError):
        asyncio.run(_run_failing())


def test_fetch_remote_tags_cache_and_404(monkeypatch: pytest.MonkeyPatch) -> None:
    updater = DockerImageUpdater()
    analyzed = updater.analyzer.analyze_tag(
        TagInfo(name="latest", created_at="2026-02-01T00:00:00Z", digest="sha256:a")
    )
    updater._cache.entries["repo/app"] = ([analyzed], time.time())

    async def _run_from_cache() -> list[EnhancedTagInfo]:
        async with ClientSession() as session:
            return await updater._fetch_remote_tags(session, "repo/app")

    from_cache = asyncio.run(_run_from_cache())
    assert len(from_cache) == 1
    assert updater._stats["cache_hits"] == 1

    updater._cache.entries.clear()

    async def _always_404(
        _session: ClientSession, _url: str, _repo: str
    ) -> list[EnhancedTagInfo] | None:
        raise _make_client_response_error(404, "not found")

    monkeypatch.setattr(updater, "_fetch_tags_from_url", _always_404)

    async def _run_missing() -> list[EnhancedTagInfo]:
        async with ClientSession() as session:
            return await updater._fetch_remote_tags(session, "missing")

    missing = asyncio.run(_run_missing())
    assert missing == []
    assert "missing" in updater._cache.entries
    assert updater._cache.entries["missing"][0] == []


def test_check_updates_status_transitions(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytmbot.adapters.docker.updates as updates_module

    class _NoopClientSession:
        def __init__(self, **_kwargs: str | float | bool | int) -> None:
            return

        async def __aenter__(self) -> _NoopClientSession:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    monkeypatch.setattr(
        "pytmbot.adapters.docker.updates.aiohttp.TCPConnector",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(updates_module, "ClientSession", _NoopClientSession)

    updater = DockerImageUpdater()
    local_tag: dict[str, str | None] = {
        "tag": "v1.0.0",
        "created_at": "2026-01-01T00:00:00Z",
        "digest": "sha256:old",
    }
    updater.local_images = {"repo/ok": [local_tag]}

    remote_tag = updater.analyzer.analyze_tag(
        TagInfo(name="v1.1.0", created_at="2026-02-01T00:00:00Z", digest="sha256:new")
    )

    async def _fetch_success(
        _session: ClientSession, _repo: str
    ) -> list[EnhancedTagInfo]:
        return [remote_tag]

    monkeypatch.setattr(updater, "_fetch_remote_tags", _fetch_success)
    success = asyncio.run(updater._check_updates())
    assert success.status == UpdaterStatus.SUCCESS
    assert success.repositories_processed == 1
    assert success.repositories_failed == 0
    assert isinstance(success.data, dict)
    assert success.data["repo/ok"]["updates"]

    updater.local_images = {"repo/rate": [local_tag]}

    async def _fetch_rate_limited(
        _session: ClientSession, _repo: str
    ) -> list[EnhancedTagInfo]:
        raise _make_client_response_error(429, "rate limited")

    monkeypatch.setattr(updater, "_fetch_remote_tags", _fetch_rate_limited)
    rate_limited = asyncio.run(updater._check_updates())
    assert rate_limited.status == UpdaterStatus.RATE_LIMITED
    assert rate_limited.repositories_failed == 1

    updater.local_images = {"repo/ok": [local_tag], "repo/fail": [local_tag]}

    async def _fetch_mixed(_session: ClientSession, repo: str) -> list[EnhancedTagInfo]:
        if repo == "repo/ok":
            return [remote_tag]
        raise RuntimeError("boom")

    monkeypatch.setattr(updater, "_fetch_remote_tags", _fetch_mixed)
    partial = asyncio.run(updater._check_updates())
    assert partial.status == UpdaterStatus.PARTIAL_SUCCESS
    assert partial.repositories_processed == 1
    assert partial.repositories_failed == 1


def test_tag_analyzer_normalize_and_parse_extra_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.updates as updates_module

    analyzer = TagAnalyzer()
    # Date with time branch.
    with_time = analyzer.analyze_tag(
        TagInfo(name="20260217-120101", created_at="2026-02-17T12:01:01Z", digest=None)
    )
    assert with_time.tag_type == TagType.DATE

    # Numeric pattern branch (semver regex does not match x.y).
    numeric = analyzer.analyze_tag(TagInfo(name="1.2", created_at="", digest=None))
    assert numeric.tag_type == TagType.SEMVER

    # Default custom path.
    custom = analyzer.analyze_tag(
        TagInfo(name="feature-branch", created_at="", digest=None)
    )
    assert custom.tag_type == TagType.CUSTOM

    # normalize_created_at non-datetime parsed result + outer exception branch.
    with monkeypatch.context() as local_patch:
        local_patch.setattr(
            updates_module,
            "isoparse",
            lambda _value: "normalized-string",
        )
        assert normalize_created_at("2026-02-17T00:00:00Z") == "normalized-string"

    with monkeypatch.context() as local_patch:
        local_patch.setattr(
            updates_module,
            "isoparse",
            lambda _value: (_ for _ in ()).throw(RuntimeError("parse crash")),
        )
        assert normalize_created_at("2026-02-17T00:00:00Z") is None


def test_updater_init_get_local_images_and_process_tags_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.updates as updates_module

    # Invalid timeout path falls back to default.
    updater = DockerImageUpdater(timeout=-1)
    assert updater._timeout == updates_module.DEFAULT_TIMEOUT

    # initialize success path.
    with monkeypatch.context() as local_patch:
        local_patch.setattr(
            updater,
            "_get_local_images",
            lambda: {"repo/app": [{"tag": "1.0", "created_at": "", "digest": None}]},
        )
        updater.initialize()
        assert "repo/app" in updater.local_images

    # _get_local_images outer failure path.
    class _FailingContext:
        def __enter__(self) -> Never:
            raise RuntimeError("docker client down")

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    monkeypatch.setattr(
        updates_module, "docker_client_context", lambda: _FailingContext()
    )
    with pytest.raises(RuntimeError, match="docker client down"):
        updater._get_local_images()

    # _process_image_tags warning branches.
    image = SimpleNamespace(
        tags=["repo/app:1.0", "repo/app:2.0"], attrs={"Created": "bad"}
    )
    local: dict[str, list[dict[str, str | None]]] = {}
    with monkeypatch.context() as local_patch:
        call = {"n": 0}

        def _parse_tag(_tag: str) -> tuple[str, str]:
            call["n"] += 1
            if call["n"] == 1:
                raise ValueError("bad tag")
            raise RuntimeError("unexpected parse fail")

        updates_module._process_local_image_tags(
            image,
            None,
            local,
            log=updater._log,
            parse_tag=_parse_tag,
        )
    assert local == {}


def test_fetch_remote_and_fetch_tags_extra_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = DockerImageUpdater()

    async def _run_repo(repo: str) -> list[EnhancedTagInfo]:
        async with ClientSession() as session:
            return await updater._fetch_remote_tags(session, repo)

    monkeypatch.setattr(updater.rate_limiter, "should_skip_request", lambda: True)
    assert asyncio.run(_run_repo("repo/app")) == []

    # Successful non-empty fetch path.
    analyzed = updater.analyzer.analyze_tag(
        TagInfo(name="latest", created_at="2026-02-01T00:00:00Z", digest="sha256:a")
    )

    async def _fetch_success(
        _session: ClientSession, _url: str, _repo: str
    ) -> list[EnhancedTagInfo] | None:
        return [analyzed]

    monkeypatch.setattr(updater.rate_limiter, "should_skip_request", lambda: False)
    monkeypatch.setattr(updater, "_fetch_tags_from_url", _fetch_success)

    successful = asyncio.run(_run_repo("repo/app"))
    assert len(successful) == 1

    # 429 path and generic warning branch.
    async def _fetch_rate_limit(
        _session: ClientSession, _url: str, _repo: str
    ) -> list[EnhancedTagInfo] | None:
        raise _make_client_response_error(429, "rate limited")

    updater._cache.entries.clear()
    monkeypatch.setattr(updater, "_fetch_tags_from_url", _fetch_rate_limit)
    with pytest.raises(ClientResponseError):
        asyncio.run(_run_repo("repo/rate"))

    errors = iter(
        [
            _make_client_response_error(500, "server"),
            RuntimeError("generic fetch fail"),
        ]
    )

    async def _fetch_errors(
        _session: ClientSession, _url: str, _repo: str
    ) -> list[EnhancedTagInfo] | None:
        error = next(errors)
        raise error

    monkeypatch.setattr(updater, "_fetch_tags_from_url", _fetch_errors)
    assert asyncio.run(_run_repo("repo/errors")) == []


def test_fetch_tags_retry_and_entry_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    updater = DockerImageUpdater()

    class _Response:
        def __init__(
            self,
            payload: Mapping[str, _DockerHubResults | list[str | _DockerHubResult]],
        ) -> None:
            self._payload = dict(payload)

        async def __aenter__(self) -> _Response:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def json(self) -> _DockerHubAnyPayload:
            return self._payload

    def _get_empty(self: ClientSession, _url: str, timeout: float) -> _Response:
        del self, timeout
        return _Response({"results": []})

    monkeypatch.setattr("pytmbot.adapters.docker.updates.ClientSession.get", _get_empty)

    async def _run_empty() -> list[EnhancedTagInfo] | None:
        async with ClientSession() as session:
            return await updater._fetch_tags_from_url(
                session,
                "https://registry.hub.docker.com/v2/repositories/repo/app/tags/",
                "repo/app",
            )

    assert asyncio.run(_run_empty()) == []

    payload: _DockerHubMixedPayload = {
        "results": [
            "not-a-dict",
            {
                "name": "latest",
                "tag_last_pushed": "2026-02-01T00:00:00Z",
                "digest": "sha256:a",
            },
        ]
    }

    def _get_payload(self: ClientSession, _url: str, timeout: float) -> _Response:
        del self, timeout
        return _Response(payload)

    monkeypatch.setattr(
        "pytmbot.adapters.docker.updates.ClientSession.get", _get_payload
    )
    with monkeypatch.context() as local_patch:
        local_patch.setattr(
            updater.analyzer,
            "analyze_tag",
            lambda _tag: (_ for _ in ()).throw(RuntimeError("entry boom")),
        )
        assert asyncio.run(_run_empty()) == []

    class _ErrorResponse:
        async def __aenter__(self) -> _ErrorResponse:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

        def raise_for_status(self) -> None:
            raise _make_client_response_error(403, "forbidden")

        async def json(self) -> dict[str, str]:
            return {}

    monkeypatch.setattr(
        "pytmbot.adapters.docker.updates.ClientSession.get",
        lambda self, _url, timeout: _ErrorResponse(),
    )
    with pytest.raises(ClientResponseError):
        asyncio.run(_run_empty())

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("pytmbot.adapters.docker.updates.asyncio.sleep", _no_sleep)
    monkeypatch.setattr(
        "pytmbot.adapters.docker.updates.ClientSession.get",
        lambda self, _url, timeout: (_ for _ in ()).throw(TimeoutError()),
    )
    with pytest.raises(TimeoutError):
        asyncio.run(_run_empty())

    monkeypatch.setattr(
        "pytmbot.adapters.docker.updates.ClientSession.get",
        lambda self, _url, timeout: (_ for _ in ()).throw(ClientError("network")),
    )
    with pytest.raises(ClientError):
        asyncio.run(_run_empty())

    monkeypatch.setattr(
        "pytmbot.adapters.docker.updates.ClientSession.get",
        lambda self, _url, timeout: (_ for _ in ()).throw(RuntimeError("unknown")),
    )
    with pytest.raises(RuntimeError):
        asyncio.run(_run_empty())


def test_compare_find_and_check_updates_edge_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = DockerImageUpdater()

    local_custom = updater.analyzer.analyze_tag(
        TagInfo(name="custom", created_at="bad-local", digest=None)
    )
    remote_custom = updater.analyzer.analyze_tag(
        TagInfo(name="custom2", created_at="bad-remote", digest=None)
    )
    assert updates_module._compare_enhanced_tags(local_custom, remote_custom) is False
    assert updates_module._tag_digests_equal(local_custom, remote_custom) is False

    invalid_local = EnhancedTagInfo(
        tag_info=TagInfo(name="x", created_at="", digest=None),
        tag_type=TagType.INVALID,
        parse_error="bad",
    )
    assert (
        updates_module._find_compatible_tag_updates(
            invalid_local,
            [remote_custom],
            log=updater._log,
            compare_versions=updates_module._compare_enhanced_tags,
            digests_equal=updates_module._tag_digests_equal,
        )
        == []
    )

    same_name_local = updater.analyzer.analyze_tag(
        TagInfo(name="latest", created_at="2026-01-01T00:00:00Z", digest="sha256:a")
    )
    same_name_remote = updater.analyzer.analyze_tag(
        TagInfo(name="latest", created_at="2026-02-01T00:00:00Z", digest="sha256:a")
    )
    assert (
        updates_module._find_compatible_tag_updates(
            same_name_local,
            [same_name_remote],
            log=updater._log,
            compare_versions=updates_module._compare_enhanced_tags,
            digests_equal=updates_module._tag_digests_equal,
        )
        == []
    )

    date_local = updater.analyzer.analyze_tag(
        TagInfo(name="2026-02-01", created_at="2026-02-01T00:00:00Z", digest="sha256:a")
    )
    date_remote = updater.analyzer.analyze_tag(
        TagInfo(name="2026-02-02", created_at="2026-02-02T00:00:00Z", digest="sha256:b")
    )
    assert updates_module._find_compatible_tag_updates(
        date_local,
        [date_remote],
        log=updater._log,
        compare_versions=updates_module._compare_enhanced_tags,
        digests_equal=updates_module._tag_digests_equal,
    )

    with monkeypatch.context() as local_patch:
        local_patch.setattr(
            updates_module,
            "UpdateInfo",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("build fail")),
        )
        assert (
            updates_module._find_compatible_tag_updates(
                date_local,
                [date_remote],
                log=updater._log,
                compare_versions=updates_module._compare_enhanced_tags,
                digests_equal=updates_module._tag_digests_equal,
            )
            == []
        )

    updater.local_images = {}
    validation = asyncio.run(updater._check_updates())
    assert validation.status == UpdaterStatus.VALIDATION_ERROR

    # All failed branch (repositories_failed > 0 and processed == 0).
    updater.local_images = {
        "repo/missing": [{"tag": "latest", "created_at": "", "digest": None}]
    }

    class _NoopClientSession:
        def __init__(self, **_kwargs: str | float | bool | int) -> None:
            return

        async def __aenter__(self) -> _NoopClientSession:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    monkeypatch.setattr(
        "pytmbot.adapters.docker.updates.aiohttp.TCPConnector",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(updates_module, "ClientSession", _NoopClientSession)
    monkeypatch.setattr(
        updater,
        "_fetch_remote_tags",
        lambda _session, _repo: (_ for _ in ()).throw(
            _make_client_response_error(404, "missing")
        ),
    )
    all_failed = asyncio.run(updater._check_updates())
    assert all_failed.status == UpdaterStatus.ERROR

    # gather exception branch.
    updater.local_images = {
        "repo/fail": [{"tag": "latest", "created_at": "", "digest": None}]
    }

    async def _gather_fail(
        *_args: Coroutine[None, None, UpdaterResponse], **_kwargs: bool
    ) -> list[UpdaterResponse]:
        for arg in _args:
            if asyncio.iscoroutine(arg):
                arg.close()
        raise RuntimeError("gather failed")

    monkeypatch.setattr("pytmbot.adapters.docker.updates.asyncio.gather", _gather_fail)
    gather_failed = asyncio.run(updater._check_updates())
    assert gather_failed.status == UpdaterStatus.ERROR

    # outer exception branch.
    class _FailingSession:
        def __init__(self, **_kwargs: str | float | bool | int) -> None:
            return

        async def __aenter__(self) -> Never:
            raise RuntimeError("session failure")

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    monkeypatch.setattr(updates_module, "ClientSession", _FailingSession)
    outer_failed = asyncio.run(updater._check_updates())
    assert outer_failed.status == UpdaterStatus.ERROR
