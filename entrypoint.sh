#!/bin/sh
set -uef
########################################################################################################################
#                                                                                                                      #
#                                               pyTMBot - entrypoint.sh                                                #
# -------------------------------------------------------------------------------------------------------------------- #
# A lightweight Telegram bot for managing Docker containers and images, monitoring server statuses,                    #
# and extending its functionality with plugins.                                                                        #
#                                                                                                                      #
# Project:        pyTMBot                                                                                              #
# Author:         Denis Rozhnovskiy <pytelemonbot@mail.ru>                                                             #
# Repository:     https://github.com/orenlab/pytmbot                                                                   #
# License:        MIT                                                                                                  #
# Description:    This entrypoint.sh run the main.py script with the specified arguments.                              #
#                                                                                                                      #
########################################################################################################################

# Constants
PYTHON_PATH="/venv/bin/python3"
MAIN_SCRIPT="main.py"
SALT_SCRIPT="pytmbot/utils/salt.py"

# Default values
LOG_LEVEL="INFO"
MODE="prod"
SALT="False"
PLUGINS=""
WEBHOOK="False"
SOCKET_HOST="127.0.0.1"
HEALTH_CHECK="False"

# Function to validate log level
validate_log_level() {
    case "$1" in
        DEBUG|INFO|ERROR) return 0 ;;
        *) echo "Invalid log level: $1" >&2; return 1 ;;
    esac
}

# Function to validate mode
validate_mode() {
    case "$1" in
        dev|prod) return 0 ;;
        *) echo "Invalid mode: $1" >&2; return 1 ;;
    esac
}

# Function to check dependencies
check_dependencies() {
    if ! command -v "$PYTHON_PATH" >/dev/null 2>&1; then
        echo >&2 "Python3 is required but not installed. Aborting."
        exit 1
    fi

    if [ ! -f "$MAIN_SCRIPT" ]; then
        echo "Error: $MAIN_SCRIPT does not exist or cannot be accessed." >&2
        exit 1
    fi
}

# Function to perform health check
perform_health_check() {
    "$PYTHON_PATH" "$MAIN_SCRIPT" --health_check "True"
    result=$?

    return $result
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
        *)
            echo "Invalid option: $1" >&2
            exit 1
            ;;
    esac
done

# Setup logging symlinks if needed
[ ! -L /dev/stdout ] && ln -sf /proc/self/fd/1 /dev/stdout
[ ! -L /dev/stderr ] && ln -sf /proc/self/fd/2 /dev/stderr

# Check dependencies
check_dependencies

# Handle health check
if [ "$HEALTH_CHECK" = "True" ]; then
    if perform_health_check; then
        exit 0
    else
        exit 1
    fi
fi

# Run the appropriate script
if [ "$SALT" = "True" ]; then
    if [ ! -f "$SALT_SCRIPT" ]; then
        echo "Error: $SALT_SCRIPT does not exist or cannot be accessed." >&2
        exit 1
    fi
    "$PYTHON_PATH" "$SALT_SCRIPT"
else
    "$PYTHON_PATH" "$MAIN_SCRIPT" \
        --log-level "$LOG_LEVEL" \
        --mode "$MODE" \
        --plugins "$PLUGINS" \
        --webhook "$WEBHOOK" \
        --socket_host "$SOCKET_HOST"
fi