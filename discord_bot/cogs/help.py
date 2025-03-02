import discord
from discord.ext import commands
import logging

logger = logging.getLogger('HelpCommand')

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='help')
    async def help_command(self, ctx, *, command_name: str = None):
        """Show help for commands"""
        try:
            embed = discord.Embed(
                title="Monitor Bot Commands" if not command_name else f"Command: !{command_name}",
                color=discord.Color.blue()
            )

            if command_name:
                cmd = self.bot.get_command(command_name)
                if not cmd:
                    return await ctx.send(f"Command `{command_name}` not found.")

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

            await ctx.send(embed=embed)
            logger.info(f"Sent help message to {ctx.author.id} in {ctx.channel.id}")

        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await ctx.send("❌ Error displaying help.")

async def setup(bot):
    await bot.add_cog(HelpCog(bot))
    logger.info("Help cog loaded")