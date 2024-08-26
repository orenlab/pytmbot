### pyTMbot v.2

A simple Telegram bot to handle Docker containers and images, also providing basic information about the status of
**local** servers. The bot operates synchronously. It does not use webhooks.

[![Production Docker CI](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml/badge.svg)](https://github.com/orenlab/pytmbot/actions/workflows/prod-docker-ci.yml)
![Github last-commit](https://img.shields.io/github/last-commit/orenlab/pytmbot)
![GitHub Release](https://img.shields.io/github/v/release/orenlab/pytmbot)

## 💡 Key Features

### 🐳 A large section on Docker

__Some of the features are protected by two-factor authentication, which is built into pyTMbot v.2__

- Container management (start, stop, restart, etc.)
- Key information about the current status of containers (even those that have finished work)
- Ability to access container logs
- Key information about images

### 🖥️ A large section on local servers

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
touch pytmbot.yaml
```

Then,

```bash
nano pytmbot.yaml
```

And we insert the following content, then fill in the required fields between single quotes:

```yaml
# Setup bot tokens
bot_token:
  # Prod bot token.
  prod_token:
    - ''
  # Development bot token. Not necessary for production bot.
  dev_bot_token:
    - ''
# Setup access control
access_control:
  # The ID of the users who have permission to access the bot.
  # You can have one or more values - there are no restrictions.
  allowed_user_ids:
    - 0000000000
    - 0000000000
  # The ID of the admins who have permission to access the bot.
  # You can have one or more values, there are no restrictions.
  # However, it's important to keep in mind that these users will be able to manage Docker images and containers.
  allowed_admins_ids:
    - 0000000000
    - 0000000000
  # Salt is used to generate TOTP (Time-Based One-Time Password) secrets and to verify the TOTP code.
  # A script for the fast generation of a truly unique "salt" is available in the bot's repository:
  # https://github.com/orenlab/pytmbot/blob/feature/2.0.0/cli/generate_salt.py
  auth_salt:
    - ''
# Docker settings
docker:
  # Docker socket. Usually: unix:///var/run/docker.sock.
  host:
    - 'unix:///var/run/docker.sock'

```

Then press `Ctrl + X` followed by `Y` to save your changes and exit the `nano` editor.

#### Note about `auth_salt` parameter:

The bot supports random salt generation. To use this feature, it is recommended to run the following command in a
separate terminal window:

```bash
sudo docker run --rm orenlab/pytmbot:0.2.0-alpine-dev -s true
```

This command will generate a unique "salt" value for you and display it on the screen. The container will then be
automatically deleted.

## 🔌 Run bot

To launch a Docker container:

```bash
sudo docker run -d -m 100M \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
orenlab/pytmbot:0.2.0-alpine-dev
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

