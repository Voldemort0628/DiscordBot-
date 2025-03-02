import os
import discord
from discord.ext import commands
import logging

# Configure logging
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
        # Basic intents - only what we need
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None  # Disable default help
        )

        # Store processed message IDs to prevent duplicate handling
        self._processed_messages = set()

        # API configuration
        repl_slug = os.environ.get('REPL_SLUG', '')
        repl_owner = os.environ.get('REPL_OWNER', '')
        self.api_base_url = (
            f'https://{repl_slug}.{repl_owner}.repl.dev/api'
            if repl_slug and repl_owner else
            'http://localhost:5000/api'
        )
        self.api_key = os.environ.get('MONITOR_API_KEY')

    async def process_commands(self, message):
        """Override to prevent duplicate command processing"""
        if message.id in self._processed_messages:
            return

        self._processed_messages.add(message.id)
        try:
            await super().process_commands(message)
        finally:
            # Clean up old message IDs periodically
            if len(self._processed_messages) > 1000:
                self._processed_messages.clear()

    async def setup_hook(self):
        """Load extensions during setup"""
        extensions = [
            'cogs.help',
            'cogs.monitor_commands'
        ]

        for ext in extensions:
            try:
                await self.load_extension(ext)
                logger.info(f"Loaded extension: {ext}")
            except Exception as e:
                logger.error(f"Failed to load extension {ext}: {e}")

    async def on_ready(self):
        """Called when bot is ready"""
        logger.info(f"Logged in as {self.user.name} (ID: {self.user.id})")
        logger.info(f"API URL: {self.api_base_url}")
        logger.info("Bot is ready!")

def main():
    """Start the bot"""
    token = os.environ.get('DISCORD_BOT_TOKEN')
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN not set")

    bot = MonitorBot()
    bot.run(token)

if __name__ == "__main__":
    main()