"""
Core Ticket Manager - Business logic and database operations
Handles all ticket CRUD operations, permissions, and state management
"""

import discord
from discord.ext import commands
import uuid
import json
import asyncio
import io
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import logging

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
        
        ticket_manager = TicketManager(self.bot)
        ticket = await ticket_manager.get_ticket(ticket_id)
        
        if not ticket:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return
        
        # Check if user is admin or assignee
        if not ticket_manager.can_manage_ticket(interaction.user, ticket):
            await interaction.response.send_message("Only ticket assignees or admins can accept join requests!", ephemeral=True)
            return
        
        try:
            # Grant permissions to the requesting user
            await self.ticket_channel.set_permissions(
                self.requesting_user, 
                read_messages=True, 
                send_messages=True
            )
            
            # Update the embed to show accepted
            embed = discord.Embed(
                title="✅ Join Request Accepted",
                description=f"{self.requesting_user.mention} has been granted access to this ticket",
                color=0x57F287
            )
            embed.add_field(name="Accepted by", value=interaction.user.mention, inline=True)
            embed.add_field(name="Time", value=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), inline=True)
            
            # Disable all buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
            # Send notification to the requesting user
            try:
                dm_embed = discord.Embed(
                    title="🎫 Ticket Access Granted",
                    description=f"Your request to join ticket {ticket_id} has been accepted!",
                    color=0x57F287
                )
                dm_embed.add_field(name="Ticket", value=self.ticket_channel.mention, inline=True)
                dm_embed.add_field(name="Accepted by", value=interaction.user.mention, inline=True)
                
                await self.requesting_user.send(embed=dm_embed)
            except:
                # If DM fails, send in channel
                await self.ticket_channel.send(f"{self.requesting_user.mention} Your join request has been accepted!")
            
        except Exception as e:
            await interaction.response.send_message(f"Failed to grant access: {str(e)}", ephemeral=True)
    
    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger)
    async def deny_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user can deny (must be assignee or admin, not the requester)
        if interaction.user.id == self.requesting_user.id:
            await interaction.response.send_message("You cannot deny your own join request!", ephemeral=True)
            return
        
        # Get ticket info to check if user is assignee
        ticket_id = self.ticket_channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        
        ticket_manager = TicketManager(self.bot)
        ticket = await ticket_manager.get_ticket(ticket_id)
        
        if not ticket:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return
        
        # Check if user is admin or assignee
        if not ticket_manager.can_manage_ticket(interaction.user, ticket):
            await interaction.response.send_message("Only ticket assignees or admins can deny join requests!", ephemeral=True)
            return
        
        # Update the embed to show denied
        embed = discord.Embed(
            title="❌ Join Request Denied",
            description=f"{self.requesting_user.mention}'s request to join this ticket has been denied",
            color=0xED4245
        )
        embed.add_field(name="Denied by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), inline=True)
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Send notification to the requesting user
        try:
            dm_embed = discord.Embed(
                title="🎫 Ticket Access Denied",
                description=f"Your request to join ticket {ticket_id} has been denied.",
                color=0xED4245
            )
            dm_embed.add_field(name="Denied by", value=interaction.user.mention, inline=True)
            
            await self.requesting_user.send(embed=dm_embed)
        except:
            # If DM fails, don't send in channel for privacy
            pass

class RejectReasonModal(discord.ui.Modal):
    def __init__(self, bot, requester: discord.Member, rejector: discord.Member):
        super().__init__(title="Rejection Reason")
        self.bot = bot
        self.requester = requester
        self.rejector = rejector
        
        self.reason_input = discord.ui.TextInput(
            label="Reason for rejection",
            placeholder="Please provide a reason for rejecting this request...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )
        self.add_item(self.reason_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Send DM to requester
            embed = discord.Embed(
                title="❌ Ticket Join Request Rejected",
                description=f"Your request to join the ticket in **{interaction.guild.name}** was rejected.",
                color=0xED4245
            )
            embed.add_field(name="Rejected by", value=self.rejector.display_name, inline=True)
            embed.add_field(name="Reason", value=self.reason_input.value, inline=False)
            
            try:
                await self.requester.send(embed=embed)
                response_msg = f"Request rejected and {self.requester.mention} has been notified."
            except discord.Forbidden:
                response_msg = f"Request rejected but couldn't send DM to {self.requester.mention}."
            
            embed_response = discord.Embed(
                title="❌ Request Rejected",
                description=response_msg,
                color=0xED4245
            )
            
            await interaction.response.send_message(embed=embed_response)
            
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

class TicketManager:
    """Core ticket business logic and database operations"""
    
    def __init__(self, bot):
        self.bot = bot
        self.ticket_configs = {}  # Cache for guild configurations
    
    def generate_ticket_id(self) -> str:
        """Generate a unique ticket ID"""
        return f"TKT-{uuid.uuid4().hex[:8].upper()}"
    
    def current_timestamp(self) -> int:
        """Get current Unix timestamp"""
        return int(datetime.now(timezone.utc).timestamp())
    
    async def get_ticket_config(self, guild_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket configuration for a guild"""
        try:
            row = await self.bot.db.connection.fetchrow(
                "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                guild_id, 'ticket_config'
            )
            
            if row:
                config = json.loads(row['data_content'])
                self.ticket_configs[guild_id] = config
                return config
            return None
        except Exception as e:
            logger.error(f"Error getting ticket config for guild {guild_id}: {e}")
            return None
    
    async def save_ticket_config(self, guild_id: str, config: Dict[str, Any]) -> bool:
        """Save ticket configuration for a guild"""
        try:
            config['updated_at'] = self.current_timestamp()
            
            await self.bot.db.connection.execute(
                """INSERT INTO user_data (user_id, guild_id, data_type, data_content, created_at, updated_at)
                   VALUES ($1, $1, $2, $3, $4, $4)
                   ON CONFLICT (user_id, guild_id, data_type) DO UPDATE SET
                   data_content = $3, updated_at = $4""",
                guild_id, 'ticket_config', json.dumps(config), self.current_timestamp()
            )
            
            self.ticket_configs[guild_id] = config
            logger.info(f"Saved ticket config for guild {guild_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving ticket config for guild {guild_id}: {e}")
            return False
    
    async def create_ticket(self, guild: discord.Guild, user: discord.Member, 
                          title: str, description: str, priority: str = "medium") -> Optional[Dict[str, Any]]:
        """Create a new ticket with channel and database entry"""
        try:
            # Get configuration
            config = await self.get_ticket_config(str(guild.id))
            if not config:
                logger.error(f"No ticket config found for guild {guild.id}")
                return None
            
            # Generate ticket ID
            ticket_id = self.generate_ticket_id()
            current_time = self.current_timestamp()
            
            # Create ticket channel
            channel = await self._create_ticket_channel(guild, ticket_id, user, title, config)
            if not channel:
                return None
            
            # Save to database
            await self.bot.db.connection.execute(
                """INSERT INTO tickets (ticket_id, guild_id, user_id, channel_id, title, description, 
                   status, priority, assigned_users, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
                ticket_id, str(guild.id), str(user.id), str(channel.id), title, description,
                'open', priority, json.dumps([str(user.id)]), current_time, current_time
            )
            
            ticket_data = {
                'ticket_id': ticket_id,
                'guild_id': str(guild.id),
                'user_id': str(user.id),
                'channel_id': str(channel.id),
                'title': title,
                'description': description,
                'status': 'open',
                'priority': priority,
                'assigned_users': [str(user.id)],
                'created_at': current_time,
                'updated_at': current_time
            }
            
            logger.info(f"Created ticket {ticket_id} for user {user.id} in guild {guild.id}")
            return ticket_data
            
        except Exception as e:
            logger.error(f"Error creating ticket: {e}")
            return None
    
    async def _create_ticket_channel(self, guild: discord.Guild, ticket_id: str, 
                                   user: discord.Member, title: str, config: Dict[str, Any]) -> Optional[discord.TextChannel]:
        """Create the ticket channel with proper permissions"""
        try:
            # Get category
            category_id = config.get('category_id')
            category = guild.get_channel(int(category_id)) if category_id else None
            
            # Set up permissions - READ-ONLY by default for everyone
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            
            # Add admin permissions
            if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager:
                admin_role_ids = self.bot.admin_manager.get_admin_roles(str(guild.id))
                for role_id in admin_role_ids:
                    role = guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            # Create channel
            channel = await guild.create_text_channel(
                name=f"ticket-{ticket_id.lower()}",
                category=category,
                topic=f"Support ticket: {ticket_id} | Created by {user.display_name} | {title}",
                overwrites=overwrites,
                reason=f"Ticket {ticket_id} created by {user}"
            )
            
            logger.info(f"Created ticket channel {channel.name} for ticket {ticket_id}")
            return channel
            
        except Exception as e:
            logger.error(f"Error creating ticket channel: {e}")
            return None
    
    async def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket by ID"""
        try:
            row = await self.bot.db.connection.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
            )
            
            if row:
                ticket = dict(row)
                # Parse JSON fields
                if ticket.get('assigned_users'):
                    ticket['assigned_users'] = json.loads(ticket['assigned_users'])
                return ticket
            return None
        except Exception as e:
            logger.error(f"Error getting ticket {ticket_id}: {e}")
            return None
    
    async def get_user_tickets(self, guild_id: str, user_id: str, status: str = None) -> List[Dict[str, Any]]:
        """Get tickets for a specific user"""
        try:
            if status:
                rows = await self.bot.db.connection.fetch(
                    "SELECT * FROM tickets WHERE guild_id = $1 AND user_id = $2 AND status = $3 ORDER BY created_at DESC",
                    guild_id, user_id, status
                )
            else:
                rows = await self.bot.db.connection.fetch(
                    "SELECT * FROM tickets WHERE guild_id = $1 AND user_id = $2 ORDER BY created_at DESC",
                    guild_id, user_id
                )
            
            tickets = []
            for row in rows:
                ticket = dict(row)
                if ticket.get('assigned_users'):
                    ticket['assigned_users'] = json.loads(ticket['assigned_users'])
                tickets.append(ticket)
            
            return tickets
        except Exception as e:
            logger.error(f"Error getting user tickets: {e}")
            return []
    
    async def get_guild_tickets(self, guild_id: str, status: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all tickets for a guild"""
        try:
            if status:
                rows = await self.bot.db.connection.fetch(
                    "SELECT * FROM tickets WHERE guild_id = $1 AND status = $2 ORDER BY created_at DESC LIMIT $3",
                    guild_id, status, limit
                )
            else:
                rows = await self.bot.db.connection.fetch(
                    "SELECT * FROM tickets WHERE guild_id = $1 ORDER BY created_at DESC LIMIT $2",
                    guild_id, limit
                )
            
            tickets = []
            for row in rows:
                ticket = dict(row)
                if ticket.get('assigned_users'):
                    ticket['assigned_users'] = json.loads(ticket['assigned_users'])
                tickets.append(ticket)
            
            return tickets
        except Exception as e:
            logger.error(f"Error getting guild tickets: {e}")
            return []
    
    async def assign_user_to_ticket(self, ticket_id: str, user_id: str) -> bool:
        """Assign a user to a ticket"""
        try:
            ticket = await self.get_ticket(ticket_id)
            if not ticket:
                return False
            
            assigned_users = ticket.get('assigned_users', [])
            if user_id not in assigned_users:
                assigned_users.append(user_id)
                
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET assigned_users = $1, updated_at = $2 WHERE ticket_id = $3",
                    json.dumps(assigned_users), self.current_timestamp(), ticket_id
                )
                
                logger.info(f"Assigned user {user_id} to ticket {ticket_id}")
            
            return True
        except Exception as e:
            logger.error(f"Error assigning user to ticket: {e}")
            return False
    
    async def unassign_user_from_ticket(self, ticket_id: str, user_id: str) -> bool:
        """Unassign a user from a ticket"""
        try:
            ticket = await self.get_ticket(ticket_id)
            if not ticket:
                return False
            
            assigned_users = ticket.get('assigned_users', [])
            if user_id in assigned_users:
                assigned_users.remove(user_id)
                
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET assigned_users = $1, updated_at = $2 WHERE ticket_id = $3",
                    json.dumps(assigned_users), self.current_timestamp(), ticket_id
                )
                
                logger.info(f"Unassigned user {user_id} from ticket {ticket_id}")
            
            return True
        except Exception as e:
            logger.error(f"Error unassigning user from ticket: {e}")
            return False
    
    async def update_ticket_status(self, ticket_id: str, status: str) -> bool:
        """Update ticket status"""
        try:
            current_time = self.current_timestamp()
            
            if status == 'closed':
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET status = $1, updated_at = $2, closed_at = $3 WHERE ticket_id = $4",
                    status, current_time, current_time, ticket_id
                )
            else:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET status = $1, updated_at = $2 WHERE ticket_id = $3",
                    status, current_time, ticket_id
                )
            
            logger.info(f"Updated ticket {ticket_id} status to {status}")
            return True
        except Exception as e:
            logger.error(f"Error updating ticket status: {e}")
            return False
    
    async def set_ticket_visibility(self, channel: discord.TextChannel, private: bool = False) -> bool:
        """Set ticket visibility (public read-only or private)"""
        try:
            guild = channel.guild
            
            if private:
                # Private: Only assigned users can read
                await channel.set_permissions(guild.default_role, read_messages=False, send_messages=False)
            else:
                # Public: Everyone can read, only assigned can write
                await channel.set_permissions(guild.default_role, read_messages=True, send_messages=False)
            
            # Preserve bot permissions
            await channel.set_permissions(guild.me, read_messages=True, send_messages=True, manage_channels=True)
            
            # Get ticket info to preserve assigned user permissions
            if channel.topic and "Support ticket:" in channel.topic:
                ticket_id = channel.topic.split("|")[0].replace("Support ticket:", "").strip()
                ticket = await self.get_ticket(ticket_id)
                
                if ticket:
                    # Restore permissions for assigned users
                    assigned_users = ticket.get('assigned_users', [])
                    for user_id in assigned_users:
                        user = guild.get_member(int(user_id))
                        if user:
                            await channel.set_permissions(user, read_messages=True, send_messages=True)
                    
                    # Restore admin permissions
                    if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager:
                        admin_role_ids = self.bot.admin_manager.get_admin_roles(str(guild.id))
                        for role_id in admin_role_ids:
                            role = guild.get_role(int(role_id))
                            if role:
                                await channel.set_permissions(role, read_messages=True, send_messages=True)
            
            logger.info(f"Set ticket channel {channel.name} to {'private' if private else 'public'}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting ticket visibility: {e}")
            return False
    
    async def create_transcript(self, channel: discord.TextChannel) -> str:
        """Create a transcript of the ticket channel"""
        try:
            messages = []
            async for message in channel.history(limit=None, oldest_first=True):
                timestamp = message.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
                content = message.content or "[No content]"
                
                # Handle embeds
                if message.embeds:
                    for embed in message.embeds:
                        if embed.title:
                            content += f"\n[Embed: {embed.title}]"
                        if embed.description:
                            content += f"\n{embed.description}"
                
                # Handle attachments
                if message.attachments:
                    for attachment in message.attachments:
                        content += f"\n[Attachment: {attachment.filename}]"
                
                messages.append(f"[{timestamp}] {message.author}: {content}")
            
            transcript = "\n".join(messages)
            logger.info(f"Created transcript for {channel.name} ({len(messages)} messages)")
            return transcript
            
        except Exception as e:
            logger.error(f"Error creating transcript for {channel.name}: {e}")
            return f"Error creating transcript: {str(e)}"
    
    async def send_transcript(self, guild: discord.Guild, transcript: str, ticket_id: str, closed_by: discord.Member) -> bool:
        """Send transcript to the configured channel"""
        try:
            config = await self.get_ticket_config(str(guild.id))
            if not config or not config.get('transcript_channel_id'):
                logger.warning(f"No transcript channel configured for guild {guild.id}")
                return False
            
            transcript_channel = guild.get_channel(int(config['transcript_channel_id']))
            if not transcript_channel:
                logger.warning(f"Transcript channel not found for guild {guild.id}")
                return False
            
            # Create transcript file
            transcript_file = discord.File(
                io.StringIO(transcript),
                filename=f"transcript-{ticket_id}-{self.current_timestamp()}.txt"
            )
            
            # Create embed
            embed = discord.Embed(
                title=f"📄 Ticket Transcript: {ticket_id}",
                description=f"Ticket closed by {closed_by.mention}",
                color=0x5865F2,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(name="Closed by", value=closed_by.mention, inline=True)
            embed.add_field(name="Ticket ID", value=ticket_id, inline=True)
            embed.add_field(name="Closed at", value=f"<t:{self.current_timestamp()}:F>", inline=True)
            
            # Send transcript
            await transcript_channel.send(embed=embed, file=transcript_file)
            
            logger.info(f"Sent transcript for {ticket_id} to {transcript_channel.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending transcript for {ticket_id}: {e}")
            return False
    
    def can_manage_ticket(self, user: discord.Member, ticket: Dict[str, Any]) -> bool:
        """Check if user can manage a ticket (close, assign, etc.)"""
        # Check if user is admin
        if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(user):
            return True
        
        # Check if user is assigned to the ticket
        assigned_users = ticket.get('assigned_users', [])
        return str(user.id) in assigned_users
    
    def can_access_ticket(self, user: discord.Member, ticket: Dict[str, Any]) -> bool:
        """Check if user can access a ticket (read/write)"""
        # Admins can always access
        if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(user):
            return True
        
        # Assigned users can access
        assigned_users = ticket.get('assigned_users', [])
        return str(user.id) in assigned_users
