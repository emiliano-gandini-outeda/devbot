import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import aiohttp
import asyncpg
import json
import re
import os
import traceback
from datetime import datetime, timedelta
from typing import Optional, List, Union, Literal
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('discord-bot')

# Environment variables with better error handling
TOKEN = os.environ.get('DISCORD_TOKEN')
APP_ID = os.environ.get('APP_ID')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')

if not TOKEN:
    logger.error("DISCORD_TOKEN environment variable is required")
    exit(1)

if not APP_ID:
    logger.error("APP_ID environment variable is required")
    exit(1)

if not DATABASE_URL:
    logger.warning("DATABASE_URL environment variable not set. Bot will run with limited functionality.")

# Constants
PRIORITY_CHOICES = [
    app_commands.Choice(name="Low", value="Low"),
    app_commands.Choice(name="Medium", value="Medium"),
    app_commands.Choice(name="High", value="High")
]

STATUS_CHOICES = [
    app_commands.Choice(name="All", value="all"),
    app_commands.Choice(name="Open", value="open"),
    app_commands.Choice(name="Closed", value="closed")
]

async def safe_db_execute(bot, operation_func):
    """Safely execute a database operation with proper error handling"""
    if not bot.db_pool:
        raise Exception("Database connection not available. Please contact an administrator.")
    
    try:
        async with bot.db_pool.acquire() as conn:
            return await operation_func(conn)
    except Exception as e:
        logger.error(f"Database operation failed: {e}")
        # Try to ensure connection and retry once
        if hasattr(bot, 'ensure_database_connection'):
            if await bot.ensure_database_connection():
                try:
                    async with bot.db_pool.acquire() as conn:
                        return await operation_func(conn)
                except Exception as retry_error:
                    logger.error(f"Database operation failed after reconnection: {retry_error}")
                    raise Exception("Database operation failed. Please try again later.")
            else:
                raise Exception("Database connection unavailable. Please contact an administrator.")
        else:
            raise Exception("Database operation failed. Please try again later.")

class DevBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix='!', intents=intents, application_id=APP_ID)
        self.db_pool = None
        
    async def setup_hook(self):
        # Initialize database connection pool with retry logic
        max_retries = 5
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                # Parse DATABASE_URL to handle different formats
                if DATABASE_URL:
                    # Handle Railway's DATABASE_URL format
                    if DATABASE_URL.startswith('postgresql://'):
                        # Convert postgresql:// to postgres:// for asyncpg compatibility
                        db_url = DATABASE_URL.replace('postgresql://', 'postgres://', 1)
                    else:
                        db_url = DATABASE_URL
                    
                    self.db_pool = await asyncpg.create_pool(
                        db_url,
                        min_size=1,
                        max_size=10,
                        command_timeout=60,
                        server_settings={
                            'jit': 'off'
                        }
                    )
                    logger.info("Database connection pool created successfully")
                    await self.init_db()
                    break
                else:
                    logger.error("DATABASE_URL environment variable not set")
                    break
            except Exception as e:
                logger.error(f"Failed to create database connection pool (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error("Failed to connect to database after all retries. Bot will run with limited functionality.")
                    self.db_pool = None
        
        # Add command groups
        await self.add_cog(TicketCommands(self))
        await self.add_cog(GitHubCommands(self))
        await self.add_cog(ReminderCommands(self))
        await self.add_cog(MeetingCommands(self))
        await self.add_cog(NotificationCommands(self))
        await self.add_cog(RoleCommands(self))
        await self.add_cog(UserCommands(self))
        await self.add_cog(ConversationCommands(self))
        await self.add_cog(AICommands(self))
        await self.add_cog(WorkflowCommands(self))
        await self.add_cog(IntegrationCommands(self))
        await self.add_cog(AdminCommands(self))
        await self.add_cog(LogCommands(self))
        await self.add_cog(PrivacyCommands(self))
        await self.add_cog(HelpCommands(self))
        
        # Start background tasks only if database is available
        if self.db_pool:
            self.github_checker.start()
            self.reminder_checker.start()
            logger.info("Background tasks started")
        else:
            logger.warning("Background tasks not started due to database connection failure")
        
        # Sync commands with Discord
        logger.info("Syncing commands...")
        try:
            for guild in self.guilds:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            logger.info("Commands synced successfully")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
        
    async def on_ready(self):
        logger.info(f'{self.user} is ready!')
        logger.info(f'Connected to {len(self.guilds)} guilds')
        
    async def on_guild_join(self, guild):
        # Sync commands to the new guild
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
        
    async def init_db(self):
        """Initialize database tables if they don't exist and handle migrations"""
        if not self.db_pool:
            logger.error("Cannot initialize database: no connection pool")
            return
        
        try:
            async with self.db_pool.acquire() as conn:
                # Create tables with current schema
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS tickets (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        creator_id BIGINT NOT NULL,
                        channel_id BIGINT,
                        status TEXT DEFAULT 'open',
                        priority TEXT DEFAULT 'Medium',
                        is_private BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        assigned_users TEXT,
                        guild_id BIGINT NOT NULL
                    )
                ''')
            
                # Create reminders table with proper schema
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS reminders (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        message TEXT NOT NULL,
                        remind_time TIMESTAMP NOT NULL,
                        channel_id BIGINT,
                        send_dm BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
            
                # Handle schema migrations for existing tables
                await self.migrate_schema(conn)
            
                # Create indexes for performance
                await self.create_indexes(conn)
            
                # Continue with other tables...
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS keywords (
                        user_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        keyword TEXT NOT NULL,
                        PRIMARY KEY (user_id, guild_id, keyword)
                    )
                ''')
            
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS github_repos (
                        guild_id BIGINT NOT NULL,
                        repo_name TEXT NOT NULL,
                        channel_id BIGINT NOT NULL,
                        last_commit_sha TEXT,
                        star_count INTEGER DEFAULT 0,
                        fork_count INTEGER DEFAULT 0,
                        branches TEXT,
                        last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (guild_id, repo_name)
                    )
                ''')
            
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS meetings (
                        id TEXT PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        name TEXT NOT NULL,
                        description TEXT,
                        meeting_time TIMESTAMP NOT NULL,
                        voice_channel_id BIGINT,
                        creator_id BIGINT NOT NULL,
                        participants TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
            
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS workflows (
                        guild_id BIGINT NOT NULL,
                        name TEXT NOT NULL,
                        trigger_type TEXT NOT NULL,
                        trigger_value TEXT,
                        trigger_channel_id BIGINT,
                        actions TEXT NOT NULL,
                        log_channel_id BIGINT,
                        is_enabled BOOLEAN DEFAULT TRUE,
                        PRIMARY KEY (guild_id, name)
                    )
                ''')
            
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS admin_roles (
                        guild_id BIGINT NOT NULL,
                        role_id BIGINT NOT NULL,
                        PRIMARY KEY (guild_id, role_id)
                    )
                ''')
            
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS server_config (
                        guild_id BIGINT PRIMARY KEY,
                        ticket_category_id BIGINT,
                        ticket_transcript_channel_id BIGINT,
                        github_channel_id BIGINT,
                        reminder_channel_id BIGINT,
                        meeting_announcement_channel_id BIGINT,
                        meeting_voice_channel_id BIGINT,
                        log_channel_id BIGINT,
                        thread_log_channel_id BIGINT
                    )
                ''')
            
            logger.info("Database tables initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise e

    async def migrate_schema(self, conn):
        """Handle database schema migrations"""
        try:
            # Check if remind_time column exists in reminders table
            column_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'reminders' 
                    AND column_name = 'remind_time'
                )
            """)
        
            if not column_exists:
                logger.info("Adding missing remind_time column to reminders table")
            
                # Add the remind_time column
                await conn.execute("""
                    ALTER TABLE reminders 
                    ADD COLUMN remind_time TIMESTAMP
                """)
            
                # For existing records without remind_time, set a default value
                # (24 hours from creation time or current time)
                await conn.execute("""
                    UPDATE reminders 
                    SET remind_time = COALESCE(created_at + INTERVAL '24 hours', CURRENT_TIMESTAMP + INTERVAL '24 hours')
                    WHERE remind_time IS NULL
                """)
            
                # Make the column NOT NULL after setting values
                await conn.execute("""
                    ALTER TABLE reminders 
                    ALTER COLUMN remind_time SET NOT NULL
                """)
            
                logger.info("Successfully added remind_time column to reminders table")
        
            # Check for other missing columns in other tables
            await self.migrate_other_tables(conn)
        
        except Exception as e:
            logger.error(f"Error during schema migration: {e}")
            raise e

    async def migrate_other_tables(self, conn):
        """Handle migrations for other tables if needed"""
        try:
            # Check if meetings table has meeting_time column
            meeting_time_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'meetings' 
                    AND column_name = 'meeting_time'
                )
            """)
        
            if not meeting_time_exists:
                logger.info("Adding missing meeting_time column to meetings table")
                await conn.execute("""
                    ALTER TABLE meetings 
                    ADD COLUMN meeting_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP + INTERVAL '1 hour'
                """)
        
            # Add any other column migrations here as needed
        
        except Exception as e:
            logger.error(f"Error during table migrations: {e}")
            # Don't raise here to prevent blocking other migrations

    async def create_indexes(self, conn):
        """Create database indexes for performance"""
        try:
            # Index on remind_time for efficient reminder queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_reminders_remind_time 
                ON reminders(remind_time)
            """)
        
            # Index on user_id and guild_id for user-specific queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_reminders_user_guild 
                ON reminders(user_id, guild_id)
            """)
        
            # Index on meeting_time for meeting queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_meetings_meeting_time 
                ON meetings(meeting_time)
            """)
        
            # Index on keywords for notification queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_keywords_guild_keyword 
                ON keywords(guild_id, keyword)
            """)
        
            # Index on github repos for tracking queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_github_repos_last_checked 
                ON github_repos(last_checked)
            """)
        
            logger.info("Database indexes created successfully")
        
        except Exception as e:
            logger.error(f"Error creating indexes: {e}")
            # Don't raise here as indexes are performance optimizations
    
    async def verify_database_schema(self):
        """Verify that all required database columns exist"""
        if not self.db_pool:
            return False
            
        try:
            async with self.db_pool.acquire() as conn:
                # Define required columns for each table
                required_schema = {
                    'reminders': ['id', 'user_id', 'guild_id', 'message', 'remind_time', 'channel_id', 'send_dm', 'created_at'],
                    'tickets': ['id', 'title', 'description', 'creator_id', 'channel_id', 'status', 'priority', 'is_private', 'created_at', 'assigned_users', 'guild_id'],
                    'meetings': ['id', 'guild_id', 'name', 'description', 'meeting_time', 'voice_channel_id', 'creator_id', 'participants', 'created_at'],
                    'keywords': ['user_id', 'guild_id', 'keyword'],
                    'github_repos': ['guild_id', 'repo_name', 'channel_id', 'last_commit_sha', 'star_count', 'fork_count', 'branches', 'last_checked'],
                    'workflows': ['guild_id', 'name', 'trigger_type', 'trigger_value', 'trigger_channel_id', 'actions', 'log_channel_id', 'is_enabled'],
                    'admin_roles': ['guild_id', 'role_id'],
                    'server_config': ['guild_id', 'ticket_category_id', 'ticket_transcript_channel_id', 'github_channel_id', 'reminder_channel_id', 'meeting_announcement_channel_id', 'meeting_voice_channel_id', 'log_channel_id', 'thread_log_channel_id']
                }
                
                schema_issues = []
                
                for table_name, required_columns in required_schema.items():
                    # Check if table exists
                    table_exists = await conn.fetchval("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_name = $1
                        )
                    """, table_name)
                    
                    if not table_exists:
                        schema_issues.append(f"Table '{table_name}' does not exist")
                        continue
                    
                    # Check if all required columns exist
                    for column_name in required_columns:
                        column_exists = await conn.fetchval("""
                            SELECT EXISTS (
                                SELECT 1 FROM information_schema.columns 
                                WHERE table_name = $1 AND column_name = $2
                            )
                        """, table_name, column_name)
                        
                        if not column_exists:
                            schema_issues.append(f"Column '{column_name}' missing from table '{table_name}'")
                
                if schema_issues:
                    logger.error("Database schema issues found:")
                    for issue in schema_issues:
                        logger.error(f"  - {issue}")
                    return False
                else:
                    logger.info("Database schema verification passed")
                    return True
                    
        except Exception as e:
            logger.error(f"Error verifying database schema: {e}")
            return False

    async def fix_reminder_data_types(self, conn):
        """Ensure remind_time column has proper data type and constraints"""
        try:
            # Check current data type of remind_time column
            current_type = await conn.fetchval("""
                SELECT data_type FROM information_schema.columns 
                WHERE table_name = 'reminders' AND column_name = 'remind_time'
            """)
            
            if current_type and current_type.lower() not in ['timestamp', 'timestamp without time zone', 'timestamp with time zone']:
                logger.info(f"Converting remind_time column from {current_type} to TIMESTAMP")
                
                # Create a backup column first
                await conn.execute("ALTER TABLE reminders ADD COLUMN remind_time_backup TEXT")
                await conn.execute("UPDATE reminders SET remind_time_backup = remind_time::TEXT")
                
                # Drop and recreate the column with correct type
                await conn.execute("ALTER TABLE reminders DROP COLUMN remind_time")
                await conn.execute("ALTER TABLE reminders ADD COLUMN remind_time TIMESTAMP")
                
                # Try to convert the data back
                await conn.execute("""
                    UPDATE reminders 
                    SET remind_time = remind_time_backup::TIMESTAMP 
                    WHERE remind_time_backup IS NOT NULL
                """)
                
                # Clean up backup column
                await conn.execute("ALTER TABLE reminders DROP COLUMN remind_time_backup")
                
                # Make NOT NULL
                await conn.execute("ALTER TABLE reminders ALTER COLUMN remind_time SET NOT NULL")
                
                logger.info("Successfully converted remind_time column to TIMESTAMP")
                
        except Exception as e:
            logger.error(f"Error fixing remind_time data type: {e}")
            # Don't raise as this is a recovery operation
    
    @tasks.loop(minutes=30)
    async def github_checker(self):
        """Check GitHub repositories for updates every 30 minutes"""
        if not self.is_ready() or not self.db_pool:
            return
            
        try:
            async with self.db_pool.acquire() as conn:
                repos = await conn.fetch("SELECT * FROM github_repos")
                
                for repo in repos:
                    guild_id = repo['guild_id']
                    repo_name = repo['repo_name']
                    channel_id = repo['channel_id']
                    last_commit_sha = repo['last_commit_sha']
                    stored_star_count = repo['star_count']
                    stored_fork_count = repo['fork_count']
                    stored_branches = json.loads(repo['branches']) if repo['branches'] else []
                    
                    guild = self.get_guild(guild_id)
                    if not guild:
                        continue
                        
                    channel = guild.get_channel(channel_id)
                    if not channel:
                        continue
                    
                    # Fetch current repo data from GitHub API
                    headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
                    
                    async with aiohttp.ClientSession() as session:
                        # Get repo info
                        async with session.get(f"https://api.github.com/repos/{repo_name}", headers=headers) as response:
                            if response.status != 200:
                                continue
                            repo_data = await response.json()
                            
                            current_star_count = repo_data.get('stargazers_count', 0)
                            current_fork_count = repo_data.get('forks_count', 0)
                            
                            # Check for new stars
                            if current_star_count > stored_star_count:
                                # We can't get who starred, just the count difference
                                star_diff = current_star_count - stored_star_count
                                await channel.send(f"⭐ +{star_diff} star{'s' if star_diff > 1 else ''} on {repo_name} (Total: {current_star_count} stars)")
                            
                            # Check for new forks
                            if current_fork_count > stored_fork_count:
                                fork_diff = current_fork_count - stored_fork_count
                                await channel.send(f"🍴 Repository {repo_name} has {fork_diff} new fork{'s' if fork_diff > 1 else ''} (Total: {current_fork_count} forks)")
                        
                        # Get branches
                        async with session.get(f"https://api.github.com/repos/{repo_name}/branches", headers=headers) as response:
                            if response.status != 200:
                                continue
                            branches_data = await response.json()
                            
                            current_branches = [branch['name'] for branch in branches_data]
                            
                            # Check for new branches
                            new_branches = set(current_branches) - set(stored_branches)
                            for branch in new_branches:
                                await channel.send(f"🌿 New branch `{branch}` created in {repo_name}")
                        
                        # Get latest commits
                        async with session.get(f"https://api.github.com/repos/{repo_name}/commits", headers=headers) as response:
                            if response.status != 200:
                                continue
                            commits_data = await response.json()
                            
                            if commits_data and last_commit_sha:
                                latest_commit = commits_data[0]
                                latest_sha = latest_commit['sha']
                                
                                if latest_sha != last_commit_sha:
                                    commit_author = latest_commit['commit']['author']['name']
                                    commit_message = latest_commit['commit']['message'].split('\n')[0]  # First line only
                                    commit_branch = latest_commit.get('branch', 'main')  # Default to main if not specified
                                    
                                    await channel.send(f"📝 New commit on `{commit_branch}` by {commit_author}: '{commit_message}'")
                    
                    # Update stored data
                    await conn.execute(
                        """
                        UPDATE github_repos 
                        SET star_count = $1, fork_count = $2, branches = $3, last_commit_sha = $4, last_checked = CURRENT_TIMESTAMP
                        WHERE guild_id = $5 AND repo_name = $6
                        """,
                        current_star_count, current_fork_count, json.dumps(current_branches),
                        commits_data[0]['sha'] if commits_data else last_commit_sha,
                        guild_id, repo_name
                    )
        except Exception as e:
            logger.error(f"Error in github_checker task: {e}")
            traceback.print_exc()
    
    @github_checker.before_loop
    async def before_github_checker(self):
        await self.wait_until_ready()
    
    @tasks.loop(minutes=1)
    async def reminder_checker(self):
        """Check for due reminders every minute"""
        if not self.is_ready() or not self.db_pool:
            return
            
        try:
            current_time = datetime.utcnow()
            
            async with self.db_pool.acquire() as conn:
                # Get all reminders that are due
                reminders = await conn.fetch(
                    "SELECT * FROM reminders WHERE remind_time <= $1",
                    current_time
                )
                
                for reminder in reminders:
                    user_id = reminder['user_id']
                    guild_id = reminder['guild_id']
                    message = reminder['message']
                    channel_id = reminder['channel_id']
                    send_dm = reminder['send_dm']
                    
                    guild = self.get_guild(guild_id)
                    if not guild:
                        continue
                    
                    user = guild.get_member(user_id)
                    if not user:
                        continue
                    
                    # Create reminder embed
                    embed = discord.Embed(
                        title="⏰ Reminder",
                        description=message,
                        color=discord.Color.blue(),
                        timestamp=current_time
                    )
                    embed.set_footer(text=f"Reminder set in {guild.name}")
                    
                    # Send DM if requested
                    if send_dm:
                        try:
                            await user.send(embed=embed)
                        except discord.Forbidden:
                            # Can't DM user, try to send to channel instead
                            if channel_id:
                                channel = guild.get_channel(channel_id)
                                if channel:
                                    await channel.send(content=f"{user.mention}", embed=embed)
                    
                    # Send to channel if specified
                    if channel_id:
                        channel = guild.get_channel(channel_id)
                        if channel:
                            await channel.send(content=f"{user.mention}", embed=embed)
                    
                    # Delete the reminder
                    await conn.execute("DELETE FROM reminders WHERE id = $1", reminder['id'])
        except Exception as e:
            logger.error(f"Error in reminder_checker task: {e}")
            traceback.print_exc()
    
    @reminder_checker.before_loop
    async def before_reminder_checker(self):
        await self.wait_until_ready()
    
    async def on_message(self, message):
        """Process messages for keyword notifications and workflow triggers"""
        if message.author.bot:
            return
            
        await self.process_commands(message)
        
        # Check for keyword notifications
        await self.check_keywords(message)
        
        # Check for workflow triggers
        await self.check_workflow_triggers(message, "message:text")
    
    async def check_keywords(self, message):
        """Check if message contains any monitored keywords"""
        try:
            if not message.guild:
                return
                
            content = message.content.lower()
            
            async with self.db_pool.acquire() as conn:
                # Get all keywords for this guild
                keywords = await conn.fetch(
                    "SELECT user_id, keyword FROM keywords WHERE guild_id = $1",
                    message.guild.id
                )
                
                # Group keywords by user
                user_keywords = {}
                for row in keywords:
                    user_id = row['user_id']
                    keyword = row['keyword'].lower()
                    
                    if user_id not in user_keywords:
                        user_keywords[user_id] = []
                    
                    user_keywords[user_id].append(keyword)
                
                # Check each user's keywords
                for user_id, keywords in user_keywords.items():
                    # Skip if the message author is the keyword owner
                    if message.author.id == user_id:
                        continue
                        
                    user = message.guild.get_member(user_id)
                    if not user:
                        continue
                    
                    # Check if any keyword matches
                    for keyword in keywords:
                        if keyword in content:
                            # Create notification embed
                            embed = discord.Embed(
                                title="🔔 Keyword Notification",
                                description=f"Your keyword `{keyword}` was mentioned",
                                color=discord.Color.gold(),
                                timestamp=datetime.utcnow()
                            )
                            
                            embed.add_field(name="Author", value=message.author.mention, inline=True)
                            embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                            
                            # Add message content (truncate if too long)
                            content_preview = message.content[:1000] + "..." if len(message.content) > 1000 else message.content
                            embed.add_field(name="Message", value=content_preview, inline=False)
                            
                            # Add jump link
                            embed.add_field(name="Go to Message", value=f"[Click here]({message.jump_url})", inline=False)
                            
                            try:
                                await user.send(embed=embed)
                            except discord.Forbidden:
                                # Can't DM user, skip
                                pass
                            
                            # Only notify once per message, even if multiple keywords match
                            break
        except Exception as e:
            logger.error(f"Error in check_keywords: {e}")
            traceback.print_exc()
    
    async def check_workflow_triggers(self, message, trigger_type, **kwargs):
        """Check if message triggers any workflows"""
        try:
            if not message.guild:
                return
                
            async with self.db_pool.acquire() as conn:
                # Get all workflows for this guild with the specified trigger type
                workflows = await conn.fetch(
                    "SELECT * FROM workflows WHERE guild_id = $1 AND trigger_type = $2 AND is_enabled = TRUE",
                    message.guild.id, trigger_type
                )
                
                for workflow in workflows:
                    trigger_value = workflow['trigger_value']
                    trigger_channel_id = workflow['trigger_channel_id']
                    actions = json.loads(workflow['actions'])
                    
                    # Check channel constraint if specified
                    if trigger_channel_id and message.channel.id != trigger_channel_id:
                        continue
                    
                    # For message:text triggers, check if the trigger text is in the message
                    if trigger_type == "message:text" and trigger_value:
                        if trigger_value.lower() not in message.content.lower():
                            continue
                    
                    # Execute workflow actions
                    await self.execute_workflow_actions(message.guild, message, actions, workflow)
        except Exception as e:
            logger.error(f"Error in check_workflow_triggers: {e}")
            traceback.print_exc()
    
    async def execute_workflow_actions(self, guild, context_obj, actions, workflow):
        """Execute the actions defined in a workflow"""
        try:
            log_channel_id = workflow['log_channel_id']
            log_channel = guild.get_channel(log_channel_id) if log_channel_id else None
            
            for action in actions:
                action_type = action.get('type')
                
                if action_type == 'send_message':
                    channel_id = action.get('channel_id')
                    message_content = action.get('content', '')
                    
                    channel = guild.get_channel(channel_id)
                    if channel:
                        await channel.send(message_content)
                        
                        if log_channel:
                            await log_channel.send(f"Workflow '{workflow['name']}' sent message to {channel.mention}")
                
                elif action_type == 'add_role':
                    role_id = action.get('role_id')
                    
                    # For message context, use the author
                    if hasattr(context_obj, 'author'):
                        user = context_obj.author
                    else:
                        user = context_obj
                    
                    role = guild.get_role(role_id)
                    if role and isinstance(user, discord.Member):
                        await user.add_roles(role)
                        
                        if log_channel:
                            await log_channel.send(f"Workflow '{workflow['name']}' added role {role.name} to {user.mention}")
                
                elif action_type == 'create_channel':
                    channel_name = action.get('name', 'new-channel')
                    channel_type = action.get('channel_type', 'text')
                    category_id = action.get('category_id')
                    
                    category = guild.get_channel(category_id) if category_id else None
                    
                    if channel_type == 'text':
                        channel = await guild.create_text_channel(channel_name, category=category)
                    elif channel_type == 'voice':
                        channel = await guild.create_voice_channel(channel_name, category=category)
                    
                    if log_channel:
                        await log_channel.send(f"Workflow '{workflow['name']}' created channel {channel.mention}")
                
                elif action_type == 'send_dm':
                    # For message context, use the author
                    if hasattr(context_obj, 'author'):
                        user = context_obj.author
                    else:
                        user = context_obj
                    
                    message_content = action.get('content', '')
                    
                    if isinstance(user, discord.Member):
                        try:
                            await user.send(message_content)
                            
                            if log_channel:
                                await log_channel.send(f"Workflow '{workflow['name']}' sent DM to {user.mention}")
                        except discord.Forbidden:
                            if log_channel:
                                await log_channel.send(f"Workflow '{workflow['name']}' failed to send DM to {user.mention} (DMs closed)")
        except Exception as e:
            logger.error(f"Error executing workflow actions: {e}")
            traceback.print_exc()
            
            if log_channel:
                await log_channel.send(f"Error executing workflow '{workflow['name']}': {str(e)}")
    
    async def on_member_join(self, member):
        """Handle member join events"""
        await self.check_workflow_triggers(member, "member_join")
        
        # Log the event
        await self.log_event(member.guild, "member_join", member=member)
    
    async def on_member_remove(self, member):
        """Handle member leave events"""
        await self.check_workflow_triggers(member, "member_leave")
        
        # Log the event
        await self.log_event(member.guild, "member_leave", member=member)
    
    async def on_thread_create(self, thread):
        """Handle thread creation events"""
        await self.check_workflow_triggers(thread, "thread_create")
        
        # Log the event
        await self.log_event(thread.guild, "thread_create", thread=thread)
    
    async def on_guild_channel_create(self, channel):
        """Handle channel creation events"""
        await self.check_workflow_triggers(channel, "channel_create")
        
        # Log the event
        await self.log_event(channel.guild, "channel_create", channel=channel)
    
    async def on_message_delete(self, message):
        """Handle message deletion events"""
        if message.author.bot:
            return
            
        # Log the event
        await self.log_event(message.guild, "message_delete", message=message)
    
    async def on_message_edit(self, before, after):
        """Handle message edit events"""
        if before.author.bot:
            return
            
        # Ignore if content didn't change (e.g., embed loading)
        if before.content == after.content:
            return
            
        # Log the event
        await self.log_event(after.guild, "message_edit", before=before, after=after)
    
    async def on_guild_role_create(self, role):
        """Handle role creation events"""
        await self.log_event(role.guild, "role_create", role=role)
    
    async def on_guild_role_delete(self, role):
        """Handle role deletion events"""
        await self.log_event(role.guild, "role_delete", role=role)
    
    async def on_guild_role_update(self, before, after):
        """Handle role update events"""
        await self.log_event(after.guild, "role_update", before=before, after=after)
    
    async def on_guild_channel_delete(self, channel):
        """Handle channel deletion events"""
        await self.log_event(channel.guild, "channel_delete", channel=channel)
    
    async def log_event(self, guild, event_type, **kwargs):
        """Log events to the configured log channel"""
        if not guild:
            return
            
        try:
            async with self.db_pool.acquire() as conn:
                # Get log channel ID
                config = await conn.fetchrow("SELECT log_channel_id FROM server_config WHERE guild_id = $1", guild.id)
                
                if not config or not config['log_channel_id']:
                    return
                    
                log_channel = guild.get_channel(config['log_channel_id'])
                if not log_channel:
                    return
                
                embed = discord.Embed(
                    title=f"📝 {event_type.replace('_', ' ').title()}",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                if event_type == "message_delete":
                    message = kwargs.get('message')
                    
                    embed.add_field(name="Author", value=message.author.mention, inline=True)
                    embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                    
                    content = message.content[:1000] + "..." if len(message.content) > 1000 else message.content
                    embed.add_field(name="Content", value=content or "(empty)", inline=False)
                    
                    if message.attachments:
                        attachment_list = "\n".join([f"[{a.filename}]({a.url})" for a in message.attachments])
                        embed.add_field(name="Attachments", value=attachment_list, inline=False)
                
                elif event_type == "message_edit":
                    before = kwargs.get('before')
                    after = kwargs.get('after')
                    
                    embed.add_field(name="Author", value=after.author.mention, inline=True)
                    embed.add_field(name="Channel", value=after.channel.mention, inline=True)
                    embed.add_field(name="Jump to Message", value=f"[Click here]({after.jump_url})", inline=True)
                    
                    before_content = before.content[:500] + "..." if len(before.content) > 500 else before.content
                    after_content = after.content[:500] + "..." if len(after.content) > 500 else after.content
                    
                    embed.add_field(name="Before", value=before_content or "(empty)", inline=False)
                    embed.add_field(name="After", value=after_content or "(empty)", inline=False)
                
                elif event_type == "member_join":
                    member = kwargs.get('member')
                    
                    embed.add_field(name="Member", value=member.mention, inline=True)
                    embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at), inline=True)
                    
                    embed.set_thumbnail(url=member.display_avatar.url)
                
                elif event_type == "member_leave":
                    member = kwargs.get('member')
                    
                    embed.add_field(name="Member", value=f"{member.name} ({member.id})", inline=True)
                    embed.add_field(name="Joined At", value=discord.utils.format_dt(member.joined_at) if member.joined_at else "Unknown", inline=True)
                    
                    embed.set_thumbnail(url=member.display_avatar.url)
                
                elif event_type == "role_create" or event_type == "role_delete":
                    role = kwargs.get('role')
                    
                    embed.add_field(name="Role Name", value=role.name, inline=True)
                    embed.add_field(name="Role ID", value=role.id, inline=True)
                    
                    if event_type == "role_create":
                        embed.add_field(name="Color", value=str(role.color), inline=True)
                        embed.add_field(name="Mentionable", value=str(role.mentionable), inline=True)
                        embed.add_field(name="Hoisted", value=str(role.hoist), inline=True)
                
                elif event_type == "role_update":
                    before = kwargs.get('before')
                    after = kwargs.get('after')
                    
                    embed.add_field(name="Role", value=after.name, inline=True)
                    embed.add_field(name="Role ID", value=after.id, inline=True)
                    
                    if before.name != after.name:
                        embed.add_field(name="Name Changed", value=f"From: {before.name}\nTo: {after.name}", inline=False)
                    
                    if before.color != after.color:
                        embed.add_field(name="Color Changed", value=f"From: {before.color}\nTo: {after.color}", inline=False)
                    
                    if before.mentionable != after.mentionable:
                        embed.add_field(name="Mentionable Changed", value=f"From: {before.mentionable}\nTo: {after.mentionable}", inline=False)
                    
                    if before.hoist != after.hoist:
                        embed.add_field(name="Hoisted Changed", value=f"From: {before.hoist}\nTo: {after.hoist}", inline=False)
                
                elif event_type == "channel_create" or event_type == "channel_delete":
                    channel = kwargs.get('channel')
                    
                    embed.add_field(name="Channel Name", value=channel.name, inline=True)
                    embed.add_field(name="Channel ID", value=channel.id, inline=True)
                    embed.add_field(name="Channel Type", value=str(channel.type), inline=True)
                
                elif event_type == "thread_create":
                    thread = kwargs.get('thread')
                    
                    embed.add_field(name="Thread Name", value=thread.name, inline=True)
                    embed.add_field(name="Thread ID", value=thread.id, inline=True)
                    embed.add_field(name="Parent Channel", value=thread.parent.mention if thread.parent else "Unknown", inline=True)
                
                await log_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error logging event: {e}")
            traceback.print_exc()

    async def check_database_health(self):
        """Check if database connection is healthy"""
        if not self.db_pool:
            return False
        
        try:
            async with self.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    async def ensure_database_connection(self):
        """Ensure database connection is available, attempt reconnection if needed"""
        if not self.db_pool or not await self.check_database_health():
            logger.info("Attempting to reconnect to database...")
            try:
                if self.db_pool:
                    await self.db_pool.close()
                
                if DATABASE_URL:
                    db_url = DATABASE_URL.replace('postgresql://', 'postgres://', 1) if DATABASE_URL.startswith('postgresql://') else DATABASE_URL
                    self.db_pool = await asyncpg.create_pool(
                        db_url,
                        min_size=1,
                        max_size=10,
                        command_timeout=60,
                        server_settings={'jit': 'off'}
                    )
                    await self.init_db()
                    logger.info("Database reconnection successful")
                    return True
            except Exception as e:
                logger.error(f"Database reconnection failed: {e}")
                self.db_pool = None
        
        return self.db_pool is not None

    async def safe_db_operation(self, operation):
        """Safely execute a database operation with error handling"""
        if not self.db_pool:
            if not await self.ensure_database_connection():
                raise Exception("Database connection not available")
        
        try:
            return await operation()
        except Exception as e:
            logger.error(f"Database operation failed: {e}")
            # Try to reconnect once
            if await self.ensure_database_connection():
                try:
                    return await operation()
                except Exception as retry_error:
                    logger.error(f"Database operation failed after reconnection: {retry_error}")
                    raise retry_error
            else:
                raise e

# Utility functions
def parse_time(time_str):
    """Parse time string in format like '1h30m', '2d', etc."""
    total_seconds = 0
    pattern = r'(\d+)([dhms])'
    
    matches = re.findall(pattern, time_str.lower())
    
    if not matches:
        raise ValueError("Invalid time format. Use format like '1h30m', '2d', etc.")
    
    for value, unit in matches:
        value = int(value)
        
        if unit == 'd':
            total_seconds += value * 86400
        elif unit == 'h':
            total_seconds += value * 3600
        elif unit == 'm':
            total_seconds += value * 60
        elif unit == 's':
            total_seconds += value
    
    # Limit to 9 years (to avoid overflow)
    max_seconds = 9 * 365 * 24 * 3600
    if total_seconds > max_seconds:
        raise ValueError(f"Time too far in the future (max: 9 years)")
    
    return datetime.utcnow() + timedelta(seconds=total_seconds)

async def is_admin(interaction):
    """Check if user has admin permissions"""
    if interaction.user.guild_permissions.administrator:
        return True
        
    async with interaction.client.db_pool.acquire() as conn:
        admin_roles = await conn.fetch(
            "SELECT role_id FROM admin_roles WHERE guild_id = $1",
            interaction.guild.id
        )
        
        user_roles = [role.id for role in interaction.user.roles]
        
        for admin_role in admin_roles:
            if admin_role['role_id'] in user_roles:
                return True
    
    return False

async def generate_transcript(channel):
    """Generate a transcript of a channel"""
    messages = []
    
    async for message in channel.history(limit=None, oldest_first=True):
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        content = message.content or ""
        for attachment in message.attachments:
            content += f"\n[Attachment: {attachment.filename}]({attachment.url})"
        
        messages.append(f"**{message.author.display_name}** ({timestamp}):\n{content}\n")
    
    transcript = "\n".join(messages)
    
    # If transcript is too long, split it
    if len(transcript) > 1900:
        parts = []
        current_part = ""
        
        for message in messages:
            if len(current_part) + len(message) > 1900:
                parts.append(current_part)
                current_part = message
            else:
                current_part += message
        
        if current_part:
            parts.append(current_part)
        
        return parts
    
    return [transcript]

# Command Groups
class TicketCommands(commands.GroupCog, name="ticket"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="create")
    @app_commands.describe(
        title="Title of the ticket",
        description="Description of the ticket",
        priority="Priority of the ticket"
    )
    @app_commands.choices(priority=PRIORITY_CHOICES)
    async def create_ticket(
        self, 
        interaction: discord.Interaction, 
        title: str, 
        description: str, 
        priority: app_commands.Choice[str] = None
    ):
        """Create a new support ticket"""
        try:
            # Generate ticket ID
            ticket_id = f"{interaction.user.name.lower()}-{int(datetime.utcnow().timestamp())}"
            
            # Get ticket category
            async with self.bot.db_pool.acquire() as conn:
                config = await conn.fetchrow(
                    "SELECT ticket_category_id FROM server_config WHERE guild_id = $1",
                    interaction.guild.id
                )
                
                if not config or not config['ticket_category_id']:
                    await interaction.response.send_message(
                        "Ticket system is not set up. Please ask an admin to run `/ticket setup`.",
                        ephemeral=True
                    )
                    return
                
                category_id = config['ticket_category_id']
                category = interaction.guild.get_channel(category_id)
                
                if not category:
                    await interaction.response.send_message(
                        "Ticket category not found. Please ask an admin to run `/ticket setup`.",
                        ephemeral=True
                    )
                    return
            
            # Create ticket channel
            channel_name = f"ticket-{ticket_id}"
            
            # Create private channel
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            
            channel = await interaction.guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Ticket: {title} | Created by: {interaction.user.display_name}"
            )
            
            # Store ticket in database
            priority_value = priority.value if priority else "Medium"
            
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO tickets (id, title, description, creator_id, channel_id, priority, guild_id, assigned_users)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    ticket_id, title, description, interaction.user.id, channel.id, priority_value,
                    interaction.guild.id, json.dumps([interaction.user.id])
                )
            
            # Create ticket embed
            embed = discord.Embed(
                title=f"Ticket: {title}",
                description=description,
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Creator", value=interaction.user.mention, inline=True)
            embed.add_field(name="Priority", value=priority_value, inline=True)
            embed.add_field(name="Status", value="Open", inline=True)
            
            # Add ticket controls
            controls = discord.ui.View()
            controls.add_item(discord.ui.Button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket"))
            
            await channel.send(embed=embed, view=controls)
            
            # Send confirmation
            await interaction.response.send_message(
                f"Ticket created! Please go to {channel.mention}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Error creating ticket: {str(e)}", ephemeral=True)
            logger.error(f"Error creating ticket: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="join")
    @app_commands.describe(ticket_id="ID of the ticket to join")
    async def join_ticket(self, interaction: discord.Interaction, ticket_id: str = None):
        """Request to join a ticket or list available tickets"""
        try:
            if not ticket_id:
                # List available tickets
                async with self.bot.db_pool.acquire() as conn:
                    tickets = await conn.fetch(
                        """
                        SELECT id, title, creator_id, is_private 
                        FROM tickets 
                        WHERE guild_id = $1 AND status = 'open' AND is_private = FALSE
                        """,
                        interaction.guild.id
                    )
                
                if not tickets:
                    await interaction.response.send_message("No open tickets available to join.", ephemeral=True)
                    return
                
                embed = discord.Embed(
                    title="Available Tickets",
                    description="Use `/ticket join <ticket_id>` to request access",
                    color=discord.Color.blue()
                )
                
                for ticket in tickets:
                    creator = interaction.guild.get_member(ticket['creator_id'])
                    creator_name = creator.display_name if creator else "Unknown"
                    
                    embed.add_field(
                        name=f"ID: {ticket['id']}",
                        value=f"Title: {ticket['title']}\nCreator: {creator_name}",
                        inline=False
                    )
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Request to join specific ticket
            async with self.bot.db_pool.acquire() as conn:
                ticket = await conn.fetchrow(
                    "SELECT * FROM tickets WHERE id = $1 AND guild_id = $2",
                    ticket_id, interaction.guild.id
                )
                
                if not ticket:
                    await interaction.response.send_message(f"Ticket {ticket_id} not found.", ephemeral=True)
                    return
                
                if ticket['is_private']:
                    await interaction.response.send_message("This ticket is private. You cannot join it.", ephemeral=True)
                    return
                
                # Check if user is already in the ticket
                assigned_users = json.loads(ticket['assigned_users'])
                if interaction.user.id in assigned_users:
                    await interaction.response.send_message("You are already in this ticket.", ephemeral=True)
                    return
                
                # Get ticket channel
                channel = interaction.guild.get_channel(ticket['channel_id'])
                if not channel:
                    await interaction.response.send_message("Ticket channel not found.", ephemeral=True)
                    return
                
                # Send join request to ticket channel
                embed = discord.Embed(
                    title="Join Request",
                    description=f"{interaction.user.mention} wants to join this ticket.",
                    color=discord.Color.blue()
                )
                
                # Create approve/deny buttons
                class JoinRequestView(discord.ui.View):
                    def __init__(self):
                        super().__init__(timeout=None)
                    
                    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id=f"approve_join_{interaction.user.id}")
                    async def approve_button(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                        # Check if user is ticket creator or admin
                        is_admin_user = await is_admin(button_interaction)
                        is_creator = button_interaction.user.id == ticket['creator_id']
                        
                        if not (is_admin_user or is_creator):
                            await button_interaction.response.send_message("You don't have permission to approve join requests.", ephemeral=True)
                            return
                        
                        # Add user to ticket
                        await channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
                        
                        # Update database
                        assigned_users.append(interaction.user.id)
                        async with self.bot.db_pool.acquire() as conn:
                            await conn.execute(
                                "UPDATE tickets SET assigned_users = $1 WHERE id = $2",
                                json.dumps(assigned_users), ticket_id
                            )
                        
                        await button_interaction.response.send_message(f"{interaction.user.mention} has been added to the ticket.")
                        
                        # Notify the user
                        try:
                            await interaction.user.send(f"Your request to join ticket {ticket_id} has been approved.")
                        except discord.Forbidden:
                            pass
                        
                        # Disable buttons
                        self.disable_all_items()
                        await button_interaction.message.edit(view=self)
                    
                    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red, custom_id=f"deny_join_{interaction.user.id}")
                    async def deny_button(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                        # Check if user is ticket creator or admin
                        is_admin_user = await is_admin(button_interaction)
                        is_creator = button_interaction.user.id == ticket['creator_id']
                        
                        if not (is_admin_user or is_creator):
                            await button_interaction.response.send_message("You don't have permission to deny join requests.", ephemeral=True)
                            return
                        
                        await button_interaction.response.send_message(f"Join request from {interaction.user.mention} has been denied.")
                        
                        # Notify the user
                        try:
                            await interaction.user.send(f"Your request to join ticket {ticket_id} has been denied.")
                        except discord.Forbidden:
                            pass
                        
                        # Disable buttons
                        self.disable_all_items()
                        await button_interaction.message.edit(view=self)
                
                await channel.send(embed=embed, view=JoinRequestView())
                
                await interaction.response.send_message(f"Join request sent for ticket {ticket_id}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in join_ticket: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="private")
    async def make_private(self, interaction: discord.Interaction):
        """Make the current ticket private (only assignees can see)"""
        try:
            # Check if this is a ticket channel
            channel_name = interaction.channel.name
            if not channel_name.startswith("ticket-"):
                await interaction.response.send_message("This command can only be used in ticket channels.", ephemeral=True)
                return
            
            # Get ticket info
            async with self.bot.db_pool.acquire() as conn:
                ticket = await conn.fetchrow(
                    "SELECT * FROM tickets WHERE channel_id = $1 AND guild_id = $2",
                    interaction.channel.id, interaction.guild.id
                )
                
                if not ticket:
                    await interaction.response.send_message("Ticket not found for this channel.", ephemeral=True)
                    return
                
                # Check if user is ticket creator or admin
                is_admin_user = await is_admin(interaction)
                is_creator = interaction.user.id == ticket['creator_id']
                
                if not (is_admin_user or is_creator):
                    await interaction.response.send_message("You don't have permission to make this ticket private.", ephemeral=True)
                    return
                
                # Check if already private
                if ticket['is_private']:
                    await interaction.response.send_message("This ticket is already private.", ephemeral=True)
                    return
                
                # Make ticket private
                await conn.execute(
                    "UPDATE tickets SET is_private = TRUE WHERE id = $1",
                    ticket['id']
                )
                
                # Update channel permissions
                await interaction.channel.set_permissions(interaction.guild.default_role, read_messages=False)
                
                # Set permissions for assigned users
                assigned_users = json.loads(ticket['assigned_users'])
                for user_id in assigned_users:
                    user = interaction.guild.get_member(user_id)
                    if user:
                        await interaction.channel.set_permissions(user, read_messages=True, send_messages=True)
                
                await interaction.response.send_message("Ticket is now private. Only assigned users can see it.")
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in make_private: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="public")
    async def make_public(self, interaction: discord.Interaction):
        """Make the current ticket public (everyone can see, only assignees can write)"""
        try:
            # Check if this is a ticket channel
            channel_name = interaction.channel.name
            if not channel_name.startswith("ticket-"):
                await interaction.response.send_message("This command can only be used in ticket channels.", ephemeral=True)
                return
            
            # Get ticket info
            async with self.bot.db_pool.acquire() as conn:
                ticket = await conn.fetchrow(
                    "SELECT * FROM tickets WHERE channel_id = $1 AND guild_id = $2",
                    interaction.channel.id, interaction.guild.id
                )
                
                if not ticket:
                    await interaction.response.send_message("Ticket not found for this channel.", ephemeral=True)
                    return
                
                # Check if user is ticket creator or admin
                is_admin_user = await is_admin(interaction)
                is_creator = interaction.user.id == ticket['creator_id']
                
                if not (is_admin_user or is_creator):
                    await interaction.response.send_message("You don't have permission to make this ticket public.", ephemeral=True)
                    return
                
                # Check if already public
                if not ticket['is_private']:
                    await interaction.response.send_message("This ticket is already public.", ephemeral=True)
                    return
                
                # Make ticket public
                await conn.execute(
                    "UPDATE tickets SET is_private = FALSE WHERE id = $1",
                    ticket['id']
                )
                
                # Update channel permissions
                await interaction.channel.set_permissions(interaction.guild.default_role, read_messages=True, send_messages=False)
                
                # Set permissions for assigned users
                assigned_users = json.loads(ticket['assigned_users'])
                for user_id in assigned_users:
                    user = interaction.guild.get_member(user_id)
                    if user:
                        await interaction.channel.set_permissions(user, read_messages=True, send_messages=True)
                
                await interaction.response.send_message("Ticket is now public. Everyone can see it, but only assigned users can write.")
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in make_public: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="list")
    @app_commands.describe(
        status="Filter tickets by status",
        user="Filter tickets by user"
    )
    @app_commands.choices(status=STATUS_CHOICES)
    async def list_tickets(
        self, 
        interaction: discord.Interaction, 
        status: app_commands.Choice[str] = None,
        user: discord.User = None
    ):
        """List tickets in the server"""
        try:
            status_filter = status.value if status else "all"
            user_id = user.id if user else None
            
            # Build query based on filters
            query = "SELECT * FROM tickets WHERE guild_id = $1"
            params = [interaction.guild.id]
            
            if status_filter != "all":
                query += f" AND status = ${len(params) + 1}"
                params.append(status_filter)
            
            if user_id:
                query += f" AND creator_id = ${len(params) + 1}"
                params.append(user_id)
            
            # Get tickets
            async with self.bot.db_pool.acquire() as conn:
                tickets = await conn.fetch(query, *params)
            
            if not tickets:
                await interaction.response.send_message("No tickets found matching the criteria.", ephemeral=True)
                return
            
            # Create embed
            embed = discord.Embed(
                title="Tickets",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            # Add filters to description
            description = "Filters: "
            if status_filter != "all":
                description += f"Status: {status_filter}, "
            if user_id:
                description += f"User: {user.mention}, "
            
            embed.description = description.rstrip(", ")
            
            # Add tickets to embed
            for ticket in tickets:
                creator = interaction.guild.get_member(ticket['creator_id'])
                creator_name = creator.display_name if creator else "Unknown"
                
                channel = interaction.guild.get_channel(ticket['channel_id'])
                channel_mention = channel.mention if channel else "Channel Deleted"
                
                value = f"Status: {ticket['status']}\n"
                value += f"Priority: {ticket['priority']}\n"
                value += f"Creator: {creator_name}\n"
                value += f"Channel: {channel_mention}\n"
                value += f"Created: {discord.utils.format_dt(ticket['created_at'])}"
                
                embed.add_field(
                    name=f"{ticket['title']} (ID: {ticket['id']})",
                    value=value,
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in list_tickets: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="assign")
    @app_commands.describe(
        ticket_id="ID of the ticket",
        user="User to assign to the ticket"
    )
    async def assign_ticket(self, interaction: discord.Interaction, ticket_id: str, user: discord.User):
        """Assign a user to a ticket"""
        try:
            # Get ticket info
            async with self.bot.db_pool.acquire() as conn:
                ticket = await conn.fetchrow(
                    "SELECT * FROM tickets WHERE id = $1 AND guild_id = $2",
                    ticket_id, interaction.guild.id
                )
                
                if not ticket:
                    await interaction.response.send_message(f"Ticket {ticket_id} not found.", ephemeral=True)
                    return
                
                # Check if user is ticket creator or admin
                is_admin_user = await is_admin(interaction)
                is_creator = interaction.user.id == ticket['creator_id']
                
                if not (is_admin_user or is_creator):
                    await interaction.response.send_message("You don't have permission to assign users to this ticket.", ephemeral=True)
                    return
                
                # Check if user is already assigned
                assigned_users = json.loads(ticket['assigned_users'])
                if user.id in assigned_users:
                    await interaction.response.send_message(f"{user.mention} is already assigned to this ticket.", ephemeral=True)
                    return
                
                # Add user to ticket
                assigned_users.append(user.id)
                await conn.execute(
                    "UPDATE tickets SET assigned_users = $1 WHERE id = $2",
                    json.dumps(assigned_users), ticket_id
                )
                
                # Update channel permissions
                channel = interaction.guild.get_channel(ticket['channel_id'])
                if channel:
                    await channel.set_permissions(user, read_messages=True, send_messages=True)
                    
                    # Notify in channel
                    await channel.send(f"{user.mention} has been assigned to this ticket by {interaction.user.mention}.")
                
                await interaction.response.send_message(f"{user.mention} has been assigned to ticket {ticket_id}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in assign_ticket: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="setup")
    @app_commands.describe(
        category="Category for ticket channels",
        transcript_channel="Channel for ticket transcripts"
    )
    async def setup_tickets(
        self, 
        interaction: discord.Interaction, 
        category: discord.CategoryChannel,
        transcript_channel: discord.TextChannel
    ):
        """Set up the ticket system"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to set up the ticket system.", ephemeral=True)
                return
            
            # Update server config
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO server_config (guild_id, ticket_category_id, ticket_transcript_channel_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (guild_id) 
                    DO UPDATE SET ticket_category_id = $2, ticket_transcript_channel_id = $3
                    """,
                    interaction.guild.id, category.id, transcript_channel.id
                )
            
            await interaction.response.send_message(
                f"Ticket system set up successfully!\n"
                f"Category: {category.mention}\n"
                f"Transcript Channel: {transcript_channel.mention}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in setup_tickets: {e}")
            traceback.print_exc()

class GitHubCommands(commands.GroupCog, name="github"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="track")
    @app_commands.describe(repo="Repository to track (format: owner/repo)")
    async def track_repo(self, interaction: discord.Interaction, repo: str):
        """Track a GitHub repository"""
        try:
            # Validate repo format
            if not re.match(r'^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$', repo):
                await interaction.response.send_message(
                    "Invalid repository format. Use format: owner/repo",
                    ephemeral=True
                )
                return
            
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to track repositories.", ephemeral=True)
                return
            
            # Get GitHub channel
            async with self.bot.db_pool.acquire() as conn:
                config = await conn.fetchrow(
                    "SELECT github_channel_id FROM server_config WHERE guild_id = $1",
                    interaction.guild.id
                )
                
                if not config or not config['github_channel_id']:
                    await interaction.response.send_message(
                        "GitHub tracking is not set up. Please run `/github setup` first.",
                        ephemeral=True
                    )
                    return
                
                channel_id = config['github_channel_id']
                
                # Check if repo is already tracked
                existing = await conn.fetchrow(
                    "SELECT * FROM github_repos WHERE guild_id = $1 AND repo_name = $2",
                    interaction.guild.id, repo
                )
                
                if existing:
                    await interaction.response.send_message(f"Repository {repo} is already being tracked.", ephemeral=True)
                    return
            
            # Fetch initial repo data from GitHub API
            headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
            
            async with aiohttp.ClientSession() as session:
                # Get repo info
                async with session.get(f"https://api.github.com/repos/{repo}", headers=headers) as response:
                    if response.status == 404:
                        await interaction.response.send_message(f"Repository {repo} not found.", ephemeral=True)
                        return
                    elif response.status != 200:
                        await interaction.response.send_message(f"Error accessing repository: {response.status}", ephemeral=True)
                        return
                    
                    repo_data = await response.json()
                    star_count = repo_data.get('stargazers_count', 0)
                    fork_count = repo_data.get('forks_count', 0)
                
                # Get branches
                async with session.get(f"https://api.github.com/repos/{repo}/branches", headers=headers) as response:
                    if response.status == 200:
                        branches_data = await response.json()
                        branches = [branch['name'] for branch in branches_data]
                    else:
                        branches = []
                
                # Get latest commit
                async with session.get(f"https://api.github.com/repos/{repo}/commits", headers=headers) as response:
                    if response.status == 200:
                        commits_data = await response.json()
                        last_commit_sha = commits_data[0]['sha'] if commits_data else None
                    else:
                        last_commit_sha = None
            
            # Store repo data
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO github_repos (guild_id, repo_name, channel_id, last_commit_sha, star_count, fork_count, branches)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    interaction.guild.id, repo, channel_id, last_commit_sha, star_count, fork_count, json.dumps(branches)
                )
            
            await interaction.response.send_message(f"Now tracking repository {repo}!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in track_repo: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="untrack")
    @app_commands.describe(repo="Repository to stop tracking")
    async def untrack_repo(self, interaction: discord.Interaction, repo: str):
        """Stop tracking a GitHub repository"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to untrack repositories.", ephemeral=True)
                return
            
            # Remove repo from tracking
            async with self.bot.db_pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM github_repos WHERE guild_id = $1 AND repo_name = $2",
                    interaction.guild.id, repo
                )
                
                if result == "DELETE 0":
                    await interaction.response.send_message(f"Repository {repo} is not being tracked.", ephemeral=True)
                    return
            
            await interaction.response.send_message(f"Stopped tracking repository {repo}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in untrack_repo: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="list")
    async def list_repos(self, interaction: discord.Interaction):
        """List tracked repositories"""
        try:
            async with self.bot.db_pool.acquire() as conn:
                repos = await conn.fetch(
                    "SELECT * FROM github_repos WHERE guild_id = $1",
                    interaction.guild.id
                )
            
            if not repos:
                await interaction.response.send_message("No repositories are being tracked.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="Tracked Repositories",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            for repo in repos:
                channel = interaction.guild.get_channel(repo['channel_id'])
                channel_mention = channel.mention if channel else "Channel Deleted"
                
                value = f"Channel: {channel_mention}\n"
                value += f"Stars: {repo['star_count']}\n"
                value += f"Forks: {repo['fork_count']}\n"
                value += f"Last Checked: {discord.utils.format_dt(repo['last_checked'])}"
                
                embed.add_field(
                    name=repo['repo_name'],
                    value=value,
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in list_repos: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="setup")
    @app_commands.describe(channel="Channel for GitHub notifications")
    async def setup_github(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set up GitHub tracking"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to set up GitHub tracking.", ephemeral=True)
                return
            
            # Update server config
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO server_config (guild_id, github_channel_id)
                    VALUES ($1, $2)
                    ON CONFLICT (guild_id) 
                    DO UPDATE SET github_channel_id = $2
                    """,
                    interaction.guild.id, channel.id
                )
            
            await interaction.response.send_message(
                f"GitHub tracking set up successfully!\nNotifications will be sent to {channel.mention}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in setup_github: {e}")
            traceback.print_exc()

class ReminderCommands(commands.GroupCog, name="reminder"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="create")
    @app_commands.describe(
        time="Time until reminder (e.g., 1h30m, 2d, 30m)",
        message="Reminder message",
        send_dm="Whether to send a DM (default: True)"
    )
    async def create_reminder(
        self, 
        interaction: discord.Interaction, 
        time: str, 
        message: str,
        send_dm: bool = True
    ):
        """Create a personal reminder"""
        try:
            # Parse time
            remind_time = parse_time(time)
            
            # Store reminder
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO reminders (user_id, guild_id, message, remind_time, send_dm)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    interaction.user.id, interaction.guild.id, message, remind_time, send_dm
                )
            
            embed = discord.Embed(
                title="⏰ Reminder Created",
                description=f"I'll remind you: {message}",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Remind Time", value=discord.utils.format_dt(remind_time), inline=True)
            embed.add_field(name="Send DM", value="Yes" if send_dm else "No", inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except ValueError as e:
            await interaction.response.send_message(f"Error parsing time: {str(e)}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in create_reminder: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="channel")
    @app_commands.describe(
        time="Time until reminder (e.g., 1h30m, 2d, 30m)",
        message="Reminder message",
        channel="Channel to send reminder to (default: current channel)"
    )
    async def channel_reminder(
        self, 
        interaction: discord.Interaction, 
        time: str, 
        message: str,
        channel: discord.TextChannel = None
    ):
        """Create a channel reminder"""
        try:
            # Parse time
            remind_time = parse_time(time)
            
            # Use current channel if not specified
            target_channel = channel or interaction.channel
            
            # Store reminder
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO reminders (user_id, guild_id, message, remind_time, channel_id, send_dm)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    interaction.user.id, interaction.guild.id, message, remind_time, target_channel.id, False
                )
            
            embed = discord.Embed(
                title="⏰ Channel Reminder Created",
                description=f"I'll remind in {target_channel.mention}: {message}",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Remind Time", value=discord.utils.format_dt(remind_time), inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except ValueError as e:
            await interaction.response.send_message(f"Error parsing time: {str(e)}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in channel_reminder: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="list")
    async def list_reminders(self, interaction: discord.Interaction):
        """List your active reminders"""
        try:
            async with self.bot.db_pool.acquire() as conn:
                reminders = await conn.fetch(
                    """
                    SELECT * FROM reminders 
                    WHERE user_id = $1 AND guild_id = $2 
                    ORDER BY remind_time ASC
                    """,
                    interaction.user.id, interaction.guild.id
                )
            
            if not reminders:
                await interaction.response.send_message("You have no active reminders.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="Your Reminders",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            for i, reminder in enumerate(reminders, 1):
                channel_info = ""
                if reminder['channel_id']:
                    channel = interaction.guild.get_channel(reminder['channel_id'])
                    channel_info = f" in {channel.mention}" if channel else " in deleted channel"
                
                dm_info = " (DM)" if reminder['send_dm'] else ""
                
                embed.add_field(
                    name=f"{i}. {reminder['message'][:50]}{'...' if len(reminder['message']) > 50 else ''}",
                    value=f"Time: {discord.utils.format_dt(reminder['remind_time'])}{channel_info}{dm_info}",
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in list_reminders: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="delete")
    @app_commands.describe(number="Number of the reminder to delete (from /reminder list)")
    async def delete_reminder(self, interaction: discord.Interaction, number: int):
        """Delete a reminder"""
        try:
            async with self.bot.db_pool.acquire() as conn:
                # Get user's reminders
                reminders = await conn.fetch(
                    """
                    SELECT * FROM reminders 
                    WHERE user_id = $1 AND guild_id = $2 
                    ORDER BY remind_time ASC
                    """,
                    interaction.user.id, interaction.guild.id
                )
                
                if not reminders or number < 1 or number > len(reminders):
                    await interaction.response.send_message(
                        f"Invalid reminder number. You have {len(reminders)} reminders.",
                        ephemeral=True
                    )
                    return
                
                # Delete the reminder
                reminder_to_delete = reminders[number - 1]
                await conn.execute(
                    "DELETE FROM reminders WHERE id = $1",
                    reminder_to_delete['id']
                )
            
            await interaction.response.send_message(
                f"Deleted reminder: {reminder_to_delete['message'][:50]}{'...' if len(reminder_to_delete['message']) > 50 else ''}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in delete_reminder: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="setup")
    @app_commands.describe(channel="Default channel for reminders")
    async def setup_reminders(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set up reminder system"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to set up reminders.", ephemeral=True)
                return
            
            # Update server config
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO server_config (guild_id, reminder_channel_id)
                    VALUES ($1, $2)
                    ON CONFLICT (guild_id) 
                    DO UPDATE SET reminder_channel_id = $2
                    """,
                    interaction.guild.id, channel.id
                )
            
            await interaction.response.send_message(
                f"Reminder system set up successfully!\nDefault channel: {channel.mention}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in setup_reminders: {e}")
            traceback.print_exc()

class MeetingCommands(commands.GroupCog, name="meeting"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="create")
    @app_commands.describe(
        name="Name of the meeting",
        time="Time of the meeting (e.g., 1h30m, 2d, 30m from now)",
        description="Description of the meeting",
        voice_channel="Voice channel for the meeting"
    )
    async def create_meeting(
        self, 
        interaction: discord.Interaction, 
        name: str, 
        time: str,
        description: str,
        voice_channel: discord.VoiceChannel
    ):
        """Create a new meeting"""
        try:
            # Parse time
            meeting_time = parse_time(time)
            
            # Generate meeting ID
            meeting_id = f"meeting-{int(datetime.utcnow().timestamp())}"
            
            # Store meeting
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO meetings (id, guild_id, name, description, meeting_time, voice_channel_id, creator_id, participants)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    meeting_id, interaction.guild.id, name, description, meeting_time, 
                    voice_channel.id, interaction.user.id, json.dumps([interaction.user.id])
                )
            
            # Create meeting embed
            embed = discord.Embed(
                title=f"📅 Meeting: {name}",
                description=description,
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Meeting Time", value=discord.utils.format_dt(meeting_time), inline=True)
            embed.add_field(name="Voice Channel", value=voice_channel.mention, inline=True)
            embed.add_field(name="Creator", value=interaction.user.mention, inline=True)
            embed.add_field(name="Meeting ID", value=meeting_id, inline=False)
            
            # Add join button
            class MeetingView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=None)
                
                @discord.ui.button(label="Join Meeting", style=discord.ButtonStyle.green, custom_id=f"join_meeting_{meeting_id}")
                async def join_meeting(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                    # Add user to participants
                    async with self.bot.db_pool.acquire() as conn:
                        meeting = await conn.fetchrow(
                            "SELECT participants FROM meetings WHERE id = $1",
                            meeting_id
                        )
                        
                        if meeting:
                            participants = json.loads(meeting['participants'])
                            
                            if button_interaction.user.id not in participants:
                                participants.append(button_interaction.user.id)
                                
                                await conn.execute(
                                    "UPDATE meetings SET participants = $1 WHERE id = $2",
                                    json.dumps(participants), meeting_id
                                )
                                
                                await button_interaction.response.send_message(
                                    f"You've joined the meeting: {name}",
                                    ephemeral=True
                                )
                            else:
                                await button_interaction.response.send_message(
                                    "You're already in this meeting.",
                                    ephemeral=True
                                )
            
            await interaction.response.send_message(embed=embed, view=MeetingView())
            
            # Send to announcement channel if configured
            async with self.bot.db_pool.acquire() as conn:
                config = await conn.fetchrow(
                    "SELECT meeting_announcement_channel_id FROM server_config WHERE guild_id = $1",
                    interaction.guild.id
                )
                
                if config and config['meeting_announcement_channel_id']:
                    announcement_channel = interaction.guild.get_channel(config['meeting_announcement_channel_id'])
                    if announcement_channel and announcement_channel != interaction.channel:
                        await announcement_channel.send(embed=embed, view=MeetingView())
        except ValueError as e:
            await interaction.response.send_message(f"Error parsing time: {str(e)}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in create_meeting: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="join")
    @app_commands.describe(meeting_id="ID of the meeting to join")
    async def join_meeting(self, interaction: discord.Interaction, meeting_id: str):
        """Join a meeting"""
        try:
            async with self.bot.db_pool.acquire() as conn:
                meeting = await conn.fetchrow(
                    "SELECT * FROM meetings WHERE id = $1 AND guild_id = $2",
                    meeting_id, interaction.guild.id
                )
                
                if not meeting:
                    await interaction.response.send_message(f"Meeting {meeting_id} not found.", ephemeral=True)
                    return
                
                participants = json.loads(meeting['participants'])
                
                if interaction.user.id in participants:
                    await interaction.response.send_message("You're already in this meeting.", ephemeral=True)
                    return
                
                # Add user to participants
                participants.append(interaction.user.id)
                await conn.execute(
                    "UPDATE meetings SET participants = $1 WHERE id = $2",
                    json.dumps(participants), meeting_id
                )
            
            await interaction.response.send_message(f"You've joined the meeting: {meeting['name']}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in join_meeting: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="list")
    async def list_meetings(self, interaction: discord.Interaction):
        """List upcoming meetings"""
        try:
            current_time = datetime.utcnow()
            
            async with self.bot.db_pool.acquire() as conn:
                meetings = await conn.fetch(
                    """
                    SELECT * FROM meetings 
                    WHERE guild_id = $1 AND meeting_time > $2
                    ORDER BY meeting_time ASC
                    """,
                    interaction.guild.id, current_time
                )
            
            if not meetings:
                await interaction.response.send_message("No upcoming meetings.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="Upcoming Meetings",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            for meeting in meetings:
                creator = interaction.guild.get_member(meeting['creator_id'])
                creator_name = creator.display_name if creator else "Unknown"
                
                voice_channel = interaction.guild.get_channel(meeting['voice_channel_id'])
                voice_channel_name = voice_channel.name if voice_channel else "Channel Deleted"
                
                participants = json.loads(meeting['participants'])
                participant_count = len(participants)
                
                value = f"Time: {discord.utils.format_dt(meeting['meeting_time'])}\n"
                value += f"Voice Channel: {voice_channel_name}\n"
                value += f"Creator: {creator_name}\n"
                value += f"Participants: {participant_count}\n"
                value += f"ID: {meeting['id']}"
                
                embed.add_field(
                    name=meeting['name'],
                    value=value,
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in list_meetings: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="setup")
    @app_commands.describe(
        announcement_channel="Channel for meeting announcements",
        voice_channel="Default voice channel for meetings"
    )
    async def setup_meetings(
        self, 
        interaction: discord.Interaction, 
        announcement_channel: discord.TextChannel,
        voice_channel: discord.VoiceChannel
    ):
        """Set up meeting system"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to set up meetings.", ephemeral=True)
                return
            
            # Update server config
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO server_config (guild_id, meeting_announcement_channel_id, meeting_voice_channel_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (guild_id) 
                    DO UPDATE SET meeting_announcement_channel_id = $2, meeting_voice_channel_id = $3
                    """,
                    interaction.guild.id, announcement_channel.id, voice_channel.id
                )
            
            await interaction.response.send_message(
                f"Meeting system set up successfully!\n"
                f"Announcement Channel: {announcement_channel.mention}\n"
                f"Default Voice Channel: {voice_channel.mention}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in setup_meetings: {e}")
            traceback.print_exc()

class NotificationCommands(commands.GroupCog, name="notification"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="add")
    @app_commands.describe(keyword="Keyword to monitor")
    async def add_keyword(self, interaction: discord.Interaction, keyword: str):
        """Add a keyword to monitor"""
        try:
            # Check keyword length
            if len(keyword) < 2:
                await interaction.response.send_message("Keyword must be at least 2 characters long.", ephemeral=True)
                return
            
            if len(keyword) > 50:
                await interaction.response.send_message("Keyword must be 50 characters or less.", ephemeral=True)
                return
            
            # Add keyword
            async with self.bot.db_pool.acquire() as conn:
                try:
                    await conn.execute(
                        "INSERT INTO keywords (user_id, guild_id, keyword) VALUES ($1, $2, $3)",
                        interaction.user.id, interaction.guild.id, keyword.lower()
                    )
                    
                    await interaction.response.send_message(f"Added keyword: `{keyword}`", ephemeral=True)
                except Exception:
                    await interaction.response.send_message(f"Keyword `{keyword}` is already being monitored.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in add_keyword: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="remove")
    @app_commands.describe(keyword="Keyword to stop monitoring")
    async def remove_keyword(self, interaction: discord.Interaction, keyword: str):
        """Remove a keyword from monitoring"""
        try:
            async with self.bot.db_pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM keywords WHERE user_id = $1 AND guild_id = $2 AND keyword = $3",
                    interaction.user.id, interaction.guild.id, keyword.lower()
                )
                
                if result == "DELETE 0":
                    await interaction.response.send_message(f"Keyword `{keyword}` is not being monitored.", ephemeral=True)
                    return
            
            await interaction.response.send_message(f"Removed keyword: `{keyword}`", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in remove_keyword: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="list")
    async def list_keywords(self, interaction: discord.Interaction):
        """List your monitored keywords"""
        try:
            async with self.bot.db_pool.acquire() as conn:
                keywords = await conn.fetch(
                    "SELECT keyword FROM keywords WHERE user_id = $1 AND guild_id = $2 ORDER BY keyword",
                    interaction.user.id, interaction.guild.id
                )
            
            if not keywords:
                await interaction.response.send_message("You're not monitoring any keywords.", ephemeral=True)
                return
            
            keyword_list = [f"`{row['keyword']}`" for row in keywords]
            
            embed = discord.Embed(
                title="Your Monitored Keywords",
                description="\n".join(keyword_list),
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.set_footer(text=f"Total: {len(keywords)} keywords")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in list_keywords: {e}")
            traceback.print_exc()

class RoleCommands(commands.GroupCog, name="role"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="assign")
    @app_commands.describe(
        user="User to assign role to",
        role="Role to assign"
    )
    async def assign_role(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role):
        """Assign a role to a user"""
        try:
            # Check permissions
            if not interaction.user.guild_permissions.manage_roles and not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to assign roles.", ephemeral=True)
                return
            
            # Check if bot can assign the role
            if role >= interaction.guild.me.top_role:
                await interaction.response.send_message("I can't assign this role (it's higher than my highest role).", ephemeral=True)
                return
            
            # Check if user already has the role
            if role in user.roles:
                await interaction.response.send_message(f"{user.mention} already has the role {role.mention}.", ephemeral=True)
                return
            
            # Assign role
            await user.add_roles(role, reason=f"Assigned by {interaction.user}")
            
            await interaction.response.send_message(f"Assigned role {role.mention} to {user.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to assign this role.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in assign_role: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="remove")
    @app_commands.describe(
        user="User to remove role from",
        role="Role to remove"
    )
    async def remove_role(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role):
        """Remove a role from a user"""
        try:
            # Check permissions
            if not interaction.user.guild_permissions.manage_roles and not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to remove roles.", ephemeral=True)
                return
            
            # Check if bot can remove the role
            if role >= interaction.guild.me.top_role:
                await interaction.response.send_message("I can't remove this role (it's higher than my highest role).", ephemeral=True)
                return
            
            # Check if user has the role
            if role not in user.roles:
                await interaction.response.send_message(f"{user.mention} doesn't have the role {role.mention}.", ephemeral=True)
                return
            
            # Remove role
            await user.remove_roles(role, reason=f"Removed by {interaction.user}")
            
            await interaction.response.send_message(f"Removed role {role.mention} from {user.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to remove this role.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in remove_role: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="info")
    @app_commands.describe(role="Role to get information about")
    async def role_info(self, interaction: discord.Interaction, role: discord.Role):
        """Get information about a role"""
        try:
            embed = discord.Embed(
                title=f"Role: {role.name}",
                color=role.color,
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="ID", value=role.id, inline=True)
            embed.add_field(name="Color", value=str(role.color), inline=True)
            embed.add_field(name="Position", value=role.position, inline=True)
            
            embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
            embed.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True)
            embed.add_field(name="Members", value=len(role.members), inline=True)
            
            embed.add_field(name="Created", value=discord.utils.format_dt(role.created_at), inline=True)
            
            # Add permissions
            permissions = [perm.replace('_', ' ').title() for perm, value in role.permissions if value]
            if permissions:
                # Limit to first 10 permissions to avoid embed limits
                perm_text = ", ".join(permissions[:10])
                if len(permissions) > 10:
                    perm_text += f" and {len(permissions) - 10} more..."
                embed.add_field(name="Key Permissions", value=perm_text, inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in role_info: {e}")
            traceback.print_exc()

class UserCommands(commands.GroupCog, name="user"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="permissions")
    @app_commands.describe(user="User to check permissions for (default: yourself)")
    async def user_permissions(self, interaction: discord.Interaction, user: discord.Member = None):
        """Check user permissions"""
        try:
            target_user = user or interaction.user
            
            embed = discord.Embed(
                title=f"Permissions: {target_user.display_name}",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.set_thumbnail(url=target_user.display_avatar.url)
            
            # Get permissions
            permissions = target_user.guild_permissions
            
            # Key permissions to highlight
            key_perms = {
                'administrator': 'Administrator',
                'manage_guild': 'Manage Server',
                'manage_roles': 'Manage Roles',
                'manage_channels': 'Manage Channels',
                'manage_messages': 'Manage Messages',
                'kick_members': 'Kick Members',
                'ban_members': 'Ban Members',
                'moderate_members': 'Moderate Members'
            }
            
            has_key_perms = []
            for perm, name in key_perms.items():
                if getattr(permissions, perm):
                    has_key_perms.append(name)
            
            if has_key_perms:
                embed.add_field(name="Key Permissions", value="\n".join(has_key_perms), inline=False)
            else:
                embed.add_field(name="Key Permissions", value="None", inline=False)
            
            # Role information
            roles = [role.mention for role in target_user.roles[1:]]  # Exclude @everyone
            if roles:
                role_text = ", ".join(roles[:10])  # Limit to first 10 roles
                if len(roles) > 10:
                    role_text += f" and {len(roles) - 10} more..."
                embed.add_field(name="Roles", value=role_text, inline=False)
            else:
                embed.add_field(name="Roles", value="None", inline=False)
            
            # Check if user is bot admin
            is_bot_admin = await is_admin(interaction) if target_user == interaction.user else False
            if target_user != interaction.user:
                # Check if target user is bot admin
                mock_interaction = type('MockInteraction', (), {
                    'user': target_user,
                    'guild': interaction.guild,
                    'client': interaction.client
                })()
                is_bot_admin = await is_admin(mock_interaction)
            
            embed.add_field(name="Bot Admin", value="Yes" if is_bot_admin else "No", inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in user_permissions: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="info")
    @app_commands.describe(user="User to get information about (default: yourself)")
    async def user_info(self, interaction: discord.Interaction, user: discord.Member = None):
        """Get information about a user"""
        try:
            target_user = user or interaction.user
            
            embed = discord.Embed(
                title=f"User Info: {target_user.display_name}",
                color=target_user.color,
                timestamp=datetime.utcnow()
            )
            
            embed.set_thumbnail(url=target_user.display_avatar.url)
            
            embed.add_field(name="Username", value=target_user.name, inline=True)
            embed.add_field(name="ID", value=target_user.id, inline=True)
            embed.add_field(name="Bot", value="Yes" if target_user.bot else "No", inline=True)
            
            embed.add_field(name="Account Created", value=discord.utils.format_dt(target_user.created_at), inline=True)
            embed.add_field(name="Joined Server", value=discord.utils.format_dt(target_user.joined_at) if target_user.joined_at else "Unknown", inline=True)
            
            # Status
            status_emoji = {
                discord.Status.online: "🟢",
                discord.Status.idle: "🟡",
                discord.Status.dnd: "🔴",
                discord.Status.offline: "⚫"
            }
            
            embed.add_field(
                name="Status", 
                value=f"{status_emoji.get(target_user.status, '❓')} {target_user.status.name.title()}", 
                inline=True
            )
            
            # Activity
            if target_user.activity:
                activity_type = {
                    discord.ActivityType.playing: "Playing",
                    discord.ActivityType.streaming: "Streaming",
                    discord.ActivityType.listening: "Listening to",
                    discord.ActivityType.watching: "Watching",
                    discord.ActivityType.custom: "Custom Status",
                    discord.ActivityType.competing: "Competing in"
                }
                
                activity_name = activity_type.get(target_user.activity.type, "Unknown")
                embed.add_field(name="Activity", value=f"{activity_name} {target_user.activity.name}", inline=False)
            
            # Roles
            roles = [role.mention for role in target_user.roles[1:]]  # Exclude @everyone
            if roles:
                role_text = ", ".join(roles[:10])  # Limit to first 10 roles
                if len(roles) > 10:
                    role_text += f" and {len(roles) - 10} more..."
                embed.add_field(name=f"Roles ({len(roles)})", value=role_text, inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in user_info: {e}")
            traceback.print_exc()

class ConversationCommands(commands.GroupCog, name="conversation"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="thread")
    @app_commands.describe(
        message_id="ID of the message to create thread from",
        name="Name of the thread"
    )
    async def create_thread(self, interaction: discord.Interaction, message_id: str, name: str):
        """Create a thread from a message"""
        try:
            # Get the message
            try:
                message = await interaction.channel.fetch_message(int(message_id))
            except (ValueError, discord.NotFound):
                await interaction.response.send_message("Message not found.", ephemeral=True)
                return
            
            # Create thread
            thread = await message.create_thread(name=name, auto_archive_duration=1440)  # 24 hours
            
            await interaction.response.send_message(f"Created thread: {thread.mention}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to create threads.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in create_thread: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="rename")
    @app_commands.describe(new_name="New name for the thread")
    async def rename_thread(self, interaction: discord.Interaction, new_name: str):
        """Rename the current thread"""
        try:
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.response.send_message("This command can only be used in threads.", ephemeral=True)
                return
            
            # Check permissions
            if not interaction.user.guild_permissions.manage_threads and interaction.channel.owner_id != interaction.user.id:
                await interaction.response.send_message("You don't have permission to rename this thread.", ephemeral=True)
                return
            
            old_name = interaction.channel.name
            await interaction.channel.edit(name=new_name)
            
            await interaction.response.send_message(f"Renamed thread from '{old_name}' to '{new_name}'.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to rename this thread.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in rename_thread: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="archive")
    async def archive_thread(self, interaction: discord.Interaction):
        """Archive the current thread"""
        try:
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.response.send_message("This command can only be used in threads.", ephemeral=True)
                return
            
            # Check permissions
            if not interaction.user.guild_permissions.manage_threads and interaction.channel.owner_id != interaction.user.id:
                await interaction.response.send_message("You don't have permission to archive this thread.", ephemeral=True)
                return
            
            await interaction.channel.edit(archived=True)
            await interaction.response.send_message("Thread archived.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to archive this thread.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in archive_thread: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="search")
    @app_commands.describe(
        query="Search query",
        limit="Number of messages to search (default: 100)"
    )
    async def search_messages(self, interaction: discord.Interaction, query: str, limit: int = 100):
        """Search messages in the current channel"""
        try:
            if limit > 500:
                limit = 500
            
            await interaction.response.defer(ephemeral=True)
            
            # Search messages
            found_messages = []
            async for message in interaction.channel.history(limit=limit):
                if query.lower() in message.content.lower():
                    found_messages.append(message)
                    
                    # Limit results to prevent spam
                    if len(found_messages) >= 10:
                        break
            
            if not found_messages:
                await interaction.followup.send("No messages found matching your query.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title=f"Search Results for: {query}",
                description=f"Found {len(found_messages)} message{'s' if len(found_messages) != 1 else ''}",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            for message in found_messages:
                content = message.content[:100] + "..." if len(message.content) > 100 else message.content
                
                embed.add_field(
                    name=f"{message.author.display_name} - {discord.utils.format_dt(message.created_at, 'R')}",
                    value=f"{content}\n[Jump to message]({message.jump_url})",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in search_messages: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="pin")
    @app_commands.describe(message_id="ID of the message to pin")
    async def pin_message(self, interaction: discord.Interaction, message_id: str):
        """Pin a message"""
        try:
            # Check permissions
            if not interaction.user.guild_permissions.manage_messages:
                await interaction.response.send_message("You don't have permission to pin messages.", ephemeral=True)
                return
            
            # Get the message
            try:
                message = await interaction.channel.fetch_message(int(message_id))
            except (ValueError, discord.NotFound):
                await interaction.response.send_message("Message not found.", ephemeral=True)
                return
            
            await message.pin()
            await interaction.response.send_message("Message pinned.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to pin messages.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in pin_message: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="unpin")
    @app_commands.describe(message_id="ID of the message to unpin")
    async def unpin_message(self, interaction: discord.Interaction, message_id: str):
        """Unpin a message"""
        try:
            # Check permissions
            if not interaction.user.guild_permissions.manage_messages:
                await interaction.response.send_message("You don't have permission to unpin messages.", ephemeral=True)
                return
            
            # Get the message
            try:
                message = await interaction.channel.fetch_message(int(message_id))
            except (ValueError, discord.NotFound):
                await interaction.response.send_message("Message not found.", ephemeral=True)
                return
            
            await message.unpin()
            await interaction.response.send_message("Message unpinned.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to unpin messages.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in unpin_message: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="setup")
    @app_commands.describe(log_channel="Channel for conversation logs")
    async def setup_conversation(self, interaction: discord.Interaction, log_channel: discord.TextChannel):
        """Set up conversation management"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to set up conversation management.", ephemeral=True)
                return
            
            # Update server config
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO server_config (guild_id, thread_log_channel_id)
                    VALUES ($1, $2)
                    ON CONFLICT (guild_id) 
                    DO UPDATE SET thread_log_channel_id = $2
                    """,
                    interaction.guild.id, log_channel.id
                )
            
            await interaction.response.send_message(
                f"Conversation management set up successfully!\nLog channel: {log_channel.mention}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in setup_conversation: {e}")
            traceback.print_exc()

class AICommands(commands.GroupCog, name="ai"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="summarize")
    @app_commands.describe(
        count="Number of messages to summarize (default: 50)",
        user="Summarize messages from specific user only"
    )
    async def summarize_messages(self, interaction: discord.Interaction, count: int = 50, user: discord.User = None):
        """Summarize recent messages in the channel"""
        try:
            if count > 200:
                count = 200
            
            await interaction.response.defer(ephemeral=True)
            
            # Collect messages
            messages = []
            async for message in interaction.channel.history(limit=count):
                if message.author.bot:
                    continue
                    
                if user and message.author != user:
                    continue
                
                messages.append(f"{message.author.display_name}: {message.content}")
            
            if not messages:
                await interaction.followup.send("No messages found to summarize.", ephemeral=True)
                return
            
            # Create a simple summary (since we don't have AI integration)
            embed = discord.Embed(
                title="Message Summary",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            # Count messages per user
            user_counts = {}
            for message in messages:
                username = message.split(":")[0]
                user_counts[username] = user_counts.get(username, 0) + 1
            
            # Most active users
            top_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            
            embed.add_field(
                name="Messages Analyzed",
                value=str(len(messages)),
                inline=True
            )
            
            embed.add_field(
                name="Unique Users",
                value=str(len(user_counts)),
                inline=True
            )
            
            if top_users:
                top_users_text = "\n".join([f"{user}: {count}" for user, count in top_users])
                embed.add_field(
                    name="Most Active Users",
                    value=top_users_text,
                    inline=False
                )
            
            # Recent messages preview
            recent_preview = "\n".join(messages[:5])
            if len(recent_preview) > 1000:
                recent_preview = recent_preview[:1000] + "..."
            
            embed.add_field(
                name="Recent Messages Preview",
                value=recent_preview,
                inline=False
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in summarize_messages: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="translate")
    @app_commands.describe(
        text="Text to translate",
        target_language="Target language (e.g., 'spanish', 'french', 'german')"
    )
    async def translate_text(self, interaction: discord.Interaction, text: str, target_language: str):
        """Translate text to another language"""
        try:
            # This is a placeholder since we don't have AI integration
            # In a real implementation, you would use a translation API
            
            embed = discord.Embed(
                title="Translation Request",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Original Text", value=text[:1000], inline=False)
            embed.add_field(name="Target Language", value=target_language.title(), inline=True)
            embed.add_field(
                name="Translation", 
                value="Translation feature requires AI integration setup. Please contact an administrator.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in translate_text: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="ask")
    @app_commands.describe(question="Question to ask the AI")
    async def ask_ai(self, interaction: discord.Interaction, question: str):
        """Ask a question to the AI"""
        try:
            # This is a placeholder since we don't have AI integration
            embed = discord.Embed(
                title="AI Question",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Your Question", value=question, inline=False)
            embed.add_field(
                name="AI Response", 
                value="AI integration is not configured. Please contact an administrator to set up AI features.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in ask_ai: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="analyze")
    @app_commands.describe(count="Number of messages to analyze (default: 100)")
    async def analyze_conversation(self, interaction: discord.Interaction, count: int = 100):
        """Analyze conversation patterns"""
        try:
            if count > 500:
                count = 500
            
            await interaction.response.defer(ephemeral=True)
            
            # Collect messages
            messages = []
            word_count = {}
            user_activity = {}
            hourly_activity = {}
            
            async for message in interaction.channel.history(limit=count):
                if message.author.bot:
                    continue
                
                messages.append(message)
                
                # Count user activity
                user_id = message.author.id
                user_activity[user_id] = user_activity.get(user_id, 0) + 1
                
                # Count hourly activity
                hour = message.created_at.hour
                hourly_activity[hour] = hourly_activity.get(hour, 0) + 1
                
                # Count words
                words = message.content.lower().split()
                for word in words:
                    if len(word) > 3:  # Only count words longer than 3 characters
                        word_count[word] = word_count.get(word, 0) + 1
            
            if not messages:
                await interaction.followup.send("No messages found to analyze.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="Conversation Analysis",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Messages Analyzed",
                value=str(len(messages)),
                inline=True
            )
            
            embed.add_field(
                name="Unique Users",
                value=str(len(user_activity)),
                inline=True
            )
            
            # Most active users
            top_users = sorted(user_activity.items(), key=lambda x: x[1], reverse=True)[:5]
            if top_users:
                user_list = []
                for user_id, count in top_users:
                    user = interaction.guild.get_member(user_id)
                    username = user.display_name if user else f"Unknown ({user_id})"
                    user_list.append(f"{username}: {count}")
                
                embed.add_field(
                    name="Most Active Users",
                    value="\n".join(user_list),
                    inline=False
                )
            
            # Most common words
            top_words = sorted(word_count.items(), key=lambda x: x[1], reverse=True)[:10]
            if top_words:
                word_list = [f"{word}: {count}" for word, count in top_words]
                embed.add_field(
                    name="Most Common Words",
                    value="\n".join(word_list),
                    inline=False
                )
            
            # Peak activity hours
            peak_hours = sorted(hourly_activity.items(), key=lambda x: x[1], reverse=True)[:5]
            if peak_hours:
                hour_list = [f"{hour:02d}:00 - {count} messages" for hour, count in peak_hours]
                embed.add_field(
                    name="Peak Activity Hours (UTC)",
                    value="\n".join(hour_list),
                    inline=False
                )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in analyze_conversation: {e}")
            traceback.print_exc()

class WorkflowCommands(commands.GroupCog, name="workflow"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="create")
    @app_commands.describe(
        name="Name of the workflow",
        trigger="Trigger type (message:text, member_join, member_leave, thread_create, channel_create)",
        trigger_channel="Channel to monitor for triggers (optional)",
        log_channel="Channel for workflow logs (optional)"
    )
    async def create_workflow(
        self, 
        interaction: discord.Interaction, 
        name: str,
        trigger: str,
        trigger_channel: discord.TextChannel = None,
        log_channel: discord.TextChannel = None
    ):
        """Create a new workflow"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to create workflows.", ephemeral=True)
                return
            
            # Validate trigger type
            valid_triggers = ["message:text", "member_join", "member_leave", "thread_create", "channel_create"]
            if not any(trigger.startswith(t) for t in valid_triggers):
                await interaction.response.send_message(
                    f"Invalid trigger type. Valid triggers: {', '.join(valid_triggers)}",
                    ephemeral=True
                )
                return
            
            # Parse trigger value for message:text triggers
            trigger_value = None
            if trigger.startswith("message:"):
                parts = trigger.split(":", 1)
                if len(parts) > 1:
                    trigger_value = parts[1]
                    trigger = "message:text"
            
            # Create workflow with basic actions (user will need to configure actions separately)
            default_actions = [
                {
                    "type": "send_message",
                    "channel_id": interaction.channel.id,
                    "content": f"Workflow '{name}' triggered!"
                }
            ]
            
            async with self.bot.db_pool.acquire() as conn:
                # Check if workflow name already exists
                existing = await conn.fetchrow(
                    "SELECT name FROM workflows WHERE guild_id = $1 AND name = $2",
                    interaction.guild.id, name
                )
                
                if existing:
                    await interaction.response.send_message(f"Workflow '{name}' already exists.", ephemeral=True)
                    return
                
                # Create workflow
                await conn.execute(
                    """
                    INSERT INTO workflows (guild_id, name, trigger_type, trigger_value, trigger_channel_id, actions, log_channel_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    interaction.guild.id, name, trigger, trigger_value,
                    trigger_channel.id if trigger_channel else None,
                    json.dumps(default_actions),
                    log_channel.id if log_channel else None
                )
            
            embed = discord.Embed(
                title="Workflow Created",
                description=f"Workflow '{name}' has been created with default actions.",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Trigger", value=trigger, inline=True)
            
            if trigger_value:
                embed.add_field(name="Trigger Value", value=trigger_value, inline=True)
            
            if trigger_channel:
                embed.add_field(name="Trigger Channel", value=trigger_channel.mention, inline=True)
            
            if log_channel:
                embed.add_field(name="Log Channel", value=log_channel.mention, inline=True)
            
            embed.add_field(
                name="Default Action",
                value=f"Send message to {interaction.channel.mention}",
                inline=False
            )
            
            embed.add_field(
                name="Next Steps",
                value="Use the dashboard to configure advanced workflow actions.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in create_workflow: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="list")
    async def list_workflows(self, interaction: discord.Interaction):
        """List all workflows"""
        try:
            async with self.bot.db_pool.acquire() as conn:
                workflows = await conn.fetch(
                    "SELECT * FROM workflows WHERE guild_id = $1",
                    interaction.guild.id
                )
            
            if not workflows:
                await interaction.response.send_message("No workflows found.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="Workflows",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            for workflow in workflows:
                trigger_info = workflow['trigger_type']
                if workflow['trigger_value']:
                    trigger_info += f": {workflow['trigger_value']}"
                
                channel_info = ""
                if workflow['trigger_channel_id']:
                    channel = interaction.guild.get_channel(workflow['trigger_channel_id'])
                    channel_info = f" in {channel.mention}" if channel else " in deleted channel"
                
                status = "Enabled" if workflow['is_enabled'] else "Disabled"
                
                actions = json.loads(workflow['actions'])
                action_count = len(actions)
                
                value = f"Trigger: {trigger_info}{channel_info}\n"
                value += f"Status: {status}\n"
                value += f"Actions: {action_count}"
                
                embed.add_field(
                    name=workflow['name'],
                    value=value,
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in list_workflows: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="toggle")
    @app_commands.describe(workflow_name="Name of the workflow to toggle")
    async def toggle_workflow(self, interaction: discord.Interaction, workflow_name: str):
        """Enable or disable a workflow"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to toggle workflows.", ephemeral=True)
                return
            
            async with self.bot.db_pool.acquire() as conn:
                workflow = await conn.fetchrow(
                    "SELECT * FROM workflows WHERE guild_id = $1 AND name = $2",
                    interaction.guild.id, workflow_name
                )
                
                if not workflow:
                    await interaction.response.send_message(f"Workflow '{workflow_name}' not found.", ephemeral=True)
                    return
                
                # Toggle workflow
                new_status = not workflow['is_enabled']
                await conn.execute(
                    "UPDATE workflows SET is_enabled = $1 WHERE guild_id = $2 AND name = $3",
                    new_status, interaction.guild.id, workflow_name
                )
            
            status_text = "enabled" if new_status else "disabled"
            await interaction.response.send_message(f"Workflow '{workflow_name}' is now {status_text}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in toggle_workflow: {e}")
            traceback.print_exc()

class IntegrationCommands(commands.GroupCog, name="integration"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="google-connect")
    async def google_connect(self, interaction: discord.Interaction):
        """Connect to Google services"""
        try:
            # This is a placeholder since we don't have actual Google integration
            embed = discord.Embed(
                title="Google Integration",
                description="Google integration is not configured.",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Setup Required",
                value="Please contact an administrator to set up Google integration.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in google_connect: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="google-events")
    @app_commands.describe(count="Number of events to fetch (default: 5)")
    async def google_events(self, interaction: discord.Interaction, count: int = 5):
        """Fetch upcoming Google Calendar events"""
        try:
            # This is a placeholder since we don't have actual Google integration
            embed = discord.Embed(
                title="Google Calendar Events",
                description="Google Calendar integration is not configured.",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Setup Required",
                value="Please contact an administrator to set up Google Calendar integration.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in google_events: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="notion-connect")
    async def notion_connect(self, interaction: discord.Interaction):
        """Connect to Notion"""
        try:
            # This is a placeholder since we don't have actual Notion integration
            embed = discord.Embed(
                title="Notion Integration",
                description="Notion integration is not configured.",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Setup Required",
                value="Please contact an administrator to set up Notion integration.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in notion_connect: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="notion-pages")
    async def notion_pages(self, interaction: discord.Interaction):
        """List Notion pages"""
        try:
            # This is a placeholder since we don't have actual Notion integration
            embed = discord.Embed(
                title="Notion Pages",
                description="Notion integration is not configured.",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Setup Required",
                value="Please contact an administrator to set up Notion integration.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in notion_pages: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="trello-connect")
    async def trello_connect(self, interaction: discord.Interaction):
        """Connect to Trello"""
        try:
            # This is a placeholder since we don't have actual Trello integration
            embed = discord.Embed(
                title="Trello Integration",
                description="Trello integration is not configured.",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Setup Required",
                value="Please contact an administrator to set up Trello integration.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in trello_connect: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="trello-boards")
    async def trello_boards(self, interaction: discord.Interaction):
        """List Trello boards"""
        try:
            # This is a placeholder since we don't have actual Trello integration
            embed = discord.Embed(
                title="Trello Boards",
                description="Trello integration is not configured.",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Setup Required",
                value="Please contact an administrator to set up Trello integration.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in trello_boards: {e}")
            traceback.print_exc()

class AdminCommands(commands.GroupCog, name="admin"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="role-add")
    @app_commands.describe(role="Role to add as admin role")
    async def add_admin_role(self, interaction: discord.Interaction, role: discord.Role):
        """Add a role as an admin role"""
        try:
            # Check if user is server admin
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
                return
            
            # Add role to admin roles
            async with self.bot.db_pool.acquire() as conn:
                try:
                    await conn.execute(
                        "INSERT INTO admin_roles (guild_id, role_id) VALUES ($1, $2)",
                        interaction.guild.id, role.id
                    )
                    
                    await interaction.response.send_message(f"Added {role.mention} as an admin role.", ephemeral=True)
                except Exception:
                    await interaction.response.send_message(f"{role.mention} is already an admin role.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in add_admin_role: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="role-remove")
    @app_commands.describe(role="Role to remove from admin roles")
    async def remove_admin_role(self, interaction: discord.Interaction, role: discord.Role):
        """Remove a role from admin roles"""
        try:
            # Check if user is server admin
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
                return
            
            # Remove role from admin roles
            async with self.bot.db_pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM admin_roles WHERE guild_id = $1 AND role_id = $2",
                    interaction.guild.id, role.id
                )
                
                if result == "DELETE 0":
                    await interaction.response.send_message(f"{role.mention} is not an admin role.", ephemeral=True)
                    return
            
            await interaction.response.send_message(f"Removed {role.mention} from admin roles.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in remove_admin_role: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="role-list")
    async def list_admin_roles(self, interaction: discord.Interaction):
        """List admin roles"""
        try:
            async with self.bot.db_pool.acquire() as conn:
                admin_roles = await conn.fetch(
                    "SELECT role_id FROM admin_roles WHERE guild_id = $1",
                    interaction.guild.id
                )
            
            if not admin_roles:
                await interaction.response.send_message("No admin roles configured.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="Admin Roles",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            role_list = []
            for admin_role in admin_roles:
                role = interaction.guild.get_role(admin_role['role_id'])
                if role:
                    role_list.append(role.mention)
                else:
                    role_list.append(f"Deleted Role ({admin_role['role_id']})")
            
            embed.description = "\n".join(role_list)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in list_admin_roles: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="purge")
    @app_commands.describe(
        count="Number of messages to delete",
        user="Delete messages from specific user only"
    )
    async def purge_messages(self, interaction: discord.Interaction, count: int, user: discord.User = None):
        """Purge messages from the channel"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to purge messages.", ephemeral=True)
                return
            
            if count > 100:
                count = 100
            
            await interaction.response.defer(ephemeral=True)
            
            # Delete messages
            deleted = 0
            async for message in interaction.channel.history(limit=count):
                if user and message.author != user:
                    continue
                
                try:
                    await message.delete()
                    deleted += 1
                except discord.NotFound:
                    # Message already deleted
                    pass
                except discord.Forbidden:
                    # Can't delete message
                    break
            
            await interaction.followup.send(f"Deleted {deleted} messages.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in purge_messages: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="status")
    async def bot_status(self, interaction: discord.Interaction):
        """Get bot status information"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to view bot status.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="Bot Status",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            
            # Basic info
            embed.add_field(name="Bot Name", value=self.bot.user.name, inline=True)
            embed.add_field(name="Bot ID", value=self.bot.user.id, inline=True)
            embed.add_field(name="Guilds", value=len(self.bot.guilds), inline=True)
            
            # Database status
            db_status = "Connected" if self.bot.db_pool else "Disconnected"
            embed.add_field(name="Database", value=db_status, inline=True)
            
            # Background tasks status
            github_status = "Running" if self.bot.github_checker.is_running() else "Stopped"
            reminder_status = "Running" if self.bot.reminder_checker.is_running() else "Stopped"
            
            embed.add_field(name="GitHub Checker", value=github_status, inline=True)
            embed.add_field(name="Reminder Checker", value=reminder_status, inline=True)
            
            # Memory usage (basic)
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            embed.add_field(name="Memory Usage", value=f"{memory_mb:.1f} MB", inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in bot_status: {e}")
            traceback.print_exc()

class LogCommands(commands.GroupCog, name="log"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="setup")
    @app_commands.describe(channel="Channel for server logs")
    async def setup_logging(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set up server logging"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to set up logging.", ephemeral=True)
                return
            
            # Update server config
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO server_config (guild_id, log_channel_id)
                    VALUES ($1, $2)
                    ON CONFLICT (guild_id) 
                    DO UPDATE SET log_channel_id = $2
                    """,
                    interaction.guild.id, channel.id
                )
            
            await interaction.response.send_message(
                f"Logging set up successfully!\nLogs will be sent to {channel.mention}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in setup_logging: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="disable")
    async def disable_logging(self, interaction: discord.Interaction):
        """Disable server logging"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to disable logging.", ephemeral=True)
                return
            
            # Update server config
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE server_config 
                    SET log_channel_id = NULL 
                    WHERE guild_id = $1
                    """,
                    interaction.guild.id
                )
            
            await interaction.response.send_message("Logging disabled.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in disable_logging: {e}")
            traceback.print_exc()

class PrivacyCommands(commands.GroupCog, name="privacy"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="data-export")
    async def export_data(self, interaction: discord.Interaction):
        """Export your data from the bot"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            user_data = {}
            
            async with self.bot.db_pool.acquire() as conn:
                # Get user's tickets
                tickets = await conn.fetch(
                    "SELECT * FROM tickets WHERE creator_id = $1 AND guild_id = $2",
                    interaction.user.id, interaction.guild.id
                )
                user_data['tickets'] = [dict(ticket) for ticket in tickets]
                
                # Get user's reminders
                reminders = await conn.fetch(
                    "SELECT * FROM reminders WHERE user_id = $1 AND guild_id = $2",
                    interaction.user.id, interaction.guild.id
                )
                user_data['reminders'] = [dict(reminder) for reminder in reminders]
                
                # Get user's keywords
                keywords = await conn.fetch(
                    "SELECT * FROM keywords WHERE user_id = $1 AND guild_id = $2",
                    interaction.user.id, interaction.guild.id
                )
                user_data['keywords'] = [dict(keyword) for keyword in keywords]
                
                # Get user's meetings
                meetings = await conn.fetch(
                    "SELECT * FROM meetings WHERE creator_id = $1 AND guild_id = $2",
                    interaction.user.id, interaction.guild.id
                )
                user_data['meetings'] = [dict(meeting) for meeting in meetings]
            
            # Convert to JSON
            import json
            data_json = json.dumps(user_data, indent=2, default=str)
            
            # Create file
            import io
            file_buffer = io.StringIO(data_json)
            file = discord.File(file_buffer, filename=f"user_data_{interaction.user.id}.json")
            
            embed = discord.Embed(
                title="Data Export",
                description="Your data has been exported. This includes tickets, reminders, keywords, and meetings you've created.",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in export_data: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="data-delete")
    async def delete_data(self, interaction: discord.Interaction):
        """Delete all your data from the bot"""
        try:
            # Create confirmation view
            class ConfirmView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=60)
                
                @discord.ui.button(label="Confirm Delete", style=discord.ButtonStyle.danger)
                async def confirm_delete(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                    if button_interaction.user != interaction.user:
                        await button_interaction.response.send_message("You can't confirm this action.", ephemeral=True)
                        return
                    
                    try:
                        async with self.bot.db_pool.acquire() as conn:
                            # Delete user's data
                            await conn.execute("DELETE FROM reminders WHERE user_id = $1 AND guild_id = $2", interaction.user.id, interaction.guild.id)
                            await conn.execute("DELETE FROM keywords WHERE user_id = $1 AND guild_id = $2", interaction.user.id, interaction.guild.id)
                            
                            # Note: We don't delete tickets and meetings as they may involve other users
                            # Instead, we could anonymize them or mark them as deleted
                        
                        await button_interaction.response.send_message("Your personal data has been deleted.", ephemeral=True)
                    except Exception as e:
                        await button_interaction.response.send_message(f"Error deleting data: {str(e)}", ephemeral=True)
                        logger.error(f"Error in delete_data confirmation: {e}")
                
                @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
                async def cancel_delete(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                    if button_interaction.user != interaction.user:
                        await button_interaction.response.send_message("You can't cancel this action.", ephemeral=True)
                        return
                    
                    await button_interaction.response.send_message("Data deletion cancelled.", ephemeral=True)
                    self.stop()
            
            embed = discord.Embed(
                title="⚠️ Data Deletion Confirmation",
                description="This will delete all your personal data including reminders and keywords. Tickets and meetings will be preserved but anonymized.\n\n**This action cannot be undone.**",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            
            await interaction.response.send_message(embed=embed, view=ConfirmView(), ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in delete_data: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="policy")
    async def privacy_policy(self, interaction: discord.Interaction):
        """View the bot's privacy policy"""
        try:
            embed = discord.Embed(
                title="Privacy Policy",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Data Collection",
                value="We collect only the data necessary for bot functionality: user IDs, message content for commands, and configuration data.",
                inline=False
            )
            
            embed.add_field(
                name="Data Usage",
                value="Your data is used solely to provide bot services like reminders, tickets, and notifications. We do not share data with third parties.",
                inline=False
            )
            
            embed.add_field(
                name="Data Retention",
                value="Data is retained until you delete it or leave the server. You can export or delete your data at any time.",
                inline=False
            )
            
            embed.add_field(
                name="Your Rights",
                value="You have the right to access, export, and delete your data. Use `/privacy data-export` and `/privacy data-delete` commands.",
                inline=False
            )
            
            embed.add_field(
                name="Contact",
                value="For privacy concerns, contact the server administrators.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in privacy_policy: {e}")
            traceback.print_exc()

class HelpCommands(commands.GroupCog, name="help"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="commands")
    async def list_commands(self, interaction: discord.Interaction):
        """List all available commands"""
        try:
            embed = discord.Embed(
                title="Bot Commands",
                description="Here are all the available command groups:",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            command_groups = {
                "🎫 Ticket": "Create and manage support tickets",
                "🐙 GitHub": "Track GitHub repositories",
                "⏰ Reminder": "Set personal and channel reminders",
                "📅 Meeting": "Schedule and manage meetings",
                "🔔 Notification": "Monitor keywords in messages",
                "👥 Role": "Manage user roles",
                "👤 User": "Get user information and permissions",
                "🗨️ Conversation": "Manage threads and messages",
                "🤖 AI": "AI-powered features (requires setup)",
                "⚙️ Workflow": "Automate server actions",
                "🔗 Integration": "Connect external services",
                "🛡️ Admin": "Administrative commands",
                "📝 Log": "Server event logging",
                "🔒 Privacy": "Data management and privacy",
                "❓ Help": "Get help and information"
            }
            
            for group, description in command_groups.items():
                embed.add_field(
                    name=group,
                    value=description,
                    inline=True
                )
            
            embed.add_field(
                name="Usage",
                value="Use `/[group] [command]` to run commands. For example: `/ticket create`",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in list_commands: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="setup")
    async def setup_guide(self, interaction: discord.Interaction):
        """Get setup guide for the bot"""
        try:
            embed = discord.Embed(
                title="Bot Setup Guide",
                description="Follow these steps to set up the bot features:",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            
            setup_steps = [
                "1. **Admin Roles**: `/admin role-add @role` - Add admin roles",
                "2. **Tickets**: `/ticket setup #category #transcript-channel` - Set up ticket system",
                "3. **GitHub**: `/github setup #notifications-channel` - Set up GitHub tracking",
                "4. **Reminders**: `/reminder setup #default-channel` - Set up reminders",
                "5. **Meetings**: `/meeting setup #announcements #voice-channel` - Set up meetings",
                "6. **Logging**: `/log setup #log-channel` - Set up event logging",
                "7. **Conversations**: `/conversation setup #thread-log-channel` - Set up conversation management"
            ]
            
            embed.add_field(
                name="Setup Steps",
                value="\n".join(setup_steps),
                inline=False
            )
            
            embed.add_field(
                name="Required Permissions",
                value="The bot needs Administrator permissions or specific permissions for each feature.",
                inline=False
            )
            
            embed.add_field(
                name="Optional Features",
                value="Workflows, integrations, and AI features can be set up later as needed.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in setup_guide: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="about")
    async def about_bot(self, interaction: discord.Interaction):
        """Get information about the bot"""
        try:
            embed = discord.Embed(
                title="Discord Management Bot",
                description="A comprehensive Discord management bot with advanced features.",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            
            features = [
                "🎫 Complete ticket system with transcripts",
                "🐙 GitHub repository tracking and notifications",
                "⏰ Personal and channel reminder system",
                "📅 Meeting scheduling and management",
                "🔔 Keyword monitoring and notifications",
                "👥 Advanced role management",
                "🗨️ Thread and conversation management",
                "⚙️ Workflow automation system",
                "📝 Comprehensive event logging",
                "🔒 GDPR-compliant data management",
                "🤖 AI integration support",
                "🔗 External service integrations"
            ]
            
            embed.add_field(
                name="Features",
                value="\n".join(features),
                inline=False
            )
            
            embed.add_field(
                name="Version",
                value="1.0.0",
                inline=True
            )
            
            embed.add_field(
                name="Servers",
                value=str(len(self.bot.guilds)),
                inline=True
            )
            
            embed.add_field(
                name="Support",
                value="Contact server administrators for support",
                inline=True
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in about_bot: {e}")
            traceback.print_exc()

# Main execution
if __name__ == "__main__":
    bot = DevBot()
    
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        traceback.print_exc()
    finally:
        # Cleanup
        if bot.db_pool:
            asyncio.run(bot.db_pool.close())
        logger.info("Bot shutdown complete")
