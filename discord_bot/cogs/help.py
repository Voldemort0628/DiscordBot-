import discord
from discord.ext import commands
import logging
from collections import defaultdict
import time

logger = logging.getLogger('HelpCommand')

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._processing = set()
        self._last_use = defaultdict(float)
        self._cooldown = 3.0  # seconds

    @commands.command(name='help')
    async def help_command(self, ctx, *, command_name: str = None):
        """Show help for commands"""
        msg_id = ctx.message.id
        logger.info(f"Help command received - MID: {msg_id}, UID: {ctx.author.id}")

        # Prevent duplicate processing
        if msg_id in self._processing:
            logger.warning(f"Already processing help for {msg_id}")
            return

        # Check cooldown
        current_time = time.time()
        if current_time - self._last_use[ctx.author.id] < self._cooldown:
            logger.debug(f"Help cooldown for user {ctx.author.id}")
            return

        try:
            self._processing.add(msg_id)
            self._last_use[ctx.author.id] = current_time

            # Create help embed
            embed = discord.Embed(
                title="Monitor Bot Commands" if not command_name else f"Command: !{command_name}",
                color=discord.Color.blue()
            )

            if command_name:
                cmd = self.bot.get_command(command_name)
                if not cmd:
                    logger.info(f"Command not found: {command_name}")
                    await ctx.send(f"Command `{command_name}` not found.")
                    return

                embed.description = cmd.help or "No description available"
                if cmd.aliases:
                    embed.add_field(
                        name="Aliases",
                        value=", ".join(f"`!{a}`" for a in cmd.aliases),
                        inline=False
                    )
            else:
                commands_list = []
                for cmd in self.bot.commands:
                    if not cmd.hidden and cmd.cog_name != "HelpCog":
                        commands_list.append(f"`!{cmd.name}` - {cmd.help or 'No description'}")

                embed.description = "\n".join(commands_list)
                embed.set_footer(text="Type !help <command> for more info about a specific command.")

            logger.info(f"Sending help message for {msg_id}")
            await ctx.send(embed=embed)
            logger.info(f"Help message sent for {msg_id}")

        except Exception as e:
            logger.error(f"Error in help command for {msg_id}: {e}")
            await ctx.send("❌ Error displaying help.")
        finally:
            self._processing.discard(msg_id)
            logger.debug(f"Finished processing help for {msg_id}")

async def setup(bot):
    await bot.add_cog(HelpCog(bot))
    logger.info("Help cog loaded")