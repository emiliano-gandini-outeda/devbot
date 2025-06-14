# Copyright (C) 2025 Eclipse Growth Optimization Services
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import discord
from discord.ext import commands
import asyncio
import logging
import os
import sys
from pathlib import Path
import signal

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config.settings import Settings
from utils.db import DatabaseManager
from utils.admin import AdminManager
from utils.logging_manager import LoggingManager
from utils.workflow_manager import WorkflowManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)

logger = logging.getLogger(__name__)

# Global flag to prevent shutdown
SHUTDOWN_REQUESTED = False

class DiscordBot(commands.Bot):
    def __init__(self):
        # Configure intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.reactions = True
        intents.voice_states = True
        
        super().__init__(
            command_prefix=Settings.PREFIX,
            intents=intents,
            help_command=None,
            case_insensitive=True
        )
        
        # Initialize managers
        self.db = None
        self.admin_manager = None
        self.logging_manager = None
        self.ticket_manager = None
        self.workflow_manager = None
        self.startup_complete = False
    
    async def setup_hook(self):
        """Called when the bot is starting up"""
        logger.info("🤖 Starting Discord bot setup...")
        
        # Set startup as complete early to prevent shutdown
        self.startup_complete = True
        
        try:
            # Initialize database
            logger.info("📊 Initializing database...")
            try:
                async with asyncio.timeout(30):
                    self.db = DatabaseManager()
                    await self.db.init_database()
                    logger.info("✅ Database initialized successfully")
            except asyncio.TimeoutError:
                logger.error("❌ Database initialization timed out after 30 seconds")
                raise
            except Exception as e:
                logger.error(f"❌ Database initialization failed: {e}")
                raise
        
            # Initialize admin manager
            logger.info("🛡️ Initializing admin manager...")
            try:
                if self.db:
                    self.admin_manager = AdminManager(self)
                    await self.admin_manager.load_admin_roles()
                    logger.info("✅ Admin manager initialized")
                else:
                    logger.warning("⚠️ Skipping admin manager initialization (no database)")
            except Exception as e:
                logger.warning(f"⚠️ Admin manager initialization failed: {e}")

            # Initialize logging manager
            logger.info("📝 Initializing logging manager...")
            try:
                if self.db:
                    self.logging_manager = LoggingManager(self)
                    await self.logging_manager.load_log_configs()
                    logger.info("✅ Logging manager initialized")
                else:
                    logger.warning("⚠️ Skipping logging manager initialization (no database)")
            except Exception as e:
                logger.warning(f"⚠️ Logging manager initialization failed: {e}")

            # Initialize workflow manager
            logger.info("⚙️ Initializing workflow manager...")
            try:
                if self.db:
                    self.workflow_manager = WorkflowManager(self)
                    await self.workflow_manager.load_workflows()
                    logger.info("✅ Workflow manager initialized")
                else:
                    logger.warning("⚠️ Skipping workflow manager initialization (no database)")
            except Exception as e:
                logger.warning(f"⚠️ Workflow manager initialization failed: {e}")

            # Initialize ticket manager
            logger.info("🎫 Initializing ticket manager...")
            try:
                if self.db:
                    from utils.ticket_manager import TicketManager
                    self.ticket_manager = TicketManager(self)
                    await self.ticket_manager.load_ticket_configs()
                    logger.info("✅ Ticket manager initialized")
                else:
                    logger.warning("⚠️ Skipping ticket manager initialization (no database)")
            except Exception as e:
                logger.warning(f"⚠️ Ticket manager initialization failed: {e}")

            # Load cogs
            logger.info("🔧 Loading cogs...")
            try:
                await self.load_cogs()
                logger.info("✅ Cogs loaded successfully")
            except Exception as e:
                logger.warning(f"⚠️ Cog loading failed: {e}")

            logger.info("✅ Bot setup completed successfully!")

        except Exception as e:
            logger.error(f"❌ Error during setup: {e}")
            logger.exception("Full traceback:")
            raise
    
    async def load_cogs(self):
        """Load all cogs"""
        cogs = [
            'cogs.admin',
            'cogs.help',
            'cogs.setup',
            'cogs.tickets',  # This should work with our new tickets.py
            'cogs.reminders',
            'cogs.workflows',
            'cogs.roles',
            'cogs.meetings',
            'cogs.notifications',
            'cogs.logging',
            'cogs.privacy',
            'cogs.conversations',
            'cogs.intelligence',
            'cogs.integrations_google',
            'cogs.integrations_github',
            'cogs.integrations_notion',
            'cogs.integrations_trello'
        ]
        
        loaded_count = 0
        failed_count = 0
        
        for cog in cogs:
            try:
                logger.info(f"  • Loading {cog}...")
                await self.load_extension(cog)
                loaded_count += 1
                logger.info(f"  ✅ Loaded {cog}")
            except Exception as e:
                failed_count += 1
                logger.error(f"  ❌ Failed to load {cog}: {e}")
    
        logger.info(f"📦 Loaded {loaded_count}/{len(cogs)} cogs successfully")
        if failed_count > 0:
            logger.warning(f"⚠️ {failed_count} cogs failed to load")
    
    async def on_ready(self):
        """Called when the bot is ready"""
        logger.info(f"🚀 {self.user} is now online!")
        logger.info(f"📊 Connected to {len(self.guilds)} guilds")
        logger.info(f"👥 Serving {sum(guild.member_count for guild in self.guilds)} users")
        
        # Wait a moment for all cogs to fully initialize
        await asyncio.sleep(2)
        
        # Check available commands
        global_commands = self.tree.get_commands()
        logger.info(f"📋 Found {len(global_commands)} global commands available")
        
        if len(global_commands) > 0:
            logger.info("📝 Available commands:")
            for cmd in global_commands[:10]:  # Show first 10 commands
                logger.info(f"  • {cmd.name}: {cmd.description}")
            if len(global_commands) > 10:
                logger.info(f"  ... and {len(global_commands) - 10} more commands")
        else:
            logger.warning("⚠️ No commands found! This might indicate a problem with cog loading.")
        
        # Sync commands to all guilds first
        logger.info("🔄 Syncing commands to all guilds...")
        synced_guilds = 0
        failed_guilds = 0
        total_commands_synced = 0
        
        for guild in self.guilds:
            try:
                # Copy global commands to guild
                self.tree.copy_global_to(guild=guild)
                
                # Sync to guild
                synced = await self.tree.sync(guild=guild)
                synced_guilds += 1
                total_commands_synced += len(synced)
                logger.info(f"✅ Synced {len(synced)} commands to {guild.name}")
                
                # Log some command names for verification
                if len(synced) > 0:
                    sample_commands = [cmd.name for cmd in synced[:5]]
                    logger.info(f"  Sample commands: {', '.join(sample_commands)}")
                    
            except Exception as e:
                failed_guilds += 1
                logger.error(f"❌ Failed to sync commands to {guild.name}: {e}")
        
        # Only clear global commands if guild syncing was successful
        if synced_guilds > 0 and total_commands_synced > 0:
            logger.info("🧹 Clearing global commands (guild sync successful)...")
            try:
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
                logger.info("✅ Global commands cleared successfully")
            except Exception as e:
                logger.error(f"❌ Failed to clear global commands: {e}")
        else:
            logger.warning("⚠️ Keeping global commands as fallback (guild sync failed)")
            try:
                # Sync globally as fallback
                synced_global = await self.tree.sync()
                logger.info(f"🌐 Synced {len(synced_global)} commands globally as fallback")
            except Exception as e:
                logger.error(f"❌ Failed to sync global commands as fallback: {e}")
        
        logger.info(f"🎉 Command sync complete! {synced_guilds} guilds synced, {failed_guilds} failed")
        logger.info(f"📊 Total commands synced: {total_commands_synced}")
        
        # Set bot status
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | /help"
            )
            await self.change_presence(activity=activity, status=discord.Status.online)
        except Exception as e:
            logger.error(f"Failed to set bot status: {e}")
    
    async def on_message(self, message):
        """Handle message events for workflow triggers"""
        # Process commands first
        await self.process_commands(message)
        
        # Process workflow triggers
        if self.workflow_manager:
            try:
                await self.workflow_manager.process_message_triggers(message)
            except Exception as e:
                logger.error(f"Error processing workflow message triggers: {e}")
    
    async def on_member_join(self, member):
        """Handle member join events for workflow triggers"""
        if self.workflow_manager:
            try:
                await self.workflow_manager.process_member_join_triggers(member)
            except Exception as e:
                logger.error(f"Error processing workflow member join triggers: {e}")
    
    async def on_thread_create(self, thread):
        """Handle thread creation events for workflow triggers"""
        if self.workflow_manager:
            try:
                await self.workflow_manager.process_thread_create_triggers(thread)
            except Exception as e:
                logger.error(f"Error processing workflow thread create triggers: {e}")
    
    async def on_guild_channel_create(self, channel):
        """Handle channel creation events for workflow triggers"""
        if self.workflow_manager:
            try:
                await self.workflow_manager.process_channel_create_triggers(channel)
            except Exception as e:
                logger.error(f"Error processing workflow channel create triggers: {e}")
    
    async def on_guild_join(self, guild):
        """Called when the bot joins a new guild"""
        logger.info(f"📥 Joined new guild: {guild.name} (ID: {guild.id}) with {guild.member_count} members")
        
        # Sync commands to the new guild
        try:
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info(f"✅ Synced {len(synced)} commands to new guild {guild.name}")
        except Exception as e:
            logger.error(f"❌ Failed to sync commands to new guild {guild.name}: {e}")
        
        # Update status
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | /help"
            )
            await self.change_presence(activity=activity)
        except Exception as e:
            logger.error(f"Failed to update status: {e}")
    
    async def on_guild_remove(self, guild):
        """Called when the bot leaves a guild"""
        logger.info(f"📤 Left guild: {guild.name} (ID: {guild.id})")
        
        # Update status
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | /help"
            )
            await self.change_presence(activity=activity)
        except Exception as e:
            logger.error(f"Failed to update status: {e}")
    
    async def on_app_command_error(self, interaction: discord.Interaction, error):
        """Global error handler for slash commands"""
        logger.error(f"Slash command error in {interaction.command}: {error}")
        
        try:
            embed = discord.Embed(
                title="❌ Command Error",
                description=f"An error occurred: {str(error)}",
                color=0xFF0000
            )
            
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")
    
    async def close(self):
        """Clean shutdown"""
        global SHUTDOWN_REQUESTED
        
        # Only close if shutdown was requested
        if not SHUTDOWN_REQUESTED:
            logger.warning("🛑 Shutdown attempted but SHUTDOWN_REQUESTED is False - ignoring")
            return
            
        logger.info("🔄 Shutting down bot...")
        
        # Close database connection
        if self.db:
            await self.db.close()
        
        # Close the bot
        await super().close()
        logger.info("✅ Bot shutdown complete")

# Signal handlers
def handle_sigterm(signum, frame):
    global SHUTDOWN_REQUESTED
    logger.info("🛑 Received SIGTERM signal")
    SHUTDOWN_REQUESTED = True

def handle_sigint(signum, frame):
    global SHUTDOWN_REQUESTED
    logger.info("🛑 Received SIGINT signal")
    SHUTDOWN_REQUESTED = True

async def main():
    """Main function to run the bot"""
    global SHUTDOWN_REQUESTED
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigint)
    
    logger.info("🚀 Starting Discord Bot...")
    
    # Validate environment variables
    try:
        Settings.validate_required_env_vars()
        logger.info("✅ Environment variables validated")
    except ValueError as e:
        logger.error(f"❌ Environment validation failed: {e}")
        return
    
    # Create bot
    bot = DiscordBot()
    
    # Start the bot
    try:
        logger.info("🔄 Starting bot...")
        await bot.start(Settings.DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.error("❌ Invalid Discord token")
        SHUTDOWN_REQUESTED = True
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        logger.exception("Full traceback:")
    finally:
        # Only close if shutdown was requested
        if SHUTDOWN_REQUESTED and not bot.is_closed():
            logger.info("🔄 Performing final shutdown...")
            await bot.close()

if __name__ == "__main__":
    try:
        # Check Python version
        if sys.version_info < (3, 8):
            logger.error("❌ Python 3.8 or higher is required")
            sys.exit(1)
        
        # Run the bot
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
        SHUTDOWN_REQUESTED = True
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)
