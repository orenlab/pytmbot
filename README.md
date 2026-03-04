# pyTMbot

**pyTMbot** is a versatile Telegram bot designed for managing Docker containers, monitoring server status, and extending
its functionality through a modular plugin system. The bot supports both **polling** and **webhook** modes, offering
flexibility based on your deployment requirements. Starting with the current release line, **pyTMbot** is distributed
and supported as a **Docker-first application**.

[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=bugs)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Duplicated Lines (%)](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=duplicated_lines_density)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/abe0314bb5c24cfda8db9c0a293d17c0)](https://app.codacy.com/gh/orenlab/pytmbot/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)

**pyTMbot** leverages
the [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI), [psutil](https://github.com/giampaolo/psutil),
and [docker-py](https://github.com/docker/docker-py) libraries to provide robust Docker and server management tools.

## 💡 Key Features

### 🐳 Docker Management

- Efficient management of Docker containers (start, stop, restart, etc.)
- Monitor and retrieve real-time status of running and stopped containers
- Access and search detailed container logs
- Retrieve, inspect, and manage Docker images, including tag information and metadata
- Seamless inline query handling for direct container management via Telegram
- **NEW**: Docker image update checking: Manually check for newer image versions by comparing local tags with those
  available on Docker Hub, helping ensure that your containers can be updated when needed

### 🖥️ Local Server Monitoring

- Load average details and monitoring
- Summary of memory and swap usage
- Real-time sensor data
- Process summary and control
- Uptime information
- Network and file system information
- **NEW**: Quick view for system and Docker summary

### 🔌 Plugin System

- Extend functionality through custom plugins with simple configuration.
- Example plugins:
    - **Monitor Plugin:** Monitor CPU, memory, temperature _(only for Linux)_, disk usage, and detect changes in Docker
      containers and images. The plugin sends notifications for various monitored parameters, including new containers
      and images, ensuring timely awareness of system status.
    - **2FA Plugin:** Two-factor authentication for added security using QR codes and TOTP.
    - **Outline VPN Plugin:** Monitor your [Outline VPN](https://getoutline.org/) server directly from Telegram.

Refer to [plugins.md](docs/plugins.md) for more information on adding and managing plugins.

### 🔖 Additional Features

- Integrated bot update check: `/check_bot_updates`
- Emoji support for improved user interaction 😎
- Templated response system powered by Jinja2
- Extensive logging through Docker log aggregators

## 🕸 Requirements

Current **0.3.x** builds are supported in **Docker / Docker Compose** deployments.

- **Docker Engine** 20.10+
- **Docker Compose** v2.0+ (recommended)
- Access to Docker socket for container-management features

The bot supports two operational modes:

- **Polling Mode:** Simplified setup with no need for HTTPS or a static IP address. Recommended for small-scale or
  development deployments.
- **Webhook Mode:** Optimized for real-time updates with reduced latency. Requires a public reachable hostname for
  Telegram `setWebhook`; local `cert`/`cert_key` are optional when TLS is terminated by a reverse proxy.

Logging defaults:

- At `INFO` and above, error logs are concise (no full Python traceback dump).
- Full stack traces are preserved in `DEBUG`.

## 🔌 Installation and Setup

Use Docker / Docker Compose setup guides:

- [installation.md](docs/installation.md)
- [docker.md](docs/docker.md)

## 🛡 Security

**pyTMbot** comes with security-first features, such as:

- **Allowlist Access Control:** Only IDs from `allowed_user_ids` can use bot features.
- **Admin Boundaries:** Sensitive actions are restricted to `allowed_admins_ids`.
- **TOTP 2FA Support:** Sensitive operations use time-based OTP verification with QR setup.
- **Rate Limiting Middleware:** To protect against **DoS (Denial-of-Service) attacks**, pyTMbot integrates middleware
  that limits the number of requests allowed from a single user or IP address within a specified time frame. This
  prevents abuse while ensuring smooth performance under heavy load.

Learn more about the security measures in our detailed [security guide](docs/security.md).

## 📈 Roadmap

To learn more about planned features and future updates, check the [roadmap](docs/roadmap.md).

## 🐋 Docker Hub

You can find the official Docker image on Docker Hub:

![GitHub Release](https://img.shields.io/github/v/release/orenlab/pytmbot)
[![Docker Pulls](https://badgen.net/docker/pulls/orenlab/pytmbot?icon=docker&label=pulls)](https://hub.docker.com/r/orenlab/pytmbot/)
[![Docker Image Size](https://badgen.net/docker/size/orenlab/pytmbot?icon=docker&label=image%20size)](https://hub.docker.com/r/orenlab/pytmbot/)
![Github last-commit](https://img.shields.io/github/last-commit/orenlab/pytmbot)

Head to the [Docker Hub repository](https://hub.docker.com/r/orenlab/pytmbot) for more details.

## 📚 Documentation

- 📘 [Docs Index](docs/README.md)
- 🔒 [Auth Control](docs/auth_control.md)
- ⚙️ [CLI Args](docs/bot_cli_args.md)
- 🐞 [Debugging](docs/debug.md)
- 🐳 [Docker](docs/docker.md)
- 🛠️ [Installation](docs/installation.md)
- 📦 [Plugins](docs/plugins.md)
- 🗺️ [Roadmap](docs/roadmap.md)
- 🔐 [Security](docs/security.md)
- ⚙️ [Settings](docs/settings.md)

## 🧬 Contributors

- [@orenlab](https://github.com/orenlab)

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)

This project is licensed under the MIT License – see the [LICENSE](LICENSE) file for details.
