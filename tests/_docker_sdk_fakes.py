"""
Fake Docker Engine API behind the real docker SDK model layer.

Only ``DockerClient.api`` is faked: ContainerCollection, ImageCollection,
Container and Image are the installed docker SDK code. Container references
resolve like dockerd (full ID, then exact name, then unique ID prefix).
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType

import pytest
from docker.client import DockerClient
from docker.errors import APIError, ImageNotFound, NotFound

type FakeAttrs = dict[str, object]

DEFAULT_IMAGE_ID = "sha256:" + "a" * 64


def make_container_attrs(
    container_id: str,
    name: str,
    status: str = "running",
    *,
    image_id: str = DEFAULT_IMAGE_ID,
    env: list[str] | None = None,
    cmd: list[str] | None = None,
) -> FakeAttrs:
    """Build inspect-style container attrs."""
    return {
        "Id": container_id,
        "Name": "/" + name,
        "Image": image_id,
        "Created": "2026-10-19T07:00:00.123456789Z",
        "RestartCount": 0,
        "State": {
            "Status": status,
            "Running": status in ("running", "paused", "restarting"),
            "Paused": status == "paused",
            "Restarting": status == "restarting",
            "StartedAt": "2026-10-19T07:00:01.5Z",
            "ExitCode": 0,
        },
        "Config": {"Image": "nginx:latest", "Env": env or [], "Cmd": cmd or []},
        "HostConfig": {},
        "NetworkSettings": {
            "Networks": {"bridge": {}},
            "Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
        },
    }


def make_image_attrs(
    image_id: str,
    tags: list[str] | None = None,
    *,
    env: list[str] | None = None,
    created: str = "2026-10-19T07:00:00Z",
) -> FakeAttrs:
    """Build inspect-style image attrs."""
    return {
        "Id": image_id,
        "RepoTags": tags or [],
        "Created": created,
        "Size": 12 * 1024 * 1024,
        "Config": {"Env": env or [], "Cmd": [], "Entrypoint": []},
    }


class FakeDockerApi:
    """Minimal stand-in for ``docker.api.client.APIClient``."""

    def __init__(
        self,
        containers: list[FakeAttrs],
        images: list[FakeAttrs] | None = None,
    ) -> None:
        self.containers_db: dict[str, FakeAttrs] = {
            str(container["Id"]): container for container in containers
        }
        self.images_db: dict[str, FakeAttrs] = {
            str(image["Id"]): image for image in images or []
        }
        self.history_db: dict[str, list[dict[str, object]]] = {}
        self.calls: list[tuple[str, object]] = []
        self.vanish_on_inspect: set[str] = set()
        self.vanish_images_on_inspect: set[str] = set()
        self.remove_on_stop: set[str] = set()
        self.fail_on: dict[str, Exception] = {}
        self.timeout = 10

    # --- helpers -----------------------------------------------------------
    def _maybe_fail(self, operation: str) -> None:
        error = self.fail_on.get(operation)
        if error is not None:
            raise error

    def _state(self, container_id: str) -> dict[str, object]:
        state = self.containers_db[container_id]["State"]
        assert isinstance(state, dict)
        return state

    def set_status(self, container_id: str, status: str) -> None:
        state = self._state(container_id)
        state["Status"] = status
        state["Running"] = status in ("running", "paused", "restarting")

    def _resolve(self, reference: str) -> FakeAttrs:
        if reference in self.containers_db:
            return self.containers_db[reference]
        for container in self.containers_db.values():
            if container["Name"] == "/" + reference:
                return container
        matches = [
            container
            for container_id, container in self.containers_db.items()
            if container_id.startswith(reference)
        ]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise APIError(f"multiple IDs found with provided prefix: {reference}")
        raise NotFound(f"No such container: {reference}")

    # --- containers --------------------------------------------------------
    def containers(self, all: bool = False, **_kwargs: object) -> list[FakeAttrs]:  # noqa: A002
        self.calls.append(("containers", all))
        self._maybe_fail("containers")
        return [
            {
                "Id": container_id,
                "Names": [container["Name"]],
                "Image": container["Image"],
                "State": self._state(container_id)["Status"],
            }
            for container_id, container in self.containers_db.items()
        ]

    def inspect_container(self, reference: str) -> FakeAttrs:
        self.calls.append(("inspect_container", reference))
        self._maybe_fail("inspect_container")
        if reference in self.vanish_on_inspect:
            raise NotFound(f"No such container: {reference}")
        return copy.deepcopy(self._resolve(reference))

    def start(self, container: str, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("start", container))
        self._maybe_fail("start")
        self.set_status(container, "running")

    def stop(self, container: str, timeout: int | None = None) -> None:
        self.calls.append(("stop", (container, timeout)))
        self._maybe_fail("stop")
        self.set_status(container, "exited")
        if container in self.remove_on_stop:
            del self.containers_db[container]

    def restart(self, container: str, timeout: int = 10) -> None:
        self.calls.append(("restart", (container, timeout)))
        self._maybe_fail("restart")
        self.set_status(container, "running")

    def logs(self, container: str, **_kwargs: object) -> bytes:
        self.calls.append(("logs", container))
        self._maybe_fail("logs")
        return f"logs of {container[:12]}\n".encode()

    # --- images ------------------------------------------------------------
    def images(
        self,
        name: str | None = None,
        quiet: bool = False,
        all: bool = False,  # noqa: A002
        filters: object = None,
    ) -> list[object]:
        del name, filters
        self.calls.append(("images", all))
        self._maybe_fail("images")
        if quiet:
            return list(self.images_db)
        return [{"Id": image_id} for image_id in self.images_db]

    def inspect_image(self, reference: str) -> FakeAttrs:
        self.calls.append(("inspect_image", reference))
        if reference in self.vanish_images_on_inspect:
            raise ImageNotFound(f"No such image: {reference}")
        hex_reference = reference.removeprefix("sha256:")
        for image_id, image in self.images_db.items():
            tags = image.get("RepoTags")
            if reference in (tags if isinstance(tags, list) else []):
                return copy.deepcopy(image)
            if image_id.removeprefix("sha256:").startswith(hex_reference):
                return copy.deepcopy(image)
        raise ImageNotFound(f"No such image: {reference}")

    def history(self, image: str) -> list[dict[str, object]]:
        self.calls.append(("history", image))
        return copy.deepcopy(self.history_db.get(image, []))

    def close(self) -> None:
        self.calls.append(("close", None))


def make_client(api: FakeDockerApi) -> DockerClient:
    """Return a real DockerClient whose low-level API is the fake."""
    client = DockerClient.__new__(DockerClient)
    client.api = api
    return client


def install_client(
    monkeypatch: pytest.MonkeyPatch,
    modules: list[ModuleType],
    client: DockerClient,
) -> None:
    """Make ``docker_client_context()`` yield ``client`` in the given modules."""

    @contextmanager
    def _context() -> Iterator[DockerClient]:
        yield client

    for module in modules:
        monkeypatch.setattr(module, "docker_client_context", _context)


def api_calls(api: FakeDockerApi, operation: str) -> list[object]:
    """Arguments of all recorded calls of one API operation."""
    return [argument for name, argument in api.calls if name == operation]
