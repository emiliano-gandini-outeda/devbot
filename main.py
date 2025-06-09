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
        self.synced = False  # Track if commands have been synced
    
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
            failed_cogs = []
            
            for cog in cogs:
                try:
                    await self.load_extension(cog)
                    loaded_cogs.append(cog)
                    logger.info(f"✅ Loaded cog: {cog}")
                except Exception as e:
                    failed_cogs.append(cog)
                    logger.error(f"❌ Failed to load cog {cog}: {e}", exc_info=True)

            logger.info(f"Loaded {len(loaded_cogs)}/{len(cogs)} cogs successfully")
            
            if failed_cogs:
                logger.warning(f"Failed to load cogs: {failed_cogs}")
            
            # Wait a moment for all cogs to fully register their commands
            await asyncio.sleep(1)
            
            # Log command registration status
            all_commands = self.tree.get_commands()
            logger.info(f"Total registered slash commands after cog loading: {len(all_commands)}")
            
            for cmd in all_commands:
                logger.debug(f"Registered command: /{cmd.name}")
                
            logger.info("Setup hook completed successfully")
                
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}", exc_info=True)
    
    async def on_ready(self):
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        
        # Only sync once when bot is ready
        if not self.synced:
            await self.sync_commands_to_all_guilds()
            self.synced = True
        
        logger.info(f'Bot deployment successful! 🚀')

    async def sync_commands_to_all_guilds(self):
        """Sync commands to all guilds with proper error handling and rate limiting"""
        try:
            # Get all registered commands
            all_commands = self.tree.get_commands()
            logger.info(f"Starting sync of {len(all_commands)} commands to {len(self.guilds)} guilds...")
            
            if len(all_commands) == 0:
                logger.warning("⚠️ No commands found to sync! Check if cogs loaded properly.")
                return
            
            # Log command names for debugging
            command_names = [cmd.name for cmd in all_commands]
            logger.info(f"Commands to sync: {', '.join(command_names)}")
            
            total_synced = 0
            successful_guilds = 0
            failed_guilds = 0
            
            for guild in self.guilds:
                try:
                    logger.info(f"Syncing commands to guild: {guild.name} ({guild.id})")
                    
                    # Sync commands to this specific guild
                    synced = await self.tree.sync(guild=guild)
                    
                    if len(synced) > 0:
                        total_synced += len(synced)
                        successful_guilds += 1
                        logger.info(f"✅ Synced {len(synced)} commands to guild: {guild.name}")
                        
                        # Log synced command names for verification
                        synced_names = [cmd.name for cmd in synced]
                        logger.debug(f"   Commands synced: {', '.join(synced_names)}")
                    else:
                        logger.warning(f"⚠️ Synced 0 commands to guild: {guild.name} - This may indicate an issue")
                    
                    # Rate limiting: Discord allows 200 requests per 10 minutes for command sync
                    # Adding a small delay to be safe
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    failed_guilds += 1
                    logger.error(f"❌ Failed to sync commands to guild {guild.name} ({guild.id}): {e}")
                    
                    # Continue with other guilds even if one fails
                    continue
            
            # Summary
            logger.info(f"🎉 Command sync completed!")
            logger.info(f"   Total commands synced: {total_synced}")
            logger.info(f"   Successful guilds: {successful_guilds}/{len(self.guilds)}")
            logger.info(f"   Failed guilds: {failed_guilds}")
            
            if failed_guilds > 0:
                logger.warning(f"⚠️ {failed_guilds} guilds failed to sync. Check logs above for details.")
            
        except Exception as e:
            logger.error(f"❌ Critical error during command sync: {e}", exc_info=True)

    # Enhanced sync command for debugging
    @commands.command(name='sync')
    @commands.is_owner()
    async def sync_commands(self, ctx):
        """Manually sync slash commands to current guild (Owner only)"""
        try:
            await ctx.send("🔄 Starting guild command sync process...")
            
            # Check registered commands first
            all_commands = self.tree.get_commands()
            await ctx.send(f"📋 Found {len(all_commands)} registered commands in tree")
            
            if len(all_commands) == 0:
                await ctx.send("⚠️ No commands found! Check if cogs are loaded properly.")
                return
            
            # Sync to current guild
            synced = await self.tree.sync(guild=ctx.guild)
            
            if len(synced) > 0:
                await ctx.send(f'✅ Successfully synced {len(synced)} commands to {ctx.guild.name}!')
                
                # List synced commands
                command_list = "\n".join([f"- /{cmd.name}: {cmd.description}" for cmd in synced])
                if len(command_list) < 1800:  # Leave room for formatting
                    await ctx.send(f"```\nSynced commands:\n{command_list}\n```")
                else:
                    # Split into multiple messages if too long
                    command_names = [cmd.name for cmd in synced]
                    await ctx.send(f"```\nSynced commands: {', '.join(command_names)}\n```")
            else:
                await ctx.send("⚠️ Synced 0 commands - this indicates a problem with command registration")
            
        except Exception as e:
            await ctx.send(f'❌ Failed to sync commands: {e}')
            logger.error("Manual command sync failed", exc_info=True)

    @commands.command(name='sync_all')
    @commands.is_owner()
    async def sync_all_guilds(self, ctx):
        """Manually sync slash commands to all guilds (Owner only)"""
        try:
            await ctx.send("🔄 Starting sync to all guilds...")
            
            # Check registered commands
            all_commands = self.tree.get_commands()
            await ctx.send(f"📋 Found {len(all_commands)} registered commands")
            
            if len(all_commands) == 0:
                await ctx.send("⚠️ No commands to sync! Check cog loading.")
                return
            
            total_synced = 0
            successful = 0
            failed = 0
            
            for guild in self.guilds:
                try:
                    synced = await self.tree.sync(guild=guild)
                    total_synced += len(synced)
                    successful += 1
                    await ctx.send(f"✅ {guild.name}: {len(synced)} commands")
                    await asyncio.sleep(0.3)  # Rate limit protection
                except Exception as e:
                    failed += 1
                    await ctx.send(f"❌ {guild.name}: {str(e)[:100]}")
            
            await ctx.send(f"🎉 Completed! Total: {total_synced} commands across {successful} guilds ({failed} failed)")
            
        except Exception as e:
            await ctx.send(f'❌ Failed to sync commands: {e}')
            logger.error("Sync all command failed", exc_info=True)

    @commands.command(name='check_commands')
    @commands.is_owner()
    async def check_commands(self, ctx):
        """Check what commands are registered (Owner only)"""
        try:
            all_commands = self.tree.get_commands()
            await ctx.send(f"📋 Total registered commands: {len(all_commands)}")
            
            if len(all_commands) == 0:
                await ctx.send("⚠️ No commands registered! This explains why sync returns 0.")
                
                # Check loaded cogs
                loaded_cogs = list(self.cogs.keys())
                await ctx.send(f"Loaded cogs ({len(loaded_cogs)}): {', '.join(loaded_cogs)}")
                return
            
            # Group commands by cog
            command_info = {}
            for cmd in all_commands:
                cog_name = getattr(cmd, 'module', 'Unknown')
                if cog_name not in command_info:
                    command_info[cog_name] = []
                command_info[cog_name].append(cmd.name)
            
            response = "```\nRegistered Commands by Cog:\n"
            for cog, commands in command_info.items():
                response += f"\n{cog}:\n"
                for cmd in commands:
                    response += f"  - /{cmd}\n"
            response += "```"
            
            if len(response) < 2000:
                await ctx.send(response)
            else:
                # Send command names only if too long
                command_names = [cmd.name for cmd in all_commands]
                await ctx.send(f"```\nAll commands: {', '.join(command_names)}\n```")
                
        except Exception as e:
            await ctx.send(f'❌ Error checking commands: {e}')
            logger.error("Check commands failed", exc_info=True)
    
    async def on_error(self, event, *args, **kwargs):
        logger.error(f'An error occurred in {event}', exc_info=True)

    async def on_guild_join(self, guild):
        """Sync commands when bot joins a new guild"""
        try:
            logger.info(f"Bot joined new guild: {guild.name} ({guild.id})")
            
            # Wait a moment to ensure bot is fully ready
            await asyncio.sleep(2)
            
            synced = await self.tree.sync(guild=guild)
            logger.info(f"✅ Synced {len(synced)} commands to new guild: {guild.name}")
            
            if len(synced) == 0:
                logger.warning(f"⚠️ Synced 0 commands to new guild {guild.name} - may indicate an issue")
                
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
