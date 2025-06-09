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
            
            # Add admin slash commands AFTER loading cogs
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
                        # Get all commands from the tree
                        all_commands = [cmd for cmd in self.tree.get_commands() if cmd.name != "admin_sync"]
                        
                        # Clear existing guild commands first
                        self.tree.clear_commands(guild=interaction.guild)
                        
                        # Add all commands to guild
                        for command in all_commands:
                            self.tree.add_command(command, guild=interaction.guild)
                        
                        # Sync to current guild
                        synced = await self.tree.sync(guild=interaction.guild)
                        await interaction.followup.send(f'✅ Synced {len(synced)} commands to {interaction.guild.name}.')
                        
                        # Clear global commands automatically
                        self.tree.clear_commands(guild=None)
                        global_synced = await self.tree.sync()
                        await interaction.followup.send(f'✅ Cleared global commands. {len(global_synced)} global commands remain.')
                        self._guild_synced.add(interaction.guild.id)
                    else:
                        synced = await self.tree.sync()
                        await interaction.followup.send(f'✅ Synced {len(synced)} commands globally.')
                        
                except Exception as e:
                    await interaction.followup.send(f'❌ Failed to sync commands: {e}')
                    logger.error("Slash sync failed", exc_info=True)

            # Define fix duplicates command
            @app_commands.command(name="admin_fix_duplicates", description="Fix duplicate commands in this guild (Owner only)")
            async def fix_duplicates_slash(interaction: discord.Interaction):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    # Get all commands except admin commands
                    all_commands = [cmd for cmd in self.tree.get_commands() if not cmd.name.startswith("admin_")]
                    
                    if not all_commands:
                        await interaction.followup.send("❌ No commands found in command tree!")
                        return
                    
                    # Clear existing guild commands
                    self.tree.clear_commands(guild=interaction.guild)
                    
                    # Add all commands to guild
                    for command in all_commands:
                        self.tree.add_command(command, guild=interaction.guild)
                    
                    # Sync to guild
                    guild_synced = await self.tree.sync(guild=interaction.guild)
                    await interaction.followup.send(f"✅ Synced {len(guild_synced)} commands to {interaction.guild.name}")
                    
                    # Automatically clear global commands
                    self.tree.clear_commands(guild=None)
                    global_synced = await self.tree.sync()
                    await interaction.followup.send(f"✅ Automatically cleared global commands. {len(global_synced)} global commands remain.")
                    
                    self._guild_synced.add(interaction.guild.id)
                    await interaction.followup.send("✅ Duplicate commands fixed! You should now see only one set of commands.")
                    
                except Exception as e:
                    await interaction.followup.send(f"❌ Failed to fix duplicate commands: {e}")
                    logger.error("Failed to fix duplicate commands", exc_info=True)

            # Define status command
            @app_commands.command(name="admin_status", description="Show bot status and sync information (Owner only)")
            async def status_slash(interaction: discord.Interaction):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                try:
                    embed = discord.Embed(
                        title="🤖 Bot Status",
                        color=0x5865F2
                    )
                    
                    # Basic info
                    embed.add_field(
                        name="📊 Basic Info",
                        value=f"Guilds: {len(self.guilds)}\nPrefix: `{self.command_prefix}`\nLatency: {round(self.latency * 1000)}ms",
                        inline=True
                    )
                    
                    # Command info
                    all_commands = self.tree.get_commands()
                    embed.add_field(
                        name="⚡ Commands",
                        value=f"Slash Commands: {len(all_commands)}\nPrefix Commands: {len(self.commands)}",
                        inline=True
                    )
                    
                    # Sync status
                    synced_guilds = len(self._guild_synced)
                    embed.add_field(
                        name="🔄 Sync Status",
                        value=f"Synced Guilds: {synced_guilds}/{len(self.guilds)}\nAuto-sync: ✅ Enabled",
                        inline=True
                    )
                    
                    # Loaded cogs
                    loaded_cogs = list(self.cogs.keys())
                    embed.add_field(
                        name=f"📦 Loaded Cogs ({len(loaded_cogs)})",
                        value=", ".join(loaded_cogs) if loaded_cogs else "None",
                        inline=False
                    )
                    
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    
                except Exception as e:
                    await interaction.response.send_message(f"❌ Failed to get bot status: {e}", ephemeral=True)

            # Define clear global command
            @app_commands.command(name="admin_clear_global", description="Clear all global commands (Owner only)")
            async def clear_global_slash(interaction: discord.Interaction):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    self.tree.clear_commands(guild=None)
                    synced = await self.tree.sync()
                    await interaction.followup.send(f'✅ Cleared all global commands. {len(synced)} commands remain.')
                except Exception as e:
                    await interaction.followup.send(f'❌ Failed to clear global commands: {e}')

            # Define clear guild command
            @app_commands.command(name="admin_clear_guild", description="Clear all guild-specific commands (Owner only)")
            async def clear_guild_slash(interaction: discord.Interaction):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    self.tree.clear_commands(guild=interaction.guild)
                    synced = await self.tree.sync(guild=interaction.guild)
                    await interaction.followup.send(f'✅ Cleared guild commands. {len(synced)} commands remain.')
                except Exception as e:
                    await interaction.followup.send(f'❌ Failed to clear guild commands: {e}')

            # Define list commands command
            @app_commands.command(name="admin_list_commands", description="List all registered commands (Owner only)")
            async def list_commands_slash(interaction: discord.Interaction):
                if not await self.is_owner(interaction.user):
                    await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
                    return
                
                all_commands = self.tree.get_commands()
                
                if not all_commands:
                    await interaction.response.send_message("No commands are currently registered.", ephemeral=True)
                    return
                
                # Group by cog
                cog_commands = {}
                admin_commands = []
                
                for cmd in all_commands:
                    if cmd.name.startswith("admin_"):
                        admin_commands.append(cmd.name)
                    else:
                        cog_name = getattr(cmd.callback, '__qualname__', 'Unknown').split('.')[0]
                        if cog_name not in cog_commands:
                            cog_commands[cog_name] = []
                        cog_commands[cog_name].append(cmd.name)
                
                message = f"**Total Commands: {len(all_commands)}**\n\n"
                
                if admin_commands:
                    message += f"**Admin Commands:** {', '.join(sorted(admin_commands))}\n\n"
                
                for cog_name, cmd_names in cog_commands.items():
                    message += f"**{cog_name}:** {', '.join(sorted(cmd_names))}\n"
                
                if len(message) > 4000:
                    await interaction.response.send_message("Command list too long, check logs.", ephemeral=True)
                    logger.info(message)
                else:
                    await interaction.response.send_message(message, ephemeral=True)

            # Store references to admin commands
            self.admin_commands = [sync_slash, fix_duplicates_slash, status_slash, clear_global_slash, clear_guild_slash, list_commands_slash]
            
            # Add all slash commands to the tree
            for cmd in self.admin_commands:
                self.tree.add_command(cmd)
            
            logger.info("✅ Added admin slash commands to command tree")
            
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
        logger.info(f'Slash commands loaded: {len(self.tree.get_commands())}')
        
        # List all loaded commands for debugging
        prefix_commands = [cmd.name for cmd in self.commands]
        slash_commands = [cmd.name for cmd in self.tree.get_commands()]
        logger.info(f'Prefix commands: {", ".join(prefix_commands)}')
        logger.info(f'Slash commands: {", ".join(slash_commands)}')
        
        # Only sync once when the bot first starts
        if not self._synced:
            # Wait a moment for all cogs to fully initialize
            await asyncio.sleep(2)
            
            # Sync commands once with automatic global clearing
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
            logger.info("Starting command sync with automatic global clearing...")
            
            # Get all commands from the tree
            all_commands = self.tree.get_commands()
            logger.info(f"Found {len(all_commands)} commands to sync")
            
            if not all_commands:
                logger.warning("No commands found to sync!")
                return
            
            # Always sync to individual guilds and clear global commands
            logger.info("Syncing to individual guilds and clearing global commands...")
            
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
                    self._guild_synced.add(guild.id)
                    
                except Exception as e:
                    logger.error(f"❌ Failed to sync to guild {guild.name}: {e}")
            
            # Clear global commands to prevent duplicates
            try:
                self.tree.clear_commands(guild=None)
                global_synced = await self.tree.sync()
                logger.info(f"✅ Cleared global commands. {len(global_synced)} global commands remain.")
            except Exception as e:
                logger.error(f"❌ Failed to clear global commands: {e}")
            
            # List synced commands for debugging
            command_names = [cmd.name for cmd in all_commands]
            logger.info(f"Synced commands: {', '.join(sorted(command_names))}")
            
        except Exception as e:
            logger.error(f"❌ Failed to sync commands: {e}", exc_info=True)

    async def on_error(self, event, *args, **kwargs):
        logger.error(f'An error occurred in {event}', exc_info=True)

    async def on_guild_join(self, guild):
        """Automatically sync commands when joining a new guild"""
        logger.info(f"Bot joined new guild: {guild.name} ({guild.id})")
        
        try:
            # Auto-sync to new guild
            all_commands = self.tree.get_commands()
            if all_commands:
                # Clear existing guild commands
                self.tree.clear_commands(guild=guild)
                
                # Add commands to guild
                for command in all_commands:
                    self.tree.add_command(command, guild=guild)
                
                # Sync to guild
                synced = await self.tree.sync(guild=guild)
                logger.info(f"✅ Auto-synced {len(synced)} commands to new guild: {guild.name}")
                self._guild_synced.add(guild.id)
                
                # Clear global commands if this is the first guild sync
                if len(self._guild_synced) == 1:
                    self.tree.clear_commands(guild=None)
                    await self.tree.sync()
                    logger.info("✅ Cleared global commands after first guild sync")
                    
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
