import discord
from discord.ext import commands
import logging
import psycopg2
import os
import sys
import psutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('discord_bot.log'),
        logging.StreamHandler()
    ]
)

def is_monitor_running(user_id):
    """Check if a specific user's monitor is running"""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if ('python' in proc.info['name'] and 
                'main.py' in cmdline and 
                f"MONITOR_USER_ID={user_id}" in cmdline):
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False

class MonitorCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logging.info("MonitorCommands cog initialized")

    @commands.command(name='verify')
    async def verify_user(self, ctx):
        """Verify yourself to use the monitor"""
        try:
            logging.info(f"Verify command received from user {ctx.author.id}")

            try:
                # Try to DM the user first to check if we can
                await ctx.author.send("Processing your verification...")
            except discord.Forbidden:
                await ctx.send("I couldn't DM you. Please enable DMs from server members and try again.")
                return

            # Connect to database
            conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
            cur = conn.cursor()

            try:
                # First check if user exists
                cur.execute(
                    'SELECT username FROM "user" WHERE discord_user_id = %s;',
                    (str(ctx.author.id),)
                )

                result = cur.fetchone()
                if result:
                    logging.info(f"Found existing user for Discord ID {ctx.author.id}")
                    embed = discord.Embed(
                        title="✅ Already Verified",
                        description="Your Discord account is already verified and linked to the monitor.",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Username", value=result[0])
                    await ctx.author.send(embed=embed)
                    try:
                        await ctx.send("✅ Your account is already verified!")
                    except discord.Forbidden:
                        pass
                    return

                # Create new user
                username = f"discord_{ctx.author.name}"

                # Insert new user
                cur.execute(
                    'INSERT INTO "user" (username, discord_user_id, enabled) VALUES (%s, %s, true) RETURNING id;',
                    (username, str(ctx.author.id))
                )

                user_id = cur.fetchone()[0]

                # Create monitor config
                cur.execute(
                    '''INSERT INTO monitor_config (
                        user_id, rate_limit, monitor_delay, max_products,
                        min_cycle_delay, success_delay_multiplier, batch_size, initial_product_limit
                    ) VALUES (%s, 1.0, 30, 250, 0.05, 0.25, 20, 150);''',
                    (user_id,)
                )

                conn.commit()
                logging.info(f"Successfully created user {username} with Discord ID {ctx.author.id}")

                embed = discord.Embed(
                    title="✅ Verification Successful",
                    description="Your Discord account has been verified and linked to the monitor.",
                    color=discord.Color.green()
                )
                embed.add_field(name="Username", value=username)
                await ctx.author.send(embed=embed)

                try:
                    await ctx.send("✅ Verification successful! Check your DMs for details.")
                except discord.Forbidden:
                    pass  # If we can't send to the channel, that's okay

            except Exception as e:
                conn.rollback()
                logging.error(f"Database error during verification: {str(e)}")
                await ctx.author.send("❌ Error during verification. Please try again later.")
            finally:
                cur.close()
                conn.close()

        except Exception as e:
            logging.error(f"Error verifying user: {e}")
            try:
                await ctx.author.send("❌ Error during verification. Please try again later.")
            except:
                await ctx.send("❌ Error during verification. Please enable DMs and try again.")

    @commands.command(name='status')
    async def check_status(self, ctx):
        """Check your monitor status"""
        try:
            conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
            cur = conn.cursor()

            # Get user information
            cur.execute(
                'SELECT id, username FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            user = cur.fetchone()

            if not user:
                await ctx.send("❌ You need to verify your account first. Use `!verify` to get started.")
                return

            user_id, username = user
            monitor_running = is_monitor_running(user_id)

            embed = discord.Embed(
                title="Monitor Status",
                color=discord.Color.green() if monitor_running else discord.Color.red()
            )
            embed.add_field(name="Status", value="✅ Running" if monitor_running else "❌ Stopped")
            embed.add_field(name="Username", value=username)
            await ctx.send(embed=embed)

        except Exception as e:
            logging.error(f"Error checking status: {e}")
            await ctx.send("❌ Error checking status. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()

    @commands.command(name='start')
    async def start_monitor(self, ctx):
        """Start your monitor"""
        try:
            conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
            cur = conn.cursor()

            # Update user enabled status
            cur.execute(
                'UPDATE "user" SET enabled = true WHERE discord_user_id = %s RETURNING id;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()

            if not result:
                await ctx.send("❌ You need to verify your account first. Use `!verify` to get started.")
                return

            conn.commit()
            await ctx.send("✅ Monitor started successfully!")

        except Exception as e:
            logging.error(f"Error starting monitor: {e}")
            await ctx.send("❌ Error starting monitor. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()

    @commands.command(name='stop')
    async def stop_monitor(self, ctx):
        """Stop your monitor"""
        try:
            conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
            cur = conn.cursor()

            # Update user enabled status
            cur.execute(
                'UPDATE "user" SET enabled = false WHERE discord_user_id = %s RETURNING id;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()

            if not result:
                await ctx.send("❌ You need to verify your account first. Use `!verify` to get started.")
                return

            conn.commit()
            await ctx.send("✅ Monitor stopped successfully!")

        except Exception as e:
            logging.error(f"Error stopping monitor: {e}")
            await ctx.send("❌ Error stopping monitor. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()

    @commands.command(name='keywords')
    async def list_keywords(self, ctx):
        """List your keywords"""
        try:
            conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
            cur = conn.cursor()

            # Get user's keywords
            cur.execute(
                '''SELECT k.word, k.enabled 
                FROM keyword k 
                JOIN "user" u ON k.user_id = u.id 
                WHERE u.discord_user_id = %s;''',
                (str(ctx.author.id),)
            )
            keywords = cur.fetchall()

            if not keywords:
                await ctx.send("No keywords found. Add some using `!add_keyword <word>`")
                return

            embed = discord.Embed(
                title="Your Keywords",
                color=discord.Color.blue()
            )
            for word, enabled in keywords:
                embed.add_field(
                    name=word,
                    value="✅ Enabled" if enabled else "❌ Disabled",
                    inline=True
                )
            await ctx.send(embed=embed)

        except Exception as e:
            logging.error(f"Error listing keywords: {e}")
            await ctx.send("❌ Error listing keywords. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()

    @commands.command(name='add_keyword')
    async def add_keyword(self, ctx, *, keyword: str):
        """Add a keyword to monitor"""
        try:
            conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
            cur = conn.cursor()

            # Get user_id first
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                await ctx.send("❌ You need to verify your account first. Use `!verify` to get started.")
                return

            user_id = result[0]

            # Check if keyword already exists
            cur.execute(
                'SELECT 1 FROM keyword WHERE user_id = %s AND word = %s;',
                (user_id, keyword)
            )
            if cur.fetchone():
                await ctx.send("⚠️ This keyword already exists in your list.")
                return

            # Add the keyword
            cur.execute(
                'INSERT INTO keyword (user_id, word, enabled) VALUES (%s, %s, true);',
                (user_id, keyword)
            )
            conn.commit()
            await ctx.send(f"✅ Added keyword: `{keyword}`")

        except Exception as e:
            logging.error(f"Error adding keyword: {e}")
            await ctx.send("❌ Error adding keyword. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()

    @commands.command(name='remove_keyword')
    async def remove_keyword(self, ctx, *, keyword: str):
        """Remove a keyword from your monitor"""
        try:
            conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
            cur = conn.cursor()

            # Get user_id first
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                await ctx.send("❌ You need to verify your account first. Use `!verify` to get started.")
                return

            user_id = result[0]

            # Remove the keyword
            cur.execute(
                'DELETE FROM keyword WHERE user_id = %s AND word = %s RETURNING word;',
                (user_id, keyword)
            )
            deleted = cur.fetchone()

            if deleted:
                conn.commit()
                await ctx.send(f"✅ Removed keyword: `{keyword}`")
            else:
                await ctx.send("⚠️ Keyword not found in your list.")

        except Exception as e:
            logging.error(f"Error removing keyword: {e}")
            await ctx.send("❌ Error removing keyword. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()

async def setup(bot):
    await bot.add_cog(MonitorCommands(bot))