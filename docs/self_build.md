# pyTMBot v.2 Self-Build Guide

## 🔌 Installation

To build the pyTMBot project from source, follow these steps:

1. **Clone the Repository**

   ```bash
   git clone https://github.com/orenlab/pytmbot.git
   cd ./pytmbot
   ```

2. **Set Up the Virtual Environment and Install Dependencies**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Build the Docker Image**

   Before running the bot, you need to build the Docker image. Use the following command:

   ```bash
   docker build -t orenlab/pytmbot:self-build .
   ```

## 🧪 Configure the Bot

1. **Activate the Virtual Environment** and **Install Dependencies** as described above.

2. **Run the CLI Setup Wizard** to configure the bot:

   ```bash
   python3 ./setup_bot.py
   ```

   Follow the prompts in the wizard to generate the necessary configuration file. The wizard will create a configuration
   file named `pytmbot.yaml`.

   You can accept the default settings by pressing "Enter" when prompted.

## 💰 Run the Bot

### Using Docker Compose

1. **Create a `docker-compose.yml` File**

   ```yaml
   version: '3.8'

   services:
     pytmbot:
       image: orenlab/pytmbot:self-build
       container_name: pytmbot
       restart: always
       environment:
         - TZ=Asia/Yekaterinburg
       volumes:
         - /var/run/docker.sock:/var/run/docker.sock:ro
         - /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro
       security_opt:
         - no-new-privileges
       pid: host
       command: --log_level INFO --mode prod
   ```

2. **Start the Container**

   ```bash
   docker-compose up -d
   ```

### Using Docker CLI

To start the bot directly with Docker CLI, use the following command:

```bash
sudo docker run -d \
-v /var/run/docker.sock:/var/run/docker.sock:ro \
-v /root/pytmbot.yaml:/opt/app/pytmbot.yaml:ro \
--env TZ="Asia/Yekaterinburg" \
--restart=always \
--name=pytmbot \
--pid=host \
--security-opt=no-new-privileges \
orenlab/pytmbot:self-build \
--log_level INFO --mode prod
```

### Supported Logging Levels

| # | Logging Level | Description                                                                                                             | Arguments           |
|---|---------------|-------------------------------------------------------------------------------------------------------------------------|---------------------|
| 1 | `INFO`        | Provides a balanced level of logging with essential information and a brief description of errors and exceptions.       | `--log_level=INFO`  |
| 2 | `ERROR`       | Displays only errors and exceptions, suitable for a quieter mode.                                                       | `--log_level=ERROR` |
| 3 | `DEBUG`       | Offers the most detailed logs, including all information from previous levels, along with additional debugging details. | `--log_level=DEBUG` |

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