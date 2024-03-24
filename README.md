![pyTMbot](docs/.screenshots/main_banner.png)

# pyTMbot

A simple Telegram bot designed to gather basic information about the status of your __local__ servers. 
The bot operates synchronously. It does not use webhooks.

[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=bugs)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Duplicated Lines (%)](https://sonarcloud.io/api/project_badges/measure?project=orenlab_pytmbot&metric=duplicated_lines_density)](https://sonarcloud.io/summary/new_code?id=orenlab_pytmbot)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/abe0314bb5c24cfda8db9c0a293d17c0)](https://app.codacy.com/gh/orenlab/pytmbot/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)

The bot was written using the [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI).
Use [psutil](https://github.com/giampaolo/psutil) and [docker-py](https://github.com/docker/docker-py) libraries for
gather information.

Screenshots are available here: [screenshots.md](docs/screenshots.md)


## 💡 Features

- Load average information
- Summary memory usage information (with swap)
- Sensors information
- Summary process information
- Uptime information
- File system base information
- Containers (only docker and only on Linux) base information
- Use `Jinja2` for answers template
- Use docker logs collector (`sudo docker logs container_id`)
- Use emoji :)

## 🪤 Requirements

Initially, the bot was designed to ensure its correct operation only within the Docker container. I have not tested it
running on a local system, either inside or outside a virtual environment.
Therefore, please make sure that Docker is installed on your system.

Full list of Python dependencies see in `requirements.txt`

## 🔌 Installation, setup and run bot

- _See [installation.md](docs/installation.md)_

## 🛡 Secure

The bot has a user.id authorization mechanism (specified at the initial stage of configuration). 
If the user.id is not specified, the bot will report that it is unable to access information about the server.


## 📈 Roadmap

- See [roadmap.md](docs/roadmap.md)

## 👾 Known issues

- You tell me :)


## 🧬 Authors

- [@orenlab](https://github.com/orenlab)

## 🚀 About Me

I am a novice Python developer. This is my first publicly available project in this great programming language.

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
