import os
import sys
import discord
from discord.ext import commands
import logging
import psutil
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('discord_bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('MonitorBot')

def find_discord_bot_processes():
    """Find running Discord bot processes"""
    bot_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'python' in proc.info['name'] and 'discord_bot/bot.py' in cmdline:
                bot_processes.append(proc.info['pid'])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return bot_processes

def kill_existing_bots():
    """Kill any existing bot processes"""
    current_pid = os.getpid()
    for pid in find_discord_bot_processes():
        if pid != current_pid:
            try:
                process = psutil.Process(pid)
                process.terminate()
                try:
                    process.wait(timeout=3)
                except psutil.TimeoutExpired:
                    process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    time.sleep(1)  # Give processes time to terminate

class MonitorBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.guild_messages = True
        intents.guild_reactions = True
        intents.members = True  # Need this for user management

        super().__init__(
            command_prefix='!',
            intents=intents,
            description="Monitor Bot - Track product restocks and updates"
        )

    async def setup_hook(self):
        await self.load_extension('cogs.monitor_commands')

    async def on_command(self, ctx):
        """Log when a command is received"""
        logger.info(f"Command received - {ctx.command.name} from {ctx.author}")

    async def on_command_completion(self, ctx):
        """Log when a command completes successfully"""
        logger.info(f"Command completed - {ctx.command.name} from {ctx.author}")

    async def on_command_error(self, ctx, error):
        """Log command errors"""
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ I don't have the required permissions to perform this action.")
        elif isinstance(error, discord.Forbidden):
            await ctx.send("❌ I don't have permission to send messages in this channel.")
        else:
            logger.error(f"Command error - {ctx.command.name if ctx.command else 'Unknown'} from {ctx.author}: {str(error)}")
            await ctx.send("❌ An error occurred while processing your command.")

def main():
    # Ensure only one instance runs
    kill_existing_bots()
    other_instances = find_discord_bot_processes()
    if len(other_instances) > 1:  # More than just our process
        logger.error("Failed to kill all bot instances")
        sys.exit(1)

    token = os.environ.get('DISCORD_BOT_TOKEN')
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN not set")

    bot = MonitorBot()
    logger.info(f"Starting single bot instance (PID: {os.getpid()})")
    bot.run(token)

if __name__ == "__main__":
    main()