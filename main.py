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
        self.admin_manager = None
        self.ticket_manager = None
        self.logging_manager = None
        self.workflow_manager = None
    
    async def setup_hook(self):
        """Setup database and load cogs"""
        try:
            # Initialize database
            self.db = DatabaseManager()
            await self.db.init_database()
            logger.info("Database initialized successfully")
            
            # Initialize managers
            from utils.admin import AdminManager
            from utils.ticket_manager import TicketManager
            from utils.logging_manager import LoggingManager
            from utils.workflow_manager import WorkflowManager
            
            self.admin_manager = AdminManager(self)
            self.ticket_manager = TicketManager(self)
            self.logging_manager = LoggingManager(self)
            self.workflow_manager = WorkflowManager(self)
            
            await self.admin_manager.load_admin_roles()
            await self.ticket_manager.load_ticket_configs()
            await self.logging_manager.load_log_configs()
            
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
                'cogs.intelligence',
                'cogs.admin',
                'cogs.help',
                'cogs.logging'
            ]

            loaded_cogs = []
            for cog in cogs:
                try:
                    await self.load_extension(cog)
                    loaded_cogs.append(cog)
                    logger.info(f"✅ Loaded cog: {cog}")
                except Exception as e:
                    logger.error(f"❌ Failed to load cog {cog}: {e}")

            logger.info(f"Loaded {len(loaded_cogs)}/{len(cogs)} cogs successfully")

            # Force sync slash commands
            try:
                logger.info("Syncing slash commands...")
                synced = await self.tree.sync()
                logger.info(f"✅ Synced {len(synced)} slash commands")
                
                # List all synced commands for debugging
                for cmd in synced:
                    logger.info(f"  - /{cmd.name}: {cmd.description}")
                    
            except Exception as e:
                logger.error(f"❌ Failed to sync commands: {e}")
                
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}")
    
    async def on_ready(self):
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        
        # List all loaded commands for debugging
        logger.info("Loaded slash commands:")
        for command in self.tree.get_commands():
            logger.info(f"  - /{command.name}: {command.description}")
        
        logger.info(f'Bot deployment successful! 🚀')

    # Add a sync command for debugging
    @commands.command(name='sync')
    @commands.is_owner()
    async def sync_commands(self, ctx):
        """Manually sync slash commands (Owner only)"""
        try:
            synced = await self.tree.sync()
            await ctx.send(f'Synced {len(synced)} commands.')
            
            # List synced commands
            command_list = "\n".join([f"- /{cmd.name}" for cmd in synced])
            if len(command_list) < 2000:
                await ctx.send(f"\`\`\`\nSynced commands:\n{command_list}\n\`\`\`")
        except Exception as e:
            await ctx.send(f'Failed to sync commands: {e}')
    
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
    # Deployment compatibility
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting bot (port {port})")
    asyncio.run(main())
