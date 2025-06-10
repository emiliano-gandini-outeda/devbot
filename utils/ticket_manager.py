"""
EMERGENCY FIX: Ticket Manager with corrected datetime handling
"""

import discord
from discord.ext import commands
import uuid
from datetime import datetime, timezone, timedelta
import json
from typing import Optional, Dict, Any
import asyncio
import random
import string
import io
import logging
from utils.datetime_utils import (
    utc_now, ensure_timezone_aware, format_for_database, 
    format_for_discord, safe_datetime_subtract
)

logger = logging.getLogger(__name__)

class TicketJoinRequestView(discord.ui.View):
    def __init__(self, bot, requesting_user: discord.Member, ticket_channel: discord.TextChannel):
        super().__init__(timeout=300)
        self.bot = bot
        self.requesting_user = requesting_user
        self.ticket_channel = ticket_channel
    
    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success)
    async def accept_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user can accept (must be assignee or admin, not the requester)
        if interaction.user.id == self.requesting_user.id:
            await interaction.response.send_message("You cannot accept your own join request!", ephemeral=True)
            return
        
        # Get ticket info to check if user is assignee
        ticket_id = self.ticket_channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        
        if self.bot.db.is_postgresql:
            ticket = await self.bot.db.connection.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
            )
            ticket = await cursor.fetchone()
        
        if not ticket:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return
        
        # Check if user is admin or assignee
        is_admin = self.bot.admin_manager.is_admin(interaction.user) if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager else False
        assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[4]
        user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[3]
        is_assignee = str(interaction.user.id) == assignee_id
        is_creator = str(interaction.user.id) == user_id
        
        if not (is_admin or is_assignee or is_creator):
            await interaction.response.send_message("Only ticket assignees, creators, or admins can accept join requests!", ephemeral=True)
            return
        
        try:
            # Grant permissions to the requesting user
            await self.ticket_channel.set_permissions(
                self.requesting_user, 
                read_messages=True, 
                send_messages=True
            )
            
            # Update the embed to show accepted with timezone-aware datetime
            current_time = utc_now()
            embed = discord.Embed(
                title="✅ Join Request Accepted",
                description=f"{self.requesting_user.mention} has been granted access to this ticket",
                color=0x57F287,
                timestamp=current_time
            )
            embed.add_field(name="Accepted by", value=interaction.user.mention, inline=True)
            embed.add_field(name="Time", value=format_for_discord(current_time), inline=True)
            
            # Disable all buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
            # Send notification to the requesting user
            try:
                dm_embed = discord.Embed(
                    title="🎫 Ticket Access Granted",
                    description=f"Your request to join ticket {ticket_id} has been accepted!",
                    color=0x57F287,
                    timestamp=current_time
                )
                dm_embed.add_field(name="Ticket", value=self.ticket_channel.mention, inline=True)
                dm_embed.add_field(name="Accepted by", value=interaction.user.mention, inline=True)
                
                await self.requesting_user.send(embed=dm_embed)
            except:
                # If DM fails, send in channel
                await self.ticket_channel.send(f"{self.requesting_user.mention} Your join request has been accepted!")
            
        except Exception as e:
            logger.error(f"Failed to grant access: {e}")
            await interaction.response.send_message(f"Failed to grant access: {str(e)}", ephemeral=True)
    
    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger)
    async def deny_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user can deny (must be assignee or admin, not the requester)
        if interaction.user.id == self.requesting_user.id:
            await interaction.response.send_message("You cannot deny your own join request!", ephemeral=True)
            return
        
        # Get ticket info to check if user is assignee
        ticket_id = self.ticket_channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        
        if self.bot.db.is_postgresql:
            ticket = await self.bot.db.connection.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
            )
            ticket = await cursor.fetchone()
        
        if not ticket:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return
        
        # Check if user is admin or assignee
        is_admin = self.bot.admin_manager.is_admin(interaction.user) if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager else False
        assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[4]
        user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[3]
        is_assignee = str(interaction.user.id) == assignee_id
        is_creator = str(interaction.user.id) == user_id
        
        if not (is_admin or is_assignee or is_creator):
            await interaction.response.send_message("Only ticket assignees, creators, or admins can deny join requests!", ephemeral=True)
            return
        
        # Update the embed to show denied with timezone-aware datetime
        current_time = utc_now()
        embed = discord.Embed(
            title="❌ Join Request Denied",
            description=f"{self.requesting_user.mention}'s request to join this ticket has been denied",
            color=0xED4245,
            timestamp=current_time
        )
        embed.add_field(name="Denied by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=format_for_discord(current_time), inline=True)
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Send notification to the requesting user
        try:
            dm_embed = discord.Embed(
                title="🎫 Ticket Access Denied",
                description=f"Your request to join ticket {ticket_id} has been denied.",
                color=0xED4245,
                timestamp=current_time
            )
            dm_embed.add_field(name="Denied by", value=interaction.user.mention, inline=True)
            
            await self.requesting_user.send(embed=dm_embed)
        except:
            # If DM fails, don't send in channel for privacy
            pass

class TicketManager:
    def __init__(self, bot):
        self.bot = bot
        self.ticket_configs = {}  # guild_id -> config
    
    def generate_ticket_id(self) -> str:
        """Generate a unique ticket ID"""
        return f"TKT-{uuid.uuid4().hex[:8].upper()}"
    
    async def load_ticket_configs(self):
        """Load ticket configurations from database"""
        try:
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT * FROM ticket_configs"
                )
                for row in rows:
                    guild_id = row['guild_id']
                    config = {
                        'category_id': row['category_id'],
                        'support_role_id': row['support_role_id'],
                        'log_channel_id': row['log_channel_id'],
                        'auto_close_hours': row['auto_close_hours'],
                        'max_tickets_per_user': row['max_tickets_per_user']
                    }
                    self.ticket_configs[guild_id] = config
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM ticket_configs"
                )
                rows = await cursor.fetchall()
                for row in rows:
                    guild_id = row[1]  # guild_id column
                    config = {
                        'category_id': row[2],
                        'support_role_id': row[3],
                        'log_channel_id': row[4],
                        'auto_close_hours': row[5],
                        'max_tickets_per_user': row[6]
                    }
                    self.ticket_configs[guild_id] = config
        except Exception as e:
            logger.error(f"Error loading ticket configs: {e}")
    
    async def save_ticket_config(self, guild_id: str, config: Dict[str, Any]):
        """Save ticket configuration to database with timezone-aware datetime"""
        try:
            self.ticket_configs[guild_id] = config
            current_time = utc_now()
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO ticket_configs (guild_id, category_id, support_role_id, log_channel_id, auto_close_hours, max_tickets_per_user, updated_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)
                       ON CONFLICT (guild_id) DO UPDATE SET
                       category_id = $2, support_role_id = $3, log_channel_id = $4, 
                       auto_close_hours = $5, max_tickets_per_user = $6, updated_at = $7""",
                    guild_id, config.get('category_id'), config.get('support_role_id'),
                    config.get('log_channel_id'), config.get('auto_close_hours', 72),
                    config.get('max_tickets_per_user', 3), current_time
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO ticket_configs (guild_id, category_id, support_role_id, log_channel_id, auto_close_hours, max_tickets_per_user, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (guild_id, config.get('category_id'), config.get('support_role_id'),
                     config.get('log_channel_id'), config.get('auto_close_hours', 72),
                     config.get('max_tickets_per_user', 3), current_time)
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            logger.error(f"Error saving ticket config: {e}")
    
    async def get_ticket_config(self, guild_id: str) -> Optional[dict]:
        """Get ticket configuration for a guild"""
        try:
            if self.bot.db.is_postgresql:
                row = await self.bot.db.connection.fetchrow(
                    "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                    guild_id, 'ticket_config'
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT data_content FROM user_data WHERE user_id = ? AND data_type = ?",
                    (guild_id, 'ticket_config')
                )
                row = await cursor.fetchone()
        
            if row:
                data_content = row['data_content'] if self.bot.db.is_postgresql else row[0]
                if isinstance(data_content, str):
                    return json.loads(data_content)
                return data_content
            return None
        except Exception as e:
            logger.error(f"Error getting ticket config: {e}")
            return None
    
    async def create_ticket_channel(self, guild: discord.Guild, ticket_id: str, user: discord.Member, title: str) -> Optional[discord.TextChannel]:
        """Create a ticket channel"""
        try:
            # Get ticket config
            config = await self.get_ticket_config(str(guild.id))
            if not config:
                logger.error(f"No ticket config found for guild {guild.id}")
                return None
            
            category_id = config.get('category_id')
            if not category_id:
                logger.error(f"No category_id in ticket config for guild {guild.id}")
                return None
            
            category = guild.get_channel(int(category_id))
            if not category:
                logger.error(f"Category channel {category_id} not found in guild {guild.id}")
                return None
            
            # Create channel
            channel_name = f"ticket-{ticket_id.lower()}"
            
            # Set permissions - PUBLIC AND READ-ONLY BY DEFAULT
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            
            # Add admin roles with write permissions
            if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager:
                admin_role_ids = self.bot.admin_manager.get_admin_roles(str(guild.id))
                for role_id in admin_role_ids:
                    role = guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                topic=f"Support ticket: {ticket_id} | Created by {user.display_name}",
                overwrites=overwrites
            )
            
            return channel
            
        except Exception as e:
            logger.error(f"Error creating ticket channel: {e}")
            return None
    
    async def set_ticket_visibility(self, channel: discord.TextChannel, private: bool = True) -> bool:
        """Set ticket visibility (private or public)"""
        try:
            guild = channel.guild
            
            if private:
                # Private: Only assignees and admins can read
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False)
                }
            else:
                # Public: Everyone can read, but only assignees can write
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False)
                }
            
            # Always allow bot to manage
            overwrites[guild.me] = discord.PermissionOverwrite(
                read_messages=True, 
                send_messages=True, 
                manage_channels=True
            )
            
            # Get ticket info to preserve creator and assignee permissions
            if channel.topic and "Support ticket:" in channel.topic:
                ticket_id = channel.topic.split("|")[0].replace("Support ticket:", "").strip()
                
                if self.bot.db.is_postgresql:
                    ticket = await self.bot.db.connection.fetchrow(
                        "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
                    )
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
                    )
                    ticket = await cursor.fetchone()
                
                if ticket:
                    # Creator permissions
                    user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[3]
                    creator = guild.get_member(int(user_id))
                    if creator:
                        overwrites[creator] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                    
                    # Assignee permissions
                    assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[4]
                    if assignee_id:
                        assignee = guild.get_member(int(assignee_id))
                        if assignee:
                            overwrites[assignee] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            # Admin role permissions
            if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager:
                admin_role_ids = self.bot.admin_manager.get_admin_roles(str(guild.id))
                for role_id in admin_role_ids:
                    role = guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            await channel.edit(overwrites=overwrites)
            return True
            
        except Exception as e:
            logger.error(f"Error setting ticket visibility: {e}")
            return False
    
    async def create_transcript(self, channel: discord.TextChannel) -> str:
        """Create a transcript of the ticket channel"""
        try:
            messages = []
            async for message in channel.history(limit=None, oldest_first=True):
                # Use timezone-aware datetime formatting
                timestamp = ensure_timezone_aware(message.created_at).strftime('%Y-%m-%d %H:%M:%S UTC')
                content = message.content or "[No content]"
                
                if message.attachments:
                    attachments = "\n".join([f"Attachment: {att.filename}" for att in message.attachments])
                    content += f"\n{attachments}"
                
                messages.append(f"[{timestamp}] {message.author}: {content}")
            
            return "\n".join(messages)
            
        except Exception as e:
            logger.error(f"Error creating transcript: {e}")
            return f"Error creating transcript: {str(e)}"
    
    async def send_transcript(self, guild: discord.Guild, transcript: str, ticket_id: str, user: discord.Member) -> bool:
        """Send transcript to the configured channel"""
        try:
            config = await self.get_ticket_config(str(guild.id))
            if not config:
                logger.error(f"No ticket config found for guild {guild.id}")
                return False
            
            transcript_channel_id = config.get('transcript_channel_id')
            if not transcript_channel_id:
                logger.error(f"No transcript_channel_id in config for guild {guild.id}")
                return False
            
            transcript_channel = guild.get_channel(int(transcript_channel_id))
            if not transcript_channel:
                logger.error(f"Transcript channel {transcript_channel_id} not found in guild {guild.id}")
                return False
            
            # Create transcript file
            current_time = utc_now()
            transcript_file = discord.File(
                fp=io.StringIO(transcript),
                filename=f"transcript_{ticket_id}_{current_time.strftime('%Y%m%d_%H%M%S')}.txt"
            )
            
            embed = discord.Embed(
                title=f"🎫 Ticket Transcript: {ticket_id}",
                description=f"Ticket closed by {user.mention}",
                color=0x5865F2,
                timestamp=current_time
            )
            embed.set_footer(text="devBot - Powered by EGOS")
            
            await transcript_channel.send(embed=embed, file=transcript_file)
            logger.info(f"Transcript sent successfully for ticket {ticket_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending transcript: {e}")
            return False
    
    async def save_ticket_to_database(self, ticket_id: str, guild_id: str, user_id: str, title: str, description: str, priority: str, channel_id: str, assignee_id: Optional[str] = None):
        """EMERGENCY FIX: Save ticket to database with correct parameter count"""
        try:
            current_time = utc_now()
            
            # CRITICAL FIX: Ensure all parameters are provided in correct order
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO tickets (ticket_id, guild_id, user_id, assignee_id, title, description, status, priority, channel_id, created_at, updated_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
                    ticket_id,           # $1
                    guild_id,            # $2
                    user_id,             # $3
                    assignee_id,         # $4
                    title,               # $5
                    description,         # $6
                    "open",              # $7
                    priority,            # $8
                    channel_id,          # $9
                    current_time,        # $10 - FIXED: timezone-aware datetime
                    current_time         # $11 - FIXED: timezone-aware datetime
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT INTO tickets (ticket_id, guild_id, user_id, assignee_id, title, description, status, priority, channel_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ticket_id, guild_id, user_id, assignee_id, title, description, 
                     "open", priority, channel_id, current_time, current_time)
                )
                await self.bot.db.connection.commit()
                
            logger.info(f"Ticket {ticket_id} saved to database successfully")
            
        except Exception as e:
            logger.error(f"EMERGENCY: Error saving ticket to database: {e}")
            logger.error(f"Parameters: ticket_id={ticket_id}, guild_id={guild_id}, user_id={user_id}")
            logger.error(f"Title={title}, description={description}, priority={priority}, channel_id={channel_id}")
            logger.error(f"Current time type: {type(current_time)}, tzinfo: {current_time.tzinfo}")
            raise
    
    async def get_ticket_by_id(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket information by ID"""
        try:
            if self.bot.db.is_postgresql:
                ticket = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
                )
                return dict(ticket) if ticket else None
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
                )
                ticket = await cursor.fetchone()
                if ticket:
                    columns = ['id', 'ticket_id', 'guild_id', 'user_id', 'assignee_id', 'title', 'description', 'status', 'priority', 'channel_id', 'created_at', 'updated_at']
                    return dict(zip(columns, ticket))
                return None
        except Exception as e:
            logger.error(f"Error getting ticket by ID: {e}")
            return None
    
    async def update_ticket_status(self, ticket_id: str, status: str):
        """Update ticket status with timezone-aware datetime"""
        try:
            current_time = utc_now()
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET status = $1, updated_at = $2 WHERE ticket_id = $3",
                    status, current_time, ticket_id
                )
            else:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET status = ?, updated_at = ? WHERE ticket_id = ?",
                    (status, current_time, ticket_id)
                )
                await self.bot.db.connection.commit()
                
            logger.info(f"Ticket {ticket_id} status updated to {status}")
            
        except Exception as e:
            logger.error(f"Error updating ticket status: {e}")
            raise
    
    async def assign_ticket(self, ticket_id: str, assignee_id: str):
        """Assign ticket to a user with timezone-aware datetime"""
        try:
            current_time = utc_now()
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET assignee_id = $1, updated_at = $2 WHERE ticket_id = $3",
                    assignee_id, current_time, ticket_id
                )
            else:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET assignee_id = ?, updated_at = ? WHERE ticket_id = ?",
                    (assignee_id, current_time, ticket_id)
                )
                await self.bot.db.connection.commit()
                
            logger.info(f"Ticket {ticket_id} assigned to {assignee_id}")
            
        except Exception as e:
            logger.error(f"Error assigning ticket: {e}")
            raise
    
    async def get_user_tickets(self, guild_id: str, user_id: str, status: Optional[str] = None):
        """Get tickets for a specific user"""
        try:
            if self.bot.db.is_postgresql:
                if status:
                    tickets = await self.bot.db.connection.fetch(
                        "SELECT * FROM tickets WHERE guild_id = $1 AND user_id = $2 AND status = $3 ORDER BY created_at DESC",
                        guild_id, user_id, status
                    )
                else:
                    tickets = await self.bot.db.connection.fetch(
                        "SELECT * FROM tickets WHERE guild_id = $1 AND user_id = $2 ORDER BY created_at DESC",
                        guild_id, user_id
                    )
                return [dict(ticket) for ticket in tickets]
            else:
                if status:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND status = ? ORDER BY created_at DESC",
                        (guild_id, user_id, status)
                    )
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
                        (guild_id, user_id)
                    )
                tickets = await cursor.fetchall()
                columns = ['id', 'ticket_id', 'guild_id', 'user_id', 'assignee_id', 'title', 'description', 'status', 'priority', 'channel_id', 'created_at', 'updated_at']
                return [dict(zip(columns, ticket)) for ticket in tickets]
        except Exception as e:
            logger.error(f"Error getting user tickets: {e}")
            return []
