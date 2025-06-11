"""
FIXED Main Bot Entry Point - Uses new database manager with type conversion
"""

import discord
from discord.ext import commands
import asyncio
import logging
import os
from config.settings import Settings
from utils.db_converter import FixedDatabaseManager
from utils.admin import AdminManager
from utils.logging_manager import LoggingManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class DevBot(commands.Bot):
    """Enhanced Discord bot with fixed database handling"""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None,
            case_insensitive=True
        )
        
        # Initialize managers
        self.db = None
        self.admin_manager = None
        self.logging_manager = None
        
        logger.info("🤖 DevBot initialized with FIXED database handling")
    
    async def setup_hook(self):
        """Setup hook called when bot starts"""
        try:
            logger.info("🔧 Starting bot setup...")
            
            # Initialize FIXED database manager
            self.db = FixedDatabaseManager()
            await self.db.init_database()
            logger.info("✅ Database initialized with type conversion")
            
            # Initialize admin manager
            self.admin_manager = AdminManager(self.db)
            await self.admin_manager.load_admin_roles()
            logger.info("✅ Admin manager initialized")
            
            # Initialize logging manager
            self.logging_manager = LoggingManager(self.db)
            logger.info("✅ Logging manager initialized")
            
            # Load all cogs
            await self.load_cogs()
            
            # Test database connection
            await self.db.test_connection()
            
            logger.info("🚀 Bot setup completed successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to setup bot: {e}")
            raise
    
    async def load_cogs(self):
        """Load all bot cogs"""
        cogs = [
            'cogs.admin',
            'cogs.help',
            'cogs.tickets',
            'cogs.integrations_github',
            'cogs.reminders',
            'cogs.meetings',
            'cogs.notifications',
            'cogs.roles',
            'cogs.setup',
            'cogs.workflows',
            'cogs.conversations',
            'cogs.intelligence',
            'cogs.logging',
            'cogs.privacy',
            'cogs.integrations_google',
            'cogs.integrations_notion',
            'cogs.integrations_trello'
        ]
        
        loaded_count = 0
        failed_count = 0
        
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"✅ Loaded {cog}")
                loaded_count += 1
            except Exception as e:
                logger.error(f"❌ Failed to load {cog}: {e}")
                failed_count += 1
        
        logger.info(f"📊 Cog loading complete: {loaded_count} loaded, {failed_count} failed")
        
        # Sync commands
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} slash commands")
        except Exception as e:
            logger.error(f"❌ Failed to sync commands: {e}")
    
    async def on_ready(self):
        """Called when bot is ready"""
        logger.info(f"🎉 {self.user} is now online!")
        logger.info(f"📊 Connected to {len(self.guilds)} guilds")
        logger.info(f"👥 Serving {sum(guild.member_count for guild in self.guilds)} users")
        
        # Set bot status
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="for /help | devBot - Powered by EGOS"
        )
        await self.change_presence(activity=activity)
    
    async def on_guild_join(self, guild):
        """Called when bot joins a guild"""
        logger.info(f"🏠 Joined guild: {guild.name} (ID: {guild.id})")
        
        # Create user entry for guild
        if self.db:
            await self.db.create_user(str(guild.id), guild.name)
    
    async def on_guild_remove(self, guild):
        """Called when bot leaves a guild"""
        logger.info(f"👋 Left guild: {guild.name} (ID: {guild.id})")
    
    async def on_error(self, event, *args, **kwargs):
        """Global error handler"""
        logger.error(f"❌ Error in {event}: {args}", exc_info=True)
    
    async def close(self):
        """Clean shutdown"""
        logger.info("🔄 Shutting down bot...")
        
        if self.db:
            await self.db.close()
        
        await super().close()
        logger.info("✅ Bot shutdown complete")

async def main():
    """Main function to run the bot"""
    try:
        # Validate environment
        if not Settings.DISCORD_TOKEN:
            logger.error("❌ DISCORD_TOKEN not found in environment variables")
            return
        
        if not Settings.DATABASE_URL:
            logger.error("❌ DATABASE_URL not found in environment variables")
            return
        
        logger.info("🚀 Starting DevBot with FIXED database handling...")
        
        # Create and run bot
        bot = DevBot()
        
        async with bot:
            await bot.start(Settings.DISCORD_TOKEN)
            
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
