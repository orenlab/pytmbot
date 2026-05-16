# pyTMBot Docker Image

[![Docker Pulls](https://img.shields.io/docker/pulls/orenlab/pytmbot?style=flat-square&logo=docker&logoColor=white&label=pulls&color=1a7fd4&labelColor=2b3137)](https://hub.docker.com/r/orenlab/pytmbot/)
[![Image Size](https://img.shields.io/docker/image-size/orenlab/pytmbot?style=flat-square&logo=docker&logoColor=white&label=image%20size&color=1a7fd4&labelColor=2b3137)](https://hub.docker.com/r/orenlab/pytmbot/)
[![Release](https://img.shields.io/github/v/release/orenlab/pytmbot?style=flat-square&logo=github&logoColor=white&color=1a7fd4&labelColor=2b3137)](https://github.com/orenlab/pytmbot/releases)
[![License](https://img.shields.io/github/license/orenlab/pytmbot?style=flat-square&logo=opensourceinitiative&logoColor=white&color=1a7fd4&labelColor=2b3137)](https://github.com/orenlab/pytmbot/blob/master/LICENSE)

Secure multi-arch Docker image for pyTMBot — a Telegram bot for Docker operations, host monitoring, health checks, and
optional plugins.

## Quick Reference

- Maintained by: [OrenLab](https://github.com/orenlab)
- Source code and issues: [github.com/orenlab/pytmbot](https://github.com/orenlab/pytmbot)
- Image: `orenlab/pytmbot`
- Supported architectures: `linux/amd64`, `linux/arm64`
- Base image: Ubuntu `24.04`
- Runtime user: `pytmbot` (uid:gid `1001:1001`)

## Supported Tags

Stable public tags:

| Tag      | Description                   |
|----------|-------------------------------|
| `0.3.0`  | Exact immutable release image |
| `0.3`    | Current supported stable line |
| `stable` | Stable channel alias          |
| `latest` | Alias of `stable`             |

Additional tags:

| Tag                 | Description                                   |
|---------------------|-----------------------------------------------|
| `0.3-rYYYYMMDD`     | Dated weekly rebuild of the stable line       |
| `edge-<branch>`     | Development image for a feature or fix branch |
| `edge-sha-<gitsha>` | Development image pinned to a branch commit   |

Recommended: use `0.3.0` for reproducible production rollouts, `stable` for the supported channel. Do not use `edge-*`
tags in production.

## Image Features

- Non-root runtime user
- Built-in Docker `HEALTHCHECK`
- Multi-stage build with `uv` and locked Python dependencies
- OCI labels, SBOM, and provenance on release images
- Weekly base-image and OS-package refreshes for floating stable tags

## Security Guidance

Recommended runtime hardening:

```
--read-only
--security-opt no-new-privileges
--cap-drop ALL
```

- Docker socket access is equivalent to privileged host control. Mount `/var/run/docker.sock` only if you need Docker
  management features.
- For webhook mode, expose the app through a reverse proxy with TLS termination.

## Requirements

- Docker Engine 20.10+
- Docker Compose v2 recommended
- Telegram bot token from `@BotFather`
- A valid `pytmbot.yaml` configuration file

## Quick Start

Generate a TOTP salt:

```bash
docker run --rm orenlab/pytmbot:stable --salt
```

Create a config directory and download the sample config:

```bash
mkdir -p /etc/pytmbot
curl -L -o /etc/pytmbot/pytmbot.yaml \
  https://raw.githubusercontent.com/orenlab/pytmbot/master/pytmbot.yaml.sample
```

Minimal production run:

```bash
docker run -d \
  --name pytmbot \
  --restart on-failure \
  -e TZ=UTC \
  -v /etc/pytmbot/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --read-only \
  --security-opt no-new-privileges \
  --cap-drop ALL \
  --pid host \
  orenlab/pytmbot:stable --mode prod
```

For pinned rollouts, replace `stable` with `0.3.0`. To enforce Docker socket availability on startup, add
`-e STRICT_DOCKER_ACCESS=True`.

## Docker Compose Example

```yaml
services:
  pytmbot:
    image: orenlab/pytmbot:stable
    container_name: pytmbot
    restart: on-failure
    environment:
      TZ: UTC
    volumes:
      - /etc/pytmbot/pytmbot.yaml:/opt/app/pytmbot.yaml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    security_opt:
      - no-new-privileges:true
    read_only: true
    cap_drop:
      - ALL
    pid: host
    tmpfs:
      - /tmp:noexec,nosuid,nodev,size=100m,uid=1001,gid=1001
      - /var/tmp:noexec,nosuid,nodev,size=50m,uid=1001,gid=1001
    command: [ "--mode", "prod" ]
```

## Configuration Overview

Required top-level sections in `pytmbot.yaml`:

| Section          | Key fields                                            |
|------------------|-------------------------------------------------------|
| `config_version` | —                                                     |
| `bot_token`      | `prod_token`                                          |
| `access_control` | `allowed_user_ids`, `allowed_admins_ids`, `auth_salt` |
| `chat_id`        | `global_chat_id`                                      |
| `docker`         | `host`                                                |

Optional sections: `webhook_config`, `plugins_config`, `influxdb`.

Notes:

- `plugins_config.monitor` also requires the top-level `influxdb` section.
- Webhook mode requires a valid `webhook_config`.

## Runtime Flags

| Flag                                                       | Description                          |
|------------------------------------------------------------|--------------------------------------|
| `--mode dev\|prod`                                         | Runtime mode                         |
| `--log-level TRACE\|DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL` | Log verbosity                        |
| `--log-format human\|json`                                 | Log format                           |
| `--plugins monitor outline`                                | Enable plugins                       |
| `--webhook`                                                | Enable webhook mode                  |
| `--socket_host 0.0.0.0`                                    | Bind address for webhook listener    |
| `--health_check`                                           | Run health check and exit            |
| `--check-docker`                                           | Verify Docker socket access and exit |
| `--salt`                                                   | Generate a TOTP salt and exit        |
| `--debug`                                                  | Enable debug output                  |

Examples:

```bash
# Verify Docker socket access
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:stable --check-docker

# Run with plugins
docker run -d \
  --name pytmbot \
  -v /etc/pytmbot/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:stable --mode prod --plugins monitor outline
```

## Webhook Notes

- Polling is the simplest deployment mode — no public endpoint required.
- Webhook mode should be placed behind a reverse proxy with TLS termination.
- Use `--socket_host 0.0.0.0` for containerized webhook listeners.
- `webhook_config.local_port` must be `>= 1024`.

## Upgrade Policy

- Exact release tags (`0.3.0`) are immutable.
- Floating tags (`0.3`, `stable`, `latest`) can move forward.
- Weekly rebuilds refresh the Ubuntu base image and installed OS packages.
- Python dependency updates require a committed `uv.lock` change and a new release.

## Documentation

- [Project repository](https://github.com/orenlab/pytmbot)
- [Runtime documentation](https://github.com/orenlab/pytmbot/blob/master/docs/docker.md)
- [Settings reference](https://github.com/orenlab/pytmbot/blob/master/docs/settings.md)
- [CLI reference](https://github.com/orenlab/pytmbot/blob/master/docs/bot_cli_args.md)
- [Release policy](https://github.com/orenlab/pytmbot/blob/master/docs/release_policy.md)

## License

Released under the [MIT License](https://github.com/orenlab/pytmbot/blob/master/LICENSE).
