# pyTMBot v.2 Self-Build Guide

## 🔌 Installation

To build the pyTMBot project from source, follow these steps:

1. Clone the repository:

    ```bash
    git clone https://github.com/orenlab/pytmbot.git
    cd ./pytmbot
    ```

2. Set up the virtual environment and install dependencies:

    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -r setup_req.txt
    ```

## 🧪 Configure the Bot

1. **Activate the virtual environment** and **install dependencies** as described above.

2. **Run the CLI Setup Wizard** to configure the bot:

    ```bash
    python3 ./setup_bot.py
    ```

   Follow the prompts in the wizard to generate the necessary configuration file.

   This wizard will create a configuration file:

   | File           | Purpose                                                                                      |
             |----------------|----------------------------------------------------------------------------------------------|
   | `pytmbot.yaml` | Stores bot settings, including tokens, allowed user IDs, and paths to Docker and Podman sockets. |

   You can accept the default settings by pressing "Enter" when prompted.

## 💰 Run the Bot

To start the bot in a Docker container, use the following command:

```bash
sudo docker run -d -m 100M \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
orenlab/pytmbot:self-build
```

### Supported Logging Levels

| # | Logging Level | Description                                                                                                             | Arguments           |
|---|---------------|-------------------------------------------------------------------------------------------------------------------------|---------------------|
| 1 | `INFO`        | Provides a balanced level of logging with essential information and a brief description of errors and exceptions.       | `--log-level=INFO`  |
| 2 | `ERROR`       | Displays only errors and exceptions, suitable for a quieter mode.                                                       | `--log-level=ERROR` |
| 3 | `DEBUG`       | Offers the most detailed logs, including all information from previous levels, along with additional debugging details. | `--log-level=DEBUG` |

#### Note:

- **Time Zone**: Ensure you specify your time zone. A list of available time zones can be
  found [here](https://manpages.ubuntu.com/manpages/trusty/man3/DateTime::TimeZone::Catalog.3pm.html).

After starting the bot, you can initiate it by sending the `/start` command in your Telegram app.

## 🚀 Bot Logs

To view the bot logs, use the following command:

```bash
sudo docker logs pytmbot
```

For advanced logging and debugging details, refer to [debug.md](debug.md).

If you are running the container on your workstation, you can also use Docker Desktop to view the logs.