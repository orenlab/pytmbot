# pyTMBot installation and setup guide

## 🔌 Installation

To install this project:

```bash
  git clone https://github.com/orenlab/pytmbot.git
  cd ~/pytmbot
```

## 🪛 Configure bot

1. Run the CLI Setup Wizard (__mandatory stage__):

```bash
cd ~/pytmbot
python3 ./setup_bot.py
```

And follow the wizard's instructions.

This wizard will generate the necessary configuration files for you.
You can leave the steps with the default settings by simply pressing "Enter".

2. Set your local TZ in `Dockerfile`:

```dockerfile
ENV TZ="Asia/Yekaterinburg"
```

If needed, set log level and operational mode in `Dockerfile`:

```dockerfile
# run app
# !!! needed set log level:
#   - DEBUG
#   - INFO (default)
#   - ERROR
#   - CRITICAL
# !!! needed set pyTMBot mode:
#   - dev
#   - prod (default)
CMD [ "/venv/bin/python3", "app/main.py", "--log-level=INFO", "--mode=prod" ]
```

## 💰 Run bot

To build a Docker image:

```bash
  cd ~/pytmbot
  docker build -t orenlab/pytmbot:latest .
```

To launch a Docker container:

```bash
  docker run -d -m 100M --restart=always --name=pytmbot orenlab/pytmbot:latest
```
Docker image size ~80,5 Мб.

## 🛠 Logs

To access to bot logs, please run in terminal:

```bash
  docker logs bot_contaner_id
```

Or use Docker Desktop (if run workstation)