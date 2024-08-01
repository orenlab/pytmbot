![pytmbot](https://socialify.git.ci/orenlab/pytmbot/image?description=1&forks=1&issues=1&language=1&name=1&owner=1&pattern=Plus&pulls=1&stargazers=1&theme=Light)

# pyTMbot

A simple Telegram bot to handle **Docker** `containers` and `images`, also providing basic information about the status of
**local** servers.
The bot operates synchronously. It does not use webhooks.

[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=bugs)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Duplicated Lines (%)](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=duplicated_lines_density)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/abe0314bb5c24cfda8db9c0a293d17c0)](https://app.codacy.com/gh/orenlab/pytmbot/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)
[![Production Docker CI](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml/badge.svg)](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml)

The bot was written using the [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI).
Use [psutil](https://github.com/giampaolo/psutil) and [docker-py](https://github.com/docker/docker-py) libraries for
gather information.

## 🐳 A large section on Docker

- Information about containers (even those that have finished work)
- The ability to view container logs
- Information about images

### 💡 Features

- Load average information
- Summary memory usage information (with swap)
- Sensors information
- Summary process information
- Uptime information
- File system base information
- Basic information about the network connection

### 🔖 Additionally:

- The "About Me" section, which allows users to check for updates regarding the bot: `/check_bot_updates`
- The `Jinja2` templating engine is used to generate the responses.
- The bot logs are accessible in the Docker log aggregator.
- And of course we use emoji 😅

Screenshots are available here: [screenshots.md](docs/screenshots.md).

## 🕸 Requirements

Initially, I designed the bot to run only inside a Docker container. However, this method has some limitations, so from
version 0.9.0 onward, it is possible to install the bot locally outside the container. At the same time, the bot will
still be able to function and receive information about Docker containers.

Full list of Python dependencies see in `requirements.txt`. List of Python dependencies for self setup bot see
in `setup_req.txt`

## 🔌 Installation, setup and run bot

- _See [installation.md](docs/installation.md)_

## 🛡 Secure

An authorization mechanism has been built into the pyTMbot management system.
To describe the principle of its operation in the most concise way, we can say the following:

- At the initial stage of configuration, we set the unique identifiers of users who are allowed to access the
  bot (`ALLOWED_USER_IDS`), regardless of which official method is used.
- With each new request for the bot, the middleware `AccessControl` is activated first. It checks whether the
  variable `from_user.id` matches the values specified in the settings. If a match is found, the request is sent to the
  appropriate handler.
- In all other cases, a mechanism is triggered that informs the user that they do not have access to the bot and stops
  processing.

In the `alpine-dev` build (and the next release `0.1.2`), this mechanism has been expanded:

- The bot now reacts to incoming requests by reporting the lack of access twice, then completely stops processing
  messages.
- All failed attempts to authorize are logged with an `DENIED` and `BLOCKED`flag.

For stable version, failed attempts to authorize are logged with an `ERROR`flag.

## 💢 Supported commands

In addition to button navigation, the bot also supports commands. Below is a list of commands and their details:

| # | Command              | Keyboard button      | Note                                   | 
|---|----------------------|----------------------|----------------------------------------|
| 1 | `/start`             | None                 | -                                      | 
| 2 | `/help`              | None                 | -                                      | 
| 3 | `/docker`            | 🐳 Docker            | -                                      |
| 4 | `/containers`        | 🧰 Containers        | Button available in the Docker section |
| 5 | `/images`            | 🖼️ Images           | Button available in the Docker section |
| 6 | `/back`              | 🔙 Back to main menu | Button available in the Docker section |
| 7 | `/check_bot_updates` | None                 | -                                      |

## 🌲 Bot tree

- See [bot_tree.md](docs/bot_tree.md)

## 📈 Roadmap

- See [roadmap.md](docs/roadmap.md)

## 🐋 pyTMbot on Docker Hub

![GitHub Release](https://img.shields.io/github/v/release/orenlab/pytmbot)
[![Docker Pulls](https://badgen.net/docker/pulls/orenlab/pytmbot?icon=docker&label=pulls)](https://hub.docker.com/r/orenlab/pytmbot/)
[![Docker Image Size](https://badgen.net/docker/size/orenlab/pytmbot?icon=docker&label=image%20size)](https://hub.docker.com/r/orenlab/pytmbot/)
![Github last-commit](https://img.shields.io/github/last-commit/orenlab/pytmbot)

- pyTMbot repo on Docker Hub: https://hub.docker.com/r/orenlab/pytmbot

## 🧬 Authors

- [@orenlab](https://github.com/orenlab)

## 🚀 About Me

I am a novice Python developer. This is my first publicly available project in this great programming language.

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
