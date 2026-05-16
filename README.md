<div align="center">

  <picture>
    <source
      media="(prefers-color-scheme: dark)"
      srcset="https://raw.githubusercontent.com/orenlab/pytmbot/master/docs/assets/pytmbot-wordmark-dark.svg"
    >
    <source
      media="(prefers-color-scheme: light)"
      srcset="https://raw.githubusercontent.com/orenlab/pytmbot/master/docs/assets/pytmbot-wordmark.svg"
    >
    <img
      alt="pyTMbot"
      src="https://raw.githubusercontent.com/orenlab/pytmbot/master/docs/assets/pytmbot-wordmark.svg"
      width="280"
    >
  </picture>

  <p>Docker-first Telegram bot for container management, server monitoring, and secure remote administration.</p>

  <p>
    <a href="https://hub.docker.com/r/orenlab/pytmbot/"><img src="https://img.shields.io/docker/pulls/orenlab/pytmbot?style=flat-square&logo=docker&logoColor=white&label=pulls&color=1a7fd4&labelColor=2b3137" alt="Docker Pulls"></a>
    <a href="https://hub.docker.com/r/orenlab/pytmbot/"><img src="https://img.shields.io/docker/image-size/orenlab/pytmbot?style=flat-square&logo=docker&logoColor=white&label=image%20size&color=1a7fd4&labelColor=2b3137" alt="Image Size"></a>
    <a href="https://github.com/orenlab/pytmbot/releases"><img src="https://img.shields.io/github/v/release/orenlab/pytmbot?style=flat-square&logo=github&logoColor=white&color=1a7fd4&labelColor=2b3137" alt="Release"></a>
    <a href="LICENSE"><img src="https://img.shields.io/github/license/orenlab/pytmbot?style=flat-square&logo=opensourceinitiative&logoColor=white&color=1a7fd4&labelColor=2b3137" alt="License"></a>
  </p>

</div>

---

---

## Overview

**pyTMbot** lets you manage Docker containers and monitor server health directly from Telegram — without opening a
terminal. It supports both **polling** and **webhook** modes, enforces access control with allowlists and TOTP-based
2FA, and extends via a modular plugin system.

Built
on [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI), [psutil](https://github.com/giampaolo/psutil),
and [docker-py](https://github.com/docker/docker-py).

---

## Quick Start

### 1. Prepare your config

Create `/etc/pytmbot/pytmbot.yaml` following the [settings guide](docs/settings.md).

### 2. Deploy with Docker Compose

```yaml
services:
  pytmbot:
    image: orenlab/pytmbot:stable
    container_name: pytmbot
    restart: on-failure
    environment:
      TZ: UTC
      PYTMBOT_STATE_DIR: /run/pytmbot
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /etc/pytmbot/pytmbot.yaml:/opt/app/pytmbot.yaml:ro
    security_opt:
      - no-new-privileges:true
    read_only: true
    cap_drop:
      - ALL
    pid: host
    tmpfs:
      - /run/pytmbot:noexec,nosuid,nodev,size=10m,uid=1001,gid=1001
    command: [ "--log-level", "INFO" ]
```

```bash
docker compose up -d
```

For a hardened production setup with resource limits, tmpfs, network isolation, and health checks —
see [docs/docker.md](docs/docker.md).

---

## Features

### Docker management

- Start, stop, restart, inspect, and browse containers
- View logs with pagination and export
- Manage images: metadata, tag details, update checks against Docker Hub
- Browse volumes and networks (optionally protected by 2FA)
- Inline Telegram interactions for faster operations

### Server monitoring

- Live summary pages for system and Docker state with refresh
- Per-metric views: CPU, memory, swap, disk, network, sensors, fans, users
- Load average, uptime, filesystem, and process insights
- Startup and component-level health checks

### Security

- Access restricted by `allowed_user_ids` and `allowed_admins_ids`
- TOTP-based 2FA for sensitive actions
- Rate limiting and duplicate update protection
- Webhook deployments with trusted proxy / IP validation
- Secure message deletion scheduling
- Improved credential masking in structured logs

### Extensibility

- Plugin system for custom modules with minimal configuration
- Jinja2-based templating for bot responses

---

## Plugins

Two plugins are included out of the box:

**Monitor Plugin** — push notifications for CPU, memory, disk, temperature, and container/image state changes.

**Outline VPN Plugin** — monitor your [Outline VPN](https://getoutline.org/) server from Telegram.

See [docs/plugins.md](docs/plugins.md) for the plugin API and configuration reference.

---

## Requirements

| Component      | Requirement                       |
|----------------|-----------------------------------|
| Python         | `>=3.12,<4` (CI: 3.12-3.14)       |
| Docker Engine  | 20.10+                            |
| Docker Compose | v2.0+                             |
| Docker socket  | required for container management |

## Operating modes

**Polling** — simplest deployment; no HTTPS or public endpoint required.

**Webhook** — lower latency; requires a public hostname for Telegram `setWebhook`.
See [docs/webhook.md](docs/webhook.md).

---

## Documentation

Full docs: [orenlab.github.io/pytmbot](https://orenlab.github.io/pytmbot/)

| Guide                                        | Description                           |
|----------------------------------------------|---------------------------------------|
| [Installation](docs/installation.md)         | Step-by-step setup                    |
| [Docker](docs/docker.md)                     | Docker-specific deployment            |
| [Settings](docs/settings.md)                 | `pytmbot.yaml` reference              |
| [Commands](docs/commands.md)                 | All bot commands                      |
| [Webhook mode](docs/webhook.md)              | Webhook setup and proxy config        |
| [Security](docs/security.md)                 | Hardening and threat model            |
| [Access control & 2FA](docs/auth_control.md) | Allowlists and TOTP                   |
| [Health system](docs/health.md)              | Startup and runtime checks            |
| [Plugins](docs/plugins.md)                   | Plugin API and bundled plugins        |
| [CLI arguments](docs/bot_cli_args.md)        | `--log-level`, `--health_check`, etc. |
| [Architecture](docs/architecture.md)         | Internal design overview              |
| [Development](docs/development.md)           | Contributing and local setup          |
| [Roadmap](docs/roadmap.md)                   | Planned features                      |
| [Debugging](docs/debug.md)                   | Logging and troubleshooting           |

---

## Contributing

Bug reports, feature requests, and pull requests are welcome. Please read [docs/development.md](docs/development.md)
before submitting a PR.

---

## License

Licensed under the [MIT License](LICENSE).
