#!/bin/sh
set -uef

# (c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
# pyTMBot - A simple Telegram bot to handle Docker containers and images,
# also providing basic information about the status of local servers.


while [[ $# -gt 0 ]]; do
  case "$1" in
    --log-level)
      LOG_LEVEL="$2"
      shift 2
      ;;
    --mode)
      MODE="$2"
      shift 2
      ;;
    --salt)
      SALT="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

# Set default values if not provided
LOG_LEVEL=${LOG_LEVEL:-INFO}
MODE=${MODE:-prod}
SALT=${SALT:-false}

# Check if --salt was provided
if [ "$SALT" = true ]; then
  /venv/bin/python3 pytmbot/utils/salt.py
else
  /venv/bin/python3 main.py --log-level "$LOG_LEVEL" --mode "$MODE"
fi