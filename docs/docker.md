### pyTMbot

A simple Telegram bot to handle Docker containers and images, also providing basic information about the status of *
*local** servers. The bot operates
synchronously. It does not use webhooks.

[![Production Docker CI](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml/badge.svg)](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml)
![Github last-commit](https://img.shields.io/github/last-commit/orenlab/pytmbot)
![GitHub Release](https://img.shields.io/github/v/release/orenlab/pytmbot)

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

Screenshots are available here: [screenshots.md](https://github.com/orenlab/pytmbot/blob/master/docs/screenshots.md).

## 🐋 pyTMBot tag info

| Tag        | Content                                                                                                                                                                 |
|------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| latest     | The latest stable release image, based on Alpine Linux                                                                                                                  |
| 0.X.X      | Stable release, based on Alpine Linux                                                                                                                                   |
| alpine-dev | The latest version, which is compiled each time it is successfully added to the development branch, is not guaranteed to be stable. The image is based on Alpine Linux. |

## 🧪 Configure bot

1. Secret Settings:

- Let's create the necessary files:

```bash
sudo -i
cd /root/
touch .pytmbotenv
```

Then,

```bash
nano .pytmbotenv
```

And we insert the following content, first replacing `<PUT YOUR VALUE HERE>`:

- For stable tag: `0.0.9`, `0.1.1`, `latest`:

```bash
# The bot token that you received from the BotFather:
BOT_TOKEN=<PUT YOUR VALUE HERE>
# Add your telegram IDs:
ALLOWED_USER_IDS=[00000000000, 00000000000]
# Set Docker Socket o TCP param. Usually: unix:///var/run/docker.sock: 
DOCKER_HOST='unix:///var/run/docker.sock'
PODMAN_HOST=''
```

- For `alpine-dev` tag:

```bash
# The bot token that you received from the BotFather:
BOT_TOKEN=<PUT YOUR VALUE HERE>
# Add your telegram IDs:
ALLOWED_USER_IDS=[00000000000, 00000000000]
# Setting up administrative (full) access. This field is only required for the alpine-dev environment!
# For version 0.1.1 and earlier, this field may be omitted.
ALLOWED_ADMINS_IDS=[00000000000, 00000000000]
# Set Docker Socket o TCP param. Usually: unix:///var/run/docker.sock: 
DOCKER_HOST='unix:///var/run/docker.sock'
```

Then press `Ctrl + X` followed by `Y` to save your changes and exit the `nano` editor.

## 🔌 Run bot

To launch a Docker container:

```bash
sudo docker run -d -m 100M \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/.pytmbotenv:/opt/pytmbot/.pytmbotenv:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
orenlab/pytmbot:latest \
--log-level=INFO --mode=prod
```

#### Supported logging levels:

| # | Logging levels | Note                                                                                                                                                                  | Args                | 
|---|----------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------|
| 1 | `INFO`         | Balanced logging mode: only the most important information + a short description of errors and exceptions.                                                            | `--log-level=INFO`  |
| 2 | `ERROR`        | Only errors and exceptions are shown. This can be considered a "quiet" mode.                                                                                          | `--log-level=ERROR` | 
| 3 | `DEBUG`        | The most detailed level of logs provides all the information displayed in the previous levels, plus additional details, such as traces and all debugging information. | `--log-level=DEBUG` |

#### Note #1:

_Please don't forget to specify your time zone! You can find a list of available time zones, for
example, [here](https://manpages.ubuntu.com/manpages/trusty/man3/DateTime::TimeZone::Catalog.3pm.html)_

#### Note #2:

_Please don't forget to specify Tag version!_

Now everything is ready for you to use the bot. All you need to do is run the `/start` command in your Telegram app.

## 🏗 Updating the image

In order to update the image to the latest version, please follow these steps:

* Stopping the running pyTMbot container:

```bash
sudo docker stop pytmbot
```

* Deleting an outdated container:

```bash
sudo docker rm /pytmbot
```

* Deleting an outdated image:

```bash
sudo docker rmi pytmbot
```

* Uploading an updated image:

```bash
sudo docker pull orenlab/pytmbot:latest
```

And we run it in the same way as we would if we had just installed the bot (see the instructions above).

## Bot logs

- To access the bot logs, please run the following command in the terminal:

```bash
sudo docker logs pytmbot
```

- Advanced logs and debugging: [debug.md](https://github.com/orenlab/pytmbot/blob/master/docs/debug.md)

_Alternatively, if the container is running on your workstation, you can use Docker Desktop._

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

## 👾 Support, source code, questions and discussions

- Support: https://github.com/orenlab/pytmbot/issues
- Source code: [https://github.com/orenlab/pytmbot/](https://github.com/orenlab/pytmbot/)
- Discussions: [https://github.com/orenlab/pytmbot/discussions](https://github.com/orenlab/pytmbot/discussions)

## 🧬 Authors

- [@orenlab](https://github.com/orenlab)

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
