import os
import discord
from discord.ext import commands
import logging
import aiohttp
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('discord_bot.log'),
        logging.StreamHandler()
    ]
)

class MonitorBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
        # API configuration - will be set up later
        self.api_base_url = os.getenv('MONITOR_API_URL', 'http://localhost:5000/api')
        self.api_key = os.getenv('MONITOR_API_KEY', '')

    async def setup_hook(self):
        await self.load_extension('cogs.monitor_commands')
        
    async def on_ready(self):
        logging.info(f'Logged in as {self.user.name} (ID: {self.user.id})')
        logging.info('------')

def main():
    bot = MonitorBot()
    bot.run(os.getenv('DISCORD_BOT_TOKEN'))

if __name__ == "__main__":
    main()
