# pyTMBot installation and setup guide

## 🔌 Installation

To install this project:

```bash
  git clone https://github.com/orenlab/pytmbot.git
  cd ~/pytmbot
```

## 🧪 Configure bot

1. Activate the virtual environment and install the dependencies using your preferred package manager.
   The following instructions provide an example using pip (__mandatory stage__):

```bash
python -m venv .venv
source ~/pytmbot/.venv/bin/activate
pip install -r setup_req.txt
```

2. Run the CLI Setup Wizard (__mandatory stage__):

```bash
python3 ./setup_bot.py
```

And follow the wizard's instructions.

This wizard will generate the necessary configuration files for you:

| Files                             | Assignment                                                                                       |
|-----------------------------------|--------------------------------------------------------------------------------------------------|
| .env                              | To store bot tokens                                                                              |
| app/core/settings/bot_settings.py | To store both settings, including the allowed user ID and paths to the Docker and Podman socket. |

You can leave the steps with the default settings by simply pressing "Enter".

3. Set your local TZ in `Dockerfile`:

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

*Also available in the root of the project is a Dockerfile based on the Ubuntu image: ubuntu.Dockerfile*

To launch a Docker container:

```bash
  sudo docker run -d -m 100M -v /var/run/docker.sock:/var/run/docker.sock:ro --restart=always --name=pytmbot --pid=host --security-opt=no-new-privileges orenlab/pytmbot:latest
```

Docker image size ~80,5 Мб.

## 🛠 Logs

To access to bot logs, please run in terminal:

```bash
  docker ps
```

And grap pyTMbot container id. Then, run:

```bash
  docker logs bot_contaner_id
```

Or use Docker Desktop (if run workstation)
