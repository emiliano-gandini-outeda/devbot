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
            command_prefix='!',
            intents=intents,
            help_command=None,
            heartbeat_timeout=60.0,
            guild_ready_timeout=5.0
        )
        
        self.db = None
        self.admin_manager = None
        self.ticket_manager = None
        self.logging_manager = None
        self.workflow_manager = None
        self._ready_fired = False
        self._synced = False
    
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
            
            # Add emergency sync command
            await self.add_emergency_sync_command()
            
            logger.info("Setup hook completed successfully")
                
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}", exc_info=True)
            raise
    
    async def add_emergency_sync_command(self):
        """Add emergency sync command"""
        try:
            @app_commands.command(name="emergency_sync", description="Emergency sync all commands (Owner only)")
            async def emergency_sync(interaction: discord.Interaction):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    # Clear everything first
                    self.tree.clear_commands(guild=None)
                    self.tree.clear_commands(guild=interaction.guild)
                    
                    # Sync empty to clear Discord's cache
                    await self.tree.sync(guild=None)
                    await self.tree.sync(guild=interaction.guild)
                    
                    # Wait a moment
                    await asyncio.sleep(2)
                    
                    # Now sync all commands to this guild only
                    synced = await self.tree.sync(guild=interaction.guild)
                    
                    await interaction.followup.send(f"✅ Emergency sync complete! Synced {len(synced)} commands to {interaction.guild.name}")
                    
                    # Log what was synced
                    if synced:
                        synced_names = [cmd['name'] for cmd in synced]
                        logger.info(f"Emergency synced commands: {', '.join(sorted(synced_names))}")
                    else:
                        logger.warning("No commands were synced!")
                    
                except Exception as e:
                    await interaction.followup.send(f"❌ Emergency sync failed: {e}")
                    logger.error(f"Emergency sync failed: {e}", exc_info=True)
            
            # Add the emergency command to the tree
            self.tree.add_command(emergency_sync)
            logger.info("✅ Added emergency sync command")
            
        except Exception as e:
            logger.error(f"Failed to add emergency sync command: {e}", exc_info=True)
    
    async def on_ready(self):
        """Called when bot is ready"""
        if self._ready_fired:
            logger.info(f'{self.user} reconnected to Discord!')
            return
        
        self._ready_fired = True
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        
        # Get all commands from tree
        all_commands = self.tree.get_commands()
        logger.info(f'Total commands in tree: {len(all_commands)}')
        
        if all_commands:
            command_names = [cmd.name for cmd in all_commands]
            logger.info(f'Commands in tree: {", ".join(sorted(command_names))}')
        else:
            logger.warning("⚠️ NO COMMANDS FOUND IN TREE!")
        
        # Only sync once when the bot first starts
        if not self._synced:
            await asyncio.sleep(2)  # Wait for everything to initialize
            
            # Simple sync to first guild only
            if self.guilds:
                first_guild = self.guilds[0]
                try:
                    logger.info(f"Syncing commands to {first_guild.name}...")
                    synced = await self.tree.sync(guild=first_guild)
                    logger.info(f"✅ Synced {len(synced)} commands to {first_guild.name}")
                    
                    if synced:
                        synced_names = [cmd['name'] for cmd in synced]
                        logger.info(f"Synced commands: {', '.join(sorted(synced_names))}")
                    
                    self._synced = True
                except Exception as e:
                    logger.error(f"Failed to sync to {first_guild.name}: {e}")
        
        logger.info(f'Bot ready! Use /emergency_sync if commands don\'t work')

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

    async def on_command_error(self, ctx, error):
        """Handle command errors"""
        if isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.NotOwner):
            await ctx.send("❌ Only the bot owner can use this command.")
        else:
            logger.error(f"Command error in {ctx.command}: {error}", exc_info=True)
            await ctx.send(f"❌ An error occurred: {error}")

    async def on_member_join(self, member):
        """Handle member join events for workflow triggers"""
        if self.workflow_manager:
            await self.workflow_manager.check_member_join_triggers(member)

    async def on_thread_create(self, thread):
        """Handle thread creation events for workflow triggers"""
        if self.workflow_manager:
            await self.workflow_manager.check_thread_create_triggers(thread)

    async def on_error(self, event, *args, **kwargs):
        logger.error(f'An error occurred in {event}', exc_info=True)

    async def close(self):
        """Clean shutdown"""
        logger.info("Bot is shutting down...")
        if self.db:
            await self.db.close()
        await super().close()

async def main():
    """Main function with improved error handling"""
    bot = SlackBot()
    
    try:
        logger.info("Starting bot...")
        await bot.start(Settings.DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.error("Invalid Discord token provided")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        if not bot.is_closed():
            await bot.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
    except Exception as e:
        logger.error(f"Application failed to start: {e}", exc_info=True)
