import discord
from discord.ext import commands
import asyncio
import logging
import os
import sys
from pathlib import Path
import signal
import traceback

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config.settings import Settings
from utils.db import DatabaseManager
from utils.admin import AdminManager
from utils.logging_manager import LoggingManager
from utils.ticket_manager import TicketManager

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
        self.logging_manager = None
        self.ticket_manager = None
        self.startup_complete = False
        
        # Add error handlers
        self._setup_error_handlers()
    
    def _setup_error_handlers(self):
        """Set up global error handlers"""
        # Set up asyncio exception handler
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(self._handle_asyncio_exception)
    
    def _handle_asyncio_exception(self, loop, context):
        """Handle uncaught exceptions in the event loop"""
        exception = context.get('exception')
        if exception:
            logger.error(f"Uncaught exception in event loop: {exception}")
            logger.error(f"Context: {context}")
            traceback.print_exception(type(exception), exception, exception.__traceback__)
        else:
            logger.error(f"Asyncio error: {context.get('message')}")
            logger.error(f"Context: {context}")
    
    async def setup_hook(self):
        """Called when the bot is starting up"""
        logger.info("🤖 Starting Discord bot setup...")
        
        try:
            # Initialize database with timeout
            logger.info("📊 Initializing database...")
            self.db = DatabaseManager()
            try:
                # Set a timeout for database initialization
                await asyncio.wait_for(self.db.init_database(), timeout=30.0)
                logger.info("✅ Database initialized successfully")
            except asyncio.TimeoutError:
                logger.error("❌ Database initialization timed out")
                raise TimeoutError("Database initialization timed out after 30 seconds")
        
            # Initialize managers with timeouts
            logger.info("🛡️ Initializing managers...")
            if self.db:
                # Admin manager
                self.admin_manager = AdminManager(self)
                await asyncio.wait_for(self.admin_manager.load_admin_roles(), timeout=10.0)
                
                # Logging manager
                self.logging_manager = LoggingManager(self)
                await asyncio.wait_for(self.logging_manager.load_log_configs(), timeout=10.0)
                
                # Ticket manager
                self.ticket_manager = TicketManager(self)
                logger.info("✅ Managers initialized")

            # Load cogs with timeout
            logger.info("🔧 Loading cogs...")
            await asyncio.wait_for(self.load_cogs(), timeout=30.0)
            logger.info("✅ Cogs loaded successfully")

            self.startup_complete = True
            logger.info("✅ Bot setup completed successfully!")

        except Exception as e:
            logger.error(f"❌ Error during setup: {e}")
            logger.exception("Full traceback:")
            # Don't raise the exception - allow the bot to continue with partial functionality
    
    async def load_cogs(self):
        """Load all cogs"""
        cogs = [
            'cogs.admin',
            'cogs.help',
            'cogs.setup',
            'cogs.ticket',
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
            'cogs.integrations_github',
            'cogs.integrations_notion',
            'cogs.integrations_trello'
        ]
        
        loaded_count = 0
        failed_cogs = []
        
        for cog in cogs:
            try:
                # Set a timeout for each cog loading
                await asyncio.wait_for(self.load_extension(cog), timeout=5.0)
                loaded_count += 1
                logger.info(f"  ✅ Loaded {cog}")
            except asyncio.TimeoutError:
                logger.error(f"  ❌ Timed out loading {cog}")
                failed_cogs.append(cog)
            except Exception as e:
                logger.error(f"  ❌ Failed to load {cog}: {e}")
                failed_cogs.append(cog)
    
        logger.info(f"📦 Loaded {loaded_count}/{len(cogs)} cogs successfully")
        if failed_cogs:
            logger.warning(f"Failed cogs: {', '.join(failed_cogs)}")
    
    async def on_ready(self):
        """Called when the bot is ready"""
        logger.info(f"🚀 {self.user} is now online!")
        logger.info(f"📊 Connected to {len(self.guilds)} guilds")
        
        # Clear and sync commands properly
        try:
            logger.info("🔄 Clearing and syncing commands...")
            
            # Clear all commands first
            self.tree.clear_commands(guild=None)
            
            # Sync globally with timeout
            try:
                synced = await asyncio.wait_for(self.tree.sync(), timeout=15.0)
                logger.info(f"✅ Synced {len(synced)} commands globally")
                
                # List synced commands for verification
                if synced:
                    command_names = [cmd.name for cmd in synced]
                    logger.info(f"📋 Synced commands: {', '.join(command_names)}")
            except asyncio.TimeoutError:
                logger.error("❌ Command syncing timed out")
            
        except Exception as e:
            logger.error(f"❌ Failed to sync commands: {e}")
        
        # Set bot status
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | /help"
            )
            await self.change_presence(activity=activity, status=discord.Status.online)
        except Exception as e:
            logger.error(f"Failed to set bot status: {e}")
    
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
        logger.info("🔄 Shutting down bot...")
        
        # Close database connection with timeout
        if self.db:
            try:
                await asyncio.wait_for(self.db.close(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.error("❌ Database close operation timed out")
            except Exception as e:
                logger.error(f"❌ Error closing database: {e}")
        
        # Close the bot
        try:
            await asyncio.wait_for(super().close(), timeout=5.0)
            logger.info("✅ Bot shutdown complete")
        except asyncio.TimeoutError:
            logger.error("❌ Bot close operation timed out")
        except Exception as e:
            logger.error(f"❌ Error during bot shutdown: {e}")

async def main():
    """Main function to run the bot"""
    logger.info("🚀 Starting Discord Bot...")
    
    # Validate environment variables
    try:
        Settings.validate_required_env_vars()
        logger.info("✅ Environment variables validated")
    except ValueError as e:
        logger.error(f"❌ Environment validation failed: {e}")
        return
    
    # Create and start bot
    bot = DiscordBot()
    
    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(handle_shutdown(bot, sig)))
    
    try:
        # Start with a timeout for connection
        connect_task = bot.start(Settings.DISCORD_TOKEN)
        await asyncio.wait_for(shield_task(connect_task), timeout=60.0)
    except asyncio.TimeoutError:
        logger.error("❌ Bot connection timed out")
    except discord.LoginFailure:
        logger.error("❌ Invalid Discord token")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        logger.exception("Full traceback:")
    finally:
        if not bot.is_closed():
            await bot.close()

async def shield_task(coro):
    """Shield a coroutine from cancellation"""
    return await asyncio.shield(coro)

async def handle_shutdown(bot, signal):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signal.name}, shutting down...")
    await bot.close()

if __name__ == "__main__":
    try:
        # Check Python version
        if sys.version_info < (3, 8):
            logger.error("❌ Python 3.8 or higher is required")
            sys.exit(1)
        
        # Run the bot with proper exception handling
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("🛑 Bot stopped by user")
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
            logger.exception("Full traceback:")
    except Exception as e:
        logger.error(f"❌ Fatal error outside main loop: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)
