import discord
from discord.ext import commands
import uuid
from datetime import datetime
import json
from typing import Optional, Dict, Any
import asyncio
import random
import string
import io

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
        is_admin = self.bot.admin_manager.is_admin(interaction.user)
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
        is_admin = self.bot.admin_manager.is_admin(interaction.user)
        assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[4]
        user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[3]
        is_assignee = str(interaction.user.id) == assignee_id
        is_creator = str(interaction.user.id) == user_id
        
        if not (is_admin or is_assignee or is_creator):
            await interaction.response.send_message("Only ticket assignees, creators, or admins can deny join requests!", ephemeral=True)
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
            print(f"Error loading ticket configs: {e}")
    
    async def save_ticket_config(self, guild_id: str, config: Dict[str, Any]):
        """Save ticket configuration to database"""
        try:
            self.ticket_configs[guild_id] = config
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO ticket_configs (guild_id, category_id, support_role_id, log_channel_id, auto_close_hours, max_tickets_per_user)
                       VALUES ($1, $2, $3, $4, $5, $6)
                       ON CONFLICT (guild_id) DO UPDATE SET
                       category_id = $2, support_role_id = $3, log_channel_id = $4, 
                       auto_close_hours = $5, max_tickets_per_user = $6, updated_at = CURRENT_TIMESTAMP""",
                    guild_id, config.get('category_id'), config.get('support_role_id'),
                    config.get('log_channel_id'), config.get('auto_close_hours', 72),
                    config.get('max_tickets_per_user', 3)
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO ticket_configs (guild_id, category_id, support_role_id, log_channel_id, auto_close_hours, max_tickets_per_user)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (guild_id, config.get('category_id'), config.get('support_role_id'),
                     config.get('log_channel_id'), config.get('auto_close_hours', 72),
                     config.get('max_tickets_per_user', 3))
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error saving ticket config: {e}")
    
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
            print(f"Error getting ticket config: {e}")
            return None
    
    async def create_ticket_channel(self, guild: discord.Guild, ticket_id: str, user: discord.Member, title: str) -> Optional[discord.TextChannel]:
        """Create a ticket channel"""
        try:
            # Get ticket config
            config = await self.get_ticket_config(str(guild.id))
            if not config:
                print(f"No ticket config found for guild {guild.id}")
                return None
            
            category_id = config.get('category_id')
            if not category_id:
                print(f"No category_id in ticket config for guild {guild.id}")
                return None
            
            category = guild.get_channel(int(category_id))
            if not category:
                print(f"Category channel {category_id} not found in guild {guild.id}")
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
            if self.bot.admin_manager:
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
            print(f"Error creating ticket channel: {e}")
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
            if self.bot.admin_manager:
                admin_role_ids = self.bot.admin_manager.get_admin_roles(str(guild.id))
                for role_id in admin_role_ids:
                    role = guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            await channel.edit(overwrites=overwrites)
            return True
            
        except Exception as e:
            print(f"Error setting ticket visibility: {e}")
            return False
    
    async def create_transcript(self, channel: discord.TextChannel) -> str:
        """Create a transcript of the ticket channel"""
        try:
            messages = []
            async for message in channel.history(limit=None, oldest_first=True):
                timestamp = message.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
                content = message.content or "[No content]"
                
                if message.attachments:
                    attachments = "\n".join([f"Attachment: {att.filename}" for att in message.attachments])
                    content += f"\n{attachments}"
                
                messages.append(f"[{timestamp}] {message.author}: {content}")
            
            return "\n".join(messages)
            
        except Exception as e:
            print(f"Error creating transcript: {e}")
            return f"Error creating transcript: {str(e)}"
    
    async def send_transcript(self, guild: discord.Guild, transcript: str, ticket_id: str, user: discord.Member) -> bool:
        """Send transcript to the configured channel"""
        try:
            config = await self.get_ticket_config(str(guild.id))
            if not config:
                print(f"No ticket config found for guild {guild.id}")
                return False
            
            transcript_channel_id = config.get('transcript_channel_id')
            if not transcript_channel_id:
                print(f"No transcript_channel_id in config for guild {guild.id}")
                return False
            
            transcript_channel = guild.get_channel(int(transcript_channel_id))
            if not transcript_channel:
                print(f"Transcript channel {transcript_channel_id} not found in guild {guild.id}")
                return False
            
            # Create transcript file
            transcript_file = discord.File(
                fp=io.StringIO(transcript),
                filename=f"transcript_{ticket_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
            )
            
            embed = discord.Embed(
                title=f"🎫 Ticket Transcript: {ticket_id}",
                description=f"Ticket closed by {user.mention}",
                color=0x5865F2,
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="devBot - Powered by EGOS")
            
            await transcript_channel.send(embed=embed, file=transcript_file)
            print(f"Transcript sent successfully for ticket {ticket_id}")
            return True
            
        except Exception as e:
            print(f"Error sending transcript: {e}")
            return False
