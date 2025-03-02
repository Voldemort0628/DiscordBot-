import discord
from discord.ext import commands
import logging
import psycopg2
import os
import sys
import psutil
import subprocess
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('discord_bot.log'),
        logging.StreamHandler()
    ]
)

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1345624968070824099/41_PR3u7Q9zTTnClsoiYLuDGQ7vMmXwfALNMLGlHDGVo5OU7dmi13D8fvM-_-uLWmFDz"

def is_monitor_running(user_id):
    """Check if a specific user's monitor is running"""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'environ']):
            try:
                env = proc.environ()
                # Check both command line args and environment variables
                is_monitor = ('python' in proc.info['name'] and 
                            'main.py' in ' '.join(proc.info['cmdline'] or []))

                has_user_id = (f"MONITOR_USER_ID={user_id}" in ' '.join(proc.info['cmdline'] or []) or
                              env.get('MONITOR_USER_ID') == str(user_id))

                if is_monitor and has_user_id:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False

class MonitorCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logging.info("MonitorCommands cog initialized")

    async def safe_send(self, ctx, content=None, embed=None):
        """Safely send a message, falling back to DM if channel send fails"""
        try:
            if content:
                await ctx.send(content)
            if embed:
                await ctx.send(embed=embed)
        except discord.Forbidden:
            try:
                if content:
                    await ctx.author.send(content)
                if embed:
                    await ctx.author.send(embed=embed)
            except discord.Forbidden:
                logging.error(f"Could not send message to user {ctx.author.id}")

    @commands.command(name='verify')
    async def verify_user(self, ctx):
        """Verify yourself to use the monitor"""
        try:
            logging.info(f"Verify command received from user {ctx.author.id}")

            try:
                # Try to DM the user first to check if we can
                await ctx.author.send("Processing your verification...")
            except discord.Forbidden:
                await self.safe_send(ctx, "I couldn't DM you. Please enable DMs from server members and try again.")
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
                    await self.safe_send(ctx, "✅ Your account is already verified!")
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

                await self.safe_send(ctx, "✅ Verification successful! Check your DMs for details.")

            except Exception as e:
                conn.rollback()
                logging.error(f"Database error during verification: {str(e)}")
                await self.safe_send(ctx, "❌ Error during verification. Please try again later.")
            finally:
                cur.close()
                conn.close()

        except Exception as e:
            logging.error(f"Error verifying user: {e}")
            await self.safe_send(ctx, "❌ Error during verification. Please try again later.")


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
                await self.safe_send(ctx, "❌ You need to verify your account first. Use `!verify` to get started.")
                return

            user_id, username = user
            monitor_running = is_monitor_running(user_id)

            embed = discord.Embed(
                title="Monitor Status",
                color=discord.Color.green() if monitor_running else discord.Color.red()
            )
            embed.add_field(name="Status", value="✅ Running" if monitor_running else "❌ Stopped")
            embed.add_field(name="Username", value=username)
            await self.safe_send(ctx, embed=embed)

        except Exception as e:
            logging.error(f"Error checking status: {e}")
            await self.safe_send(ctx, "❌ Error checking status. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()

    @commands.command(name='start')
    async def start_monitor(self, ctx):
        """Start your monitor"""
        try:
            conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
            cur = conn.cursor()

            # Get user_id and webhook URL
            cur.execute(
                'SELECT id, discord_webhook_url FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                await self.safe_send(ctx, "❌ You need to verify your account first. Use `!verify` to get started.")
                return

            user_id, custom_webhook = result

            # Check if user has any stores configured
            cur.execute(
                'SELECT COUNT(*) FROM store WHERE user_id = %s AND enabled = true;',
                (user_id,)
            )
            store_count = cur.fetchone()[0]

            if store_count == 0:
                await self.safe_send(ctx, "❌ You need to add some stores first! Use `!preset_stores` to add our curated list of stores, or `!add_store` to add your own.")
                return

            # Check if monitor is already running
            if is_monitor_running(user_id):
                await self.safe_send(ctx, "Monitor is already running!")
                return

            # Get absolute path to main.py
            main_script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'main.py')

            # Use custom webhook if set, otherwise use preset webhook
            webhook_url = custom_webhook if custom_webhook else DISCORD_WEBHOOK_URL

            # Start monitor process with proper environment variables
            process_env = os.environ.copy()
            process_env['DISCORD_WEBHOOK_URL'] = webhook_url
            process_env['MONITOR_USER_ID'] = str(user_id)

            # Enable user in database
            cur.execute(
                'UPDATE "user" SET enabled = true WHERE id = %s;',
                (user_id,)
            )

            # Start the monitor process
            cmd = ['python', main_script]
            if sys.platform != 'win32':  # Add command line arg on non-Windows platforms
                cmd.append(f"MONITOR_USER_ID={user_id}")

            subprocess.Popen(
                cmd,
                env=process_env,
                start_new_session=True
            )

            conn.commit()
            logging.info(f"Starting monitor for user {user_id} with webhook URL: {webhook_url}")
            webhook_type = "custom" if custom_webhook else "default"

            status_msg = [
                "✅ Monitor started successfully!",
                f"Using {webhook_type} webhook for notifications.",
                f"Monitoring {store_count} store{'s' if store_count != 1 else ''}.",
                "Use !status to check monitor status.",
            ]
            await self.safe_send(ctx, "\n".join(status_msg))

        except Exception as e:
            logging.error(f"Error starting monitor: {e}")
            await self.safe_send(ctx, "❌ Error starting monitor. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()

    @commands.command(name='stop')
    async def stop_monitor(self, ctx):
        """Stop your monitor"""
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
                await self.safe_send(ctx, "❌ You need to verify your account first. Use `!verify` to get started.")
                return

            user_id = result[0]
            stopped = False

            # Stop the monitor process
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    if ('python' in proc.info['name'] and 
                        'main.py' in cmdline and 
                        f"MONITOR_USER_ID={user_id}" in cmdline):
                        process = psutil.Process(proc.info['pid'])
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                            stopped = True
                        except psutil.TimeoutExpired:
                            process.kill()
                            stopped = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # Disable user in database
            cur.execute(
                'UPDATE "user" SET enabled = false WHERE id = %s;',
                (user_id,)
            )
            conn.commit()

            if stopped:
                logging.info(f"Stopped monitor for user {user_id}")
                await self.safe_send(ctx, "✅ Monitor stopped successfully!")
            else:
                await self.safe_send(ctx, "Monitor was not running.")

        except Exception as e:
            logging.error(f"Error stopping monitor: {e}")
            await self.safe_send(ctx, "❌ Error stopping monitor. Please try again later.")
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
                await self.safe_send(ctx, "No keywords found. Add some using `!add_keyword <word>`")
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
            await self.safe_send(ctx, embed=embed)

        except Exception as e:
            logging.error(f"Error listing keywords: {e}")
            await self.safe_send(ctx, "❌ Error listing keywords. Please try again later.")
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
                await self.safe_send(ctx, "❌ You need to verify your account first. Use `!verify` to get started.")
                return

            user_id = result[0]

            # Check if keyword already exists
            cur.execute(
                'SELECT 1 FROM keyword WHERE user_id = %s AND word = %s;',
                (user_id, keyword)
            )
            if cur.fetchone():
                await self.safe_send(ctx, "⚠️ This keyword already exists in your list.")
                return

            # Add the keyword
            cur.execute(
                'INSERT INTO keyword (user_id, word, enabled) VALUES (%s, %s, true);',
                (user_id, keyword)
            )
            conn.commit()
            await self.safe_send(ctx, f"✅ Added keyword: `{keyword}`")

        except Exception as e:
            logging.error(f"Error adding keyword: {e}")
            await self.safe_send(ctx, "❌ Error adding keyword. Please try again later.")
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
                await self.safe_send(ctx, "❌ You need to verify your account first. Use `!verify` to get started.")
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
                await self.safe_send(ctx, f"✅ Removed keyword: `{keyword}`")
            else:
                await self.safe_send(ctx, "⚠️ Keyword not found in your list.")

        except Exception as e:
            logging.error(f"Error removing keyword: {e}")
            await self.safe_send(ctx, "❌ Error removing keyword. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()

    @commands.command(name='preset_stores')
    async def preset_stores(self, ctx):
        """Show and enable preset stores to monitor"""
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
                await self.safe_send(ctx, "❌ You need to verify your account first. Use `!verify` to get started.")
                return

            user_id = result[0]

            # List of preset stores
            preset_stores = [
                "https://www.deadstock.ca",
                "https://www.bowsandarrowsberkeley.com",
                "https://www.featuresneakerboutique.com",
                "https://www.blendsus.com",
                "https://www.apbstore.com",
                "https://www.bbbranded.com",
                "https://www.a-ma-maniere.com",
                "https://www.socialstatuspgh.com",
                "https://www.wishatl.com",
                "https://www.xhibition.co"
            ]

            # Add each preset store if it doesn't exist
            stores_added = 0
            for store_url in preset_stores:
                cur.execute(
                    'SELECT 1 FROM store WHERE user_id = %s AND url = %s;',
                    (user_id, store_url)
                )
                if not cur.fetchone():
                    cur.execute(
                        'INSERT INTO store (user_id, url, enabled) VALUES (%s, %s, true);',
                        (user_id, store_url)
                    )
                    stores_added += 1

            conn.commit()

            embed = discord.Embed(
                title="Preset Stores Added",
                description=f"Added {stores_added} new preset stores to your monitor.",
                color=discord.Color.green()
            )
            embed.add_field(name="Total Preset Stores", value=str(len(preset_stores)))
            await self.safe_send(ctx, embed=embed)

        except Exception as e:
            logging.error(f"Error adding preset stores: {e}")
            await self.safe_send(ctx, "❌ Error adding preset stores. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()

    @commands.command(name='add_store')
    async def add_store(self, ctx, *, store_url: str):
        """Add a store URL to monitor"""
        try:
            # Basic URL validation
            if not store_url.startswith(('http://', 'https://')):
                store_url = 'https://' + store_url

            conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
            cur = conn.cursor()

            # Get user_id first
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                await self.safe_send(ctx, "❌ You need to verify your account first. Use `!verify` to get started.")
                return

            user_id = result[0]

            # Check if store already exists
            cur.execute(
                'SELECT 1 FROM store WHERE user_id = %s AND url = %s;',
                (user_id, store_url)
            )
            if cur.fetchone():
                await self.safe_send(ctx, "⚠️ This store is already in your list.")
                return

            # Add the store
            cur.execute(
                'INSERT INTO store (user_id, url, enabled) VALUES (%s, %s, true);',
                (user_id, store_url)
            )
            conn.commit()
            await self.safe_send(ctx, f"✅ Added store: `{store_url}`")

        except Exception as e:
            logging.error(f"Error adding store: {e}")
            await self.safe_send(ctx, "❌ Error adding store. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()

    @commands.command(name='list_stores')
    async def list_stores(self, ctx):
        """List all your active stores"""
        try:
            conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
            cur = conn.cursor()

            # Get user's stores
            cur.execute(
                '''SELECT s.url, s.enabled 
                FROM store s 
                JOIN "user" u ON s.user_id = u.id 
                WHERE u.discord_user_id = %s;''',
                (str(ctx.author.id),)
            )
            stores = cur.fetchall()

            if not stores:
                await self.safe_send(ctx, "No stores found. Add some using `!add_store <url>` or `!preset_stores`")
                return

            embed = discord.Embed(
                title="Your Monitored Stores",
                color=discord.Color.blue()
            )

            # Group stores by status
            enabled_stores = []
            disabled_stores = []
            for url, enabled in stores:
                if enabled:
                    enabled_stores.append(url)
                else:
                    disabled_stores.append(url)

            if enabled_stores:
                embed.add_field(
                    name="✅ Active Stores",
                    value="\n".join(enabled_stores),
                    inline=False
                )
            if disabled_stores:
                embed.add_field(
                    name="❌ Disabled Stores",
                    value="\n".join(disabled_stores),
                    inline=False
                )

            embed.set_footer(text="Use !add_store to add more stores or !preset_stores to add preset stores")
            await self.safe_send(ctx, embed=embed)

        except Exception as e:
            logging.error(f"Error listing stores: {e}")
            await self.safe_send(ctx, "❌ Error listing stores. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()


    @commands.command(name='set_webhook')
    async def set_webhook(self, ctx):
        """Set your custom Discord webhook URL (via DM only)"""
        try:
            # This command should only work in DMs
            if not isinstance(ctx.channel, discord.DMChannel):
                await ctx.author.send("For security, please use this command in a DM with me!")
                return

            await ctx.send("Please send your Discord webhook URL. It should start with 'https://discord.com/api/webhooks/'")

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            try:
                msg = await self.bot.wait_for('message', timeout=60.0, check=check)
                webhook_url = msg.content.strip()

                if not webhook_url.startswith('https://discord.com/api/webhooks/'):
                    await ctx.send("❌ Invalid webhook URL. It should start with 'https://discord.com/api/webhooks/'")
                    return

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

                # Update the webhook URL
                cur.execute(
                    'UPDATE "user" SET discord_webhook_url = %s WHERE id = %s;',
                    (webhook_url, user_id)
                )
                conn.commit()

                await ctx.send("✅ Your webhook URL has been set! Monitor notifications will now be sent to your custom webhook.")

            except asyncio.TimeoutError:
                await ctx.send("Webhook setup timed out. Please try again.")

        except Exception as e:
            logging.error(f"Error setting webhook: {e}")
            await ctx.send("❌ Error setting webhook. Please try again later.")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()

async def setup(bot):
    await bot.add_cog(MonitorCommands(bot))