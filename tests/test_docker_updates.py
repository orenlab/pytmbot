from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from aiohttp import ClientResponseError, ClientSession
from aiohttp.client_reqrep import RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from pytmbot.adapters.docker.updates import (
    MAX_TAGS_PER_REPO,
    DockerImageUpdater,
    EnhancedTagInfo,
    TagAnalyzer,
    TagInfo,
    TagType,
    UpdaterStatus,
    dict_to_tag_info,
    normalize_created_at,
)


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
        dict_to_tag_info({"tag": "latest"})  # type: ignore[arg-type]


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
    assert DockerImageUpdater._build_repository_urls("orenlab/pytmbot") == [
        "https://registry.hub.docker.com/v2/repositories/orenlab/pytmbot/tags/"
    ]
    assert DockerImageUpdater._build_repository_urls("nginx") == [
        "https://registry.hub.docker.com/v2/repositories/nginx/tags/",
        "https://registry.hub.docker.com/v2/repositories/library/nginx/tags/",
    ]


def test_parse_tag_handles_registry_prefix_and_default_latest() -> None:
    assert DockerImageUpdater._parse_tag("docker.io/library/nginx:1.27") == (
        "library/nginx",
        "1.27",
    )
    assert DockerImageUpdater._parse_tag("redis") == ("redis", "latest")
    with pytest.raises(ValueError):
        DockerImageUpdater._parse_tag("")


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
    assert DockerImageUpdater._compare_versions(local, remote) is True
    assert DockerImageUpdater._digests_equal(local, remote) is False

    remote_same_digest = analyzer.analyze_tag(
        TagInfo(
            name="v1.3.0",
            created_at=datetime(2026, 2, 1, tzinfo=UTC).isoformat(),
            digest="sha256:a",
        )
    )
    assert DockerImageUpdater._digests_equal(local, remote_same_digest) is True


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
    updates = updater._find_compatible_updates(local, remote_tags)
    newer_tags = {update.newer_tag for update in updates}
    assert "v1.3.0" in newer_tags
    assert "v2.0.0" not in newer_tags


def test_updater_to_json_and_cache_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    updater = DockerImageUpdater()

    async def _failing_check_updates() -> object:
        raise RuntimeError("failed")

    monkeypatch.setattr(
        updater,
        "_check_updates",
        _failing_check_updates,
    )
    payload = updater.to_dict()
    assert payload["status"] == "ERROR"
    assert "failed" in payload["message"]
    assert "performance" in updater.get_stats()
    updater.clear_cache()
    assert updater.get_stats()["cache"]["size"] == 0


def test_validate_configuration_reports_known_issues() -> None:
    updater = DockerImageUpdater(timeout=61)
    updater._stats["api_calls"] = 10
    updater._stats["rate_limits"] = 2
    validation = updater.validate_configuration()
    assert validation["valid"] is False
    assert validation["issues"]


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
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        async def __aenter__(self) -> _FakeResponse:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: object,
        ) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def json(self) -> dict[str, Any]:
            return self._payload

    results: list[dict[str, Any]] = [
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
    payload = {"results": results}
    calls = {"count": 0}

    def _fake_get(self: object, _url: str, timeout: object) -> _FakeResponse:
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
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        async def __aenter__(self) -> _FakeResponse:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: object,
        ) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def json(self) -> dict[str, Any]:
            return self._payload

    results = [
        {
            "name": f"v1.0.{idx}",
            "tag_last_pushed": "2026-02-01T00:00:00Z",
            "digest": f"sha256:{idx:064x}",
        }
        for idx in range(MAX_TAGS_PER_REPO + 5)
    ]

    def _fake_get_success(self: object, _url: str, timeout: object) -> _FakeResponse:
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
            _tb: object,
        ) -> None:
            return None

        def raise_for_status(self) -> None:
            raise _make_client_response_error(500, "server error")

        async def json(self) -> dict[str, Any]:
            return {}

    def _fake_get_failing(self: object, _url: str, timeout: object) -> _FailingResponse:
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
    updater.tag_cache["repo/app"] = ([analyzed], time.time())

    async def _run_from_cache() -> list[EnhancedTagInfo]:
        async with ClientSession() as session:
            return await updater._fetch_remote_tags(session, "repo/app")

    from_cache = asyncio.run(_run_from_cache())
    assert len(from_cache) == 1
    assert updater._stats["cache_hits"] == 1

    updater.tag_cache.clear()

    async def _always_404(
        _session: object, _url: str, _repo: str
    ) -> list[EnhancedTagInfo] | None:
        raise _make_client_response_error(404, "not found")

    monkeypatch.setattr(updater, "_fetch_tags_from_url", _always_404)

    async def _run_missing() -> list[EnhancedTagInfo]:
        async with ClientSession() as session:
            return await updater._fetch_remote_tags(session, "missing")

    missing = asyncio.run(_run_missing())
    assert missing == []
    assert "missing" in updater.tag_cache
    assert updater.tag_cache["missing"][0] == []


def test_check_updates_status_transitions(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytmbot.adapters.docker.updates as updates_module

    class _NoopClientSession:
        def __init__(self, **_kwargs: object) -> None:
            return

        async def __aenter__(self) -> _NoopClientSession:
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: object,
        ) -> None:
            return None

    monkeypatch.setattr(
        updates_module.aiohttp, "TCPConnector", lambda **_kwargs: object()
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

    async def _fetch_success(_session: object, _repo: str) -> list[EnhancedTagInfo]:
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
        _session: object, _repo: str
    ) -> list[EnhancedTagInfo]:
        raise _make_client_response_error(429, "rate limited")

    monkeypatch.setattr(updater, "_fetch_remote_tags", _fetch_rate_limited)
    rate_limited = asyncio.run(updater._check_updates())
    assert rate_limited.status == UpdaterStatus.RATE_LIMITED
    assert rate_limited.repositories_failed == 1

    updater.local_images = {"repo/ok": [local_tag], "repo/fail": [local_tag]}

    async def _fetch_mixed(_session: object, repo: str) -> list[EnhancedTagInfo]:
        if repo == "repo/ok":
            return [remote_tag]
        raise RuntimeError("boom")

    monkeypatch.setattr(updater, "_fetch_remote_tags", _fetch_mixed)
    partial = asyncio.run(updater._check_updates())
    assert partial.status == UpdaterStatus.PARTIAL_SUCCESS
    assert partial.repositories_processed == 1
    assert partial.repositories_failed == 1
