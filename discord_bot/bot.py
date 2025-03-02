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
        # Configure proper intents with all required permissions
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True  # Enable DM messages

        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=commands.DefaultHelpCommand(
                no_category='Monitor Commands'
            )
        )

        # API configuration
        repl_slug = os.environ.get('REPL_SLUG', '')
        repl_owner = os.environ.get('REPL_OWNER', '')

        # Log the Replit environment details
        logging.info(f"REPL_SLUG: {repl_slug}")
        logging.info(f"REPL_OWNER: {repl_owner}")

        if repl_slug and repl_owner:
            self.api_base_url = f'https://{repl_slug}.{repl_owner}.repl.dev/api'
            logging.info(f"API URL: {self.api_base_url}")
        else:
            self.api_base_url = 'http://localhost:5000/api'
            logging.info("Using local development API URL")

    async def setup_hook(self):
        """A coroutine to be called to setup the bot, by default does nothing.
        This is the method called by :meth:`.login` to setup the bot when it starts.
        """
        try:
            # Load the monitor commands cog
            await self.load_extension('cogs.monitor_commands')
            logging.info("Successfully loaded monitor commands extension")
        except Exception as e:
            logging.error(f"Failed to load monitor commands extension: {e}")
            raise  # Re-raise the exception to ensure the bot doesn't start with missing commands

    async def on_ready(self):
        """Called when the bot is ready and has a connection to Discord."""
        logging.info(f'Logged in as {self.user.name} (ID: {self.user.id})')
        logging.info('------')
        logging.info(f'API URL: {self.api_base_url}')
        logging.info('Bot is ready to accept commands!')

        # Log all available commands
        for command in self.commands:
            logging.info(f'Command loaded: {command.name}')

    async def on_command_error(self, ctx, error):
        """Global error handler for command errors."""
        if isinstance(error, commands.errors.CommandNotFound):
            await ctx.send("Command not found. Use !help to see available commands.")
        elif isinstance(error, commands.errors.MissingPermissions):
            await ctx.send("You don't have permission to use this command.")
        elif isinstance(error, commands.errors.NoPrivateMessage):
            await ctx.send("This command cannot be used in private messages.")
        else:
            logging.error(f"Command error: {error}")
            await ctx.send(f"An error occurred while processing the command: {str(error)}")

def main():
    # Verify required environment variables
    token = os.environ.get('DISCORD_BOT_TOKEN')
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN not set in environment")

    # Create and run the bot
    bot = MonitorBot()
    bot.run(token, log_handler=None)  # Disable discord.py's default logging

if __name__ == "__main__":
    main()