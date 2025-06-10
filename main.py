"""
NUCLEAR MAIN: Updated to use nuclear database manager
EMERGENCY COMMAND REGISTRATION FIX
Complete bot setup with working slash command registration
"""
import discord
from discord.ext import commands
import asyncio
import logging
import os
import sys
from pathlib import Path
import signal

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config.settings import Settings
from utils.db_nuclear import NuclearDatabaseManager
from utils.admin import AdminManager
from utils.logging_manager import LoggingManager

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
        
        # Initialize managers with nuclear database
        self.db = None
        self.admin_manager = None
        self.logging_manager = None
        self.startup_complete = False
    
    async def setup_hook(self):
        """Called when the bot is starting up"""
        logger.info("🤖 Starting Discord bot setup...")
        
        # Set startup as complete early to prevent shutdown
        self.startup_complete = True
        
        try:
            # Initialize nuclear database
            logger.info("📊 Initializing nuclear database...")
            try:
                async with asyncio.timeout(30):
                    self.db = NuclearDatabaseManager()
                    await self.db.init_database()
                    logger.info("✅ Nuclear database initialized successfully")
            except asyncio.TimeoutError:
                logger.error("❌ Database initialization timed out after 30 seconds")
                raise
            except Exception as e:
                logger.error(f"❌ Database initialization failed: {e}")
                raise
        
            # Test nuclear connection
            if await self.db.test_nuclear_connection():
                logger.info("✅ Nuclear database connection verified")
            else:
                logger.error("❌ Nuclear database connection failed")
                return
        
            # Initialize admin manager
            logger.info("🛡️ Initializing admin manager...")
            try:
                if self.db:
                    self.admin_manager = AdminManager(self)
                    await self.admin_manager.load_admin_roles()
                    logger.info("✅ Admin manager initialized")
                else:
                    logger.warning("⚠️ Skipping admin manager initialization (no database)")
            except Exception as e:
                logger.warning(f"⚠️ Admin manager initialization failed: {e}")

            # Initialize logging manager
            logger.info("📝 Initializing logging manager...")
            try:
                if self.db:
                    self.logging_manager = LoggingManager(self)
                    await self.logging_manager.load_log_configs()
                    logger.info("✅ Logging manager initialized")
                else:
                    logger.warning("⚠️ Skipping logging manager initialization (no database)")
            except Exception as e:
                logger.warning(f"⚠️ Logging manager initialization failed: {e}")

            # Load cogs with emergency fallback
            logger.info("🔧 Loading cogs...")
            try:
                await self.load_cogs()
                logger.info("✅ Cogs loaded successfully")
            except Exception as e:
                logger.warning(f"⚠️ Cog loading failed: {e}")

            logger.info("✅ Bot setup completed successfully!")

        except Exception as e:
            logger.error(f"❌ Error during setup: {e}")
            logger.exception("Full traceback:")
            raise
    
    async def load_cogs(self):
        """Load all cogs with emergency fallback"""
        # Priority cogs (emergency versions)
        priority_cogs = [
            'cogs.tickets',  # Nuclear tickets with setup command
            'cogs.integrations_github',  # Nuclear GitHub integration
            'cogs.help',
            'cogs.admin'
        ]
        
        # Additional cogs
        additional_cogs = [
            'cogs.setup',
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
            'cogs.integrations_trello'
        ]
        
        all_cogs = priority_cogs + additional_cogs
        loaded_count = 0
        failed_count = 0
        
        for cog in all_cogs:
            try:
                logger.info(f"  • Loading {cog}...")
                await self.load_extension(cog)
                loaded_count += 1
                logger.info(f"  ✅ Loaded {cog}")
            except Exception as e:
                failed_count += 1
                logger.error(f"  ❌ Failed to load {cog}: {e}")
                # Continue loading other cogs
        
        logger.info(f"📦 Loaded {loaded_count}/{len(all_cogs)} cogs successfully")
        if failed_count > 0:
            logger.warning(f"⚠️ {failed_count} cogs failed to load")
        
        # Debug: List all commands before sync
        logger.info("🔍 Commands loaded:")
        for command in self.tree.get_commands():
            logger.info(f"  • /{command.name}: {command.description}")
    
    async def on_ready(self):
        """Called when the bot is ready"""
        logger.info(f"🚀 {self.user} is now online!")
        logger.info(f"📊 Connected to {len(self.guilds)} guilds")
        logger.info(f"👥 Serving {sum(guild.member_count for guild in self.guilds)} users")
        
        # Wait a moment for all cogs to fully initialize
        await asyncio.sleep(2)
        
        # EMERGENCY COMMAND SYNC
        try:
            logger.info("🔄 Starting EMERGENCY command synchronization...")
            
            # Get all commands
            commands = self.tree.get_commands()
            logger.info(f"📋 Found {len(commands)} commands to sync:")
            for cmd in commands:
                logger.info(f"  • /{cmd.name} - {cmd.description}")
            
            if len(commands) == 0:
                logger.error("❌ NO COMMANDS FOUND! Cog loading failed!")
                return
            
            # Sync to all guilds first (faster for testing)
            synced_guilds = 0
            total_synced = 0
            
            for guild in self.guilds:
                try:
                    logger.info(f"🔄 Syncing commands to guild: {guild.name}")
                    
                    # Copy global commands to guild
                    self.tree.copy_global_to(guild=guild)
                    
                    # Sync to guild
                    synced = await self.tree.sync(guild=guild)
                    synced_guilds += 1
                    total_synced += len(synced)
                    
                    logger.info(f"✅ Synced {len(synced)} commands to {guild.name}")
                    
                    # Log synced commands
                    for cmd in synced:
                        logger.info(f"  ✓ /{cmd.name}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to sync to {guild.name}: {e}")
            
            # Also sync globally as backup
            try:
                logger.info("🌐 Syncing commands globally...")
                global_synced = await self.tree.sync()
                logger.info(f"✅ Synced {len(global_synced)} commands globally")
            except Exception as e:
                logger.error(f"❌ Failed to sync globally: {e}")
            
            logger.info(f"🎉 EMERGENCY SYNC COMPLETE!")
            logger.info(f"📊 Synced to {synced_guilds} guilds, {total_synced} total commands")
            
        except Exception as e:
            logger.error(f"❌ EMERGENCY SYNC FAILED: {e}")
            logger.exception("Full traceback:")
        
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
        
        # Sync commands to the new guild
        try:
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info(f"✅ Synced {len(synced)} commands to new guild {guild.name}")
        except Exception as e:
            logger.error(f"❌ Failed to sync commands to new guild {guild.name}: {e}")
        
        # Update status
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | /help"
            )
            await self.change_presence(activity=activity)
        except Exception as e:
            logger.error(f"Failed to update status: {e}")
    
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
    
    async def on_app_command_error(self, interaction: discord.Interaction, error):
        """Global error handler for slash commands"""
        logger.error(f"Slash command error in {interaction.command}: {error}")
        logger.exception("Full traceback:")
        
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
    
    # Start the bot
    try:
        logger.info("🔄 Starting bot...")
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
