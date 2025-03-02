import discord
from discord.ext import commands
import logging
import aiohttp
from typing import Optional

class MonitorCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='status')
    async def status(self, ctx):
        """Check the status of your monitor"""
        try:
            logging.info(f"Status command received from user {ctx.author.id}")
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.bot.api_base_url}/status",
                    headers={'X-API-Key': self.bot.api_key},
                    params={
                        'discord_user_id': str(ctx.author.id)
                    }
                ) as resp:
                    logging.info(f"Status API response: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        embed = discord.Embed(
                            title="Monitor Status",
                            color=discord.Color.green() if data['running'] else discord.Color.red()
                        )
                        embed.add_field(name="Status", value="✅ Running" if data['running'] else "❌ Stopped")
                        embed.add_field(name="User", value=data['username'])
                        await ctx.send(embed=embed)
                    elif resp.status == 404:
                        await ctx.send("❌ Error: Your Discord account is not registered with the monitor. Use `!link` to link your account.")
                    else:
                        error_data = await resp.json()
                        await ctx.send(f"❌ Error checking monitor status: {error_data.get('error', 'Unknown error')}")
        except Exception as e:
            logging.error(f"Error checking status: {e}")
            await ctx.send("❌ Error checking monitor status. Please try again later.")

    @commands.command(name='start')
    async def start_monitor(self, ctx):
        """Start your monitor"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.bot.api_base_url}/start",
                    headers={'X-API-Key': self.bot.api_key},
                    json={'user_id': ctx.author.id}
                ) as resp:
                    if resp.status == 200:
                        await ctx.send("Monitor started successfully!")
                    else:
                        await ctx.send("Failed to start monitor")
        except Exception as e:
            logging.error(f"Error starting monitor: {e}")
            await ctx.send("Error starting monitor")

    @commands.command(name='stop')
    async def stop_monitor(self, ctx):
        """Stop your monitor"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.bot.api_base_url}/stop",
                    headers={'X-API-Key': self.bot.api_key},
                    json={'user_id': ctx.author.id}
                ) as resp:
                    if resp.status == 200:
                        await ctx.send("Monitor stopped successfully!")
                    else:
                        await ctx.send("Failed to stop monitor")
        except Exception as e:
            logging.error(f"Error stopping monitor: {e}")
            await ctx.send("Error stopping monitor")

    @commands.command(name='keywords')
    async def list_keywords(self, ctx):
        """List your current keywords"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.bot.api_base_url}/keywords",
                    headers={'X-API-Key': self.bot.api_key},
                    params={'user_id': ctx.author.id}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        embed = discord.Embed(
                            title="Monitor Keywords",
                            color=discord.Color.blue()
                        )
                        for keyword in data['keywords']:
                            embed.add_field(
                                name=keyword['word'],
                                value="✅ Enabled" if keyword['enabled'] else "❌ Disabled",
                                inline=True
                            )
                        await ctx.send(embed=embed)
                    else:
                        await ctx.send("Failed to fetch keywords")
        except Exception as e:
            logging.error(f"Error listing keywords: {e}")
            await ctx.send("Error fetching keywords")

    @commands.command(name='add_keyword')
    async def add_keyword(self, ctx, *, keyword: str):
        """Add a new keyword to monitor"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.bot.api_base_url}/keywords",
                    headers={'X-API-Key': self.bot.api_key},
                    json={'user_id': ctx.author.id, 'word': keyword}
                ) as resp:
                    if resp.status == 200:
                        await ctx.send(f"Added keyword: {keyword}")
                    else:
                        await ctx.send("Failed to add keyword")
        except Exception as e:
            logging.error(f"Error adding keyword: {e}")
            await ctx.send("Error adding keyword")

    @commands.command(name='remove_keyword')
    async def remove_keyword(self, ctx, *, keyword: str):
        """Remove a keyword from your monitor"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    f"{self.bot.api_base_url}/keywords",
                    headers={'X-API-Key': self.bot.api_key},
                    json={'user_id': ctx.author.id, 'word': keyword}
                ) as resp:
                    if resp.status == 200:
                        await ctx.send(f"Removed keyword: {keyword}")
                    else:
                        await ctx.send("Failed to remove keyword")
        except Exception as e:
            logging.error(f"Error removing keyword: {e}")
            await ctx.send("Error removing keyword")

    @commands.command(name='link')
    async def link_account(self, ctx):
        """Link your Discord account with your monitor account"""
        try:
            # Get base URL from API URL but remove /api suffix
            base_url = self.bot.api_base_url.replace('/api', '')

            embed = discord.Embed(
                title="Link Your Discord Account",
                description=(
                    "Click the link below to connect your Discord account with the monitor:\n"
                    f"🔗 [Login with Discord]({base_url}/discord-login)"
                ),
                color=discord.Color.blue()
            )
            embed.set_footer(text="This link will securely connect your Discord account")
            await ctx.send(embed=embed)
        except Exception as e:
            logging.error(f"Error providing login link: {e}")
            await ctx.send("❌ Error generating login link. Please try again later.")


async def setup(bot):
    await bot.add_cog(MonitorCommands(bot))