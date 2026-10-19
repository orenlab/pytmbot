"""Secrets in container/image config are never shown in clear text."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import pytmbot.adapters.docker.images_info as images_info_module
import pytmbot.handlers.handlers_util.docker as handlers_docker
from pytmbot.adapters.docker.utils import (
    SECRET_MASK,
    mask_command_args,
    mask_environment_variables,
    mask_secrets_in_text,
    mask_url_credentials,
)
from tests._docker_sdk_fakes import (
    FakeDockerApi,
    install_client,
    make_client,
    make_image_attrs,
)

M = SECRET_MASK
IMAGE_ID = "sha256:" + "4" * 64


def test_secret_mask_is_four_bullets() -> None:
    assert M == "••••"


def test_environment_variables_show_keys_only() -> None:
    masked = mask_environment_variables(
        [
            "PATH=/usr/local/bin:/usr/bin",
            "TZ=Europe/Berlin",
            "LC_ALL=C.UTF-8",
            "PUID=1000",
            "NODE_ENV=production",
            "DB_PASSWORD=hunter2",
            "NGINX_VERSION=1.25.3",
            "API_KEY=abcd",
            "DATABASE_URL=postgres://app:s3cret@db/app",
            "EMPTY=",
            "FLAG_ONLY",
            "Path=/not/allowlisted",
        ]
    )
    assert masked == [
        "PATH=/usr/local/bin:/usr/bin",
        "TZ=Europe/Berlin",
        "LC_ALL=C.UTF-8",
        "PUID=1000",
        "NODE_ENV=production",
        f"DB_PASSWORD={M}",
        f"NGINX_VERSION={M}",
        f"API_KEY={M}",
        f"DATABASE_URL={M}",
        "EMPTY=",
        "FLAG_ONLY",
        f"Path={M}",
    ]


def test_allowlisted_values_still_mask_url_credentials() -> None:
    assert mask_environment_variables(["ENVIRONMENT=https://u:pw@host"]) == [
        f"ENVIRONMENT=https://u:{M}@host"
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("postgres://admin:s3cret@db:5432/app", f"postgres://admin:{M}@db:5432/app"),
        ("redis://:pw@cache:6379", f"redis://:{M}@cache:6379"),
        ("http://host:8080/path", "http://host:8080/path"),
        ("https://user@host/repo.git", "https://user@host/repo.git"),
        (
            "a amqp://u:p@q and mongodb+srv://x:y@z",
            f"a amqp://u:{M}@q and mongodb+srv://x:{M}@z",
        ),
    ],
)
def test_mask_url_credentials(text: str, expected: str) -> None:
    assert mask_url_credentials(text) == expected


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ["redis-server", "--requirepass", "s3cret"],
            ["redis-server", "--requirepass", M],
        ),
        (
            ["app", "--password=abc", "--port", "80"],
            ["app", f"--password={M}", "--port", "80"],
        ),
        (["app", "--secret", "--verbose"], ["app", "--secret", "--verbose"]),
        (["app", "--auth-token"], ["app", "--auth-token"]),
        (["-e", "API_TOKEN=xyz", "PORT=80"], ["-e", f"API_TOKEN={M}", "PORT=80"]),
        (
            ["app", "--apikey", "k", "--api-key=k2"],
            ["app", "--apikey", M, f"--api-key={M}"],
        ),
        (
            ["java", "-Dspring.datasource.password=pw"],
            ["java", f"-Dspring.datasource.password={M}"],
        ),
        (["app", "--dsn", "postgres://u:p@h/db"], ["app", "--dsn", M]),
        (
            ["app", "--db-url", "postgres://u:p@h/db"],
            ["app", "--db-url", f"postgres://u:{M}@h/db"],
        ),
        (
            ["sh", "-c", "mysqld --password s3cret --user mysql"],
            ["sh", "-c", f"mysqld --password {M} --user mysql"],
        ),
        (["nginx", "-g", "daemon off;"], ["nginx", "-g", "daemon off;"]),
    ],
)
def test_mask_command_args(args: list[str], expected: list[str]) -> None:
    assert mask_command_args(args) == expected


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (
            "ENV DB_PASSWORD=secret NGINX_VERSION=1.25",
            f"ENV DB_PASSWORD={M} NGINX_VERSION={M}",
        ),
        ("ENV PATH=/usr/local/bin:$PATH", "ENV PATH=/usr/local/bin:$PATH"),
        (
            "/bin/sh -c #(nop)  ENV MYSQL_ROOT_PASSWORD supersecret",
            f"/bin/sh -c #(nop)  ENV MYSQL_ROOT_PASSWORD {M}",
        ),
        ("ENV TZ Europe/Berlin", "ENV TZ Europe/Berlin"),
        ("ARG NPM_TOKEN=abc", f"ARG NPM_TOKEN={M}"),
        (
            "RUN |2 NPM_TOKEN=abc VERSION=1 /bin/sh -c npm ci",
            f"RUN |2 NPM_TOKEN={M} VERSION={M} /bin/sh -c npm ci",
        ),
        ("RUN ./configure --prefix=/usr", "RUN ./configure --prefix=/usr"),
        (
            "RUN curl -fsSL https://user:pass@host/file",
            f"RUN curl -fsSL https://user:{M}@host/file",
        ),
        ("RUN echo 'KEY=\"a b\"'", f"RUN echo 'KEY={M}'"),
    ],
)
def test_build_step_masking(step: str, expected: str) -> None:
    assert mask_secrets_in_text(step, mask_all_assignments=True) == expected


def test_container_environment_view_masks_values_and_command() -> None:
    attrs: dict[str, object] = {
        "Config": {
            "Env": ["TZ=UTC", "POSTGRES_PASSWORD=pw", "APP_MODE=prod"],
            "Cmd": ["--requirepass", "s3cret", "--url", "redis://:pw@cache"],
            "Entrypoint": ["sh", "-c", "exec app --token abc"],
        }
    }
    environment = handlers_docker.parse_container_environment(
        SimpleNamespace(), attrs=attrs
    )
    assert environment["environment_vars"] == [
        "TZ=UTC",
        f"POSTGRES_PASSWORD={M}",
        f"APP_MODE={M}",
    ]
    assert environment["command"] == f"--requirepass {M} --url redis://:{M}@cache"
    assert environment["entrypoint"] == f"sh -c exec app --token {M}"
    assert environment["env_count"] == 3


def test_image_details_mask_env_cmd_and_healthcheck() -> None:
    image = SimpleNamespace(
        short_id=IMAGE_ID[:19],
        tags=["app:1"],
        attrs={
            "RepoTags": ["app:1"],
            "Config": {
                "Labels": {"org.opencontainers.image.source": "https://u:tok@git/x"},
                "Env": ["PATH=/bin", "SECRET_KEY=abc"],
                "Cmd": ["--password", "pw"],
                "Entrypoint": ["app"],
                "Healthcheck": {
                    "Test": ["CMD-SHELL", "curl -f http://u:p@localhost/health"]
                },
            },
        },
    )
    details = images_info_module.process_image_attrs(image)
    assert details["env_variables"] == ["PATH=/bin", f"SECRET_KEY={M}"]
    assert details["cmd"] == ["--password", M]
    assert details["entrypoint"] == ["app"]
    assert details["labels"] == {
        "org.opencontainers.image.source": f"https://u:{M}@git/x"
    }
    assert f"http://u:{M}@localhost/health" in str(details["healthcheck"])


def test_image_history_masks_build_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeDockerApi([], images=[make_image_attrs(IMAGE_ID, ["app:1"])])
    api.history_db[IMAGE_ID] = [
        {
            "Id": IMAGE_ID,
            "Created": 1_760_000_000,
            "CreatedBy": "RUN |1 GITHUB_TOKEN=ghp_x /bin/sh -c make",
            "Size": 10,
            "Comment": "",
            "Tags": None,
        }
    ]
    install_client(monkeypatch, [images_info_module], make_client(api))

    history = images_info_module.get_image_history(IMAGE_ID[:19])
    assert history is not None
    assert history[0]["created_by"] == f"RUN |1 GITHUB_TOKEN={M} /bin/sh -c make"
    assert history[0]["tags"] == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            'curl -H "Authorization: Bearer abc123" http://x',
            'curl -H "Authorization: ••••" http://x',
        ),
        (
            "curl -fsS -H 'X-Api-Key: k123' -H 'Accept: application/json' http://x",
            "curl -fsS -H 'X-Api-Key: ••••' -H 'Accept: application/json' http://x",
        ),
        (
            "wget --header='Cookie: session=abc' http://x",
            "wget --header='Cookie: ••••' http://x",
        ),
    ],
)
def test_http_header_credentials_are_masked(text: str, expected: str) -> None:
    assert mask_secrets_in_text(text) == expected


def test_header_argument_in_argv_is_masked() -> None:
    assert mask_command_args(["curl", "-H", "Proxy-Authorization: Basic Zm9v"]) == [
        "curl",
        "-H",
        "Proxy-Authorization: ••••",
    ]
