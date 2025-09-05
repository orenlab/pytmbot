#!/bin/bash
# (c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
# pyTMBot - A simple Telegram bot to handle Docker containers and images,
# also providing basic information about the status of local servers.

# Safe error handling - only exit on truly critical errors
# set -e TODO: fix the processing of non-zero signals and enable it. This is a critical issue!

# Colors for output
readonly GREEN='\033[0;32m'
readonly RED='\033[0;31m'
readonly YELLOW='\033[1;33m'
readonly CYAN='\033[1;36m'
readonly WHITE='\033[1;37m'
readonly BLUE='\033[0;34m'
readonly PURPLE='\033[0;35m'
readonly GRAY='\033[0;37m'
readonly BOLD='\033[1m'
readonly NC='\033[0m' # No Color

# Configuration paths (can be overridden via environment variables)
readonly INSTALL_DIR="${PYTMBOT_INSTALL_DIR:-/opt/pytmbot}"
readonly CONFIG_FILE="${INSTALL_DIR}/pytmbot.yaml"
readonly LOG_DIR="${PYTMBOT_LOG_DIR:-/var/log}"
readonly LOG_FILE="${LOG_DIR}/pytmbot_install.log"

# Minimum Python version required
readonly REQUIRED_PYTHON="3.12.0"

# GitHub repository URL for the bot
readonly GITHUB_REPO="https://github.com/orenlab/pytmbot.git"

# Bot service name
readonly SERVICE_NAME="pytmbot"

# Cleanup function for sensitive data
cleanup() {
  # Restore cursor if it was hidden
  tput cnorm 2>/dev/null || true

  # Clear sensitive variables
  unset -v prod_token dev_token influxdb_token auth_salt 2>/dev/null || true

  # Clear bash history of sensitive commands (optional)
  history -c 2>/dev/null || true
}

# Enhanced cleanup for interruption
cleanup_on_interrupt() {
  echo ""
  print_warn "Installation interrupted by user"
  cleanup
  exit 130  # Standard exit code for Ctrl+C
}

# Set up signal handlers
trap cleanup EXIT
trap cleanup_on_interrupt INT TERM

# Separate UI output and logging
print_message() {
  local color="$1"
  local message="$2"
  echo -e "${color}${message}${NC}"
}

# Logging function (only to file)
log_to_file() {
  local level="$1"
  local message="$2"
  local timestamp
  timestamp=$(date '+%Y-%m-%d %H:%M:%S') || {
    # Fallback if date command fails
    timestamp="UNKNOWN_TIME"
  }

  # Ensure log directory exists
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

  # Write to log file only
  echo "[${timestamp}] [${level}] ${message}" >> "$LOG_FILE" 2>/dev/null || true
}

# UI functions (console output)
print_info() {
  print_message "$GREEN" "✓ $1"
  log_to_file "INFO" "$1"
}

print_warn() {
  print_message "$YELLOW" "⚠ $1"
  log_to_file "WARN" "$1"
}

print_error() {
  print_message "$RED" "✗ $1"
  log_to_file "ERROR" "$1"
}

print_debug() {
  print_message "$CYAN" "→ $1"
  log_to_file "DEBUG" "$1"
}

# Section headers for better organization
print_section() {
  echo ""
  print_message "$BOLD$CYAN" "═══════════════════════════════════════════════════════════════"
  print_message "$BOLD$WHITE" "  $1"
  print_message "$BOLD$CYAN" "═══════════════════════════════════════════════════════════════"
  echo ""
}

# Enhanced spinner with docker-compose style animation
show_spinner() {
  local pid=$1
  local message="${2:-Processing}"
  local delay=0.1
  local frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
  local colors=("${CYAN}" "${BLUE}" "${GREEN}" "${YELLOW}")
  local frame_count=0
  local color_count=0

  # Hide cursor
  tput civis 2>/dev/null || true

  # Safe process check - don't let it crash the script
  while kill -0 "$pid" 2>/dev/null; do
    local current_frame=${frames[$((frame_count % ${#frames[@]}))]}
    local current_color=${colors[$((color_count % ${#colors[@]}))]}

    printf "\r${current_color}%s${NC} %s..." "$current_frame" "$message"

    sleep $delay
    ((frame_count++))

    # Change color every 5 frames for smooth transition
    if (( frame_count % 5 == 0 )); then
      ((color_count++))
    fi
  done

  # Show cursor and clear line
  tput cnorm 2>/dev/null || true
  printf "\r\033[K"
}

# Validation functions with better error messages
validate_telegram_token() {
  local token="$1"
  if [[ -z "$token" ]]; then
    return 1
  fi
  if [[ ! "$token" =~ ^[0-9]{8,10}:[a-zA-Z0-9_-]{35}$ ]]; then
    return 1
  fi
  return 0
}

validate_chat_id() {
  local chat_id="$1"
  if [[ -z "$chat_id" ]]; then
    return 1
  fi
  if [[ ! "$chat_id" =~ ^-?[0-9]{1,15}$ ]]; then
    return 1
  fi
  return 0
}

validate_user_ids() {
  local ids="$1"
  if [[ -z "$ids" ]]; then
    return 1
  fi
  IFS=',' read -ra id_array <<< "$ids"
  for id in "${id_array[@]}"; do
    id=$(echo "$id" | xargs) # trim whitespace
    if [[ ! "$id" =~ ^[0-9]{1,15}$ ]]; then
      return 1
    fi
  done
  return 0
}

validate_port() {
  local port="$1"
  if [[ -z "$port" ]]; then
    return 1
  fi
  if [[ ! "$port" =~ ^[0-9]+$ ]] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
    return 1
  fi
  return 0
}

validate_url() {
  local url="$1"
  # Allow empty URLs for optional fields
  if [[ -z "$url" ]]; then
    return 0
  fi
  # More permissive URL validation
  if [[ "$url" =~ ^https?://[a-zA-Z0-9.-]+([:/][a-zA-Z0-9._~:/?#[\]@!$&\'()*+,;=%-]*)?$ ]]; then
    return 0
  fi
  return 1
}

# Check system requirements
check_system_requirements() {
  local min_ram_mb=512
  local min_disk_mb=1024

  # Check RAM (safe operation)
  local total_ram
  total_ram=$(free -m 2>/dev/null | awk 'NR==2{print $2}' || echo "1024")

  if [ "$total_ram" -lt "$min_ram_mb" ]; then
    print_warn "Low RAM detected: ${total_ram}MB (recommended: ${min_ram_mb}MB+)"
    read -r -p "Continue anyway? [y/N]: " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
      exit 1
    fi
  fi

  # Check disk space (safe operation)
  local available_disk
  available_disk=$(df "$(dirname "$INSTALL_DIR")" 2>/dev/null | awk 'NR==2 {print int($4/1024)}' || echo "2048")

  if [ "$available_disk" -lt "$min_disk_mb" ]; then
    print_warn "Low disk space: ${available_disk}MB available (recommended: ${min_disk_mb}MB+)"
    read -r -p "Continue anyway? [y/N]: " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
      exit 1
    fi
  fi

  print_info "System requirements check passed"
}

# Modern beautiful banner
show_banner() {
  local action="$1"
  clear

  # Get terminal width for responsive design
  local term_width
  term_width=$(tput cols 2>/dev/null || echo 80)
  local banner_width=$((term_width > 100 ? 100 : term_width - 4))

  # Create gradient effect with different colors
  local gradient1="${CYAN}▓▓▓▓▓▓${BLUE}▓▓▓▓▓▓${PURPLE}▓▓▓▓▓▓${NC}"
  local gradient2="${PURPLE}▓▓▓▓▓▓${BLUE}▓▓▓▓▓▓${CYAN}▓▓▓▓▓▓${NC}"

  echo ""
  echo -e "${BOLD}${CYAN}╔$(printf '═%.0s' $(seq 1 $((banner_width-2))))╗${NC}"
  echo -e "${BOLD}${CYAN}║${NC} ${gradient1} ${BOLD}${WHITE}pyTMBot ${YELLOW}Installer${NC} ${gradient2} ${BOLD}${CYAN}║${NC}"
  echo -e "${BOLD}${CYAN}╠$(printf '═%.0s' $(seq 1 $((banner_width-2))))╣${NC}"

  # Center-aligned info
  local version="v0.3.0-dev"
  local author="by Denis Rozhnovskiy"
  local system_info
  system_info="$(uname -s 2>/dev/null || echo "Linux") $(uname -r 2>/dev/null || echo "Unknown")"
  local date_info
  date_info="$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date)"

  printf "${BOLD}${CYAN}║${NC} ${BOLD}${WHITE}%-*s${CYAN}║${NC}\n" $((banner_width-4)) "🚀 $action"
  printf "${BOLD}${CYAN}║${NC} ${GRAY}%-*s${CYAN}║${NC}\n" $((banner_width-4)) "   Version: $version"
  printf "${BOLD}${CYAN}║${NC} ${GRAY}%-*s${CYAN}║${NC}\n" $((banner_width-4)) "   $author"
  echo -e "${BOLD}${CYAN}╠$(printf '─%.0s' $(seq 1 $((banner_width-2))))╣${NC}"
  printf "${BOLD}${CYAN}║${NC} ${WHITE}%-*s${CYAN}║${NC}\n" $((banner_width-4)) "💻 System: $system_info"
  printf "${BOLD}${CYAN}║${NC} ${WHITE}%-*s${CYAN}║${NC}\n" $((banner_width-4)) "🕒 Time: $date_info"
  echo -e "${BOLD}${CYAN}╠$(printf '─%.0s' $(seq 1 $((banner_width-2))))╣${NC}"
  printf "${BOLD}${CYAN}║${NC} ${YELLOW}%-*s${CYAN}║${NC}\n" $((banner_width-4)) "🔗 github.com/orenlab/pytmbot"
  echo -e "${BOLD}${CYAN}╚$(printf '═%.0s' $(seq 1 $((banner_width-2))))╝${NC}"
  echo ""
}

# Function to check if the script is running as root
check_root() {
  if ! sudo -n true 2>/dev/null; then
    print_error "This script requires root privileges. Please use 'sudo' or switch to a user with appropriate permissions."
    exit 1
  fi
  print_info "Root privileges confirmed"
}

# Secure random salt generation
generate_auth_salt() {
  local salt

  if command -v openssl &> /dev/null; then
    salt=$(openssl rand -hex 32 2>/dev/null || echo "")
  fi

  if [[ -z "$salt" ]] && [[ -r /dev/urandom ]]; then
    salt=$(head -c 32 /dev/urandom 2>/dev/null | xxd -p | tr -d '\n' || echo "")
  fi

  if [[ -z "$salt" ]]; then
    print_error "No secure random generator found. Please install openssl."
    return 1
  fi

  echo "$salt"
}

# Function to check if a command exists
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Safe user operations
create_pytmbot_user() {
  show_banner "Creating User Account"
  print_info "Ensuring user 'pytmbot' exists and is in the 'docker' group..."

  # Create user if it doesn't exist (safe check)
  if ! id "pytmbot" >/dev/null 2>&1; then
    print_info "Creating system user 'pytmbot'..."

    {
      useradd --system --no-create-home --shell /usr/sbin/nologin --comment "pyTMBot Service User" pytmbot 2>/dev/null || true
      mkdir -p "$INSTALL_DIR" 2>/dev/null || true
      chown pytmbot:pytmbot "$INSTALL_DIR" 2>/dev/null || true
      chmod 750 "$INSTALL_DIR" 2>/dev/null || true
    } >> "$LOG_FILE" 2>&1 &

    local user_pid=$!
    show_spinner $user_pid "Creating user 'pytmbot'"
    wait $user_pid || true

    # Verify user was created
    if id "pytmbot" >/dev/null 2>&1; then
      print_info "User 'pytmbot' created successfully"
    else
      print_error "Failed to create user 'pytmbot'"
      exit 1
    fi
  else
    print_info "User 'pytmbot' already exists"
  fi

  # Check Docker installation
  if ! command_exists docker; then
    echo ""
    read -r -p "${RED}Docker is not installed. Would you like to install Docker? [y/N]: ${NC}" install_docker
    if [[ "${install_docker,,}" =~ ^[y]$ ]]; then
      install_docker_securely
    else
      print_error "Docker is required for pyTMBot. Aborting installation."
      exit 1
    fi
  else
    print_info "Docker is already installed"
  fi

  # Add user to docker group (safe check)
  if ! groups pytmbot 2>/dev/null | grep -q '\bdocker\b'; then
    print_info "Adding user 'pytmbot' to 'docker' group..."
    if usermod -aG docker pytmbot 2>/dev/null; then
      print_info "User 'pytmbot' added to 'docker' group successfully"
    else
      print_error "Failed to add user to docker group"
      exit 1
    fi
  else
    print_info "User 'pytmbot' is already in 'docker' group"
  fi
}

# Safe Docker installation
install_docker_securely() {
  show_banner "Docker Installation"

  local docker_script="/tmp/docker-install-$$.sh"
  local docker_url="https://get.docker.com"

  print_info "Downloading Docker installation script..."

  # Download with timeout and error checking
  {
    curl -fsSL --connect-timeout 30 --max-time 300 "$docker_url" -o "$docker_script" 2>/dev/null || exit 1
  } >> "$LOG_FILE" 2>&1 &

  local download_pid=$!
  show_spinner $download_pid "Downloading Docker script"
  wait $download_pid
  local download_status=$?

  if [ $download_status -ne 0 ] || [ ! -f "$docker_script" ]; then
    print_error "Failed to download Docker installation script"
    rm -f "$docker_script" 2>/dev/null || true
    exit 1
  fi

  # Show script size and ask for confirmation
  local script_size
  script_size=$(stat -c%s "$docker_script" 2>/dev/null || echo "unknown")
  print_warn "Downloaded script size: ${script_size} bytes"

  echo ""
  echo -e "${YELLOW}The script will now install Docker. This will:"
  echo "- Add Docker's official GPG key"
  echo "- Add Docker repository to your system"
  echo "- Install Docker CE"
  echo "- Start and enable Docker service${NC}"
  echo ""

  read -r -p "Do you want to continue with Docker installation? [y/N]: " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    rm -f "$docker_script" 2>/dev/null || true
    print_error "Docker installation cancelled by user"
    exit 1
  fi

  {
    bash "$docker_script" 2>/dev/null || exit 1
    systemctl enable docker 2>/dev/null || true
    systemctl start docker 2>/dev/null || true
  } >> "$LOG_FILE" 2>&1 &

  local docker_pid=$!
  show_spinner $docker_pid "Installing Docker"
  wait $docker_pid
  local docker_status=$?

  rm -f "$docker_script" 2>/dev/null || true

  # Verify installation
  if [ $docker_status -eq 0 ] && command_exists docker && systemctl is-active --quiet docker 2>/dev/null; then
    print_info "Docker installed and running successfully"
  else
    print_error "Docker installation failed. Check log: $LOG_FILE"
    exit 1
  fi
}

# Repository cloning with error handling
clone_repo() {
  show_banner "Repository Download"

  print_info "Cloning pyTMBot repository..."

  # Check if directory exists
  if [ -d "$INSTALL_DIR" ]; then
    print_warn "Installation directory exists. Creating backup..."
    mv "$INSTALL_DIR" "${INSTALL_DIR}.backup.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || {
      print_error "Failed to backup existing directory"
      exit 1
    }
  fi

  {
    # Clone with depth=1 for faster download
    git clone --depth=1 --single-branch "$GITHUB_REPO" "$INSTALL_DIR" 2>/dev/null || exit 1

    # Verify repository integrity
    cd "$INSTALL_DIR" || exit 1

    # Check if essential files exist
    for file in "requirements.txt" "pytmbot/main.py" "pytmbot.yaml.sample"; do
      if [ ! -f "$file" ]; then
        echo "Essential file missing: $file" >&2
        exit 1
      fi
    done

    # Set initial permissions
    chown -R pytmbot:pytmbot "$INSTALL_DIR" 2>/dev/null || true
    chmod -R 750 "$INSTALL_DIR" 2>/dev/null || true

  } >> "$LOG_FILE" 2>&1 &

  local clone_pid=$!
  show_spinner $clone_pid "Cloning repository and verifying files"
  wait $clone_pid
  local clone_status=$?

  if [ $clone_status -eq 0 ]; then
    print_info "Repository cloned successfully"
  else
    print_error "Repository cloning failed"
    exit 1
  fi
}

# Beautiful configuration input with proper sections
configure_bot() {
  show_banner "Bot Configuration"

  print_info "Starting bot configuration wizard..."
  echo ""
  print_message "$BOLD$WHITE" "This wizard will help you configure your pyTMBot installation."
  print_message "$GRAY" "Required fields are marked with [REQUIRED]"
  print_message "$GRAY" "Optional fields can be skipped by pressing Enter"
  echo ""

  # ===============================================
  # SECTION 1: BOT TOKENS
  # ===============================================
  print_section "📱 BOT TOKENS CONFIGURATION"

  print_message "$WHITE" "Get your bot tokens from @BotFather on Telegram"
  print_message "$GRAY" "Production token is required, development token is optional"
  echo ""

  # Production token (required)
  local prod_token=""
  while true; do
    read -r -s -p "🤖 Enter production bot token [REQUIRED]: " prod_token
    echo

    if [[ -z "$prod_token" ]]; then
      print_error "Production bot token is required"
      continue
    fi

    if validate_telegram_token "$prod_token"; then
      print_info "Production token format is valid"
      break
    else
      print_error "Invalid token format. Expected: 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ"
      echo ""
    fi
  done

  # Development token (optional)
  local dev_token=""
  read -r -s -p "🔧 Enter development bot token [OPTIONAL - press Enter to skip]: " dev_token
  echo

  if [[ -n "$dev_token" ]]; then
    if validate_telegram_token "$dev_token"; then
      print_info "Development token format is valid"
    else
      print_warn "Development token format is invalid, will be ignored"
      dev_token=""
    fi
  else
    print_info "Development token skipped"
  fi

  # ===============================================
  # SECTION 2: ACCESS CONTROL
  # ===============================================
  print_section "🔐 ACCESS CONTROL CONFIGURATION"

  print_message "$WHITE" "Configure who can access your bot"
  print_message "$GRAY" "To get your user ID: send any message to @userinfobot on Telegram"
  echo ""

  # Chat ID for notifications
  local global_chat_id=""
  while true; do
    read -r -p "💬 Enter chat ID for notifications [REQUIRED]: " global_chat_id

    if [[ -z "$global_chat_id" ]]; then
      print_error "Chat ID is required"
      print_message "$GRAY" "   For private chat: use your user ID (positive number)"
      print_message "$GRAY" "   For group chat: use group ID (negative number, starts with -)"
      continue
    fi

    if validate_chat_id "$global_chat_id"; then
      if [[ "$global_chat_id" =~ ^- ]]; then
        print_info "Group chat ID format is valid"
      else
        print_info "Private chat ID format is valid"
      fi
      break
    else
      print_error "Invalid chat ID format. Should be a number, optionally starting with '-'"
      print_message "$GRAY" "   Examples: 123456789 (private) or -1001234567890 (group)"
      echo ""
    fi
  done

  # Allowed user IDs
  local allowed_user_ids=""
  while true; do
    read -r -p "👤 Enter allowed user IDs [REQUIRED, comma-separated]: " allowed_user_ids

    if [[ -z "$allowed_user_ids" ]]; then
      print_error "At least one user ID is required"
      print_message "$GRAY" "   Example: 123456789,987654321"
      continue
    fi

    if validate_user_ids "$allowed_user_ids"; then
      local user_count
      user_count=$(echo "$allowed_user_ids" | tr ',' '\n' | wc -l)
      print_info "Added $user_count allowed user(s)"
      break
    else
      print_error "Invalid user ID format. Should be comma-separated numbers"
      print_message "$GRAY" "   Example: 123456789,987654321"
      echo ""
    fi
  done

  # Admin IDs
  local allowed_admins_ids=""
  while true; do
    read -r -p "👑 Enter admin user IDs [REQUIRED, comma-separated]: " allowed_admins_ids

    if [[ -z "$allowed_admins_ids" ]]; then
      print_error "At least one admin ID is required"
      print_message "$GRAY" "   Admins have access to sensitive commands"
      continue
    fi

    if validate_user_ids "$allowed_admins_ids"; then
      local admin_count
      admin_count=$(echo "$allowed_admins_ids" | tr ',' '\n' | wc -l)
      print_info "Added $admin_count admin user(s)"
      break
    else
      print_error "Invalid admin ID format. Should be comma-separated numbers"
      echo ""
    fi
  done

  # ===============================================
  # SECTION 3: DOCKER CONFIGURATION
  # ===============================================
  print_section "🐳 DOCKER CONFIGURATION"

  print_message "$WHITE" "Configure Docker connection settings"
  echo ""

  local docker_host=""
  read -r -p "🔌 Docker socket path [press Enter for default]: " docker_host
  docker_host="${docker_host:-unix:///var/run/docker.sock}"
  print_info "Using Docker socket: $docker_host"

  # ===============================================
  # SECTION 4: WEBHOOK CONFIGURATION (OPTIONAL)
  # ===============================================
  print_section "🌐 WEBHOOK CONFIGURATION (OPTIONAL)"

  print_message "$WHITE" "Webhooks allow faster message delivery than polling"
  print_message "$GRAY" "Leave empty to use polling mode (recommended for beginners)"
  echo ""

  local webhook_url=""
  local webhook_port="8443"
  local local_port="5001"
  local cert=""
  local cert_key=""

  read -r -p "🌍 Enter your domain for webhooks [OPTIONAL - press Enter to skip]: " webhook_url

  if [[ -n "$webhook_url" ]]; then
    # If user provided webhook URL, ask for related settings
    if [[ ! "$webhook_url" =~ ^https?:// ]]; then
      webhook_url="https://$webhook_url"
    fi

    if validate_url "$webhook_url"; then
      print_info "Webhook URL accepted: $webhook_url"

      # Webhook port
      read -r -p "🔌 Webhook port [press Enter for 8443]: " webhook_port
      webhook_port="${webhook_port:-8443}"
      if validate_port "$webhook_port"; then
        print_info "Webhook port: $webhook_port"
      else
        webhook_port="8443"
        print_warn "Invalid port, using default: 8443"
      fi

      # Local port
      read -r -p "🏠 Local port [press Enter for 5001]: " local_port
      local_port="${local_port:-5001}"
      if validate_port "$local_port"; then
        print_info "Local port: $local_port"
      else
        local_port="5001"
        print_warn "Invalid port, using default: 5001"
      fi

      # SSL certificates (optional for webhooks)
      read -r -p "🔐 SSL certificate path [OPTIONAL]: " cert
      read -r -p "🔑 SSL certificate key path [OPTIONAL]: " cert_key

      if [[ -n "$cert" && -n "$cert_key" ]]; then
        print_info "SSL certificates configured"
      else
        print_info "No SSL certificates provided (will use defaults)"
      fi
    else
      print_warn "Invalid webhook URL format, webhook disabled"
      webhook_url=""
    fi
  else
    print_info "Webhook configuration skipped - using polling mode"
    webhook_url="https://yourdomain.com/webhook"
  fi

  # ===============================================
  # SECTION 5: INFLUXDB CONFIGURATION (OPTIONAL)
  # ===============================================
  print_section "📊 INFLUXDB CONFIGURATION (OPTIONAL)"

  print_message "$WHITE" "InfluxDB stores monitoring data for analytics"
  print_message "$GRAY" "Only needed if you plan to use the monitoring plugin"
  echo ""

  local influxdb_url=""
  local influxdb_token=""
  local influxdb_org="pytmbot_monitor"
  local influxdb_bucket="pytmbot"
  local influxdb_debug="false"

  read -r -p "📈 InfluxDB URL [OPTIONAL - press Enter to skip]: " influxdb_url

  if [[ -n "$influxdb_url" ]]; then
    if validate_url "$influxdb_url"; then
      print_info "InfluxDB URL: $influxdb_url"

      read -r -s -p "🔑 InfluxDB token: " influxdb_token
      echo

      read -r -p "🏢 InfluxDB organization [press Enter for 'pytmbot_monitor']: " influxdb_org
      influxdb_org="${influxdb_org:-pytmbot_monitor}"

      read -r -p "🪣 InfluxDB bucket [press Enter for 'pytmbot']: " influxdb_bucket
      influxdb_bucket="${influxdb_bucket:-pytmbot}"

      read -r -p "🐛 Enable InfluxDB debug mode? [y/N]: " debug_choice
      if [[ "${debug_choice,,}" =~ ^[y]$ ]]; then
        influxdb_debug="true"
      fi

      print_info "InfluxDB configuration completed"
    else
      print_warn "Invalid InfluxDB URL format, InfluxDB disabled"
      influxdb_url="http://influxdb:8086"
    fi
  else
    print_info "InfluxDB configuration skipped"
    influxdb_url="http://influxdb:8086"
  fi

  # ===============================================
  # SECTION 6: GENERATE CONFIGURATION FILE
  # ===============================================
  print_section "📝 GENERATING CONFIGURATION FILE"

  # Generate secure auth salt
  local auth_salt
  auth_salt=$(generate_auth_salt)
  if [[ -z "$auth_salt" ]]; then
    print_error "Failed to generate auth salt"
    exit 1
  fi
  print_info "Generated secure authentication salt"

  # Create backup of existing config
  if [ -f "$CONFIG_FILE" ]; then
    cp "$CONFIG_FILE" "${CONFIG_FILE}.backup.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
    print_info "Existing config backed up"
  fi

  # Prepare YAML arrays
  local allowed_user_ids_yaml
  local allowed_admins_ids_yaml
  allowed_user_ids_yaml=$(echo "$allowed_user_ids" | tr ',' '\n' | sed 's/^[[:space:]]*/    - /' | sed 's/[[:space:]]*$//')
  allowed_admins_ids_yaml=$(echo "$allowed_admins_ids" | tr ',' '\n' | sed 's/^[[:space:]]*/    - /' | sed 's/[[:space:]]*$//')

  # Create configuration with secure permissions
  {
    umask 077 # Only owner can read/write

    # Create the complete YAML configuration
    cat > "$CONFIG_FILE" << EOF
################################################################
# General Bot Settings
################################################################
# Bot Token Configuration
bot_token:
  # Production bot token (REQUIRED)
  prod_token:
    - '$prod_token'

  # Development bot token (OPTIONAL)
  dev_bot_token:
    - '${dev_token:-}'

# Access Control Settings (REQUIRED)
access_control:
  # User IDs allowed to access the bot (REQUIRED)
  allowed_user_ids:
$allowed_user_ids_yaml

  # Admin IDs with elevated permissions (REQUIRED)
  allowed_admins_ids:
$allowed_admins_ids_yaml

  # Salt for TOTP (Time-Based One-Time Password) generation (REQUIRED)
  auth_salt:
    - '$auth_salt'

# Chat ID Configuration (REQUIRED)
chat_id:
  # Global chat ID for notifications (REQUIRED)
  global_chat_id:
    - $global_chat_id

################################################################
# Docker Settings (REQUIRED)
################################################################
docker:
  # Docker socket path (REQUIRED)
  host:
    - '$docker_host'

  # Enable Docker client debug logging (OPTIONAL)
  debug_docker_client: false

################################################################
# Webhook Configuration (OPTIONAL)
################################################################
webhook_config:
  # Webhook URL (REQUIRED if using webhooks)
  url:
    - '${webhook_url#https://}'

  # External webhook port (REQUIRED if using webhooks)
  webhook_port:
    - $webhook_port

  # Local application port (REQUIRED if using webhooks)
  local_port:
    - $local_port

  # SSL certificate path (OPTIONAL for HTTPS webhooks)
  cert:
    - '${cert:-/path/to/your/certificate.pem}'

  # SSL private key path (OPTIONAL for HTTPS webhooks)
  cert_key:
    - '${cert_key:-/path/to/your/private.key}'

################################################################
# Plugins Configuration (OPTIONAL)
################################################################
plugins_config:
  # System Monitoring Plugin Configuration
  monitor:
    # Resource usage thresholds
    tracehold:
      cpu_usage_threshold:
        - 80
      memory_usage_threshold:
        - 80
      disk_usage_threshold:
        - 80
      cpu_temperature_threshold:
        - 85
      gpu_temperature_threshold:
        - 90
      disk_temperature_threshold:
        - 60

    # Monitoring settings
    max_notifications:
      - 3
    check_interval:
      - 5
    reset_notification_count:
      - 5
    retry_attempts:
      - 3
    retry_interval:
      - 10
    monitor_docker: true

  # Outline VPN Plugin Configuration
  outline:
    # Outline VPN API URL (REQUIRED if using Outline plugin)
    api_url:
      - 'https://your-outline-server.com:12345/api'

    # Certificate fingerprint (REQUIRED if using Outline plugin)
    cert:
      - 'YOUR_OUTLINE_CERT_FINGERPRINT'

################################################################
# InfluxDB Settings (OPTIONAL)
################################################################
influxdb:
  # InfluxDB server URL (REQUIRED if using InfluxDB)
  url:
    - '$influxdb_url'

  # InfluxDB access token (REQUIRED if using InfluxDB)
  token:
    - '${influxdb_token:-YOUR_INFLUXDB_TOKEN}'

  # InfluxDB organization name (REQUIRED if using InfluxDB)
  org:
    - '$influxdb_org'

  # InfluxDB bucket name (REQUIRED if using InfluxDB)
  bucket:
    - '$influxdb_bucket'

  # InfluxDB debug mode (OPTIONAL)
  debug_mode: $influxdb_debug
EOF

    # Set secure permissions
    chown pytmbot:pytmbot "$CONFIG_FILE" 2>/dev/null || true
    chmod 600 "$CONFIG_FILE" 2>/dev/null || true

  } >> "$LOG_FILE" 2>&1 &

  local config_pid=$!
  show_spinner $config_pid "Creating configuration file"
  wait $config_pid || true

  # Clear sensitive variables
  unset -v influxdb_token prod_token dev_token auth_salt 2>/dev/null || true

  print_info "Configuration file created successfully at $CONFIG_FILE"
}

# Enhanced service creation with better plugin handling
create_service() {
  show_banner "Systemd Service Creation"

  local service_file="/etc/systemd/system/$SERVICE_NAME.service"

  if [ -f "$service_file" ]; then
    print_warn "Service file exists. Creating backup..."
    cp "$service_file" "${service_file}.backup.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
  fi

  # Plugin selection with better descriptions
  echo ""
  print_message "$BOLD$WHITE" "AVAILABLE PLUGINS:"
  echo ""
  print_message "$WHITE" "1) Outline Plugin - Manage Outline VPN server"
  print_message "$GRAY" "   • Create and delete VPN access keys"
  print_message "$GRAY" "   • Monitor VPN usage and connections"
  echo ""
  print_message "$WHITE" "2) Monitor Plugin - System monitoring and alerts"
  print_message "$GRAY" "   • CPU, Memory, Disk usage monitoring"
  print_message "$GRAY" "   • Temperature monitoring"
  print_message "$GRAY" "   • Docker container monitoring"
  echo ""
  print_message "$WHITE" "3) Both Plugins - Full functionality"
  print_message "$GRAY" "   • All features from both plugins"
  echo ""

  local plugins=""
  while true; do
    read -r -p "Select plugins (1/2/3): " plugin_choice
    case "$plugin_choice" in
      1)
        plugins="outline"
        print_info "Outline plugin selected"
        break
        ;;
      2)
        plugins="monitor"
        print_info "Monitor plugin selected"
        break
        ;;
      3)
        plugins="outline,monitor"
        print_info "Both plugins selected"
        break
        ;;
      *)
        print_error "Invalid choice. Please select 1, 2, or 3."
        ;;
    esac
  done

  # Log level selection
  echo ""
  print_message "$WHITE" "LOG LEVEL OPTIONS:"
  print_message "$GRAY" "INFO  - Standard logging (recommended)"
  print_message "$GRAY" "ERROR - Only error messages"
  print_message "$GRAY" "DEBUG - Verbose logging (for troubleshooting)"
  echo ""

  local log_level="INFO"
  while true; do
    read -r -p "Select logging level [INFO/ERROR/DEBUG, press Enter for INFO]: " log_level
    log_level="${log_level:-INFO}"
    case "$log_level" in
      INFO|ERROR|DEBUG)
        print_info "Log level set to: $log_level"
        break
        ;;
      *)
        print_error "Invalid logging level. Please choose INFO, ERROR, or DEBUG."
        ;;
    esac
  done

  # Create service file
  {
    cat > "$service_file" << EOF
[Unit]
Description=pyTMBot Service - Telegram Bot for Docker Management
Documentation=https://github.com/orenlab/pytmbot
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=pytmbot
Group=docker
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/pytmbot/main.py${plugins:+ --plugins $plugins} --log-level $log_level
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=10
StartLimitInterval=60
StartLimitBurst=3

# Environment
Environment=PATH=$INSTALL_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=$INSTALL_DIR
Environment=PYTHONUNBUFFERED=1

# Logging
StandardOutput=append:$LOG_DIR/pytmbot.log
StandardError=append:$LOG_DIR/pytmbot_error.log
SyslogIdentifier=pytmbot

# Security settings
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$LOG_DIR
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RemoveIPC=true
RestrictRealtime=true
SystemCallFilter=~@debug @mount @cpu-emulation @obsolete @privileged

# Resource limits
LimitNOFILE=65536
MemoryMax=1G
TasksMax=100

[Install]
WantedBy=multi-user.target
EOF
  } >> "$LOG_FILE" 2>&1 &

  local service_pid=$!
  show_spinner $service_pid "Creating systemd service file"
  wait $service_pid || true
  print_info "Service file created at $service_file"
}

# Update function for local installation
update_local_pytmbot() {
  show_banner "Update Local Installation"

  # Check if installation exists
  if [ ! -d "$INSTALL_DIR" ] || [ ! -f "$CONFIG_FILE" ]; then
    print_error "pyTMBot installation not found at $INSTALL_DIR"
    print_info "Please install pyTMBot first using option 2"
    exit 1
  fi

  # Check if service is running
  local service_was_running=false
  if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    service_was_running=true
    print_info "Service is currently running"
  fi

  # Create backup
  local backup_dir
  local timestamp
  timestamp=$(date +%Y%m%d_%H%M%S) || {
    print_error "Failed to generate timestamp"
    exit 1
  }
  backup_dir="${INSTALL_DIR}.backup.${timestamp}"
  print_info "Creating backup at $backup_dir"

  {
    cp -r "$INSTALL_DIR" "$backup_dir" 2>/dev/null || exit 1
  } >> "$LOG_FILE" 2>&1 &

  local backup_pid=$!
  show_spinner $backup_pid "Creating backup"
  wait $backup_pid
  local backup_status=$?

  if [ $backup_status -eq 0 ]; then
    print_info "Backup created successfully"
  else
    print_error "Failed to create backup"
    exit 1
  fi

  # Stop service if running
  if [ "$service_was_running" = true ]; then
    print_info "Stopping pyTMBot service..."
    {
      systemctl stop "$SERVICE_NAME" 2>/dev/null || exit 1
    } >> "$LOG_FILE" 2>&1 &

    local stop_pid=$!
    show_spinner $stop_pid "Stopping service"
    wait $stop_pid || {
      print_error "Failed to stop service"
      exit 1
    }
    print_info "Service stopped successfully"
  fi

  # Save current config
  local temp_config="/tmp/pytmbot_config_$.yaml"
  cp "$CONFIG_FILE" "$temp_config" 2>/dev/null || {
    print_error "Failed to backup configuration"
    exit 1
  }

  # Update repository
  print_info "Updating repository..."
  {
    cd "$INSTALL_DIR" || exit 1
    git fetch origin 2>/dev/null || exit 1
    git reset --hard origin/main 2>/dev/null || exit 1

    # Update virtual environment if requirements changed
    if [ -f requirements.txt ] && [ -d venv ]; then
      source venv/bin/activate || exit 1
      pip install --upgrade pip setuptools wheel 2>/dev/null || exit 1
      pip install -r requirements.txt --upgrade 2>/dev/null || exit 1
    fi

    # Restore configuration
    cp "$temp_config" "$CONFIG_FILE" 2>/dev/null || exit 1
    rm -f "$temp_config" 2>/dev/null || true

    # Set proper permissions
    chown -R pytmbot:pytmbot "$INSTALL_DIR" 2>/dev/null || true
    chmod 600 "$CONFIG_FILE" 2>/dev/null || true

  } >> "$LOG_FILE" 2>&1 &

  local update_pid=$!
  show_spinner $update_pid "Updating repository and dependencies"
  wait $update_pid
  local update_status=$?

  if [ $update_status -eq 0 ]; then
    print_info "Repository updated successfully"
  else
    print_error "Failed to update repository"
    print_info "Restoring from backup..."
    rm -rf "$INSTALL_DIR" 2>/dev/null || true
    mv "$backup_dir" "$INSTALL_DIR" 2>/dev/null || true
    exit 1
  fi

  # Restart service if it was running
  if [ "$service_was_running" = true ]; then
    print_info "Starting pyTMBot service..."
    {
      systemctl daemon-reload 2>/dev/null || true
      systemctl start "$SERVICE_NAME" 2>/dev/null || exit 1

      # Wait for service to start
      sleep 5

      # Verify service is running
      if ! systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        exit 1
      fi
    } >> "$LOG_FILE" 2>&1 &

    local start_pid=$!
    show_spinner $start_pid "Starting service"
    wait $start_pid
    local start_status=$?

    if [ $start_status -eq 0 ]; then
      print_info "Service started successfully"
    else
      print_error "Service failed to start after update"
      print_info "Check logs with: journalctl -u $SERVICE_NAME -f"
      exit 1
    fi
  fi

  # Remove backup if update was successful
  read -r -p "Update completed successfully. Remove backup? [y/N]: " remove_backup
  if [[ "${remove_backup,,}" =~ ^[y]$ ]]; then
    rm -rf "$backup_dir" 2>/dev/null || true
    print_info "Backup removed"
  else
    print_info "Backup preserved at: $backup_dir"
  fi

  echo ""
  print_message "$BOLD$GREEN" "LOCAL UPDATE COMPLETED!"
  echo ""
  print_message "$WHITE" "Service Status:"
  systemctl status "$SERVICE_NAME" --no-pager -l 2>/dev/null || true
  echo ""
  print_message "$BOLD$YELLOW" "USEFUL COMMANDS:"
  print_message "$WHITE" "• Check logs: journalctl -u $SERVICE_NAME -f"
  print_message "$WHITE" "• Restart service: systemctl restart $SERVICE_NAME"
  print_message "$WHITE" "• Check config: sudo nano $CONFIG_FILE"
  echo ""
}

# Update function for Docker installation
update_docker_pytmbot() {
  show_banner "Update Docker Installation"

  # Check if Docker installation exists
  if [ ! -d "$INSTALL_DIR" ] || [ ! -f "$INSTALL_DIR/docker-compose.yml" ]; then
    print_error "pyTMBot Docker installation not found at $INSTALL_DIR"
    print_info "Please install pyTMBot first using option 1"
    exit 1
  fi

  cd "$INSTALL_DIR" || {
    print_error "Failed to enter installation directory"
    exit 1
  }

  # Check if container is running
  local container_was_running=false
  if docker ps --format "{{.Names}}" | grep -q "pytmbot"; then
    container_was_running=true
    print_info "Container is currently running"
  fi

  # Determine update method based on docker-compose.yml
  local image_name
  image_name=$(grep "image:" docker-compose.yml | awk '{print $2}' | head -n1)

  if [[ "$image_name" == "orenlab/pytmbot"* ]]; then
    # Pre-built image update
    print_info "Updating pre-built Docker image..."

    {
      docker compose pull 2>/dev/null || exit 1
      docker compose up -d 2>/dev/null || exit 1
    } >> "$LOG_FILE" 2>&1 &

    local update_pid=$!
    show_spinner $update_pid "Pulling latest image and restarting container"
    wait $update_pid
    local update_status=$?

    if [ $update_status -eq 0 ]; then
      print_info "Pre-built image updated successfully"
    else
      print_error "Failed to update pre-built image"
      exit 1
    fi
  else
    # Source-based update
    print_info "Updating from source..."

    # Save current config
    local temp_config="/tmp/pytmbot_config_$$.yaml"
    cp "$CONFIG_FILE" "$temp_config" 2>/dev/null || {
      print_error "Failed to backup configuration"
      exit 1
    }

    {
      # Update repository
      git fetch origin 2>/dev/null || exit 1
      git reset --hard origin/main 2>/dev/null || exit 1

      # Restore configuration
      cp "$temp_config" "$CONFIG_FILE" 2>/dev/null || exit 1
      rm -f "$temp_config" 2>/dev/null || true

      # Rebuild and restart
      docker compose build 2>/dev/null || exit 1
      docker compose up -d 2>/dev/null || exit 1

    } >> "$LOG_FILE" 2>&1 &

    local update_pid=$!
    show_spinner $update_pid "Updating source and rebuilding container"
    wait $update_pid
    local update_status=$?

    if [ $update_status -eq 0 ]; then
      print_info "Source-based image updated successfully"
    else
      print_error "Failed to update from source"
      exit 1
    fi
  fi

  # Verify container is running
  sleep 5
  if docker ps --format "{{.Names}}" | grep -q "pytmbot"; then
    echo ""
    print_message "$BOLD$GREEN" "DOCKER UPDATE COMPLETED!"
    echo ""
    print_message "$WHITE" "Container Status:"
    docker ps --filter "name=pytmbot" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" 2>/dev/null || true
    echo ""
    print_message "$BOLD$YELLOW" "USEFUL COMMANDS:"
    print_message "$WHITE" "• Check logs: docker logs pytmbot -f"
    print_message "$WHITE" "• Restart container: docker restart pytmbot"
    print_message "$WHITE" "• Check config: sudo nano $CONFIG_FILE"
    echo ""

    # Информировать о статусе контейнера
    if [ "$container_was_running" = true ]; then
      print_info "Container was running before update and is now updated"
    else
      print_info "Container was stopped before update and is now running"
    fi
  else
    print_error "Container failed to start after update"
    print_info "Check logs with: docker logs pytmbot"
    exit 1
  fi
}

# Complete uninstall function
uninstall_pytmbot() {
  show_banner "Uninstall pyTMBot"

  # Check what type of installation exists
  local install_type=""
  local has_systemd=false
  local has_docker=false

  if [ -f "/etc/systemd/system/$SERVICE_NAME.service" ]; then
    has_systemd=true
    install_type="systemd service"
  fi

  if [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
    has_docker=true
    if [ "$install_type" = "" ]; then
      install_type="Docker"
    else
      install_type="systemd service and Docker"
    fi
  fi

  if [ "$install_type" = "" ]; then
    print_error "No pyTMBot installation found"
    exit 1
  fi

  print_warn "Found pyTMBot installation: $install_type"
  echo ""
  print_message "$BOLD$RED" "WARNING: This will completely remove pyTMBot and all its data!"
  print_message "$WHITE" "The following will be removed:"

  if [ "$has_systemd" = true ]; then
    print_message "$GRAY" "• Systemd service: $SERVICE_NAME"
  fi

  if [ "$has_docker" = true ]; then
    print_message "$GRAY" "• Docker containers and images"
  fi

  print_message "$GRAY" "• Installation directory: $INSTALL_DIR"
  print_message "$GRAY" "• User account: pytmbot"
  print_message "$GRAY" "• Configuration files"
  echo ""

  read -r -p "Are you sure you want to continue? [y/N]: " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    print_info "Uninstall cancelled"
    exit 0
  fi

  # Ask about configuration backup
  local backup_file=""
  read -r -p "Create backup of configuration before removal? [Y/n]: " backup_config
  if [[ ! "${backup_config,,}" =~ ^[n]$ ]]; then
    backup_file="/tmp/pytmbot_config_backup_$(date +%Y%m%d_%H%M%S).yaml"
    if [ -f "$CONFIG_FILE" ]; then
      cp "$CONFIG_FILE" "$backup_file" 2>/dev/null && {
        print_info "Configuration backed up to: $backup_file"
      }
    fi
  fi

  # Stop and remove systemd service
  if [ "$has_systemd" = true ]; then
    print_info "Removing systemd service..."
    {
      systemctl stop "$SERVICE_NAME" 2>/dev/null || true
      systemctl disable "$SERVICE_NAME" 2>/dev/null || true
      rm -f "/etc/systemd/system/$SERVICE_NAME.service" 2>/dev/null || true
      systemctl daemon-reload 2>/dev/null || true
    } >> "$LOG_FILE" 2>&1 &

    local systemd_pid=$!
    show_spinner $systemd_pid "Stopping and removing systemd service"
    wait $systemd_pid || true
    print_info "Systemd service removed"
  fi

  # Stop and remove Docker containers
  if [ "$has_docker" = true ]; then
    print_info "Removing Docker containers and images..."
    {
      cd "$INSTALL_DIR" 2>/dev/null || true
      docker compose down --rmi all --volumes --remove-orphans 2>/dev/null || true

      # Remove any remaining pytmbot containers/images
      docker ps -a --filter "name=pytmbot" --format "{{.ID}}" | xargs -r docker rm -f 2>/dev/null || true
      docker images --filter "reference=*pytmbot*" --format "{{.ID}}" | xargs -r docker rmi -f 2>/dev/null || true

    } >> "$LOG_FILE" 2>&1 &

    local docker_pid=$!
    show_spinner $docker_pid "Stopping containers and removing images"
    wait $docker_pid || true
    print_info "Docker containers and images removed"
  fi

  # Remove installation directory
  if [ -d "$INSTALL_DIR" ]; then
    print_info "Removing installation directory..."
    {
      rm -rf "$INSTALL_DIR" 2>/dev/null || exit 1
    } >> "$LOG_FILE" 2>&1 &

    local dir_pid=$!
    show_spinner $dir_pid "Removing installation directory"
    wait $dir_pid
    local dir_status=$?

    if [ $dir_status -eq 0 ]; then
      print_info "Installation directory removed"
    else
      print_warn "Failed to remove installation directory completely"
    fi
  fi

  # Remove user account
  read -r -p "Remove pytmbot user account? [Y/n]: " remove_user
  if [[ ! "${remove_user,,}" =~ ^[n]$ ]]; then
    if id "pytmbot" >/dev/null 2>&1; then
      print_info "Removing user account..."
      {
        userdel pytmbot 2>/dev/null || true
      } >> "$LOG_FILE" 2>&1 &

      local user_pid=$!
      show_spinner $user_pid "Removing user account"
      wait $user_pid || true
      print_info "User account removed"
    fi
  fi

  # Clean up logs
  read -r -p "Remove log files? [Y/n]: " remove_logs
  if [[ ! "${remove_logs,,}" =~ ^[n]$ ]]; then
    {
      rm -f "$LOG_DIR"/pytmbot*.log 2>/dev/null || true
    } >> "$LOG_FILE" 2>&1 &

    local log_pid=$!
    show_spinner $log_pid "Removing log files"
    wait $log_pid || true
    print_info "Log files removed"
  fi

  echo ""
  print_message "$BOLD$GREEN" "UNINSTALL COMPLETED!"
  echo ""
  print_message "$WHITE" "pyTMBot has been completely removed from your system"

  if [ -f "$backup_file" ]; then
    print_message "$WHITE" "Configuration backup: $backup_file"
  fi

  print_message "$GRAY" "Thank you for using pyTMBot!"
  echo ""
}

# Enhanced Python installation with version checking
install_python_user() {
 show_banner "Python Installation"

 if command_exists python3.12; then
   print_info "Python 3.12 is already installed"
   return 0
 fi

 print_info "Installing Python 3.12..."

 {
   case "$(grep -oP '(?<=^ID=).+' /etc/os-release 2>/dev/null || echo ubuntu)" in
     ubuntu|debian)
       export DEBIAN_FRONTEND=noninteractive
       apt-get update -y 2>/dev/null
       apt-get install -y software-properties-common 2>/dev/null
       if ! grep -q "deadsnakes/ppa" /etc/apt/sources.list.d/* 2>/dev/null; then
         add-apt-repository ppa:deadsnakes/ppa -y 2>/dev/null
         apt-get update -y 2>/dev/null
       fi
       apt-get install -y python3.12 python3.12-venv python3.12-dev python3-pip 2>/dev/null
       ;;
     centos|rhel)
       dnf install -y python3.12 python3.12-pip 2>/dev/null
       ;;
     fedora)
       dnf install -y python3.12 python3.12-pip 2>/dev/null
       ;;
     arch)
       pacman -Syu --noconfirm python python-pip 2>/dev/null
       ;;
     *)
       echo "Unsupported OS for automatic Python installation" >&2
       exit 1
       ;;
   esac
 } >> "$LOG_FILE" 2>&1 &

 local python_pid=$!
 show_spinner $python_pid "Installing Python 3.12"
 wait $python_pid
 local python_status=$?

 if [ $python_status -eq 0 ] && command_exists python3.12; then
   print_info "Python 3.12 installed successfully"
 else
   print_error "Python 3.12 installation failed"
   exit 1
 fi
}

# Python version check with better logic
check_python_version() {
 show_banner "Python Version Check"

 local python_cmd="python3"
 local python_version=""

 # Try different Python commands
 for cmd in python3.12 python3.11 python3.10 python3; do
   if command_exists "$cmd"; then
     python_version=$($cmd --version 2>&1 | awk '{print $2}' 2>/dev/null || echo "0.0.0")
     if [[ "$(printf '%s\n' "$REQUIRED_PYTHON" "$python_version" | sort -V | head -n1)" == "$REQUIRED_PYTHON" ]]; then
       python_cmd="$cmd"
       print_info "Found suitable Python: $cmd version $python_version"
       return 0
     fi
   fi
 done

 print_warn "Python version $python_version is insufficient. Required: $REQUIRED_PYTHON+"
 read -r -p "Would you like to install Python 3.12? [y/N]: " install_python
 if [[ "${install_python,,}" =~ ^[y]$ ]]; then
   install_python_user
 else
   print_error "Python 3.12+ is required. Aborting."
   exit 1
 fi
}

# Virtual environment setup with error checking
setup_virtualenv() {
  show_banner "Virtual Environment Setup"

  print_info "Creating Python virtual environment..."

  {
    cd "$INSTALL_DIR" || exit 1

    local python_cmd
    if command_exists python3.12; then
      python_cmd=python3.12
    elif command_exists python3; then
      python_cmd=python3
    else
      echo "No suitable Python interpreter found" >&2
      exit 1
    fi

    # Create virtual environment
    $python_cmd -m venv venv 2>/dev/null || exit 1

    # Activate and upgrade pip
    source venv/bin/activate || exit 1
    pip install --upgrade pip setuptools wheel 2>/dev/null || exit 1

    # Install requirements
    if [ -f requirements.txt ]; then
      pip install -r requirements.txt 2>/dev/null || exit 1
    else
      echo "requirements.txt not found" >&2
      exit 1
    fi

    # Set proper permissions
    chown -R pytmbot:pytmbot "$INSTALL_DIR" 2>/dev/null || true

  } >> "$LOG_FILE" 2>&1 &

  local venv_pid=$!
  show_spinner $venv_pid "Setting up virtual environment"
  wait $venv_pid
  local venv_status=$?

  if [ $venv_status -eq 0 ]; then
    print_info "Virtual environment created successfully"
  else
    print_error "Virtual environment setup failed"
    exit 1
  fi
}

# Main installation function
install_local() {
  show_banner "Local Installation"

  # Check system requirements
  check_system_requirements

  # Create rollback script
  local rollback_script="/tmp/pytmbot_rollback_$.sh"
  cat > "$rollback_script" << 'EOF'
#!/bin/bash
echo "Rolling back pyTMBot installation..."
systemctl stop pytmbot 2>/dev/null || true
systemctl disable pytmbot 2>/dev/null || true
rm -f /etc/systemd/system/pytmbot.service
systemctl daemon-reload 2>/dev/null || true
userdel pytmbot 2>/dev/null || true
rm -rf /opt/pytmbot 2>/dev/null || true
echo "Rollback completed"
EOF
  chmod +x "$rollback_script" 2>/dev/null || true

  # Set up error handling
  handle_error() {
    print_error "Installation failed. Running rollback..."
    bash "$rollback_script" 2>/dev/null || true
    rm -f "$rollback_script" 2>/dev/null || true
    exit 1
  }
  trap handle_error ERR

  # Install system packages
  print_info "Installing required packages..."
  {
    case "$(grep -oP '(?<=^ID=).+' /etc/os-release 2>/dev/null || echo ubuntu)" in
      ubuntu|debian)
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -y 2>/dev/null
        apt-get install -y python3 python3-pip python3-venv git curl software-properties-common 2>/dev/null
        ;;
      centos|rhel)
        yum update -y 2>/dev/null
        yum install -y python3 python3-pip git curl 2>/dev/null
        ;;
      fedora)
        dnf update -y 2>/dev/null
        dnf install -y python3 python3-pip git curl 2>/dev/null
        ;;
      arch)
        pacman -Syu --noconfirm 2>/dev/null
        pacman -S --noconfirm python python-pip git curl 2>/dev/null
        ;;
      *)
        echo "Unsupported operating system" >&2
        exit 1
        ;;
    esac
  } >> "$LOG_FILE" 2>&1 &

  local pkg_pid=$!
  show_spinner $pkg_pid "Installing system packages"
  wait $pkg_pid
  local pkg_status=$?

  if [ $pkg_status -eq 0 ]; then
    print_info "System packages installed successfully"
  else
    print_error "System package installation failed"
    exit 1
  fi

  # Run installation steps
  create_pytmbot_user
  clone_repo
  check_python_version
  setup_virtualenv
  configure_bot
  create_service

  # Start service
  print_info "Starting pyTMBot service..."
  {
    systemctl daemon-reload 2>/dev/null
    systemctl enable "$SERVICE_NAME" 2>/dev/null
    systemctl start "$SERVICE_NAME" 2>/dev/null

    # Wait for service to start
    sleep 5

    # Verify service is running
    if ! systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
      journalctl -u "$SERVICE_NAME" --no-pager -n 20 2>/dev/null
      exit 1
    fi
  } >> "$LOG_FILE" 2>&1 &

  local service_pid=$!
  show_spinner $service_pid "Starting and enabling service"
  wait $service_pid
  local service_status=$?

  if [ $service_status -eq 0 ]; then
    # Remove rollback script on success
    rm -f "$rollback_script" 2>/dev/null || true
    trap - ERR

    print_info "Local installation completed successfully!"
    echo ""
    print_message "$BOLD$GREEN" "INSTALLATION COMPLETED!"
    echo ""
    print_message "$WHITE" "Service Status:"
    systemctl status "$SERVICE_NAME" --no-pager -l 2>/dev/null || true
    echo ""
    print_message "$BOLD$YELLOW" "USEFUL COMMANDS:"
    print_message "$WHITE" "• Check logs: journalctl -u $SERVICE_NAME -f"
    print_message "$WHITE" "• Restart service: systemctl restart $SERVICE_NAME"
    print_message "$WHITE" "• Stop service: systemctl stop $SERVICE_NAME"
    print_message "$WHITE" "• Edit config: sudo nano $CONFIG_FILE"
    echo ""
    print_message "$BOLD$CYAN" "Next steps:"
    print_message "$GRAY" "1. Test your bot by sending a message to it on Telegram"
    print_message "$GRAY" "2. Check the logs if there are any issues"
    print_message "$GRAY" "3. Configure additional plugins as needed"
    echo ""
  else
    print_error "Service failed to start"
    exit 1
  fi
}

# Docker installation function with pre-built and source options
install_bot_in_docker() {
  show_banner "Docker Installation"

  # Check system requirements
  check_system_requirements

  # Install required packages
  print_info "Installing required packages..."
  {
    case "$(grep -oP '(?<=^ID=).+' /etc/os-release 2>/dev/null || echo ubuntu)" in
      ubuntu|debian)
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -y 2>/dev/null
        apt-get install -y git curl 2>/dev/null
        ;;
      centos|rhel)
        yum update -y 2>/dev/null
        yum install -y git curl 2>/dev/null
        ;;
      fedora)
        dnf update -y 2>/dev/null
        dnf install -y git curl 2>/dev/null
        ;;
      arch)
        pacman -Syu --noconfirm 2>/dev/null
        pacman -S --noconfirm git curl 2>/dev/null
        ;;
      *)
        echo "Unsupported operating system" >&2
        exit 1
        ;;
    esac
  } >> "$LOG_FILE" 2>&1 &

  local pkg_pid=$!
  show_spinner $pkg_pid "Installing system packages"
  wait $pkg_pid
  local pkg_status=$?

  if [ $pkg_status -eq 0 ]; then
    print_info "System packages installed successfully"
  else
    print_error "System package installation failed"
    exit 1
  fi

  # Check Docker and docker compose
  if ! command_exists docker; then
    print_warn "Docker is not installed. Installing Docker..."
    install_docker_securely
  else
    print_info "Docker is already installed"
  fi

  # Check for Docker Compose plugin
  if ! docker compose version >/dev/null 2>&1; then
    print_info "Installing Docker Compose plugin..."
    {
      # Install Docker Compose as plugin
      mkdir -p ~/.docker/cli-plugins/
      curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o ~/.docker/cli-plugins/docker-compose 2>/dev/null
      chmod +x ~/.docker/cli-plugins/docker-compose 2>/dev/null
    } >> "$LOG_FILE" 2>&1 &

    local compose_pid=$!
    show_spinner $compose_pid "Installing Docker Compose plugin"
    wait $compose_pid || {
      print_error "Failed to install Docker Compose plugin"
      exit 1
    }
    print_info "Docker Compose plugin installed successfully"
  else
    print_info "Docker Compose is already available"
  fi

  # Create user and directories
  create_pytmbot_user

  # Installation method selection
  echo ""
  print_message "$BOLD$WHITE" "DOCKER INSTALLATION OPTIONS:"
  echo ""
  print_message "$WHITE" "1) 📦 Pre-built Docker image"
  print_message "$GRAY" "   - Faster installation"
  print_message "$GRAY" "   - Uses official image from Docker Hub"
  print_message "$GRAY" "   - Recommended for most users"
  echo ""
  print_message "$WHITE" "2) 🔨 Build from source"
  print_message "$GRAY" "   - Latest development version"
  print_message "$GRAY" "   - Longer installation time"
  print_message "$GRAY" "   - For advanced users"
  echo ""

  local choice
  while true; do
    read -r -p "Choose installation method [1/2]: " choice
    case "$choice" in
      1) install_prebuilt_docker; break ;;
      2) install_docker_from_source; break ;;
      *) print_error "Invalid choice. Please select 1 or 2." ;;
    esac
  done
}

# Pre-built Docker installation
install_prebuilt_docker() {
  show_banner "Pre-built Docker Installation"

  print_info "Installing pyTMBot using pre-built Docker image..."

  # Configure bot
  configure_bot

  # Create docker-compose.yml for pre-built image
  {
    cat > "$INSTALL_DIR/docker-compose.yml" << EOF
services:
  pytmbot:
    image: orenlab/pytmbot:latest
    container_name: pytmbot
    restart: on-failure
    environment:
      - TZ=UTC
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./pytmbot.yaml:/opt/app/pytmbot.yaml:ro
    security_opt:
      - no-new-privileges
    read_only: true
    cap_drop:
      - ALL
    group_add:
      - 0
    pid: host
    mem_limit: 256m
    memswap_limit: 256m
    cpu_shares: 512
    ulimits:
      nproc: 65535
      nofile:
        soft: 20000
        hard: 40000
    networks:
      - pytmbot_network
    tmpfs:
      - /tmp:noexec,nosuid,nodev,size=100m
      - /var/tmp:noexec,nosuid,nodev,size=50m
    logging:
      options:
        max-size: "10m"
        max-file: "3"
    command: --log-level INFO

networks:
  pytmbot_network:
    driver: bridge
    # If the bot starts without plug-ins, then we disable network interaction:
    driver_opts:
      com.docker.network.bridge.enable_icc: "false"
    # The case when the bot is running with the Monitor plugin enabled:
    #driver_opts:
    #  com.docker.network.bridge.enable_icc: "true"
    ipam:
      driver: default
      config:
        - subnet: 172.20.0.0/16
EOF

    chown root:root "$INSTALL_DIR/docker-compose.yml" 2>/dev/null || true
    chmod 644 "$INSTALL_DIR/docker-compose.yml" 2>/dev/null || true

  } >> "$LOG_FILE" 2>&1 &

  local compose_pid=$!
  show_spinner $compose_pid "Creating docker-compose configuration"
  wait $compose_pid || true
  print_info "Docker Compose configuration created"

  # Start container
  print_info "Starting Docker container..."
  {
    cd "$INSTALL_DIR" || exit 1
    docker compose pull 2>/dev/null || exit 1
    docker compose up -d 2>/dev/null || exit 1
  } >> "$LOG_FILE" 2>&1 &

  local start_pid=$!
  show_spinner $start_pid "Pulling image and starting container"
  wait $start_pid
  local start_status=$?

  if [ $start_status -eq 0 ]; then
    # Verify container is running
    sleep 5
    if docker ps --format "table {{.Names}}" | grep -q "pytmbot"; then
      print_info "Docker container started successfully"

      echo ""
      print_message "$BOLD$GREEN" "DOCKER INSTALLATION COMPLETED!"
      echo ""
      print_message "$WHITE" "Container Status:"
      docker ps --filter "name=pytmbot" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" 2>/dev/null || true
      echo ""
      print_message "$BOLD$YELLOW" "USEFUL COMMANDS:"
      print_message "$WHITE" "• Check logs: docker logs pytmbot -f"
      print_message "$WHITE" "• Restart container: docker restart pytmbot"
      print_message "$WHITE" "• Stop container: docker stop pytmbot"
      print_message "$WHITE" "• Update container: cd $INSTALL_DIR && docker compose pull && docker compose up -d"
      echo ""
    else
      print_error "Container failed to start properly"
      print_info "Check logs with: docker logs pytmbot"
      exit 1
    fi
  else
    print_error "Failed to start Docker container"
    exit 1
  fi
}

# Docker installation from source
install_docker_from_source() {
  show_banner "Docker Build from Source"

  print_info "Building pyTMBot Docker image from source..."

  # Clone repository
  clone_repo

  # Configure bot
  configure_bot

  # Build and start
  print_info "Building and starting Docker container..."
  {
    cd "$INSTALL_DIR" || exit 1
    docker compose build 2>/dev/null || exit 1
    docker compose up -d 2>/dev/null || exit 1
  } >> "$LOG_FILE" 2>&1 &

  local build_pid=$!
  show_spinner $build_pid "Building Docker image and starting container"
  wait $build_pid
  local build_status=$?

  if [ $build_status -eq 0 ]; then
    # Verify container is running
    sleep 5
    if docker ps --format "table {{.Names}}" | grep -q "pytmbot"; then
      print_info "Docker container built and started successfully"

      echo ""
      print_message "$BOLD$GREEN" "DOCKER BUILD COMPLETED!"
      echo ""
      print_message "$WHITE" "Container Status:"
      docker ps --filter "name=pytmbot" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" 2>/dev/null || true
      echo ""
      print_message "$BOLD$YELLOW" "USEFUL COMMANDS:"
      print_message "$WHITE" "• Check logs: docker logs pytmbot -f"
      print_message "$WHITE" "• Restart container: docker restart pytmbot"
      print_message "$WHITE" "• Stop container: docker stop pytmbot"
      print_message "$WHITE" "• Rebuild: cd $INSTALL_DIR && docker compose build && docker compose up -d"
      echo ""
    else
      print_error "Container failed to start properly"
      print_info "Check logs with: docker logs pytmbot"
      exit 1
    fi
  else
    print_error "Failed to build/start Docker container"
    exit 1
  fi
}

# Main menu
main_menu() {
  show_banner "Installation Menu"

  print_message "$BOLD$YELLOW" "REQUIREMENTS CHECK:"
  echo ""
  print_message "$WHITE" "Before proceeding, ensure you have:"
  print_message "$GRAY" "📱 Telegram bot token from @BotFather"
  print_message "$GRAY" "🆔 Your Telegram user ID and chat ID"
  echo ""

  read -r -p "Do you have all required information? [y/N]: " ready
  if [[ ! "$ready" =~ ^[Yy]$ ]]; then
    print_info "Please gather the required information and run the script again"
    print_message "$GRAY" "To get your user ID: send any message to @userinfobot on Telegram"
    exit 0
  fi

  echo ""
  print_message "$BOLD$WHITE" "AVAILABLE OPTIONS:"
  echo ""
  print_message "$WHITE" "1) 🐳 Docker installation"
  print_message "$GRAY" "   - Containerized deployment"
  print_message "$GRAY" "   - Easy updates and isolation"
  print_message "$GRAY" "   - Recommended for servers"
  echo ""
  print_message "$WHITE" "2) 📦 Local installation"
  print_message "$GRAY" "   - Direct system install"
  print_message "$GRAY" "   - More control and flexibility"
  print_message "$GRAY" "   - Systemd service integration"
  echo ""
  print_message "$WHITE" "3) 🔄 Update existing installation"
  print_message "$GRAY" "   - Update to latest version"
  print_message "$GRAY" "   - Preserves configuration"
  print_message "$GRAY" "   - Automatic backup"
  echo ""
  print_message "$WHITE" "4) 🗑️ Uninstall pyTMBot"
  print_message "$GRAY" "   - Complete removal"
  print_message "$GRAY" "   - Optional configuration backup"
  print_message "$GRAY" "   - Clean system state"
  echo ""

  local choice
  while true; do
    read -r -p "Choose an option [1-4]: " choice
    case $choice in
      1) install_bot_in_docker; break ;;
      2) install_local; break ;;
      3) update_menu; break ;;
      4) uninstall_pytmbot; break ;;
      *) print_error "Invalid choice. Please select 1, 2, 3, or 4." ;;
    esac
  done
}

# Update menu for different installation types
update_menu() {
  show_banner "Update Menu"

  # Detect installation type
  local install_type=""

  if [ -f "/etc/systemd/system/$SERVICE_NAME.service" ] && [ -d "$INSTALL_DIR" ]; then
    install_type="local"
  elif [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
    install_type="docker"
  else
    print_error "No pyTMBot installation detected"
    print_info "Please install pyTMBot first using option 1 or 2"
    exit 1
  fi

  echo ""
  print_message "$BOLD$WHITE" "DETECTED INSTALLATION TYPE:"

  case "$install_type" in
    "local")
      print_message "$WHITE" "📦 Local installation (systemd service)"
      echo ""
      read -r -p "Proceed with local update? [Y/n]: " confirm
      if [[ ! "${confirm,,}" =~ ^[n]$ ]]; then
        update_local_pytmbot
      else
        print_info "Update cancelled"
      fi
      ;;
    "docker")
      print_message "$WHITE" "🐳 Docker installation"
      echo ""
      read -r -p "Proceed with Docker update? [Y/n]: " confirm
      if [[ ! "${confirm,,}" =~ ^[n]$ ]]; then
        update_docker_pytmbot
      else
        print_info "Update cancelled"
      fi
      ;;
  esac
}

# Script entry point
main() {
  # Initialize logging
  log_to_file "INFO" "pyTMBot Installer v0.3.0-dev started"
  log_to_file "INFO" "System: $(uname -a 2>/dev/null || echo "Unknown")"
  log_to_file "INFO" "User: $(whoami 2>/dev/null || echo "Unknown")"

  # Check root privileges
  check_root

  # Show main menu
  main_menu

  print_info "Process completed"
  log_to_file "INFO" "Process completed"
}

# Run main function
main "$@"