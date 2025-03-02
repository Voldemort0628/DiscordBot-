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
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )

        self._processed_messages = set()
        self.api_base_url = (
            f'https://{os.environ.get("REPL_SLUG")}.{os.environ.get("REPL_OWNER")}.repl.dev/api'
            if os.environ.get('REPL_SLUG') and os.environ.get('REPL_OWNER') else
            'http://localhost:5000/api'
        )
        self.api_key = os.environ.get('MONITOR_API_KEY')

    async def on_message(self, message):
        """Single entry point for message processing"""
        if message.author.bot:
            return

        msg_id = message.id
        if msg_id in self._processed_messages:
            logger.warning(f"Skipping duplicate message {msg_id}")
            return

        self._processed_messages.add(msg_id)
        try:
            await self.process_commands(message)
        except Exception as e:
            logger.error(f"Error processing message {msg_id}: {e}")
        finally:
            if len(self._processed_messages) > 1000:
                self._processed_messages.clear()

    async def setup_hook(self):
        """Load only necessary cogs"""
        try:
            logger.info("=== Bot Initialization ===")

            # Remove any existing help command
            if self.help_command:
                self.remove_command('help')
                logger.info("Removed default help command")

            # Load help cog first
            await self.load_extension('cogs.help')
            logger.info("Help cog loaded")

            # Load monitor commands
            await self.load_extension('cogs.monitor_commands')
            logger.info("Monitor commands loaded")

            logger.info("=== Registered Commands ===")
            for cmd in self.commands:
                logger.info(f"Command: {cmd.name} in cog: {cmd.cog_name if cmd.cog else 'No Cog'}")
            logger.info("========================")

        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            raise

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