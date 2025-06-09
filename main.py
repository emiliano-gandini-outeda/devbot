import discord
from discord.ext import commands
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config.settings import Settings
from utils.db import DatabaseManager
from utils.admin import AdminManager
from utils.ticket_manager import TicketManager
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
        self.ticket_manager = None
        self.logging_manager = None
        self.workflow_manager = None
        self.meeting_manager = None
        self.startup_complete = False
        
        # Add admin commands
        self.add_admin_commands()
    
    def add_admin_commands(self):
        """Add admin-only commands"""
        
        @self.command(name='admin_sync')
        @commands.is_owner()
        async def admin_sync(ctx):
            """Sync slash commands (Owner only)"""
            try:
                synced = await self.tree.sync()
                await ctx.send(f"✅ Synced {len(synced)} commands")
                logger.info(f"Admin sync: {len(synced)} commands synced")
            except Exception as e:
                await ctx.send(f"❌ Sync failed: {e}")
                logger.error(f"Admin sync failed: {e}")
        
        @self.command(name='admin_force_register')
        @commands.is_owner()
        async def admin_force_register(ctx):
            """Force register all commands from all cogs (Owner only)"""
            try:
                # Clear existing commands
                self.tree.clear_commands()
                
                # Re-add commands from all cogs
                for cog_name, cog in self.cogs.items():
                    for command in cog.get_app_commands():
                        if command not in self.tree.get_commands():
                            self.tree.add_command(command)
                
                # Sync commands
                synced = await self.tree.sync()
                await ctx.send(f"✅ Force registered and synced {len(synced)} commands from {len(self.cogs)} cogs")
                logger.info(f"Force register: {len(synced)} commands from {len(self.cogs)} cogs")
            except Exception as e:
                await ctx.send(f"❌ Force register failed: {e}")
                logger.error(f"Force register failed: {e}")
        
        @self.command(name='admin_debug')
        @commands.is_owner()
        async def admin_debug(ctx):
            """Debug bot status (Owner only)"""
            try:
                embed = discord.Embed(title="🔧 Bot Debug Info", color=0x5865F2)
                
                # Basic info
                embed.add_field(name="Guilds", value=len(self.guilds), inline=True)
                embed.add_field(name="Users", value=sum(g.member_count for g in self.guilds), inline=True)
                embed.add_field(name="Cogs", value=len(self.cogs), inline=True)
                
                # Commands
                slash_commands = len(self.tree.get_commands())
                embed.add_field(name="Slash Commands", value=slash_commands, inline=True)
                
                # Database
                db_status = "✅ Connected" if self.db and self.db.connection else "❌ Disconnected"
                embed.add_field(name="Database", value=db_status, inline=True)
                
                # Managers
                managers_status = []
                managers_status.append(f"Admin: {'✅' if self.admin_manager else '❌'}")
                managers_status.append(f"Ticket: {'✅' if self.ticket_manager else '❌'}")
                managers_status.append(f"Logging: {'✅' if self.logging_manager else '❌'}")
                managers_status.append(f"Workflow: {'✅' if self.workflow_manager else '❌'}")
                managers_status.append(f"Meeting: {'✅' if self.meeting_manager else '❌'}")
                
                embed.add_field(name="Managers", value="\n".join(managers_status), inline=False)
                
                # Cog list
                cog_list = "\n".join([f"• {name}" for name in self.cogs.keys()])
                if len(cog_list) > 1024:
                    cog_list = cog_list[:1021] + "..."
                embed.add_field(name="Loaded Cogs", value=cog_list or "None", inline=False)
                
                await ctx.send(embed=embed)
                
            except Exception as e:
                await ctx.send(f"❌ Debug failed: {e}")
                logger.error(f"Debug command failed: {e}")
        
        @self.command(name='admin_db_test')
        @commands.is_owner()
        async def admin_db_test(ctx):
            """Test database connection (Owner only)"""
            try:
                if not self.db:
                    await ctx.send("❌ Database manager not initialized")
                    return
                
                # Test connection
                success = await self.db.test_connection()
                
                if success:
                    # Test table verification
                    tables_ok = await self.db.verify_tables()
                    
                    embed = discord.Embed(title="🗄️ Database Test Results", color=0x57F287)
                    embed.add_field(name="Connection", value="✅ Success", inline=True)
                    embed.add_field(name="Tables", value="✅ Verified" if tables_ok else "❌ Issues", inline=True)
                    embed.add_field(name="Type", value="PostgreSQL" if self.db.is_postgresql else "SQLite", inline=True)
                    
                    await ctx.send(embed=embed)
                else:
                    await ctx.send("❌ Database connection test failed")
                    
            except Exception as e:
                await ctx.send(f"❌ Database test failed: {e}")
                logger.error(f"Database test failed: {e}")
        
        @self.command(name='admin_clear_global')
        @commands.is_owner()
        async def admin_clear_global(ctx):
            """Clear all global slash commands (Owner only)"""
            try:
                self.tree.clear_commands()
                synced = await self.tree.sync()
                await ctx.send(f"✅ Cleared all global commands. {len(synced)} commands remaining.")
                logger.info("Admin cleared all global commands")
            except Exception as e:
                await ctx.send(f"❌ Clear failed: {e}")
                logger.error(f"Clear global commands failed: {e}")
        
        @self.command(name='emergency_sync')
        @commands.is_owner()
        async def emergency_sync(ctx):
            """Emergency command sync with detailed output (Owner only)"""
            try:
                await ctx.send("🔄 Starting emergency sync...")
                
                # Get current commands
                current_commands = self.tree.get_commands()
                await ctx.send(f"📊 Current commands in tree: {len(current_commands)}")
                
                # List cogs and their commands
                cog_info = []
                total_cog_commands = 0
                
                for cog_name, cog in self.cogs.items():
                    cog_commands = cog.get_app_commands()
                    total_cog_commands += len(cog_commands)
                    cog_info.append(f"• {cog_name}: {len(cog_commands)} commands")
                
                if cog_info:
                    cog_text = "\n".join(cog_info)
                    if len(cog_text) > 1900:
                        cog_text = cog_text[:1900] + "..."
                    await ctx.send(f"📦 Cog commands:\n\`\`\`\n{cog_text}\n\`\`\`")
                
                await ctx.send(f"🔢 Total commands from cogs: {total_cog_commands}")
                
                # Sync
                synced = await self.tree.sync()
                await ctx.send(f"✅ Emergency sync complete: {len(synced)} commands synced")
                
                # List synced commands
                if synced:
                    synced_names = [cmd.name for cmd in synced]
                    synced_text = ", ".join(synced_names)
                    if len(synced_text) > 1900:
                        synced_text = synced_text[:1900] + "..."
                    await ctx.send(f"📋 Synced commands:\n\`\`\`\n{synced_text}\n\`\`\`")
                
            except Exception as e:
                await ctx.send(f"❌ Emergency sync failed: {e}")
                logger.error(f"Emergency sync failed: {e}")
    
    async def setup_hook(self):
        """Called when the bot is starting up"""
        logger.info("🤖 Starting Discord bot setup...")
        
        try:
            # Initialize database
            logger.info("📊 Initializing database...")
            self.db = DatabaseManager()
            await self.db.init_database()
            
            # Verify database tables
            tables_ok = await self.db.verify_tables()
            if not tables_ok:
                logger.error("❌ Database tables verification failed")
                return
            
            # Test database connection
            connection_ok = await self.db.test_connection()
            if not connection_ok:
                logger.error("❌ Database connection test failed")
                return
            
            # Initialize managers
            logger.info("🛡️ Initializing managers...")
            
            # Admin manager
            self.admin_manager = AdminManager(self)
            await self.admin_manager.load_admin_roles()
            
            # Ticket manager
            self.ticket_manager = TicketManager(self)
            await self.ticket_manager.load_ticket_configs()
            
            # Logging manager
            self.logging_manager = LoggingManager(self)
            await self.logging_manager.load_log_configs()
            
            # Workflow manager
            self.workflow_manager = WorkflowManager(self)
            await self.workflow_manager.load_workflows()
            
            logger.info("✅ All managers initialized successfully")
            
            # Load cogs
            logger.info("🔧 Loading cogs...")
            await self.load_cogs()
            
            # Sync commands
            logger.info("🔄 Syncing slash commands...")
            try:
                synced = await self.tree.sync()
                logger.info(f"✅ Synced {len(synced)} slash commands")
            except Exception as e:
                logger.error(f"❌ Failed to sync commands: {e}")
            
            self.startup_complete = True
            logger.info("✅ Bot setup completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Critical error during setup: {e}")
            logger.exception("Full traceback:")
            await self.close()
    
    async def load_cogs(self):
        """Load all cogs"""
        cogs = [
            'cogs.admin',
            'cogs.help',
            'cogs.setup',
            'cogs.tickets',
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
            'cogs.integrations_notion',
            'cogs.integrations_trello',
            'cogs.integrations_github'
        ]
        
        loaded_count = 0
        failed_count = 0
        
        for cog in cogs:
            try:
                await self.load_extension(cog)
                loaded_count += 1
                logger.info(f"✅ Loaded {cog}")
            except Exception as e:
                failed_count += 1
                logger.error(f"❌ Failed to load {cog}: {e}")
                logger.exception(f"Full traceback for {cog}:")
        
        logger.info(f"📦 Loaded {loaded_count}/{len(cogs)} cogs successfully")
        if failed_count > 0:
            logger.warning(f"⚠️ {failed_count} cogs failed to load")
    
    async def on_ready(self):
        """Called when the bot is ready"""
        if not self.startup_complete:
            logger.warning("⚠️ Bot ready but startup not complete")
            return
        
        logger.info(f"🚀 {self.user} is now online!")
        logger.info(f"📊 Connected to {len(self.guilds)} guilds")
        logger.info(f"👥 Serving {sum(guild.member_count for guild in self.guilds)} users")
        logger.info(f"⚡ {len(self.tree.get_commands())} slash commands available")
        
        # Set bot status
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | /help"
            )
            await self.change_presence(activity=activity, status=discord.Status.online)
        except Exception as e:
            logger.error(f"Failed to set bot status: {e}")
    
    async def on_guild_join(self, guild):
        """Called when the bot joins a new guild"""
        logger.info(f"📥 Joined new guild: {guild.name} (ID: {guild.id}) with {guild.member_count} members")
        
        # Update status
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | /help"
            )
            await self.change_presence(activity=activity)
        except Exception as e:
            logger.error(f"Failed to update status: {e}")
        
        # Send welcome message if possible
        try:
            if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                embed = discord.Embed(
                    title="👋 Thanks for adding me!",
                    description="I'm a powerful Discord bot with many features to help manage your server.",
                    color=0x5865F2
                )
                embed.add_field(
                    name="🚀 Getting Started",
                    value="Use `/help` to see all available commands\nUse `/ticket-setup` to configure the ticket system",
                    inline=False
                )
                embed.add_field(
                    name="🔧 Admin Setup",
                    value="Use `/add-admin-role` to give roles admin access to bot commands",
                    inline=False
                )
                embed.set_footer(text="Powered by Railway 🚄")
                
                await guild.system_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to send welcome message to {guild.name}: {e}")
    
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
    
    async def on_message(self, message):
        """Handle incoming messages"""
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Process workflow triggers
        if self.workflow_manager and message.guild:
            try:
                await self.workflow_manager.process_message_triggers(message)
            except Exception as e:
                logger.error(f"Error processing workflow triggers: {e}")
        
        # Process commands
        await self.process_commands(message)
    
    async def on_member_join(self, member):
        """Handle member join events"""
        logger.info(f"👤 {member} joined {member.guild.name}")
        
        # Process workflow triggers
        if self.workflow_manager:
            try:
                await self.workflow_manager.process_member_join_triggers(member)
            except Exception as e:
                logger.error(f"Error processing member join workflow triggers: {e}")
        
        # Log the event
        if self.logging_manager:
            try:
                await self.logging_manager.log_member_join(member)
            except Exception as e:
                logger.error(f"Error logging member join: {e}")
    
    async def on_member_remove(self, member):
        """Handle member leave events"""
        logger.info(f"👤 {member} left {member.guild.name}")
        
        # Log the event
        if self.logging_manager:
            try:
                await self.logging_manager.log_member_leave(member)
            except Exception as e:
                logger.error(f"Error logging member leave: {e}")
    
    async def on_thread_create(self, thread):
        """Handle thread creation events"""
        logger.info(f"🧵 Thread created: {thread.name} in {thread.guild.name}")
        
        # Process workflow triggers
        if self.workflow_manager:
            try:
                await self.workflow_manager.process_thread_create_triggers(thread)
            except Exception as e:
                logger.error(f"Error processing thread create workflow triggers: {e}")
    
    async def on_guild_channel_create(self, channel):
        """Handle channel creation events"""
        logger.info(f"📝 Channel created: {channel.name} in {channel.guild.name}")
        
        # Process workflow triggers
        if self.workflow_manager:
            try:
                await self.workflow_manager.process_channel_create_triggers(channel)
            except Exception as e:
                logger.error(f"Error processing channel create workflow triggers: {e}")
    
    async def on_command_error(self, ctx, error):
        """Global error handler for prefix commands"""
        if isinstance(error, commands.CommandNotFound):
            return  # Ignore unknown commands
        
        if isinstance(error, commands.NotOwner):
            await ctx.send("❌ This command is restricted to the bot owner.")
            return
        
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command.")
            return
        
        logger.error(f"Command error in {ctx.command}: {error}")
        
        try:
            embed = discord.Embed(
                title="❌ Command Error",
                description=f"An error occurred: {str(error)}",
                color=0xFF0000
            )
            await ctx.send(embed=embed)
        except:
            pass  # Ignore if we can't send the error message
    
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
        logger.info("🔄 Shutting down bot...")
        
        # Close database connection
        if self.db:
            await self.db.close()
        
        # Close the bot
        await super().close()
        logger.info("✅ Bot shutdown complete")

async def main():
    """Main function to run the bot"""
    logger.info("🚀 Starting Discord Bot...")
    
    # Validate environment variables
    try:
        Settings.validate_required_env_vars()
        logger.info("✅ Environment variables validated")
    except ValueError as e:
        logger.error(f"❌ Environment validation failed: {e}")
        return
    
    # Create and run bot
    bot = DiscordBot()
    
    try:
        # Add a timeout to prevent hanging
        async with asyncio.timeout(120):  # 2 minute timeout for startup
            await bot.start(Settings.DISCORD_TOKEN)
    except asyncio.TimeoutError:
        logger.error("❌ Bot startup timed out after 2 minutes")
        await bot.close()
    except discord.LoginFailure:
        logger.error("❌ Invalid Discord token")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        logger.exception("Full traceback:")
    finally:
        if not bot.is_closed():
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
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)
