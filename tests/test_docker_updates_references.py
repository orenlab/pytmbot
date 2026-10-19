"""Image references, registries and local digests for the Docker update check."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace, TracebackType

import pytest
from aiohttp import ClientSession

import pytmbot.adapters.docker.updates as updates_module
from pytmbot.adapters.docker.updates import (
    CheckFailure,
    DockerImageUpdater,
    EnhancedTagInfo,
    LocalImageInfo,
    UpdaterStatus,
    parse_image_reference,
)
from pytmbot.models.docker_models import TagInfo

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


class _NoopClientSession:
    def __init__(self, **_kwargs: object) -> None:
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


@pytest.fixture
def offline_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(
        "pytmbot.adapters.docker.updates.aiohttp.TCPConnector",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(updates_module, "ClientSession", _NoopClientSession)
    yield


@pytest.mark.parametrize(
    ("reference", "registry", "path", "tag"),
    [
        ("nginx", "docker.io", "library/nginx", "latest"),
        ("nginx:1.25", "docker.io", "library/nginx", "1.25"),
        ("acme/app:2", "docker.io", "acme/app", "2"),
        ("docker.io/library/nginx:1.25", "docker.io", "library/nginx", "1.25"),
        ("docker.io/nginx", "docker.io", "library/nginx", "latest"),
        ("index.docker.io/acme/app:1", "docker.io", "acme/app", "1"),
        ("registry-1.docker.io/acme/app", "docker.io", "acme/app", "latest"),
        (
            "registry.corp.example:5000/acme/payments:2.3.1",
            "registry.corp.example:5000",
            "acme/payments",
            "2.3.1",
        ),
        ("quay.io/org/team/tool:1.0.0", "quay.io", "org/team/tool", "1.0.0"),
        ("ghcr.io/acme/app:1.0.0", "ghcr.io", "acme/app", "1.0.0"),
        ("localhost:5000/app", "localhost:5000", "app", "latest"),
        ("localhost/app:1", "localhost", "app", "1"),
        (f"nginx:1.25@{DIGEST_A}", "docker.io", "library/nginx", "1.25"),
    ],
)
def test_parse_image_reference_follows_docker_rules(
    reference: str, registry: str, path: str, tag: str
) -> None:
    parsed = parse_image_reference(reference)
    assert (parsed.registry, parsed.path, parsed.tag) == (registry, path, tag)
    assert parsed.is_docker_hub is (registry == "docker.io")


@pytest.mark.parametrize("reference", ["", "  ", "repo/:", "repo:", "a//b", "/app"])
def test_parse_image_reference_rejects_malformed_values(reference: str) -> None:
    with pytest.raises(ValueError):
        parse_image_reference(reference)


@pytest.mark.parametrize(
    "reference",
    [
        "registry.corp.example:5000/acme/payments:2.3.1",
        "quay.io/org/team/tool",
        "localhost:5000/app",
        "ghcr.io/acme/app",
        "docker.io/org/team/tool",  # Docker Hub has no nested repositories
        "Acme/App",  # not a valid Docker Hub repository name
    ],
)
def test_only_docker_hub_repositories_get_a_docker_hub_url(reference: str) -> None:
    assert updates_module._docker_hub_tags_url(parse_image_reference(reference)) is None


def test_other_registries_and_local_images_are_never_looked_up(
    offline_session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    updater = DockerImageUpdater()
    updater.local_images = {
        "registry.corp.example:5000/acme/payments": [
            {"tag": "2.3.1", "created_at": "", "digest": DIGEST_A}
        ],
        "quay.io/org/team/tool": [{"tag": "1.0.0", "created_at": "", "digest": None}],
        "localhost:5000/app": [{"tag": "latest", "created_at": "", "digest": None}],
        "myapp": [{"tag": "dev", "created_at": "", "digest": None}],
    }
    looked_up: list[str] = []

    async def _fetch(_session: ClientSession, repo: str) -> list[EnhancedTagInfo]:
        looked_up.append(repo)
        return []

    monkeypatch.setattr(updater, "_fetch_remote_tags", _fetch)
    response = asyncio.run(updater._check_updates())

    assert looked_up == []
    assert response.status == UpdaterStatus.SUCCESS
    assert response.repositories_failed == 0
    assert isinstance(response.data, dict)
    assert {label: result["error"] for label, result in response.data.items()} == {
        "registry.corp.example:5000/acme/payments:2.3.1": "registry not supported",
        "quay.io/org/team/tool:1.0.0": "registry not supported",
        "localhost:5000/app:latest": "registry not supported",
        "myapp:dev": "local image",
    }


def test_docker_hub_images_are_checked_under_their_full_reference(
    offline_session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    updater = DockerImageUpdater()
    updater.local_images = {
        "nginx": [
            {"tag": "1.25.3", "created_at": "", "digest": DIGEST_A},
            {"tag": "custom", "created_at": "", "digest": None},
        ],
        "docker.io/acme/app": [{"tag": "1.0.0", "created_at": "", "digest": DIGEST_A}],
    }
    remote = {
        "nginx": [TagInfo(name="1.25.4", created_at="", digest=DIGEST_B)],
        "docker.io/acme/app": [TagInfo(name="1.0.0", created_at="", digest=DIGEST_A)],
    }
    looked_up: list[str] = []

    async def _fetch(_session: ClientSession, repo: str) -> list[EnhancedTagInfo]:
        looked_up.append(repo)
        return [updater.analyzer.analyze_tag(tag) for tag in remote[repo]]

    monkeypatch.setattr(updater, "_fetch_remote_tags", _fetch)
    response = asyncio.run(updater._check_updates())

    assert sorted(looked_up) == ["docker.io/acme/app", "nginx"]
    assert isinstance(response.data, dict)
    data = response.data
    assert sorted(data) == ["docker.io/acme/app:1.0.0", "nginx:1.25.3", "nginx:custom"]
    assert [u["newer_tag"] for u in data["nginx:1.25.3"]["updates"]] == ["1.25.4"]
    assert data["nginx:custom"]["error"] == CheckFailure.LOCAL_IMAGE.value
    assert data["docker.io/acme/app:1.0.0"]["updates"] == []
    assert "error" not in data["docker.io/acme/app:1.0.0"]


def test_local_digest_comes_from_the_tags_own_repository() -> None:
    image = SimpleNamespace(
        attrs={
            "Created": "2024-01-01T00:00:00Z",
            "RepoDigests": [
                f"registry.local/team/nginx@{DIGEST_B}",
                f"docker.io/library/nginx@{DIGEST_A}",
            ],
        },
        tags=["nginx:latest", "registry.local/team/nginx:latest", "myapp:dev"],
    )
    local_images: LocalImageInfo = {}
    updates_module._process_local_image_tags(
        image, local_images, log=DockerImageUpdater()._log
    )

    digests = {
        repository: [entry["digest"] for entry in entries]
        for repository, entries in local_images.items()
    }
    assert digests == {
        "nginx": [DIGEST_A],
        "registry.local/team/nginx": [DIGEST_B],
        # Re-tagged locally: no digest for this repository, so not checkable.
        "myapp": [None],
    }


def test_matching_digest_means_up_to_date(
    offline_session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = SimpleNamespace(
        attrs={
            "Created": "2024-01-01T00:00:00Z",
            "RepoDigests": [
                f"registry.local/team/nginx@{DIGEST_B}",
                f"nginx@{DIGEST_A}",
            ],
        },
        tags=["nginx:latest"],
    )
    updater = DockerImageUpdater()
    updates_module._process_local_image_tags(
        image, updater.local_images, log=updater._log
    )

    async def _fetch(_session: ClientSession, _repo: str) -> list[EnhancedTagInfo]:
        hub_latest = TagInfo(
            name="latest", created_at="2024-01-02T00:00:00Z", digest=DIGEST_A
        )
        return [updater.analyzer.analyze_tag(hub_latest)]

    monkeypatch.setattr(updater, "_fetch_remote_tags", _fetch)
    response = asyncio.run(updater._check_updates())

    assert isinstance(response.data, dict)
    assert response.data["nginx:latest"]["updates"] == []
    assert "error" not in response.data["nginx:latest"]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"name": "1.0.1", "digest": DIGEST_A}, ("1.0.1", DIGEST_A)),
        ({"name": "1.0.1", "digest": DIGEST_A + "\n"}, ("1.0.1", None)),
        ({"name": "1.0.1\n", "digest": DIGEST_A}, None),
        ({"name": "１.０", "digest": None}, None),  # non-ASCII digits
        ({"name": "<b>", "digest": None}, None),
        ({"name": "x" * 129, "digest": None}, None),
        ({"digest": DIGEST_A}, None),
        ("1.0.1", None),
    ],
)
def test_registry_tag_entries_are_validated(
    entry: object, expected: tuple[str, str | None] | None
) -> None:
    tag_info = updates_module._tag_info_from_entry(entry)
    assert (None if tag_info is None else (tag_info.name, tag_info.digest)) == expected
