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
                'cogs.integrations_github',
                'cogs.workflows',
                'cogs.tickets',
                'cogs.roles',
                'cogs.privacy',
                'cogs.reminders',
                'cogs.notifications',
                'cogs.intelligence',
                'cogs.admin',
                'cogs.help',
                'cogs.logging',
                'cogs.meetings'
            ]

            loaded_cogs = []
            for cog in cogs:
                try:
                    await self.load_extension(cog)
                    loaded_cogs.append(cog)
                    logger.info(f"✅ Loaded cog: {cog}")
                except Exception as e:
                    logger.error(f"❌ Failed to load cog {cog}: {e}", exc_info=True)

            logger.info(f"Loaded {len(loaded_cogs)}/{len(cogs)} cogs successfully")
            
            # Don't sync commands in setup_hook - do it in on_ready to avoid blocking
            logger.info("Setup hook completed successfully")
                
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}", exc_info=True)
    
    async def on_ready(self):
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        
        # List all loaded commands for debugging
        all_commands = self.tree.get_commands()
        logger.info(f"Total registered slash commands: {len(all_commands)}")
        
        # Check for specific commands that should be available
        command_names = [cmd.name for cmd in all_commands]
        logger.info(f"Command check - create-workflow: {'create-workflow' in command_names}")
        logger.info(f"Command check - list-workflows: {'list-workflows' in command_names}")
        logger.info(f"Command check - edit-reminder: {'edit-reminder' in command_names}")
        logger.info(f"Command check - remind: {'remind' in command_names}")
        
        # Sync commands to guilds asynchronously (non-blocking)
        asyncio.create_task(self.sync_commands_to_guilds())
        
        logger.info(f'Bot deployment successful! 🚀')

    async def sync_commands_to_guilds(self):
        """Sync commands to all guilds asynchronously"""
        try:
            logger.info("Starting command sync to guilds...")
            synced_count = 0
            
            for guild in self.guilds:
                try:
                    synced = await self.tree.sync(guild=guild)
                    synced_count += len(synced)
                    logger.info(f"✅ Synced {len(synced)} commands to guild: {guild.name} ({guild.id})")
                    
                    # Small delay to avoid hitting rate limits
                    await asyncio.sleep(0.2)
                    
                except Exception as e:
                    logger.error(f"❌ Failed to sync commands to guild {guild.name}: {e}")
            
            logger.info(f"✅ Command sync completed! Total: {synced_count} commands across {len(self.guilds)} guilds")
            
        except Exception as e:
            logger.error(f"❌ Failed to sync commands: {e}", exc_info=True)

    # Add a sync command for debugging
    @commands.command(name='sync')
    @commands.is_owner()
    async def sync_commands(self, ctx):
        """Manually sync slash commands to current guild (Owner only)"""
        try:
            await ctx.send("Starting guild command sync process...")
            
            # Sync to current guild
            synced = await self.tree.sync(guild=ctx.guild)
            await ctx.send(f'✅ Synced {len(synced)} commands to {ctx.guild.name}.')
            
            # List synced commands
            command_list = "\n".join([f"- /{cmd.name}" for cmd in synced])
            if len(command_list) < 1900:
                await ctx.send(f"```\nSynced commands:\n{command_list}\n```")
        
            # Check total registered commands
            all_commands = self.tree.get_commands()
            await ctx.send(f"Total registered commands in tree: {len(all_commands)}")
            
        except Exception as e:
            await ctx.send(f'❌ Failed to sync commands: {e}')
            logger.error("Command sync failed", exc_info=True)

    @commands.command(name='sync_all')
    @commands.is_owner()
    async def sync_all_guilds(self, ctx):
        """Manually sync slash commands to all guilds (Owner only)"""
        try:
            await ctx.send("Starting sync to all guilds...")
            synced_count = 0
            
            for guild in self.guilds:
                try:
                    synced = await self.tree.sync(guild=guild)
                    synced_count += len(synced)
                    await ctx.send(f"✅ {guild.name}: {len(synced)} commands")
                    await asyncio.sleep(0.1)  # Rate limit protection
                except Exception as e:
                    await ctx.send(f"❌ {guild.name}: {e}")
            
            await ctx.send(f"✅ Completed! Total: {synced_count} commands across {len(self.guilds)} guilds")
            
        except Exception as e:
            await ctx.send(f'❌ Failed to sync commands: {e}')
            logger.error("Sync all command failed", exc_info=True)
    
    async def on_error(self, event, *args, **kwargs):
        logger.error(f'An error occurred in {event}', exc_info=True)

    async def on_guild_join(self, guild):
        """Sync commands when bot joins a new guild"""
        try:
            logger.info(f"Bot joined new guild: {guild.name} ({guild.id})")
            synced = await self.tree.sync(guild=guild)
            logger.info(f"✅ Synced {len(synced)} commands to new guild: {guild.name}")
        except Exception as e:
            logger.error(f"❌ Failed to sync commands to new guild {guild.name}: {e}")

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
