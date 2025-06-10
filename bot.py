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

# Environment variables
TOKEN = os.environ.get('DISCORD_TOKEN')
APP_ID = os.environ.get('APP_ID')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')

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

class DevBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix='!', intents=intents, application_id=APP_ID)
        self.db_pool = None
        
    async def setup_hook(self):
        # Initialize database connection pool
        try:
            self.db_pool = await asyncpg.create_pool(DATABASE_URL)
            logger.info("Database connection pool created successfully")
            await self.init_db()
        except Exception as e:
            logger.error(f"Failed to create database connection pool: {e}")
            traceback.print_exc()
            
        # Start background tasks
        self.github_checker.start()
        self.reminder_checker.start()
        
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
        
        # Sync commands with Discord
        logger.info("Syncing commands...")
        for guild in self.guilds:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        
    async def on_ready(self):
        logger.info(f'{self.user} is ready!')
        logger.info(f'Connected to {len(self.guilds)} guilds')
        
    async def on_guild_join(self, guild):
        # Sync commands to the new guild
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
        
    async def init_db(self):
        """Initialize database tables if they don't exist"""
        try:
            async with self.db_pool.acquire() as conn:
                # Create tables based on schema
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
            traceback.print_exc()
    
    @tasks.loop(minutes=30)
    async def github_checker(self):
        """Check GitHub repositories for updates every 30 minutes"""
        if not self.is_ready():
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
        if not self.is_ready():
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
            
            # Set up close ticket button handler
            @self.bot.tree.context_menu(name="Close Ticket")
            async def close_ticket(interaction: discord.Interaction, message: discord.Message):
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
                    
                    # Check if user is ticket creator, assigned, or admin
                    is_admin_user = await is_admin(interaction)
                    is_creator = interaction.user.id == ticket['creator_id']
                    is_assigned = interaction.user.id in json.loads(ticket['assigned_users'])
                    
                    if not (is_admin_user or is_creator or is_assigned):
                        await interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
                        return
                    
                    # Mark ticket as closed
                    await conn.execute(
                        "UPDATE tickets SET status = 'closed' WHERE id = $1",
                        ticket['id']
                    )
                    
                    # Get transcript channel
                    config = await conn.fetchrow(
                        "SELECT ticket_transcript_channel_id FROM server_config WHERE guild_id = $1",
                        interaction.guild.id
                    )
                    
                    transcript_channel_id = config['ticket_transcript_channel_id'] if config else None
                    transcript_channel = interaction.guild.get_channel(transcript_channel_id) if transcript_channel_id else None
                    
                    # Generate transcript
                    await interaction.response.send_message("Generating transcript and closing ticket...")
                    
                    if transcript_channel:
                        transcript_parts = await generate_transcript(interaction.channel)
                        
                        # Create transcript embed
                        embed = discord.Embed(
                            title=f"Ticket Transcript: {ticket['title']}",
                            description=f"Ticket ID: {ticket['id']}\nClosed by: {interaction.user.mention}",
                            color=discord.Color.blue(),
                            timestamp=datetime.utcnow()
                        )
                        
                        creator = interaction.guild.get_member(ticket['creator_id'])
                        creator_name = creator.mention if creator else f"Unknown ({ticket['creator_id']})"
                        
                        embed.add_field(name="Creator", value=creator_name, inline=True)
                        embed.add_field(name="Status", value="Closed", inline=True)
                        embed.add_field(name="Priority", value=ticket['priority'], inline=True)
                        
                        await transcript_channel.send(embed=embed)
                        
                        # Send transcript parts
                        for i, part in enumerate(transcript_parts):
                            await transcript_channel.send(f"**Transcript Part {i+1}/{len(transcript_parts)}**\n{part}")
                    
                    # Delete channel after 10 seconds
                    await interaction.channel.send("This ticket has been closed. Channel will be deleted in 10 seconds.")
                    await asyncio.sleep(10)
                    await interaction.channel.delete()
            
            # Sync commands
            await self.bot.tree.sync(guild=interaction.guild)
            
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
            
            role_mentions = []
            for row in admin_roles:
                role = interaction.guild.get_role(row['role_id'])
                if role:
                    role_mentions.append(role.mention)
                else:
                    role_mentions.append(f"Deleted Role ({row['role_id']})")
            
            embed.description = "\n".join(role_mentions)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in list_admin_roles: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="panel")
    async def admin_panel(self, interaction: discord.Interaction):
        """Open admin panel"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to access the admin panel.", ephemeral=True)
                return
            
            # Get server config
            async with self.bot.db_pool.acquire() as conn:
                config = await conn.fetchrow(
                    "SELECT * FROM server_config WHERE guild_id = $1",
                    interaction.guild.id
                )
                
                # Get counts
                ticket_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM tickets WHERE guild_id = $1",
                    interaction.guild.id
                )
                
                reminder_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM reminders WHERE guild_id = $1",
                    interaction.guild.id
                )
                
                github_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM github_repos WHERE guild_id = $1",
                    interaction.guild.id
                )
                
                meeting_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM meetings WHERE guild_id = $1",
                    interaction.guild.id
                )
                
                workflow_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM workflows WHERE guild_id = $1",
                    interaction.guild.id
                )
            
            embed = discord.Embed(
                title="Admin Panel",
                description="Server configuration and statistics",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            # Configuration
            config_info = []
            if config:
                if config['ticket_category_id']:
                    category = interaction.guild.get_channel(config['ticket_category_id'])
                    config_info.append(f"Ticket Category: {category.mention if category else 'Deleted'}")
                
                if config['ticket_transcript_channel_id']:
                    channel = interaction.guild.get_channel(config['ticket_transcript_channel_id'])
                    config_info.append(f"Ticket Transcript Channel: {channel.mention if channel else 'Deleted'}")
                
                if config['github_channel_id']:
                    channel = interaction.guild.get_channel(config['github_channel_id'])
                    config_info.append(f"GitHub Channel: {channel.mention if channel else 'Deleted'}")
                
                if config['reminder_channel_id']:
                    channel = interaction.guild.get_channel(config['reminder_channel_id'])
                    config_info.append(f"Reminder Channel: {channel.mention if channel else 'Deleted'}")
                
                if config['meeting_announcement_channel_id']:
                    channel = interaction.guild.get_channel(config['meeting_announcement_channel_id'])
                    config_info.append(f"Meeting Announcement Channel: {channel.mention if channel else 'Deleted'}")
                
                if config['log_channel_id']:
                    channel = interaction.guild.get_channel(config['log_channel_id'])
                    config_info.append(f"Log Channel: {channel.mention if channel else 'Deleted'}")
            
            if config_info:
                embed.add_field(
                    name="Configuration",
                    value="\n".join(config_info),
                    inline=False
                )
            else:
                embed.add_field(
                    name="Configuration",
                    value="No configuration found. Use setup commands to configure the bot.",
                    inline=False
                )
            
            # Statistics
            embed.add_field(name="Active Tickets", value=str(ticket_count), inline=True)
            embed.add_field(name="Active Reminders", value=str(reminder_count), inline=True)
            embed.add_field(name="GitHub Repos", value=str(github_count), inline=True)
            embed.add_field(name="Meetings", value=str(meeting_count), inline=True)
            embed.add_field(name="Workflows", value=str(workflow_count), inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in admin_panel: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="export")
    @app_commands.describe(user="User to export data for")
    async def export_user_data(self, interaction: discord.Interaction, user: discord.User):
        """Export user data"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to export user data.", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            # Get user data
            async with self.bot.db_pool.acquire() as conn:
                # Get tickets
                tickets = await conn.fetch(
                    "SELECT * FROM tickets WHERE creator_id = $1 AND guild_id = $2",
                    user.id, interaction.guild.id
                )
                
                # Get reminders
                reminders = await conn.fetch(
                    "SELECT * FROM reminders WHERE user_id = $1 AND guild_id = $2",
                    user.id, interaction.guild.id
                )
                
                # Get keywords
                keywords = await conn.fetch(
                    "SELECT * FROM keywords WHERE user_id = $1 AND guild_id = $2",
                    user.id, interaction.guild.id
                )
                
                # Get meetings
                meetings = await conn.fetch(
                    "SELECT * FROM meetings WHERE creator_id = $1 AND guild_id = $2",
                    user.id, interaction.guild.id
                )
            
            # Create export data
            export_data = {
                "user_id": user.id,
                "username": user.name,
                "guild_id": interaction.guild.id,
                "guild_name": interaction.guild.name,
                "export_time": datetime.utcnow().isoformat(),
                "tickets": [dict(ticket) for ticket in tickets],
                "reminders": [dict(reminder) for reminder in reminders],
                "keywords": [dict(keyword) for keyword in keywords],
                "meetings": [dict(meeting) for meeting in meetings]
            }
            
            # Convert to JSON
            export_json = json.dumps(export_data, indent=2, default=str)
            
            # Send as file
            file = discord.File(
                io.BytesIO(export_json.encode()),
                filename=f"user_data_{user.id}.json"
            )
            
            await interaction.followup.send(
                f"Exported data for {user.mention}",
                file=file,
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in export_user_data: {e}")
            traceback.print_exc()

class LogCommands(commands.GroupCog, name="log"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="setup")
    @app_commands.describe(
        log_channel="Channel for logs",
        events="Events to log (comma-separated, e.g., 'message_delete,member_join')"
    )
    async def setup_logging(self, interaction: discord.Interaction, log_channel: discord.TextChannel, events: str):
        """Set up logging system"""
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
                    interaction.guild.id, log_channel.id
                )
            
            # Parse events
            event_list = [e.strip() for e in events.split(",")]
            valid_events = [
                "message_delete", "message_edit", "member_join", "member_leave",
                "role_create", "role_delete", "role_update", "channel_create", "channel_delete"
            ]
            
            valid_event_list = [e for e in event_list if e in valid_events]
            invalid_events = [e for e in event_list if e not in valid_events]
            
            embed = discord.Embed(
                title="Logging Setup",
                description=f"Logging has been set up in {log_channel.mention}",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            
            if valid_event_list:
                embed.add_field(
                    name="Enabled Events",
                    value="\n".join(valid_event_list),
                    inline=False
                )
            
            if invalid_events:
                embed.add_field(
                    name="Invalid Events (Ignored)",
                    value="\n".join(invalid_events),
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in setup_logging: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="export")
    @app_commands.describe(data_type="Type of data to export (e.g., 'tickets', 'reminders')")
    async def export_logs(self, interaction: discord.Interaction, data_type: str = None):
        """Export logs"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to export logs.", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            # Get data
            async with self.bot.db_pool.acquire() as conn:
                if data_type == "tickets" or not data_type:
                    tickets = await conn.fetch(
                        "SELECT * FROM tickets WHERE guild_id = $1",
                        interaction.guild.id
                    )
                    
                    # Convert to JSON
                    tickets_json = json.dumps([dict(ticket) for ticket in tickets], indent=2, default=str)
                    
                    # Send as file
                    file = discord.File(
                        io.BytesIO(tickets_json.encode()),
                        filename=f"tickets_{interaction.guild.id}.json"
                    )
                    
                    await interaction.followup.send(
                        f"Exported {len(tickets)} tickets",
                        file=file,
                        ephemeral=True
                    )
                
                elif data_type == "reminders":
                    reminders = await conn.fetch(
                        "SELECT * FROM reminders WHERE guild_id = $1",
                        interaction.guild.id
                    )
                    
                    # Convert to JSON
                    reminders_json = json.dumps([dict(reminder) for reminder in reminders], indent=2, default=str)
                    
                    # Send as file
                    file = discord.File(
                        io.BytesIO(reminders_json.encode()),
                        filename=f"reminders_{interaction.guild.id}.json"
                    )
                    
                    await interaction.followup.send(
                        f"Exported {len(reminders)} reminders",
                        file=file,
                        ephemeral=True
                    )
                
                elif data_type == "github":
                    repos = await conn.fetch(
                        "SELECT * FROM github_repos WHERE guild_id = $1",
                        interaction.guild.id
                    )
                    
                    # Convert to JSON
                    repos_json = json.dumps([dict(repo) for repo in repos], indent=2, default=str)
                    
                    # Send as file
                    file = discord.File(
                        io.BytesIO(repos_json.encode()),
                        filename=f"github_repos_{interaction.guild.id}.json"
                    )
                    
                    await interaction.followup.send(
                        f"Exported {len(repos)} GitHub repositories",
                        file=file,
                        ephemeral=True
                    )
                
                elif data_type == "meetings":
                    meetings = await conn.fetch(
                        "SELECT * FROM meetings WHERE guild_id = $1",
                        interaction.guild.id
                    )
                    
                    # Convert to JSON
                    meetings_json = json.dumps([dict(meeting) for meeting in meetings], indent=2, default=str)
                    
                    # Send as file
                    file = discord.File(
                        io.BytesIO(meetings_json.encode()),
                        filename=f"meetings_{interaction.guild.id}.json"
                    )
                    
                    await interaction.followup.send(
                        f"Exported {len(meetings)} meetings",
                        file=file,
                        ephemeral=True
                    )
                
                elif data_type == "workflows":
                    workflows = await conn.fetch(
                        "SELECT * FROM workflows WHERE guild_id = $1",
                        interaction.guild.id
                    )
                    
                    # Convert to JSON
                    workflows_json = json.dumps([dict(workflow) for workflow in workflows], indent=2, default=str)
                    
                    # Send as file
                    file = discord.File(
                        io.BytesIO(workflows_json.encode()),
                        filename=f"workflows_{interaction.guild.id}.json"
                    )
                    
                    await interaction.followup.send(
                        f"Exported {len(workflows)} workflows",
                        file=file,
                        ephemeral=True
                    )
                
                else:
                    await interaction.followup.send(
                        f"Unknown data type: {data_type}. Valid types: tickets, reminders, github, meetings, workflows",
                        ephemeral=True
                    )
        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in export_logs: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="delete")
    @app_commands.describe(
        data_type="Type of data to delete (e.g., 'tickets', 'reminders')",
        confirm="Type 'confirm' to confirm deletion"
    )
    async def delete_logs(self, interaction: discord.Interaction, data_type: str, confirm: bool):
        """Delete logs"""
        try:
            # Check if user is admin
            if not await is_admin(interaction):
                await interaction.response.send_message("You don't have permission to delete logs.", ephemeral=True)
                return
            
            # Check confirmation
            if not confirm:
                await interaction.response.send_message(
                    f"To confirm deletion of {data_type} data, set confirm=True",
                    ephemeral=True
                )
                return
            
            # Delete data
            async with self.bot.db_pool.acquire() as conn:
                if data_type == "tickets":
                    result = await conn.execute(
                        "DELETE FROM tickets WHERE guild_id = $1 AND status = 'closed'",
                        interaction.guild.id
                    )
                    
                    await interaction.response.send_message(
                        f"Deleted closed tickets from the database.",
                        ephemeral=True
                    )
                
                elif data_type == "reminders":
                    result = await conn.execute(
                        "DELETE FROM reminders WHERE guild_id = $1 AND remind_time < $2",
                        interaction.guild.id, datetime.utcnow()
                    )
                    
                    await interaction.response.send_message(
                        f"Deleted expired reminders from the database.",
                        ephemeral=True
                    )
                
                elif data_type == "meetings":
                    result = await conn.execute(
                        "DELETE FROM meetings WHERE guild_id = $1 AND meeting_time < $2",
                        interaction.guild.id, datetime.utcnow()
                    )
                    
                    await interaction.response.send_message(
                        f"Deleted past meetings from the database.",
                        ephemeral=True
                    )
                
                else:
                    await interaction.response.send_message(
                        f"Unknown data type: {data_type}. Valid types: tickets, reminders, meetings",
                        ephemeral=True
                    )
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in delete_logs: {e}")
            traceback.print_exc()

class PrivacyCommands(commands.GroupCog, name="privacy"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="export")
    async def export_data(self, interaction: discord.Interaction):
        """Export your personal data"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Get user data
            async with self.bot.db_pool.acquire() as conn:
                # Get tickets
                tickets = await conn.fetch(
                    "SELECT * FROM tickets WHERE creator_id = $1",
                    interaction.user.id
                )
                
                # Get reminders
                reminders = await conn.fetch(
                    "SELECT * FROM reminders WHERE user_id = $1",
                    interaction.user.id
                )
                
                # Get keywords
                keywords = await conn.fetch(
                    "SELECT * FROM keywords WHERE user_id = $1",
                    interaction.user.id
                )
                
                # Get meetings
                meetings = await conn.fetch(
                    "SELECT * FROM meetings WHERE creator_id = $1 OR participants::text LIKE $2",
                    interaction.user.id, f"%{interaction.user.id}%"
                )
            
            # Create export data
            export_data = {
                "user_id": interaction.user.id,
                "username": interaction.user.name,
                "export_time": datetime.utcnow().isoformat(),
                "tickets": [dict(ticket) for ticket in tickets],
                "reminders": [dict(reminder) for reminder in reminders],
                "keywords": [dict(keyword) for keyword in keywords],
                "meetings": [dict(meeting) for meeting in meetings]
            }
            
            # Convert to JSON
            export_json = json.dumps(export_data, indent=2, default=str)
            
            # Send as file
            file = discord.File(
                io.BytesIO(export_json.encode()),
                filename=f"my_data_{interaction.user.id}.json"
            )
            
            await interaction.followup.send(
                "Here's your personal data export:",
                file=file,
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in export_data: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="delete")
    @app_commands.describe(data_type="Type of data to delete (leave blank to delete all)")
    async def delete_data(self, interaction: discord.Interaction, data_type: str = None):
        """Delete your personal data"""
        try:
            # Delete data
            async with self.bot.db_pool.acquire() as conn:
                if data_type == "tickets" or not data_type:
                    await conn.execute(
                        "DELETE FROM tickets WHERE creator_id = $1",
                        interaction.user.id
                    )
                
                if data_type == "reminders" or not data_type:
                    await conn.execute(
                        "DELETE FROM reminders WHERE user_id = $1",
                        interaction.user.id
                    )
                
                if data_type == "keywords" or not data_type:
                    await conn.execute(
                        "DELETE FROM keywords WHERE user_id = $1",
                        interaction.user.id
                    )
                
                if data_type == "meetings" or not data_type:
                    # For meetings, we need to handle participants differently
                    meetings = await conn.fetch(
                        "SELECT id, participants FROM meetings WHERE participants::text LIKE $1",
                        f"%{interaction.user.id}%"
                    )
                    
                    for meeting in meetings:
                        participants = json.loads(meeting['participants'])
                        if interaction.user.id in participants:
                            participants.remove(interaction.user.id)
                            
                            await conn.execute(
                                "UPDATE meetings SET participants = $1 WHERE id = $2",
                                json.dumps(participants), meeting['id']
                            )
                    
                    # Delete meetings where user is creator and no participants
                    await conn.execute(
                        """
                        DELETE FROM meetings 
                        WHERE creator_id = $1 AND (participants::text = '[]' OR participants IS NULL)
                        """,
                        interaction.user.id
                    )
            
            await interaction.response.send_message(
                f"Your {'personal data' if not data_type else data_type} has been deleted.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in delete_data: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="summary")
    async def data_summary(self, interaction: discord.Interaction):
        """Get a summary of your personal data"""
        try:
            # Get data counts
            async with self.bot.db_pool.acquire() as conn:
                ticket_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM tickets WHERE creator_id = $1",
                    interaction.user.id
                )
                
                reminder_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM reminders WHERE user_id = $1",
                    interaction.user.id
                )
                
                keyword_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM keywords WHERE user_id = $1",
                    interaction.user.id
                )
                
                meeting_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM meetings WHERE creator_id = $1 OR participants::text LIKE $2",
                    interaction.user.id, f"%{interaction.user.id}%"
                )
            
            embed = discord.Embed(
                title="Your Data Summary",
                description="Here's a summary of your personal data stored by the bot:",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Tickets", value=str(ticket_count), inline=True)
            embed.add_field(name="Reminders", value=str(reminder_count), inline=True)
            embed.add_field(name="Keywords", value=str(keyword_count), inline=True)
            embed.add_field(name="Meetings", value=str(meeting_count), inline=True)
            
            embed.add_field(
                name="Data Management",
                value="Use `/privacy export` to export your data\nUse `/privacy delete` to delete your data",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in data_summary: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="policy")
    async def privacy_policy(self, interaction: discord.Interaction):
        """View the privacy policy"""
        try:
            embed = discord.Embed(
                title="Privacy Policy",
                description="This bot collects and stores data necessary for its functionality.",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Data Collection",
                value=(
                    "The bot collects and stores the following data:\n"
                    "- User IDs for tracking tickets, reminders, etc.\n"
                    "- Message content for keyword notifications\n"
                    "- Channel and role IDs for configuration"
                ),
                inline=False
            )
            
            embed.add_field(
                name="Data Usage",
                value=(
                    "Your data is used solely for the functionality of the bot and is not shared with third parties."
                ),
                inline=False
            )
            
            embed.add_field(
                name="Data Management",
                value=(
                    "You can export your data using `/privacy export`\n"
                    "You can delete your data using `/privacy delete`"
                ),
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in privacy_policy: {e}")
            traceback.print_exc()
    
    @app_commands.command(name="terms")
    async def terms_of_service(self, interaction: discord.Interaction):
        """View the terms of service"""
        try:
            embed = discord.Embed(
                title="Terms of Service",
                description="By using this bot, you agree to the following terms:",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Usage",
                value=(
                    "The bot is provided as-is, without any warranty.\n"
                    "You agree to use the bot in compliance with Discord's Terms of Service."
                ),
                inline=False
            )
            
            embed.add_field(
                name="Limitations",
                value=(
                    "The bot may be unavailable at times for maintenance or updates.\n"
                    "The bot's functionality may change without notice."
                ),
                inline=False
            )
            
            embed.add_field(
                name="Data",
                value=(
                    "You agree that the bot may collect and store data necessary for its functionality.\n"
                    "You can manage your data using the `/privacy` commands."
                ),
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in terms_of_service: {e}")
            traceback.print_exc()

class HelpCommands(commands.GroupCog, name="help"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="help")
    @app_commands.describe(category="Command category to get help for")
    async def help_command(self, interaction: discord.Interaction, category: str = None):
        """Get help with bot commands"""
        try:
            if not category:
                # Show main help
                embed = discord.Embed(
                    title="Bot Help",
                    description="Here are the available command categories:",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                categories = [
                    ("ticket", "🎫 Ticket System", "Create and manage support tickets"),
                    ("github", "🐙 GitHub Integration", "Track GitHub repositories"),
                    ("reminder", "⏰ Reminder System", "Set reminders for yourself or channels"),
                    ("meeting", "📅 Meeting System", "Schedule and manage meetings"),
                    ("notification", "🔔 Notification System", "Get notified when keywords are mentioned"),
                    ("role", "👥 Role Management", "Manage server roles"),
                    ("user", "👤 User Management", "Get information about users"),
                    ("conversation", "🗨️ Conversation Management", "Manage threads and messages"),
                    ("ai", "🤖 AI Features", "AI-powered features"),
                    ("workflow", "⚙️ Workflow Automation", "Automate server tasks"),
                    ("integration", "🔗 Integrations", "Connect to external services"),
                    ("admin", "🛡️ Admin Commands", "Server administration"),
                    ("log", "📊 Logging System", "Configure logging"),
                    ("privacy", "🔒 Privacy & Data", "Manage your data")
                ]
                
                for cmd, emoji_name, desc in categories:
                    embed.add_field(
                        name=f"{emoji_name}",
                        value=f"`/help {cmd}` - {desc}",
                        inline=False
                    )
                
                embed.set_footer(text="Use /help <category> for more information")
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Show category help
            if category == "ticket":
                embed = discord.Embed(
                    title="🎫 Ticket System Help",
                    description="Commands for creating and managing support tickets",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/ticket create", value="Create a new support ticket", inline=False)
                embed.add_field(name="/ticket join", value="Join an existing ticket", inline=False)
                embed.add_field(name="/ticket private", value="Make a ticket private", inline=False)
                embed.add_field(name="/ticket public", value="Make a ticket public", inline=False)
                embed.add_field(name="/ticket list", value="List tickets", inline=False)
                embed.add_field(name="/ticket assign", value="Assign a user to a ticket", inline=False)
                embed.add_field(name="/ticket setup", value="Set up the ticket system", inline=False)
            
            elif category == "github":
                embed = discord.Embed(
                    title="🐙 GitHub Integration Help",
                    description="Commands for tracking GitHub repositories",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/github track", value="Track a GitHub repository", inline=False)
                embed.add_field(name="/github untrack", value="Stop tracking a repository", inline=False)
                embed.add_field(name="/github list", value="List tracked repositories", inline=False)
                embed.add_field(name="/github setup", value="Set up GitHub tracking", inline=False)
            
            elif category == "reminder":
                embed = discord.Embed(
                    title="⏰ Reminder System Help",
                    description="Commands for setting reminders",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/reminder create", value="Create a personal reminder", inline=False)
                embed.add_field(name="/reminder channel", value="Create a channel reminder", inline=False)
                embed.add_field(name="/reminder list", value="List your reminders", inline=False)
                embed.add_field(name="/reminder delete", value="Delete a reminder", inline=False)
                embed.add_field(name="/reminder setup", value="Set up the reminder system", inline=False)
            
            elif category == "meeting":
                embed = discord.Embed(
                    title="📅 Meeting System Help",
                    description="Commands for scheduling meetings",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/meeting create", value="Create a new meeting", inline=False)
                embed.add_field(name="/meeting join", value="Join a meeting", inline=False)
                embed.add_field(name="/meeting list", value="List upcoming meetings", inline=False)
                embed.add_field(name="/meeting setup", value="Set up the meeting system", inline=False)
            
            elif category == "notification":
                embed = discord.Embed(
                    title="🔔 Notification System Help",
                    description="Commands for keyword notifications",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/notification add", value="Add a keyword to monitor", inline=False)
                embed.add_field(name="/notification remove", value="Remove a monitored keyword", inline=False)
                embed.add_field(name="/notification list", value="List your monitored keywords", inline=False)
            
            elif category == "role":
                embed = discord.Embed(
                    title="👥 Role Management Help",
                    description="Commands for managing roles",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/role assign", value="Assign a role to a user", inline=False)
                embed.add_field(name="/role remove", value="Remove a role from a user", inline=False)
                embed.add_field(name="/role info", value="Get information about a role", inline=False)
            
            elif category == "user":
                embed = discord.Embed(
                    title="👤 User Management Help",
                    description="Commands for user information",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/user permissions", value="Check user permissions", inline=False)
                embed.add_field(name="/user info", value="Get information about a user", inline=False)
            
            elif category == "conversation":
                embed = discord.Embed(
                    title="🗨️ Conversation Management Help",
                    description="Commands for managing conversations",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/conversation thread", value="Create a thread from a message", inline=False)
                embed.add_field(name="/conversation rename", value="Rename a thread", inline=False)
                embed.add_field(name="/conversation archive", value="Archive a thread", inline=False)
                embed.add_field(name="/conversation search", value="Search messages", inline=False)
                embed.add_field(name="/conversation pin", value="Pin a message", inline=False)
                embed.add_field(name="/conversation unpin", value="Unpin a message", inline=False)
                embed.add_field(name="/conversation setup", value="Set up conversation management", inline=False)
            
            elif category == "ai":
                embed = discord.Embed(
                    title="🤖 AI Features Help",
                    description="AI-powered commands",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/ai summarize", value="Summarize recent messages", inline=False)
                embed.add_field(name="/ai translate", value="Translate text", inline=False)
                embed.add_field(name="/ai ask", value="Ask a question to the AI", inline=False)
                embed.add_field(name="/ai analyze", value="Analyze conversation patterns", inline=False)
            
            elif category == "workflow":
                embed = discord.Embed(
                    title="⚙️ Workflow Automation Help",
                    description="Commands for automating tasks",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/workflow create", value="Create a new workflow", inline=False)
                embed.add_field(name="/workflow list", value="List workflows", inline=False)
                embed.add_field(name="/workflow toggle", value="Enable or disable a workflow", inline=False)
            
            elif category == "integration":
                embed = discord.Embed(
                    title="🔗 Integration Help",
                    description="Commands for external integrations",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/integration google-connect", value="Connect to Google", inline=False)
                embed.add_field(name="/integration google-events", value="Fetch Google Calendar events", inline=False)
                embed.add_field(name="/integration notion-connect", value="Connect to Notion", inline=False)
                embed.add_field(name="/integration notion-pages", value="List Notion pages", inline=False)
                embed.add_field(name="/integration trello-connect", value="Connect to Trello", inline=False)
                embed.add_field(name="/integration trello-boards", value="List Trello boards", inline=False)
            
            elif category == "admin":
                embed = discord.Embed(
                    title="🛡️ Admin Commands Help",
                    description="Commands for server administration",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/admin role-add", value="Add an admin role", inline=False)
                embed.add_field(name="/admin role-remove", value="Remove an admin role", inline=False)
                embed.add_field(name="/admin role-list", value="List admin roles", inline=False)
                embed.add_field(name="/admin panel", value="Open admin panel", inline=False)
                embed.add_field(name="/admin export", value="Export user data", inline=False)
            
            elif category == "log":
                embed = discord.Embed(
                    title="📊 Logging System Help",
                    description="Commands for logging",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/log setup", value="Set up logging", inline=False)
                embed.add_field(name="/log export", value="Export logs", inline=False)
                embed.add_field(name="/log delete", value="Delete logs", inline=False)
            
            elif category == "privacy":
                embed = discord.Embed(
                    title="🔒 Privacy & Data Help",
                    description="Commands for managing your data",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="/privacy export", value="Export your data", inline=False)
                embed.add_field(name="/privacy delete", value="Delete your data", inline=False)
                embed.add_field(name="/privacy summary", value="Get a summary of your data", inline=False)
                embed.add_field(name="/privacy policy", value="View the privacy policy", inline=False)
                embed.add_field(name="/privacy terms", value="View the terms of service", inline=False)
            
            else:
                embed = discord.Embed(
                    title="Help",
                    description=f"Unknown category: {category}",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(
                    name="Available Categories",
                    value=(
                        "ticket, github, reminder, meeting, notification, role, user, "
                        "conversation, ai, workflow, integration, admin, log, privacy"
                    ),
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            logger.error(f"Error in help_command: {e}")
            traceback.print_exc()

# Run the bot
bot = DevBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"This command is on cooldown. Try again in {error.retry_after:.2f} seconds.",
            ephemeral=True
        )
    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You don't have permission to use this command.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"An error occurred: {str(error)}",
            ephemeral=True
        )
        logger.error(f"Command error: {error}")
        traceback.print_exc()

if __name__ == "__main__":
    bot.run(TOKEN)
