#!/bin/sh
set -e

########################################################################################################################
#                                                                                                                      #
#                                               pyTMBot - Entrypoint                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
# A lightweight Telegram bot for managing Docker containers and images, monitoring server statuses,                    #
# and extending its functionality with plugins.                                                                        #
#                                                                                                                      #
# Project:        pyTMBot                                                                                              #
# Author:         Denis Rozhnovskiy <pytelemonbot@mail.ru>                                                             #
# Repository:     https://github.com/orenlab/pytmbot                                                                   #
# License:        MIT                                                                                                  #
#                                                                                                                      #
########################################################################################################################

# Constants
# IMPORTANT: use venv interpreter directly; `/usr/local/bin/python3` symlink
# does not reliably activate venv on Ubuntu images.
PYTHON_PATH="/opt/venv/bin/python3"
MAIN_SCRIPT="pytmbot/main.py"
SALT_SCRIPT="pytmbot/utils/salt.py"

# Default values
LOG_LEVEL="INFO"
MODE="prod"
LOG_FORMAT=""
SALT="False"
PLUGINS=""
WEBHOOK="False"
SOCKET_HOST="127.0.0.1"
HEALTH_CHECK="False"
DEBUG="False"
COLORIZE_LOGS="True"
STRICT_DOCKER_ACCESS="${STRICT_DOCKER_ACCESS:-False}"

# Variables for process management
child_pid=""

# Function to format logs like the application
log() {
    _log_timestamp=$(date "+%Y-%m-%d")
    _log_time=$(date "+%H:%M:%S")

    case "$1" in
        "TRACE")   _log_formatted_level="TRACE   " ;;
        "DEBUG")   _log_formatted_level="DEBUG   " ;;
        "INFO")    _log_formatted_level="INFO    " ;;
        "WARNING") _log_formatted_level="WARNING " ;;
        "ERROR")   _log_formatted_level="ERROR   " ;;
        "CRITICAL") _log_formatted_level="CRITICAL" ;;
        *)         _log_formatted_level="INFO    " ;;
    esac

    _log_formatted_component=$(printf "%-16s" "$2")
    _log_extra_data="$4"
    if [ -z "$_log_extra_data" ]; then
        _log_extra_data="{}"
    fi

    echo "$_log_timestamp [$_log_time][$_log_formatted_level][$_log_formatted_component] › $3 › $_log_extra_data"
}

# Validate that an option requiring a value received one
require_option_value() {
    _option_name="$1"
    _option_value="$2"

    if [ -z "$_option_value" ] || [ "${_option_value#--}" != "$_option_value" ]; then
        log "ERROR" "entrypoint" "Missing value for option" "{\"option\": \"$_option_name\"}"
        exit 1
    fi
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

# Explain how the Docker socket group relates to this process (diagnostics only, never changes groups)
report_docker_socket_group() {
    if [ ! -S /var/run/docker.sock ]; then
        log "INFO" "entrypoint" "Docker socket not mounted" "{\"path\": \"/var/run/docker.sock\"}"
        return 0
    fi

    DOCKER_SOCKET_GID=$(stat -c %g /var/run/docker.sock 2>/dev/null || echo "")
    case "$DOCKER_SOCKET_GID" in
        ''|*[!0-9]*)
            log "WARNING" "entrypoint" "Cannot determine Docker socket GID" "{}"
            return 0
            ;;
    esac

    if id -G | tr ' ' '\n' | grep -Fxq "$DOCKER_SOCKET_GID"; then
        log "INFO" "entrypoint" "Docker socket group is granted to this process" "{\"socket_gid\": $DOCKER_SOCKET_GID}"
    else
        log "WARNING" "entrypoint" "Docker socket group is not granted to this process" "{\"socket_gid\": $DOCKER_SOCKET_GID, \"fix\": \"docker run --group-add $DOCKER_SOCKET_GID (compose: group_add)\"}"
    fi
}

# Function to check Docker access after setup
check_docker_access() {
    if [ -S /var/run/docker.sock ]; then
        if [ -r /var/run/docker.sock ] && [ -w /var/run/docker.sock ]; then
            log "INFO" "entrypoint" "Docker socket access OK" "{\"user\": \"$(id -un 2>/dev/null || id -u)\", \"groups\": \"$(groups 2>/dev/null)\"}"
            return 0
        else
            log "WARNING" "entrypoint" "Docker socket access denied" "{\"user\": \"$(id -un 2>/dev/null || id -u)\", \"groups\": \"$(groups 2>/dev/null)\", \"socket_perms\": \"$(ls -la /var/run/docker.sock 2>/dev/null || echo 'unknown')\"}"
            return 1
        fi
    else
        log "INFO" "entrypoint" "Docker socket not available" "{}"
        return 1
    fi
}

# Docker diagnostics for --check-docker: succeeds only when the Docker API answers a ping, made with the bot's Docker
# settings when a config file is present (default local socket otherwise). Socket permissions only explain a failure.
check_docker() {
    report_docker_socket_group
    check_docker_access || true

    _docker_check_module="pytmbot.adapters.docker.check"
    if "$PYTHON_PATH" -m "$_docker_check_module"; then
        log "INFO" "entrypoint" "Docker API check passed" "{\"source\": \"$_docker_check_module\"}"
        return 0
    fi
    log "ERROR" "entrypoint" "Docker API check failed" "{\"source\": \"$_docker_check_module\"}"
    return 1
}

# Function to validate log level
validate_log_level() {
    case "$1" in
        TRACE|DEBUG|INFO|WARNING|ERROR|CRITICAL) return 0 ;;
        *) log "ERROR" "entrypoint" "Invalid log level" "{\"level\": \"$1\"}"; return 1 ;;
    esac
}

# Function to validate log format
validate_log_format() {
    case "$1" in
        human|json) return 0 ;;
        *) log "ERROR" "entrypoint" "Invalid log format" "{\"format\": \"$1\"}"; return 1 ;;
    esac
}

# Function to validate mode
validate_mode() {
    case "$1" in
        dev|prod) return 0 ;;
        *) log "ERROR" "entrypoint" "Invalid mode" "{\"mode\": \"$1\"}"; return 1 ;;
    esac
}

# Function to validate boolean values
validate_bool() {
    case "$1" in
        true|false|True|False|TRUE|FALSE|1|0|yes|no|on|off|YES|NO|ON|OFF)
            return 0
            ;;
        *)
            log "ERROR" "entrypoint" "Invalid boolean value" "{\"value\": \"$1\"}"
            return 1
            ;;
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

# Container health check: judge the health snapshot published by the running bot
health_check() {
    log "INFO" "entrypoint" "Performing health check" "{}"

    if [ ! -f "$MAIN_SCRIPT" ]; then
        log "ERROR" "entrypoint" "Health check failed: Main script not found" "{\"script\": \"$MAIN_SCRIPT\"}"
        exit 1
    fi

    if ! "$PYTHON_PATH" -c "import sys; print('Python OK')" >/dev/null 2>&1; then
        log "ERROR" "entrypoint" "Health check failed: Python not working" "{\"python_path\": \"$PYTHON_PATH\"}"
        exit 1
    fi

    check_docker_access || log "WARNING" "entrypoint" "Docker access not available during health check" "{}"

    # The probe only reads the health snapshot the running bot writes to its state directory
    # (PYTMBOT_STATE_DIR) and prints the reason of a failure to stderr.
    _health_probe="pytmbot.health_system.probe"
    _python_health_rc=0
    "$PYTHON_PATH" -m "$_health_probe" || _python_health_rc=$?

    case "$_python_health_rc" in
        0)
            log "INFO" "entrypoint" "Health check passed" "{\"source\": \"$_health_probe\", \"code\": 0}"
            return 0
            ;;
        1)
            log "ERROR" "entrypoint" "Health check failed: bot is unhealthy or its health snapshot is stale" "{\"source\": \"$_health_probe\", \"code\": 1}"
            return 1
            ;;
        2)
            log "ERROR" "entrypoint" "Health check failed: no health data yet (bot still starting or not running) or the state directory is not writable" "{\"source\": \"$_health_probe\", \"code\": 2}"
            return 1
            ;;
        *)
            log "ERROR" "entrypoint" "Unexpected health check exit code" "{\"source\": \"$_health_probe\", \"code\": $_python_health_rc}"
            return 1
            ;;
    esac
}

# Parse command line arguments
while [ $# -gt 0 ]; do
    case "$1" in
        --log-level)
            require_option_value "--log-level" "$2"
            if validate_log_level "$2"; then
                LOG_LEVEL="$2"
            else
                exit 1
            fi
            shift 2
            ;;
        --mode)
            require_option_value "--mode" "$2"
            if validate_mode "$2"; then
                MODE="$2"
            else
                exit 1
            fi
            shift 2
            ;;
        --log-format)
            require_option_value "--log-format" "$2"
            if validate_log_format "$2"; then
                LOG_FORMAT="$2"
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
            shift
            PLUGINS=""
            while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do
                if [ -z "$PLUGINS" ]; then
                    PLUGINS="$1"
                else
                    PLUGINS="$PLUGINS $1"
                fi
                shift
            done
            ;;
        --webhook)
            if [ $# -gt 1 ] && [ "${2#--}" = "$2" ]; then
                require_option_value "--webhook" "$2"
                if validate_bool "$2"; then
                    WEBHOOK="$2"
                else
                    exit 1
                fi
                shift 2
            else
                WEBHOOK="True"
                shift
            fi
            ;;
        --socket_host)
            require_option_value "--socket_host" "$2"
            SOCKET_HOST="$2"
            shift 2
            ;;
        --colorize_logs)
            require_option_value "--colorize_logs" "$2"
            if validate_bool "$2"; then
                COLORIZE_LOGS="$2"
            else
                exit 1
            fi
            shift 2
            ;;
        --debug)
            DEBUG="True"
            shift
            ;;
        --health_check)
            HEALTH_CHECK="True"
            shift
            ;;
        --check-docker)
            if check_docker; then
                exit 0
            fi
            exit 1
            ;;
        *)
            log "ERROR" "entrypoint" "Invalid option" "{\"option\": \"$1\", \"available\": \"--log-level, --mode, --log-format, --colorize_logs, --debug, --salt, --plugins, --webhook, --socket_host, --health_check, --check-docker\"}"
            exit 1
            ;;
    esac
done

if [ -n "$LOG_FORMAT" ]; then
    EFFECTIVE_LOG_FORMAT="$LOG_FORMAT"
elif [ "$MODE" = "dev" ]; then
    EFFECTIVE_LOG_FORMAT="human(auto)"
else
    EFFECTIVE_LOG_FORMAT="json(auto)"
fi

log "INFO" "entrypoint" "Starting pyTMBot from entrypoint... ›››››››› 🚀🚀🚀" "{}"
log "INFO" "entrypoint" "User information" "{\"user\": \"$(id -un 2>/dev/null || id -u)\", \"uid\": $(id -u), \"gid\": $(id -g), \"groups\": \"$(groups 2>/dev/null)\"}"
log "INFO" "entrypoint" "Configuration" "{\"python\": \"$PYTHON_PATH\", \"mode\": \"$MODE\", \"log_level\": \"$LOG_LEVEL\", \"log_format\": \"$EFFECTIVE_LOG_FORMAT\", \"colorize_logs\": \"$COLORIZE_LOGS\", \"debug\": \"$DEBUG\", \"plugins\": \"$PLUGINS\", \"webhook\": \"$WEBHOOK\", \"socket_host\": \"$SOCKET_HOST\", \"strict_docker_access\": \"$STRICT_DOCKER_ACCESS\"}"

# Check dependencies
check_dependencies

# Report Docker socket group and check access
report_docker_socket_group
if ! check_docker_access; then
    case "$STRICT_DOCKER_ACCESS" in
        true|True|TRUE|1|yes|YES|on|ON)
            log "ERROR" "entrypoint" "Docker access is required in strict mode" "{\"strict_docker_access\": \"$STRICT_DOCKER_ACCESS\"}"
            exit 1
            ;;
        false|False|FALSE|0|no|NO|off|OFF)
            log "WARNING" "entrypoint" "Docker access unavailable, continuing in degraded mode" "{\"strict_docker_access\": \"$STRICT_DOCKER_ACCESS\"}"
            ;;
        *)
            log "WARNING" "entrypoint" "Invalid STRICT_DOCKER_ACCESS value, treating as false" "{\"strict_docker_access\": \"$STRICT_DOCKER_ACCESS\"}"
            log "WARNING" "entrypoint" "Docker access unavailable, continuing in degraded mode" "{\"strict_docker_access\": \"$STRICT_DOCKER_ACCESS\"}"
            ;;
    esac
fi

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
    set -- \
        "$PYTHON_PATH" "$MAIN_SCRIPT" \
        --log-level "$LOG_LEVEL" \
        --mode "$MODE" \
        --colorize_logs "$COLORIZE_LOGS" \
        --webhook "$WEBHOOK" \
        --socket_host "$SOCKET_HOST"

    if [ -n "$LOG_FORMAT" ]; then
        set -- "$@" --log-format "$LOG_FORMAT"
    fi

    if [ -n "$PLUGINS" ]; then
        set -- "$@" --plugins
        for _plugin in $PLUGINS; do
            set -- "$@" "$_plugin"
        done
    fi

    if [ "$DEBUG" = "True" ]; then
        set -- "$@" --debug
    fi

    "$@" &
    child_pid=$!
fi

log "INFO" "entrypoint" "Process started" "{\"pid\": $child_pid}"

# Wait for the Python process
wait $child_pid
