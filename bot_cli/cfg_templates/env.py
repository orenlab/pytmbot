ENV_TEMPLATE = """# Dev bot token (if needed). If not set, --mode in Dockerfile need set to "prod"
DEV_BOT_TOKEN=$dev_token
# Prod bot token
BOT_TOKEN=$prod_token
# Add your telegram IDs. And your bot too!
ALLOWED_USER_IDS=[$user_id]
# Set Docker Socket o TCP param
DOCKER_HOST='$docker_host'
# Set Podman Socket o TCP param
PODMAN_HOST='$podman_host'
"""
