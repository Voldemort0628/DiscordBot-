import discord
from discord.ext import commands
import logging
import aiohttp
from typing import Optional
import secrets
import sys
import os

# Add the parent directory to sys.path to allow importing from database.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import verify_discord_user

class MonitorCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logging.info("MonitorCommands cog initialized")

    @commands.command(name='verify')
    async def verify_user(self, ctx):
        """Verify yourself to use the monitor"""
        try:
            logging.info(f"Verify command received from user {ctx.author.id}")

            # Call the database function directly
            result = verify_discord_user(
                discord_user_id=str(ctx.author.id),
                discord_username=ctx.author.name
            )

            if result['success']:
                embed = discord.Embed(
                    title="✅ Verification Successful",
                    description="Your Discord account has been verified and linked to the monitor.",
                    color=discord.Color.green()
                )
                embed.add_field(name="Username", value=result['username'])
                await ctx.send(embed=embed)
            else:
                error_msg = result['message']
                logging.error(f"Verification failed: {error_msg}")
                await ctx.send(f"❌ Error during verification: {error_msg}")
        except Exception as e:
            logging.error(f"Error verifying user: {e}")
            await ctx.send("❌ Error during verification. Please try again later.")

async def setup(bot):
    await bot.add_cog(MonitorCommands(bot))