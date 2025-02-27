
import sys
from test_discord import test_webhook

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python run_webhook_test.py <webhook_url>")
        print("Example: python run_webhook_test.py https://discord.com/api/webhooks/your-webhook-id/your-webhook-token")
        sys.exit(1)
    
    webhook_url = sys.argv[1]
    test_webhook(webhook_url)
