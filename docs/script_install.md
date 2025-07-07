# 📦 pyTMBot Installation Script

This script provides an easy way to install, manage, and uninstall the pyTMBot either inside a Docker container or
locally on your system. It also includes support for setting up a Python virtual environment for local installations.

## ✅ Requirements

- **Root privileges**: The script requires `sudo` or root access to install necessary system packages.
- **Supported Operating Systems**:
    - Ubuntu/Debian
    - CentOS/RHEL/Fedora
    - Arch Linux
- **Python 3.12** (automatically installed if not present)
- **Docker** (automatically installed if not present for Docker installation option)

## 📋 Pre-Installation Information

Before running the script, gather the following information:

### 🔑 Essential Information

1. **Telegram Bot Token**: Obtain from BotFather when creating your bot
2. **Allowed Telegram User IDs**: Valid Telegram user IDs (can be adjusted later via logs)
3. **Global Chat ID**: Send a message to your bot, then visit:
   ```
   https://api.telegram.org/bot<YourBotToken>/getUpdates
   ```
   Look for the `chat_id` in the JSON response.

### 🐳 Docker Configuration

4. **Docker Socket Path**: Default is `unix:///var/run/docker.sock`

### 🌐 Webhook Configuration (if applicable)

5. **Domain URL or Public IP**: For webhook mode
6. **SSL Certificate Path**: Path to SSL certificate file
7. **SSL Private Key Path**: Path to SSL private key file

### 📊 Monitor Plugin (InfluxDB)

8. **InfluxDB URL**: Address of your InfluxDB server
9. **Organization Name**: Your InfluxDB organization name
10. **Bucket Name**: The name of your InfluxDB bucket
11. **InfluxDB Token**: Your authorization token for InfluxDB

## ⚙️ Usage

### 🚀 Running the Script

To get the latest version of the script and run it:

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/orenlab/pytmbot/refs/heads/master/tools/install.sh)"
```

### 🛠️ Installation Options

When running the script, you will be prompted to choose one of the following options:

#### 1. **Docker Installation**

Runs pyTMBot inside a Docker container for easy management and isolation.

- **Features**: Process isolation, reduced dependency conflicts, easy management
- **Sub-options**:
    - Use pre-built Docker image (recommended)
    - Build from source
- **Requirements**: Docker and Docker Compose (automatically installed if missing)

#### 2. **Local Installation**

Installs pyTMBot directly on your system.

- **Features**: More control and flexibility, direct system integration
- **Process**:
    - Creates `pytmbot` system user
    - Installs Python 3.12 (if necessary)
    - Sets up virtual environment
    - Installs all required dependencies
    - Creates systemd service for automatic startup
- **Plugin Selection**: Choose between `outline`, `monitor`, or both
- **Logging Levels**: INFO, ERROR, or DEBUG

#### 3. **Update Local Installation**

Updates pyTMBot to the latest version.

- **Process**: Updates from GitHub repository
- **Note**: Review configuration file compatibility after updates
- **Service Management**: Option to automatically restart the service

#### 4. **Uninstall pyTMBot**

Completely removes the bot and its files from your system.

- **Removes**: Service files, bot files, virtual environment, user account
- **Optional**: Log file removal

## 🔧 Configuration Details

### 📝 Systemd Service

For local installations, the script creates a systemd service with:

- **User**: `pytmbot`
- **Group**: `docker`
- **Working Directory**: `/opt/pytmbot`
- **Security**: Enhanced security options including `ProtectSystem=full`
- **Logging**: Separate logs for stdout and stderr

### 🐳 Docker Compose

For Docker installations, creates a `docker-compose.yml` with:

- **Security**: Read-only filesystem, dropped capabilities, no new privileges
- **Networking**: Isolated network (`pytmbot_net`)
- **Health Checks**: Python process monitoring
- **Logging**: Size-limited JSON logs

## 📜 Logs and Monitoring

### 📊 Log Files

- **Installation Log**: `/var/log/pytmbot_install.log`
- **Application Log**: `/var/log/pytmbot.log` (local installation)
- **Error Log**: `/var/log/pytmbot_error.log` (local installation)
- **Docker Logs**: `docker logs pytmbot` (Docker installation)

### 🔍 Service Management

For local installations:

```bash
# Check service status
sudo systemctl status pytmbot

# Start/stop/restart service
sudo systemctl start pytmbot
sudo systemctl stop pytmbot
sudo systemctl restart pytmbot

# View logs
sudo journalctl -u pytmbot -f
```

For Docker installations:

```bash
# Check container status
docker ps -f name=pytmbot

# View logs
docker logs pytmbot -f

# Restart container
docker restart pytmbot
```

## ❗ Troubleshooting

### 🔧 Common Issues

- **Unsupported OS**: Manually install Python 3.12 if your OS is not supported
- **Permission Denied**: Ensure you are running the script with `sudo` or as root
- **Docker Issues**: Confirm Docker is installed and properly configured
- **Service Fails**: Check logs for detailed error information
- **Configuration Errors**: Verify all required fields are properly filled

### 🛠️ Manual Fixes

- **Python Version**: Script automatically handles Python 3.12 installation
- **Virtual Environment**: Automatically created in `/opt/pytmbot/venv`
- **Dependencies**: All requirements installed automatically
- **User Permissions**: `pytmbot` user automatically added to `docker` group

## 🚫 Uninstallation

### 🏠 Local Uninstallation

Run the script and choose option `4`:

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/orenlab/pytmbot/refs/heads/master/tools/install.sh)"
```

### 🐳 Docker Uninstallation

Remove the Docker container and images:

```bash
# Stop and remove container
sudo docker compose down

# Remove images (optional)
sudo docker rmi orenlab/pytmbot

# Clean up files
sudo rm -rf /opt/pytmbot
```

## 🔄 Updates

### 📦 Local Updates

- Use option `3` in the installation script
- Automatically pulls latest changes from GitHub
- Prompts for service restart
- Check configuration file compatibility

### 🐳 Docker Updates

```bash
cd /opt/pytmbot
sudo docker compose pull
sudo docker compose up -d
```