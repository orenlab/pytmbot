"""Tag classification and version comparison for the Docker update check."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import pytmbot.adapters.docker.updates as updates_module
from pytmbot.adapters.docker.updates import (
    DockerImageUpdater,
    EnhancedTagInfo,
    TagAnalyzer,
    TagType,
)
from pytmbot.models.docker_models import TagInfo

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _tag(name: str, created_at: str = "", digest: str | None = None) -> EnhancedTagInfo:
    return TagAnalyzer.analyze_tag(
        TagInfo(name=name, created_at=created_at, digest=digest)
    )


def _suggested(local: EnhancedTagInfo, remote: list[EnhancedTagInfo]) -> list[str]:
    updates = updates_module._find_compatible_tag_updates(
        local,
        remote,
        log=DockerImageUpdater()._log,
        compare_versions=updates_module._compare_enhanced_tags,
        digests_equal=updates_module._tag_digests_equal,
    )
    return [update.newer_tag for update in updates]


@pytest.mark.parametrize(
    ("name", "tag_type"),
    [
        ("20240115", TagType.DATE),
        ("2024-01-15", TagType.DATE),
        ("20240115-120000", TagType.DATE),
        ("1234567", TagType.SEMVER),  # numbers before SHA detection
        ("abcdef0", TagType.SHA),
        ("16", TagType.SEMVER),
        ("1.25-alpine", TagType.SEMVER),
        ("1.25.3-alpine3.19", TagType.SEMVER),
        ("v2.0.0", TagType.SEMVER),
        ("release-1.2.3", TagType.SEMVER),
        ("1.27.0-rc1", TagType.SEMVER),
        ("2024.01.15", TagType.SEMVER),
        ("mainline-alpine-perl", TagType.CUSTOM),
        ("latest", TagType.LATEST),
        ("stable", TagType.LATEST),
    ],
)
def test_tag_classification(name: str, tag_type: TagType) -> None:
    assert _tag(name).tag_type == tag_type


def test_prerelease_and_variant_are_split_from_the_version() -> None:
    rc = _tag("1.27.0-rc1-alpine")
    assert rc.version_info is not None and rc.version_info.is_prerelease
    assert rc.family == _tag("1.27.0-alpine").family
    assert _tag("1.0.0-beta.2").version_info == _tag("1.0.0b2").version_info
    assert _tag("1.25.3-alpine").family != _tag("1.25.3").family
    assert _tag("16").family != _tag("16.1").family
    assert _tag("v1.2.3").family != _tag("1.2.3").family


@pytest.mark.parametrize(
    ("local", "remote", "expected"),
    [
        # Same variant only, no pre-releases, never lower versions.
        (
            "1.25.3-alpine",
            [
                "1.25.4",
                "1.27.0-rc1",
                "1.27.0-rc1-alpine",
                "1.25.2-alpine",
                "1.25.3-alpine",
                "1.25.5-alpine",
                "1.26.1-alpine",
            ],
            ["1.26.1-alpine", "1.25.5-alpine"],
        ),
        (
            "1.25-alpine",
            ["mainline-alpine-perl", "1.24-alpine", "stable-bookworm", "1.27-alpine"],
            ["1.27-alpine"],
        ),
        # A floating major tag is only updated through its own digest.
        ("16", ["16.1", "16.2", "17", "15"], []),
        # Major upgrades are not suggested.
        ("1.2.3", ["2.0.0", "1.2.4", "1.10.0"], ["1.10.0", "1.2.4"]),
        # Pre-releases only for pre-release users; the final release wins.
        (
            "1.0.0-rc1",
            ["1.0.0-rc2", "1.0.0", "0.9.0", "1.0.0-beta1"],
            ["1.0.0", "1.0.0-rc2"],
        ),
        ("v1.2.0", ["v1.3.0", "1.4.0"], ["v1.3.0"]),
        ("20240115", ["20240301", "20231201", "2024-03-01"], ["20240301"]),
        ("latest", ["stable", "main", "1.0.0"], []),
        ("abcdef0", ["abcdef1", "1234567"], []),
        ("feature-x", ["feature-y", "mainline"], []),
    ],
)
def test_suggested_updates(local: str, remote: list[str], expected: list[str]) -> None:
    assert _suggested(_tag(local), [_tag(name) for name in remote]) == expected


def test_latest_and_custom_tags_update_only_through_a_new_digest() -> None:
    for name in ("latest", "feature-x", "abcdef0", "1.25"):
        local = _tag(name, digest=DIGEST_A)
        assert _suggested(local, [_tag(name, digest=DIGEST_A)]) == []
        assert _suggested(local, [_tag(name, digest=DIGEST_B)]) == [name]
        # Unknown digests prove nothing.
        assert _suggested(local, [_tag(name)]) == []


def test_duplicate_remote_tags_are_suggested_once() -> None:
    remote = [_tag("1.2.4"), _tag("1.2.4"), _tag("1.2.5")]
    assert _suggested(_tag("1.2.3"), remote) == ["1.2.5", "1.2.4"]


def test_sorting_never_mixes_naive_aware_or_broken_timestamps() -> None:
    tags = [
        _tag("custom-a", created_at="2024-01-01T00:00:00"),
        _tag("custom-b", created_at="2024-01-02T00:00:00Z"),
        _tag("custom-c", created_at="garbage"),
        _tag("custom-d", created_at=""),
        _tag("custom-e", created_at="2024-01-01T00:00:00+02:00"),
    ]
    ordered = [tag.name for tag in sorted(tags)]
    assert ordered == ["custom-c", "custom-d", "custom-e", "custom-a", "custom-b"]

    key = updates_module._timestamp_sort_key
    assert key("2024-01-01T00:00:00") == datetime(2024, 1, 1, tzinfo=UTC)
    assert key("not a date") == datetime.min.replace(tzinfo=UTC)
    assert key(None).tzinfo is not None
