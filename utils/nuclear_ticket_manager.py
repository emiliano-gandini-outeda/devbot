"""
NUCLEAR TICKET MANAGER: Zero datetime objects
All timestamps stored as Unix integers
"""
import discord
from discord.ext import commands
import uuid
import json
import asyncio
import io
from typing import Optional, Dict, Any, List
from utils.timestamp_utils import (
    now_timestamp, timestamp_to_datetime, format_timestamp_for_discord,
    get_relative_timestamp
)
import logging

logger = logging.getLogger(__name__)

class NuclearTicketManager:
    """Nuclear ticket manager with integer timestamps only"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info("🚀 Nuclear Ticket Manager initialized")
    
    def generate_ticket_id(self) -> str:
        """Generate unique ticket ID"""
        return f"TKT-{uuid.uuid4().hex[:8].upper()}"
    
    async def get_ticket_config(self, guild_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket configuration for guild"""
        try:
            return await self.bot.db.fetchrow_nuclear(
                "SELECT * FROM ticket_configs WHERE guild_id = $1",
                guild_id
            )
        except Exception as e:
            logger.error(f"Failed to get ticket config: {e}")
            return None
    
    async def save_ticket_config(self, guild_id: str, category_id: str, transcript_channel_id: str, support_role_id: str = None):
        """Save ticket configuration with nuclear timestamps"""
        try:
            current_timestamp = now_timestamp()
            
            await self.bot.db.execute_nuclear(
                """INSERT INTO ticket_configs 
                   (guild_id, category_id, transcript_channel_id, support_role_id, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (guild_id) DO UPDATE SET
                   category_id = $2, transcript_channel_id = $3, support_role_id = $4, updated_at = $6""",
                guild_id, category_id, transcript_channel_id, support_role_id, current_timestamp, current_timestamp
            )
            
            logger.info(f"✅ Saved ticket config for guild {guild_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save ticket config: {e}")
            return False
    
    async def is_ticket_system_setup(self, guild_id: str) -> bool:
        """Check if ticket system is properly configured"""
        try:
            config = await self.get_ticket_config(guild_id)
            return config is not None and config.get('category_id') and config.get('transcript_channel_id')
        except Exception as e:
            logger.error(f"Failed to check ticket setup: {e}")
            return False
    
    async def save_ticket_to_database(self, ticket_id: str, guild_id: str, user_id: str, 
                                    title: str, description: str, priority: str, channel_id: str):
        """Save ticket with nuclear timestamp handling"""
        try:
            current_timestamp = now_timestamp()
            
            logger.info(f"🚀 Saving nuclear ticket {ticket_id}")
            logger.debug(f"Timestamp: {current_timestamp} (type: {type(current_timestamp)})")
            
            await self.bot.db.execute_nuclear(
                """INSERT INTO tickets 
                   (ticket_id, guild_id, user_id, title, description, priority, channel_id, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                ticket_id, guild_id, user_id, title, description, priority, channel_id, current_timestamp, current_timestamp
            )
            
            logger.info(f"✅ Nuclear ticket {ticket_id} saved successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to save nuclear ticket {ticket_id}: {e}")
            raise
    
    async def get_ticket_by_id(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket by ID"""
        try:
            return await self.bot.db.fetchrow_nuclear(
                "SELECT * FROM tickets WHERE ticket_id = $1",
                ticket_id
            )
        except Exception as e:
            logger.error(f"Failed to get ticket {ticket_id}: {e}")
            return None
    
    async def get_user_tickets(self, guild_id: str, user_id: str, status: str = None) -> List[Dict[str, Any]]:
        """Get tickets for user"""
        try:
            if status:
                return await self.bot.db.fetch_nuclear(
                    "SELECT * FROM tickets WHERE guild_id = $1 AND user_id = $2 AND status = $3 ORDER BY created_at DESC",
                    guild_id, user_id, status
                )
            else:
                return await self.bot.db.fetch_nuclear(
                    "SELECT * FROM tickets WHERE guild_id = $1 AND user_id = $2 ORDER BY created_at DESC",
                    guild_id, user_id
                )
        except Exception as e:
            logger.error(f"Failed to get user tickets: {e}")
            return []
    
    async def update_ticket_status(self, ticket_id: str, status: str):
        """Update ticket status"""
        try:
            current_timestamp = now_timestamp()
            await self.bot.db.execute_nuclear(
                "UPDATE tickets SET status = $1, updated_at = $2 WHERE ticket_id = $3",
                status, current_timestamp, ticket_id
            )
            logger.info(f"✅ Ticket {ticket_id} status updated to {status}")
        except Exception as e:
            logger.error(f"Failed to update ticket status: {e}")
            raise
    
    async def assign_ticket(self, ticket_id: str, assignee_id: Optional[str]):
        """Assign ticket to user"""
        try:
            current_timestamp = now_timestamp()
            await self.bot.db.execute_nuclear(
                "UPDATE tickets SET assignee_id = $1, updated_at = $2 WHERE ticket_id = $3",
                assignee_id, current_timestamp, ticket_id
            )
            logger.info(f"✅ Ticket {ticket_id} assigned to {assignee_id}")
        except Exception as e:
            logger.error(f"Failed to assign ticket: {e}")
            raise
    
    async def create_ticket_channel(self, guild: discord.Guild, ticket_id: str, user: discord.Member, title: str) -> Optional[discord.TextChannel]:
        """Create ticket channel"""
        try:
            config = await self.get_ticket_config(str(guild.id))
            if not config:
                logger.error(f"No ticket config for guild {guild.id}")
                return None
            
            # Get category
            category = None
            if config.get('category_id'):
                category = guild.get_channel(int(config['category_id']))
            
            # Create channel name
            channel_name = f"ticket-{ticket_id.lower()}"
            
            # Set permissions
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            
            # Add support role
            if config.get('support_role_id'):
                support_role = guild.get_role(int(config['support_role_id']))
                if support_role:
                    overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            # Create channel
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Support ticket: {ticket_id} | Created by {user.display_name}",
                reason=f"Ticket {ticket_id} created by {user}"
            )
            
            logger.info(f"✅ Created ticket channel {channel.name}")
            return channel
            
        except Exception as e:
            logger.error(f"Failed to create ticket channel: {e}")
            return None
    
    async def create_transcript(self, channel: discord.TextChannel) -> str:
        """Create channel transcript"""
        try:
            messages = []
            async for message in channel.history(limit=None, oldest_first=True):
                # Convert Discord timestamp to readable format
                timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
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
            logger.info(f"✅ Created transcript ({len(messages)} messages)")
            return transcript
            
        except Exception as e:
            logger.error(f"Failed to create transcript: {e}")
            return f"Error creating transcript: {str(e)}"
    
    async def send_transcript(self, guild: discord.Guild, transcript: str, ticket_id: str, closed_by: discord.Member) -> bool:
        """Send transcript to configured channel"""
        try:
            config = await self.get_ticket_config(str(guild.id))
            if not config or not config.get('transcript_channel_id'):
                logger.warning("No transcript channel configured")
                return False
            
            transcript_channel = guild.get_channel(int(config['transcript_channel_id']))
            if not transcript_channel:
                logger.warning("Transcript channel not found")
                return False
            
            # Create file
            transcript_file = discord.File(
                io.StringIO(transcript),
                filename=f"transcript-{ticket_id}.txt"
            )
            
            # Create embed with nuclear timestamp
            current_timestamp = now_timestamp()
            embed = discord.Embed(
                title=f"📄 Ticket Transcript: {ticket_id}",
                description=f"Ticket closed by {closed_by.mention}",
                color=0x5865F2,
                timestamp=timestamp_to_datetime(current_timestamp)
            )
            
            await transcript_channel.send(embed=embed, file=transcript_file)
            logger.info(f"✅ Sent transcript for {ticket_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send transcript: {e}")
            return False
