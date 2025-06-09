import discord
from discord.ext import commands
import json
from datetime import datetime
from typing import Optional, Dict, Any, List

class WorkflowManager:
    def __init__(self, bot):
        self.bot = bot
    
    async def execute_workflow_actions(self, workflow: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Execute all actions in a workflow"""
        try:
            actions = workflow.get('actions', [])
            if isinstance(actions, str):
                actions = json.loads(actions)
            
            guild = self.bot.get_guild(int(workflow['guild_id']))
            if not guild:
                return
            
            # Log workflow execution if log channel is configured
            log_channel_id = workflow.get('log_channel_id')
            if log_channel_id:
                await self.log_workflow_execution(guild, workflow, trigger_data, log_channel_id)
            
            for action in actions:
                await self.execute_single_action(guild, action, trigger_data)
                
        except Exception as e:
            print(f"Error executing workflow: {e}")
    
    async def execute_single_action(self, guild: discord.Guild, action: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Execute a single workflow action"""
        try:
            action_type = action.get('type')
            action_data = action.get('data', {})
            
            if action_type == 'send_message':
                await self.action_send_message(guild, action_data, trigger_data)
            elif action_type == 'add_role':
                await self.action_add_role(guild, action_data, trigger_data)
            elif action_type == 'create_channel':
                await self.action_create_channel(guild, action_data, trigger_data)
            elif action_type == 'send_dm':
                await self.action_send_dm(guild, action_data, trigger_data)
                
        except Exception as e:
            print(f"Error executing action {action.get('type')}: {e}")
    
    async def action_send_message(self, guild: discord.Guild, action_data: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Send message action"""
        channel_id = action_data.get('channel_id')
        message = action_data.get('message', '')
        
        # Replace placeholders
        message = message.replace('{user}', trigger_data.get('user_mention', ''))
        message = message.replace('{channel}', trigger_data.get('channel_mention', ''))
        
        if channel_id == 'same':
            channel = guild.get_channel(int(trigger_data.get('channel_id', 0)))
        else:
            channel = guild.get_channel(int(channel_id))
        
        if channel:
            await channel.send(message)
    
    async def action_add_role(self, guild: discord.Guild, action_data: Dict[str, Any], trigger_data: Dict[str, Any]):
        """Add role action"""
        role_id = action_data.get('role_id')
        user_id = trigger_data.get('user_id')
        
        if role_id and user_id:
            role = guild.get_role(int(role_id))
            member = guild.get_member(int(user_id))
            
            if role and member:
                await member.add_roles(role)
    
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
        
        if channel_type == 'text':
            await guild.create_text_channel(name=channel_name, category=category)
        elif channel_type == 'voice':
            await guild.create_voice_channel(name=channel_name, category=category)
    
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
    
    async def log_workflow_execution(self, guild: discord.Guild, workflow: Dict[str, Any], trigger_data: Dict[str, Any], log_channel_id: str):
        """Log workflow execution"""
        try:
            log_channel = guild.get_channel(int(log_channel_id))
            if not log_channel:
                return
            
            embed = discord.Embed(
                title="⚙️ Workflow Executed",
                color=0x5865F2,
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Workflow", value=workflow.get('name', 'Unknown'), inline=True)
            embed.add_field(name="Trigger", value=workflow.get('trigger_type', 'Unknown'), inline=True)
            
            if 'user_mention' in trigger_data:
                embed.add_field(name="Triggered by", value=trigger_data['user_mention'], inline=True)
            
            if 'message_link' in trigger_data:
                embed.add_field(name="Message", value=f"[Jump to message]({trigger_data['message_link']})", inline=False)
            
            await log_channel.send(embed=embed)
            
        except Exception as e:
            print(f"Error logging workflow execution: {e}")
    
    async def check_message_triggers(self, message: discord.Message):
        """Check if message triggers any workflows"""
        if not message.guild or message.author.bot:
            return
        
        try:
            # Get workflows for this guild
            if self.bot.db.is_postgresql:
                workflows = await self.bot.db.connection.fetch(
                    "SELECT * FROM workflows WHERE guild_id = $1 AND status = 'active' AND trigger_type = 'message'",
                    str(message.guild.id)
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM workflows WHERE guild_id = ? AND status = 'active' AND trigger_type = 'message'",
                    (str(message.guild.id),)
                )
                workflows = await cursor.fetchall()
            
            for workflow in workflows:
                # Check if workflow conditions are met
                trigger_data_raw = workflow['trigger_data'] if self.bot.db.is_postgresql else workflow[5]
                if isinstance(trigger_data_raw, str):
                    trigger_conditions = json.loads(trigger_data_raw)
                else:
                    trigger_conditions = trigger_data_raw
                
                # Check channel condition
                if 'channel_id' in trigger_conditions:
                    if str(message.channel.id) != trigger_conditions['channel_id']:
                        continue
                
                # Check message count condition
                if 'message_count' in trigger_conditions:
                    # Count recent messages from this user
                    count = 0
                    async for msg in message.channel.history(limit=100):
                        if msg.author == message.author:
                            count += 1
                        if count >= trigger_conditions['message_count']:
                            break
                    
                    if count < trigger_conditions['message_count']:
                        continue
                
                # Execute workflow
                trigger_data = {
                    'user_id': str(message.author.id),
                    'user_name': message.author.display_name,
                    'user_mention': message.author.mention,
                    'channel_id': str(message.channel.id),
                    'channel_mention': message.channel.mention,
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
                    'status': workflow[7],
                    'log_channel_id': trigger_conditions.get('log_channel_id')
                }
                
                await self.execute_workflow_actions(workflow_dict, trigger_data)
                
        except Exception as e:
            print(f"Error checking message triggers: {e}")
    
    async def check_member_join_triggers(self, member: discord.Member):
        """Check if member join triggers any workflows"""
        try:
            # Get workflows for this guild
            if self.bot.db.is_postgresql:
                workflows = await self.bot.db.connection.fetch(
                    "SELECT * FROM workflows WHERE guild_id = $1 AND status = 'active' AND trigger_type = 'member_join'",
                    str(member.guild.id)
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM workflows WHERE guild_id = ? AND status = 'active' AND trigger_type = 'member_join'",
                    (str(member.guild.id),)
                )
                workflows = await cursor.fetchall()
            
            for workflow in workflows:
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
                
                await self.execute_workflow_actions(workflow_dict, trigger_data)
                
        except Exception as e:
            print(f"Error checking member join triggers: {e}")
    
    async def check_thread_create_triggers(self, thread: discord.Thread):
        """Check if thread creation triggers any workflows"""
        try:
            # Get workflows for this guild
            if self.bot.db.is_postgresql:
                workflows = await self.bot.db.connection.fetch(
                    "SELECT * FROM workflows WHERE guild_id = $1 AND status = 'active' AND trigger_type = 'thread_create'",
                    str(thread.guild.id)
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM workflows WHERE guild_id = ? AND status = 'active' AND trigger_type = 'thread_create'",
                    (str(thread.guild.id),)
                )
                workflows = await cursor.fetchall()
            
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
                
                await self.execute_workflow_actions(workflow_dict, trigger_data)
                
        except Exception as e:
            print(f"Error checking thread create triggers: {e}")
