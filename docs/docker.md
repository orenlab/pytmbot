![pytmbot](https://socialify.git.ci/orenlab/pytmbot/image?description=1&forks=1&issues=1&language=1&name=1&owner=1&pattern=Floating%20Cogs&pulls=1&stargazers=1&theme=Auto)

# pyTMbot

A simple Telegram bot designed to gather basic information about the status of your **local** servers. The bot operates
synchronously. It does not use webhooks.

[![Docker Image CI](https://github.com/orenlab/pytmbot/actions/workflows/docker-image.yml/badge.svg)](https://github.com/orenlab/pytmbot/actions/workflows/docker-image.yml)

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

## 🧪 Configure bot

1. Secret Settings:

- Let's create the necessary files:

```bash
  sudo -i
  cd /root/
  touch .env
```

- Now let's add the necessary data to the .env file:

```bash
  nano .env
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

```bash
  sudo docker run -d -m 100M -v /var/run/docker.sock:/var/run/docker.sock:ro -v /root/.env:/opt/pytmbot/.env:ro --restart=always --name=pytmbot --pid=host --security-opt=no-new-privileges orenlab/pytmbot:latest
```

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