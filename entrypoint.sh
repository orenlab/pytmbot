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

# Create symlinks for logging to stdout and stderr if they do not exist
[ ! -L /dev/stdout ] && ln -sf /dev/stdout /dev/stdout
[ ! -L /dev/stderr ] && ln -sf /dev/stderr /dev/stderr

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

# Default values for script arguments
LOG_LEVEL="INFO"         # Set the default log level
MODE="prod"              # Set the default mode (prod/dev)
SALT="False"             # Default value for salt execution
PLUGINS=""               # Default value for plugins
WEBHOOK="False"          # Set default value for webhook
SOCKET_HOST="127.0.0.1" # Default socket host
HEALTH_CHECK="False"     # Set default value for health check

# Parse command-line arguments using a while loop
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
            SALT="True"  # Enable salt execution
            shift
            ;;
        --plugins)
            PLUGINS="$2"  # Set plugins to load
            shift 2
            ;;
        --webhook)
            WEBHOOK="True"  # Enable webhook mode
            shift
            ;;
        --socket_host)
            SOCKET_HOST="$2"  # Set socket host address
            shift 2
            ;;
        --health_check)
            HEALTH_CHECK="True"  # Enable health check
            shift
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

if [ "$HEALTH_CHECK" = "True" ]; then

    if pgrep -f "/venv/bin/python3 main.py --health_check" > /dev/null; then
        exit 0  # Healthy
    else
        exit 1  # Unhealthy
    fi
fi

if [ "$SALT" = "True" ]; then
    if [ ! -f "pytmbot/utils/salt.py" ]; then
        echo "Error: pytmbot/utils/salt.py does not exist or cannot be accessed." >&2
        exit 1
    fi
    /venv/bin/python3 pytmbot/utils/salt.py || handle_error
else
    # Execute the main Python script with the specified arguments
    /venv/bin/python3 main.py --log-level "$LOG_LEVEL" --mode "$MODE" --plugins "$PLUGINS" --webhook "$WEBHOOK" --socket_host "$SOCKET_HOST" || handle_error
fi

# Exit successfully
exit 0