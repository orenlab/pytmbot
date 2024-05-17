![pytmbot](https://socialify.git.ci/orenlab/pytmbot/image?description=1&forks=1&issues=1&language=1&name=1&owner=1&pattern=Floating%20Cogs&pulls=1&stargazers=1&theme=Auto)

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
- Use `Jinja2` for answers template
- Use docker logs collector (`sudo docker logs container_id`)
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
| `ubuntu-dev` | The latest version, which is compiled each time it is successfully added to the development branch, is not guaranteed to be stable. The image is based on Ubuntu Linux. |

## 🧪 Configure bot

1. Secret Settings:

- Let's create the necessary files:

For stable tag `0.0.5`, `latest`:

```bash
sudo -i
cd /root/
touch .env
```

For over tag (`ubuntu-dev`, `alpine-dev`):

```bash
sudo -i
cd /root/
touch .pytmbotenv
```

Then, for stable tag `0.0.5`, `latest`:

```bash
nano .env
```

or for over tag (`ubuntu-dev`, `alpine-dev`)::

```bash
nano .pytmbotenv
```

And we insert the following content, first replacing `<PUT YOUR VALUE HERE>`:

```bash
# Prod bot token
BOT_TOKEN=<PUT YOUR VALUE HERE>
# Add your telegram IDs. And your bot too!
ALLOWED_USER_IDS=[00000000000, 00000000000]
# Set Docker Socket o TCP param. Usually: unix:///var/run/docker.sock: 
DOCKER_HOST='<PUT YOUR VALUE HERE>'
# Set Podman Socket o TCP param. Usually: unix:///run/user/1000/podman/podman.sock 
PODMAN_HOST='<PUT YOUR VALUE HERE>'
```

## 🔌 Run bot

To launch a Docker container:

For stable tag `0.0.5`, `latest`:

```bash
sudo docker run -d -m 100M \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/.env:/opt/pytmbot/.env:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
orenlab/pytmbot:latest
```

##### **Note**

_Please don't forget to specify your time zone! You can find a list of available time zones, for
example, [here](https://manpages.ubuntu.com/manpages/trusty/man3/DateTime::TimeZone::Catalog.3pm.html)_

For over tag version (`ubuntu-dev`, `alpine-dev`). Please remember to check and change the tag as necessary:

```bash
sudo docker run -d -m 100M \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/.pytmbotenv:/opt/pytmbot/.pytmbotenv:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
orenlab/pytmbot:alpine-dev
```

##### **Note**

_Please don't forget to specify your time zone! You can find a list of available time zones, for
example, [here](https://manpages.ubuntu.com/manpages/trusty/man3/DateTime::TimeZone::Catalog.3pm.html)_

##### **Note:**

_This difference in the naming convention for environment files will be removed with the release of version 0.0.6, which
is expected in early June 2024._

## 🚀 Bot logs

- To access to bot logs, please run in terminal:

```bash
docker ps
```

- And grab pyTMbot container id. Then, run:

```bash
docker logs bot_contaner_id
```

_Or use Docker Desktop (if run workstation)_

## 👾 Support, source code, questions and discussions

- Support: [https://github.com/orenlab/pytmbot/issues](https://github.com/orenlab/pytmbot/issues)
- Source code: [https://github.com/orenlab/pytmbot/](https://github.com/orenlab/pytmbot/)
- Discussions: [https://github.com/orenlab/pytmbot/discussions](https://github.com/orenlab/pytmbot/discussions)

## 🧬 Authors

- [@orenlab](https://github.com/orenlab)

## 📜 License

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)