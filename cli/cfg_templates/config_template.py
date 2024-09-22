ENV_TEMPLATE = """
# Setup bot tokens
bot_token:
  # Prod bot token.
  prod_token:
    - '$prod_token'
  # Development bot token. Not necessary for production bot.
  dev_bot_token:
    - '$dev_token'
# Setup access control
access_control:
  # The ID of the users who have permission to access the bot.
  # You can have one or more values - there are no restrictions.
  allowed_user_ids:
    - [$user_id]
  # The ID of the admins who have permission to access the bot.
  # You can have one or more values, there are no restrictions.
  # However, it's important to keep in mind that these users will be able to manage Docker images and containers.
  allowed_admins_ids:
    - [$admin_id]
  # Salt is used to generate TOTP (Time-Based One-Time Password) secrets and to verify the TOTP code.
  # A script for the fast generation of a truly unique "salt" is available in the bot's repository.
  auth_salt:
    - '$auth_salt'
# Docker settings
docker:
  # Docker socket. Usually: unix:///var/run/docker.sock.
  host:
    - '$docker_host'
"""
