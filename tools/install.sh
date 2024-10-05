#!/bin/bash
# (c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
# pyTMBot - A simple Telegram bot to handle Docker containers and images,
# also providing basic information about the status of local servers.
set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Config file and sample file paths
CONFIG_FILE="/opt/pytmbot/pytmbot.yaml"
SAMPLE_FILE="/opt/pytmbot/pytmbot.yaml.sample"

# Minimum Python version required
REQUIRED_PYTHON="3.12.0"

# GitHub repository URL for the bot
GITHUB_REPO="https://github.com/orenlab/pytmbot.git"

# Bot service name
SERVICE_NAME="pytmbot"

# Utility function for logging
log_message() {
  local color="$1"
  local message="$2"
  echo -e "${color}${message}${NC}" | tee -a "$LOG_FILE"
}

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

# Function to display a banner
show_banner() {
    local action="$1"

    # Clear the terminal for better visibility
    clear

    # Create a stylish banner
    echo -e "${BLUE}######################################################################"
    echo -e "${GREEN}##                      pyTMBot Installer                          ##"
    echo -e "${BLUE}######################################################################"
    echo -e "${WHITE}  Starting the ${YELLOW}${action^^}${WHITE} process...${NC}"
    echo -e "${BLUE}######################################################################"
    echo ""
}

# Function to check if the script is running as root
check_root() {
  if ! sudo -n true 2>/dev/null; then
    log_message "$RED" "This script requires root privileges. Please use 'sudo' or switch to a user with appropriate permissions."
    exit 1
  fi
}


# Generate a random auth salt for the bot.
generate_auth_salt() {
  if ! command -v openssl &> /dev/null; then
    echo "Error: openssl is not installed. Please install it and try again." >&2
    echo "-QD5CODUFY3FAMAA7DZX7WMNUTHLA===="
  fi

  auth_salt=$(openssl rand -base64 32)

  auth_salt="${auth_salt}===="

  echo "-$auth_salt"
}

# Function to check if a command exists
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Function to create user pytmbot and add to docker group
create_pytmbot_user() {

  show_banner "Creating user"

  log_message "$GREEN" "Ensuring user 'pytmbot' exists and is in the 'docker' group..."

  # Check if user 'pytmbot' exists, if not, create it
  if ! id "pytmbot" &>/dev/null; then
    log_message "$YELLOW" "User 'pytmbot' does not exist. Creating..."
    useradd --system --no-create-home --shell /usr/sbin/nologin pytmbot
    mkdir -p /opt/pytmbot && chown pytmbot:pytmbot /opt/pytmbot
    log_message "$GREEN" "User 'pytmbot' created successfully."
  else
    log_message "$GREEN" "User 'pytmbot' already exists."
  fi

  # Check if Docker is installed
  if ! command_exists docker; then
    read -r -p "${RED}Docker is not installed. Would you like to install Docker? [y/N]: ${NC}" install_docker
    if [[ "${install_docker,,}" =~ ^[y]$ ]]; then
      install_docker_app
    else
      show_banner "cancelled installation"
      log_message "$RED" "Docker is required for pyTMBot. Aborting installation."
      exit 1
    fi
  else
    log_message "$GREEN" "Docker is already installed."
  fi

  # Check if user 'pytmbot' is already in the 'docker' group
  show_banner "Adding user to group 'docker'"
  if groups pytmbot | grep &>/dev/null '\bdocker\b'; then
    log_message "$GREEN" "User 'pytmbot' is already in the 'docker' group."
  else
    # Add user 'pytmbot' to the 'docker' group
    log_message "$YELLOW" "User 'pytmbot' is not in the 'docker' group. Adding..."
    usermod -aG docker pytmbot
    log_message "$GREEN" "User 'pytmbot' added to the 'docker' group successfully."
  fi

  log_message "$GREEN" "User and group created successfully."
}

# Function to check the Python version
check_python_version() {
  show_banner "Checking Python version"

  # Get the Python version
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')

    # Check if the Python version was determined
    if [[ -z "$PYTHON_VERSION" ]]; then
      log_message "$RED" "Unable to determine Python version. Please ensure Python is installed."
      exit 1
    fi

    # Compare the installed Python version with the required version
    if [[ "$(printf '%s\n' "$REQUIRED_PYTHON" "$PYTHON_VERSION" | sort -V | head -n1)" == "$REQUIRED_PYTHON" ]]; then
      log_message "$GREEN" "Python version $PYTHON_VERSION is sufficient for pyTMBot."
    else
      log_message "$RED" "Python version $PYTHON_VERSION is not sufficient for pyTMBot. Required version is $REQUIRED_PYTHON or newer."
      read -r -p "Would you like to install Python 3.12 in user environment? [y/N]: " install_python
      if [[ "${install_python,,}" =~ ^[y]$ ]]; then
        install_python_user
      else
        log_message "$RED" "Python 3.12 is required for pyTMBot. Aborting installation."
        exit 1
      fi
    fi
}

# Function to check and install Python 3.12 if needed
install_python_user() {
  show_banner "Installing Python 3.12 in user env"

  if command_exists python3.12; then
    log_message "$GREEN" "Python 3.12 is already installed."
    return
  fi

  log_message "$YELLOW" "Python 3.12 is not installed. Installing..."

  (
    case "$(grep -oP '(?<=^ID=).+' /etc/os-release)" in
      ubuntu|debian)
        if ! grep -q '^deb .*/deadsnakes' /etc/apt/sources.list /etc/apt/sources.list.d/*; then
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
        log_message "$RED" "Unsupported OS. Please install Python 3.12 manually."
        exit 1
        ;;
    esac
  ) &

  show_spinner $!
  log_message "$GREEN" "Python 3.12 installed successfully."
}

# Function to create a Python virtual environment and install dependencies
setup_virtualenv() {
  show_banner "dependencies installation"

  log_message "$GREEN" "Setting up Python virtual environment..."
  (
    local python_cmd
    if command_exists python3.12; then
      python_cmd=python3.12
    else
      python_cmd=python3
    fi

    if ! command_exists pip3; then
      log_message "$RED" "Pip3 is required but not installed."
      exit 1
    fi

    if ! command_exists virtualenv; then
        pip3 install -U virtualenv >> "$LOG_FILE" 2>&1
    fi
    virtualenv -p "$python_cmd" ./pytmbot/venv >> "$LOG_FILE" 2>&1

    source ./pytmbot/venv/bin/activate

    pip install -U pip setuptools >> "$LOG_FILE" 2>&1

    pip install -r ./pytmbot/requirements.txt >> "$LOG_FILE" 2>&1

    log_message "$GREEN" "Dependencies installed successfully."
  )&
  show_spinner $!
  log_message "$GREEN" "Done!"
}

# Function to create systemd service file for the bot
create_service() {

  show_banner "Creating systemd service file"

  SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

  # Check if the service file already exists
  if [ -f "$SERVICE_FILE" ]; then
    log_message "$YELLOW" "Service file already exists at $SERVICE_FILE. Updating the existing service..."
  else
    log_message "$GREEN" "Service file does not exist. Creating a new service file at $SERVICE_FILE..."
  fi

  # Prompt user for plugins to run
  log_message "$GREEN" "Please select the plugins to run (comma-separated):"
  echo ""
  log_message "$GREEN" "1) outline\n2) monitor"
  echo ""
  read -r -p "Enter your choice (1, 2 or 1,2): " plugin_choice

  # Prepare the plugin options
  case "$plugin_choice" in
    1) plugins="outline" ;;
    2) plugins="monitor" ;;
    1,2) plugins="outline,monitor" ;;
    *)
      log_message "$RED" "Invalid choice. No plugins will be set."
      plugins="" # No plugins selected
      ;;
  esac

  # Prompt user for logging level
  log_message "$GREEN" "Please select the logging level (INFO, ERROR, DEBUG):"
  echo ""
  read -r -p "Enter your choice: " log_level

  # Validate logging level
  case "$log_level" in
    INFO|ERROR|DEBUG) ;;
    *)
      log_message "$RED" "Invalid logging level. Defaulting to INFO."
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

  log_message "$GREEN" "Service file created/updated successfully at $SERVICE_FILE."
}

# Function to install Docker app
install_docker_app() {

  show_banner "Docker installation"

  if ! command_exists docker; then
    log_message "YELLOW" "Docker is not installed. Installing Docker..."
    (
      curl -fsSL https://get.docker.com | bash >> "$LOG_FILE" 2>&1
    ) & show_spinner $! && log_message "$GREEN" "Done!"
  else
    log_message "$GREEN" "Docker is already installed. Skipping..."
  fi
}

configure_bot() {

  show_banner "Configuring pyTMBot..."

  log_message "$YELLOW" "We need some information to configure the bot from you. Let's get started..."
  echo ""

  # Prompt for bot tokens
  read -r -p "Enter your production bot token: " prod_token
  read -r -p "Enter your development bot token (optional): " dev_token
  read -r -p "Enter your global chat ID for notifications (-0000000000): " global_chat_id

  # Prompt for allowed user and admin IDs
  read -r -p "Enter allowed user ID(s) (comma-separated): " allowed_user_ids
  read -r -p "Enter allowed admin ID(s) (comma-separated): " allowed_admins_ids

  # Prepare YAML for allowed user and admin IDs
  allowed_user_ids_yaml=$(echo "$allowed_user_ids" | tr ',' '\n' | sed 's/^/    - /')
  allowed_admins_ids_yaml=$(echo "$allowed_admins_ids" | tr ',' '\n' | sed 's/^/    - /')

  # Prompt for Docker settings
  read -r -p "Enter Docker socket (default: 'unix:///var/run/docker.sock'): " docker_host
  docker_host="${docker_host:-unix:///var/run/docker.sock}"

  # Prompt for Webhook settings
  read -r -p "Enter Webhook URL (default: 'https://yourdomain.com/webhook'): " webhook_url
  webhook_url="${webhook_url:-https://yourdomain.com/webhook}"
  read -r -p "Enter Webhook port (default: 443): " webhook_port
  webhook_port="${webhook_port:-443}"
  read -r -p "Enter Local port (default: 5001): " local_port
  local_port="${local_port:-5001}"
  read -r -p "Enter path to SSL certificate: " cert
  read -r -p "Enter path to SSL certificate key: " cert_key

  # Prompt for InfluxDB settings
  read -r -p "Enter InfluxDB URL (default: 'http://influxdb:8086'): " influxdb_url
  influxdb_url="${influxdb_url:-http://influxdb:8086}"
  if [ -z "$INFLUXDB_TOKEN" ]; then
    read -r -p "Enter InfluxDB token: " influxdb_token
  else
    influxdb_token="$INFLUXDB_TOKEN"
  fi
  read -r -p "Enter InfluxDB organization name (default: 'pytmbot_monitor'): " influxdb_org
  influxdb_org="${influxdb_org:-pytmbot_monitor}"
  read -r -p "Enter InfluxDB bucket name (default: 'pytmbot'): " influxdb_bucket
  influxdb_bucket="${influxdb_bucket:-pytmbot}"
  read -r -p "Enable InfluxDB debug mode? (true/false, default: false): " influxdb_debug
  influxdb_debug="${influxdb_debug:-false}"

  auth_salt=$(generate_auth_salt)

  # Update the configuration file
  sed -e "s/YOUR_PROD_BOT_TOKEN/$prod_token/" \
      -e "s/YOUR_DEV_BOT_TOKEN/$dev_token/" \
      -e "s/YOUR_CHAT_ID/$global_chat_id/" \
      -e "s|YOUR_AUTH_SALT|$auth_salt|" \
      -e "s|unix:///var/run/docker.sock|$docker_host|" \
      -e "s|YOUR_WEBHOOK_URL|$webhook_url|" \
      -e "s|YOUR_WEBHOOK_PORT|$webhook_port|" \
      -e "s|YOUR_LOCAL_PORT|$local_port|" \
      -e "s|YOUR_CERT_PATH|$cert|" \
      -e "s|YOUR_CERT_KEY_PATH|$cert_key|" \
      -e "s|YOUR_INFLUXDB_URL|$influxdb_url|" \
      -e "s|YOUR_INFLUXDB_TOKEN|$influxdb_token|" \
      -e "s|YOUR_INFLUXDB_ORG|$influxdb_org|" \
      -e "s|YOUR_INFLUXDB_BUCKET|$influxdb_bucket|" \
      -e "s|YOUR_INFLUXDB_DEBUG_MODE|$influxdb_debug|" \
      "$SAMPLE_FILE" > "$CONFIG_FILE"

  # Append allowed user and admin IDs to the config file
  sed -i "/allowed_user_ids:/r /dev/stdin" "$CONFIG_FILE" <<< "$allowed_user_ids_yaml"
  sed -i "/allowed_admins_ids:/r /dev/stdin" "$CONFIG_FILE" <<< "$allowed_admins_ids_yaml"

  unset INFLUXDB_TOKEN

  log_message "$GREEN" "Configuration written to $CONFIG_FILE."
}

clone_repo() {
  show_banner "Cloning pyTMBot repository..."

  log_message "$YELLOW" "Cloning pyTMBot repository..."
  (
    git clone "$GITHUB_REPO" /opt/pytmbot >> "$LOG_FILE" 2>&1
    cd /opt/pytmbot || { echo -e "${RED}Failed to enter directory.${NC}" | tee -a "$LOG_FILE"; exit 1; }
  ) & show_spinner $! && log_message "$GREEN" "Done!"
}

install_local() {
  show_banner "Installing locally..."

  # Create the pytmbot user and add to docker group
  create_pytmbot_user

  log_message "$YELLOW" "Installing required packages..."
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
      log_message "$RED" "Unsupported OS. Please install Python 3.12 manually."
      exit 1
    fi
  ) & show_spinner $! && log_message "$GREEN" "Done!"

  # Clone the repository
  clone_repo

  # Check Python version
  check_python_version

  # Setup virtual environment
  setup_virtualenv

  # Install required container InfluxDB
  log_message "$YELLOW" "Now we needed check if InfluxDB container exists. If it doesn't exist, we will create it."
  install_influxdb

  # Configure bot settings
  configure_bot

  # Create systemd service
  create_service

  # Reload systemd and start the service
  log_message "$YELLOW" "Reloading systemd and starting the service..."
  (
      # shellcheck disable=SC2129
      systemctl daemon-reload >> "$LOG_FILE" 2>&1
      systemctl start "$SERVICE_NAME" >> "$LOG_FILE" 2>&1
      systemctl enable "$SERVICE_NAME" >> "$LOG_FILE" 2>&1
  ) & show_spinner $! && log_message "$GREEN" "Done!"

  log_message "$GREEN" "Local installation completed. Service '$SERVICE_NAME' is running."
}

uninstall_pytmbot() {

  show_banner "Uninstalling pyTMBot..."

  # Check if service exists and is loaded
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    log_message "$YELLOW" "Stopping the service..."
    (
      systemctl stop "$SERVICE_NAME" >> "$LOG_FILE" 2>&1
    ) & show_spinner $! && log_message "$GREEN" "Done!"
  fi

  if systemctl is-enabled --quiet "$SERVICE_NAME"; then
    log_message "$YELLOW" "Disabling the service..."
    (
      systemctl disable "$SERVICE_NAME" >> "$LOG_FILE" 2>&1
    ) & show_spinner $! && log_message "$GREEN" "Done!"
  fi

  if [ -f "/etc/systemd/system/$SERVICE_NAME.service" ]; then
    log_message "$YELLOW" "Removing the service file..."
    (
      rm -f "/etc/systemd/system/$SERVICE_NAME.service" >> "$LOG_FILE" 2>&1
    ) & show_spinner $! && log_message "$GREEN" "Done!"

    # Reload systemd daemon after removing the service file
    log_message "$YELLOW" "Reloading systemd daemon..."
    (
      systemctl daemon-reload >> "$LOG_FILE" 2>&1 &
    ) & show_spinner $! && log_message "$GREEN" "Done!"
  else
    log_message "$YELLOW" "Service file not found. Skipping..."
  fi

  # Remove bot files and virtual environment
  if [ -d "/opt/pytmbot" ]; then
    log_message "$YELLOW" "Removing bot files from /opt/pytmbot..."
    (
      rm -rf /opt/pytmbot >> "$LOG_FILE" 2>&1
    ) & show_spinner $! && log_message "$GREEN" "Done!"
  else
    log_message "$YELLOW" "Bot files not found in /opt/pytmbot. Skipping..."
  fi

  # Check if user exists and delete it
  if id "pytmbot" &>/dev/null; then
    log_message "$YELLOW" "Removing user 'pytmbot'..."
    (
      userdel pytmbot >> "$LOG_FILE" 2>&1
    ) & show_spinner $! && log_message "$GREEN" "Done!"
  else
    log_message "$YELLOW" "User 'pytmbot' not found. Skipping..."
  fi

  # Ask user if they want to remove logs
  read -r -p "Do you want to remove log files (/var/log/pytmbot.log, pytmbot_install.log, pytmbot_error.log)? [y/N]: " remove_logs

  if [[ "$remove_logs" =~ ^[Yy]$ ]]; then
    log_message "$YELLOW" "Removing log files..."
    (
      rm -f /var/log/pytmbot.log /var/log/pytmbot_install.log /var/log/pytmbot_error.log >> "$LOG_FILE" 2>&1
    ) & show_spinner $! && log_message "$GREEN" "Done!"
  else
    log_message "$YELLOW" "Log files not removed. Skipping..."
  fi

  log_message "$GREEN" "Uninstallation completed."
}

# Function to install Docker app
install_bot_in_docker() {
  show_banner "Installing in Docker..."

  log_message "$GREEN" "Starting installation in Docker..."
  create_pytmbot_user

  # Check if Docker is installed
  if ! command_exists docker; then
    log_message "$YELLOW" "Docker is not installed. Installing Docker..."
    install_docker_app >> "$LOG_FILE" 2>&1
  fi

  read -r -p "Do you want to use a pre-built Docker image (1) or build from source (2)? [1/2]: " choice

  if [[ "$choice" == "1" ]]; then
    log_message "$GREEN" "Using pre-built Docker image..."

    if [ -d "/opt/pytmbot" ]; then
      log_message "$YELLOW" "Removing old bot files from /opt/pytmbot..."
      (
        rm -rf /opt/pytmbot || { log_message "$RED" "Failed to remove old bot files from /opt/pytmbot." | tee -a "$LOG_FILE"; exit 1; }
      ) & show_spinner $! && log_message "$GREEN" "Done!"
    fi

    create_pytmbot_user

    log_message "$YELLOW" "Creating bot directory at /opt/pytmbot..."
    mkdir -p /opt/pytmbot || { log_message "$RED" "Failed to create bot directory at /opt/pytmbot." | tee -a "$LOG_FILE"; exit 1; }

    configure_bot

    log_message "$GREEN" "Creating docker-compose.yml file..."
    cat << EOF > /opt/pytmbot/docker-compose.yml
services:
  pytmbot:
    image: orenlab/pytmbot:alpine-dev
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

    log_message "$GREEN" "docker-compose.yml file created successfully."

    log_message "$YELLOW" "Now we needed check if InfluxDB container exists. If it doesn't exist, we will create it."
    install_influxdb

    log_message "$GREEN" "Starting Docker container..."
    (
      cd /opt/pytmbot || exit 1
      docker compose up -d
    ) >> "$LOG_FILE" 2>&1

    # shellcheck disable=SC2181
    if [[ $? -eq 0 ]]; then
      log_message "$GREEN" "Docker container started successfully."
    else
      log_message "$RED" "Failed to start Docker container."
      exit 1
    fi

  elif [[ "$choice" == "2" ]]; then
    log_message "$GREEN" "Building Docker image from source..."
    clone_repo

    cd /opt/pytmbot || { log_message "$RED" "Failed to enter directory." | tee -a "$LOG_FILE"; exit 1; }

    configure_bot

    log_message "$GREEN" "Docker image built successfully. Starting Docker container..."
    (
      docker compose up -d
    ) >> "$LOG_FILE" 2>&1

    # shellcheck disable=SC2181
    if [[ $? -eq 0 ]]; then
      log_message "$GREEN" "Docker container started successfully."
    else
      log_message "$RED" "Failed to start Docker container."
      exit 1
    fi

  else
    log_message "$RED" "Invalid choice. Aborting installation."
    exit 1
  fi
}

update_local_pytmbot() {

  show_banner "Updating local pyTMBot"

  if [ -d "/opt/pytmbot" ]; then
    log_message "$GREEN" "Updating local pyTMBot..."
      cd /opt/pytmbot || { log_message "$RED" "Failed to enter directory." | tee -a "$LOG_FILE"; exit 1;}

      log_message "$GREEN" "Downloading latest pyTMBot..."
      (
        git pull > "$LOG_FILE" 2>&1 || { log_message "$RED" "Failed to update pyTMBot. Check your internet connection." | tee -a "$LOG_FILE"; exit 1; }
      ) & show_spinner $! && log_message "$GREEN" "Done!"

      # shellcheck disable=SC2181
      if [[ $? -eq 0 ]]; then
        log_message "$GREEN" "pyTMBot updated successfully."
        echo ""
        log_message "$GREEN" "Please ensure that your version is pytmbot.yaml file matches the updated version (compare your current pytmbot.yaml with the sample pytmbot.yaml)"
        echo ""
        log_message "$GREEN" "An up-to-date example of the pytmbot.yaml file is always available on the official repository at: https://github.com/orenlab/pytmbot/blob/master/pytmbot.yaml.sample."

        read -r -p "Try to restart the service $SERVICE_NAME? [y/N] " choice

        if [[ "$choice" =~ ^[Yy]$ ]]; then
          show_banner "Trying to restart the service $SERVICE_NAME"
          systemctl restart "$SERVICE_NAME"
          exit 0
        else
          echo ""
          echo -e "${GREEN}Ok, you need to restart the service manually, use command: systemctl restart $SERVICE_NAME${NC}"
fi

        systemctl restart "$SERVICE_NAME"
      else
        log_message "$RED" "Failed to update pyTMBot."
        exit 1
      fi
  else
    log_message "$RED" "Local pyTMBot directory not found."
    exit 1
  fi
}


install_influxdb() {
  local influxdb_container_name="influxdb"
  local new_influxdb_container_name="influxdb_pytmbot"
  local default_username="pytmbot"
  local default_org="pytmbot_monitor"
  local default_bucket="pytmbot_monitor"

  show_banner "Installing InfluxDB"

  # Check if InfluxDB container exists
  if [ "$(docker ps -a -q -f name="$influxdb_container_name")" ]; then
    log_message "$YELLOW" "An InfluxDB container already exists."

    # Ask user what to do with the existing container
    echo "What would you like to do?"
    echo "1) Delete the existing container (WARNING: This will remove all data)"
    echo "2) Create a new container with name 'influxdb_pytmbot'"
    echo "3) Use the existing container and exit"

    read -r -p "Enter your choice (1/2/3): " choice

    case $choice in
      1)
        show_banner "Deleting the existing InfluxDB container"

        log_message "$RED" "WARNING: You are about to delete the existing InfluxDB container and all its data!"
        read -r -p "Are you sure? Type 'yes' to confirm: " confirm
        if [ "$confirm" == "yes" ]; then
          log_message "$BLUE" "Stopping and removing the existing InfluxDB container..."
          (
            docker stop "$influxdb_container_name" >"$LOG_FILE" 2>&1 && \
            docker rm "$influxdb_container_name" >>"$LOG_FILE" 2>&1 && \
            docker volume rm influxdb_influxdb_data  >>"$LOG_FILE" 2>&1
           ) & show_spinner $!
        else
          log_message "$YELLOW" "Operation aborted. Exiting..."
          return
        fi
        ;;
      2)
        show_banner "Creating a new InfluxDB container"
        log_message "$BLUE" "Creating a new InfluxDB container with name 'influxdb_pytmbot'..."
        influxdb_container_name="$new_influxdb_container_name"
        ;;
      3)
        show_banner "Using the existing InfluxDB container"
        log_message "$GREEN" "Using the existing InfluxDB container. Exiting..."
        return
        ;;
      *)
        show_banner "Returning..."
        log_message "$RED" "Invalid choice. Exiting..."
        return
        ;;
    esac
  fi

  show_banner "Configure InfluxDB"

  # Ask for user input
  read -r -p "Enter InfluxDB admin username [${default_username}]: " username
  username=${username:-$default_username}

  read -r -sp "Enter InfluxDB admin password (leave empty to auto-generate): " password
  if [ -z "$password" ]; then
    password=$(openssl rand -base64 19)
    log_message "$BLUE" "Auto-generated password: $password"
    echo -e "\nAuto-generated password: $password"
  else
    log_message "$BLUE" "Using provided password: $password"
    return
  fi

  read -r -p "Enter InfluxDB organization name [${default_org}]: " org
  org=${org:-$default_org}

  read -r -p "Enter InfluxDB bucket name [${default_bucket}]: " bucket
  bucket=${bucket:-$default_bucket}

  show_banner "Pulling and starting InfluxDB container"

  log_message "$BLUE" "Pulling the latest InfluxDB Docker image..."
  (docker pull influxdb:latest >"$LOG_FILE" 2>&1) & show_spinner $!

  log_message "$BLUE" "Starting InfluxDB container..."
  (docker run -d --name "$influxdb_container_name" -p 8086:8086 \
    -e DOCKER_INFLUXDB_INIT_USERNAME="$username" \
    -e DOCKER_INFLUXDB_INIT_PASSWORD="$password" \
    -e DOCKER_INFLUXDB_INIT_ORG="$org" \
    -e DOCKER_INFLUXDB_INIT_BUCKET="$bucket" \
    influxdb:latest >"$LOG_FILE" 2>&1) & show_spinner $!

  show_banner "Waiting for InfluxDB to be ready 20 seconds..."

  # Wait for InfluxDB to be ready
  log_message "$BLUE" "Waiting for InfluxDB to be ready..."
  sleep 20

  show_banner "Generating InfluxDB admin token"

  # Generate InfluxDB token
  log_message "$BLUE" "Generating InfluxDB admin token..."
  # shellcheck disable=SC2155
  export INFLUXDB_TOKEN=$(docker exec -it "$influxdb_container_name" influx auth create \
    --org "$org" \
    --user "$username" \
    --description "Admin Token" \
    --write-buckets \
    --read-buckets | grep "Token" | awk '{print $3}' >"$LOG_FILE" 2>&1)

  # Export InfluxDB token
  export INFLUXDB_TOKEN=token

  if [ -n "$INFLUXDB_TOKEN" ]; then
    log_message "$GREEN" "InfluxDB Admin Token generated successfully."
    log_message "$WHITE" "Admin Token: $INFLUXDB_TOKEN (Make sure to store this securely in your environment!)"
  else
    log_message "$RED" "Failed to generate InfluxDB admin token."
    unset INFLUXDB_TOKEN
  fi

  show_banner "InfluxDB installed"

  log_message "$GREEN" "InfluxDB has been installed and started successfully."
  log_message "$WHITE" "Please, write securely the following information (show it only once!!!):"
  echo ""
  log_message "$WHITE" "InfluxDB URL: http://127.0.0.1:8086 or http://$influxdb_container_name:8086 or http://server_public_ip:8086"
  log_message "$WHITE" "Admin Username: $username"
  log_message "$WHITE" "Organization: $org"
  log_message "$WHITE" "Bucket: $bucket"
  log_message "$WHITE" "Password: $password (Make sure to store this securely!)"
}

# Check if script is run as root
check_root

show_banner "Installation"

log_message "$YELLOW" "Before proceeding with the setup, please gather the following information:"

echo ""
log_message "$GREEN" "1. Telegram Token: Obtain your Telegram bot token from BotFather when creating your bot."
echo ""
log_message "$GREEN" "2. Allowed Telegram User IDs: You can enter any valid Telegram user IDs. If you are unsure, enter arbitrary values, and later check the logs of pyTMBot to add the correct IDs to the configuration."
echo ""
log_message "$GREEN" "3. Global Chat ID: To get your chat ID, send a message to your bot and then visit the following URL in your browser:"
log_message "$GREEN" "   https://api.telegram.org/bot<YourBotToken>/getUpdates"
log_message "$WHITE" "   Look for the chat object in the JSON response to find your chat_id."
echo ""
log_message "$GREEN" "4. Docker Socket Path: The default path is usually unix:///var/run/docker.sock. You may need to adjust this if your Docker setup is different."
echo ""
log_message "$GREEN" "5. Webhook Configuration: If running in webhook mode, provide your domain URL or public IP."
log_message "$GREEN" "   If running locally, you will need the path to the SSL certificate and its corresponding private key."
echo ""
log_message "$GREEN" "6. Plugin Information: For the Monitor plugin, InfluxDB is required (recommended to run in a Docker container)."
log_message "$GREEN" "   If you already have InfluxDB installed, you will need the following details for the connection:"
log_message "$GREEN" "   - InfluxDB URL: Address of your InfluxDB server."
log_message "$GREEN" "   - Organization Name: Your InfluxDB organization name."
log_message "$GREEN" "   - Bucket Name: The name of your InfluxDB bucket."
log_message "$GREEN" "   - InfluxDB Token: Your authorization token for InfluxDB."
echo ""
log_message "$YELLOW" "Once you have gathered this information, you can proceed with the installation setup."
echo ""

read -r -p "Do you want to proceed with the installation? (y/n): " choice

if [[ ! "$choice" =~ ^[Yy]$ ]]; then
  show_banner "cancelled installation"
  exit 0
else
  echo ""
  echo -e "${GREEN}Continuing with the installation...${NC}"
fi

# Choose installation method with descriptions
echo ""
echo -e "${GREEN}Choose installation method:${NC}" | tee -a "$LOG_FILE"
echo ""
echo "1. Docker installation - Run the bot inside a Docker container for easy management and isolation." | tee -a "$LOG_FILE"
echo "2. Local installation - Provides more control and flexibility, as it runs directly on the system without process isolation." | tee -a "$LOG_FILE"
echo "3. Update local installation - Update the bot to the latest version." | tee -a "$LOG_FILE"
echo "4. Uninstall local installation pyTMBot - Completely remove the bot and its files from your system." | tee -a "$LOG_FILE"
echo ""
echo ""
read -r -p "Enter the number (1, 2, 3 or 4): " choice

case $choice in
  1)
    install_bot_in_docker  # Docker installation
    ;;
  2)
    install_local  # Local installation
    ;;
  3)
    update_local_pytmbot  # Update the bot
    ;;
  4)
    uninstall_pytmbot  # Uninstall the bot
    ;;
  *)
    echo -e "${RED}Invalid choice. Please choose 1, 2, or 3.${NC}" | tee -a "$LOG_FILE"
    exit 1
    ;;
esac