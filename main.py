import discord
from discord.ext import commands
import asyncio
import logging
import os
import sys
from pathlib import Path
import aiosqlite
import signal

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config.settings import Settings
from utils.db import DatabaseManager
from utils.admin import AdminManager
from utils.ticket_manager import TicketManager
from utils.logging_manager import LoggingManager
from utils.workflow_manager import WorkflowManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)

logger = logging.getLogger(__name__)

# Global flag to prevent shutdown
SHUTDOWN_REQUESTED = False

class DiscordBot(commands.Bot):
    def __init__(self):
        # Configure intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.reactions = True
        intents.voice_states = True
        
        super().__init__(
            command_prefix=Settings.PREFIX,
            intents=intents,
            help_command=None,
            case_insensitive=True
        )
        
        # Initialize managers
        self.db = None
        self.admin_manager = None
        self.ticket_manager = None
        self.logging_manager = None
        self.workflow_manager = None
        self.meeting_manager = None
        self.startup_complete = False
        
        # Add admin commands
        self.add_admin_commands()
    
    def add_admin_commands(self):
        """Add admin-only commands"""
        
        @self.command(name='admin_sync')
        @commands.is_owner()
        async def admin_sync(ctx):
            """Sync slash commands (Owner only)"""
            try:
                synced = await self.tree.sync()
                await ctx.send(f"✅ Synced {len(synced)} commands")
                logger.info(f"Admin sync: {len(synced)} commands synced")
            except Exception as e:
                await ctx.send(f"❌ Sync failed: {e}")
                logger.error(f"Admin sync failed: {e}")
        
        @self.command(name='force_sync')
        @commands.is_owner()
        async def force_sync(ctx):
            """Force sync all commands (Owner only)"""
            try:
                await ctx.send("🔄 Starting force sync...")
                
                # Clear existing commands
                self.tree.clear_commands()
                await ctx.send("🗑️ Cleared existing commands")
                
                # Reload all cogs
                for cog_name in list(self.cogs.keys()):
                    try:
                        await self.reload_extension(f"cogs.{cog_name.lower()}")
                        await ctx.send(f"🔄 Reloaded {cog_name}")
                    except Exception as e:
                        await ctx.send(f"❌ Failed to reload {cog_name}: {e}")
                
                # Sync commands
                synced = await self.tree.sync()
                await ctx.send(f"✅ Force sync complete: {len(synced)} commands synced")
                
                # List synced commands
                command_names = [cmd.name for cmd in synced]
                if command_names:
                    commands_text = ", ".join(command_names)
                    if len(commands_text) > 1900:
                        commands_text = commands_text[:1900] + "..."
                    await ctx.send(f"📋 Synced commands: {commands_text}")
                
            except Exception as e:
                await ctx.send(f"❌ Force sync failed: {e}")
                logger.error(f"Force sync failed: {e}")
    
        @self.command(name='emergency_sync')
        @commands.is_owner()
        async def emergency_sync(ctx):
            """Emergency command sync with detailed output (Owner only)"""
            try:
                await ctx.send("🔄 Starting emergency sync...")
            
                # Get current commands
                current_commands = self.tree.get_commands()
                await ctx.send(f"📊 Current commands in tree: {len(current_commands)}")
            
                # List cogs and their commands
                cog_info = []
                total_cog_commands = 0
            
                for cog_name, cog in self.cogs.items():
                    cog_commands = cog.get_app_commands()
                    total_cog_commands += len(cog_commands)
                    cog_info.append(f"• {cog_name}: {len(cog_commands)} commands")
            
                if cog_info:
                    cog_text = "\n".join(cog_info)
                    if len(cog_text) > 1900:
                        cog_text = cog_text[:1900] + "..."
                    await ctx.send(f"📦 Cog commands:\n```\n{cog_text}\n```")
            
                await ctx.send(f"🔢 Total commands from cogs: {total_cog_commands}")
            
                # Sync
                synced = await self.tree.sync()
                await ctx.send(f"✅ Emergency sync complete: {len(synced)} commands synced")
            
            except Exception as e:
                await ctx.send(f"❌ Emergency sync failed: {e}")
                logger.error(f"Emergency sync failed: {e}")
    
    async def setup_hook(self):
        """Called when the bot is starting up"""
        logger.info("🤖 Starting Discord bot setup...")
        
        # Set startup as complete early to prevent shutdown
        self.startup_complete = True
        
        try:
            # Initialize database with shorter timeout
            logger.info("📊 Initializing database...")
            try:
                async with asyncio.timeout(30):  # Reduced from 60 to 30 seconds
                    self.db = DatabaseManager()
                    await self.db.init_database()
                    logger.info("✅ Database initialized successfully")
            except asyncio.TimeoutError:
                logger.error("❌ Database initialization timed out after 30 seconds")
                logger.info("🔄 Attempting minimal SQLite fallback...")
                # Quick SQLite fallback
                try:
                    self.db = DatabaseManager()
                    self.db.connection = await aiosqlite.connect("bot.db")
                    self.db.is_postgresql = False
                    # Create minimal tables only
                    await self.db.connection.execute("""
                        CREATE TABLE IF NOT EXISTS users (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            discord_id TEXT UNIQUE NOT NULL,
                            username TEXT NOT NULL
                        )
                    """)
                    await self.db.connection.execute("""
                        CREATE TABLE IF NOT EXISTS user_data (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id TEXT NOT NULL,
                            guild_id TEXT,
                            data_type TEXT NOT NULL,
                            data_content TEXT DEFAULT '{}',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(user_id, data_type)
                        )
                    """)
                    await self.db.connection.commit()
                    logger.info("✅ Minimal SQLite database ready")
                except Exception as e:
                    logger.error(f"❌ Fallback database failed: {e}")
                    logger.info("🚀 Continuing without database...")
                    self.db = None
            except Exception as e:
                logger.error(f"❌ Database initialization failed: {e}")
                logger.info("🚀 Continuing without database...")
                self.db = None
        
            # Verify database tables with shorter timeout (optional)
            if self.db:
                logger.info("🔍 Verifying database tables...")
                try:
                    async with asyncio.timeout(10):  # Reduced from 20 to 10 seconds
                        tables_ok = await self.db.verify_tables()
                        if not tables_ok:
                            logger.warning("⚠️ Some database tables missing - continuing anyway")
                        else:
                            logger.info("✅ Database tables verified successfully")
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"⚠️ Database table verification failed/timed out: {e} - continuing anyway")
        
            # Test database connection (optional)
            if self.db:
                logger.info("🧪 Testing database connection...")
                try:
                    async with asyncio.timeout(5):  # Reduced from 10 to 5 seconds
                        connection_ok = await self.db.test_connection()
                        if connection_ok:
                            logger.info("✅ Database connection test passed")
                        else:
                            logger.warning("⚠️ Database connection test failed - continuing anyway")
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"⚠️ Database connection test failed/timed out: {e} - continuing anyway")
        
            # Initialize managers with shorter timeout (optional)
            logger.info("🛡️ Initializing managers...")
            try:
                async with asyncio.timeout(10):  # Reduced from 20 to 10 seconds
                    if self.db:
                        # Admin manager
                        logger.info("  • Initializing Admin Manager...")
                        self.admin_manager = AdminManager(self)
                        await self.admin_manager.load_admin_roles()
                        logger.info("  ✅ Admin Manager initialized")
                    
                        # Ticket manager
                        logger.info("  • Initializing Ticket Manager...")
                        self.ticket_manager = TicketManager(self)
                        await self.ticket_manager.load_ticket_configs()
                        logger.info("  ✅ Ticket Manager initialized")
                    
                        # Logging manager
                        logger.info("  • Initializing Logging Manager...")
                        self.logging_manager = LoggingManager(self)
                        await self.logging_manager.load_log_configs()
                        logger.info("  ✅ Logging Manager initialized")
                    
                        # Workflow manager
                        logger.info("  • Initializing Workflow Manager...")
                        self.workflow_manager = WorkflowManager(self)
                        await self.workflow_manager.load_workflows()
                        logger.info("  ✅ Workflow Manager initialized")
                    else:
                        logger.warning("⚠️ Skipping manager initialization (no database)")
                
                logger.info("✅ Manager initialization completed")
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning(f"⚠️ Manager initialization failed/timed out: {e} - continuing without managers")
                # Set managers to None to prevent errors
                self.admin_manager = None
                self.ticket_manager = None
                self.logging_manager = None
                self.workflow_manager = None

            # Load cogs with shorter timeout
            logger.info("🔧 Loading cogs...")
            try:
                async with asyncio.timeout(20):  # Reduced from 30 to 20 seconds
                    await self.load_cogs()
                    logger.info("✅ Cogs loaded successfully")
            except asyncio.TimeoutError:
                logger.warning("⚠️ Cog loading timed out after 20 seconds - continuing with loaded cogs")
            except Exception as e:
                logger.warning(f"⚠️ Cog loading failed: {e} - continuing with loaded cogs")

            # Verify commands are registered
            logger.info("🔍 Verifying command registration...")
            total_commands = 0

            for cog_name, cog in self.cogs.items():
                cog_commands = cog.get_app_commands()
                total_commands += len(cog_commands)
                logger.info(f"  • {cog_name}: {len(cog_commands)} commands")

            logger.info(f"📊 Total commands from cogs: {total_commands}")
            tree_commands = len(self.tree.get_commands())
            logger.info(f"📊 Commands in tree: {tree_commands}")

            # List all commands in tree for debugging
            tree_command_names = [cmd.name for cmd in self.tree.get_commands()]
            logger.info(f"Tree commands: {tree_command_names}")

            # Force sync commands on startup
            logger.info("🔄 Force syncing slash commands...")
            try:
                async with asyncio.timeout(20):  # Increased timeout for sync
                    synced = await self.tree.sync()
                    logger.info(f"✅ Force synced {len(synced)} slash commands")
                    
                    # Log synced command names
                    synced_names = [cmd.name for cmd in synced]
                    logger.info(f"Synced commands: {synced_names}")
                    
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning(f"⚠️ Command sync failed/timed out: {e} - commands will sync later")

            logger.info("✅ Bot setup completed successfully!")

        except Exception as e:
            logger.error(f"❌ Error during setup: {e}")
            logger.exception("Full traceback:")
            # Don't close the bot, just log the error and continue
            logger.info("🚀 Continuing bot startup despite setup errors...")
    
    async def load_cogs(self):
        """Load all cogs"""
        cogs = [
            'cogs.admin',
            'cogs.help',
            'cogs.setup',
            'cogs.tickets',
            'cogs.reminders',
            'cogs.workflows',
            'cogs.roles',
            'cogs.meetings',
            'cogs.notifications',
            'cogs.logging',
            'cogs.privacy',
            'cogs.conversations',
            'cogs.intelligence',
            'cogs.integrations_google',
            'cogs.integrations_notion',
            'cogs.integrations_trello',
            'cogs.integrations_github'
        ]
        
        loaded_count = 0
        failed_count = 0
        
        for cog in cogs:
            try:
                logger.info(f"  • Loading {cog}...")
                async with asyncio.timeout(5):  # 5 second timeout per cog
                    await self.load_extension(cog)
                    loaded_count += 1
                    logger.info(f"  ✅ Loaded {cog}")
            except asyncio.TimeoutError:
                failed_count += 1
                logger.error(f"  ❌ {cog} timed out after 5 seconds")
            except Exception as e:
                failed_count += 1
                logger.error(f"  ❌ Failed to load {cog}: {e}")
    
        logger.info(f"📦 Loaded {loaded_count}/{len(cogs)} cogs successfully")
        if failed_count > 0:
            logger.warning(f"⚠️ {failed_count} cogs failed to load")
    
    async def on_ready(self):
        """Called when the bot is ready"""
        logger.info(f"🚀 {self.user} is now online!")
        logger.info(f"📊 Connected to {len(self.guilds)} guilds")
        logger.info(f"👥 Serving {sum(guild.member_count for guild in self.guilds)} users")
        logger.info(f"⚡ {len(self.tree.get_commands())} slash commands available")
        
        # If startup wasn't complete, try to sync commands now
        if not self.startup_complete:
            logger.info("🔄 Startup was incomplete, attempting command sync now...")
            try:
                synced = await self.tree.sync()
                logger.info(f"✅ Late sync completed: {len(synced)} commands")
                self.startup_complete = True
            except Exception as e:
                logger.warning(f"⚠️ Late sync failed: {e}")
        
        # Set bot status
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | /help"
            )
            await self.change_presence(activity=activity, status=discord.Status.online)
        except Exception as e:
            logger.error(f"Failed to set bot status: {e}")
    
    async def on_guild_join(self, guild):
        """Called when the bot joins a new guild"""
        logger.info(f"📥 Joined new guild: {guild.name} (ID: {guild.id}) with {guild.member_count} members")
        
        # Update status
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | /help"
            )
            await self.change_presence(activity=activity)
        except Exception as e:
            logger.error(f"Failed to update status: {e}")
        
        # Send welcome message if possible
        try:
            if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                embed = discord.Embed(
                    title="👋 Thanks for adding me!",
                    description="I'm a powerful Discord bot with many features to help manage your server.",
                    color=0x5865F2
                )
                embed.add_field(
                    name="🚀 Getting Started",
                    value="Use `/help` to see all available commands\nUse `/ticket-system-setup` to configure the ticket system",
                    inline=False
                )
                embed.add_field(
                    name="🔧 Admin Setup",
                    value="Use `/add-admin-role` to give roles admin access to bot commands",
                    inline=False
                )
                embed.set_footer(text="Powered by Railway 🚄")
                
                await guild.system_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to send welcome message to {guild.name}: {e}")
    
    async def on_guild_remove(self, guild):
        """Called when the bot leaves a guild"""
        logger.info(f"📤 Left guild: {guild.name} (ID: {guild.id})")
        
        # Update status
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | /help"
            )
            await self.change_presence(activity=activity)
        except Exception as e:
            logger.error(f"Failed to update status: {e}")
    
    async def on_message(self, message):
        """Handle incoming messages"""
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Process workflow triggers
        if self.workflow_manager and message.guild:
            try:
                await self.workflow_manager.check_message_triggers(message)
            except Exception as e:
                logger.error(f"Error processing workflow triggers: {e}")
        
        # Process commands
        await self.process_commands(message)
    
    async def on_member_join(self, member):
        """Handle member join events"""
        logger.info(f"👤 {member} joined {member.guild.name}")
        
        # Process workflow triggers
        if self.workflow_manager:
            try:
                await self.workflow_manager.check_member_join_triggers(member)
            except Exception as e:
                logger.error(f"Error processing member join workflow triggers: {e}")
        
        # Log the event
        if self.logging_manager:
            try:
                await self.logging_manager.log_member_join(member)
            except Exception as e:
                logger.error(f"Error logging member join: {e}")
    
    async def on_member_remove(self, member):
        """Handle member leave events"""
        logger.info(f"👤 {member} left {member.guild.name}")
        
        # Log the event
        if self.logging_manager:
            try:
                await self.logging_manager.log_member_leave(member)
            except Exception as e:
                logger.error(f"Error logging member leave: {e}")
    
    async def on_thread_create(self, thread):
        """Handle thread creation events"""
        logger.info(f"🧵 Thread created: {thread.name} in {thread.guild.name}")
        
        # Process workflow triggers
        if self.workflow_manager:
            try:
                await self.workflow_manager.check_thread_create_triggers(thread)
            except Exception as e:
                logger.error(f"Error processing thread create workflow triggers: {e}")
    
    async def on_guild_channel_create(self, channel):
        """Handle channel creation events"""
        logger.info(f"📝 Channel created: {channel.name} in {channel.guild.name}")
        
        # Process workflow triggers
        if self.workflow_manager:
            try:
                await self.workflow_manager.check_channel_create_triggers(channel)
            except Exception as e:
                logger.error(f"Error processing channel create workflow triggers: {e}")
    
    async def on_command_error(self, ctx, error):
        """Global error handler for prefix commands"""
        if isinstance(error, commands.CommandNotFound):
            return  # Ignore unknown commands
        
        if isinstance(error, commands.NotOwner):
            await ctx.send("❌ This command is restricted to the bot owner.")
            return
        
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command.")
            return
        
        logger.error(f"Command error in {ctx.command}: {error}")
        
        try:
            embed = discord.Embed(
                title="❌ Command Error",
                description=f"An error occurred: {str(error)}",
                color=0xFF0000
            )
            await ctx.send(embed=embed)
        except:
            pass  # Ignore if we can't send the error message
    
    async def on_app_command_error(self, interaction: discord.Interaction, error):
        """Global error handler for slash commands"""
        logger.error(f"Slash command error in {interaction.command}: {error}")
        
        try:
            embed = discord.Embed(
                title="❌ Command Error",
                description=f"An error occurred: {str(error)}",
                color=0xFF0000
            )
            
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")
    
    async def close(self):
        """Clean shutdown"""
        global SHUTDOWN_REQUESTED
        
        # Only close if shutdown was requested
        if not SHUTDOWN_REQUESTED:
            logger.warning("🛑 Shutdown attempted but SHUTDOWN_REQUESTED is False - ignoring")
            return
            
        logger.info("🔄 Shutting down bot...")
        
        # Close database connection
        if self.db:
            await self.db.close()
        
        # Close the bot
        await super().close()
        logger.info("✅ Bot shutdown complete")

# Signal handlers
def handle_sigterm(signum, frame):
    global SHUTDOWN_REQUESTED
    logger.info("🛑 Received SIGTERM signal")
    SHUTDOWN_REQUESTED = True

def handle_sigint(signum, frame):
    global SHUTDOWN_REQUESTED
    logger.info("🛑 Received SIGINT signal")
    SHUTDOWN_REQUESTED = True

async def main():
    """Main function to run the bot"""
    global SHUTDOWN_REQUESTED
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigint)
    
    logger.info("🚀 Starting Discord Bot...")
    
    # Validate environment variables
    try:
        Settings.validate_required_env_vars()
        logger.info("✅ Environment variables validated")
    except ValueError as e:
        logger.error(f"❌ Environment validation failed: {e}")
        return
    
    # Create bot
    bot = DiscordBot()
    
    # Start the bot without timeout
    try:
        logger.info("🔄 Starting bot (no timeout)...")
        await bot.start(Settings.DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.error("❌ Invalid Discord token")
        SHUTDOWN_REQUESTED = True
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        logger.exception("Full traceback:")
    finally:
        # Only close if shutdown was requested
        if SHUTDOWN_REQUESTED and not bot.is_closed():
            logger.info("🔄 Performing final shutdown...")
            await bot.close()

if __name__ == "__main__":
    try:
        # Check Python version
        if sys.version_info < (3, 8):
            logger.error("❌ Python 3.8 or higher is required")
            sys.exit(1)
        
        # Run the bot
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
        SHUTDOWN_REQUESTED = True
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)
