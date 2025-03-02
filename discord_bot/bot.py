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
        # Configure proper intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.guild_messages = True

        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=commands.DefaultHelpCommand(
                no_category='Monitor Commands'
            )
        )

        # API configuration
        self.api_base_url = os.getenv('MONITOR_API_URL', 'http://localhost:5000/api')
        self.api_key = os.environ['MONITOR_API_KEY']

    async def setup_hook(self):
        await self.load_extension('cogs.monitor_commands')

    async def on_ready(self):
        logging.info(f'Logged in as {self.user.name} (ID: {self.user.id})')
        logging.info('------')
        logging.info(f'API URL: {self.api_base_url}')
        logging.info('API Key configured: Yes' if self.api_key else 'No')
        logging.info('Bot is ready to accept commands!')

def main():
    # Set Discord token from environment variable
    token = os.environ.get('DISCORD_BOT_TOKEN')
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN not set in environment")

    bot = MonitorBot()
    bot.run(token)

if __name__ == "__main__":
    main()