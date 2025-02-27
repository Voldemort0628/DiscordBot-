import os

# Discord Webhook Configuration
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Shopify API Configuration
SHOPIFY_RATE_LIMIT = 1  # requests per second per store
MONITOR_DELAY = 30  # seconds between full store checks

# Product Monitor Configuration
MAX_PRODUCTS = 250  # increased to handle multiple stores
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

# Webhook Embed Colors
SUCCESS_COLOR = 0x00ff00
ERROR_COLOR = 0xff0000
INFO_COLOR = 0x0000ff