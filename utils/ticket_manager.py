"""
FIXED Ticket Manager - Uses correct database methods
All database calls now use the proper DatabaseManager interface
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
        if interaction.user.id == self.requesting_user.id:
            await interaction.response.send_message("You cannot accept your own join request!", ephemeral=True)
            return
        
        ticket_id = self.ticket_channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        
        ticket_manager = TicketManager(self.bot)
        ticket = await ticket_manager.get_ticket(ticket_id)
        
        if not ticket:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return
        
        if not ticket_manager.can_manage_ticket(interaction.user, ticket):
            await interaction.response.send_message("Only ticket assignees or admins can accept join requests!", ephemeral=True)
            return
        
        try:
            await self.ticket_channel.set_permissions(
                self.requesting_user, 
                read_messages=True, 
                send_messages=True
            )
            
            embed = discord.Embed(
                title="✅ Join Request Accepted",
                description=f"{self.requesting_user.mention} has been granted access to this ticket",
                color=0x57F287
            )
            embed.add_field(name="Accepted by", value=interaction.user.mention, inline=True)
            embed.add_field(name="Time", value=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), inline=True)
            
            for item in self.children:
                item.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
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
                await self.ticket_channel.send(f"{self.requesting_user.mention} Your join request has been accepted!")
            
        except Exception as e:
            await interaction.response.send_message(f"Failed to grant access: {str(e)}", ephemeral=True)
    
    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger)
    async def deny_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.requesting_user.id:
            await interaction.response.send_message("You cannot deny your own join request!", ephemeral=True)
            return
        
        ticket_id = self.ticket_channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        
        ticket_manager = TicketManager(self.bot)
        ticket = await ticket_manager.get_ticket(ticket_id)
        
        if not ticket:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return
        
        if not ticket_manager.can_manage_ticket(interaction.user, ticket):
            await interaction.response.send_message("Only ticket assignees or admins can deny join requests!", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="❌ Join Request Denied",
            description=f"{self.requesting_user.mention}'s request to join this ticket has been denied",
            color=0xED4245
        )
        embed.add_field(name="Denied by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), inline=True)
        
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        try:
            dm_embed = discord.Embed(
                title="🎫 Ticket Access Denied",
                description=f"Your request to join ticket {ticket_id} has been denied.",
                color=0xED4245
            )
            dm_embed.add_field(name="Denied by", value=interaction.user.mention, inline=True)
            
            await self.requesting_user.send(embed=dm_embed)
        except:
            pass

class TicketManager:
    """FIXED Ticket Manager with correct database method calls"""
    
    def __init__(self, bot):
        self.bot = bot
        self.ticket_configs = {}
    
    async def load_ticket_configs(self) -> bool:
        """Load all ticket configurations from database"""
        try:
            rows = await self.bot.db.connection.fetch(
                "SELECT user_id, data_content FROM user_data WHERE data_type = $1",
                'ticket_config'
            )
            
            for row in rows:
                guild_id = row['user_id']  # user_id is used as guild_id for configs
                config = json.loads(row['data_content'])
                self.ticket_configs[guild_id] = config
            
            logger.info(f"Loaded {len(self.ticket_configs)} ticket configurations")
            return True
            
        except Exception as e:
            logger.error(f"Error loading ticket configs: {e}")
            return False
    
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
            current_time = self.current_timestamp()
            
            await self.bot.db.connection.execute(
                """INSERT INTO user_data (user_id, guild_id, data_type, data_content, created_at, updated_at)
                   VALUES ($1, $1, $2, $3, $4, $4)
                   ON CONFLICT (user_id, guild_id, data_type) DO UPDATE SET
                   data_content = $3, updated_at = $4""",
                guild_id, 'ticket_config', json.dumps(config), current_time
            )
            
            self.ticket_configs[guild_id] = config
            logger.info(f"Saved ticket config for guild {guild_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving ticket config for guild {guild_id}: {e}")
            return False
    
    async def create_ticket(self, guild: discord.Guild, user: discord.Member, 
                          title: str, description: str, priority: str = "medium") -> Optional[Dict[str, Any]]:
        """FIXED: Create a new ticket with proper timestamp handling"""
        try:
            config = await self.get_ticket_config(str(guild.id))
            if not config:
                logger.error(f"No ticket config found for guild {guild.id}")
                return None
            
            ticket_id = self.generate_ticket_id()
            current_time = self.current_timestamp()
            
            channel = await self._create_ticket_channel(guild, ticket_id, user, title, config)
            if not channel:
                return None
            
            # FIXED: Database will automatically convert Unix timestamp to datetime
            logger.info(f"🔧 Creating ticket with timestamp: {current_time}")
            
            await self.bot.db.connection.execute(
                """INSERT INTO tickets (ticket_id, guild_id, user_id, channel_id, title, description, 
                   status, priority, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                ticket_id, str(guild.id), str(user.id), str(channel.id), title, description,
                'open', priority, current_time, current_time
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
                'created_at': current_time,
                'updated_at': current_time
            }
            
            logger.info(f"✅ Created ticket {ticket_id} for user {user.id} in guild {guild.id}")
            return ticket_data
            
        except Exception as e:
            logger.error(f"❌ Error creating ticket: {e}")
            logger.error(f"Parameters: guild={guild.id}, user={user.id}, title={title}")
            return None
    
    async def _create_ticket_channel(self, guild: discord.Guild, ticket_id: str, 
                                   user: discord.Member, title: str, config: Dict[str, Any]) -> Optional[discord.TextChannel]:
        """Create the ticket channel with proper permissions"""
        try:
            category_id = config.get('category_id')
            category = guild.get_channel(int(category_id)) if category_id else None
            
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            
            if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager:
                admin_role_ids = self.bot.admin_manager.get_admin_roles(str(guild.id))
                for role_id in admin_role_ids:
                    role = guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
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
            return dict(row) if row else None
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
            
            return [dict(row) for row in rows]
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
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting guild tickets: {e}")
            return []
    
    async def assign_user_to_ticket(self, ticket_id: str, user_id: str) -> bool:
        """Assign a user to a ticket"""
        try:
            current_time = self.current_timestamp()
            await self.bot.db.connection.execute(
                "UPDATE tickets SET assignee_id = $1, updated_at = $2 WHERE ticket_id = $3",
                user_id, current_time, ticket_id
            )
            logger.info(f"Assigned user {user_id} to ticket {ticket_id}")
            return True
        except Exception as e:
            logger.error(f"Error assigning user to ticket: {e}")
            return False
    
    async def update_ticket_status(self, ticket_id: str, status: str) -> bool:
        """Update ticket status"""
        try:
            current_time = self.current_timestamp()
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
                await channel.set_permissions(guild.default_role, read_messages=False, send_messages=False)
            else:
                await channel.set_permissions(guild.default_role, read_messages=True, send_messages=False)
            
            await channel.set_permissions(guild.me, read_messages=True, send_messages=True, manage_channels=True)
            
            if channel.topic and "Support ticket:" in channel.topic:
                ticket_id = channel.topic.split("|")[0].replace("Support ticket:", "").strip()
                ticket = await self.get_ticket(ticket_id)
                
                if ticket:
                    user_id = ticket.get('user_id')
                    if user_id:
                        user = guild.get_member(int(user_id))
                        if user:
                            await channel.set_permissions(user, read_messages=True, send_messages=True)
                    
                    assignee_id = ticket.get('assignee_id')
                    if assignee_id:
                        assignee = guild.get_member(int(assignee_id))
                        if assignee:
                            await channel.set_permissions(assignee, read_messages=True, send_messages=True)
                    
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
                
                if message.embeds:
                    for embed in message.embeds:
                        if embed.title:
                            content += f"\n[Embed: {embed.title}]"
                        if embed.description:
                            content += f"\n{embed.description}"
                
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
            
            transcript_file = discord.File(
                io.StringIO(transcript),
                filename=f"transcript-{ticket_id}-{self.current_timestamp()}.txt"
            )
            
            embed = discord.Embed(
                title=f"📄 Ticket Transcript: {ticket_id}",
                description=f"Ticket closed by {closed_by.mention}",
                color=0x5865F2,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(name="Closed by", value=closed_by.mention, inline=True)
            embed.add_field(name="Ticket ID", value=ticket_id, inline=True)
            embed.add_field(name="Closed at", value=f"<t:{self.current_timestamp()}:F>", inline=True)
            
            await transcript_channel.send(embed=embed, file=transcript_file)
            
            logger.info(f"Sent transcript for {ticket_id} to {transcript_channel.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending transcript for {ticket_id}: {e}")
            return False
    
    def can_manage_ticket(self, user: discord.Member, ticket: Dict[str, Any]) -> bool:
        """Check if user can manage a ticket"""
        if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(user):
            return True
        
        if str(user.id) == ticket.get('user_id'):
            return True
        
        assignee_id = ticket.get('assignee_id')
        if assignee_id and str(user.id) == assignee_id:
            return True
        
        return False
    
    def can_access_ticket(self, user: discord.Member, ticket: Dict[str, Any]) -> bool:
        """Check if user can access a ticket"""
        if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(user):
            return True
        
        if str(user.id) == ticket.get('user_id'):
            return True
        
        assignee_id = ticket.get('assignee_id')
        if assignee_id and str(user.id) == assignee_id:
            return True
        
        return False
