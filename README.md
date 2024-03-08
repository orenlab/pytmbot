# pyTMbot

A simple Telegram bot designed to gather basic information about the status of your __local__ servers

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=bugs)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Duplicated Lines (%)](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=duplicated_lines_density)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/abe0314bb5c24cfda8db9c0a293d17c0)](https://app.codacy.com/gh/orenlab/pytmbot/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)

The bot was written using the [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI)
and [psutil](https://github.com/giampaolo/psutil) libraries.

__Important! During the transition period from Glances to PsUtil,
it is necessary to have the Glance application installed and running in Restful API mode.__

## 💡 Features

- Load average information (with history)
- Summary memory usage information
- Sensors information
- Summary process information
- Uptime information
- File system base information
- Containers (e.g. podman, docker) base information
- Use `Jinja2` for answers template
- Use docker logs collector (`sudo docker logs container_id`)
- Use emoji :)

## 🪤 Requirements

Initially, the bot was designed to ensure its correct operation only within the Docker container. I have not tested it
running on a local system, either inside or outside a virtual environment.
Therefore, please make sure that Docker is installed on your system.

Full list of Python dependencies see in `requirements.txt`

## 🔌 Installation, setup and run bot

- _See [install.md](docs/INSTALL.md)_

## 🛡 Secure

The bot is designed to only respond to commands from authorized users.
A message comparison is used to verify the `messages.from_user.id` value
and constant `ALLOWED_USER_IDS` list in the `BotSettings`
(please see the section on configuring the bot for more information).

Therefore, it is essential to enter the `ALLOWED_USER_IDS` accurately.

## 📈 Roadmap

- See [roadmap.md](docs/ROADMAP.md)

## 👾 Known issues

- The bot crashes when there is an error polling the Telegram server

The idea behind the bot is that we cannot rely on a webhook for communication.
Instead, polling from the local server (which is not accessible from the internet)
always carries the risk of disconnection or errors on the telecom infrastructure and on the Telegram platform.

## 🧬 Authors

- [@orenlab](https://github.com/orenlab/pytelemonbot)

## 🚀 About Me

I am a novice Python developer. This is my first publicly available project in this great programming language.

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
