import os
import asyncio
import logging
from discord.ext import commands
from discord import Intents
from dotenv import load_dotenv
from config.settings import Settings
from utils.db import DatabaseManager
import discord
from discord import app_commands

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
        self._synced = False  # Track if we've already synced
    
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
                'cogs.admin',
                'cogs.conversations', 
                'cogs.help',
                'cogs.integrations_github',
                'cogs.logging',
                'cogs.meetings',
                'cogs.notifications',
                'cogs.privacy',
                'cogs.reminders',
                'cogs.roles',
                'cogs.setup',
                'cogs.tickets',
                'cogs.workflows'
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
        
        # Only sync once when the bot first starts
        if not self._synced:
            # Wait a moment for all cogs to fully initialize
            await asyncio.sleep(2)
            
            # Sync commands once
            await self.sync_commands_once()
            self._synced = True
        
        logger.info(f'Bot deployment successful! 🚄')

    async def on_disconnect(self):
        """Called when bot disconnects"""
        logger.warning("Bot disconnected from Discord")

    async def on_resumed(self):
        """Called when bot resumes connection"""
        logger.info("Bot resumed connection to Discord")

    async def on_message(self, message):
        """Handle message events for workflow triggers"""
        if message.author.bot:
            return
        
        # Check for workflow triggers
        if self.workflow_manager:
            await self.workflow_manager.check_message_triggers(message)
        
        # Process commands
        await self.process_commands(message)

    async def on_member_join(self, member):
        """Handle member join events for workflow triggers"""
        if self.workflow_manager:
            await self.workflow_manager.check_member_join_triggers(member)

    async def on_thread_create(self, thread):
        """Handle thread creation events for workflow triggers"""
        if self.workflow_manager:
            await self.workflow_manager.check_thread_create_triggers(thread)

    async def sync_commands_once(self):
        """Sync commands only once to avoid duplicates"""
        try:
            logger.info("Starting one-time command sync...")
            
            # Get all commands from the tree
            all_commands = self.tree.get_commands()
            logger.info(f"Found {len(all_commands)} commands to sync")
            
            if not all_commands:
                logger.warning("No commands found to sync!")
                return
            
            # Choose sync strategy based on environment
            if len(self.guilds) <= 3:  # Development mode
                logger.info("Development mode: Syncing to individual guilds")
                for guild in self.guilds:
                    try:
                        # Clear existing guild commands first
                        self.tree.clear_commands(guild=guild)
                        
                        # Copy global commands to guild
                        for command in all_commands:
                            self.tree.add_command(command, guild=guild)
                        
                        # Sync to guild
                        guild_synced = await self.tree.sync(guild=guild)
                        logger.info(f"✅ Synced {len(guild_synced)} commands to {guild.name}")
                    except Exception as e:
                        logger.error(f"❌ Failed to sync to guild {guild.name}: {e}")
                
                # Clear global commands to prevent duplicates
                try:
                    self.tree.clear_commands(guild=None)
                    await self.tree.sync()
                    logger.info("✅ Cleared global commands to prevent duplicates")
                except Exception as e:
                    logger.error(f"❌ Failed to clear global commands: {e}")
            else:  # Production mode
                logger.info("Production mode: Syncing globally")
                try:
                    synced = await self.tree.sync()
                    logger.info(f"✅ Synced {len(synced)} commands globally")
                except Exception as e:
                    logger.error(f"❌ Failed to sync globally: {e}")
            
            # List synced commands for debugging
            command_names = [cmd.name for cmd in all_commands]
            logger.info(f"Synced commands: {', '.join(sorted(command_names))}")
            
        except Exception as e:
            logger.error(f"❌ Failed to sync commands: {e}", exc_info=True)

    # Manual sync commands for debugging (owner only)
    @commands.command(name='sync')
    @commands.is_owner()
    async def sync_commands(self, ctx):
        """Manually sync slash commands to current guild and clear global commands (Owner only)"""
        try:
            await ctx.send("Starting manual guild sync...")
            
            # Clear existing guild commands first
            self.tree.clear_commands(guild=ctx.guild)
            
            # Copy global commands to guild
            global_commands = self.tree.get_commands()
            for command in global_commands:
                self.tree.add_command(command, guild=ctx.guild)
            
            # Sync to current guild
            synced = await self.tree.sync(guild=ctx.guild)
            await ctx.send(f'✅ Synced {len(synced)} commands to {ctx.guild.name}.')
            
            # Clear global commands for this guild to prevent duplicates
            await ctx.send("Clearing global commands for this guild...")
            
            # We need to keep the global commands in the tree for other guilds
            # but remove them from Discord's API for this specific guild
            try:
                # This will remove the global commands from showing in this guild
                await self.tree.sync(guild=discord.Object(id=ctx.guild.id))
                await ctx.send(f'✅ Cleared global commands for {ctx.guild.name}.')
            except Exception as e:
                await ctx.send(f'❌ Failed to clear global commands: {e}')
            
        except Exception as e:
            await ctx.send(f'❌ Failed to sync commands: {e}')
            logger.error("Manual sync failed", exc_info=True)

    @commands.command(name='sync_global')
    @commands.is_owner()
    async def sync_global(self, ctx):
        """Manually sync slash commands globally (Owner only)"""
        try:
            await ctx.send("Starting manual global sync...")
            synced = await self.tree.sync()
            await ctx.send(f'✅ Synced {len(synced)} commands globally.')
        except Exception as e:
            await ctx.send(f'❌ Failed to sync commands globally: {e}')
            logger.error("Global sync failed", exc_info=True)

    @commands.command(name='clear_guild')
    @commands.is_owner()
    async def clear_guild_commands(self, ctx):
        """Clear all guild-specific commands (Owner only)"""
        try:
            await ctx.send("Clearing guild commands...")
            self.tree.clear_commands(guild=ctx.guild)
            synced = await self.tree.sync(guild=ctx.guild)
            await ctx.send(f'✅ Cleared guild commands. {len(synced)} commands remain.')
        except Exception as e:
            await ctx.send(f'❌ Failed to clear guild commands: {e}')

    @commands.command(name='clear_global')
    @commands.is_owner()
    async def clear_global_commands(self, ctx):
        """Clear all global commands (Owner only)"""
        try:
            await ctx.send("⚠️ Clearing ALL global commands...")
            self.tree.clear_commands(guild=None)
            synced = await self.tree.sync()
            await ctx.send(f'✅ Cleared all global commands. {len(synced)} commands remain.')
        except Exception as e:
            await ctx.send(f'❌ Failed to clear global commands: {e}')

    @commands.command(name='list_commands')
    @commands.is_owner()
    async def list_commands_cmd(self, ctx):
        """List all registered commands"""
        all_commands = self.tree.get_commands()
        
        if not all_commands:
            await ctx.send("No commands are currently registered.")
            return
        
        # Group by cog
        cog_commands = {}
        for cmd in all_commands:
            cog_name = getattr(cmd.callback, '__qualname__', 'Unknown').split('.')[0]
            if cog_name not in cog_commands:
                cog_commands[cog_name] = []
            cog_commands[cog_name].append(cmd.name)
        
        message = f"**Total Commands: {len(all_commands)}**\n\n"
        for cog_name, cmd_names in cog_commands.items():
            message += f"**{cog_name}:** {', '.join(sorted(cmd_names))}\n"
        
        if len(message) > 2000:
            # Split into multiple messages if too long
            parts = message.split('\n')
            current = ""
            for part in parts:
                if len(current + part + '\n') > 1900:
                    await ctx.send(current)
                    current = part + '\n'
                else:
                    current += part + '\n'
            if current:
                await ctx.send(current)
        else:
            await ctx.send(message)
    
    async def on_error(self, event, *args, **kwargs):
        logger.error(f'An error occurred in {event}', exc_info=True)

    async def on_guild_join(self, guild):
        """Don't auto-sync when joining new guilds to avoid duplicates"""
        logger.info(f"Bot joined new guild: {guild.name} ({guild.id})")
        logger.info("Use manual sync commands if needed for this guild")

    async def close(self):
        """Clean shutdown"""
        logger.info("Bot is shutting down...")
        if self.db:
            await self.db.close()
        await super().close()

    @commands.command(name='fix_duplicates')
    @commands.is_owner()
    async def fix_duplicates(self, ctx):
        """Fix duplicate commands in the current guild (Owner only)"""
        try:
            await ctx.send("🔧 Fixing duplicate commands...")
            
            # Step 1: Get all global commands
            global_commands = self.tree.get_commands()
            
            # Step 2: Clear existing guild commands
            self.tree.clear_commands(guild=ctx.guild)
            
            # Step 3: Add global commands to guild
            for command in global_commands:
                self.tree.add_command(command, guild=ctx.guild)
            
            # Step 4: Sync to guild
            guild_synced = await self.tree.sync(guild=ctx.guild)
            await ctx.send(f"✅ Synced {len(guild_synced)} commands to {ctx.guild.name}")
            
            # Step 5: Clear global commands
            self.tree.clear_commands(guild=None)
            global_synced = await self.tree.sync()
            await ctx.send(f"✅ Cleared global commands. {len(global_synced)} global commands remain.")
            
            await ctx.send("✅ Duplicate commands fixed! You should now see only one set of commands.")
            
        except Exception as e:
            await ctx.send(f"❌ Failed to fix duplicate commands: {e}")
            logger.error("Failed to fix duplicate commands", exc_info=True)

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
