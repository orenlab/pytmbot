"""Listings survive objects vanishing mid-listing and never serve stale state."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

import pytmbot.adapters.docker.containers_info as containers_info_module
import pytmbot.adapters.docker.images_info as images_info_module
import pytmbot.adapters.docker.utils as docker_utils_module
from tests._docker_sdk_fakes import (
    FakeDockerApi,
    api_calls,
    install_client,
    make_client,
    make_container_attrs,
    make_image_attrs,
)

WEB_ID = "a1" + "0" * 62
JOB_ID = "b2" + "0" * 62
DB_ID = "c3" + "0" * 62
IMAGE_A = "sha256:" + "1" * 64
IMAGE_B = "sha256:" + "2" * 64
REMOVED_IMAGE = "sha256:" + "9" * 64


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> FakeDockerApi:
    api = FakeDockerApi(
        [
            make_container_attrs(WEB_ID, "web", image_id=IMAGE_A),
            make_container_attrs(JOB_ID, "job", status="exited", image_id=IMAGE_A),
            make_container_attrs(DB_ID, "db", status="paused", image_id=REMOVED_IMAGE),
        ],
        images=[
            make_image_attrs(IMAGE_A, ["app:1"]),
            make_image_attrs(IMAGE_B, []),
        ],
    )
    install_client(
        monkeypatch,
        [containers_info_module, images_info_module, docker_utils_module],
        make_client(api),
    )
    return api


def test_container_listing_skips_container_removed_mid_listing(
    fake_api: FakeDockerApi,
) -> None:
    fake_api.vanish_on_inspect = {JOB_ID}  # `docker run --rm` finished meanwhile
    rows = containers_info_module.retrieve_containers_stats()
    assert [row["id"] for row in rows] == [DB_ID[:12], WEB_ID[:12]]


def test_container_rows_include_networks_and_ports(fake_api: FakeDockerApi) -> None:
    rows = containers_info_module.retrieve_containers_stats()
    web = next(row for row in rows if row["id"] == WEB_ID[:12])
    assert web["networks"] == "bridge"
    assert web["ports"] == "0.0.0.0:8080->80/tcp"
    assert web["created"] == "2026-10-19, 07:00:00"


def test_list_shows_fresh_status_right_after_an_action(
    fake_api: FakeDockerApi,
) -> None:
    before = containers_info_module.retrieve_containers_stats()
    assert next(r for r in before if r["id"] == WEB_ID[:12])["status"] == "running"

    fake_api.set_status(WEB_ID, "exited")  # e.g. stopped through the bot
    after = containers_info_module.retrieve_containers_stats()
    assert next(r for r in after if r["id"] == WEB_ID[:12])["status"] == "exited"


def test_counters_use_sparse_listing_and_count_states_separately(
    fake_api: FakeDockerApi,
) -> None:
    fake_api.vanish_on_inspect = {JOB_ID}
    fake_api.containers_db["d4" + "0" * 62] = make_container_attrs(
        "d4" + "0" * 62, "init", status="created"
    )
    fake_api.containers_db["e5" + "0" * 62] = make_container_attrs(
        "e5" + "0" * 62, "flappy", status="restarting"
    )

    counters = containers_info_module.fetch_docker_counters(force_refresh=True)

    assert counters == {
        "images_count": 2,
        "containers_count": 5,
        "running_containers": 1,
        "paused_containers": 1,
        "restarting_containers": 1,
        "created_containers": 1,
        "stopped_containers": 1,
    }
    assert api_calls(fake_api, "inspect_container") == []
    assert api_calls(fake_api, "inspect_image") == []


def test_summarize_container_statuses_counts_unknown_as_stopped() -> None:
    summary = containers_info_module.summarize_container_statuses(
        ["running", "Exited", "dead", "removing", "paused"]
    )
    assert summary["containers_count"] == 5
    assert summary["running_containers"] == 1
    assert summary["paused_containers"] == 1
    assert summary["stopped_containers"] == 3


def test_image_listing_skips_image_removed_mid_listing(
    fake_api: FakeDockerApi,
) -> None:
    fake_api.vanish_images_on_inspect = {IMAGE_B}
    images = images_info_module.fetch_image_details()
    assert [image["id"] for image in images] == [IMAGE_A[:19]]
    assert api_calls(fake_api, "images") == [True]  # intermediate layers included


def test_image_usage_survives_container_of_force_removed_image(
    fake_api: FakeDockerApi,
) -> None:
    # The "db" container references an image that no longer exists:
    # ``container.image`` would raise ImageNotFound for it.
    usage = images_info_module.get_image_usage(IMAGE_A[:19])
    assert usage is not None
    assert usage["containers_count"] == 2
    assert usage["running_count"] == 1
    rows = usage["containers"]
    assert isinstance(rows, list)
    assert [row["name"] for row in rows] == ["web", "job"]


def test_image_lookup_by_tag_and_verified_reference(fake_api: FakeDockerApi) -> None:
    usage = images_info_module.get_image_usage("app:1")
    assert usage is not None and usage["containers_count"] == 2
    # "app" means "app:latest", which does not exist.
    assert images_info_module.get_image_usage("app") is None
    # A short hex prefix that is not an exact tag is never trusted.
    assert images_info_module.get_image_usage("111") is None
    assert images_info_module.get_image_history("sha256:" + "f" * 12) is None


@pytest.fixture
def tokyo_timezone() -> Iterator[None]:
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Tokyo"
    time.tzset()
    yield
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    time.tzset()


@pytest.mark.usefixtures("tokyo_timezone")
def test_image_created_time_is_not_skewed_by_local_timezone() -> None:
    created = datetime.now(UTC) - timedelta(hours=2)
    created_raw = created.strftime("%Y-%m-%dT%H:%M:%S.%f123Z")

    parsed, created_at_utc = images_info_module._parse_created(created_raw)

    assert parsed is not None and parsed.tzinfo is not None
    assert created_at_utc == created.strftime("%Y-%m-%d %H:%M:%S UTC")
    details = images_info_module.process_image_attrs(
        type(
            "_Image",
            (),
            {
                "short_id": IMAGE_A[:19],
                "tags": [],
                "attrs": {"Created": created_raw},
            },
        )()
    )
    assert details["created"] == "2 hours ago"
