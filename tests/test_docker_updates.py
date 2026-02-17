from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pytmbot.adapters.docker.updates import (
    DockerImageUpdater,
    TagAnalyzer,
    TagInfo,
    TagType,
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
