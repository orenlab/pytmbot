#!/bin/sh
set -e

########################################################################################################################
#                                               pyTMBot - entrypoint.sh                                               #
########################################################################################################################

# Constants
PYTHON_PATH="/venv/bin/python3"
MAIN_SCRIPT="pytmbot/main.py"
SALT_SCRIPT="pytmbot/utils/salt.py"

# Default values
LOG_LEVEL="INFO"
MODE="prod"
SALT="False"
PLUGINS=""
WEBHOOK="False"
SOCKET_HOST="127.0.0.1"
HEALTH_CHECK="False"

# Variables for process management
child_pid=""

# Function to format logs like the application
log() {
    # Get current date and time in the same format as the application
    _log_timestamp=$(date "+%Y-%m-%d")
    _log_time=$(date "+%H:%M:%S")

    # Format level to be 8 characters with padding
    case "$1" in
        "DEBUG")   _log_formatted_level="DEBUG   " ;;
        "INFO")    _log_formatted_level="INFO    " ;;
        "WARNING") _log_formatted_level="WARNING " ;;
        "ERROR")   _log_formatted_level="ERROR   " ;;
        *)         _log_formatted_level="INFO    " ;;
    esac

    # Format component to be 16 characters with padding
    _log_formatted_component=$(printf "%-16s" "$2")

    # Default extra data if not provided
    _log_extra_data="$4"
    if [ -z "$_log_extra_data" ]; then
        _log_extra_data="{}"
    fi

    echo "$_log_timestamp [$_log_time][$_log_formatted_level][$_log_formatted_component] › $3 › $_log_extra_data"
}

# Trap signals for proper shutdown
trap 'handle_exit' TERM INT QUIT HUP

handle_exit() {
    if [ -n "$child_pid" ]; then
        log "INFO" "entrypoint" "Sending TERM signal to Python process" "{\"pid\": $child_pid}"
        kill -TERM "$child_pid" 2>/dev/null || true

        # Wait for the process to finish or timeout after 30 seconds
        timeout=30
        while [ $timeout -gt 0 ] && kill -0 "$child_pid" 2>/dev/null; do
            sleep 1
            timeout=$((timeout - 1))
        done

        # Force kill if still running
        if kill -0 "$child_pid" 2>/dev/null; then
            log "WARNING" "entrypoint" "Process did not terminate gracefully, forcing shutdown" "{\"pid\": $child_pid}"
            kill -9 "$child_pid" 2>/dev/null || true
        fi
    fi

    exit 0
}

# Function to check Docker socket permissions and setup access
check_docker_socket() {
    if [ -S /var/run/docker.sock ]; then
        # Use different stat command based on OS
        if stat -c %g /var/run/docker.sock >/dev/null 2>&1; then
            DOCKER_SOCKET_GID=$(stat -c %g /var/run/docker.sock)
        elif stat -f %g /var/run/docker.sock >/dev/null 2>&1; then
            DOCKER_SOCKET_GID=$(stat -f %g /var/run/docker.sock)
        else
            log "WARNING" "entrypoint" "Cannot determine Docker socket group ID" "{}"
            return
        fi

        log "INFO" "entrypoint" "Docker socket found" "{\"group_id\": $DOCKER_SOCKET_GID}"

        # Check if current user can access docker socket
        if ! [ -r /var/run/docker.sock ] || ! [ -w /var/run/docker.sock ]; then
            log "WARNING" "entrypoint" "Current user cannot access Docker socket" "{\"suggestion\": \"docker run --group-add $DOCKER_SOCKET_GID ...\"}"
        else
            log "INFO" "entrypoint" "Docker socket access OK" "{}"
        fi

        # Test Docker connectivity
        if command -v docker >/dev/null 2>&1; then
            if docker version >/dev/null 2>&1; then
                log "INFO" "entrypoint" "Docker client connectivity OK" "{}"
            else
                log "WARNING" "entrypoint" "Docker client cannot connect to daemon" "{}"
            fi
        else
            log "INFO" "entrypoint" "Docker client not installed in container (using socket directly)" "{}"
        fi
    else
        log "WARNING" "entrypoint" "Docker socket not found" "{\"path\": \"/var/run/docker.sock\"}"
    fi
}

# Function to validate log level
validate_log_level() {
    case "$1" in
        DEBUG|INFO|ERROR) return 0 ;;
        *) log "ERROR" "entrypoint" "Invalid log level" "{\"level\": \"$1\"}"; return 1 ;;
    esac
}

# Function to validate mode
validate_mode() {
    case "$1" in
        dev|prod) return 0 ;;
        *) log "ERROR" "entrypoint" "Invalid mode" "{\"mode\": \"$1\"}"; return 1 ;;
    esac
}

# Function to check dependencies
check_dependencies() {
    if ! command -v "$PYTHON_PATH" >/dev/null 2>&1; then
        log "ERROR" "entrypoint" "Python3 is required but not installed" "{\"path\": \"$PYTHON_PATH\"}"
        exit 1
    fi

    if [ ! -f "$MAIN_SCRIPT" ]; then
        log "ERROR" "entrypoint" "Main script does not exist or cannot be accessed" "{\"script\": \"$MAIN_SCRIPT\"}"
        exit 1
    fi

    log "DEBUG" "entrypoint" "Dependencies check completed" "{\"python_path\": \"$PYTHON_PATH\", \"main_script\": \"$MAIN_SCRIPT\"}"
}

# Enhanced health check function
health_check() {
    log "INFO" "entrypoint" "Performing comprehensive health check" "{}"

    # Check main script accessibility
    if [ ! -f "$MAIN_SCRIPT" ]; then
        log "ERROR" "entrypoint" "Health check failed: Main script not found" "{\"script\": \"$MAIN_SCRIPT\"}"
        exit 1
    fi

    # Check Docker socket if mounted
    if [ -S /var/run/docker.sock ]; then
        if [ -r /var/run/docker.sock ]; then
            log "INFO" "entrypoint" "Docker socket accessible" "{}"
        else
            log "WARNING" "entrypoint" "Docker socket found but not accessible" "{}"
        fi
    fi

    log "INFO" "entrypoint" "Health check passed" "{}"
    return 0
}

# Parse command line arguments
while [ $# -gt 0 ]; do
    case "$1" in
        --log-level)
            if validate_log_level "$2"; then
                LOG_LEVEL="$2"
            else
                exit 1
            fi
            shift 2
            ;;
        --mode)
            if validate_mode "$2"; then
                MODE="$2"
            else
                exit 1
            fi
            shift 2
            ;;
        --salt)
            SALT="True"
            shift
            ;;
        --plugins)
            PLUGINS="$2"
            shift 2
            ;;
        --webhook)
            WEBHOOK="True"
            shift
            ;;
        --socket_host)
            SOCKET_HOST="$2"
            shift 2
            ;;
        --health_check)
            HEALTH_CHECK="True"
            shift
            ;;
        --check-docker)
            check_docker_socket
            exit 0
            ;;
        *)
            log "ERROR" "entrypoint" "Invalid option" "{\"option\": \"$1\", \"available\": \"--log-level, --mode, --salt, --plugins, --webhook, --socket_host, --health_check, --check-docker\"}"
            exit 1
            ;;
    esac
done

# Show startup info
log "INFO" "entrypoint" "Starting pyTMBot from entrypoint... ›››››››› 🚀🚀🚀" "{}"
log "INFO" "entrypoint" "User information" "{\"user\": \"$(id -un)\", \"uid\": $(id -u), \"gid\": $(id -g), \"groups\": \"$(groups)\"}"
log "INFO" "entrypoint" "Configuration" "{\"python\": \"$PYTHON_PATH\", \"mode\": \"$MODE\", \"log_level\": \"$LOG_LEVEL\"}"

# Check dependencies
check_dependencies

# Check Docker socket access
check_docker_socket

# Handle health check
if [ "$HEALTH_CHECK" = "True" ]; then
    health_check
    exit $?
fi

# Run the appropriate script
if [ "$SALT" = "True" ]; then
    if [ ! -f "$SALT_SCRIPT" ]; then
        log "ERROR" "entrypoint" "Salt script does not exist or cannot be accessed" "{\"script\": \"$SALT_SCRIPT\"}"
        exit 1
    fi
    log "INFO" "entrypoint" "Starting salt script" "{\"script\": \"$SALT_SCRIPT\"}"
    # Run salt script
    $PYTHON_PATH "$SALT_SCRIPT" &
    child_pid=$!
else
    log "INFO" "entrypoint" "Starting main application" "{\"script\": \"$MAIN_SCRIPT\"}"
    # Run main script
    $PYTHON_PATH "$MAIN_SCRIPT" \
        --log-level "$LOG_LEVEL" \
        --mode "$MODE" \
        --plugins "$PLUGINS" \
        --webhook "$WEBHOOK" \
        --socket_host "$SOCKET_HOST" &
    child_pid=$!
fi

log "INFO" "entrypoint" "Process started" "{\"pid\": $child_pid}"

# Wait for the Python process
wait $child_pid