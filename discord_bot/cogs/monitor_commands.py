import os
import json
import asyncio
import logging
import psutil
import sys
import psycopg2
import time
from discord.ext import commands
import discord
from datetime import datetime, timedelta
import subprocess
from werkzeug.security import generate_password_hash
import secrets

logger = logging.getLogger('MonitorBot')

class MonitorCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._command_cooldowns = {}

    async def _check_cooldown(self, ctx):
        """Check command cooldown"""
        now = time.time()
        key = f"{ctx.author.id}:{ctx.command.name}"
        if key in self._command_cooldowns:
            diff = now - self._command_cooldowns[key]
            if diff < 3.0:  # 3 second cooldown
                return False
        self._command_cooldowns[key] = now
        return True

    async def _handle_db_operation(self, operation):
        """Execute database operations with proper connection handling"""
        conn = None
        cur = None
        try:
            conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
            cur = conn.cursor()
            return await operation(conn, cur)
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            return None
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    def _is_monitor_running(self, user_id):
        """Check if monitor is running for user"""
        try:
            tracking_file = f"monitor_process_{user_id}.json"

            # First check tracking file
            if os.path.exists(tracking_file):
                try:
                    with open(tracking_file) as f:
                        data = json.load(f)
                        pid = data.get('pid')
                        child_pid = data.get('child_pid')

                        # Check both parent and child processes
                        for check_pid in [pid, child_pid]:
                            if check_pid:
                                try:
                                    process = psutil.Process(check_pid)
                                    if process.is_running():
                                        # More strict process verification
                                        cmdline = ' '.join(process.cmdline())
                                        env = process.environ()

                                        is_python = 'python' in process.name().lower()
                                        has_monitor_script = any(s in cmdline for s in ['start_monitor.py', 'main.py'])
                                        correct_user = str(user_id) == env.get('MONITOR_USER_ID')

                                        if is_python and has_monitor_script and correct_user:
                                            logger.info(f"Found running monitor process: PID {check_pid}")
                                            return True
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    continue

                    # If we get here, no valid process found
                    logger.info(f"No valid monitor process found in tracking file for user {user_id}")
                    os.remove(tracking_file)
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"Error reading tracking file: {e}")
                    if os.path.exists(tracking_file):
                        os.remove(tracking_file)

            # Double check running processes even if tracking file wasn't found
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'environ']):
                try:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    env = proc.info.get('environ', {})

                    is_python = 'python' in proc.info['name'].lower()
                    has_monitor_script = any(s in cmdline for s in ['start_monitor.py', 'main.py'])
                    correct_user = str(user_id) == env.get('MONITOR_USER_ID')

                    if is_python and has_monitor_script and correct_user:
                        logger.info(f"Found orphaned monitor process: PID {proc.info['pid']}")
                        # Create tracking file if it doesn't exist
                        if not os.path.exists(tracking_file):
                            with open(tracking_file, 'w') as f:
                                json.dump({
                                    'pid': proc.info['pid'],
                                    'start_time': datetime.now().isoformat(),
                                    'log_file': f"monitor_log_{user_id}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
                                }, f)
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.warning(f"Error checking process: {e}")
                    continue

            logger.info(f"No monitor process found for user {user_id}")
            return False
        except Exception as e:
            logger.error(f"Error checking monitor status: {e}", exc_info=True)
            return False

    async def _cleanup_old_monitor(self, user_id):
        """Cleanup any existing monitor process"""
        try:
            tracking_file = f"monitor_process_{user_id}.json"
            if os.path.exists(tracking_file):
                try:
                    with open(tracking_file) as f:
                        data = json.load(f)
                        processes_to_check = [data.get('pid'), data.get('child_pid')]

                        for pid in processes_to_check:
                            if pid:
                                try:
                                    process = psutil.Process(pid)
                                    if ('python' in process.name().lower() and
                                        str(user_id) == process.environ().get('MONITOR_USER_ID')):
                                        logger.info(f"Terminating monitor process: PID {pid}")
                                        process.terminate()
                                        try:
                                            process.wait(timeout=3)
                                        except psutil.TimeoutExpired:
                                            logger.warning(f"Process {pid} did not terminate, killing it")
                                            process.kill()
                                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                                    logger.warning(f"Error terminating process {pid}: {e}")
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"Error reading tracking file: {e}")

            # Clean up any stale tracking file
            if os.path.exists(tracking_file):
                try:
                    os.remove(tracking_file)
                    logger.info(f"Removed tracking file for user {user_id}")
                except OSError as e:
                    logger.error(f"Could not remove tracking file: {e}")

        except Exception as e:
            logger.error(f"Error in cleanup process: {e}", exc_info=True)

    @commands.command(name='verify', help="Verify yourself to use the monitor")
    async def verify_user(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        logger.info(f"Starting verification for user {ctx.author.name} (ID: {ctx.author.id})")

        async def db_verify(conn, cur):
            # Check if user already exists
            cur.execute('SELECT username FROM "user" WHERE discord_user_id = %s', (str(ctx.author.id),))
            if cur.fetchone():
                logger.info(f"User {ctx.author.name} already verified")
                return "✅ Your account is already verified!"

            username = f"discord_{ctx.author.name}"
            # Create user with random password
            password = secrets.token_urlsafe(32)
            password_hash = generate_password_hash(password)

            logger.info(f"Creating new user: {username}")

            cur.execute(
                'INSERT INTO "user" (username, discord_user_id, enabled, password_hash) VALUES (%s, %s, true, %s) RETURNING id',
                (username, str(ctx.author.id), password_hash)
            )
            user_id = cur.fetchone()[0]

            cur.execute(
                '''INSERT INTO monitor_config (
                    user_id, rate_limit, monitor_delay, max_products,
                    min_cycle_delay, success_delay_multiplier, batch_size, initial_product_limit
                ) VALUES (%s, 1.0, 30, 250, 0.05, 0.25, 20, 150)''',
                (user_id,)
            )
            conn.commit()
            logger.info(f"Successfully created user {username} with ID {user_id}")
            return "✅ Verification successful! You can now use monitor commands."

        try:
            result = await self._handle_db_operation(db_verify)
            await ctx.send(result or "❌ Error during verification")
            if "Error" in str(result):
                logger.error(f"Verification failed for {ctx.author.name}: {result}")
        except Exception as e:
            logger.error(f"Unexpected error during verification for {ctx.author.name}: {e}")
            await ctx.send("❌ An unexpected error occurred during verification. Please try again.")

    @commands.command(name='status', help="Check your monitor status")
    async def check_status(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_status(conn, cur):
            cur.execute('SELECT id FROM "user" WHERE discord_user_id = %s', (str(ctx.author.id),))
            result = cur.fetchone()
            if not result:
                return None
            return result[0]

        user_id = await self._handle_db_operation(db_status)
        if not user_id:
            await ctx.send("❌ You need to verify first. Use `!verify`")
            return

        running = self._is_monitor_running(user_id)
        status_msg = f"Monitor Status: {'✅ Running' if running else '❌ Stopped'}"

        try:
            await ctx.send(status_msg)
        except discord.Forbidden:
            try:
                await ctx.author.send(f"{status_msg}\n\nNote: Use DMs for detailed status information.")
                if isinstance(ctx.channel, discord.TextChannel):
                    await ctx.send("📨 Status sent via DM!")
            except discord.Forbidden:
                await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.")

    @commands.command(name='start', help="Start your monitor")
    async def start_monitor(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_start(conn, cur):
            cur.execute(
                'SELECT id, discord_webhook_url FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id, webhook_url = result

            # Check if stores are configured
            cur.execute(
                'SELECT COUNT(*) FROM store WHERE user_id = %s AND enabled = true;',
                (user_id,)
            )
            store_count = cur.fetchone()[0]
            if store_count == 0:
                return "❌ You need to add some stores first!"

            if self._is_monitor_running(user_id):
                return "Monitor is already running!"

            # Use webhook_url from database or fallback to environment
            webhook_url = webhook_url if webhook_url else os.environ.get('DISCORD_WEBHOOK_URL')
            if not webhook_url or not webhook_url.startswith('https://discord.com/api/webhooks/'):
                return "❌ Invalid webhook URL configuration"

            # Update user status
            cur.execute(
                'UPDATE "user" SET enabled = true WHERE id = %s;',
                (user_id,)
            )
            conn.commit()
            return (user_id, webhook_url)

        result = await self._handle_db_operation(db_start)
        if not result:
            await ctx.send("❌ You need to verify first.")
            return
        if isinstance(result, str):
            await ctx.send(result)
            return

        user_id, webhook_url = result
        status_message = await ctx.send("⌛ Starting monitor, please wait...")

        # Cleanup any existing monitor process first
        await self._cleanup_old_monitor(user_id)

        # Get absolute paths
        bot_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        start_script = os.path.join(bot_dir, 'start_monitor.py')

        if not os.path.exists(start_script):
            logger.error(f"Cannot find start_monitor.py at {start_script}")
            await status_message.edit(content="❌ Error: start_monitor.py not found")
            return

        try:
            # Setup environment with all required variables
            process_env = os.environ.copy()
            process_env.update({
                'DISCORD_WEBHOOK_URL': webhook_url,
                'MONITOR_USER_ID': str(user_id),
                'PYTHONUNBUFFERED': '1',
                'DATABASE_URL': os.environ.get('DATABASE_URL', ''),
                'PYTHONPATH': bot_dir,  # Set PYTHONPATH to project root
                'MONITOR_API_KEY': os.environ.get('MONITOR_API_KEY', '')  # Ensure API key is passed
            })

            logger.info(f"Starting monitor process for user {user_id}")
            logger.info(f"Working directory: {bot_dir}")
            logger.info(f"Start script: {start_script}")
            logger.info(f"Environment: PYTHONPATH={bot_dir}")
            logger.info(f"Monitor User ID: {user_id}")
            logger.info(f"Webhook URL configured: {'Set' if webhook_url else 'Not set'}")

            # Start the monitor process with proper error handling
            try:
                process = subprocess.Popen(
                    [sys.executable, start_script, str(user_id)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    env=process_env,
                    start_new_session=True,
                    cwd=bot_dir
                )
            except Exception as e:
                logger.error(f"Failed to start monitor process: {e}", exc_info=True)
                await status_message.edit(content=f"❌ Failed to start monitor: {str(e)}")
                return

            logger.info(f"Started monitor process with PID {process.pid}")

            # Give the process a moment to start and check its status
            await asyncio.sleep(2)

            # Check process status and capture output
            poll_result = process.poll()
            if poll_result is not None:
                stdout, stderr = process.communicate()
                error_output = stderr.strip() if stderr else stdout.strip() if stdout else "No error output available"
                logger.error(f"Process failed with exit code {poll_result}")
                logger.error(f"Process output: {error_output}")
                await status_message.edit(content=f"❌ Monitor failed to start:\n```\n{error_output}\n```")
                return

            # Verify monitor is actually running with retries
            max_retries = 3
            for attempt in range(max_retries):
                if self._is_monitor_running(user_id):
                    await status_message.edit(content="✅ Monitor started successfully!")
                    return
                logger.info(f"Waiting for monitor to start (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(1)

            # If we get here, the monitor didn't start properly
            stdout, stderr = process.communicate(timeout=2)
            error_output = stderr.strip() if stderr else stdout.strip() if stdout else "No error output available"
            logger.error(f"Monitor failed to initialize properly. Output: {error_output}")
            await status_message.edit(content=f"❌ Monitor failed to initialize:\n```\n{error_output}\n```")

        except Exception as e:
            logger.error(f"Error starting monitor: {str(e)}", exc_info=True)
            await status_message.edit(content=f"❌ Error starting monitor: {str(e)}")

    @commands.command(name='stop', help="Stop your monitor")
    async def stop_monitor(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_stop(conn, cur):
            cur.execute('SELECT id FROM "user" WHERE discord_user_id = %s;', (str(ctx.author.id),))
            result = cur.fetchone()
            if not result:
                return None
            return result[0]

        user_id = await self._handle_db_operation(db_stop)
        if not user_id:
            await ctx.send("❌ You need to verify first.")
            return

        status_message = await ctx.send("⌛ Stopping monitor...")

        try:
            if not self._is_monitor_running(user_id):
                await status_message.edit(content="Monitor is not running.")
                return

            await self._cleanup_old_monitor(user_id)
            await asyncio.sleep(1)

            if self._is_monitor_running(user_id):
                await status_message.edit(content="❌ Failed to stop monitor.")
            else:
                await status_message.edit(content="✅ Monitor stopped successfully!")

        except Exception as e:
            logger.error(f"Error stopping monitor: {e}")
            await status_message.edit(content="❌ Error stopping monitor.")

    @commands.command(name='keywords', help="List your keywords")
    async def list_keywords(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        try:
            async def db_keywords(conn, cur):
                cur.execute(
                    '''SELECT k.word, k.enabled 
                    FROM keyword k 
                    JOIN "user" u ON k.user_id = u.id 
                    WHERE u.discord_user_id = %s;''',
                    (str(ctx.author.id),)
                )
                return cur.fetchall()

            keywords = await self._handle_db_operation(db_keywords)
            if not keywords:
                await ctx.send("No keywords found. Add some using `!add_keyword <word>`")
                return

            message = "Your Keywords:\n"
            for word, enabled in keywords:
                message += f"• {word}: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
            try:
                await ctx.send(message)
            except discord.Forbidden:
                try:
                    await ctx.author.send(message)
                    if isinstance(ctx.channel, discord.TextChannel):
                        await ctx.send("📨 Keywords list sent via DM!")
                except discord.Forbidden:
                    await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.")
        except Exception as e:
            logger.error(f"Error in keywords command: {e}")
            await ctx.send("❌ Error listing keywords. Please try again.")

    @commands.command(name='add_keyword', help="Add a keyword to monitor")
    async def add_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_add_keyword(conn, cur):
            cur.execute('SELECT id FROM "user" WHERE discord_user_id = %s;', (str(ctx.author.id),))
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute('SELECT 1 FROM keyword WHERE user_id = %s AND word = %s;', (user_id, keyword))
            if cur.fetchone():
                return "⚠️ Keyword already exists."

            cur.execute('INSERT INTO keyword (user_id, word, enabled) VALUES (%s, %s, true);', (user_id, keyword))
            conn.commit()
            return f"✅ Added keyword: `{keyword}`"

        result = await self._handle_db_operation(db_add_keyword)
        await ctx.send(result or "❌ Error adding keyword")

    @commands.command(name='remove_keyword', help="Remove a keyword from your monitor")
    async def remove_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_remove_keyword(conn, cur):
            cur.execute('SELECT id FROM "user" WHERE discord_user_id = %s;', (str(ctx.author.id),))
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute('DELETE FROM keyword WHERE user_id = %s AND word = %s RETURNING word;', (user_id, keyword))
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed keyword: `{keyword}`"
            else:
                return "⚠️ Keyword not found."

        result = await self._handle_db_operation(db_remove_keyword)
        await ctx.send(result or "❌ Error removing keyword")

    @commands.command(name='preset_stores', help="Show and enable preset stores to monitor")
    async def preset_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_preset_stores(conn, cur):
            cur.execute('SELECT id FROM "user" WHERE discord_user_id = %s;', (str(ctx.author.id),))
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

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

            stores_added = 0
            for store_url in preset_stores:
                cur.execute('SELECT 1 FROM store WHERE user_id = %s AND url = %s;', (user_id, store_url))
                if not cur.fetchone():
                    cur.execute('INSERT INTO store (user_id, url, enabled) VALUES (%s, %s, true);', (user_id, store_url))
                    stores_added += 1
            conn.commit()
            return stores_added

        stores_added = await self._handle_db_operation(db_preset_stores)
        if stores_added is None:
            await ctx.send("❌ Error adding preset stores. Verify your account first.")
        else:
            await ctx.send(f"✅ Added {stores_added} new preset stores to your monitor.")

    @commands.command(name='set_webhook', help="Set your custom Discord webhook URL (via DM only)")
    async def set_webhook(self, ctx):
        if not await self._check_cooldown(ctx):
            return
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
                await ctx.send("❌ Invalid webhook URL.")
                return

            async def db_set_webhook(conn, cur):
                cur.execute('UPDATE "user" SET discord_webhook_url = %s WHERE discord_user_id = %s;',
                          (webhook_url, str(ctx.author.id)))
                conn.commit()
                return "✅ Webhook URL set!"

            result = await self._handle_db_operation(db_set_webhook)
            await ctx.send(result or "❌ Error setting webhook")

        except asyncio.TimeoutError:
            await ctx.send("Webhook setup timed out. Please try again.")

async def setup(bot):
    await bot.add_cog(MonitorCommands(bot))