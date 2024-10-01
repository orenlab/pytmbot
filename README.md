# pyTMbot

**pyTMbot** is a versatile Telegram bot designed for managing Docker containers, monitoring server status, and extending
its functionality through a modular plugin system. The bot supports both **polling** and **webhook** modes, offering
flexibility based on your deployment requirements. Additionally, **pyTMbot** can be deployed either **directly on the
host machine** or within a **Docker container**, providing flexibility in infrastructure setup.

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

- Manage Docker containers (start, stop, restart, etc.)
- View and monitor the status of running and stopped containers
- Access and search container logs
- Retrieve and inspect Docker images
- Inline query handling for managing containers directly from Telegram

### 🖥️ Local Server Monitoring

- Load average details and monitoring
- Summary of memory and swap usage
- Real-time sensor data
- Process summary and control
- Uptime information
- Network and file system information

### 🔌 Plugin System

- Extend functionality through custom plugins with simple configuration.
- Example plugins:
    - **Monitor Plugin:** Monitor CPU, memory, temperature _(only for Linux)_, and disk usage with customizable
      thresholds.
    - **2FA Plugin:** Two-factor authentication for added security using QR codes and TOTP.
    - **Outline VPN Plugin:** Monitor your [Outline VPN](https://getoutline.org/) server directly from
      Telegram.

Refer to [plugins.md](docs/plugins) for more information on adding and managing plugins.

### 🔖 Additional Features

- Integrated bot update check: `/check_bot_updates`
- Emoji support for improved user interaction 😎
- Templated response system powered by Jinja2
- Extensive logging through Docker log aggregators

## 🕸 Requirements

Starting from version 0.9.0, **pyTMbot** can run **either directly on the host machine or in a Docker container**. Both
deployment methods provide full functionality, but there are slight differences in system access depending on the
environment:

- **Host machine deployment:** Direct access to system resources like CPU, memory, and sensors. Recommended for cases
  where precise and real-time system monitoring is critical.
- **Docker container deployment:** Ideal for isolated environments or multi-bot setups. Certain low-level system access
  may be restricted due to container isolation, but Docker management and most server monitoring features remain fully
  functional.

The bot supports two operational modes:

- **Polling Mode:** Simplified setup with no need for HTTPS or a static IP address. Recommended for small-scale or
  development deployments.
- **Webhook Mode:** Optimized for real-time updates with reduced latency. Suitable for production environments,
  typically requiring an HTTPS server and a valid domain.

To simplify the installation process, we provide an **`install.sh`** script that handles the setup, regardless of
whether you choose to run **pyTMbot** on a host machine or within a Docker container. For full instructions on
installation and configuration, refer to the [installation section](docs/installation.md).

## 🔌 Installation and Setup

Refer to [installation.md](docs/installation.md) for full instructions on setting up the bot in your environment.

## 🛡 Security

**pyTMbot** comes with security-first features, such as:

- **Superuser Role:** Manage Docker containers securely.
- **TOTP 2FA Support:** Secure sensitive actions with time-based OTPs and QR code generation.
- **Access Control Middleware:** Manage bot access using a customizable list of admin IDs.
- **Rate Limiting Middleware:** To protect against **DoS (Denial-of-Service) attacks**, pyTMbot integrates middleware
  that limits the number of requests allowed from a single user or IP address within a specified time frame. This
  prevents abuse while ensuring smooth performance under heavy load.

Learn more about the security measures in our detailed [security guide](docs/security.md).

## 🧑‍💻 Commands and Handlers

The bot provides a rich set of commands for users. Below is a table of the main commands available:

| # | Command              | Button               | Description                         |
|---|----------------------|----------------------|-------------------------------------|
| 1 | `/start`             | None                 | Initialize the bot                  |
| 2 | `/help`              | None                 | Display help information            |
| 3 | `/docker`            | 🐳 Docker            | Access Docker management commands   |
| 4 | `/containers`        | 🧰 Containers        | View and manage Docker containers   |
| 5 | `/images`            | 🖼️ Images           | Inspect Docker images               |
| 6 | `/outline`           | 🔑 Outline VPN       | Manage and monitor Outline VPN keys |
| 7 | `/check_bot_updates` | None                 | Check for available bot updates     |
| 8 | `/back`              | 🔙 Back to main menu | Return to the main menu             |

## 📈 Roadmap

To learn more about planned features and future updates, check the [roadmap](docs/roadmap.md).

## 🐋 Docker Hub

You can find the official Docker image on Docker Hub:

![GitHub Release](https://img.shields.io/github/v/release/orenlab/pytmbot)
[![Docker Pulls](https://badgen.net/docker/pulls/orenlab/pytmbot?icon=docker&label=pulls)](https://hub.docker.com/r/orenlab/pytmbot/)
[![Docker Image Size](https://badgen.net/docker/size/orenlab/pytmbot?icon=docker&label=image%20size)](https://hub.docker.com/r/orenlab/pytmbot/)
![Github last-commit](https://img.shields.io/github/last-commit/orenlab/pytmbot)

Head to the [Docker Hub repository](https://hub.docker.com/r/orenlab/pytmbot) for more details.

## 🧬 Contributors

- [@orenlab](https://github.com/orenlab)

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)

This project is licensed under the MIT License – see the [LICENSE](LICENSE) file for details.