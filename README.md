# pyTMbot

**pyTMbot** is a simple Telegram bot designed to manage Docker `containers` and `images` while providing basic status
information about **local** servers. The bot operates synchronously and does not use webhooks.

[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=bugs)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Duplicated Lines (%)](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=duplicated_lines_density)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/abe0314bb5c24cfda8db9c0a293d17c0)](https://app.codacy.com/gh/orenlab/pytmbot/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)
[![Production Docker CI](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml/badge.svg)](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml)

Developed using the [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI), and
utilizing [psutil](https://github.com/giampaolo/psutil) and [docker-py](https://github.com/docker/docker-py) libraries.

## 💡 Key Features

### 🐳 Docker Management

- Manage Docker containers (start, stop, restart, etc.)
- View the status of containers, including those that have completed
- Access container logs
- Retrieve information about Docker images

### 🖥️ Local Server Monitoring

- Load average details
- Summary memory usage, including swap
- Sensor data
- Summary of processes
- Uptime information
- Basic file system and network connection information

### 🔖 Additional Features

- Check for bot updates using `/check_bot_updates`
- Response templating with `Jinja2`
- Accessible bot logs through Docker log aggregator
- Emoji support 😅

Screenshots: [screenshots.md](docs/screenshots.md)

## 🕸 Requirements

Starting from version 0.9.0, the bot can be installed locally outside of Docker containers, though Docker-based
deployment is still supported.

Full list of Python dependencies can be found in `requirements.txt`. For local installation, refer to `setup_req.txt`.

## 🔌 Installation, Setup, and Running the Bot

- See [installation.md](docs/installation.md) for detailed instructions.

## 🛡 Security

pyTMbot v.2 introduces significant architectural changes and new security measures:

- **Superuser Role:** Grants Docker container management rights securely.
- **TOTP Two-Factor Authentication:** Enhances security with time-based unique codes and session controls.

Learn more about these changes in our [blog post](#).

## 💢 Supported Commands

The bot supports various commands, as listed below:

| # | Command              | Button               | Note                            |
|---|----------------------|----------------------|---------------------------------|
| 1 | `/start`             | None                 | -                               |
| 2 | `/help`              | None                 | -                               |
| 3 | `/docker`            | 🐳 Docker            | -                               |
| 4 | `/containers`        | 🧰 Containers        | Available in the Docker section |
| 5 | `/images`            | 🖼️ Images           | Available in the Docker section |
| 6 | `/back`              | 🔙 Back to main menu | Available in the Docker section |
| 7 | `/check_bot_updates` | None                 | -                               |

## 📈 Roadmap

For details on future updates, see [roadmap.md](docs/roadmap.md).

## 🐋 Docker Hub

![GitHub Release](https://img.shields.io/github/v/release/orenlab/pytmbot)
[![Docker Pulls](https://badgen.net/docker/pulls/orenlab/pytmbot?icon=docker&label=pulls)](https://hub.docker.com/r/orenlab/pytmbot/)
[![Docker Image Size](https://badgen.net/docker/size/orenlab/pytmbot?icon=docker&label=image%20size)](https://hub.docker.com/r/orenlab/pytmbot/)
![Github last-commit](https://img.shields.io/github/last-commit/orenlab/pytmbot)

Visit [Docker Hub repository](https://hub.docker.com/r/orenlab/pytmbot) for more details.

## 🧬 Authors

- [@orenlab](https://github.com/orenlab)

## 🚀 About Me

I am a novice Python developer, and this is my first publicly available project in Python.

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)