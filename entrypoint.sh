#!/bin/sh
set -uef

# Check if required tools are installed
command -v /venv/bin/python3 >/dev/null 2>&1 || { echo >&2 "Python3 is required but it's not installed. Aborting."; exit 1; }

# Default values
LOG_LEVEL="INFO"
MODE="prod"
SALT="false"

# Parse arguments using getopts for short options
while getopts "l:m:s:" opt; do
  case $opt in
    l) LOG_LEVEL="$OPTARG" ;;
    m) MODE="$OPTARG" ;;
    s) SALT="$OPTARG" ;;
    \?) echo "Invalid option: -$OPTARG" >&2; exit 1 ;;
  esac
done

# Check if -s (salt) was provided
if [ "$SALT" = "true" ]; then
  /venv/bin/python3 pytmbot/utils/salt.py
else
  /venv/bin/python3 main.py --log-level "$LOG_LEVEL" --mode "$MODE"
fi