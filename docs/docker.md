# pyTMbot

A simple Telegram bot designed to gather basic information about the status of your **local** servers. The bot operates
synchronously. It does not use webhooks.

[![Docker Image Build CI/CD](https://github.com/orenlab/pytmbot/actions/workflows/docker_build_on_push.yml/badge.svg)](https://github.com/orenlab/pytmbot/actions/workflows/docker_build_on_push.yml)

## 💡 Features

- Load average information
- Summary memory usage information (with swap)
- Sensors information
- Summary process information
- Uptime information
- File system base information
- Containers (only docker and only on Linux) base information
- Ability to check for bot software updates: `/check_bot_updates`
- Use `Jinja2` for answers template
- Use docker logs collector (`sudo docker logs pytmbot`)
- Use emoji :)

Screenshots are available here on
GitHub: [screenshots.md](https://github.com/orenlab/pytmbot/blob/master/docs/screenshots.md).
Video demo see in YouTube Shorts [here](https://youtube.com/shorts/81RE_PNjxLQ?feature=shared)

## 🐋 pyTMBot tag info

| Tag          | Content                                                                                                                                                                 |
|--------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `latest`     | The latest stable release image, based on Alpine Linux                                                                                                                  |
| `0.0.X`      | Stable release, based on Alpine Linux                                                                                                                                   |
| `alpine-dev` | The latest version, which is compiled each time it is successfully added to the development branch, is not guaranteed to be stable. The image is based on Alpine Linux. |

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

```bash
# The bot token that you received from the BotFather:
BOT_TOKEN=<PUT YOUR VALUE HERE>
# Add your telegram IDs:
ALLOWED_USER_IDS=[00000000000, 00000000000]
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
orenlab/pytmbot:latest
```

##### **Note:**

_Please don't forget to specify your time zone! You can find a list of available time zones, for
example, [here](https://manpages.ubuntu.com/manpages/trusty/man3/DateTime::TimeZone::Catalog.3pm.html)_

##### **Note:**

_Please don't forget to specify Tag version!_

## 🏗 Updating the image

In order to update the image to the latest version, please follow these steps:

* Stopping the container:

```bash
sudo docker stop pytmbot
```

* Deleting an outdated image:

```bash
sudo docker rm pytmbot
```

* Uploading an updated image:

```bash
sudo docker pull orenlab/pytmbot:latest
```

And we run it in the same way as we would if we had just installed the bot (see the instructions above).

## 🚀 Bot logs

- To access the bot logs, please run the following command in the terminal:

```bash
sudo docker logs pytmbot
```

_Alternatively, if the container is running on your workstation, you can use Docker Desktop._

## 👾 Support, source code, questions and discussions

- Support: [https://github.com/orenlab/pytmbot/issues](https://github.com/orenlab/pytmbot/issues)
- Source code: [https://github.com/orenlab/pytmbot/](https://github.com/orenlab/pytmbot/)
- Discussions: [https://github.com/orenlab/pytmbot/discussions](https://github.com/orenlab/pytmbot/discussions)

## 🧬 Authors

- [@orenlab](https://github.com/orenlab)

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)