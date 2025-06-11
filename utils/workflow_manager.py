import discord
from discord.ext import commands
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import asyncio
from collections import deque

class WorkflowManager:
    def __init__(self, bot):
        self.bot = bot
        self._processing_workflows = set()
        self._workflow_semaphore = asyncio.Semaphore(3)  # Limit concurrent workflows
    
    async def load_workflows(self):
        """Load workflows from database on startup"""
        try:
            async def fetch_workflows():
                if self.bot.db.is_postgresql:
                    return await self.bot.db.connection.fetch(
                        "SELECT * FROM workflows WHERE status = 'active'"
                    )
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT * FROM workflows WHERE status = 'active'"
                    )
                    return await cursor.fetchall()
            
            workflows = await self.bot.execute_db_operation(fetch_workflows)
            print(f"Loaded {len(workflows)} active workflows from database")
            
        except Exception as e:
            print(f"Error loading workflows: {e}")
    
    async def execute_workflow_actions(self, workflow: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Execute all actions in a workflow"""
        workflow_key = f"{workflow['guild_id']}:{workflow['id']}"
        
        # Prevent duplicate execution of the same workflow
        if workflow_key in self._processing_workflows:
            return
        
        self._processing_workflows.add(workflow_key)
        
        try:
            async with self._workflow_semaphore:
                actions = workflow.get('actions', [])
                if isinstance(actions, str):
                    actions = json.loads(actions)
                
                guild = self.bot.get_guild(int(workflow['guild_id']))
                if not guild:
                    return
                
                # Log workflow execution if log channel is configured
                trigger_data_raw = workflow.get('trigger_data', {})
                if isinstance(trigger_data_raw, str):
                    trigger_conditions = json.loads(trigger_data_raw)
                else:
                    trigger_conditions = trigger_data_raw or {}
                
                log_channel_id = trigger_conditions.get('log_channel_id')
                if log_channel_id:
                    await self.log_workflow_execution(guild, workflow, trigger_data, log_channel_id)
                
                # Execute actions sequentially to prevent conflicts
                for i, action in enumerate(actions):
                    await self.execute_single_action(guild, action, trigger_data)
                    # Progressive delay between actions
                    if i < len(actions) - 1:
                        await asyncio.sleep(0.2 + (i * 0.1))
                    
        except Exception as e:
            print(f"Error executing workflow: {e}")
        finally:
            self._processing_workflows.discard(workflow_key)
    
    async def execute_single_action(self, guild: discord.Guild, action: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Execute a single workflow action"""
        try:
            action_type = action.get('type')
            action_data = action.get('data', {})
            
            if action_type == 'send_message':
                await self.action_send_message(guild, action_data, trigger_data)
            elif action_type == 'send_embed':
                await self.action_send_embed(guild, action_data, trigger_data)
            elif action_type == 'delete_message':
                await self.action_delete_message(guild, action_data, trigger_data)
            elif action_type == 'timeout_user':
                await self.action_timeout_user(guild, action_data, trigger_data)
            elif action_type == 'add_role':
                await self.action_add_role(guild, action_data, trigger_data)
            elif action_type == 'create_channel':
                await self.action_create_channel(guild, action_data, trigger_data)
            elif action_type == 'send_dm':
                await self.action_send_dm(guild, action_data, trigger_data)
                
        except Exception as e:
            print(f"Error executing action {action.get('type')}: {e}")
    
    async def action_send_message(self, guild: discord.Guild, action_data: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Send message action with ping support"""
        channel_id = action_data.get('channel_id')
        message = action_data.get('message', '')
        ping = action_data.get('ping')
        
        # Replace placeholders
        message = message.replace('{user}', trigger_data.get('user_mention', ''))
        message = message.replace('{channel}', trigger_data.get('channel_mention', ''))
        
        # Get target channel
        if channel_id == 'same':
            channel = guild.get_channel(int(trigger_data.get('channel_id', 0)))
        else:
            channel = guild.get_channel(int(channel_id))
        
        if not channel:
            return
        
        # Add ping if specified
        final_message = message
        if ping:
            if ping == '@everyone':
                final_message = f"@everyone\n{message}"
            elif ping == '@here':
                final_message = f"@here\n{message}"
            elif ping.isdigit():
                # Role ID
                role = guild.get_role(int(ping))
                if role:
                    final_message = f"{role.mention}\n{message}"
        
        await channel.send(final_message)
    
    async def action_send_embed(self, guild: discord.Guild, action_data: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Send embed action"""
        channel_id = action_data.get('channel_id')
        title = action_data.get('title', '')
        description = action_data.get('description', '')
        fields = action_data.get('fields', [])
        
        # Replace placeholders in title and description
        title = title.replace('{user}', trigger_data.get('user_name', ''))
        title = title.replace('{channel}', trigger_data.get('channel_name', ''))
        description = description.replace('{user}', trigger_data.get('user_mention', ''))
        description = description.replace('{channel}', trigger_data.get('channel_mention', ''))
        
        # Get target channel
        if channel_id == 'same':
            channel = guild.get_channel(int(trigger_data.get('channel_id', 0)))
        else:
            channel = guild.get_channel(int(channel_id))
        
        if not channel:
            return
        
        # Create embed
        embed = discord.Embed(
            title=title,
            description=description,
            color=0x5865F2,
            timestamp=datetime.utcnow()
        )
        
        # Add fields (max 3)
        for field in fields[:3]:
            name = field.get('name', '').replace('{user}', trigger_data.get('user_name', ''))
            value = field.get('value', '').replace('{user}', trigger_data.get('user_mention', ''))
            inline = field.get('inline', False)
            
            if name and value:
                embed.add_field(name=name, value=value, inline=inline)
        
        embed.set_footer(text="Workflow Action")
        await channel.send(embed=embed)
    
    async def action_delete_message(self, guild: discord.Guild, action_data: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Delete the message that triggered the workflow"""
        message_id = trigger_data.get('message_id')
        channel_id = trigger_data.get('channel_id')
        
        if not message_id or not channel_id:
            return
        
        channel = guild.get_channel(int(channel_id))
        if not channel:
            return
        
        try:
            message = await channel.fetch_message(int(message_id))
            await message.delete()
        except discord.NotFound:
            pass  # Message already deleted
        except discord.Forbidden:
            print(f"No permission to delete message in {channel.name}")
        except Exception as e:
            print(f"Error deleting message: {e}")
    
    async def action_timeout_user(self, guild: discord.Guild, action_data: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Timeout the user who triggered the workflow"""
        user_id = trigger_data.get('user_id')
        duration = action_data.get('duration', 300)  # Default 5 minutes
        
        if not user_id:
            return
        
        member = guild.get_member(int(user_id))
        if not member:
            return
        
        # Don't timeout bots, admins, or members with manage_messages permission
        if member.bot or member.guild_permissions.administrator or member.guild_permissions.manage_messages:
            return
        
        try:
            timeout_until = datetime.utcnow() + timedelta(seconds=duration)
            await member.timeout(timeout_until, reason="Workflow action triggered")
        except discord.Forbidden:
            print(f"No permission to timeout {member.display_name}")
        except Exception as e:
            print(f"Error timing out user: {e}")
    
    async def action_add_role(self, guild: discord.Guild, action_data: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Add role action"""
        role_id = action_data.get('role_id')
        user_id = trigger_data.get('user_id')
        
        if role_id and user_id:
            role = guild.get_role(int(role_id))
            member = guild.get_member(int(user_id))
            
            if role and member:
                try:
                    await member.add_roles(role)
                except discord.Forbidden:
                    print(f"No permission to add role {role.name}")
                except Exception as e:
                    print(f"Error adding role: {e}")
    
    async def action_create_channel(self, guild: discord.Guild, action_data: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Create channel action"""
        channel_name = action_data.get('name', 'new-channel')
        channel_type = action_data.get('type', 'text')
        category_id = action_data.get('category_id')
        
        # Replace placeholders
        channel_name = channel_name.replace('{user}', trigger_data.get('user_name', ''))
        
        category = None
        if category_id:
            category = guild.get_channel(int(category_id))
        
        try:
            if channel_type == 'text':
                await guild.create_text_channel(name=channel_name, category=category)
            elif channel_type == 'voice':
                await guild.create_voice_channel(name=channel_name, category=category)
        except discord.Forbidden:
            print(f"No permission to create channel")
        except Exception as e:
            print(f"Error creating channel: {e}")
    
    async def action_send_dm(self, guild: discord.Guild, action_data: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Send DM action"""
        user_id = trigger_data.get('user_id')
        message = action_data.get('message', '')
        
        if user_id:
            user = guild.get_member(int(user_id))
            if user:
                try:
                    await user.send(message)
                except discord.Forbidden:
                    pass  # User has DMs disabled
                except Exception as e:
                    print(f"Error sending DM: {e}")
    
    async def log_workflow_execution(self, guild: discord.Guild, workflow: Dict[str, Any], trigger_data: Dict[str, Any], log_channel_id: str = None):
        """Log workflow execution"""
        try:
            # If no specific log channel provided, get from workflow config
            if not log_channel_id:
                async def get_config():
                    return await self.bot.db.connection.fetchrow(
                        "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                        str(guild.id), 'workflow_config'
                    )
                
                config_row = await self.bot.execute_db_operation(get_config)
                
                if config_row:
                    config = json.loads(config_row['data_content'])
                    log_channel_id = config.get('workflow_log_channel_id')
        
            if not log_channel_id:
                return  # No log channel configured
        
            log_channel = guild.get_channel(int(log_channel_id))
            if not log_channel:
                return
        
            embed = discord.Embed(
                title="⚙️ Workflow Executed",
                color=0x5865F2,
                timestamp=datetime.utcnow()
            )
        
            embed.add_field(name="Workflow", value=workflow.get('name', 'Unknown'), inline=True)
        
            trigger_type = workflow.get('trigger_type', 'Unknown')
            if trigger_type.startswith('message:'):
                keyword = trigger_type.split(':', 1)[1]
                embed.add_field(name="Trigger", value=f"Message: '{keyword}'", inline=True)
            else:
                embed.add_field(name="Trigger", value=trigger_type, inline=True)
        
            if 'user_mention' in trigger_data:
                embed.add_field(name="Triggered by", value=trigger_data['user_mention'], inline=True)
        
            if 'message_link' in trigger_data:
                embed.add_field(name="Message", value=f"[Jump to message]({trigger_data['message_link']})", inline=False)
        
            # Add action summary
            actions = workflow.get('actions', [])
            if isinstance(actions, str):
                actions = json.loads(actions)
        
            if actions:
                action_summary = []
                for action in actions:
                    action_type = action.get('type', 'unknown').replace('_', ' ').title()
                    action_summary.append(f"• {action_type}")
            
                embed.add_field(
                    name="Actions Executed",
                    value="\n".join(action_summary[:5]),  # Show max 5 actions
                    inline=False
                )
        
            embed.set_footer(text="devBot - Workflow System")
            await log_channel.send(embed=embed)
        
        except Exception as e:
            print(f"Error logging workflow execution: {e}")
    
    async def process_message_triggers(self, message: discord.Message):
        """Check if message triggers any workflows"""
        if not message.guild or message.author.bot:
            return
        
        try:
            # Get workflows using database operation manager
            async def get_workflows():
                if self.bot.db.is_postgresql:
                    return await self.bot.db.connection.fetch(
                        "SELECT * FROM workflows WHERE guild_id = $1 AND status = 'active' AND trigger_type LIKE 'message%'",
                        str(message.guild.id)
                    )
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT * FROM workflows WHERE guild_id = ? AND status = 'active' AND trigger_type LIKE 'message%'",
                        (str(message.guild.id),)
                    )
                    return await cursor.fetchall()
            
            workflows = await self.bot.execute_db_operation(get_workflows)
            
            for workflow in workflows:
                # Check if workflow conditions are met
                trigger_data_raw = workflow['trigger_data'] if self.bot.db.is_postgresql else workflow[5]
                trigger_type = workflow['trigger_type'] if self.bot.db.is_postgresql else workflow[4]
                
                if isinstance(trigger_data_raw, str):
                    trigger_conditions = json.loads(trigger_data_raw)
                else:
                    trigger_conditions = trigger_data_raw or {}
                
                # Check if it's a message trigger with specific text (case insensitive)
                if trigger_type.startswith('message:'):
                    trigger_text = trigger_type.split(':', 1)[1].lower()
                    if trigger_text not in message.content.lower():
                        continue
                
                # Check channel condition
                if 'channel_id' in trigger_conditions:
                    if str(message.channel.id) != trigger_conditions['channel_id']:
                        continue
                
                # Execute workflow
                trigger_data = {
                    'user_id': str(message.author.id),
                    'user_name': message.author.display_name,
                    'user_mention': message.author.mention,
                    'channel_id': str(message.channel.id),
                    'channel_name': message.channel.name,
                    'channel_mention': message.channel.mention,
                    'message_id': str(message.id),
                    'message_link': message.jump_url,
                    'guild_id': str(message.guild.id)
                }
                
                workflow_dict = dict(workflow) if self.bot.db.is_postgresql else {
                    'id': workflow[0],
                    'name': workflow[1],
                    'guild_id': workflow[2],
                    'creator_id': workflow[3],
                    'trigger_type': workflow[4],
                    'trigger_data': workflow[5],
                    'actions': workflow[6],
                    'status': workflow[7]
                }
                
                # Execute workflow asynchronously without blocking
                asyncio.create_task(self.execute_workflow_actions(workflow_dict, trigger_data))
                
        except Exception as e:
            print(f"Error checking message triggers: {e}")
    
    async def process_member_join_triggers(self, member: discord.Member):
        """Check if member join triggers any workflows"""
        try:
            # Get workflows using database operation manager
            async def get_workflows():
                if self.bot.db.is_postgresql:
                    return await self.bot.db.connection.fetch(
                        "SELECT * FROM workflows WHERE guild_id = $1 AND status = 'active' AND trigger_type = 'member_join'",
                        str(member.guild.id)
                    )
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT * FROM workflows WHERE guild_id = ? AND status = 'active' AND trigger_type = 'member_join'",
                        (str(member.guild.id),)
                    )
                    return await cursor.fetchall()
            
            workflows = await self.bot.execute_db_operation(get_workflows)
            
            for workflow in workflows:
                trigger_data_raw = workflow['trigger_data'] if self.bot.db.is_postgresql else workflow[5]
                
                if isinstance(trigger_data_raw, str):
                    trigger_conditions = json.loads(trigger_data_raw)
                else:
                    trigger_conditions = trigger_data_raw or {}
                
                trigger_data = {
                    'user_id': str(member.id),
                    'user_name': member.display_name,
                    'user_mention': member.mention,
                    'guild_id': str(member.guild.id)
                }
                
                workflow_dict = dict(workflow) if self.bot.db.is_postgresql else {
                    'id': workflow[0],
                    'name': workflow[1],
                    'guild_id': workflow[2],
                    'creator_id': workflow[3],
                    'trigger_type': workflow[4],
                    'trigger_data': workflow[5],
                    'actions': workflow[6],
                    'status': workflow[7]
                }
                
                # Execute workflow asynchronously without blocking
                asyncio.create_task(self.execute_workflow_actions(workflow_dict, trigger_data))
                
        except Exception as e:
            print(f"Error checking member join triggers: {e}")
    
    async def process_thread_create_triggers(self, thread: discord.Thread):
        """Check if thread creation triggers any workflows"""
        try:
            # Get workflows using database operation manager
            async def get_workflows():
                if self.bot.db.is_postgresql:
                    return await self.bot.db.connection.fetch(
                        "SELECT * FROM workflows WHERE guild_id = $1 AND status = 'active' AND trigger_type = 'thread_create'",
                        str(thread.guild.id)
                    )
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT * FROM workflows WHERE guild_id = ? AND status = 'active' AND trigger_type = 'thread_create'",
                        (str(thread.guild.id),)
                    )
                    return await cursor.fetchall()
            
            workflows = await self.bot.execute_db_operation(get_workflows)
            
            for workflow in workflows:
                trigger_data = {
                    'thread_id': str(thread.id),
                    'thread_name': thread.name,
                    'thread_mention': thread.mention,
                    'channel_id': str(thread.parent_id),
                    'guild_id': str(thread.guild.id)
                }
                
                if thread.owner:
                    trigger_data.update({
                        'user_id': str(thread.owner.id),
                        'user_name': thread.owner.display_name,
                        'user_mention': thread.owner.mention
                    })
                
                workflow_dict = dict(workflow) if self.bot.db.is_postgresql else {
                    'id': workflow[0],
                    'name': workflow[1],
                    'guild_id': workflow[2],
                    'creator_id': workflow[3],
                    'trigger_type': workflow[4],
                    'trigger_data': workflow[5],
                    'actions': workflow[6],
                    'status': workflow[7]
                }
                
                # Execute workflow asynchronously without blocking
                asyncio.create_task(self.execute_workflow_actions(workflow_dict, trigger_data))
                
        except Exception as e:
            print(f"Error checking thread create triggers: {e}")

    async def process_channel_create_triggers(self, channel: discord.abc.GuildChannel):
        """Check if channel creation triggers any workflows."""
        try:
            # Get workflows using database operation manager
            async def get_workflows():
                if self.bot.db.is_postgresql:
                    return await self.bot.db.connection.fetch(
                        "SELECT * FROM workflows WHERE guild_id = $1 AND status = 'active' AND trigger_type = 'channel_create'",
                        str(channel.guild.id)
                    )
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT * FROM workflows WHERE guild_id = ? AND status = 'active' AND trigger_type = 'channel_create'",
                        (str(channel.guild.id),)
                    )
                    return await cursor.fetchall()
            
            workflows = await self.bot.execute_db_operation(get_workflows)

            for workflow in workflows:
                trigger_data = {
                    'channel_id': str(channel.id),
                    'channel_name': channel.name,
                    'channel_mention': channel.mention,
                    'guild_id': str(channel.guild.id)
                }

                workflow_dict = dict(workflow) if self.bot.db.is_postgresql else {
                    'id': workflow[0],
                    'name': workflow[1],
                    'guild_id': workflow[2],
                    'creator_id': workflow[3],
                    'trigger_type': workflow[4],
                    'trigger_data': workflow[5],
                    'actions': workflow[6],
                    'status': workflow[7]
                }

                # Execute workflow asynchronously without blocking
                asyncio.create_task(self.execute_workflow_actions(workflow_dict, trigger_data))

        except Exception as e:
            print(f"Error checking channel create triggers: {e}")
