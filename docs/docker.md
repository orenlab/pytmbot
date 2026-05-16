# Docker Runtime

This document describes the Docker image and runtime behavior implemented in the repository.

Source of truth:

- `Dockerfile`
- `entrypoint.sh`
- `.github/workflows/release-to-docker-ci.yml`
- `.github/workflows/rebuild_supported_tags.yml`
- `.github/workflows/development_image_ci.yml`

## Supported Model

Docker and Docker Compose are the only supported deployment models.

Published image:

- `orenlab/pytmbot`

Stable public tags:

- `0.3.2` for an exact release image
- `0.3` for the current supported stable line
- `stable` as the stable-channel alias
- `latest` as an alias of `stable`

Additional tags:

- `0.3-rYYYYMMDD` for dated weekly stable-line rebuilds
- `edge-<branch>` and `edge-sha-<gitsha>` for development images from `feat/*` and `fix/*` branches

See [release_policy.md](release_policy.md) for the full contract.

Supported image architectures:

- `linux/amd64`
- `linux/arm64`

## Runtime Defaults

- base image: Ubuntu
- container user: `pytmbot`
- user/group id: `1001:1001`
- working directory: `/opt/app`
- default timezone env: `TZ=UTC`
- built-in Docker `HEALTHCHECK` calls `./entrypoint.sh --health_check`

## Required And Optional Mounts

Required for normal bot startup:

- config file mounted to `/opt/app/pytmbot.yaml`

Required for Docker-management features:

- `/var/run/docker.sock:/var/run/docker.sock:ro`

Optional:

- certificate files referenced by `webhook_config.cert` and `webhook_config.cert_key`

## Environment Variables

Current runtime-relevant environment variables:

| Variable               | Default                  | Purpose                                                            |
|------------------------|--------------------------|--------------------------------------------------------------------|
| `TZ`                   | `UTC`                    | Container timezone                                                 |
| `STRICT_DOCKER_ACCESS` | `False`                  | Fails startup when Docker access is unavailable if set truthy      |
| `PYTMBOT_CONFIG_PATH`  | unset                    | Overrides the config path when needed                              |
| `PYTMBOT_STATE_DIR`    | `~/.local/state/pytmbot` | Overrides runtime state path                                       |
| `XDG_STATE_HOME`       | unset                    | Base directory for runtime state when `PYTMBOT_STATE_DIR` is unset |

## Runtime State

Runtime state is used for TOTP replay protection and persisted webhook rate-limit bans.

State path resolution:

- `PYTMBOT_STATE_DIR` when set
- otherwise `$XDG_STATE_HOME/pytmbot` when `XDG_STATE_HOME` is set
- otherwise `~/.local/state/pytmbot`

When using a read-only root filesystem, set `PYTMBOT_STATE_DIR` to a writable private tmpfs or volume, for example
`/run/pytmbot`.

## Minimal Run

```bash
docker run -d \
  --name pytmbot \
  --restart on-failure \
  -v /path/to/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:stable --mode prod
```

## Minimal Compose

```yaml
services:
  pytmbot:
    image: orenlab/pytmbot:stable
    container_name: pytmbot
    restart: on-failure
    environment:
      TZ: UTC
    volumes:
      - ./pytmbot.yaml:/opt/app/pytmbot.yaml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command: --mode prod
```

## Webhook Deployment Notes

- enable with `--webhook true` or bare `--webhook` in the container entrypoint
- set `--socket_host 0.0.0.0` when the webhook listener must bind outside localhost
- `webhook_config.local_port` must be `>= 1024`
- direct public exposure is not the intended model; use a reverse proxy with TLS

## Diagnostics

Generate a TOTP salt:

```bash
docker run --rm orenlab/pytmbot:stable --salt
```

Check Docker socket access:

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  orenlab/pytmbot:stable --check-docker
```

Read container logs:

```bash
docker logs -f pytmbot
```

## Hardening Guidance

Recommended runtime flags for production:

- `--read-only`
- `--security-opt no-new-privileges`
- `--cap-drop ALL`
- read-only bind mount for `/var/run/docker.sock`
- writable private tmpfs or volume for `PYTMBOT_STATE_DIR`

Important:

- Docker socket access is privileged host control.
- If Docker access must be mandatory, set `STRICT_DOCKER_ACCESS=True`.

## Related Docs

- [installation.md](installation.md)
- [release_policy.md](release_policy.md)
- [settings.md](settings.md)
- [bot_cli_args.md](bot_cli_args.md)
- [webhook.md](webhook.md)
- [security.md](security.md)
