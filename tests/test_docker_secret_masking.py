"""Secrets in container/image config are never shown in clear text."""

from __future__ import annotations

import gc
import time
from collections.abc import Callable
from types import SimpleNamespace

import pytest

import pytmbot.adapters.docker.images_info as images_info_module
import pytmbot.handlers.docker_handlers.images as images_module
import pytmbot.handlers.handlers_util.docker as handlers_docker
from pytmbot.adapters.docker.utils import (
    SECRET_MASK,
    build_step_instruction,
    command_executable,
    mask_build_step,
    mask_command_args,
    mask_entrypoint_and_cmd,
    mask_environment_variables,
    mask_free_text,
    mask_healthcheck_test,
    mask_secrets_in_text,
    mask_shell_command,
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
        # A value may start with ``-``: glued with ``=`` or as the next word.
        (["mysql", "--password=-s3cret"], ["mysql", f"--password={M}"]),
        (["app", "--token", "-s3cret-x"], ["app", "--token", M]),
        (["app", "--token", "-v"], ["app", "--token", "-v"]),
        (["app", "--token", "-"], ["app", "--token", "-"]),
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


# --- program-aware masking: short options without secret-looking names --------


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["mysqld", "-p", "s3cret"], ["mysqld", "-p", M]),
        (["mysqld", "-ps3cret"], ["mysqld", f"-p{M}"]),
        (["mysqld", "-psecret"], ["mysqld", f"-p{M}"]),
        (["/usr/sbin/mysqld", "-ps3cret"], ["/usr/sbin/mysqld", f"-p{M}"]),
        (["mariadb-admin", "ping", "-ps3cret"], ["mariadb-admin", "ping", f"-p{M}"]),
        # ``-p`` alone prompts for the password; the next word is an option.
        (
            ["mysqldump", "-p", "--all-databases"],
            ["mysqldump", "-p", "--all-databases"],
        ),
        # A detached MySQL value is a database name: masked on purpose.
        (["mysql", "-p", "appdb"], ["mysql", "-p", M]),
        (
            ["curl", "-u", "user:s3cret", "http://db"],
            ["curl", "-u", f"user:{M}", "http://db"],
        ),
        (["curl", "-uuser:s3cret"], ["curl", f"-uuser:{M}"]),
        (["curl", "--user=user:s3cret"], ["curl", f"--user=user:{M}"]),
        (["curl", "-fsSu", "user:s3cret"], ["curl", "-fsSu", f"user:{M}"]),
        (
            ["curl", "--proxy-user", "p:s3cret", "-U", "q:s3cret"],
            ["curl", "--proxy-user", f"p:{M}", "-U", f"q:{M}"],
        ),
        # Without ``:`` curl prompts for the password: nothing to hide.
        (["curl", "-u", "user", "http://db"], ["curl", "-u", "user", "http://db"]),
        (["redis-cli", "-a", "s3cret", "ping"], ["redis-cli", "-a", M, "ping"]),
        (["redis-cli", "-as3cret"], ["redis-cli", f"-a{M}"]),
        (
            ["sshpass", "-p", "s3cret", "ssh", "-p", "22", "host"],
            ["sshpass", "-p", M, "ssh", "-p", "22", "host"],
        ),
        (["sshpass", "-ps3cret", "ssh", "host"], ["sshpass", f"-p{M}", "ssh", "host"]),
        (
            ["mongosh", "-u", "root", "-p", "s3cret"],
            ["mongosh", "-u", "root", "-p", M],
        ),
        (["mongodump", "-ps3cret"], ["mongodump", f"-p{M}"]),
        (
            ["mosquitto_pub", "-u", "bot", "-P", "s3cret", "-t", "x"],
            ["mosquitto_pub", "-u", "bot", "-P", M, "-t", "x"],
        ),
        (["openssl", "enc", "-k", "s3cret"], ["openssl", "enc", "-k", M]),
        (
            ["htpasswd", "-bc", "/etc/htpasswd", "admin", "s3cret"],
            ["htpasswd", "-bc", "/etc/htpasswd", "admin", M],
        ),
        (
            ["htpasswd", "-B", "-C", "10", "-b", "/etc/htpasswd", "admin", "s3cret"],
            ["htpasswd", "-B", "-C", "10", "-b", "/etc/htpasswd", "admin", M],
        ),
    ],
)
def test_program_secret_options_are_masked(
    args: list[str], expected: list[str]
) -> None:
    assert mask_command_args(args) == expected


@pytest.mark.parametrize(
    "prefix",
    [
        ["exec"],
        ["tini", "--"],
        ["tini", "-s", "-g", "--"],
        ["dumb-init", "--single-child"],
        ["gosu", "mysql"],
        ["su-exec", "mysql:mysql"],
        ["env", "-i", "TZ=UTC", "LANG=C"],
        ["sudo", "-u", "mysql", "-E"],
        ["nice", "-n", "10", "nohup", "time", "-p"],
        ["command", "-p"],
        ["/usr/bin/env", "MYSQL_HOST=db", "exec"],
    ],
)
def test_program_is_found_behind_wrappers_and_assignments(prefix: list[str]) -> None:
    assert mask_command_args([*prefix, "mysqld", "-ps3cret"]) == [
        *prefix,
        "mysqld",
        f"-p{M}",
    ]


@pytest.mark.parametrize(
    "args",
    [
        ["docker", "run", "-p", "80:80", "-u", "1000:1000", "nginx"],
        ["ssh", "-p", "22", "host"],
        ["nc", "-l", "-p", "8080"],
        ["psql", "-h", "db", "-p", "5432", "-U", "app"],
        ["redis-cli", "-h", "cache", "-p", "6379", "ping"],
        ["mysql", "-h", "db", "-P", "3306", "-u", "root"],
        ["mosquitto_sub", "-p", "1883", "-t", "x"],
        ["openssl", "rand", "-hex", "16"],
        ["htpasswd", "-c", "/etc/htpasswd", "admin"],
        ["curl", "-fsSL", "http://x"],
        ["sh", "-c", "docker run -p 80:80 -u 1000:1000 nginx"],
    ],
)
def test_ports_and_users_of_other_programs_stay_visible(args: list[str]) -> None:
    assert mask_command_args(args) == args


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ["sh", "-c", "mysqld -ps3cret && curl -u user:s3cret http://db"],
            ["sh", "-c", f"mysqld -p{M} && curl -u user:{M} http://db"],
        ),
        (["sh", "-c", "mysql -p s3cret"], ["sh", "-c", f"mysql -p {M}"]),
        (
            ["/bin/bash", "-o", "pipefail", "-ec", "exec mysqld -p's3cret'"],
            ["/bin/bash", "-o", "pipefail", "-ec", f"exec mysqld -p'{M}'"],
        ),
        (
            ["tini", "--", "sh", "-c", "redis-cli -as3cret"],
            ["tini", "--", "sh", "-c", f"redis-cli -a{M}"],
        ),
        (["sh", "-c", "--", "mysql -ps3cret"], ["sh", "-c", "--", f"mysql -p{M}"]),
    ],
)
def test_shell_scripts_in_argv_are_masked(args: list[str], expected: list[str]) -> None:
    assert mask_command_args(args) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mysqld -p s3cret", f"mysqld -p {M}"),
        (
            "sh -c 'mysqld -ps3cret && curl -u user:s3cret http://db'",
            f"sh -c 'mysqld -p{M} && curl -u user:{M} http://db'",
        ),
        ('bash -c "mysql -p s3cret"', f'bash -c "mysql -p {M}"'),
        (
            "MYSQL_HOST=db exec gosu mysql mysqld -ps3cret; echo done",
            f"MYSQL_HOST=db exec gosu mysql mysqld -p{M}; echo done",
        ),
        (
            'mysql -uroot -p"s3cret" -e "SELECT 1; SELECT 2"',
            f'mysql -uroot -p"{M}" -e "SELECT 1; SELECT 2"',
        ),
        (
            "curl -fsS -u 'user:s3cret' http://x || exit 1",
            f"curl -fsS -u 'user:{M}' http://x || exit 1",
        ),
        (
            '[ "$(redis-cli -a s3cret ping)" = PONG ]',
            f'[ "$(redis-cli -a {M} ping)" = PONG ]',
        ),
        (
            "echo `mysql -ps3cret -e 'select 1'`",
            f"echo `mysql -p{M} -e 'select 1'`",
        ),
        (
            "htpasswd -Bbn admin s3cret > /etc/nginx/.htpasswd",
            f"htpasswd -Bbn admin {M} > /etc/nginx/.htpasswd",
        ),
        (
            "mysqladmin ping -ps3cret>/dev/null 2>&1 &",
            f"mysqladmin ping -p{M}>/dev/null 2>&1 &",
        ),
        ("mysqladmin ping -p 2>/dev/null", "mysqladmin ping -p 2>/dev/null"),
        ("ssh -p 22 host # mysql -ps3cret", "ssh -p 22 host # mysql -ps3cret"),
        ("nginx -g 'daemon off;'", "nginx -g 'daemon off;'"),
        ("x=$(mysql -ps3cret -N)", f"x=$(mysql -p{M} -N)"),
        ("mysql -p\\ s3cret", f"mysql -p{M}"),
        # Quotes inside the option itself are dropped rather than parsed.
        ('mysql -"p"s3cret', f"mysql -p{M}"),
        (
            'echo "say \\"hi\\" `mysql -ps3cret`"',
            f'echo "say \\"hi\\" `mysql -p{M}`"',
        ),
    ],
)
def test_shell_commands_keep_their_formatting(text: str, expected: str) -> None:
    assert mask_shell_command(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mysql --password=-s3cret", f"mysql --password={M}"),
        ("app --token=--s3cret", f"app --token={M}"),
        ("app --api-key -s3cret --port 80", f"app --api-key {M} --port 80"),
        # ``-x``, ``--long`` and ``-`` after the flag are the next options.
        ("mysql --password -h db", "mysql --password -h db"),
        ("app --secret --verbose", "app --secret --verbose"),
        ("app --token - <file", "app --token - <file"),
    ],
)
def test_flag_values_starting_with_a_dash(text: str, expected: str) -> None:
    assert mask_shell_command(text) == expected
    assert mask_free_text(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Program options with a required value take a ``-`` word as the value.
        ("redis-cli -a -s3cret ping", f"redis-cli -a {M} ping"),
        ("sshpass -p -s3cret ssh host", f"sshpass -p {M} ssh host"),
        ("mysql -p -h db", "mysql -p -h db"),
    ],
)
def test_program_option_values_starting_with_a_dash(text: str, expected: str) -> None:
    assert mask_shell_command(text) == expected
    assert mask_command_args(text.split()) == expected.split()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # An unclosed quote: the rest is split without honoring quotes.
        ("mysql -p'unclosed s3cret", f"mysql -p{M} s3cret"),
        ("don't mysql --password s3cret", f"don't mysql --password {M}"),
        ('echo "unclosed $(mysql -ps3cret', f'echo "unclosed $(mysql -p{M}'),
        ("echo it's; mysql -ps3cret", f"echo it's; mysql -p{M}"),
        (
            "mysql -pone; echo it's && redis-cli -a two",
            f"mysql -p{M}; echo it's && redis-cli -a {M}",
        ),
        (
            "cat <<EOF > /etc/motd\nit's ready\nEOF\nmysqladmin -p s3cret ping",
            f"cat <<EOF > /etc/motd\nit's ready\nEOF\nmysqladmin -p {M} ping",
        ),
        ('sh -c "mysql -ps3cret', f'sh -c "mysql -p{M}'),
    ],
)
def test_unclosed_quotes_keep_the_program_rules(text: str, expected: str) -> None:
    assert mask_shell_command(text) == expected


def test_unclosed_quotes_in_image_history_keep_the_program_rules() -> None:
    step = "RUN /bin/sh -c echo it's && mysql -uroot -ps3cret # buildkit"
    assert mask_build_step(step) == (
        f"RUN /bin/sh -c echo it's && mysql -uroot -p{M} # buildkit"
    )


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (
            "RUN |1 DB_PASS=x /bin/sh -c mysql -uroot -ps3cret # buildkit",
            f"RUN |1 DB_PASS={M} /bin/sh -c mysql -uroot -p{M} # buildkit",
        ),
        (
            "/bin/sh -c curl -u admin:s3cret http://x && mysqladmin -p s3cret ping",
            f"/bin/sh -c curl -u admin:{M} http://x && mysqladmin -p {M} ping",
        ),
        (
            "RUN --network=none /bin/sh -c mysql -ps3cret",
            f"RUN --network=none /bin/sh -c mysql -p{M}",
        ),
        ('CMD ["mysqld" "-ps3cret"]', f'CMD ["mysqld" "-p{M}"]'),
        (
            '/bin/sh -c #(nop)  CMD ["mysqld", "-ps3cret"]',
            f'/bin/sh -c #(nop)  CMD ["mysqld", "-p{M}"]',
        ),
        (
            'HEALTHCHECK &{["CMD-SHELL" "mysqladmin ping -ps3cret"] "10s" "5s"}',
            f'HEALTHCHECK &{{["CMD-SHELL" "mysqladmin ping -p{M}"] "10s" "5s"}}',
        ),
        ("ENV TZ Europe/Berlin", "ENV TZ Europe/Berlin"),
    ],
)
def test_image_history_steps_are_masked(step: str, expected: str) -> None:
    assert mask_build_step(step) == expected


@pytest.mark.parametrize(
    ("test", "expected"),
    [
        (
            ["CMD", "mysqladmin", "ping", "-ps3cret"],
            ["CMD", "mysqladmin", "ping", f"-p{M}"],
        ),
        (
            ["CMD-SHELL", "redis-cli -a s3cret ping | grep PONG"],
            ["CMD-SHELL", f"redis-cli -a {M} ping | grep PONG"],
        ),
        (["NONE"], ["NONE"]),
    ],
)
def test_healthcheck_tests_are_masked(test: list[str], expected: list[str]) -> None:
    assert mask_healthcheck_test(test) == expected


@pytest.mark.parametrize(
    ("entrypoint", "cmd", "expected"),
    [
        # Cmd extends the Entrypoint program ...
        (["mysqld"], ["-ps3cret"], (["mysqld"], [f"-p{M}"])),
        (["redis-cli", "-a"], ["s3cret", "ping"], (["redis-cli", "-a"], [M, "ping"])),
        # ... and entrypoint scripts run Cmd as a command of its own.
        (
            ["docker-entrypoint.sh"],
            ["mysqld", "-ps3cret"],
            (["docker-entrypoint.sh"], ["mysqld", f"-p{M}"]),
        ),
        ([], ["curl", "-u", "a:s3cret"], ([], ["curl", "-u", f"a:{M}"])),
    ],
)
def test_entrypoint_and_cmd_are_masked_as_one_command_line(
    entrypoint: list[str],
    cmd: list[str],
    expected: tuple[list[str], list[str]],
) -> None:
    assert mask_entrypoint_and_cmd(entrypoint, cmd) == expected


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["mysqld", f"-p{M}"], "mysqld"),
        (
            ["/usr/local/bin/docker-entrypoint.sh"],
            "/usr/local/bin/docker-entrypoint.sh",
        ),
        (["TZ=UTC curl -f http://localhost/health"], "curl"),
        (["mysqld -ps3cret"], "mysqld"),
        (["--requirepass", M], None),
        ([], None),
    ],
)
def test_command_executable(arguments: list[str], expected: str | None) -> None:
    assert command_executable(arguments) == expected


def test_health_output_and_state_error_are_masked() -> None:
    attrs: dict[str, object] = {
        "State": {
            "Status": "exited",
            "Error": 'exec: "mysqld --password=s3cret": not found',
            "Health": {
                "Status": "unhealthy",
                "Log": [
                    {"End": "2026-10-19T00:00:00Z", "Output": "password=s3cret\nmore"}
                ],
            },
        }
    }
    runtime = handlers_docker.parse_container_runtime_info(SimpleNamespace(), attrs)
    basic = handlers_docker.parse_container_basic_info(SimpleNamespace(), attrs)

    assert runtime["health_last_log"] == f"password={M}"
    expected_error = f'exec: "mysqld --password={M}": not found'
    assert runtime["state_error"] == basic["state_error"] == expected_error


def test_quoted_commands_in_errors_and_probe_output_get_program_rules() -> None:
    error = 'exec: "mysqladmin -uroot -pS3cretPw ping": executable file not found'
    attrs: dict[str, object] = {
        "State": {
            "Status": "created",
            "Error": error,
            "Health": {
                "Status": "unhealthy",
                "Log": [{"Output": "sh: 'redis-cli -a S3cretPw ping' failed"}],
            },
        }
    }
    runtime = handlers_docker.parse_container_runtime_info(SimpleNamespace(), attrs)
    basic = handlers_docker.parse_container_basic_info(SimpleNamespace(), attrs)

    expected_error = f'exec: "mysqladmin -uroot -p{M} ping": executable file not found'
    assert runtime["state_error"] == basic["state_error"] == expected_error
    assert runtime["health_last_log"] == f"sh: 'redis-cli -a {M} ping' failed"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            'exec: "mysqladmin -uroot -pS3cretPw ping": not found',
            f'exec: "mysqladmin -uroot -p{M} ping": not found',
        ),
        ("can't connect: password=x", f"can't connect: password={M}"),
        ('error: "curl -u a:b http://x"', f'error: "curl -u a:{M} http://x"'),
        ("plain text without commands", "plain text without commands"),
    ],
)
def test_mask_free_text(text: str, expected: str) -> None:
    assert mask_free_text(text) == expected


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        ('CMD ["app" "--api" "sk-abcdef"]', "CMD"),
        ("RUN |1 TOKEN=x /bin/sh -c make # buildkit", "RUN"),
        ("COPY file:abc in /app ", "COPY"),
        ('/bin/sh -c #(nop)  ENTRYPOINT ["/start"]', "ENTRYPOINT"),
        ("/bin/sh -c apt-get install -y curl", "RUN"),
        ("|2 A=1 B=2 /bin/sh -c make", "RUN"),
        ("bazel build //app:image", None),
        ("", None),
    ],
)
def test_build_step_instruction(step: str, expected: str | None) -> None:
    assert build_step_instruction(step) == expected


def test_container_environment_keeps_executables_for_non_admin_views() -> None:
    attrs: dict[str, object] = {
        "Config": {
            "Entrypoint": ["docker-entrypoint.sh"],
            "Cmd": ["mysqld", "-ps3cret"],
        }
    }
    environment = handlers_docker.parse_container_environment(
        SimpleNamespace(), attrs=attrs
    )
    assert environment["entrypoint"] == "docker-entrypoint.sh"
    assert environment["command"] == f"mysqld -p{M}"

    # With an Entrypoint, Cmd only holds its arguments.
    hidden = handlers_docker.hide_command_arguments({"environment": environment})
    assert hidden["environment"] == {
        **environment,
        "entrypoint": "docker-entrypoint.sh",
        "command": "hidden",
    }


@pytest.mark.parametrize(
    ("entrypoint", "cmd", "expected"),
    [
        (
            ["docker-entrypoint.sh"],
            ["mysqld", "-ps3cret"],
            (["docker-entrypoint.sh"], ["hidden"]),
        ),
        (
            ["/app/server", "--license-file"],
            ["ghp_AbC123"],
            (["/app/server"], ["hidden"]),
        ),
        ([], ["mysqld", "-ps3cret"], ([], ["mysqld"])),
        ([], ["--requirepass", "x"], ([], ["hidden"])),
        (["redis-server"], [], (["redis-server"], [])),
        ([], [], ([], [])),
    ],
)
def test_command_line_executables(
    entrypoint: list[str],
    cmd: list[str],
    expected: tuple[list[str], list[str]],
) -> None:
    assert handlers_docker.command_line_executables(entrypoint, cmd) == expected


def test_image_view_without_arguments_hides_cmd_after_an_entrypoint() -> None:
    image: dict[str, object] = {
        "entrypoint": ["/app/server", "--license-file"],
        "cmd": ["ghp_AbC123"],
        "shell": ["/bin/sh", "-c"],
        "healthcheck": "test=CMD curl -u a:b",
        "healthcheck_without_arguments": "test=CMD curl",
    }
    view = images_module._without_command_arguments(image)  # noqa: SLF001
    assert {key: view[key] for key in image if key in view} == {
        "entrypoint": ["/app/server"],
        "cmd": ["hidden"],
        "shell": ["/bin/sh"],
        "healthcheck": "test=CMD curl",
        "healthcheck_without_arguments": "test=CMD curl",
    }


def test_cmd_holding_only_arguments_is_hidden_from_non_admins() -> None:
    attrs: dict[str, object] = {
        "Config": {"Entrypoint": ["redis-server"], "Cmd": ["--requirepass", "x"]}
    }
    environment = handlers_docker.parse_container_environment(
        SimpleNamespace(), attrs=attrs
    )
    assert environment["command_executable"] == "hidden"
    assert environment["entrypoint_executable"] == "redis-server"
    assert handlers_docker.hide_command_arguments({"name": "x"}) == {"name": "x"}


def test_image_details_keep_executables_for_non_admin_views() -> None:
    image = SimpleNamespace(
        short_id=IMAGE_ID[:19],
        tags=["db:1"],
        attrs={
            "RepoTags": ["db:1"],
            "Comment": "built with --password s3cret",
            "Config": {
                "Entrypoint": ["docker-entrypoint.sh"],
                "Cmd": ["mysqld", "-ps3cret"],
                "Shell": ["/bin/bash", "-o", "pipefail", "-c"],
                "Healthcheck": {
                    "Test": ["CMD-SHELL", "mysqladmin ping -ps3cret"],
                    "Interval": 10_000_000_000,
                },
            },
        },
    )
    details = images_info_module.process_image_attrs(image)
    assert details["cmd"] == ["mysqld", f"-p{M}"]
    assert details["shell"] == ["/bin/bash", "-o", "pipefail", "-c"]
    assert details["comment"] == f"built with --password {M}"
    assert details["healthcheck"] == (
        f"test=CMD-SHELL mysqladmin ping -p{M}; interval=10.0s"
    )
    assert details["healthcheck_without_arguments"] == (
        "test=CMD-SHELL mysqladmin; interval=10.0s"
    )


def test_image_history_masks_program_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeDockerApi([], images=[make_image_attrs(IMAGE_ID, ["app:1"])])
    api.history_db[IMAGE_ID] = [
        {
            "Id": IMAGE_ID,
            "Created": 1_760_000_000,
            "CreatedBy": "RUN /bin/sh -c mysql -uroot -ps3cret < /init.sql # buildkit",
            "Size": 10,
            "Comment": "token=s3cret",
            "Tags": None,
        }
    ]
    install_client(monkeypatch, [images_info_module], make_client(api))

    history = images_info_module.get_image_history(IMAGE_ID[:19])
    assert history is not None
    assert history[0]["created_by"] == (
        f"RUN /bin/sh -c mysql -uroot -p{M} < /init.sql # buildkit"
    )
    assert history[0]["comment"] == f"token={M}"


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        (
            ["sh", "-c", "mysql -ps3cret --token=abc"],
            ["sh", "-c", f"mysql -p{M} --token={M}"],
        ),
        (
            ["sh", "-c", "curl -u u:s3cret http://x/?token=x"],
            ["sh", "-c", f"curl -u u:{M} http://x/?token={M}"],
        ),
        (
            ["sh", "-c", "redis-cli -a s3cret; echo PASSWORD=x"],
            ["sh", "-c", f"redis-cli -a {M}; echo PASSWORD={M}"],
        ),
    ],
)
def test_cmd_keeps_its_own_program_masks_after_an_entrypoint(
    cmd: list[str], expected: list[str]
) -> None:
    entrypoint = ["/entrypoint.sh"]
    assert mask_entrypoint_and_cmd(entrypoint, cmd) == (entrypoint, expected)

    config: dict[str, object] = {"Config": {"Entrypoint": entrypoint, "Cmd": cmd}}
    environment = handlers_docker.parse_container_environment(
        SimpleNamespace(), attrs=config
    )
    image = SimpleNamespace(short_id=IMAGE_ID[:19], tags=["app:1"], attrs=config)
    assert environment["command"] == " ".join(expected)
    assert images_info_module.process_image_attrs(image)["cmd"] == expected


# Text that image and container authors control must not stall the bot.
_ADVERSARIAL_SMALL = 4 * 1024
_ADVERSARIAL_LARGE = 4 * _ADVERSARIAL_SMALL
_ADVERSARIAL_UNITS = (
    "X-",
    ".-a",
    "-a",
    "a.",
    "a-",
    "a=",
    "://",
    "x://a:",
    "Authorization:",
    "sh -c ",
    "env ",
    "A=1 ",
    "a\n",
    "|1 ",
    "<",
    '"',
    "'",
    "`",
    "$(",
    '["a" ',
    "ENV a ",
    "\\",
)
_MASKING_ENTRY_POINTS: dict[str, Callable[[str], object]] = {
    "mask_secrets_in_text": lambda text: mask_secrets_in_text(
        text, mask_all_assignments=True
    ),
    "mask_url_credentials": mask_url_credentials,
    "mask_environment_variables": lambda text: mask_environment_variables(
        [f"PATH={text}", f"URL={text}"]
    ),
    "mask_command_args": lambda text: mask_command_args([text, *text.split()]),
    "mask_shell_command": mask_shell_command,
    "mask_build_step": mask_build_step,
    "mask_healthcheck_test": lambda text: mask_healthcheck_test(["CMD-SHELL", text]),
    "mask_entrypoint_and_cmd": lambda text: mask_entrypoint_and_cmd(
        text.split()[:1], [text]
    ),
    "mask_free_text": mask_free_text,
    "command_executable": lambda text: command_executable([text]),
    "build_step_instruction": build_step_instruction,
}


def _masking_seconds(mask: Callable[[str], object], unit: str, size: int) -> float:
    """Best of three runs with the garbage collector paused, to keep noise out."""
    text = (unit * (size // len(unit) + 1))[:size]
    timings: list[float] = []
    gc.disable()
    try:
        for _ in range(3):
            started = time.perf_counter()
            mask(text)
            timings.append(time.perf_counter() - started)
    finally:
        gc.enable()
    return min(timings)


@pytest.mark.parametrize("entry_point", sorted(_MASKING_ENTRY_POINTS))
def test_masking_stays_linear_on_adversarial_input(entry_point: str) -> None:
    # Compare growth, not wall time, so slow CI runners and coverage tracing
    # do not matter: 4x more input costs ~4x for linear work, ~16x for quadratic.
    mask = _MASKING_ENTRY_POINTS[entry_point]
    for unit in _ADVERSARIAL_UNITS:
        small = _masking_seconds(mask, unit, _ADVERSARIAL_SMALL)
        large = _masking_seconds(mask, unit, _ADVERSARIAL_LARGE)
        assert large < max(10 * small, 0.05), (
            f"{entry_point} on {unit!r}: {small:.3f}s -> {large:.3f}s"
        )
        assert large < 10.0, f"{entry_point} took {large:.2f}s on {unit!r}"
