#!/bin/sh
set -e

########################################################################################################################
#                                               pyTMBot - entrypoint.sh                                               #
########################################################################################################################

# Constants
PYTHON_PATH="/usr/local/bin/python3"
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
    _log_timestamp=$(date "+%Y-%m-%d")
    _log_time=$(date "+%H:%M:%S")

    case "$1" in
        "DEBUG")   _log_formatted_level="DEBUG   " ;;
        "INFO")    _log_formatted_level="INFO    " ;;
        "WARNING") _log_formatted_level="WARNING " ;;
        "ERROR")   _log_formatted_level="ERROR   " ;;
        *)         _log_formatted_level="INFO    " ;;
    esac

    _log_formatted_component=$(printf "%-16s" "$2")
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

        timeout=30
        while [ $timeout -gt 0 ] && kill -0 "$child_pid" 2>/dev/null; do
            sleep 1
            timeout=$((timeout - 1))
        done

        if kill -0 "$child_pid" 2>/dev/null; then
            log "WARNING" "entrypoint" "Process did not terminate gracefully, forcing shutdown" "{\"pid\": $child_pid}"
            kill -9 "$child_pid" 2>/dev/null || true
        fi
    fi
    exit 0
}

# Function to fix Docker group GID at runtime
fix_docker_group_runtime() {
    if [ -S /var/run/docker.sock ]; then
        # Get Docker socket GID
        if stat -c %g /var/run/docker.sock >/dev/null 2>&1; then
            DOCKER_SOCKET_GID=$(stat -c %g /var/run/docker.sock)
        elif stat -f %g /var/run/docker.sock >/dev/null 2>&1; then
            DOCKER_SOCKET_GID=$(stat -f %g /var/run/docker.sock)
        else
            log "WARNING" "entrypoint" "Cannot determine Docker socket GID" "{}"
            return 1
        fi

        # Get current container docker group GID
        CURRENT_DOCKER_GID=$(getent group docker | cut -d: -f3 2>/dev/null || echo "")

        log "INFO" "entrypoint" "Docker socket analysis" "{\"socket_gid\": $DOCKER_SOCKET_GID, \"container_gid\": \"$CURRENT_DOCKER_GID\"}"

        # If GIDs don't match, we need to adjust
        if [ "$DOCKER_SOCKET_GID" != "$CURRENT_DOCKER_GID" ]; then
            log "INFO" "entrypoint" "Adjusting Docker group GID for socket access" "{\"from\": \"$CURRENT_DOCKER_GID\", \"to\": $DOCKER_SOCKET_GID}"

            # Check if we can modify groups (running as root during startup)
            if [ "$(id -u)" -eq 0 ]; then
                # We're running as root, can modify groups
                if getent group "$DOCKER_SOCKET_GID" >/dev/null 2>&1; then
                    # Target GID exists, add user to that group
                    EXISTING_GROUP=$(getent group "$DOCKER_SOCKET_GID" | cut -d: -f1)
                    log "INFO" "entrypoint" "Adding user to existing group" "{\"group\": \"$EXISTING_GROUP\", \"gid\": $DOCKER_SOCKET_GID}"
                    addgroup pytmbot "$EXISTING_GROUP" 2>/dev/null || true
                else
                    # Change docker group GID
                    log "INFO" "entrypoint" "Changing docker group GID" "{\"new_gid\": $DOCKER_SOCKET_GID}"
                    groupmod -g "$DOCKER_SOCKET_GID" docker 2>/dev/null || true
                fi
            else
                # Running as non-root, just inform about the issue
                log "WARNING" "entrypoint" "Cannot modify groups (not running as root)" "{\"suggestion\": \"Use --group-add $DOCKER_SOCKET_GID or rebuild with correct GID\"}"
            fi
        else
            log "INFO" "entrypoint" "Docker group GID matches socket GID" "{\"gid\": $DOCKER_SOCKET_GID}"
        fi
    else
        log "INFO" "entrypoint" "Docker socket not mounted" "{\"path\": \"/var/run/docker.sock\"}"
    fi
}

# Function to check Docker access after setup
check_docker_access() {
    if [ -S /var/run/docker.sock ]; then
        if [ -r /var/run/docker.sock ] && [ -w /var/run/docker.sock ]; then
            log "INFO" "entrypoint" "Docker socket access OK" "{\"user\": \"$(id -un)\", \"groups\": \"$(groups)\"}"
            return 0
        else
            log "WARNING" "entrypoint" "Docker socket access denied" "{\"user\": \"$(id -un)\", \"groups\": \"$(groups)\", \"socket_perms\": \"$(ls -la /var/run/docker.sock 2>/dev/null || echo 'unknown')\"}"
            return 1
        fi
    else
        log "INFO" "entrypoint" "Docker socket not available" "{}"
        return 1
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

    if [ ! -f "$MAIN_SCRIPT" ]; then
        log "ERROR" "entrypoint" "Health check failed: Main script not found" "{\"script\": \"$MAIN_SCRIPT\"}"
        exit 1
    fi

    if ! "$PYTHON_PATH" -c "import sys; print('Python OK')" >/dev/null 2>&1; then
        log "ERROR" "entrypoint" "Health check failed: Python not working" "{\"python_path\": \"$PYTHON_PATH\"}"
        exit 1
    fi

    check_docker_access || log "WARNING" "entrypoint" "Docker access not available during health check" "{}"

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
            fix_docker_group_runtime
            check_docker_access
            exit 0
            ;;
        *)
            log "ERROR" "entrypoint" "Invalid option" "{\"option\": \"$1\", \"available\": \"--log-level, --mode, --salt, --plugins, --webhook, --socket_host, --health_check, --check-docker, --debug-groups\"}"
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

# Fix Docker group if needed and check access
fix_docker_group_runtime
check_docker_access

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
    $PYTHON_PATH "$SALT_SCRIPT" &
    child_pid=$!
else
    log "INFO" "entrypoint" "Starting main application" "{\"script\": \"$MAIN_SCRIPT\"}"
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