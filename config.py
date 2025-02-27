import os

# Discord Webhook Configuration
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Shopify API Configuration
SHOPIFY_RATE_LIMIT = 2  # requests per second
MONITOR_DELAY = 5  # seconds between checks

# Product Monitor Configuration
MAX_PRODUCTS = 100
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

# Webhook Embed Colors
SUCCESS_COLOR = 0x00ff00
ERROR_COLOR = 0xff0000
INFO_COLOR = 0x0000ff
