#!/bin/bash
# (c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
# pyTMBot - A simple Telegram bot to handle Docker containers and images,
# also providing basic information about the status of local servers.
set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Minimum Python version required
REQUIRED_PYTHON="3.12.0"

# GitHub repository URL for the bot
GITHUB_REPO="https://github.com/orenlab/pytmbot.git"

# Bot service name
SERVICE_NAME="pytmbot"

cd /opt/ || exit 1

# Log file path
LOG_FILE="/var/log/pytmbot_install.log"

# Spinner for progress indication
show_spinner() {
  local pid=$1
  local delay=0.1
  local spinstr="|/-\""
  while ps -p "$pid" > /dev/null; do
    local temp=${spinstr#?}
    printf " [%c]  " "$spinstr"
    spinstr=$temp${spinstr%"$temp"}
    sleep $delay
    printf "\b\b\b\b\b\b"
  done
  printf "    \b\b\b\b"
}

# Function to check if the script is running as root
check_root() {
  if ! sudo -n true 2>/dev/null; then
    echo -e "${RED}This script requires root privileges. Please use 'sudo' or switch to a user with appropriate permissions.${NC}" | tee -a "$LOG_FILE"
    exit 1
  fi
}

# Function to check if a command exists
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Function to create user pytmbot and add to docker group
create_pytmbot_user() {
  echo -e "${GREEN}Ensuring user 'pytmbot' exists and is in the 'docker' group...${NC}" | tee -a "$LOG_FILE"

  # Check if user 'pytmbot' exists, if not, create it
  if ! id "pytmbot" &>/dev/null; then
    echo "Creating user 'pytmbot'..." | tee -a "$LOG_FILE"
    useradd --system --no-create-home --shell /usr/sbin/nologin pytmbot
    mkdir -p /opt/pytmbot && chown pytmbot:pytmbot /opt/pytmbot
    echo "User 'pytmbot' created successfully." | tee -a "$LOG_FILE"
  else
    echo "User 'pytmbot' already exists." | tee -a "$LOG_FILE"
  fi

  # Check if Docker is installed
  if ! command_exists docker; then
    read -r -p "${RED}Docker is not installed. Would you like to install Docker? [y/N]: ${NC}" install_docker
    if [[ "${install_docker,,}" =~ ^[y]$ ]]; then
      install_docker_app
    else
      echo -e "${RED}Docker is required for pyTMBot. Aborting installation.${NC}" | tee -a "$LOG_FILE"
      exit 1
    fi
  else
    echo "Docker is already installed." | tee -a "$LOG_FILE"
  fi

  # Check if user 'pytmbot' is already in the 'docker' group
  if groups pytmbot | grep &>/dev/null '\bdocker\b'; then
    echo "User 'pytmbot' is already in the 'docker' group." | tee -a "$LOG_FILE"
  else
    # Add user 'pytmbot' to the 'docker' group
    echo "Adding user 'pytmbot' to the 'docker' group..." | tee -a "$LOG_FILE"
    usermod -aG docker pytmbot
    echo "User 'pytmbot' added to the 'docker' group." | tee -a "$LOG_FILE"
  fi

  echo -e "${GREEN}User 'pytmbot' created and added to 'docker' group successfully.${NC}" | tee -a "$LOG_FILE"
}

# Function to check the Python version
check_python_version() {
  echo -e "${GREEN}Checking Python version...${NC}" | tee -a "$LOG_FILE"

  (
    # Get the Python version
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')

    # Check if the Python version was determined
    if [[ -z "$PYTHON_VERSION" ]]; then
      echo -e "${RED}Unable to determine Python version. Please ensure Python is installed.${NC}" | tee -a "$LOG_FILE"
      exit 1
    fi

    # Compare the installed Python version with the required version
    if [[ "$(printf '%s\n' "$REQUIRED_PYTHON" "$PYTHON_VERSION" | sort -V | head -n1)" == "$REQUIRED_PYTHON" ]]; then
      echo -e "${GREEN}Python version $PYTHON_VERSION is sufficient for pyTMBot.${NC}" | tee -a "$LOG_FILE"
    else
      echo -e "${RED}Python version $PYTHON_VERSION is too old. Required version is $REQUIRED_PYTHON or newer.${NC}" | tee -a "$LOG_FILE"
      read -r -p "Would you like to install Python 3.12? [y/N]: " install_python
      if [[ "${install_python,,}" =~ ^[y]$ ]]; then
        install_python_user
      else
        echo -e "${RED}Python 3.12 is required for pyTMBot. Aborting installation.${NC}" | tee -a "$LOG_FILE"
        exit 1
      fi
    fi
  ) &

  show_spinner $!
  echo -e "${GREEN}Done!${NC}" | tee -a "$LOG_FILE"
}

# Function to check and install Python 3.12 if needed
install_python_user() {
  echo -e "${GREEN}Checking for Python installation...${NC}" | tee -a "$LOG_FILE"

  if command_exists python3.12; then
    echo -e "${GREEN}Python 3.12 is already installed.${NC}" | tee -a "$LOG_FILE"
    return
  fi

  echo -e "${GREEN}Installing Python 3.12...${NC}" | tee -a "$LOG_FILE"

  (
    case "$(grep -oP '(?<=^ID=).+' /etc/os-release)" in
      ubuntu|debian)
        if ! grep -q '^deb .*/deadsnakes' /etc/apt/sources.list /etc/apt/sources.list.d/*; then
          echo -e "${YELLOW}Adding deadsnakes PPA...${NC}" | tee -a "$LOG_FILE"
          add-apt-repository ppa:deadsnakes/ppa -y >> "$LOG_FILE" 2>&1
        fi
        apt-get update -y >> "$LOG_FILE" 2>&1
        apt-get install -y python3.12 python3.12-venv python3.12-dev >> "$LOG_FILE" 2>&1
        ;;
      centos|rhel|fedora)
        dnf install -y python3.12 >> "$LOG_FILE" 2>&1
        ;;
      arch)
        pacman -Syu --noconfirm python >> "$LOG_FILE" 2>&1
        ;;
      *)
        echo -e "${RED}Unsupported OS. Please install Python 3.12 manually.${NC}" | tee -a "$LOG_FILE"
        exit 1
        ;;
    esac
  ) &

  show_spinner $!
  echo -e "${GREEN}Done! Python 3.12 installed successfully.${NC}" | tee -a "$LOG_FILE"
}

# Function to create a Python virtual environment and install dependencies
setup_virtualenv() {
  echo -e "${GREEN}Setting up Python virtual environment...${NC}" | tee -a "$LOG_FILE"

  local python_cmd
  if command_exists python3.12; then
    python_cmd=python3.12
  else
    python_cmd=python3
  fi

  if ! command_exists pip3; then
    echo -e "${RED}Pip3 is required but not installed.${NC}" | tee -a "$LOG_FILE"
    exit 1
  fi

  if ! command_exists virtualenv; then
    echo -e "${YELLOW}Virtualenv is not installed. Installing...${NC}" | tee -a "$LOG_FILE"
    (
      pip3 install -U virtualenv >> "$LOG_FILE" 2>&1
    ) &
    show_spinner $!
    echo -e "${GREEN}Done!${NC}" | tee -a "$LOG_FILE"
  fi

  printf %s"Creating virtual environment...${NC} "
  (
    virtualenv -p "$python_cmd" ./pytmbot/venv >> "$LOG_FILE" 2>&1
  ) &
  show_spinner $!
  printf %s "${GREEN}Done!${NC}\n" | tee -a "$LOG_FILE"

  echo -e "Activating virtual environment...${NC}" | tee -a "$LOG_FILE"
  # shellcheck disable=SC1091
  source ./pytmbot/venv/bin/activate

  echo -e "Updating pip and setuptools...${NC}" | tee -a "$LOG_FILE"
  (
    pip install -U pip setuptools >> "$LOG_FILE" 2>&1
  ) &
  show_spinner $!
  echo -e "${GREEN}Done!${NC}" | tee -a "$LOG_FILE"

  echo -e "Installing Python dependencies from requirements.txt...${NC}" | tee -a "$LOG_FILE"
  (
    pip install -r ./pytmbot/requirements.txt >> "$LOG_FILE" 2>&1
  ) &
  show_spinner $!
  echo -e "${GREEN}Done!${NC}" | tee -a "$LOG_FILE"

  echo -e "${GREEN}Python virtual environment setup completed successfully.${NC}" | tee -a "$LOG_FILE"
}

# Function to create systemd service file for the bot
create_service() {
  echo -e "${GREEN}Starting the creation/updating of the systemd service...${NC}" | tee -a "$LOG_FILE"
  SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

  # Check if the service file already exists
  if [ -f "$SERVICE_FILE" ]; then
    echo -e "${YELLOW}Service file already exists at $SERVICE_FILE. Updating the existing service...${NC}" | tee -a "$LOG_FILE"
  else
    echo -e "${GREEN}Service file does not exist. Creating a new service file at $SERVICE_FILE...${NC}" | tee -a "$LOG_FILE"
  fi

  # Prompt user for plugins to run
  echo -e "${GREEN}Please select the plugins to run (comma-separated):${NC}" | tee -a "$LOG_FILE"
  echo -e "1) outline\n2) monitor" | tee -a "$LOG_FILE"
  read -r -p "Enter your choice (1, 2 or 1,2): " plugin_choice

  # Prepare the plugin options
  case "$plugin_choice" in
    1) plugins="outline" ;;
    2) plugins="monitor" ;;
    1,2) plugins="outline,monitor" ;;
    *)
      echo -e "${RED}Invalid choice. No plugins will be set.${NC}" | tee -a "$LOG_FILE"
      plugins="" # No plugins selected
      ;;
  esac

  # Prompt user for logging level
  echo -e "${GREEN}Please select the logging level (INFO, ERROR, DEBUG):${NC}" | tee -a "$LOG_FILE"
  read -r -p "Enter your choice: " log_level

  # Validate logging level
  case "$log_level" in
    INFO|ERROR|DEBUG) ;;
    *)
      echo -e "${RED}Invalid logging level. Defaulting to INFO.${NC}" | tee -a "$LOG_FILE"
      log_level="INFO" # Default logging level
      ;;
  esac

  # Create or update the service file
  {
    cat << EOF > "$SERVICE_FILE"
[Unit]
Description=pyTMBot Service
After=network.target docker.service
Requires=docker.service

[Service]
User=pytmbot
Group=docker
WorkingDirectory=/opt/pytmbot
ExecStart=/usr/bin/env PYTHONUNBUFFERED=1 PYTHONPATH=/opt/pytmbot /opt/pytmbot/venv/bin/python3.12 /opt/pytmbot/main.py${plugins:+ --plugins $plugins} --log-level $log_level
Restart=on-failure
RestartSec=5
Environment=PATH=/opt/pytmbot/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
StandardOutput=append:/var/log/pytmbot.log
StandardError=append:/var/log/pytmbot_error.log

# Security options
ProtectSystem=full
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
  } >> "$LOG_FILE" 2>&1

  echo -e "${GREEN}Service file successfully created/updated at $SERVICE_FILE.${NC}" | tee -a "$LOG_FILE"
}

# Function to install Docker app
install_docker_app() {
  echo -e "${GREEN}Setting up Docker container...${NC}" | tee -a "$LOG_FILE"

  if ! command_exists docker; then
    echo -e "${YELLOW}Docker is not installed. Installing Docker...${NC}" | tee -a "$LOG_FILE"
    {
      curl -fsSL https://get.docker.com | bash
    } >> "$LOG_FILE" 2>&1 &

    show_spinner $!
    echo -e "${GREEN}Docker installed successfully.${NC}" | tee -a "$LOG_FILE"
  else
    echo -e "${GREEN}Docker is already installed.${NC}" | tee -a "$LOG_FILE"
  fi
}

configure_bot() {
  CONFIG_FILE="/opt/pytmbot/pytmbot.yaml"

  echo "Configuring pyTMBot..." | tee -a "$LOG_FILE"
  echo "We need some information to configure the bot from you. Let's get started..." | tee -a "$LOG_FILE"

  # Prompt for bot tokens
  read -r -p "Enter your production bot token: " prod_token
  read -r -p "Enter your development bot token (optional): " dev_token
  read -r -p "Enter your global chat ID for notifications: " global_chat_id
  read -r -p "Enter allowed user ID(s) (comma-separated): " allowed_user_ids
  read -r -p "Enter allowed admin ID(s) (comma-separated): " allowed_admins_ids
  read -r -p "Enter auth salt (default: 'QD5CODUFY3FAMAA7DZX7WMNUTHLA===='): " auth_salt
  auth_salt="${auth_salt:-QD5CODUFY3FAMAA7DZX7WMNUTHLA====}"

  # Convert allowed_user_ids and allowed_admins_ids into YAML format
  allowed_user_ids_yaml=$(echo "$allowed_user_ids" | tr ',' '\n' | sed 's/^/    - /')
  allowed_admins_ids_yaml=$(echo "$allowed_admins_ids" | tr ',' '\n' | sed 's/^/    - /')

  # Prompt for Docker settings
  read -r -p "Enter Docker socket (default: 'unix:///var/run/docker.sock'): " docker_host
  docker_host="${docker_host:-unix:///var/run/docker.sock}"

  # Prompt for monitoring thresholds
  read -r -p "Enter CPU usage threshold (default: 80): " cpu_threshold
  cpu_threshold="${cpu_threshold:-80}"
  read -r -p "Enter memory usage threshold (default: 80): " memory_threshold
  memory_threshold="${memory_threshold:-80}"
  read -r -p "Enter disk usage threshold (default: 80): " disk_threshold
  disk_threshold="${disk_threshold:-80}"
  read -r -p "Enter CPU temperature threshold (default: 85): " cpu_temp_threshold
  cpu_temp_threshold="${cpu_temp_threshold:-85}"
  read -r -p "Enter GPU temperature threshold (default: 90): " gpu_temp_threshold
  gpu_temp_threshold="${gpu_temp_threshold:-90}"
  read -r -p "Enter disk temperature threshold (default: 60): " disk_temp_threshold
  disk_temp_threshold="${disk_temp_threshold:-60}"
  read -r -p "Enter monitoring check interval in seconds (default: 2): " check_interval
  check_interval="${check_interval:-2}"

  # Write configuration to the YAML file
  cat << EOF > "$CONFIG_FILE"
# Setup bot tokens
bot_token:
  # Prod bot token.
  prod_token:
    - '$prod_token'
  # Development bot token. Not necessary for production bot.
  dev_bot_token:
    - '$dev_token'

# Setup chat ID
chat_id:
  # Global chat ID. Used for all notifications from plugin.
  global_chat_id:
    - '$global_chat_id'

# Setup access control
access_control:
  # The ID of the users who have permission to access the bot.
  # You can have one or more values - there are no restrictions.
  allowed_user_ids:
$allowed_user_ids_yaml
  # The ID of the admins who have permission to access the bot.
  # You can have one or more values, there are no restrictions.
  # However, it's important to keep in mind that these users will be able to manage Docker images and containers.
  allowed_admins_ids:
$allowed_admins_ids_yaml
  # Salt is used to generate TOTP (Time-Based One-Time Password) secrets and to verify the TOTP code.
  auth_salt:
    - '$auth_salt'

# Docker settings
docker:
  # Docker socket. Usually: unix:///var/run/docker.sock.
  host:
    - '$docker_host'

# Plugins configuration
plugins_config:
  # Configuration for Monitor plugin
  monitor:
    # Tracehold settings
    tracehold:
      # CPU usage thresholds in percentage
      cpu_usage_threshold:
        - $cpu_threshold
      # Memory usage thresholds in percentage
      memory_usage_threshold:
        - $memory_threshold
      # Disk usage thresholds in percentage
      disk_usage_threshold:
        - $disk_threshold
      # CPU temperature thresholds in Celsius
      cpu_temperature_threshold:
        - $cpu_temp_threshold
      # GPU temperature thresholds in Celsius
      gpu_temperature_threshold:
        - $gpu_temp_threshold
      # Disk temperature thresholds in Celsius
      disk_temperature_threshold:
        - $disk_temp_threshold
    # Number of notifications to send for each type of overload
    max_notifications:
      - 3
    # Check interval in seconds
    check_interval:
      - $check_interval
    # Reset notification count after X minutes
    reset_notification_count:
      - 5
    # Number of attempts to retry starting monitoring in case of failure
    retry_attempts:
      - 3
    # Interval (in seconds) between retry attempts
    retry_interval:
      - 10
  # Configuration for Outline plugin
  outline:
    # Outline API settings
    api_url:
      - ''
    cert:
      - ''
EOF

  echo "Configuration written to $CONFIG_FILE." | tee -a "$LOG_FILE"
}

clone_repo() {
    # Clone the repository
  echo -n "Cloning the repository..." | tee -a "$LOG_FILE"
  (
    git clone "$GITHUB_REPO" /opt/pytmbot >> "$LOG_FILE" 2>&1
    cd /opt/pytmbot || { echo -e "${RED}Failed to enter directory.${NC}" | tee -a "$LOG_FILE"; exit 1; }
  ) &
  show_spinner $!
  echo -e "${GREEN} Done!${NC}" | tee -a "$LOG_FILE"
}

install_local() {
  echo -e "${GREEN}Starting local installation...${NC}" | tee -a "$LOG_FILE"

  # Create the pytmbot user and add to docker group
  create_pytmbot_user

  echo -n "Installing required packages..." | tee -a "$LOG_FILE"
  (
    if [ -f /etc/debian_version ]; then
      apt-get update -y >> "$LOG_FILE" 2>&1
      apt-get install -y python3 python3-pip git >> "$LOG_FILE" 2>&1
    elif [ -f /etc/redhat-release ]; then
      yum install -y python3 python3-pip git >> "$LOG_FILE" 2>&1
    elif [ -f /etc/arch-release ]; then
      pacman -Syu --noconfirm >> "$LOG_FILE" 2>&1
      pacman -S --noconfirm python python-pip git >> "$LOG_FILE" 2>&1
    else
      echo -e "${RED}Unsupported operating system.${NC}" | tee -a "$LOG_FILE"
      exit 1
    fi
  ) &
  show_spinner $!
  echo -e "${GREEN} Done!${NC}" | tee -a "$LOG_FILE"

  # Clone the repository
  clone_repo

  # Check Python version
  check_python_version

  # Setup virtual environment
  setup_virtualenv

  # Configure bot settings
  configure_bot

  # Create systemd service
  create_service

  # Reload systemd and start the service
  echo -e "${GREEN}Reloading systemd and starting the service...${NC}" | tee -a "$LOG_FILE"
  (
      # shellcheck disable=SC2129
      systemctl daemon-reload >> "$LOG_FILE" 2>&1
      systemctl start "$SERVICE_NAME" >> "$LOG_FILE" 2>&1
      systemctl enable "$SERVICE_NAME" >> "$LOG_FILE" 2>&1
  ) &
  show_spinner $!
  echo -e "${GREEN} Done!${NC}" | tee -a "$LOG_FILE"

  echo -e "${GREEN}Local installation completed. Service '$SERVICE_NAME' is running.${NC}" | tee -a "$LOG_FILE"
}

uninstall_pytmbot() {
  echo -e "${GREEN}Starting uninstallation process...${NC}" | tee -a "$LOG_FILE"

  # Check if service exists and is loaded
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo -e "Stopping the service...${NC}" | tee -a "$LOG_FILE"
    (
    systemctl stop "$SERVICE_NAME" >> "$LOG_FILE" 2>&1
    ) & show_spinner $!
    echo -e "${GREEN}Done!${NC}" | tee -a "$LOG_FILE"
  fi

  if systemctl is-enabled --quiet "$SERVICE_NAME"; then
    echo -e "Disabling the service...${NC}" | tee -a "$LOG_FILE"
    (
    systemctl disable "$SERVICE_NAME" >> "$LOG_FILE" 2>&1
    ) & show_spinner $!
    echo -e "${GREEN}Done!${NC}" | tee -a "$LOG_FILE"
  fi

  if [ -f "/etc/systemd/system/$SERVICE_NAME.service" ]; then
    echo -e "Removing systemd service...${NC}" | tee -a "$LOG_FILE"
    (
    rm -f "/etc/systemd/system/$SERVICE_NAME.service" >> "$LOG_FILE" 2>&1
    ) & show_spinner $!
    echo -e "${GREEN}Done!${NC}" | tee -a "$LOG_FILE"

    # Reload systemd daemon after removing the service file
    echo -e "Reloading systemd daemon...${NC}" | tee -a "$LOG_FILE"
    systemctl daemon-reload >> "$LOG_FILE" 2>&1 &
    show_spinner $!
    echo -e "${GREEN}Done!${NC}" | tee -a "$LOG_FILE"
  else
    echo -e "${YELLOW}Service $SERVICE_NAME not found. Skipping.${NC}" | tee -a "$LOG_FILE"
  fi

  # Remove bot files and virtual environment
  if [ -d "/opt/pytmbot" ]; then
    echo -e "${GREEN}Removing bot files from /opt/pytmbot...${NC}" | tee -a "$LOG_FILE"
    (
    rm -rf /opt/pytmbot >> "$LOG_FILE" 2>&1
    ) & show_spinner $!
    echo -e "${GREEN}Done!${NC}" | tee -a "$LOG_FILE"
  else
    echo -e "${YELLOW}Bot files not found in /opt/pytmbot. Skipping.${NC}" | tee -a "$LOG_FILE"
  fi

  # Check if user exists and delete it
  if id "pytmbot" &>/dev/null; then
    echo -e "Removing user 'pytmbot'...${NC}" | tee -a "$LOG_FILE"
    (
    userdel pytmbot >> "$LOG_FILE" 2>&1
    ) & show_spinner $!
    echo -e "${GREEN}Done!${NC}" | tee -a "$LOG_FILE"
  else
    echo -e "${YELLOW}User 'pytmbot' not found. Skipping.${NC}" | tee -a "$LOG_FILE"
  fi

  # Ask user if they want to remove logs
  read -r -p "Do you want to remove log files (/var/log/pytmbot.log, pytmbot_install.log, pytmbot_error.log)? [y/N]: " remove_logs

  if [[ "$remove_logs" =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}Removing log files...${NC}" | tee -a "$LOG_FILE"
    (
    rm -f /var/log/pytmbot.log /var/log/pytmbot_install.log /var/log/pytmbot_error.log >> "$LOG_FILE" 2>&1
    ) & show_spinner $!
    echo -e "${GREEN}Done!${NC}" | tee -a "$LOG_FILE"
  else
    echo -e "${YELLOW}Log files retained.${NC}" | tee -a "$LOG_FILE"
  fi

  echo -e "${GREEN}Uninstallation completed.${NC}" | tee -a "$LOG_FILE"
}

# Function to install Docker app
install_bot_in_docker() {
  echo -e "${GREEN}Setting up Docker container...${NC}" | tee -a "$LOG_FILE"

  # Check if Docker is installed
  if ! command_exists docker; then
    echo -e "${YELLOW}Docker is not installed. Installing Docker...${NC}" | tee -a "$LOG_FILE"
    install_docker_app >> "$LOG_FILE" 2>&1
  fi

  read -r -p "Do you want to use a pre-built Docker image (1) or build from source (2)? [1/2]: " choice

  if [[ "$choice" == "1" ]]; then
    echo -e "${GREEN}Using pre-built Docker image...${NC}" | tee -a "$LOG_FILE"

    if [ -d "/opt/pytmbot" ]; then
      echo -e "${GREEN}Removing existing bot files from /opt/pytmbot...${NC}" | tee -a "$LOG_FILE"
      rm -rf /opt/pytmbot || { echo -e "${RED}Failed to remove /opt/pytmbot.${NC}" | tee -a "$LOG_FILE"; exit 1; }
      echo -e "${GREEN}Old bot files removed successfully!${NC}" | tee -a "$LOG_FILE"
    fi

    create_pytmbot_user

    echo -e "${GREEN}Creating bot directory at /opt/pytmbot...${NC}" | tee -a "$LOG_FILE"
    mkdir -p /opt/pytmbot || { echo -e "${RED}Failed to create directory /opt/pytmbot.${NC}" | tee -a "$LOG_FILE"; exit 1; }

    configure_bot

    echo -e "${GREEN}Creating docker-compose.yml file...${NC}" | tee -a "$LOG_FILE"
    cat << EOF > /opt/pytmbot/docker-compose.yml
services:
  pytmbot:
    image: orenlab/pytmbot:v0.2.0-rc2
    container_name: pytmbot
    restart: always
    environment:
      - TZ=Asia/Yekaterinburg
    user: pytmbot
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "/opt/pytmbot/pytmbot.yaml:/opt/app/pytmbot.yaml:ro"
    security_opt:
      - no-new-privileges
    logging:
      options:
        max-size: "10m"
        max-file: "3"
    pid: host
    command: --plugins monitor
EOF

    echo -e "${GREEN}docker-compose.yml created successfully.${NC}" | tee -a "$LOG_FILE"

    echo -e "${GREEN}Starting the Docker container...${NC}" | tee -a "$LOG_FILE"
    (
      cd /opt/pytmbot || exit 1
      docker compose up -d
    ) >> "$LOG_FILE" 2>&1

    # shellcheck disable=SC2181
    if [[ $? -eq 0 ]]; then
      echo -e "${GREEN}Docker container started successfully.${NC}" | tee -a "$LOG_FILE"
    else
      echo -e "${RED}Failed to start Docker container.${NC}" | tee -a "$LOG_FILE"
      exit 1
    fi

  elif [[ "$choice" == "2" ]]; then
    echo -e "${GREEN}Building from source...${NC}" | tee -a "$LOG_FILE"
    clone_repo

    cd /opt/pytmbot || { echo -e "${RED}Failed to enter directory.${NC}" | tee -a "$LOG_FILE"; exit 1; }

    configure_bot

    echo -e "${GREEN}Starting the Docker container...${NC}" | tee -a "$LOG_FILE"
    (
      docker compose up -d
    ) >> "$LOG_FILE" 2>&1

    # shellcheck disable=SC2181
    if [[ $? -eq 0 ]]; then
      echo -e "${GREEN}Docker container started successfully.${NC}" | tee -a "$LOG_FILE"
    else
      echo -e "${RED}Failed to start Docker container.${NC}" | tee -a "$LOG_FILE"
      exit 1
    fi

  else
    echo -e "${RED}Invalid option. Aborting installation.${NC}" | tee -a "$LOG_FILE"
    exit 1
  fi
}

# Check if script is run as root
check_root

# Choose installation method with descriptions
echo -e "${GREEN}Choose installation method:${NC}" | tee -a "$LOG_FILE"
echo "1. Docker installation - Run the bot inside a Docker container for easy management and isolation." | tee -a "$LOG_FILE"
echo "2. Local installation - Provides more control and flexibility, as it runs directly on the system without process isolation." | tee -a "$LOG_FILE"
echo "3. Uninstall pyTMBot - Completely remove the bot and its files from your system." | tee -a "$LOG_FILE"
read -r -p "Enter the number (1, 2 or 3): " choice

case $choice in
  1)
    echo -e "${GREEN}#############################################################################${NC}" | tee -a "$LOG_FILE"
    install_bot_in_docker  # Docker installation
    echo -e "${GREEN}#############################################################################${NC}" | tee -a "$LOG_FILE"
    ;;
  2)
    echo -e "${YELLOW}#############################################################################${NC}" | tee -a "$LOG_FILE"
    install_local  # Local installation
    echo -e "${YELLOW}#############################################################################${NC}" | tee -a "$LOG_FILE"
    ;;
  3)
    echo -e "${RED}#############################################################################${NC}" | tee -a "$LOG_FILE"
    uninstall_pytmbot  # Uninstall the bot
    echo -e "${RED}#############################################################################${NC}" | tee -a "$LOG_FILE"
    ;;
  *)
    echo -e "${RED}Invalid choice. Please choose 1, 2, or 3.${NC}" | tee -a "$LOG_FILE"
    exit 1
    ;;
esac