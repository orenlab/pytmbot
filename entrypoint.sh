#!/bin/sh
set -uef

# Create symlinks for logging to stdout and stderr
ln -sf /dev/stdout /dev/stdout
ln -sf /dev/stderr /dev/stderr

# Function to handle errors
handle_error() {
    echo "An unexpected error occurred. Exiting." >&2
    exit 1
}


# Check if required tools are installed
if ! command -v /venv/bin/python3 >/dev/null 2>&1; then
    echo >&2 "Python3 is required but it's not installed. Aborting."
    exit 1
fi

# Default values
LOG_LEVEL="INFO"
MODE="prod"
SALT="false"
PLUGINS=""
WEBHOOK="False"  # Set default value for webhook
SOCKET_HOST="127.0.0.1"

# Parse arguments using a while loop
while [ $# -gt 0 ]; do
    case "$1" in
        --log-level)
            if [ "$2" != "DEBUG" ] && [ "$2" != "INFO" ] && [ "$2" != "ERROR" ]; then
                echo "Invalid log level: $2" >&2
                exit 1
            fi
            LOG_LEVEL="$2"
            shift 2
            ;;
        --mode)
            if [ "$2" != "dev" ] && [ "$2" != "prod" ]; then
                echo "Invalid mode: $2" >&2
                exit 1
            fi
            MODE="$2"
            shift 2
            ;;
        --salt)
            SALT="true"
            shift
            ;;
        --plugins)
            PLUGINS="$2"
            shift 2
            ;;
        --webhook)
            WEBHOOK="True"  # Set webhook to True if option is provided
            shift
            ;;
        --socket_host)
            SOCKET_HOST="$2"
            shift 2
            ;;
        *)
            echo "Invalid option: $1" >&2
            exit 1
            ;;
    esac
done

# Verify necessary files and permissions
if [ ! -f "main.py" ]; then
    echo "Error: main.py does not exist or cannot be accessed." >&2
    exit 1
fi

if [ "$SALT" = "true" ]; then
    if [ ! -f "pytmbot/utils/salt.py" ]; then
        echo "Error: pytmbot/utils/salt.py does not exist or cannot be accessed." >&2
        exit 1
    fi
    /venv/bin/python3 pytmbot/utils/salt.py || handle_error
else
    # Execute the main Python script without local logging
    /venv/bin/python3 main.py --log-level "$LOG_LEVEL" --mode "$MODE" --plugins "$PLUGINS" --webhook "$WEBHOOK" --socket_host "$SOCKET_HOST" || handle_error
fi

# Exit successfully
exit 0