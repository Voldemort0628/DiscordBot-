import discord
from discord.ext import commands
import logging
import psycopg2
import os
import sys
import psutil
import time
from datetime import datetime

logger = logging.getLogger('MonitorCommands')

class MonitorCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._command_cooldowns = {}

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

    @commands.command(name='verify')
    async def verify_user(self, ctx):
        """Verify yourself to use the monitor"""
        if not await self._check_cooldown(ctx):
            return

        async def db_verify(conn, cur):
            # Check existing user
            cur.execute('SELECT username FROM "user" WHERE discord_user_id = %s', (str(ctx.author.id),))
            if cur.fetchone():
                return "✅ Your account is already verified!"

            # Create new user
            username = f"discord_{ctx.author.name}"
            cur.execute(
                'INSERT INTO "user" (username, discord_user_id, enabled) VALUES (%s, %s, true) RETURNING id',
                (username, str(ctx.author.id))
            )
            user_id = cur.fetchone()[0]

            # Create monitor config
            cur.execute(
                '''INSERT INTO monitor_config (
                    user_id, rate_limit, monitor_delay, max_products,
                    min_cycle_delay, success_delay_multiplier, batch_size, initial_product_limit
                ) VALUES (%s, 1.0, 30, 250, 0.05, 0.25, 20, 150)''',
                (user_id,)
            )
            conn.commit()
            return "✅ Verification successful! You can now use monitor commands."

        result = await self._handle_db_operation(db_verify)
        await ctx.send(result or "❌ Error during verification")

    @commands.command(name='status')
    async def check_status(self, ctx):
        """Check your monitor status"""
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
        embed = discord.Embed(
            title="Monitor Status",
            description="✅ Running" if running else "❌ Stopped",
            color=discord.Color.green() if running else discord.Color.red()
        )
        await ctx.send(embed=embed)

    def _is_monitor_running(self, user_id):
        """Check if monitor is running for user"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    if ('python' in proc.info['name'] and 
                        'main.py' in cmdline and 
                        f"MONITOR_USER_ID={user_id}" in cmdline):
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return False
        except Exception as e:
            logger.error(f"Error checking monitor status: {e}")
            return False

    @commands.command(name='start')
    async def start_monitor(self, ctx):
        """Start your monitor"""
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
            user_id, custom_webhook = result

            cur.execute(
                'SELECT COUNT(*) FROM store WHERE user_id = %s AND enabled = true;',
                (user_id,)
            )
            store_count = cur.fetchone()[0]
            if store_count == 0:
                return "❌ You need to add some stores first!"

            if self._is_monitor_running(user_id):
                return "Monitor is already running!"

            webhook_url = custom_webhook if custom_webhook else os.environ.get('DISCORD_WEBHOOK_URL')
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
        user_id, webhook_url, store_count = result

        status_message = await ctx.send("⌛ Starting monitor, please wait...")
        start_script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'start_monitor.py')
        process_env = os.environ.copy()
        process_env['DISCORD_WEBHOOK_URL'] = webhook_url
        process_env['MONITOR_USER_ID'] = str(user_id)
        process = subprocess.Popen(
            [sys.executable, start_script, str(user_id)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=process_env
        )

        max_retries = 3
        for retry in range(max_retries):
            await asyncio.sleep(2)
            if self._is_monitor_running(user_id):
                webhook_type = "custom" if custom_webhook else "default"
                success_msg = [
                    "✅ Monitor started successfully!",
                    f"Using {webhook_type} webhook for notifications.",
                    f"Monitoring {store_count} store{'s' if store_count != 1 else ''}.",
                    "Use !status to check monitor status."
                ]
                await status_message.edit(content="\n".join(success_msg))
                return
            elif retry < max_retries - 1:
                await status_message.edit(content=f"⌛ Starting monitor (attempt {retry + 1}/{max_retries})...")

        await status_message.edit(content="❌ Failed to start monitor. Please try again later.")


    @commands.command(name='stop')
    async def stop_monitor(self, ctx):
        """Stop your monitor"""
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

        stopped = False
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

        async def db_update_enabled(conn, cur):
            cur.execute(
                'UPDATE "user" SET enabled = false WHERE id = %s;',
                (user_id,)
            )
            conn.commit()
            return True

        await self._handle_db_operation(db_update_enabled)

        if stopped:
            await ctx.send("✅ Monitor stopped successfully!")
        else:
            await ctx.send("Monitor was not running.")

    @commands.command(name='keywords')
    async def list_keywords(self, ctx):
        """List your keywords"""
        if not await self._check_cooldown(ctx):
            return

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

    @commands.command(name='add_keyword')
    async def add_keyword(self, ctx, *, keyword: str):
        """Add a keyword to monitor"""
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

    @commands.command(name='remove_keyword')
    async def remove_keyword(self, ctx, *, keyword: str):
        """Remove a keyword from your monitor"""
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

    @commands.command(name='preset_stores')
    async def preset_stores(self, ctx):
        """Show and enable preset stores to monitor"""
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


    @commands.command(name='add_store')
    async def add_store(self, ctx, *, store_url: str):
        """Add a store URL to monitor"""
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


    @commands.command(name='list_stores')
    async def list_stores(self, ctx):
        """List all your active stores"""
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

        embed = discord.Embed(
            title="Your Monitored Stores",
            color=discord.Color.blue()
        )

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
        await ctx.send(embed=embed)

    @commands.command(name='set_webhook')
    async def set_webhook(self, ctx):
        """Set your custom Discord webhook URL (via DM only)"""
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

async def setup(bot):
    await bot.add_cog(MonitorCommands(bot))
    logger.info("Monitor commands cog loaded")