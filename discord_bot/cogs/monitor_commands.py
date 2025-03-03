import os
import discord
from discord.ext import commands
import logging
import psycopg2
import sys
import psutil
import time
from datetime import datetime
import subprocess
import asyncio
import secrets
from werkzeug.security import generate_password_hash
import json

logger = logging.getLogger('MonitorCommands')

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
        try:
            # Try sending a simple text message first
            status_msg = f"Monitor Status: {'✅ Running' if running else '❌ Stopped'}"
            await ctx.send(status_msg)
        except discord.Forbidden:
            try:
                # If server message fails, try DMing the user
                await ctx.author.send(f"{status_msg}\n\nNote: Use DMs for detailed status information.")
                if isinstance(ctx.channel, discord.TextChannel):  # Only send this if in a server channel
                    await ctx.send("📨 Status sent via DM!")
            except discord.Forbidden:
                await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.")

    async def _update_monitor_status(self, user_id, is_running):
        """Update monitor status in database"""
        async def db_update(conn, cur):
            cur.execute(
                'UPDATE "user" SET enabled = %s WHERE id = %s;',
                (is_running, user_id)
            )
            conn.commit()
            return True
        return await self._handle_db_operation(db_update)

    def _is_monitor_running(self, user_id):
        """Check if monitor is running for user with enhanced validation"""
        try:
            tracking_file = f"monitor_process_{user_id}.json"
            logger.info(f"Checking monitor status for user {user_id}")
            logger.info(f"Looking for tracking file: {tracking_file}")

            # Check tracking file first
            tracking_data = None
            if os.path.exists(tracking_file):
                try:
                    with open(tracking_file) as f:
                        tracking_data = json.load(f)
                        pid = tracking_data.get('pid')
                        start_time = tracking_data.get('start_time')
                        logger.info(f"Found tracking file for user {user_id}. PID: {pid}")

                        if pid:
                            try:
                                process = psutil.Process(pid)
                                if process.is_running():
                                    # Enhanced process validation
                                    cmdline = ' '.join(process.cmdline())
                                    env = process.environ()
                                    status = process.status()
                                    create_time = datetime.fromtimestamp(process.create_time())

                                    logger.info(f"Process {pid} found running. Status: {status}")
                                    logger.info(f"Process command line: {cmdline}")
                                    logger.info(f"Process environment: MONITOR_USER_ID={env.get('MONITOR_USER_ID')}")
                                    logger.info(f"Process create time: {create_time}")

                                    # Verify it's our Python monitor process with correct user_id
                                    is_valid = (
                                        'python' in process.name().lower() and  # Is Python process
                                        ('main.py' in cmdline or 'start_monitor.py' in cmdline) and  # Running our script
                                        str(user_id) == env.get('MONITOR_USER_ID') and  # Correct user
                                        status not in ['zombie', 'dead'] and  # Process is active
                                        process.cpu_times().user > 0  # Has consumed CPU time
                                    )

                                    if is_valid:
                                        logger.info(f"✓ Confirmed active monitor process for user {user_id} with PID {pid}")
                                        return True
                                    else:
                                        logger.warning(f"× Process {pid} failed validation checks")
                                else:
                                    logger.info(f"Process {pid} is not running")
                            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                                logger.error(f"Error checking process {pid}: {e}")

                        # If we get here, the tracking file is stale
                        logger.info(f"Removing stale tracking file for user {user_id}")
                        os.remove(tracking_file)
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"Error reading tracking file: {e}")
                    try:
                        os.remove(tracking_file)
                    except OSError:
                        pass

            # Fallback to process scanning with enhanced checks
            logger.info(f"Scanning for monitor process for user {user_id}")
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'environ', 'status', 'create_time']):
                try:
                    pinfo = proc.info
                    env = pinfo.get('environ', {})
                    cmdline = ' '.join(pinfo['cmdline'] or [])
                    status = pinfo.get('status')

                    # Enhanced validation checks
                    is_python = 'python' in pinfo['name'].lower()
                    is_monitor = ('main.py' in cmdline or 'start_monitor.py' in cmdline)
                    has_user_id = str(user_id) == env.get('MONITOR_USER_ID')
                    is_active = status not in ['zombie', 'dead']

                    if is_python and is_monitor:
                        logger.info(f"Found Python monitor process: PID {pinfo['pid']}")
                        logger.info(f"Process command line: {cmdline}")
                        logger.info(f"Process environment MONITOR_USER_ID: {env.get('MONITOR_USER_ID')}")
                        logger.info(f"Process status: {status}")

                        if has_user_id and is_active:
                            try:
                                process = psutil.Process(pinfo['pid'])
                                if process.cpu_times().user > 0:  # Verify process has run
                                    logger.info(f"✓ Confirmed active monitor process for user {user_id}: PID {pinfo['pid']}")
                                    return True
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                continue
                        else:
                            logger.info(f"× Process PID {pinfo['pid']} failed validation")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.error(f"Error checking process: {e}")
                    continue

            if not self._is_monitor_running(user_id):
                logger.info(f"No active monitor process found for user {user_id}")
                asyncio.create_task(self._update_monitor_status(user_id, False))

            return False

        except Exception as e:
            logger.error(f"Error checking monitor status: {e}")
            return False

    async def _get_monitor_pid(self, user_id):
        """Get the PID of a user's monitor process if running"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'environ']):
                try:
                    env = proc.info.get('environ', {})
                    cmdline = ' '.join(proc.info['cmdline'] or [])

                    is_python = 'python' in proc.info['name'].lower()
                    is_monitor = ('main.py' in cmdline or 'start_monitor.py' in cmdline)
                    has_user_id = (
                        env.get('MONITOR_USER_ID') == str(user_id) or
                        f"MONITOR_USER_ID={user_id}" in cmdline
                    )

                    if is_python and is_monitor and has_user_id:
                        return proc.info['pid']
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return None
        except Exception as e:
            logger.error(f"Error getting monitor PID: {e}")
            return None

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

            cur.execute(
                'SELECT COUNT(*) FROM store WHERE user_id = %s AND enabled = true;',
                (user_id,)
            )
            store_count = cur.fetchone()[0]
            if store_count == 0:
                return "❌ You need to add some stores first!"

            if self._is_monitor_running(user_id):
                return "Monitor is already running!"

            # Set webhook_url if not set
            webhook_url = webhook_url if webhook_url else os.environ.get('DISCORD_WEBHOOK_URL')

            # Update user status
            cur.execute(
                'UPDATE "user" SET enabled = true WHERE id = %s;',
                (user_id,)
            )
            conn.commit()
            return (user_id, webhook_url, store_count)

        result = await self._handle_db_operation(db_start)
        if not result:
            await ctx.send("❌ Error starting monitor. Database error.")
            return
        if isinstance(result, str):
            await ctx.send(result)
            return

        user_id, webhook_url, store_count = result

        status_message = await ctx.send("⌛ Starting monitor, please wait...")

        # Cleanup any existing monitor process first
        await self._cleanup_old_monitor(user_id)

        # Get the absolute path to start_monitor.py
        start_script = os.path.abspath(os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'start_monitor.py'
        ))

        # Verify files exist
        if not os.path.exists(start_script):
            logger.error(f"Cannot find start_monitor.py at {start_script}")
            await status_message.edit(content="❌ Error: start_monitor.py not found")
            return

        logger.info(f"Starting monitor for user {user_id}")
        logger.info(f"start_monitor.py path: {start_script}")
        logger.info(f"Current working directory: {os.getcwd()}")

        # Setup environment
        process_env = os.environ.copy()
        process_env.update({
            'DISCORD_WEBHOOK_URL': webhook_url,
            'MONITOR_USER_ID': str(user_id),
            'PYTHONUNBUFFERED': '1',
            'PYTHONPATH': os.getcwd()  # Add current directory to Python path
        })

        logging.info("Environment variables set for monitor process:")
        logging.info(f"- MONITOR_USER_ID: {process_env.get('MONITOR_USER_ID')}")
        logging.info(f"- DISCORD_WEBHOOK_URL: {'Set' if process_env.get('DISCORD_WEBHOOK_URL') else 'Not set'}")
        logging.info(f"- PYTHONPATH: {process_env.get('PYTHONPATH')}")

        try:
            # Start the monitor process
            process = subprocess.Popen(
                [sys.executable, start_script, str(user_id)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=process_env,
                start_new_session=True,
                cwd=os.path.dirname(start_script)  # Set working directory to where the scripts are
            )

            logger.info(f"Started process with PID {process.pid}")

            # Give the process a moment to start and check its status
            time.sleep(2)
            if process.poll() is not None:
                error_output = process.stdout.read() if process.stdout else "No error output available"
                logger.error(f"Process failed immediately. Exit code: {process.returncode}")
                logger.error(f"Process output: {error_output}")
                await status_message.edit(content=f"❌ Monitor failed to start. Exit code: {process.returncode}")
                return

            # Verify the process is actually running
            retries = 3
            for attempt in range(retries):
                if self._is_monitor_running(user_id):
                    success_msg = [
                        "✅ Monitor started successfully!",
                        f"Using {'custom' if webhook_url != os.environ.get('DISCORD_WEBHOOK_URL') else 'default'} webhook.",
                        f"Monitoring {store_count} store{'s' if store_count != 1 else ''}.",
                        "Use !status to check monitor status."
                    ]
                    await status_message.edit(content="\n".join(success_msg))
                    return

                logger.info(f"Waiting for monitor to start (attempt {attempt + 1}/{retries})")
                await asyncio.sleep(2)

            # If we get here, the monitor didn't start properly
            error_output = process.stdout.read() if process.stdout else "No error output available"
            logger.error(f"Monitor process failed to initialize properly. Output: {error_output}")
            await status_message.edit(content="❌ Monitor failed to initialize. Please check the logs.")

        except Exception as e:
            logger.error(f"Error starting monitor process: {e}")
            await status_message.edit(content=f"❌ Error starting monitor: {str(e)}")

    @commands.command(name='stop', help="Stop your monitor")
    async def stop_monitor(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_stop(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]
            return user_id

        user_id = await self._handle_db_operation(db_stop)
        if not user_id:
            await ctx.send("❌ You need to verify your account first.")
            return

        status_message = await ctx.send("⌛ Stopping monitor...")

        try:
            # Check if monitor is actually running
            if not self._is_monitor_running(user_id):
                await status_message.edit(content="Monitor is not running.")
                await self._update_monitor_status(user_id, False)
                return

            # Use cleanup function to terminate the process
            await self._cleanup_old_monitor(user_id)

            # Double check if process is really stopped
            time.sleep(1)
            if self._is_monitor_running(user_id):
                await status_message.edit(content="❌ Failed to stop monitor. Please try again.")
            else:
                await self._update_monitor_status(user_id, False)
                await status_message.edit(content="✅ Monitor stopped successfully!")

        except Exception as e:
            logger.error(f"Error stopping monitor for user {user_id}: {e}")
            await status_message.edit(content="❌ Error stopping monitor. Please try again.")

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

            # Send as plain text instead of embed if permissions are limited
            message = "Your Keywords:\n"
            for word, enabled in keywords:
                message += f"• {word}: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
            await ctx.send(message)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to send rich messages. Please give me 'Embed Links' permission or contact an admin.")
        except Exception as e:
            logger.error(f"Error in keywords command: {e}")
            await ctx.send("❌ Error listing keywords. Please try again.")

    @commands.command(name='add_keyword', help="Add a keyword to monitor")
    async def add_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_add_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM keyword WHERE user_id = %s AND word = %s;',
                (user_id, keyword)
            )
            if cur.fetchone():
                return "⚠️ Keyword already exists."

            cur.execute(
                'INSERT INTO keyword (user_id, word, enabled) VALUES (%s, %s, true);',
                (user_id, keyword)
            )
            conn.commit()
            return f"✅ Added keyword: `{keyword}`"

        result = await self._handle_db_operation(db_add_keyword)
        await ctx.send(result or "❌ Error adding keyword.")

    @commands.command(name='remove_keyword', help="Remove a keyword from your monitor")
    async def remove_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_remove_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM keyword WHERE user_id = %s AND word = %s RETURNING word;',
                (user_id, keyword)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed keyword: `{keyword}`"
            else:
                return "⚠️ Keyword not found."

        result = await self._handle_db_operation(db_remove_keyword)
        await ctx.send(result or "❌ Error removing keyword.")

    @commands.command(name='preset_stores', help="Show and enable preset stores to monitor")
    async def preset_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_preset_stores(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
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
            return (stores_added, len(preset_stores))

        result = await self._handle_db_operation(db_preset_stores)
        if not result:
            await ctx.send("❌ Error adding preset stores.")
            return
        stores_added, total_stores = result

        embed = discord.Embed(
            title="Preset Stores Added",
            description=f"Added {stores_added} new preset stores to your monitor.",
            color=discord.Color.green()
        )
        embed.add_field(name="Total Preset Stores", value=str(total_stores))
        await ctx.send(embed=embed)

    @commands.command(name='add_store', help="Add a store URL to monitor")
    async def add_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return
        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_add_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM store WHERE user_id = %s AND url = %s;',
                (user_id, store_url)
            )
            if cur.fetchone():
                return "⚠️ Store already exists."

            cur.execute(
                'INSERT INTO store (user_id, url, enabled) VALUES (%s, %s, true);',
                (user_id, store_url)
            )
            conn.commit()
            return f"✅ Added store: `{store_url}`"

        result = await self._handle_db_operation(db_add_store)
        await ctx.send(result or "❌ Error adding store.")

    @commands.command(name='list_stores', help="List all your active stores")
    async def list_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_list_stores(conn, cur):
            cur.execute(
                '''SELECT s.url, s.enabled 
                FROM store s 
                JOIN "user" u ON s.user_id = u.id 
                WHERE u.discord_user_id = %s;''',
                (str(ctx.author.id),)
            )
            return cur.fetchall()

        stores = await self._handle_db_operation(db_list_stores)
        if not stores:
            await ctx.send("No stores found. Add some using `!add_store <url>` or `!preset_stores`")
            return

        # Prepare a plain text message
        enabled_stores = []
        disabled_stores = []
        for url, enabled in stores:
            if enabled:
                enabled_stores.append(url)
            else:
                disabled_stores.append(url)

        message = "Your Monitored Stores:\n\n"
        if enabled_stores:
            message += "✅ Active Stores:\n"
            message += "\n".join(f"• {url}" for url in enabled_stores)
            message += "\n\n"
        if disabled_stores:
            message += "❌ Disabled Stores:\n"
            message += "\n".join(f"• {url}" for url in disabled_stores)

        message += "\nUse !add_store to add more stores or !preset_stores to add preset stores"

        try:
            # Try sending in the current channel
            await ctx.send(message)
        except discord.Forbidden:
            try:
                # If that fails, try DMing the user
                await ctx.author.send(message)
                if isinstance(ctx.channel, discord.TextChannel):  # Only send this if in a server channel
                    await ctx.send("📨 Store list sent via DM!")
            except discord.Forbidden:
                await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.")

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
                cur.execute(
                    'SELECT id FROM "user" WHERE discord_user_id = %s;',
                    (str(ctx.author.id),)
                )
                result = cur.fetchone()
                if not result:
                    return None
                user_id = result[0]

                cur.execute(
                    'UPDATE "user" SET discord_webhook_url = %s WHERE id = %s;',
                    (webhook_url, user_id)
                )
                conn.commit()
                return "✅ Webhook URL set!"

            result = await self._handle_db_operation(db_set_webhook)
            await ctx.send(result or "❌ Error setting webhook.")

        except asyncio.TimeoutError:
            await ctx.send("Webhook setup timed out. Please try again.")

    @commands.command(name='remove_store', help="Remove a store URL from your monitor")
    async def remove_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return

        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_remove_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM store WHERE user_id = %s AND url = %s RETURNING url;',
                (user_id, store_url)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed store: `{store_url}`"
            else:
                return "⚠️ Store not found in your list."

        result = await self._handle_db_operation(db_remove_store)
        await ctx.send(result or "❌ Error removing store.")


    async def _cleanup_old_monitor(self, user_id):
        """Cleanup any existing monitor process for the user"""
        try:
            # First check tracking file
            tracking_file = f"monitor_process_{user_id}.json"
            if os.path.exists(tracking_file):
                try:
                    with open(tracking_file) as f:
                        data = json.load(f)
                        pid = data.get('pid')
                        if pid:
                            try:
                                process = psutil.Process(pid)
                                # Verify it's our process before terminating 
                                if ('python' in process.name().lower() and
                                    str(user_id) == process.environ().get('MONITOR_USER_ID')):
                                    process.terminate()
                                    try:
                                        process.wait(timeout=3)
                                        logger.info(f"Successfully terminated process {pid}")
                                    except psutil.TimeoutExpired:
                                        process.kill()
                                        logger.info(f"Force killed process {pid}")
                                    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                                        logger.warning(f"Error terminating process {pid}: {e}")
                                        try:
                                            process.kill()
                                        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                                            logger.error(f"Could not kill process {pid}: {e}")
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"Error reading tracking file: {e}")
                    try:
                        os.remove(tracking_file)
                    except OSError as e:
                        logger.error(f"Could not remove tracking file: {e}")

            # Check for duplicated process in system
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'environ']):
                try:
                    if ('python' in proc.name().lower() and
                        str(user_id) == proc.environ().get('MONITOR_USER_ID')):
                        proc.terminate()
                        try:
                            proc.wait(timeout=3)
                        except psutil.TimeoutExpired:
                            proc.kill() 
                            logger.info(f"Force killed duplicated process {proc.pid}")
                        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                            logger.warning(f"Error cleaning up process {proc.pid}: {e}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # Clean up any stale tracking file
            if os.path.exists(tracking_file):
                try:
                    os.remove(tracking_file)
                    logger.info(f"Removed stale tracking file: {tracking_file}")
                except OSError as e:
                    logger.error(f"Error removing tracking file: {e}")

        except Exception as e:
            logger.error(f"Error during monitor cleanup: {e}")

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

            # Send as plain text instead of embed if permissions are limited
            message = "Your Keywords:\n"
            for word, enabled in keywords:
                message += f"• {word}: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
            await ctx.send(message)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to send rich messages. Please give me 'Embed Links' permission or contact an admin.")
        except Exception as e:
            logger.error(f"Error in keywords command: {e}")
            await ctx.send("❌ Error listing keywords. Please try again.")

    @commands.command(name='add_keyword', help="Add a keyword to monitor")
    async def add_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_add_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM keyword WHERE user_id = %s AND word = %s;',
                (user_id, keyword)
            )
            if cur.fetchone():
                return "⚠️ Keyword already exists."

            cur.execute(
                'INSERT INTO keyword (user_id, word, enabled) VALUES (%s, %s, true);',
                (user_id, keyword)
            )
            conn.commit()
            return f"✅ Added keyword: `{keyword}`"

        result = await self._handle_db_operation(db_add_keyword)
        await ctx.send(result or "❌ Error adding keyword.")

    @commands.command(name='remove_keyword', help="Remove a keyword from your monitor")
    async def remove_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_remove_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM keyword WHERE user_id = %s AND word = %s RETURNING word;',
                (user_id, keyword)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed keyword: `{keyword}`"
            else:
                return "⚠️ Keyword not found."

        result = await self._handle_db_operation(db_remove_keyword)
        await ctx.send(result or "❌ Error removing keyword.")

    @commands.command(name='preset_stores', help="Show and enable preset stores to monitor")
    async def preset_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_preset_stores(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
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
            return (stores_added, len(preset_stores))

        result = await self._handle_db_operation(db_preset_stores)
        if not result:
            await ctx.send("❌ Error adding preset stores.")
            return
        stores_added, total_stores = result

        embed = discord.Embed(
            title="Preset Stores Added",
            description=f"Added {stores_added} new preset stores to your monitor.",
            color=discord.Color.green()
        )
        embed.add_field(name="Total Preset Stores", value=str(total_stores))
        await ctx.send(embed=embed)

    @commands.command(name='add_store', help="Add a store URL to monitor")
    async def add_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return
        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_add_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM store WHERE user_id = %s AND url = %s;',
                (user_id, store_url)
            )
            if cur.fetchone():
                return "⚠️ Store already exists."

            cur.execute(
                'INSERT INTO store (user_id, url, enabled) VALUES (%s, %s, true);',
                (user_id, store_url)
            )
            conn.commit()
            return f"✅ Added store: `{store_url}`"

        result = await self._handle_db_operation(db_add_store)
        await ctx.send(result or "❌ Error adding store.")

    @commands.command(name='list_stores', help="List all your active stores")
    async def list_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_list_stores(conn, cur):
            cur.execute(
                '''SELECT s.url, s.enabled 
                FROM store s 
                JOIN "user" u ON s.user_id = u.id 
                WHERE u.discord_user_id = %s;''',
                (str(ctx.author.id),)
            )
            return cur.fetchall()

        stores = await self._handle_db_operation(db_list_stores)
        if not stores:
            await ctx.send("No stores found. Add some using `!add_store <url>` or `!preset_stores`")
            return

        # Prepare a plain text message
        enabled_stores = []
        disabled_stores = []
        for url, enabled in stores:
            if enabled:
                enabled_stores.append(url)
            else:
                disabled_stores.append(url)

        message = "Your Monitored Stores:\n\n"
        if enabled_stores:
            message += "✅ Active Stores:\n"
            message += "\n".join(f"• {url}" for url in enabled_stores)
            message += "\n\n"
        if disabled_stores:
            message += "❌ Disabled Stores:\n"
            message += "\n".join(f"• {url}" for url in disabled_stores)

        message += "\nUse !add_store to add more stores or !preset_stores to add preset stores"

        try:
            # Try sending in the current channel
            await ctx.send(message)
        except discord.Forbidden:
            try:
                # If that fails, try DMing the user
                await ctx.author.send(message)
                if isinstance(ctx.channel, discord.TextChannel):  # Only send this if in a server channel
                    await ctx.send("📨 Store list sent via DM!")
            except discord.Forbidden:
                await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.")

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
                cur.execute(
                    'SELECT id FROM "user" WHERE discord_user_id = %s;',
                    (str(ctx.author.id),)
                )
                result = cur.fetchone()
                if not result:
                    return None
                user_id = result[0]

                cur.execute(
                    'UPDATE "user" SET discord_webhook_url = %s WHERE id = %s;',
                    (webhook_url, user_id)
                )
                conn.commit()
                return "✅ Webhook URL set!"

            result = await self._handle_db_operation(db_set_webhook)
            await ctx.send(result or "❌ Error setting webhook.")

        except asyncio.TimeoutError:
            await ctx.send("Webhook setup timed out. Please try again.")

    @commands.command(name='remove_store', help="Remove a store URL from your monitor")
    async def remove_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return

        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_remove_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM store WHERE user_id = %s AND url = %s RETURNING url;',
                (user_id, store_url)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed store: `{store_url}`"
            else:
                return "⚠️ Store not found in your list."

        result = await self._handle_db_operation(db_remove_store)
        await ctx.send(result or "❌ Error removing store.")


    async def _cleanup_old_monitor(self, user_id):
        """Cleanup any existing monitor process for the user"""
        try:
            pid = await self._get_monitor_pid(user_id)
            if pid:
                try:
                    process = psutil.Process(pid)
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                        logger.info(f"Successfully terminated old process {pid}")
                    except psutil.TimeoutExpired:
                        process.kill()
                        logger.info(f"Force killed old process {pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.error(f"Error terminating old process {pid}: {e}")

            # Clean up any stale tracking file
            tracking_file = f"monitor_process_{user_id}.json"
            if os.path.exists(tracking_file):
                try:
                    os.remove(tracking_file)
                    logger.info(f"Removed stale tracking file: {tracking_file}")
                except OSError as e:
                    logger.error(f"Error removing tracking file: {e}")

        except Exception as e:
            logger.error(f"Error during monitor cleanup: {e}")

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

            # Send as plain text instead of embed if permissions are limited
            message = "Your Keywords:\n"
            for word, enabled in keywords:
                message += f"• {word}: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
            await ctx.send(message)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to send rich messages. Please give me 'Embed Links' permission or contact an admin.")
        except Exception as e:
            logger.error(f"Error in keywords command: {e}")
            await ctx.send("❌ Error listing keywords. Please try again.")

    @commands.command(name='add_keyword', help="Add a keyword to monitor")
    async def add_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_add_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM keyword WHERE user_id = %s AND word = %s;',
                (user_id, keyword)
            )
            if cur.fetchone():
                return "⚠️ Keyword already exists."

            cur.execute(
                'INSERT INTO keyword (user_id, word, enabled) VALUES (%s, %s, true);',
                (user_id, keyword)
            )
            conn.commit()
            return f"✅ Added keyword: `{keyword}`"

        result = await self._handle_db_operation(db_add_keyword)
        await ctx.send(result or "❌ Error adding keyword.")

    @commands.command(name='remove_keyword', help="Remove a keyword from your monitor")
    async def remove_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_remove_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM keyword WHERE user_id = %s AND word = %s RETURNING word;',
                (user_id, keyword)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed keyword: `{keyword}`"
            else:
                return "⚠️ Keyword not found."

        result = await self._handle_db_operation(db_remove_keyword)
        await ctx.send(result or "❌ Error removing keyword.")

    @commands.command(name='preset_stores', help="Show and enable preset stores to monitor")
    async def preset_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_preset_stores(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
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
            return (stores_added, len(preset_stores))

        result = await self._handle_db_operation(db_preset_stores)
        if not result:
            await ctx.send("❌ Error adding preset stores.")
            return
        stores_added, total_stores = result

        embed = discord.Embed(
            title="Preset Stores Added",
            description=f"Added {stores_added} new preset stores to your monitor.",
            color=discord.Color.green()
        )
        embed.add_field(name="Total Preset Stores", value=str(total_stores))
        await ctx.send(embed=embed)

    @commands.command(name='add_store', help="Add a store URL to monitor")
    async def add_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return
        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_add_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM store WHERE user_id = %s AND url = %s;',
                (user_id, store_url)
            )
            if cur.fetchone():
                return "⚠️ Store already exists."

            cur.execute(
                'INSERT INTO store (user_id, url, enabled) VALUES (%s, %s, true);',
                (user_id, store_url)
            )
            conn.commit()
            return f"✅ Added store: `{store_url}`"

        result = await self._handle_db_operation(db_add_store)
        await ctx.send(result or "❌ Error adding store.")

    @commands.command(name='list_stores', help="List all your active stores")
    async def list_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_list_stores(conn, cur):
            cur.execute(
                '''SELECT s.url, s.enabled 
                FROM store s 
                JOIN "user" u ON s.user_id = u.id 
                WHERE u.discord_user_id = %s;''',
                (str(ctx.author.id),)
            )
            return cur.fetchall()

        stores = await self._handle_db_operation(db_list_stores)
        if not stores:
            await ctx.send("No stores found. Add some using `!add_store <url>` or `!preset_stores`")
            return

        # Prepare a plain text message
        enabled_stores = []
        disabled_stores = []
        for url, enabled in stores:
            if enabled:
                enabled_stores.append(url)
            else:
                disabled_stores.append(url)

        message = "Your Monitored Stores:\n\n"
        if enabled_stores:
            message += "✅ Active Stores:\n"
            message += "\n".join(f"• {url}" for url in enabled_stores)
            message += "\n\n"
        if disabled_stores:
            message += "❌ Disabled Stores:\n"
            message += "\n".join(f"• {url}" for url in disabled_stores)

        message += "\nUse !add_store to add more stores or !preset_stores to add preset stores"

        try:
            # Try sending in the current channel
            await ctx.send(message)
        except discord.Forbidden:
            try:
                # If that fails, try DMing the user
                await ctx.author.send(message)
                if isinstance(ctx.channel, discord.TextChannel):  # Only send this if in a server channel
                    await ctx.send("📨 Store list sent via DM!")
            except discord.Forbidden:
                await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.")

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
                cur.execute(
                    'SELECT id FROM "user" WHERE discord_user_id = %s;',
                    (str(ctx.author.id),)
                )
                result = cur.fetchone()
                if not result:
                    return None
                user_id = result[0]

                cur.execute(
                    'UPDATE "user" SET discord_webhook_url = %s WHERE id = %s;',
                    (webhook_url, user_id)
                )
                conn.commit()
                return "✅ Webhook URL set!"

            result = await self._handle_db_operation(db_set_webhook)
            await ctx.send(result or "❌ Error setting webhook.")

        except asyncio.TimeoutError:
            await ctx.send("Webhook setup timed out. Please try again.")

    @commands.command(name='remove_store', help="Remove a store URL from your monitor")
    async def remove_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return

        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_remove_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM store WHERE user_id = %s AND url = %s RETURNING url;',
                (user_id, store_url)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed store: `{store_url}`"
            else:
                return "⚠️ Store not found in your list."

        result = await self._handle_db_operation(db_remove_store)
        await ctx.send(result or "❌ Error removing store.")


    async def _cleanup_old_monitor(self, user_id):
        """Cleanup any existing monitor process for the user"""
        try:
            pid = await self._get_monitor_pid(user_id)
            if pid:
                try:
                    process = psutil.Process(pid)
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                        logger.info(f"Successfully terminated old process {pid}")
                    except psutil.TimeoutExpired:
                        process.kill()
                        logger.info(f"Force killed old process {pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.error(f"Error terminating old process {pid}: {e}")

            # Clean up any stale tracking file
            tracking_file = f"monitor_process_{user_id}.json"
            if os.path.exists(tracking_file):
                try:
                    os.remove(tracking_file)
                    logger.info(f"Removed stale tracking file: {tracking_file}")
                except OSError as e:
                    logger.error(f"Error removing tracking file: {e}")

        except Exception as e:
            logger.error(f"Error during monitor cleanup: {e}")

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

            # Send as plain text instead of embed if permissions are limited
            message = "Your Keywords:\n"
            for word, enabled in keywords:
                message += f"• {word}: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
            await ctx.send(message)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to send rich messages. Please give me 'Embed Links' permission or contact an admin.")
        except Exception as e:
            logger.error(f"Error in keywords command: {e}")
            await ctx.send("❌ Error listing keywords. Please try again.")

    @commands.command(name='add_keyword', help="Add a keyword to monitor")
    async def add_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_add_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM keyword WHERE user_id = %s AND word = %s;',
                (user_id, keyword)
            )
            if cur.fetchone():
                return "⚠️ Keyword already exists."

            cur.execute(
                'INSERT INTO keyword (user_id, word, enabled) VALUES (%s, %s, true);',
                (user_id, keyword)
            )
            conn.commit()
            return f"✅ Added keyword: `{keyword}`"

        result = await self._handle_db_operation(db_add_keyword)
        await ctx.send(result or "❌ Error adding keyword.")

    @commands.command(name='remove_keyword', help="Remove a keyword from your monitor")
    async def remove_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_remove_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM keyword WHERE user_id = %s AND word = %s RETURNING word;',
                (user_id, keyword)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed keyword: `{keyword}`"
            else:
                return "⚠️ Keyword not found."

        result = await self._handle_db_operation(db_remove_keyword)
        await ctx.send(result or "❌ Error removing keyword.")

    @commands.command(name='preset_stores', help="Show and enable preset stores to monitor")
    async def preset_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_preset_stores(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
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
            return (stores_added, len(preset_stores))

        result = await self._handle_db_operation(db_preset_stores)
        if not result:
            await ctx.send("❌ Error adding preset stores.")
            return
        stores_added, total_stores = result

        embed = discord.Embed(
            title="Preset Stores Added",
            description=f"Added {stores_added} new preset stores to your monitor.",
            color=discord.Color.green()
        )
        embed.add_field(name="Total Preset Stores", value=str(total_stores))
        await ctx.send(embed=embed)

    @commands.command(name='add_store', help="Add a store URL to monitor")
    async def add_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return
        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_add_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM store WHERE user_id = %s AND url = %s;',
                (user_id, store_url)
            )
            if cur.fetchone():
                return "⚠️ Store already exists."

            cur.execute(
                'INSERT INTO store (user_id, url, enabled) VALUES (%s, %s, true);',
                (user_id, store_url)
            )
            conn.commit()
            return f"✅ Added store: `{store_url}`"

        result = await self._handle_db_operation(db_add_store)
        await ctx.send(result or "❌ Error adding store.")

    @commands.command(name='list_stores', help="List all your active stores")
    async def list_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_list_stores(conn, cur):
            cur.execute(
                '''SELECT s.url, s.enabled 
                FROM store s 
                JOIN "user" u ON s.user_id = u.id 
                WHERE u.discord_user_id = %s;''',
                (str(ctx.author.id),)
            )
            return cur.fetchall()

        stores = await self._handle_db_operation(db_list_stores)
        if not stores:
            await ctx.send("No stores found. Add some using `!add_store <url>` or `!preset_stores`")
            return

        # Prepare a plain text message
        enabled_stores = []
        disabled_stores = []
        for url, enabled in stores:
            if enabled:
                enabled_stores.append(url)
            else:
                disabled_stores.append(url)

        message = "Your Monitored Stores:\n\n"
        if enabled_stores:
            message += "✅ Active Stores:\n"
            message += "\n".join(f"• {url}" for url in enabled_stores)
            message += "\n\n"
        if disabled_stores:
            message += "❌ Disabled Stores:\n"
            message += "\n".join(f"• {url}" for url in disabled_stores)

        message += "\nUse !add_store to add more stores or !preset_stores to add preset stores"

        try:
            # Try sending in the current channel
            await ctx.send(message)
        except discord.Forbidden:
            try:
                # If that fails, try DMing the user
                await ctx.author.send(message)
                if isinstance(ctx.channel, discord.TextChannel):  # Only send this if in a server channel
                    await ctx.send("📨 Store list sent via DM!")
            except discord.Forbidden:
                await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.")

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
                cur.execute(
                    'SELECT id FROM "user" WHERE discord_user_id = %s;',
                    (str(ctx.author.id),)
                )
                result = cur.fetchone()
                if not result:
                    return None
                user_id = result[0]

                cur.execute(
                    'UPDATE "user" SET discord_webhook_url = %s WHERE id = %s;',
                    (webhook_url, user_id)
                )
                conn.commit()
                return "✅ Webhook URL set!"

            result = await self._handle_db_operation(db_set_webhook)
            await ctx.send(result or "❌ Error setting webhook.")

        except asyncio.TimeoutError:
            await ctx.send("Webhook setup timed out. Please try again.")

    @commands.command(name='remove_store', help="Remove a store URL from your monitor")
    async def remove_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return

        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_remove_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM store WHERE user_id = %s AND url = %s RETURNING url;',
                (user_id, store_url)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed store: `{store_url}`"
            else:
                return "⚠️ Store not found in your list."

        result = await self._handle_db_operation(db_remove_store)
        await ctx.send(result or "❌ Error removing store.")


    async def _cleanup_old_monitor(self, user_id):
        """Cleanup any existing monitor process for the user"""
        try:
            pid = await self._get_monitor_pid(user_id)
            if pid:
                try:
                    process = psutil.Process(pid)
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                        logger.info(f"Successfully terminated old process {pid}")
                    except psutil.TimeoutExpired:
                        process.kill()
                        logger.info(f"Force killed old process {pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.error(f"Error terminating old process {pid}: {e}")

            # Clean up any stale tracking file
            tracking_file = f"monitor_process_{user_id}.json"
            if os.path.exists(tracking_file):
                try:
                    os.remove(tracking_file)
                    logger.info(f"Removed stale tracking file: {tracking_file}")
                except OSError as e:
                    logger.error(f"Error removing tracking file: {e}")

        except Exception as e:
            logger.error(f"Error during monitor cleanup: {e}")

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

            # Send as plain text instead of embed if permissions are limited
            message = "Your Keywords:\n"
            for word, enabled in keywords:
                message += f"• {word}: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
            await ctx.send(message)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to send rich messages. Please give me 'Embed Links' permission or contact an admin.")
        except Exception as e:
            logger.error(f"Error in keywords command: {e}")
            await ctx.send("❌ Error listing keywords. Please try again.")

    @commands.command(name='add_keyword', help="Add a keyword to monitor")
    async def add_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_add_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM keyword WHERE user_id = %s AND word = %s;',
                (user_id, keyword)
            )
            if cur.fetchone():
                return "⚠️ Keyword already exists."

            cur.execute(
                'INSERT INTO keyword (user_id, word, enabled) VALUES (%s, %s, true);',
                (user_id, keyword)
            )
            conn.commit()
            return f"✅ Added keyword: `{keyword}`"

        result = await self._handle_db_operation(db_add_keyword)
        await ctx.send(result or "❌ Error adding keyword.")

    @commands.command(name='remove_keyword', help="Remove a keyword from your monitor")
    async def remove_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_remove_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM keyword WHERE user_id = %s AND word = %s RETURNING word;',
                (user_id, keyword)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed keyword: `{keyword}`"
            else:
                return "⚠️ Keyword not found."

        result = await self._handle_db_operation(db_remove_keyword)
        await ctx.send(result or "❌ Error removing keyword.")

    @commands.command(name='preset_stores', help="Show and enable preset stores to monitor")
    async def preset_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_preset_stores(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
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
            return (stores_added, len(preset_stores))

        result = await self._handle_db_operation(db_preset_stores)
        if not result:
            await ctx.send("❌ Error adding preset stores.")
            return
        stores_added, total_stores = result

        embed = discord.Embed(
            title="Preset Stores Added",
            description=f"Added {stores_added} new preset stores to your monitor.",
            color=discord.Color.green()
        )
        embed.add_field(name="Total Preset Stores", value=str(total_stores))
        await ctx.send(embed=embed)

    @commands.command(name='add_store', help="Add a store URL to monitor")
    async def add_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return
        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_add_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM store WHERE user_id = %s AND url = %s;',
                (user_id, store_url)
            )
            if cur.fetchone():
                return "⚠️ Store already exists."

            cur.execute(
                'INSERT INTO store (user_id, url, enabled) VALUES (%s, %s, true);',
                (user_id, store_url)
            )
            conn.commit()
            return f"✅ Added store: `{store_url}`"

        result = await self._handle_db_operation(db_add_store)
        await ctx.send(result or "❌ Error adding store.")

    @commands.command(name='list_stores', help="List all your active stores")
    async def list_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_list_stores(conn, cur):
            cur.execute(
                '''SELECT s.url, s.enabled 
                FROM store s 
                JOIN "user" u ON s.user_id = u.id 
                WHERE u.discord_user_id = %s;''',
                (str(ctx.author.id),)
            )
            return cur.fetchall()

        stores = await self._handle_db_operation(db_list_stores)
        if not stores:
            await ctx.send("No stores found. Add some using `!add_store <url>` or `!preset_stores`")
            return

        # Prepare a plain text message
        enabled_stores = []
        disabled_stores = []
        for url, enabled in stores:
            if enabled:
                enabled_stores.append(url)
            else:
                disabled_stores.append(url)

        message = "Your Monitored Stores:\n\n"
        if enabled_stores:
            message += "✅ Active Stores:\n"
            message += "\n".join(f"• {url}" for url in enabled_stores)
            message += "\n\n"
        if disabled_stores:
            message += "❌ Disabled Stores:\n"
            message += "\n".join(f"• {url}" for url in disabled_stores)

        message += "\nUse !add_store to add more stores or !preset_stores to add preset stores"

        try:
            # Try sending in the current channel
            await ctx.send(message)
        except discord.Forbidden:
            try:
                # If that fails, try DMing the user
                await ctx.author.send(message)
                if isinstance(ctx.channel, discord.TextChannel):  # Only send this if in a server channel
                    await ctx.send("📨 Store list sent via DM!")
            except discord.Forbidden:
                await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.")

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
                cur.execute(
                    'SELECT id FROM "user" WHERE discord_user_id = %s;',
                    (str(ctx.author.id),)
                )
                result = cur.fetchone()
                if not result:
                    return None
                user_id = result[0]

                cur.execute(
                    'UPDATE "user" SET discord_webhook_url = %s WHERE id = %s;',
                    (webhook_url, user_id)
                )
                conn.commit()
                return "✅ Webhook URL set!"

            result = await self._handle_db_operation(db_set_webhook)
            await ctx.send(result or "❌ Error setting webhook.")

        except asyncio.TimeoutError:
            await ctx.send("Webhook setup timed out. Please try again.")

    @commands.command(name='remove_store', help="Remove a store URL from your monitor")
    async def remove_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return

        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_remove_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM store WHERE user_id = %s AND url = %s RETURNING url;',
                (user_id, store_url)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed store: `{store_url}`"
            else:
                return "⚠️ Store not found in your list."

        result = await self._handle_db_operation(db_remove_store)
        await ctx.send(result or "❌ Error removing store.")


    async def _cleanup_old_monitor(self, user_id):
        """Cleanup any existing monitor process for the user"""
        try:
            pid = await self._get_monitor_pid(user_id)
            if pid:
                try:
                    process = psutil.Process(pid)
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                        logger.info(f"Successfully terminated old process {pid}")
                    except psutil.TimeoutExpired:
                        process.kill()
                        logger.info(f"Force killed old process {pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.error(f"Error terminating old process {pid}: {e}")

            # Clean up any stale tracking file
            tracking_file = f"monitor_process_{user_id}.json"
            if os.path.exists(tracking_file):
                try:
                    os.remove(tracking_file)
                    logger.info(f"Removed stale tracking file: {tracking_file}")
                except OSError as e:
                    logger.error(f"Error removing tracking file: {e}")

        except Exception as e:
            logger.error(f"Error during monitor cleanup: {e}")

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

            # Send as plain text instead of embed if permissions are limited
            message = "Your Keywords:\n"
            for word, enabled in keywords:
                message += f"• {word}: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
            await ctx.send(message)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to send rich messages. Please give me 'Embed Links' permission or contact an admin.")
        except Exception as e:
            logger.error(f"Error in keywords command: {e}")
            await ctx.send("❌ Error listing keywords. Please try again.")

    @commands.command(name='add_keyword', help="Add a keyword to monitor")
    async def add_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_add_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM keyword WHERE user_id = %s AND word = %s;',
                (user_id, keyword)
            )
            if cur.fetchone():
                return "⚠️ Keyword already exists."

            cur.execute(
                'INSERT INTO keyword (user_id, word, enabled) VALUES (%s, %s, true);',
                (user_id, keyword)
            )
            conn.commit()
            return f"✅ Added keyword: `{keyword}`"

        result = await self._handle_db_operation(db_add_keyword)
        await ctx.send(result or "❌ Error adding keyword.")

    @commands.command(name='remove_keyword', help="Remove a keyword from your monitor")
    async def remove_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_remove_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM keyword WHERE user_id = %s AND word = %s RETURNING word;',
                (user_id, keyword)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed keyword: `{keyword}`"
            else:
                return "⚠️ Keyword not found."

        result = await self._handle_db_operation(db_remove_keyword)
        await ctx.send(result or "❌ Error removing keyword.")

    @commands.command(name='preset_stores', help="Show and enable preset stores to monitor")
    async def preset_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_preset_stores(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
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
            return (stores_added, len(preset_stores))

        result = await self._handle_db_operation(db_preset_stores)
        if not result:
            await ctx.send("❌ Error adding preset stores.")
            return
        stores_added, total_stores = result

        embed = discord.Embed(
            title="Preset Stores Added",
            description=f"Added {stores_added} new preset stores to your monitor.",
            color=discord.Color.green()
        )
        embed.add_field(name="Total Preset Stores", value=str(total_stores))
        await ctx.send(embed=embed)

    @commands.command(name='add_store', help="Add a store URL to monitor")
    async def add_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return
        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_add_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM store WHERE user_id = %s AND url = %s;',
                (user_id, store_url)
            )
            if cur.fetchone():
                return "⚠️ Store already exists."

            cur.execute(
                'INSERT INTO store (user_id, url, enabled) VALUES (%s, %s, true);',
                (user_id, store_url)
            )
            conn.commit()
            return f"✅ Added store: `{store_url}`"

        result = await self._handle_db_operation(db_add_store)
        await ctx.send(result or "❌ Error adding store.")

    @commands.command(name='list_stores', help="List all your active stores")
    async def list_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_list_stores(conn, cur):
            cur.execute(
                '''SELECT s.url, s.enabled 
                FROM store s 
                JOIN "user" u ON s.user_id = u.id 
                WHERE u.discord_user_id = %s;''',
                (str(ctx.author.id),)
            )
            return cur.fetchall()

        stores = await self._handle_db_operation(db_list_stores)
        if not stores:
            await ctx.send("No stores found. Add some using `!add_store <url>` or `!preset_stores`")
            return

        # Prepare a plain text message
        enabled_stores = []
        disabled_stores = []
        for url, enabled in stores:
            if enabled:
                enabled_stores.append(url)
            else:
                disabled_stores.append(url)

        message = "Your Monitored Stores:\n\n"
        if enabled_stores:
            message += "✅ Active Stores:\n"
            message += "\n".join(f"• {url}" for url in enabled_stores)
            message += "\n\n"
        if disabled_stores:
            message += "❌ Disabled Stores:\n"
            message += "\n".join(f"• {url}" for url in disabled_stores)

        message += "\nUse !add_store to add more stores or !preset_stores to add preset stores"

        try:
            # Try sending in the current channel
            await ctx.send(message)
        except discord.Forbidden:
            try:
                # If that fails, try DMing the user
                await ctx.author.send(message)
                if isinstance(ctx.channel, discord.TextChannel):  # Only send this if in a server channel
                    await ctx.send("📨 Store list sent via DM!")
            except discord.Forbidden:
                await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.")

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
                cur.execute(
                    'SELECT id FROM "user" WHERE discord_user_id = %s;',
                    (str(ctx.author.id),)
                )
                result = cur.fetchone()
                if not result:
                    return None
                user_id = result[0]

                cur.execute(
                    'UPDATE "user" SET discord_webhook_url = %s WHERE id = %s;',
                    (webhook_url, user_id)
                )
                conn.commit()
                return "✅ Webhook URL set!"

            result = await self._handle_db_operation(db_set_webhook)
            await ctx.send(result or "❌ Error setting webhook.")

        except asyncio.TimeoutError:
            await ctx.send("Webhook setup timed out. Please try again.")

    @commands.command(name='remove_store', help="Remove a store URL from your monitor")
    async def remove_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return

        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_remove_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM store WHERE user_id = %s AND url = %s RETURNING url;',
                (user_id, store_url)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed store: `{store_url}`"
            else:
                return "⚠️ Store not found in your list."

        result = await self._handle_db_operation(db_remove_store)
        await ctx.send(result or "❌ Error removing store.")


    async def _cleanup_old_monitor(self, user_id):
        """Cleanup any existing monitor process for the user"""
        try:
            pid = await self._get_monitor_pid(user_id)
            if pid:
                try:
                    process = psutil.Process(pid)
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                        logger.info(f"Successfully terminated old process {pid}")
                    except psutil.TimeoutExpired:
                        process.kill()
                        logger.info(f"Force killed old process {pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.error(f"Error terminating old process {pid}: {e}")

            # Clean up any stale tracking file
            tracking_file = f"monitor_process_{user_id}.json"
            if os.path.exists(tracking_file):
                try:
                    os.remove(tracking_file)
                    logger.info(f"Removed stale tracking file: {tracking_file}")
                except OSError as e:
                    logger.error(f"Error removing tracking file: {e}")

        except Exception as e:
            logger.error(f"Error during monitor cleanup: {e}")

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

            # Send as plain text instead of embed if permissions are limited
            message = "Your Keywords:\n"
            for word, enabled in keywords:
                message += f"• {word}: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
            await ctx.send(message)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to send rich messages. Please give me 'Embed Links' permission or contact an admin.")
        except Exception as e:
            logger.error(f"Error in keywords command: {e}")
            await ctx.send("❌ Error listing keywords. Please try again.")

    @commands.command(name='add_keyword', help="Add a keyword to monitor")
    async def add_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_add_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM keyword WHERE user_id = %s AND word = %s;',
                (user_id, keyword)
            )
            if cur.fetchone():
                return "⚠️ Keyword already exists."

            cur.execute(
                'INSERT INTO keyword (user_id, word, enabled) VALUES (%s, %s, true);',
                (user_id, keyword)
            )
            conn.commit()
            return f"✅ Added keyword: `{keyword}`"

        result = await self._handle_db_operation(db_add_keyword)
        await ctx.send(result or "❌ Error adding keyword.")

    @commands.command(name='remove_keyword', help="Remove a keyword from your monitor")
    async def remove_keyword(self, ctx, *, keyword: str):
        if not await self._check_cooldown(ctx):
            return

        async def db_remove_keyword(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM keyword WHERE user_id = %s AND word = %s RETURNING word;',
                (user_id, keyword)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed keyword: `{keyword}`"
            else:
                return "⚠️ Keyword not found."

        result = await self._handle_db_operation(db_remove_keyword)
        await ctx.send(result or "❌ Error removing keyword.")

    @commands.command(name='preset_stores', help="Show and enable preset stores to monitor")
    async def preset_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_preset_stores(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
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
            return (stores_added, len(preset_stores))

        result = await self._handle_db_operation(db_preset_stores)
        if not result:
            await ctx.send("❌ Error adding preset stores.")
            return
        stores_added, total_stores = result

        embed = discord.Embed(
            title="Preset Stores Added",
            description=f"Added {stores_added} new preset stores to your monitor.",
            color=discord.Color.green()
        )
        embed.add_field(name="Total Preset Stores", value=str(total_stores))
        await ctx.send(embed=embed)

    @commands.command(name='add_store', help="Add a store URL to monitor")
    async def add_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return
        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_add_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'SELECT 1 FROM store WHERE user_id = %s AND url = %s;',
                (user_id, store_url)
            )
            if cur.fetchone():
                return "⚠️ Store already exists."

            cur.execute(
                'INSERT INTO store (user_id, url, enabled) VALUES (%s, %s, true);',
                (user_id, store_url)
            )
            conn.commit()
            return f"✅ Added store: `{store_url}`"

        result = await self._handle_db_operation(db_add_store)
        await ctx.send(result or "❌ Error adding store.")

    @commands.command(name='list_stores', help="List all your active stores")
    async def list_stores(self, ctx):
        if not await self._check_cooldown(ctx):
            return

        async def db_list_stores(conn, cur):
            cur.execute(
                '''SELECT s.url, s.enabled 
                FROM store s 
                JOIN "user" u ON s.user_id = u.id 
                WHERE u.discord_user_id = %s;''',
                (str(ctx.author.id),)
            )
            return cur.fetchall()

        stores = await self._handle_db_operation(db_list_stores)
        if not stores:
            await ctx.send("No stores found. Add some using `!add_store <url>` or `!preset_stores`")
            return

        # Prepare a plain text message
        enabled_stores = []
        disabled_stores = []
        for url, enabled in stores:
            if enabled:
                enabled_stores.append(url)
            else:
                disabled_stores.append(url)

        message = "Your Monitored Stores:\n\n"
        if enabled_stores:
            message += "✅ Active Stores:\n"
            message += "\n".join(f"• {url}" for url in enabled_stores)
            message += "\n\n"
        if disabled_stores:
            message += "❌ Disabled Stores:\n"
            message += "\n".join(f"• {url}" for url in disabled_stores)

        message += "\nUse !add_store to add more stores or !preset_stores to add preset stores"

        try:
            # Try sending in the current channel
            await ctx.send(message)
        except discord.Forbidden:
            try:
                # If that fails, try DMing the user
                await ctx.author.send(message)
                if isinstance(ctx.channel, discord.TextChannel):  # Only send this if in a server channel
                    await ctx.send("📨 Store list sent via DM!")
            except discord.Forbidden:
                await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.")

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
                cur.execute(
                    'SELECT id FROM "user" WHERE discord_user_id = %s;',
                    (str(ctx.author.id),)
                )
                result = cur.fetchone()
                if not result:
                    return None
                user_id = result[0]

                cur.execute(
                    'UPDATE "user" SET discord_webhook_url = %s WHERE id = %s;',
                    (webhook_url, user_id)
                )
                conn.commit()
                return "✅ Webhook URL set!"

            result = await self._handle_db_operation(db_set_webhook)
            await ctx.send(result or "❌ Error setting webhook.")

        except asyncio.TimeoutError:
            await ctx.send("Webhook setup timed out. Please try again.")

    @commands.command(name='remove_store', help="Remove a store URL from your monitor")
    async def remove_store(self, ctx, *, store_url: str):
        if not await self._check_cooldown(ctx):
            return

        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url

        async def db_remove_store(conn, cur):
            cur.execute(
                'SELECT id FROM "user" WHERE discord_user_id = %s;',
                (str(ctx.author.id),)
            )
            result = cur.fetchone()
            if not result:
                return None
            user_id = result[0]

            cur.execute(
                'DELETE FROM store WHERE user_id = %s AND url = %s RETURNING url;',
                (user_id, store_url)
            )
            deleted = cur.fetchone()
            if deleted:
                conn.commit()
                return f"✅ Removed store: `{store_url}`"
            else:
                return "⚠️ Store not found in your list."

        result = await self._handle_db_operation(db_remove_store)
        await ctx.send(result or "❌ Error removing store.")


    async def _cleanup_old_monitor(self, user_id):
        """Cleanup any existing monitor process for the user"""
        try:
            pid = await self._get_monitor_pid(user_id)
            if pid:
                try:
                    process = psutil.Process(pid)
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                        logger.info(f"Successfully terminated old process {pid}")
                    except psutil.TimeoutExpired:
                        process.kill()
                        logger.info(f"Force killed old process {pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.error(f"Error terminating old process {pid}: {e}")

            # Clean up any stale tracking file
            tracking_file = f"monitor_process_{user_id}.json"
            if os.path.exists(tracking_file):
                try:
                    os.remove(tracking_file)
                    logger.info(f"Removed stale tracking file: {tracking_file}")
                except OSError as e:
                    logger.error(f"Error removing tracking file: {e}")

        except Exception as e:
            logger.error(f"Error during monitor cleanup: {e}")

async def setup(bot):
    await bot.add_cog(MonitorCommands(bot))
    logger.info("Monitor commands loaded")