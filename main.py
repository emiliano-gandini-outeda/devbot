import discord
from discord.ext import commands
import asyncio
import logging
import os
import sys
from pathlib import Path

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
    
    async def setup_hook(self):
        """Called when the bot is starting up"""
        logger.info("🤖 Starting Discord bot setup...")
        
        try:
            # Initialize database
            logger.info("📊 Initializing database...")
            self.db = DatabaseManager()
            await self.db.init_database()
            logger.info("✅ Database initialized successfully")
        
            # Initialize managers
            logger.info("🛡️ Initializing managers...")
            if self.db:
                self.admin_manager = AdminManager(self)
                await self.admin_manager.load_admin_roles()
                
                self.logging_manager = LoggingManager(self)
                await self.logging_manager.load_log_configs()
                
                self.ticket_manager = TicketManager(self)
                logger.info("✅ Managers initialized")

            # Load cogs
            logger.info("🔧 Loading cogs...")
            await self.load_cogs()
            logger.info("✅ Cogs loaded successfully")

            self.startup_complete = True
            logger.info("✅ Bot setup completed successfully!")

        except Exception as e:
            logger.error(f"❌ Error during setup: {e}")
            logger.exception("Full traceback:")
            raise
    
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
        
        for cog in cogs:
            try:
                await self.load_extension(cog)
                loaded_count += 1
                logger.info(f"  ✅ Loaded {cog}")
            except Exception as e:
                logger.error(f"  ❌ Failed to load {cog}: {e}")
    
        logger.info(f"📦 Loaded {loaded_count}/{len(cogs)} cogs successfully")
    
    async def on_ready(self):
        """Called when the bot is ready"""
        logger.info(f"🚀 {self.user} is now online!")
        logger.info(f"📊 Connected to {len(self.guilds)} guilds")
        
        # Clear and sync commands properly
        try:
            logger.info("🔄 Clearing and syncing commands...")
            
            # Clear all commands first
            self.tree.clear_commands(guild=None)
            
            # Sync globally
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} commands globally")
            
            # List synced commands for verification
            if synced:
                command_names = [cmd.name for cmd in synced]
                logger.info(f"📋 Synced commands: {', '.join(command_names)}")
            
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
        
        # Close database connection
        if self.db:
            await self.db.close()
        
        # Close the bot
        await super().close()
        logger.info("✅ Bot shutdown complete")

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
    
    try:
        await bot.start(Settings.DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.error("❌ Invalid Discord token")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        logger.exception("Full traceback:")
    finally:
        if not bot.is_closed():
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
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)
