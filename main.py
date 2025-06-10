"""
NUCLEAR MAIN: Updated to use nuclear database manager
"""
import discord
from discord.ext import commands
import asyncio
import logging
import os
from config.settings import Settings
from utils.db_nuclear import NuclearDatabaseManager
from utils.admin import AdminManager
from utils.logging_manager import LoggingManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class NuclearBot(commands.Bot):
    """Nuclear Discord bot with integer timestamp database"""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )
        
        # Nuclear database manager
        self.db = NuclearDatabaseManager()
        self.admin_manager = None
        self.logging_manager = None
        
        logger.info("🚀 Nuclear Bot initialized")
    
    async def setup_hook(self):
        """Setup hook called when bot starts"""
        try:
            logger.info("🔧 Setting up nuclear bot...")
            
            # Initialize nuclear database
            await self.db.init_database()
            
            # Test nuclear connection
            if await self.db.test_nuclear_connection():
                logger.info("✅ Nuclear database connection verified")
            else:
                logger.error("❌ Nuclear database connection failed")
                return
            
            # Initialize managers
            self.admin_manager = AdminManager(self.db)
            self.logging_manager = LoggingManager(self.db)
            
            # Load nuclear cogs
            nuclear_cogs = [
                'cogs.nuclear_tickets',
                'cogs.setup',
                'cogs.help',
                'cogs.admin'
            ]
            
            for cog in nuclear_cogs:
                try:
                    await self.load_extension(cog)
                    logger.info(f"✅ Loaded nuclear cog: {cog}")
                except Exception as e:
                    logger.error(f"❌ Failed to load cog {cog}: {e}")
            
            # Sync commands
            try:
                synced = await self.tree.sync()
                logger.info(f"✅ Synced {len(synced)} nuclear commands")
            except Exception as e:
                logger.error(f"❌ Failed to sync commands: {e}")
            
            logger.info("🚀 Nuclear bot setup complete")
            
        except Exception as e:
            logger.error(f"❌ Nuclear bot setup failed: {e}")
            raise
    
    async def on_ready(self):
        """Called when bot is ready"""
        logger.info(f"🚀 Nuclear Bot is ready!")
        logger.info(f"Bot: {self.user} (ID: {self.user.id})")
        logger.info(f"Guilds: {len(self.guilds)}")
        logger.info(f"Users: {len(set(self.get_all_members()))}")
        
        # Set status
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="for /setup-tickets | Nuclear Powered"
            )
        )
    
    async def on_command_error(self, ctx, error):
        """Handle command errors"""
        logger.error(f"Command error: {error}")
    
    async def close(self):
        """Clean shutdown"""
        logger.info("🔄 Shutting down nuclear bot...")
        
        if self.db:
            await self.db.close()
        
        await super().close()
        logger.info("✅ Nuclear bot shutdown complete")

async def main():
    """Main function to run the nuclear bot"""
    try:
        # Validate settings
        if not Settings.DISCORD_TOKEN:
            logger.error("❌ DISCORD_TOKEN not found in environment")
            return
        
        if not Settings.DATABASE_URL:
            logger.error("❌ DATABASE_URL not found in environment")
            return
        
        logger.info("🚀 Starting Nuclear Discord Bot...")
        
        # Create and run nuclear bot
        bot = NuclearBot()
        
        async with bot:
            await bot.start(Settings.DISCORD_TOKEN)
            
    except KeyboardInterrupt:
        logger.info("🔄 Nuclear bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Nuclear bot crashed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
