ENV_TEMPLATE = """# Dev bot token (if needed)
DEV_BOT_TOKEN=$dev_token
# Prod bot token
BOT_TOKEN=$prod_token
# Add your telegram IDs!
ALLOWED_USER_IDS=[$user_id]
# Setting up administrative (full) access
ALLOWED_ADMINS_IDS=[$admin_id]
# Set Docker Socket o TCP param
DOCKER_HOST='$docker_host'
AUTH_SALT='$auth_salt'
"""
