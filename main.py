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
        self._guild_synced = set()
    
    async def setup_hook(self):
        """Setup database and load cogs"""
        try:
            # Validate required environment variables
            Settings.validate_required_env_vars()
            
            # Initialize database with enhanced error handling
            logger.info("🔄 Initializing database connection...")
            self.db = DatabaseManager()
            await self.db.init_database()
            
            # Verify all tables exist
            tables_ok = await self.db.verify_tables()
            if not tables_ok:
                logger.warning("⚠️ Some database tables are missing, attempting to recreate...")
                await self.db.create_tables()
                tables_ok = await self.db.verify_tables()
            
            if tables_ok:
                logger.info("✅ Database initialization completed successfully")
                # Test the connection
                connection_ok = await self.db.test_connection()
                if connection_ok:
                    logger.info("✅ Database connection test passed")
                else:
                    logger.error("❌ Database connection test failed")
            else:
                logger.error("❌ Database initialization failed - some commands may not work")
            
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
            
            # Load all cogs FIRST
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
            
            # Add admin slash commands
            await self.add_admin_slash_commands()
            
            logger.info("Setup hook completed successfully")
                
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}", exc_info=True)
            raise
    
    async def register_all_commands_to_guild(self, guild):
        """Register ALL commands from cogs to a specific guild"""
        try:
            logger.info(f"🔄 Registering all commands to guild: {guild.name}")
            
            # Clear existing guild commands first
            self.tree.clear_commands(guild=guild)
            
            total_registered = 0
            
            # Register commands from all loaded cogs
            for cog_name, cog in self.cogs.items():
                cog_commands = 0
                
                # Get all app commands from the cog
                for attr_name in dir(cog):
                    attr = getattr(cog, attr_name)
                    if isinstance(attr, app_commands.Command):
                        # Add command to tree for this specific guild
                        self.tree.add_command(attr, guild=guild)
                        cog_commands += 1
                        total_registered += 1
                        logger.info(f"  ✅ Registered /{attr.name} from {cog_name} to {guild.name}")
                
                if cog_commands > 0:
                    logger.info(f"✅ Registered {cog_commands} commands from {cog_name} to {guild.name}")
            
            # Add admin commands to this guild
            for cmd in self.admin_commands:
                self.tree.add_command(cmd, guild=guild)
                total_registered += 1
                logger.info(f"  ✅ Registered /{cmd.name} (admin) to {guild.name}")
            
            logger.info(f"✅ Total commands registered to {guild.name}: {total_registered}")
            
            # Now sync to this guild
            try:
                synced = await self.tree.sync(guild=guild)
                logger.info(f"🚀 Synced {len(synced)} commands to {guild.name}")
                
                if synced:
                    # The synced commands are dictionaries, not AppCommand objects
                    synced_names = [cmd.get('name', 'unknown') for cmd in synced]
                    logger.info(f"✅ Successfully synced to {guild.name}: {', '.join(sorted(synced_names))}")
                    return True
                else:
                    logger.error(f"❌ 0 commands synced to {guild.name}!")
                    return False
            except Exception as e:
                logger.error(f"❌ Failed to sync commands to {guild.name}: {e}", exc_info=True)
                return False
            
        except Exception as e:
            logger.error(f"❌ Failed to register commands to {guild.name}: {e}", exc_info=True)
            return False
    
    async def add_admin_slash_commands(self):
        """Add admin slash commands to the command tree"""
        try:
            # Define sync command
            @app_commands.command(name="admin_sync", description="Sync slash commands to this guild (Owner only)")
            async def sync_slash(interaction: discord.Interaction):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    # First, clear global commands to remove duplicates
                    self.tree.clear_commands(guild=None)
                    await self.tree.sync()
                    await interaction.followup.send("✅ Cleared global commands")
                    
                    # Register and sync all commands to this guild
                    success = await self.register_all_commands_to_guild(interaction.guild)
                    
                    if success:
                        await interaction.followup.send(f'✅ Successfully registered and synced all commands to {interaction.guild.name}!')
                        self._guild_synced.add(interaction.guild.id)
                    else:
                        await interaction.followup.send(f'❌ Failed to sync commands to {interaction.guild.name}')
                        
                except Exception as e:
                    await interaction.followup.send(f'❌ Failed to sync commands: {e}')
                    logger.error("Slash sync failed", exc_info=True)

            # Define debug command to show what's in the tree
            @app_commands.command(name="admin_debug", description="Debug command tree (Owner only)")
            async def debug_slash(interaction: discord.Interaction):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                # Get commands for this specific guild
                guild_commands = self.tree.get_commands(guild=interaction.guild)
                global_commands = self.tree.get_commands(guild=None)
                
                message = f"**Guild Commands ({interaction.guild.name}): {len(guild_commands)}**\n"
                if guild_commands:
                    guild_names = [cmd.name for cmd in guild_commands]
                    message += f"{', '.join(sorted(guild_names))}\n\n"
                else:
                    message += "None\n\n"
                
                message += f"**Global Commands: {len(global_commands)}**\n"
                if global_commands:
                    global_names = [cmd.name for cmd in global_commands]
                    message += f"{', '.join(sorted(global_names))}"
                else:
                    message += "None"
                
                if len(message) > 4000:
                    await interaction.response.send_message("Message too long, check logs.", ephemeral=True)
                    logger.info(message)
                else:
                    await interaction.response.send_message(message, ephemeral=True)

            # Define force reload command
            @app_commands.command(name="admin_reload", description="Force reload all cogs and commands (Owner only)")
            async def reload_slash(interaction: discord.Interaction):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    # Clear all commands
                    self.tree.clear_commands(guild=None)
                    self.tree.clear_commands(guild=interaction.guild)
                    
                    # Reload all cogs
                    cogs_to_reload = [
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
                    
                    for cog_name in cogs_to_reload:
                        try:
                            if cog_name in self.extensions:
                                await self.reload_extension(cog_name)
                            else:
                                await self.load_extension(cog_name)
                            logger.info(f"Reloaded cog: {cog_name}")
                        except Exception as e:
                            logger.error(f"Failed to reload {cog_name}: {e}")
                    
                    # Re-add admin commands
                    for cmd in [sync_slash, debug_slash, reload_slash]:
                        self.tree.add_command(cmd)
                    
                    # Register and sync all commands to this guild
                    success = await self.register_all_commands_to_guild(interaction.guild)
                    
                    if success:
                        await interaction.followup.send(f"✅ Reloaded all cogs and synced commands to {interaction.guild.name}")
                    else:
                        await interaction.followup.send(f"❌ Reloaded cogs but failed to sync to {interaction.guild.name}")
                    
                except Exception as e:
                    await interaction.followup.send(f"❌ Failed to reload: {e}")
                    logger.error(f"Failed to reload: {e}", exc_info=True)

            # Define database test command
            @app_commands.command(name="admin_db_test", description="Test database connection (Owner only)")
            async def db_test_slash(interaction: discord.Interaction):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    # Test database connection
                    connection_ok = await self.db.test_connection()
                    tables_ok = await self.db.verify_tables()
                    
                    embed = discord.Embed(
                        title="🗄️ Database Status",
                        color=0x00ff00 if connection_ok and tables_ok else 0xff0000
                    )
                    
                    embed.add_field(
                        name="Connection",
                        value="✅ Connected" if connection_ok else "❌ Failed",
                        inline=True
                    )
                    
                    embed.add_field(
                        name="Database Type",
                        value="PostgreSQL (Railway)" if self.db.is_postgresql else "SQLite (Local)",
                        inline=True
                    )
                    
                    embed.add_field(
                        name="Tables",
                        value="✅ All tables exist" if tables_ok else "❌ Missing tables",
                        inline=True
                    )
                    
                    await interaction.followup.send(embed=embed)
                    
                except Exception as e:
                    await interaction.followup.send(f"❌ Database test failed: {e}")

            # Define clear global commands command
            @app_commands.command(name="admin_clear_global", description="Clear all global commands (Owner only)")
            async def clear_global_slash(interaction: discord.Interaction):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    # Clear global commands
                    self.tree.clear_commands(guild=None)
                    await self.tree.sync()
                    
                    # Check if global commands were cleared
                    global_commands = self.tree.get_commands(guild=None)
                    
                    if not global_commands:
                        await interaction.followup.send("✅ Successfully cleared all global commands!")
                    else:
                        await interaction.followup.send(f"⚠️ Some global commands remain: {len(global_commands)}")
                    
                except Exception as e:
                    await interaction.followup.send(f"❌ Failed to clear global commands: {e}")
                    logger.error(f"Failed to clear global commands: {e}", exc_info=True)

            # Store references to admin commands
            self.admin_commands = [sync_slash, debug_slash, reload_slash, db_test_slash, clear_global_slash]
            
            logger.info(f"✅ Created {len(self.admin_commands)} admin slash commands")
            
        except Exception as e:
            logger.error(f"Failed to add admin slash commands: {e}", exc_info=True)
    
    async def on_ready(self):
        """Called when bot is ready"""
        if self._ready_fired:
            logger.info(f'{self.user} reconnected to Discord!')
            return
        
        self._ready_fired = True
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        logger.info(f'Command prefix: {self.command_prefix}')
        logger.info(f'Prefix commands loaded: {len(self.commands)}')
        
        # Only sync once when the bot first starts
        if not self._synced:
            # Wait a moment for all cogs to fully initialize
            await asyncio.sleep(3)
            
            # Register and sync commands to all guilds
            await self.sync_all_guilds()
            self._synced = True
        
        logger.info(f'Bot deployment successful! 🚄')

    async def sync_all_guilds(self):
        """Sync commands to all guilds"""
        try:
            logger.info("🔄 Starting guild sync process...")
            
            # Clear global commands first
            logger.info("Clearing global commands...")
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            logger.info("✅ Cleared global commands")
            
            # Sync to each guild individually
            for guild in self.guilds:
                try:
                    success = await self.register_all_commands_to_guild(guild)
                    if success:
                        self._guild_synced.add(guild.id)
                        logger.info(f"✅ Successfully synced to {guild.name}")
                    else:
                        logger.error(f"❌ Failed to sync to {guild.name}")
                        
                except Exception as e:
                    logger.error(f"❌ Error syncing to {guild.name}: {e}")
            
            logger.info(f"✅ Sync process complete. Synced to {len(self._guild_synced)}/{len(self.guilds)} guilds")
            
        except Exception as e:
            logger.error(f"❌ Failed to sync to guilds: {e}", exc_info=True)

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
        
        # Debug message processing
        if message.content.startswith(self.command_prefix):
            logger.info(f"Processing command: {message.content}")
        
        # Check for workflow triggers
        if self.workflow_manager:
            await self.workflow_manager.check_message_triggers(message)
        
        # Process commands
        await self.process_commands(message)

    async def on_command_error(self, ctx, error):
        """Handle command errors"""
        if isinstance(error, commands.CommandNotFound):
            logger.warning(f"Command not found: {ctx.message.content}")
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

    async def on_guild_join(self, guild):
        """Automatically sync commands when joining a new guild"""
        logger.info(f"Bot joined new guild: {guild.name} ({guild.id})")
        
        try:
            # Auto-sync to new guild
            success = await self.register_all_commands_to_guild(guild)
            if success:
                logger.info(f"✅ Auto-synced commands to new guild: {guild.name}")
                self._guild_synced.add(guild.id)
            else:
                logger.error(f"❌ Failed to auto-sync to new guild: {guild.name}")
                
        except Exception as e:
            logger.error(f"Failed to auto-sync to new guild {guild.name}: {e}")

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
                break
                
            except discord.LoginFailure:
                logger.error("Invalid Discord token provided")
                break
                
            except discord.HTTPException as e:
                if e.status == 429:
                    logger.warning(f"Rate limited, waiting {retry_delay * 2} seconds...")
                    await asyncio.sleep(retry_delay * 2)
                else:
                    logger.error(f"HTTP error: {e}")
                    
            except (discord.ConnectionClosed, discord.GatewayNotFound) as e:
                logger.warning(f"Connection issue (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                
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
            logger.error(f"Failed to start bot after {max_retries} attempts")
            
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        if not bot.is_closed():
            await bot.close()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting Discord bot on Railway (port {port})")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
    except Exception as e:
        logger.error(f"Application failed to start: {e}", exc_info=True)
