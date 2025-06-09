import discord
from discord.ext import commands
import json
from datetime import datetime
from typing import Optional, Dict, Any

class LoggingManager:
    def __init__(self, bot):
        self.bot = bot
        self.log_configs = {}  # guild_id -> config
    
    async def load_log_configs(self):
        """Load logging configurations from database"""
        try:
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT user_id, data_content FROM user_data WHERE data_type = 'log_config'"
                )
                for row in rows:
                    guild_id = row['user_id']
                    config = row['data_content']
                    self.log_configs[guild_id] = config
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT user_id, data_content FROM user_data WHERE data_type = 'log_config'"
                )
                rows = await cursor.fetchall()
                for row in rows:
                    guild_id = row[0]
                    config = json.loads(row[2])
                    self.log_configs[guild_id] = config
        except Exception as e:
            print(f"Error loading log configs: {e}")
    
    async def save_log_config(self, guild_id: str, config: Dict[str, Any]):
        """Save logging configuration to database"""
        try:
            self.log_configs[guild_id] = config
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO user_data (user_id, data_type, data_content) 
                       VALUES ($1, $2, $3) 
                       ON CONFLICT (user_id, data_type) DO UPDATE SET data_content = $3""",
                    guild_id, 'log_config', json.dumps(config)
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO user_data (user_id, data_type, data_content) 
                       VALUES (?, ?, ?)""",
                    (guild_id, 'log_config', json.dumps(config))
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error saving log config: {e}")
    
    def get_log_config(self, guild_id: str) -> Optional[Dict[str, Any]]:
        """Get logging configuration for guild"""
        return self.log_configs.get(guild_id)
    
    async def log_event(self, guild: discord.Guild, embed: discord.Embed):
        """Send log event to configured log channel"""
        config = self.get_log_config(str(guild.id))
        if not config or 'log_channel_id' not in config:
            return
        
        try:
            log_channel = guild.get_channel(int(config['log_channel_id']))
            if log_channel:
                await log_channel.send(embed=embed)
        except Exception as e:
            print(f"Error sending log: {e}")
    
    async def log_message_delete(self, message: discord.Message):
        """Log message deletion"""
        if not message.guild or message.author.bot:
            return
        
        embed = discord.Embed(
            title="🗑️ Message Deleted",
            color=0xED4245,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Author", value=f"{message.author.mention} ({message.author})", inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Message ID", value=message.id, inline=True)
        
        if message.content:
            content = message.content[:1000] + "..." if len(message.content) > 1000 else message.content
            embed.add_field(name="Content", value=f"```{content}```", inline=False)
        
        if message.attachments:
            attachments = "\n".join([f"• {att.filename}" for att in message.attachments])
            embed.add_field(name="Attachments", value=attachments, inline=False)
        
        await self.log_event(message.guild, embed)
    
    async def log_message_edit(self, before: discord.Message, after: discord.Message):
        """Log message edit"""
        if not before.guild or before.author.bot or before.content == after.content:
            return
        
        embed = discord.Embed(
            title="✏️ Message Edited",
            color=0xFEE75C,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Author", value=f"{before.author.mention} ({before.author})", inline=True)
        embed.add_field(name="Channel", value=before.channel.mention, inline=True)
        embed.add_field(name="Jump to Message", value=f"[Click here]({after.jump_url})", inline=True)
        
        if before.content:
            before_content = before.content[:500] + "..." if len(before.content) > 500 else before.content
            embed.add_field(name="Before", value=f"```{before_content}```", inline=False)
        
        if after.content:
            after_content = after.content[:500] + "..." if len(after.content) > 500 else after.content
            embed.add_field(name="After", value=f"```{after_content}```", inline=False)
        
        await self.log_event(before.guild, embed)
    
    async def log_channel_create(self, channel):
        """Log channel creation"""
        if not hasattr(channel, 'guild') or not channel.guild:
            return
        
        embed = discord.Embed(
            title="📝 Channel Created",
            color=0x57F287,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Channel", value=f"{channel.mention} ({channel.name})", inline=True)
        embed.add_field(name="Type", value=str(channel.type).title(), inline=True)
        embed.add_field(name="ID", value=channel.id, inline=True)
        
        if hasattr(channel, 'category') and channel.category:
            embed.add_field(name="Category", value=channel.category.name, inline=True)
        
        await self.log_event(channel.guild, embed)
    
    async def log_channel_delete(self, channel):
        """Log channel deletion"""
        if not hasattr(channel, 'guild') or not channel.guild:
            return
        
        embed = discord.Embed(
            title="🗑️ Channel Deleted",
            color=0xED4245,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Type", value=str(channel.type).title(), inline=True)
        embed.add_field(name="ID", value=channel.id, inline=True)
        
        if hasattr(channel, 'category') and channel.category:
            embed.add_field(name="Category", value=channel.category.name, inline=True)
        
        await self.log_event(channel.guild, embed)
    
    async def log_channel_update(self, before, after):
        """Log channel updates"""
        if not before.guild:
            return
        
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if hasattr(before, 'topic') and before.topic != after.topic:
            changes.append(f"**Topic:** {before.topic or 'None'} → {after.topic or 'None'}")
        
        if not changes:
            return
        
        embed = discord.Embed(
            title="✏️ Channel Updated",
            color=0xFEE75C,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Channel", value=after.mention, inline=True)
        embed.add_field(name="Changes", value="\n".join(changes), inline=False)
        
        await self.log_event(before.guild, embed)
    
    async def log_role_create(self, role: discord.Role):
        """Log role creation"""
        embed = discord.Embed(
            title="👑 Role Created",
            color=0x57F287,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Role", value=f"{role.mention} ({role.name})", inline=True)
        embed.add_field(name="ID", value=role.id, inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="Mentionable", value=role.mentionable, inline=True)
        embed.add_field(name="Hoisted", value=role.hoist, inline=True)
        
        await self.log_event(role.guild, embed)
    
    async def log_role_delete(self, role: discord.Role):
        """Log role deletion"""
        embed = discord.Embed(
            title="🗑️ Role Deleted",
            color=0xED4245,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Role", value=role.name, inline=True)
        embed.add_field(name="ID", value=role.id, inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        
        await self.log_event(role.guild, embed)
    
    async def log_member_role_update(self, before: discord.Member, after: discord.Member):
        """Log role assignments/removals"""
        added_roles = set(after.roles) - set(before.roles)
        removed_roles = set(before.roles) - set(after.roles)
        
        if added_roles:
            embed = discord.Embed(
                title="➕ Role Added",
                color=0x57F287,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{after.mention} ({after})", inline=True)
            embed.add_field(name="Roles Added", value="\n".join([role.mention for role in added_roles]), inline=False)
            await self.log_event(after.guild, embed)
        
        if removed_roles:
            embed = discord.Embed(
                title="➖ Role Removed",
                color=0xED4245,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{after.mention} ({after})", inline=True)
            embed.add_field(name="Roles Removed", value="\n".join([role.name for role in removed_roles]), inline=False)
            await self.log_event(after.guild, embed)
    
    async def log_command_use(self, interaction: discord.Interaction):
        """Log command usage"""
        if not interaction.guild:
            return
        
        embed = discord.Embed(
            title="⚡ Command Used",
            color=0x5865F2,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{interaction.user.mention} ({interaction.user})", inline=True)
        embed.add_field(name="Command", value=f"/{interaction.command.name}", inline=True)
        embed.add_field(name="Channel", value=interaction.channel.mention, inline=True)
        
        # Add command parameters if any
        if hasattr(interaction, 'data') and 'options' in interaction.data:
            options = []
            for option in interaction.data['options']:
                options.append(f"{option['name']}: {option.get('value', 'N/A')}")
            if options:
                embed.add_field(name="Parameters", value="\n".join(options), inline=False)
        
        await self.log_event(interaction.guild, embed)
