#!/bin/sh
set -e

########################################################################################################################
#                                               pyTMBot - entrypoint.sh                                                   #
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

# Variables for process management
child_pid=""

# Trap signals for proper shutdown
trap 'handle_exit' TERM INT QUIT HUP

handle_exit() {

    if [ -n "$child_pid" ]; then
        echo "››››››››››››››››››››››››››››››››››››››››››››››››››› Sending TERM signal to Python process (PID: $child_pid)"
        kill -TERM "$child_pid" 2>/dev/null || true

        # Wait for the process to finish or timeout after 30 seconds
        timeout=30
        while [ $timeout -gt 0 ] && kill -0 "$child_pid" 2>/dev/null; do
            sleep 1
            timeout=$((timeout - 1))
        done

        # Force kill if still running
        if kill -0 "$child_pid" 2>/dev/null; then
            echo "Process did not terminate gracefully, forcing shutdown"
            kill -9 "$child_pid" 2>/dev/null || true
        fi
    fi

    exit 0
}

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

# Check dependencies
check_dependencies

# Handle health check
if [ "$HEALTH_CHECK" = "True" ]; then
    "$PYTHON_PATH" "$MAIN_SCRIPT" --health_check "True"
    exit $?
fi

# Run the appropriate script
if [ "$SALT" = "True" ]; then
    if [ ! -f "$SALT_SCRIPT" ]; then
        echo "Error: $SALT_SCRIPT does not exist or cannot be accessed." >&2
        exit 1
    fi
    # Run salt script
    $PYTHON_PATH "$SALT_SCRIPT" &
    child_pid=$!
else
    # Run main script
    $PYTHON_PATH "$MAIN_SCRIPT" \
        --log-level "$LOG_LEVEL" \
        --mode "$MODE" \
        --plugins "$PLUGINS" \
        --webhook "$WEBHOOK" \
        --socket_host "$SOCKET_HOST" &
    child_pid=$!
fi

# Wait for the Python process
wait $child_pid