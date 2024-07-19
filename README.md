![pytmbot](https://socialify.git.ci/orenlab/pytmbot/image?description=1&forks=1&issues=1&language=1&name=1&owner=1&pattern=Plus&pulls=1&stargazers=1&theme=Light)

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
[![Production Docker CI](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml/badge.svg)](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml)

The bot was written using the [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI).
Use [psutil](https://github.com/giampaolo/psutil) and [docker-py](https://github.com/docker/docker-py) libraries for
gather information.

## 💡 Features

- Load average information
- Summary memory usage information (with swap)
- Sensors information
- Summary process information
- Uptime information
- File system base information
- Basic information about the network connection

### 🐳 A large section on Docker

- Information about containers (even those that have finished work)
- The ability to view container logs
- Information about images

### 🔖 Additionally:

- The "About Me" section, which allows users to check for updates regarding the bot: `/check_bot_updates`
- The `Jinja2` templating engine is used to generate the responses.
- The bot logs are accessible in the Docker log aggregator.
- And of course we use emoji 😅

Screenshots are available here: [screenshots.md](docs/screenshots.md).
Video demo see in YouTube Shorts [here](https://youtube.com/shorts/81RE_PNjxLQ?feature=shared)

## 🕸 Requirements

Initially, I designed the bot to run only inside a Docker container. However, this method has some limitations, so from
version 0.9.0 onward, it is possible to install the bot locally outside the container. At the same time, the bot will
still be able to function and receive information about Docker containers.

Full list of Python dependencies see in `requirements.txt`

## 🔌 Installation, setup and run bot

- _See [installation.md](docs/installation.md)_

## 🛡 Secure

The bot has an authorization mechanism. That is based on a unique value we can get from the message's
variable `from_user.id`, which is the Telegram user ID.
By comparing this value with the `user.id` values specified in the bot's settings
(which is done at the initial stage of configuring the bot), we can determine the behavior of the bot.

All failed attempts to authorize are logged with an `ERROR` flag.

## 🌲 Bot tree

```
├── Dockerfile                              - Main Dockerfile
├── LICENSE                                 - Licence file
├── README.md                               - Main README
├── SECURITY.md                             - Security policy
├── app
│   ├── __init__.py                         - Bot core
│   ├── core
│   │   ├── __init__.py                     
│   │   ├── adapters
│   │   │   ├── __init__.py
│   │   │   ├── docker_adapter.py           - Docker adapter
│   │   │   ├── podman_adapter.py           - Podman adapter (in development)
│   │   │   └── psutil_adapter.py           - Psutil adapter
│   │   ├── exceptions.py                   - Custom exceptions
│   │   ├── handlers
│   │   │   ├── __init__.py                 - Import all handlers in one list
│   │   │   ├── default_handlers
│   │   │   │   ├── __init__.py             
│   │   │   │   ├── about_bot.py            - About bot handler
│   │   │   │   ├── check_bot_update.py     - Check pyTMbot updates
│   │   │   │   ├── containers_handler.py   - Container handler
│   │   │   │   ├── echo.py                 - Handle uncknown command
│   │   │   │   ├── fs_handler.py           - Filesystem handler
│   │   │   │   ├── load_avg_handler.py     - Load average handler
│   │   │   │   ├── memory_handler.py       - Memory handler
│   │   │   │   ├── net_io_stat.py          - Network handler
│   │   │   │   ├── process_handler.py      - Process handler
│   │   │   │   ├── sensors_handler.py      - Sensors handler
│   │   │   │   ├── start_handler.py        - Main, start handler
│   │   │   │   └── uptime_handlers.py      - Uptime handler
│   │   │   ├── handler.py                  - Base handler class (abc)
│   │   │   ├── handlers_aggregator.py      - Main handlers aggregator
│   │   │   └── inline_handlers
│   │   │       ├── __init__.py
│   │   │       ├── containers_full_info.py - Full containers info handler
│   │   │       └── swap_handler.py         - Swap inline handler
│   │   │       └── update_info.py          - Updates info inline handler
│   │   ├── jinja2
│   │   │   ├── __init__.py
│   │   │   └── jinja2.py                   - Main jinja2 class
│   │   ├── keyboards
│   │   │   ├── __init__.py
│   │   │   └── keyboards.py                - Main keyboards class  
│   │   ├── logs.py                         - Custom logger
│   │   ├── middleware
│   │   │   ├── __init__.py
│   │   │   └── auth.py                     - Auth middleware class
│   │   └── settings
│   │       ├── __init__.py
│   │       ├── bot_settings.py             - Class to load configuration from .pytmbotenv
│   │       ├── keyboards.py                - Keyboards settings
│   │       └── loggers.py                  - Logger templates
│   ├── main.py                             - Main bot class
│   ├── templates
│   │   ├── about_bot.jinja2                - Bot update jinja2 template
│   │   ├── bot_update.jinja2               - Bot update jinja2 template
│   │   ├── containers.jinja2               - Containers jinja2 template
│   │   ├── containers_full_info.jinja2     - Containers full info jinja2 template                    
│   │   ├── fs.jinja2                       - Filesystem jinja2 template
│   │   ├── how_update.jinja2               - Update instruction jinja2 template
│   │   ├── index.jinja2                    - Start jinja2 template
│   │   ├── load_average.jinja2             - Load average jinja2 template
│   │   ├── memory.jinja2                   - Memory jinja2 template
│   │   ├── none.jinja2                     - Docker jinja2 template
│   │   ├── process.jinja2                  - Process jinja2 template
│   │   ├── sensors.jinja2                  - Sensors jinja2 template
│   │   ├── swap.jinja2                     - Swap jinja2 template
│   │   └── uptime.jinja2                   - Uptime jinja2 template
│   └── utilities
│       ├── __init__.py
│       └── utilities.py                    - Some utility
├── bot_cli
│   ├── cfg_templates
│   │   └── env.py                          - Template for initial setup
│   └── fs.py                               - Filesystem utility
├── docker-compose.yml                      - Docker Compose file (used main Dockerfile)
├── docs
│   ├── installation.md                     - Installation guide
│   ├── roadmap.md                          - Roadmap guide
│   └── screenshots.md                      - Bots screenshot
├── hub.Dockerfile                          - Dockerfile for Docker CI/CD based on Alpine
├── poetry.lock                             - Poetry file
├── pyproject.toml                          - Poetry file
├── requirements.txt                        - Requirements for build Docker image
├── setup_bot.py                            - Initial setup bot script
├── setup_req.txt                           - Setup requirements
├── tests                                   - Bot tests
```

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
