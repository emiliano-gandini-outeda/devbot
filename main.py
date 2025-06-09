import os
import asyncio
import logging
from discord.ext import commands
from discord import Intents
from dotenv import load_dotenv
from config.settings import Settings
from utils.db import DatabaseManager
import discord

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Reduce discord.py logging noise
logging.getLogger('discord.gateway').setLevel(logging.WARNING)
logging.getLogger('discord.client').setLevel(logging.WARNING)

class SlackBot(commands.Bot):
    def __init__(self):
        intents = Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        
        super().__init__(
            command_prefix=Settings.PREFIX,
            intents=intents,
            help_command=None,
            # Add connection resilience settings
            heartbeat_timeout=60.0,
            guild_ready_timeout=5.0
        )
        
        self.db = None
        self.admin_manager = None
        self.ticket_manager = None
        self.logging_manager = None
        self.workflow_manager = None
        self._ready_fired = False
    
    async def setup_hook(self):
        """Setup database and load cogs"""
        try:
            # Validate required environment variables
            Settings.validate_required_env_vars()
            
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
            logger.info("Setup hook completed successfully")
                
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}", exc_info=True)
            raise
    
    async def on_ready(self):
        """Called when bot is ready"""
        if self._ready_fired:
            logger.info(f'{self.user} reconnected to Discord!')
            return
            
        self._ready_fired = True
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        
        # Wait a moment for all cogs to fully initialize
        await asyncio.sleep(2)
        
        # List all loaded commands for debugging
        all_commands = self.tree.get_commands()
        logger.info(f"Total registered slash commands: {len(all_commands)}")
        
        # Check for specific commands that should be available
        command_names = [cmd.name for cmd in all_commands]
        logger.info(f"Available commands: {', '.join(sorted(command_names)) if command_names else 'None'}")
        
        # Sync commands to guilds asynchronously (non-blocking)
        asyncio.create_task(self.sync_commands_to_guilds())
        
        logger.info(f'Bot deployment successful! 🚄')

    async def on_disconnect(self):
        """Called when bot disconnects"""
        logger.warning("Bot disconnected from Discord")

    async def on_resumed(self):
        """Called when bot resumes connection"""
        logger.info("Bot resumed connection to Discord")

    async def sync_commands_to_guilds(self):
        """Sync commands to all guilds asynchronously"""
        try:
            logger.info("Starting command sync to guilds...")
            
            # First, ensure all cog commands are properly added to the tree
            await self.register_cog_commands()
            
            synced_count = 0
            failed_guilds = []
            
            for guild in self.guilds:
                try:
                    # Add retry logic for command syncing
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            synced = await self.tree.sync(guild=guild)
                            synced_count += len(synced)
                            logger.info(f"✅ Synced {len(synced)} commands to guild: {guild.name} ({guild.id})")
                            break
                        except discord.HTTPException as e:
                            if attempt == max_retries - 1:
                                raise
                            logger.warning(f"Retry {attempt + 1}/{max_retries} for guild {guild.name}: {e}")
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    
                    # Delay to avoid rate limits
                    await asyncio.sleep(1.0)
                    
                except Exception as e:
                    logger.error(f"❌ Failed to sync commands to guild {guild.name}: {e}")
                    failed_guilds.append(guild.name)
            
            logger.info(f"✅ Command sync completed! Total: {synced_count} commands across {len(self.guilds)} guilds")
            if failed_guilds:
                logger.warning(f"Failed to sync to {len(failed_guilds)} guilds: {', '.join(failed_guilds)}")
            
        except Exception as e:
            logger.error(f"❌ Failed to sync commands: {e}", exc_info=True)

    async def register_cog_commands(self):
        """Ensure all cog commands are properly registered to the command tree"""
        try:
            logger.info("Registering cog commands to command tree...")
            
            # Collect all commands from cogs
            commands_to_add = []
            existing_command_names = [cmd.name for cmd in self.tree.get_commands()]
            
            for cog_name, cog in self.cogs.items():
                if hasattr(cog, '__cog_app_commands__'):
                    for command in cog.__cog_app_commands__:
                        # Check if command is already in the tree
                        if command.name not in existing_command_names:
                            commands_to_add.append(command)
                            logger.debug(f"Adding command /{command.name} from {cog_name}")
            
            # Add any missing commands to the tree
            for command in commands_to_add:
                self.tree.add_command(command)
            
            total_commands = len(self.tree.get_commands())
            logger.info(f"✅ Registered {total_commands} commands to command tree")
            
        except Exception as e:
            logger.error(f"❌ Failed to register cog commands: {e}", exc_info=True)

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
            if command_list and len(command_list) < 1900:
                await ctx.send(f"\`\`\`\nSynced commands:\n{command_list}\n\`\`\`")
            elif not command_list:
                await ctx.send("No commands were synced.")
        
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
                    await asyncio.sleep(1.0)  # Rate limit protection
                except Exception as e:
                    await ctx.send(f"❌ {guild.name}: {e}")
            
            await ctx.send(f"✅ Completed! Total: {synced_count} commands across {len(self.guilds)} guilds")
            
        except Exception as e:
            await ctx.send(f'❌ Failed to sync commands: {e}')
            logger.error("Sync all command failed", exc_info=True)
    
    @commands.command(name='list_commands')
    @commands.is_owner()
    async def list_commands_cmd(self, ctx):
        """List all commands and their registration status"""
        all_commands = self.tree.get_commands()
        
        if not all_commands:
            await ctx.send("No commands are currently registered in the command tree.")
            return
            
        # Group by cog
        cog_commands = {}
        for cmd in all_commands:
            cog_name = getattr(cmd, "_cog_name", "Unknown")
            if cog_name not in cog_commands:
                cog_commands[cog_name] = []
            cog_commands[cog_name].append(cmd)
        
        for cog_name, cmds in cog_commands.items():
            commands_text = "\n".join([f"- /{cmd.name}" for cmd in cmds])
            await ctx.send(f"**{cog_name} Commands**:\n\`\`\`\n{commands_text}\n\`\`\`")
        
        await ctx.send(f"Total commands: {len(all_commands)}")
    
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

    async def close(self):
        """Clean shutdown"""
        logger.info("Bot is shutting down...")
        if self.db:
            await self.db.close()
        await super().close()

async def main():
    """Main function with improved error handling"""
    bot = SlackBot()
    
    max_retries = 5
    retry_delay = 5
    
    try:
        for attempt in range(max_retries):
            try:
                logger.info(f"Starting bot (attempt {attempt + 1}/{max_retries})")
                await bot.start(Settings.DISCORD_TOKEN)
                break  # If we get here, the bot started successfully
                
            except discord.LoginFailure:
                logger.error("Invalid Discord token provided")
                break  # Don't retry on authentication failures
                
            except discord.HTTPException as e:
                if e.status == 429:  # Rate limited
                    logger.warning(f"Rate limited, waiting {retry_delay * 2} seconds...")
                    await asyncio.sleep(retry_delay * 2)
                else:
                    logger.error(f"HTTP error: {e}")
                    
            except (discord.ConnectionClosed, discord.GatewayNotFound) as e:
                logger.warning(f"Connection issue (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
                
            except Exception as e:
                logger.error(f"Unexpected error (attempt {attempt + 1}): {e}", exc_info=True)
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
        else:
            # This executes if the for loop completes without breaking
            logger.error(f"Failed to start bot after {max_retries} attempts")
            
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        if not bot.is_closed():
            await bot.close()

if __name__ == "__main__":
    # Deployment compatibility
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting Discord bot on Railway (port {port})")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
    except Exception as e:
        logger.error(f"Application failed to start: {e}", exc_info=True)
