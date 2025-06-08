import os
import asyncio
import logging
from discord.ext import commands
from discord import Intents
from dotenv import load_dotenv
from config.settings import Settings
from utils.db import DatabaseManager

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SlackBot(commands.Bot):
    def __init__(self):
        intents = Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        
        super().__init__(
            command_prefix=Settings.PREFIX,
            intents=intents,
            help_command=None
        )
        
        self.db = None
    
    async def setup_hook(self):
        """Setup database and load cogs"""
        try:
            # Initialize database
            self.db = DatabaseManager()
            await self.db.init_database()
            logger.info("Database initialized successfully")
            
            # Load all cogs
            cogs = [
                'cogs.conversations',
                'cogs.integrations_google',
                'cogs.integrations_notion',
                'cogs.integrations_trello',
                'cogs.workflows',
                'cogs.tickets',
                'cogs.roles',
                'cogs.privacy',
                'cogs.reminders',
                'cogs.notifications',
                'cogs.intelligence'
            ]
            
            for cog in cogs:
                try:
                    await self.load_extension(cog)
                    logger.info(f"Loaded cog: {cog}")
                except Exception as e:
                    logger.error(f"Failed to load cog {cog}: {e}")
            
            # Sync slash commands
            try:
                synced = await self.tree.sync()
                logger.info(f"Synced {len(synced)} slash commands")
            except Exception as e:
                logger.error(f"Failed to sync commands: {e}")
                
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}")
    
    async def on_ready(self):
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        logger.info(f'Railway deployment successful! 🚄')
    
    async def on_error(self, event, *args, **kwargs):
        logger.error(f'An error occurred in {event}', exc_info=True)

async def main():
    bot = SlackBot()
    
    try:
        await bot.start(Settings.DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot encountered an error: {e}")
    finally:
        if bot.db:
            await bot.db.close()
        await bot.close()

if __name__ == "__main__":
    # Railway compatibility
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting bot on Railway (port {port})")
    asyncio.run(main())
