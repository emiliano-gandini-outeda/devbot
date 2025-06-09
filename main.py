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
            
            # Clear any existing commands from the tree
            self.tree.clear_commands(guild=None)
            
            # Add admin slash commands FIRST
            await self.add_admin_slash_commands()
            
            logger.info("Setup hook completed successfully")
                
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}", exc_info=True)
            raise
    
    async def add_admin_slash_commands(self):
        """Add admin slash commands to the command tree"""
        try:
            # Define sync command
            @app_commands.command(name="admin_sync", description="Sync slash commands to this guild (Owner only)")
            @app_commands.describe(guild_only="Whether to sync only to this guild")
            async def sync_slash(interaction: discord.Interaction, guild_only: bool = True):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    if guild_only:
                        # Clear global commands first to prevent duplicates
                        self.tree.clear_commands(guild=None)
                        await self.tree.sync()
                        
                        # Sync to current guild
                        synced = await self.tree.sync(guild=interaction.guild)
                        await interaction.followup.send(f'✅ Synced {len(synced)} commands to {interaction.guild.name}.')
                        self._guild_synced.add(interaction.guild.id)
                        
                        # Log what was synced
                        if synced:
                            synced_names = [cmd['name'] for cmd in synced]
                            logger.info(f"Synced commands to {interaction.guild.name}: {', '.join(sorted(synced_names))}")
                    else:
                        synced = await self.tree.sync()
                        await interaction.followup.send(f'✅ Synced {len(synced)} commands globally.')
                        
                except Exception as e:
                    await interaction.followup.send(f'❌ Failed to sync commands: {e}')
                    logger.error("Slash sync failed", exc_info=True)

            # Define debug command to show what's in the tree
            @app_commands.command(name="admin_debug", description="Debug command tree (Owner only)")
            async def debug_slash(interaction: discord.Interaction):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                all_commands = self.tree.get_commands()
                
                if not all_commands:
                    await interaction.response.send_message("❌ No commands found in command tree!", ephemeral=True)
                    return
                
                # Group commands by source
                cog_commands = {}
                admin_commands = []
                
                for cmd in all_commands:
                    if cmd.name.startswith("admin_"):
                        admin_commands.append(cmd.name)
                    else:
                        # Try to determine which cog this command belongs to
                        cog_name = "Unknown"
                        if hasattr(cmd, 'callback') and hasattr(cmd.callback, '__qualname__'):
                            cog_name = cmd.callback.__qualname__.split('.')[0]
                        
                        if cog_name not in cog_commands:
                            cog_commands[cog_name] = []
                        cog_commands[cog_name].append(cmd.name)
                
                message = f"**Commands in Tree: {len(all_commands)}**\n\n"
                
                if admin_commands:
                    message += f"**Admin Commands ({len(admin_commands)}):** {', '.join(sorted(admin_commands))}\n\n"
                
                for cog_name, cmd_names in cog_commands.items():
                    message += f"**{cog_name} ({len(cmd_names)}):** {', '.join(sorted(cmd_names))}\n"
                
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
                    # Clear all commands from the tree
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
                    
                    # Sync to current guild
                    synced = await self.tree.sync(guild=interaction.guild)
                    
                    await interaction.followup.send(f"✅ Reloaded all cogs and synced {len(synced)} commands to {interaction.guild.name}")
                    
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

            # Store references to admin commands
            self.admin_commands = [sync_slash, debug_slash, reload_slash, db_test_slash]
            
            # Add all slash commands to the tree
            for cmd in self.admin_commands:
                self.tree.add_command(cmd)
            
            logger.info(f"✅ Added {len(self.admin_commands)} admin slash commands to command tree")
            
            # Final check of what's in the tree
            final_commands = self.tree.get_commands()
            logger.info(f"✅ Total commands in tree after setup: {len(final_commands)}")
            if final_commands:
                final_names = [cmd.name for cmd in final_commands]
                logger.info(f"Final command list: {', '.join(sorted(final_names))}")
            
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
        
        # Check what's in the command tree
        tree_commands = self.tree.get_commands()
        logger.info(f'Slash commands in tree: {len(tree_commands)}')
        
        if tree_commands:
            command_names = [cmd.name for cmd in tree_commands]
            logger.info(f'Commands ready to sync: {", ".join(sorted(command_names))}')
        else:
            logger.error("❌ NO COMMANDS IN TREE! This will cause 'Unknown integration' errors!")
        
        # Only sync once when the bot first starts
        if not self._synced:
            # Wait a moment for all cogs to fully initialize
            await asyncio.sleep(3)
            
            # Sync commands once
            await self.sync_commands_with_auto_clear()
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

    async def sync_commands_with_auto_clear(self):
        """Sync commands with automatic global command clearing to prevent duplicates"""
        try:
            logger.info("Starting command sync...")
            
            # Get all commands from the tree
            all_commands = self.tree.get_commands()
            logger.info(f"Found {len(all_commands)} commands to sync")
            
            if not all_commands:
                logger.error("❌ NO COMMANDS TO SYNC! This is the root cause of 'Unknown integration' errors!")
                return
            
            # Log all command names for debugging
            command_names = [cmd.name for cmd in all_commands]
            logger.info(f"Commands to sync: {', '.join(sorted(command_names))}")
            
            # Clear global commands first to prevent duplicates
            logger.info("Clearing global commands to prevent duplicates...")
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            logger.info("✅ Cleared global commands")
            
            # Sync to all guilds
            for guild in self.guilds:
                try:
                    # Sync to guild
                    synced = await self.tree.sync(guild=guild)
                    logger.info(f"✅ Synced {len(synced)} commands to {guild.name}")
                    self._guild_synced.add(guild.id)
                    
                    # Log synced command names
                    if synced:
                        synced_names = [cmd['name'] for cmd in synced]
                        logger.info(f"Successfully synced commands to {guild.name}: {', '.join(sorted(synced_names))}")
                    else:
                        logger.error(f"❌ 0 commands synced to {guild.name} - this will cause 'Unknown integration' errors!")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to sync to guild {guild.name}: {e}")
            
        except Exception as e:
            logger.error(f"❌ Failed to sync commands: {e}", exc_info=True)

    async def on_error(self, event, *args, **kwargs):
        logger.error(f'An error occurred in {event}', exc_info=True)

    async def on_guild_join(self, guild):
        """Automatically sync commands when joining a new guild"""
        logger.info(f"Bot joined new guild: {guild.name} ({guild.id})")
        
        try:
            # Auto-sync to new guild
            synced = await self.tree.sync(guild=guild)
            logger.info(f"✅ Auto-synced {len(synced)} commands to new guild: {guild.name}")
            self._guild_synced.add(guild.id)
                
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
