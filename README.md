# pyTMbot

**pyTMbot** is a Docker-first Telegram bot for **Docker operations**, **server monitoring**, and **secure remote administration**. It supports both **polling** and **webhook** modes and can be extended through a modular plugin system.

[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=bugs)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Duplicated Lines (%)](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=duplicated_lines_density)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/abe0314bb5c24cfda8db9c0a293d17c0)](https://app.codacy.com/gh/orenlab/pytmbot/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)

## Why pyTMbot

- **Manage Docker from Telegram**: containers, images, logs, volumes, and networks
- **Monitor host health**: CPU, memory, disk, network, sensors, uptime, users, and quick views
- **Secure administration**: allowlists, admin-only actions, 2FA/TOTP, rate limiting, safer webhook handling
- **Production-ready Docker deployment** with structured logging, health checks, and config migration
- **Extensible architecture** through plugins and Jinja2-based templating

pyTMbot is built on [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI), [psutil](https://github.com/giampaolo/psutil), and [docker-py](https://github.com/docker/docker-py).

## Key capabilities

### Docker management
- Start, stop, restart, inspect, and browse containers
- View container logs with pagination and export support
- Inspect and manage Docker images with metadata and tag details
- Browse **Volumes** and **Networks** with optional 2FA protection
- Check for newer image versions against Docker Hub
- Use inline interactions for faster Telegram-based operations

### Server monitoring
- Quick system and Docker summary pages with live refresh
- Detailed CPU, memory, swap, network, disk, user, fan, and sensor views
- Load average, uptime, filesystem, and process insights
- Health monitoring subsystem with startup and component-level checks

### Security and reliability
- Access restricted by `allowed_user_ids` and `allowed_admins_ids`
- TOTP-based 2FA for sensitive actions
- Request rate limiting and duplicate update protection
- Safer webhook deployments with trusted proxy / IP validation
- Secure message deletion scheduling and improved masking in logs
- Better handling of Telegram API edge cases such as long messages and rate limits

### Plugins
- Extend the bot with custom modules and simple configuration
- Included examples:
  - **Monitor Plugin** — notifications for CPU, memory, disk, temperature, container, and image changes
  - **2FA Plugin** — QR-based TOTP setup for stronger protection
  - **Outline VPN Plugin** — monitor your [Outline VPN](https://getoutline.org/) server from Telegram

See [docs/plugins.md](docs/plugins.md) for details.

## What's new in 0.3.0

- Expanded server monitoring views and streamlined quick-view navigation
- Docker UI pagination for containers, images, and logs
- Log export and configurable log format (`human` / `json`)
- Health checks with clearer startup reporting
- Automatic configuration migration/versioning
- Improved performance, caching, masking, and strict typing
- Updated build/runtime stack: **Python 3.12+** and modern Docker toolchain

## Requirements

Current **0.3.x** builds are supported in **Docker / Docker Compose** deployments.

- **Python** 3.12+ runtime baseline
- **Docker Engine** 20.10+
- **Docker Compose** v2.0+ recommended
- Docker socket access for container-management features

### Operating modes
- **Polling** — easiest to deploy; no HTTPS or public endpoint required
- **Webhook** — lower latency; requires a public hostname for Telegram `setWebhook`

### Logging defaults
- `INFO` and above: concise errors without full traceback dumps
- `DEBUG`: full stack traces preserved

## Install

Use the Docker-focused setup guides:

- [docs/installation.md](docs/installation.md)
- [docs/docker.md](docs/docker.md)

## Documentation

- [Docs index](docs/README.md)
- [Settings](docs/settings.md)
- [Security](docs/security.md)
- [Plugins](docs/plugins.md)
- [CLI arguments](docs/bot_cli_args.md)
- [Debugging](docs/debug.md)
- [Roadmap](docs/roadmap.md)

## Docker Hub

![GitHub Release](https://img.shields.io/github/v/release/orenlab/pytmbot)
[![Docker Pulls](https://badgen.net/docker/pulls/orenlab/pytmbot?icon=docker&label=pulls)](https://hub.docker.com/r/orenlab/pytmbot/)
[![Docker Image Size](https://badgen.net/docker/size/orenlab/pytmbot?icon=docker&label=image%20size)](https://hub.docker.com/r/orenlab/pytmbot/)
![Github last-commit](https://img.shields.io/github/last-commit/orenlab/pytmbot)

Official image: [orenlab/pytmbot](https://hub.docker.com/r/orenlab/pytmbot)

## License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)

Licensed under the MIT License. See [LICENSE](LICENSE).
