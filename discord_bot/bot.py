import os
import discord
from discord.ext import commands
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('discord_bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('DiscordBot')

class MonitorBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        # Use the default help command
        super().__init__(
            command_prefix='!',
            intents=intents
        )

    async def setup_hook(self):
        """Initial setup"""
        try:
            # Only load monitor commands, use default help
            await self.load_extension('cogs.monitor_commands')
            logger.info("Monitor commands loaded")
        except Exception as e:
            logger.error(f"Error loading extension: {e}")
            raise

def main():
    token = os.environ.get('DISCORD_BOT_TOKEN')
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN not set")

    bot = MonitorBot()
    bot.run(token)

if __name__ == "__main__":
    main()