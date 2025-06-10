"""
Emergency rewrite of ticket manager with bulletproof database integration.
All database calls use the new sanitized query methods.
"""

import discord
from discord.ext import commands
import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)

class TicketJoinRequestView(discord.ui.View):
    """View for handling ticket join requests"""
    
    def __init__(self, bot, requesting_user: discord.Member, channel: discord.TextChannel):
        super().__init__(timeout=300)
        self.bot = bot
        self.requesting_user = requesting_user
        self.channel = channel
    
    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Check if user can approve
            if not await self._can_approve(interaction.user):
                await interaction.response.send_message("❌ Only ticket creator, assignees, or admins can approve join requests", ephemeral=True)
                return
            
            # Grant write permissions
            await self.channel.set_permissions(self.requesting_user, read_messages=True, send_messages=True)
            
            # Update embed
            embed = discord.Embed(
                title="✅ Join Request Approved",
                description=f"{self.requesting_user.mention} has been granted write access to this ticket",
                color=0x57F287,
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Approved by", value=interaction.user.mention, inline=True)
            
            # Disable buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
            # Notify the requesting user
            await self.channel.send(f"🎉 {self.requesting_user.mention} Welcome to the ticket conversation! You can now participate.")
            
        except Exception as e:
            logger.error(f"Error approving join request: {e}")
            await interaction.response.send_message("❌ Failed to approve join request", ephemeral=True)
    
    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Check if user can deny
            if not await self._can_approve(interaction.user):
                await interaction.response.send_message("❌ Only ticket creator, assignees, or admins can deny join requests", ephemeral=True)
                return
            
            # Update embed
            embed = discord.Embed(
                title="❌ Join Request Denied",
                description=f"{self.requesting_user.mention}'s request to join this ticket was denied",
                color=0xED4245,
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Denied by", value=interaction.user.mention, inline=True)
            
            # Disable buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
        except Exception as e:
            logger.error(f"Error denying join request: {e}")
            await interaction.response.send_message("❌ Failed to deny join request", ephemeral=True)
    
    async def _can_approve(self, user: discord.Member) -> bool:
        """Check if user can approve join requests"""
        try:
            # Check if admin
            if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(user):
                return True
            
            # Get ticket ID from channel topic
            if not self.channel.topic or "Support ticket:" not in self.channel.topic:
                return False
            
            ticket_id = self.channel.topic.split("|")[0].replace("Support ticket:", "").strip()
            
            # Get ticket info
            ticket_manager = self.bot.get_cog('Tickets').ticket_manager
            ticket = await ticket_manager.get_ticket_by_id(ticket_id)
            
            if not ticket:
                return False
            
            user_id = ticket['user_id']
            assignee_id = ticket['assignee_id']
            
            return str(user.id) in [user_id, assignee_id]
            
        except Exception as e:
            logger.error(f"Error checking approval permissions: {e}")
            return False

class TicketManager:
    """Emergency ticket manager with bulletproof database handling"""
    
    def __init__(self, bot):
        self.bot = bot
    
    def generate_ticket_id(self) -> str:
        """Generate a unique ticket ID"""
        return f"TKT-{uuid.uuid4().hex[:8].upper()}"
    
    async def get_ticket_config(self, guild_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket configuration for a guild"""
        try:
            return await self.bot.db.fetchrow_query(
                "SELECT * FROM ticket_configs WHERE guild_id = $1",
                guild_id
            )
        except Exception as e:
            logger.error(f"Failed to get ticket config for guild {guild_id}: {e}")
            return None
    
    async def save_ticket_to_database(self, ticket_id: str, guild_id: str, user_id: str, 
                                    title: str, description: str, priority: str, channel_id: str):
        """
        EMERGENCY FIX: Save ticket to database with bulletproof datetime handling
        """
        try:
            # Create current timestamp - this will be sanitized by db.py
            current_time = datetime.now(timezone.utc)
            
            logger.info(f"Saving ticket {ticket_id} to database")
            logger.debug(f"Parameters: guild_id={guild_id}, user_id={user_id}, title={title}")
            logger.debug(f"Current time: {current_time} (type: {type(current_time)})")
            
            # Use the new bulletproof execute_query method
            await self.bot.db.execute_query(
                """INSERT INTO tickets 
                   (ticket_id, guild_id, user_id, title, description, priority, channel_id, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                ticket_id, guild_id, user_id, title, description, priority, channel_id, current_time, current_time
            )
            
            logger.info(f"✅ Ticket {ticket_id} saved successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to save ticket {ticket_id}: {e}")
            raise
    
    async def get_ticket_by_id(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket by ID"""
        try:
            return await self.bot.db.fetchrow_query(
                "SELECT * FROM tickets WHERE ticket_id = $1",
                ticket_id
            )
        except Exception as e:
            logger.error(f"Failed to get ticket {ticket_id}: {e}")
            return None
    
    async def get_user_tickets(self, guild_id: str, user_id: str, status: str = None) -> List[Dict[str, Any]]:
        """Get tickets for a user"""
        try:
            if status:
                return await self.bot.db.fetch_query(
                    "SELECT * FROM tickets WHERE guild_id = $1 AND user_id = $2 AND status = $3 ORDER BY created_at DESC",
                    guild_id, user_id, status
                )
            else:
                return await self.bot.db.fetch_query(
                    "SELECT * FROM tickets WHERE guild_id = $1 AND user_id = $2 ORDER BY created_at DESC",
                    guild_id, user_id
                )
        except Exception as e:
            logger.error(f"Failed to get user tickets: {e}")
            return []
    
    async def update_ticket_status(self, ticket_id: str, status: str):
        """Update ticket status"""
        try:
            current_time = datetime.now(timezone.utc)
            await self.bot.db.execute_query(
                "UPDATE tickets SET status = $1, updated_at = $2 WHERE ticket_id = $3",
                status, current_time, ticket_id
            )
            logger.info(f"✅ Ticket {ticket_id} status updated to {status}")
        except Exception as e:
            logger.error(f"Failed to update ticket {ticket_id} status: {e}")
            raise
    
    async def assign_ticket(self, ticket_id: str, assignee_id: Optional[str]):
        """Assign ticket to a user"""
        try:
            current_time = datetime.now(timezone.utc)
            await self.bot.db.execute_query(
                "UPDATE tickets SET assignee_id = $1, updated_at = $2 WHERE ticket_id = $3",
                assignee_id, current_time, ticket_id
            )
            logger.info(f"✅ Ticket {ticket_id} assigned to {assignee_id}")
        except Exception as e:
            logger.error(f"Failed to assign ticket {ticket_id}: {e}")
            raise
    
    async def create_ticket_channel(self, guild: discord.Guild, ticket_id: str, user: discord.Member, title: str) -> Optional[discord.TextChannel]:
        """Create a ticket channel"""
        try:
            # Get ticket configuration
            config = await self.get_ticket_config(str(guild.id))
            
            # Determine category
            category = None
            if config and config.get('category_id'):
                category = guild.get_channel(int(config['category_id']))
            
            # Create channel name
            channel_name = f"ticket-{ticket_id.lower()}"
            
            # Set up permissions
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            
            # Add support role if configured
            if config and config.get('support_role_id'):
                support_role = guild.get_role(int(config['support_role_id']))
                if support_role:
                    overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            # Create channel
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Support ticket: {ticket_id} | Created by {user.display_name} | {title}",
                reason=f"Ticket {ticket_id} created by {user}"
            )
            
            logger.info(f"✅ Created ticket channel {channel.name} for {ticket_id}")
            return channel
            
        except Exception as e:
            logger.error(f"Failed to create ticket channel for {ticket_id}: {e}")
            return None
    
    async def set_ticket_visibility(self, channel: discord.TextChannel, private: bool = False) -> bool:
        """Set ticket visibility (public/private)"""
        try:
            guild = channel.guild
            
            if private:
                # Private: Only assigned users can read
                await channel.set_permissions(guild.default_role, read_messages=False, send_messages=False)
            else:
                # Public: Everyone can read, only assigned can write
                await channel.set_permissions(guild.default_role, read_messages=True, send_messages=False)
            
            logger.info(f"✅ Set ticket channel {channel.name} to {'private' if private else 'public'}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set ticket visibility: {e}")
            return False
    
    async def create_transcript(self, channel: discord.TextChannel) -> str:
        """Create a transcript of the ticket channel"""
        try:
            messages = []
            async for message in channel.history(limit=None, oldest_first=True):
                timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
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
            logger.info(f"✅ Created transcript for {channel.name} ({len(messages)} messages)")
            return transcript
            
        except Exception as e:
            logger.error(f"Failed to create transcript for {channel.name}: {e}")
            return f"Error creating transcript: {str(e)}"
    
    async def send_transcript(self, guild: discord.Guild, transcript: str, ticket_id: str, closed_by: discord.Member) -> bool:
        """Send transcript to the configured channel"""
        try:
            # Get ticket configuration
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
                filename=f"transcript-{ticket_id}.txt"
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
            
            # Send transcript
            await transcript_channel.send(embed=embed, file=transcript_file)
            
            logger.info(f"✅ Sent transcript for {ticket_id} to {transcript_channel.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send transcript for {ticket_id}: {e}")
            return False
