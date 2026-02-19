from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from docker.errors import ImageNotFound


@dataclass
class _FakeImage:
    short_id: str
    tags: list[str]
    attrs: object
    _history: list[dict[str, object]] = field(default_factory=list)

    def history(self) -> list[dict[str, object]]:
        return self._history


def test_process_image_attrs_success() -> None:
    import pytmbot.adapters.docker.images_info as images_info_module

    image = _FakeImage(
        short_id="sha256:abc",
        tags=["repo/app:1.0"],
        attrs={
            "Created": "2026-02-17T12:00:00.000000Z",
            "RepoTags": ["repo/app:1.0"],
            "RepoDigests": ["repo/app@sha256:abc123"],
            "Architecture": "arm64",
            "Variant": "v8",
            "Os": "linux",
            "Size": 1024,
            "VirtualSize": 2048,
            "SharedSize": 512,
            "Parent": "sha256:parent1234567890",
            "RootFS": {"Type": "layers", "Layers": ["sha256:layer1", "sha256:layer2"]},
            "Author": "dev",
            "DockerVersion": "29.2.0",
            "Config": {
                "Labels": {"com.example": "value"},
                "ExposedPorts": {"8080/tcp": {}},
                "Env": ["A=1"],
                "Entrypoint": ["python"],
                "Cmd": ["main.py"],
                "Shell": ["/bin/sh", "-c"],
                "Volumes": {"/data": {}},
                "User": "1000",
                "WorkingDir": "/app",
                "StopSignal": "SIGINT",
                "Healthcheck": {
                    "Test": [
                        "CMD-SHELL",
                        "curl -f http://localhost:8080/health || exit 1",
                    ],
                    "Interval": 30000000000,
                    "Timeout": 10000000000,
                    "Retries": 3,
                },
            },
        },
    )

    details = images_info_module.process_image_attrs(image)
    assert details["id"] == "sha256:abc"
    assert details["name"] == "repo/app:1.0"
    assert {
        "architecture": details["architecture"],
        "variant": details["variant"],
        "os": details["os"],
        "author": details["author"],
    } == {
        "architecture": "arm64",
        "variant": "v8",
        "os": "linux",
        "author": "dev",
    }
    assert details["labels"] == {"com.example": "value"}
    assert details["exposed_ports"] == ["8080/tcp"]
    assert details["repo_digests"] == ["repo/app@sha256:abc123"]
    assert details["repo_digests_count"] == 1
    assert details["layers_count"] == 2
    assert details["rootfs_type"] == "layers"
    assert details["parent_id"] == "parent1234567890"
    assert details["volumes"] == ["/data"]
    assert details["user"] == "1000"
    assert details["working_dir"] == "/app"
    assert details["stop_signal"] == "SIGINT"
    assert (
        "test=CMD-SHELL curl -f http://localhost:8080/health || exit 1"
        in details["healthcheck"]
    )


def test_process_image_attrs_handles_broken_attrs() -> None:
    import pytmbot.adapters.docker.images_info as images_info_module

    image = _FakeImage(short_id="sha256:broken", tags=[], attrs=None)
    details = images_info_module.process_image_attrs(image)

    assert details["id"] == "sha256:broken"
    assert details["name"] == "<none>:<none>"
    assert details["architecture"] == "N/A"
    assert details["healthcheck"] == "none"
    assert details["labels"] == {}


def test_fetch_image_details_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytmbot.adapters.docker.images_info as images_info_module

    images = [
        _FakeImage(
            short_id="sha256:abc",
            tags=["repo/app:1.0"],
            attrs={
                "Created": "2026-02-17T12:00:00.000000Z",
                "RepoTags": ["repo/app:1.0"],
            },
        )
    ]
    adapter = SimpleNamespace(images=SimpleNamespace(list=lambda all=True: images))  # noqa: FBT002

    @contextmanager
    def _client_context() -> Iterator[object]:
        yield adapter

    monkeypatch.setattr(images_info_module, "docker_client_context", _client_context)

    payload = images_info_module.fetch_image_details()
    assert len(payload) == 1
    assert payload[0]["id"] == "sha256:abc"


def test_fetch_image_details_wraps_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.images_info as images_info_module

    class _FailingContext:
        def __enter__(self) -> object:
            raise images_info_module.DockerConnectionError("down")

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: object,
        ) -> None:
            return None

    monkeypatch.setattr(
        images_info_module, "docker_client_context", lambda: _FailingContext()
    )

    with pytest.raises(
        images_info_module.ImageOperationError, match="Failed to connect"
    ):
        images_info_module.fetch_image_details()


def test_get_image_history_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytmbot.adapters.docker.images_info as images_info_module

    image = _FakeImage(
        short_id="sha256:abc",
        tags=["repo/app:1.0"],
        attrs={"Created": "2026-02-17T12:00:00.000000Z"},
        _history=[
            {
                "Id": "sha256:layer123456789",
                "Created": 1700000000,
                "CreatedBy": "RUN apk add curl",
                "Size": 512,
                "Comment": "layer",
                "Tags": ["repo/app:1.0"],
            }
        ],
    )
    adapter = SimpleNamespace(
        images=SimpleNamespace(
            get=lambda _image_id: image,
        )
    )

    @contextmanager
    def _client_context() -> Iterator[object]:
        yield adapter

    monkeypatch.setattr(images_info_module, "docker_client_context", _client_context)

    history = images_info_module.get_image_history("sha256:abc")
    assert len(history) == 1
    assert history[0]["id"] == "sha256:layer"
    assert history[0]["created_by"] == "RUN apk add curl"


def test_get_image_history_raises_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytmbot.adapters.docker.images_info as images_info_module

    adapter = SimpleNamespace(
        images=SimpleNamespace(
            get=lambda _image_id: (_ for _ in ()).throw(ImageNotFound("missing")),
        )
    )

    @contextmanager
    def _client_context() -> Iterator[object]:
        yield adapter

    monkeypatch.setattr(images_info_module, "docker_client_context", _client_context)

    with pytest.raises(ImageNotFound):
        images_info_module.get_image_history("missing")


def test_get_image_stats_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytmbot.adapters.docker.images_info as images_info_module

    images = [
        _FakeImage(
            short_id="sha256:1",
            tags=["repo/a:1"],
            attrs={"Size": 1024, "Os": "linux", "Architecture": "amd64"},
        ),
        _FakeImage(
            short_id="sha256:2",
            tags=[],
            attrs={"Size": 2048, "Os": "linux", "Architecture": "arm64"},
        ),
    ]
    adapter = SimpleNamespace(images=SimpleNamespace(list=lambda all=True: images))  # noqa: FBT002

    @contextmanager
    def _client_context() -> Iterator[object]:
        yield adapter

    monkeypatch.setattr(images_info_module, "docker_client_context", _client_context)

    stats = images_info_module.get_image_stats()
    assert stats["total_images"] == 2
    assert stats["tagged_images"] == 1
    assert stats["untagged_images"] == 1
    assert set(stats["architectures"]) == {"amd64", "arm64"}

    class _FailingContext:
        def __enter__(self) -> object:
            raise RuntimeError("boom")

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: object,
        ) -> None:
            return None

    monkeypatch.setattr(
        images_info_module, "docker_client_context", lambda: _FailingContext()
    )

    with pytest.raises(
        images_info_module.ImageOperationError, match="Failed to get image statistics"
    ):
        images_info_module.get_image_stats()


def test_get_image_usage_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.images_info as images_info_module

    image = SimpleNamespace(id="sha256:img")
    containers = [
        SimpleNamespace(
            name="api",
            short_id="abc123",
            status="running",
            image=SimpleNamespace(id="sha256:img"),
            attrs={"State": {"Status": "running", "StartedAt": "2026-02-19T14:00:00Z"}},
        ),
        SimpleNamespace(
            name="worker",
            short_id="def456",
            status="exited",
            image=SimpleNamespace(id="sha256:img"),
            attrs={"State": {"Status": "exited", "StartedAt": "2026-02-19T13:00:00Z"}},
        ),
        SimpleNamespace(
            name="other",
            short_id="zzz999",
            status="running",
            image=SimpleNamespace(id="sha256:other"),
            attrs={"State": {"Status": "running", "StartedAt": "2026-02-19T12:00:00Z"}},
        ),
    ]
    adapter = SimpleNamespace(
        images=SimpleNamespace(get=lambda _image_id: image),
        containers=SimpleNamespace(list=lambda all=True: containers),  # noqa: FBT002
    )

    @contextmanager
    def _client_context() -> Iterator[object]:
        yield adapter

    monkeypatch.setattr(images_info_module, "docker_client_context", _client_context)

    usage = images_info_module.get_image_usage("sha256:img")
    assert usage["containers_count"] == 2
    assert usage["running_count"] == 1
    assert usage["stopped_count"] == 1
    assert usage["containers"][0]["name"] == "api"

    class _FailingContext:
        def __enter__(self) -> object:
            raise RuntimeError("boom")

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: object,
        ) -> None:
            return None

    monkeypatch.setattr(
        images_info_module, "docker_client_context", lambda: _FailingContext()
    )

    with pytest.raises(
        images_info_module.ImageOperationError, match="Failed to get image usage"
    ):
        images_info_module.get_image_usage("sha256:img")
