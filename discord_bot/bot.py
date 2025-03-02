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

class CustomHelpCommand(commands.HelpCommand):
    async def send_bot_help(self, mapping):
        """Sends the bot help message in a single embed"""
        embed = discord.Embed(
            title="Monitor Bot Commands",
            description="Here are all available commands:",
            color=discord.Color.blue()
        )

        # Create a single field for all commands
        all_commands = []
        for cog, cmds in mapping.items():
            filtered = await self.filter_commands(cmds, sort=True)
            for cmd in filtered:
                all_commands.append(f"`!{cmd.name}` - {cmd.help or 'No description available'}")

        if all_commands:
            embed.add_field(
                name="Available Commands",
                value="\n".join(all_commands),
                inline=False
            )

        embed.set_footer(text="Type !help <command> for more info about a command.")
        channel = self.get_destination()
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            # If embed is too large, split into smaller sections
            await channel.send("⚠️ Error displaying help. Please use !help <command> for specific command help.")

    async def send_command_help(self, command):
        """Sends help for a specific command in a single embed"""
        embed = discord.Embed(
            title=f"Command: !{command.name}",
            description=command.help or "No description available",
            color=discord.Color.blue()
        )

        # Combine all command info into the description
        details = []
        if command.aliases:
            details.append(f"**Aliases:** {', '.join(f'`!{alias}`' for alias in command.aliases)}")
        if command.usage:
            details.append(f"**Usage:** `!{command.name} {command.usage}`")

        if details:
            embed.description += "\n\n" + "\n".join(details)

        channel = self.get_destination()
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            await channel.send(f"⚠️ Error displaying help for `{command.name}`.")

    # Override group help to prevent multiple messages
    send_group_help = send_command_help
    send_cog_help = send_bot_help

class MonitorBot(commands.Bot):
    def __init__(self):
        # Configure proper intents with all required permissions
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.guild_messages = True

        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=CustomHelpCommand()
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

        self.api_key = os.environ['MONITOR_API_KEY']

    async def setup_hook(self):
        try:
            await self.load_extension('cogs.monitor_commands')
            logging.info("Successfully loaded monitor commands extension")
        except Exception as e:
            logging.error(f"Failed to load monitor commands extension: {e}")

    async def on_ready(self):
        logging.info(f'Logged in as {self.user.name} (ID: {self.user.id})')
        logging.info('------')
        logging.info(f'API URL: {self.api_base_url}')
        logging.info('API Key configured: Yes' if self.api_key else 'API Key missing')
        logging.info('Bot is ready to accept commands!')

        # Log loaded commands
        for command in self.commands:
            logging.info(f'Command loaded: {command.name}')

    async def on_command(self, ctx):
        logging.info(f"Command '{ctx.command.name}' was triggered by {ctx.author} (ID: {ctx.author.id})")

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.errors.CommandNotFound):
            await ctx.send(f"Command not found. Use !help to see available commands.")
        else:
            logging.error(f"Command error: {error}")
            await ctx.send(f"An error occurred while processing the command: {str(error)}")

def main():
    # Set Discord token from environment variable
    token = os.environ.get('DISCORD_BOT_TOKEN')
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN not set in environment")

    bot = MonitorBot()
    bot.run(token)

if __name__ == "__main__":
    main()