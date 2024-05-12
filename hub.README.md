![pytmbot](https://socialify.git.ci/orenlab/pytmbot/image?description=1&forks=1&issues=1&language=1&name=1&owner=1&pattern=Floating%20Cogs&pulls=1&stargazers=1&theme=Auto)

# pyTMbot

A simple Telegram bot designed to gather basic information about the status of your local servers. The bot operates
synchronously. It does not use webhooks.

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
- Containers (only docker and only on Linux) base information
- Use `Jinja2` for answers template
- Use docker logs collector (`sudo docker logs container_id`)
- Use emoji :)

Screenshots are available here: [screenshots.md](docs/screenshots.md).
Video demo see in Youtube Shorts [here](https://youtube.com/shorts/81RE_PNjxLQ?feature=shared)

## 🧪 Configure bot

1. Secret Settings:

* Let's create the necessary files:

```bash
  sudo -i
  cd /root/
  touch .env
  touch bot_settings.py
```

* Now let's add the necessary data to the .env file:

```bash
  nano .env
```

And we insert the following content, first replacing `<PUT YOUR TOKEN HERE>` with the token value that we received when
creating the bot

```bash
# Prod bot token
BOT_TOKEN=<PUT YOUR TOKEN HERE>
```

2. Bot settings

The next and final step is to configure the main file for the bot. In this file, we need to set up access to the boat
and provide the URL for Docker and Podman socket connections.

```bash
  nano bot_settings.py
```

Using the following template, pre-filling it with your own values, insert the contents:

```python
#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local computers and/or servers from Glances
"""
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Add your telegram IDs. And your bot too!"""
    ALLOWED_USER_IDS: list[int] = [00000000000, 00000000000]


class DockerSettings:
    """Set Docker Socket o TCP param"""
    docker_host: str = 'unix:///PAST HERE DOCKER SOCKET URI'


class PodmanSettings:
    """Set Podman Socket o TCP param"""
    podman_host: str = 'unix:///PAST HERE DOCKER SOCKET URI'


class BotTokenSettings(BaseSettings):
    """Bot Token Settings. Get token from CLI"""
    bot_token: SecretStr
    dev_bot_token: SecretStr
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')


token_settings = BotTokenSettings()

```

## 🔌 Run bot

To launch a Docker container:

```bash
  sudo docker run -d -m 100M -v /var/run/docker.sock:/var/run/docker.sock:ro -v /root/.env:/opt/pytmbot/.env:ro -v /root/bot_setting.py:/opt/pytmbot/app/core/settings/bot_settings.py:ro --restart=always --name=pytmbot --pid=host --security-opt=no-new-privileges orenlab/pytmbot:0.0.5
```

## 👾 Support

Please create issue on Github: [https://github.com/orenlab/pytmbot](https://github.com/orenlab/pytmbot)