import asyncio
import aiohttp
from datetime import datetime
import sys

async def test_webhook(webhook_url):
    """Test if a Discord webhook is working"""
    print(f"Testing webhook: {webhook_url}")

    payload = {
        "username": "SoleAddictionsLLC Monitor Test",
        "content": "This is a test message from your monitor. If you see this, your webhook is working correctly!",
        "embeds": [{
            "title": "Test Product",
            "description": "This is a test notification",
            "color": 3447003,  # Blue color
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {
                    "name": "Status",
                    "value": "Test Successful",
                    "inline": True
                }
            ]
        }]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 204:
                    print("✅ Webhook test successful! Check your Discord channel.")
                    return True
                else:
                    print(f"❌ Webhook test failed. Status code: {response.status}")
                    print(f"Response: {await response.text()}")
                    return False
    except Exception as e:
        print(f"❌ Error testing webhook: {e}")
        return False

async def main():
    if len(sys.argv) != 2:
        print("Usage: python test_discord.py <webhook_url>")
        sys.exit(1)

    webhook_url = sys.argv[1]
    success = await test_webhook(webhook_url)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())