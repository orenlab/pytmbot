ENV_TEMPLATE = """# Dev bot token (if needed). If not set, --mode in Dockerfile need set in prod
DEV_BOT_TOKEN=$dev_token
# Prod bot token
BOT_TOKEN=$prod_token
"""