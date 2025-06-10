import discord
from discord.ext import commands
from discord import app_commands
import uuid
import json
import asyncio
import io
from datetime import datetime
from typing import Optional, Dict, Any
from utils.helpers import EmbedBuilder
from config.constants import TicketStatus

class TicketJoinRequestView(discord.ui.View):
    def __init__(self, bot, requesting_user: discord.Member, ticket_channel: discord.TextChannel):
        super().__init__(timeout=300)
        self.bot = bot
        self.requesting_user = requesting_user
        self.ticket_channel = ticket_channel
    
    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success)
    async def accept_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Prevent self-acceptance
        if interaction.user.id == self.requesting_user.id:
            await interaction.response.send_message("❌ You cannot accept your own join request!", ephemeral=True)
            return
        
        # Check permissions
        if not await self._can_manage_ticket(interaction.user):
            await interaction.response.send_message("❌ Only ticket creators, assignees, or admins can accept join requests!", ephemeral=True)
            return
        
        try:
            # Grant write permissions
            await self.ticket_channel.set_permissions(
                self.requesting_user, 
                read_messages=True, 
                send_messages=True,
                add_reactions=True,
                attach_files=True
            )
            
            # Update embed
            embed = discord.Embed(
                title="✅ Join Request Accepted",
                description=f"{self.requesting_user.mention} has been granted write access to this ticket",
                color=0x57F287
            )
            embed.add_field(name="Accepted by", value=interaction.user.mention, inline=True)
            embed.add_field(name="Time", value=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), inline=True)
            
            # Disable buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
            # Notify the requesting user
            try:
                dm_embed = discord.Embed(
                    title="🎫 Ticket Access Granted",
                    description=f"Your request to join the ticket has been accepted!",
                    color=0x57F287
                )
                dm_embed.add_field(name="Channel", value=self.ticket_channel.mention, inline=True)
                dm_embed.add_field(name="Accepted by", value=interaction.user.mention, inline=True)
                await self.requesting_user.send(embed=dm_embed)
            except:
                await self.ticket_channel.send(f"🎉 {self.requesting_user.mention} Your join request has been accepted!")
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to grant access: {str(e)}", ephemeral=True)
    
    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger)
    async def deny_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Prevent self-denial
        if interaction.user.id == self.requesting_user.id:
            await interaction.response.send_message("❌ You cannot deny your own join request!", ephemeral=True)
            return
        
        # Check permissions
        if not await self._can_manage_ticket(interaction.user):
            await interaction.response.send_message("❌ Only ticket creators, assignees, or admins can deny join requests!", ephemeral=True)
            return
        
        # Update embed
        embed = discord.Embed(
            title="❌ Join Request Denied",
            description=f"{self.requesting_user.mention}'s request to join this ticket has been denied",
            color=0xED4245
        )
        embed.add_field(name="Denied by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), inline=True)
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Notify the requesting user
        try:
            dm_embed = discord.Embed(
                title="🎫 Ticket Access Denied",
                description=f"Your request to join the ticket has been denied.",
                color=0xED4245
            )
            dm_embed.add_field(name="Denied by", value=interaction.user.mention, inline=True)
            await self.requesting_user.send(embed=dm_embed)
        except:
            pass  # Don't send in channel for privacy
    
    async def _can_manage_ticket(self, user: discord.Member) -> bool:
        """Check if user can manage this ticket"""
        try:
            # Check if admin
            if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(user):
                return True
            
            # Get ticket info from channel topic
            if not self.ticket_channel.topic or "Support ticket:" not in self.ticket_channel.topic:
                return False
            
            ticket_id = self.ticket_channel.topic.split("|")[0].replace("Support ticket:", "").strip()
            
            # Get ticket from database
            if self.bot.db.is_postgresql:
                ticket = await self.bot.db.connection.fetchrow(
                    "SELECT user_id, assignee_id FROM tickets WHERE ticket_id = $1", ticket_id
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT user_id, assignee_id FROM tickets WHERE ticket_id = ?", (ticket_id,)
                )
                ticket = await cursor.fetchone()
            
            if not ticket:
                return False
            
            user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[0]
            assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[1]
            
            # Check if user is creator or assignee
            return str(user.id) in [user_id, assignee_id]
            
        except Exception as e:
            print(f"Error checking ticket permissions: {e}")
            return False

class TicketCloseView(discord.ui.View):
    def __init__(self, bot, ticket_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_id = ticket_id
    
    @discord.ui.button(label="Transcribe and Close", style=discord.ButtonStyle.danger, emoji="📄")
    async def transcribe_and_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Check permissions
            if not await self._can_close_ticket(interaction.user):
                embed = EmbedBuilder.error("Permission Denied", "Only ticket creators, assignees, or admins can close tickets")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            await interaction.response.defer()
            
            # Create transcript
            transcript = await self._create_transcript(interaction.channel)
            
            # Get ticket info
            ticket_info = await self._get_ticket_info()
            if not ticket_info:
                embed = EmbedBuilder.error("Error", "Ticket not found in database")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Send transcript
            transcript_sent = await self._send_transcript(interaction.guild, transcript, ticket_info)
            
            # Update ticket status
            await self._update_ticket_status()
            
            # Send closure message
            if transcript_sent:
                embed = EmbedBuilder.success(
                    "🎫 Ticket Closed Successfully", 
                    f"**Ticket {self.ticket_id}** has been closed and transcript saved.\n\n"
                    f"📄 **Transcript:** Successfully sent to transcript channel\n"
                    f"⏰ **Channel Deletion:** This channel will be deleted in 10 seconds."
                )
            else:
                embed = EmbedBuilder.warning(
                    "⚠️ Ticket Closed with Issues", 
                    f"**Ticket {self.ticket_id}** has been closed.\n\n"
                    f"❌ **Transcript:** Could not be saved - check transcript channel configuration\n"
                    f"⏰ **Channel Deletion:** This channel will be deleted in 10 seconds."
                )
            
            await interaction.followup.send(embed=embed)
            
            # Delete channel after delay
            await asyncio.sleep(10)
            try:
                await interaction.channel.delete(reason=f"Ticket {self.ticket_id} closed and transcribed")
            except Exception as e:
                print(f"Could not delete channel: {e}")
            
        except Exception as e:
            print(f"Error closing ticket: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to close ticket: {str(e)}")
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except:
                await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def _can_close_ticket(self, user: discord.Member) -> bool:
        """Check if user can close this ticket"""
        try:
            # Check if admin
            if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(user):
                return True
            
            # Get ticket info
            if self.bot.db.is_postgresql:
                ticket = await self.bot.db.connection.fetchrow(
                    "SELECT user_id, assignee_id FROM tickets WHERE ticket_id = $1", self.ticket_id
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT user_id, assignee_id FROM tickets WHERE ticket_id = ?", (self.ticket_id,)
                )
                ticket = await cursor.fetchone()
            
            if not ticket:
                return False
            
            user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[0]
            assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[1]
            
            return str(user.id) in [user_id, assignee_id]
            
        except Exception as e:
            print(f"Error checking close permissions: {e}")
            return False
    
    async def _create_transcript(self, channel: discord.TextChannel) -> str:
        """Create a transcript of the ticket channel"""
        try:
            messages = []
            message_count = 0
            
            async for message in channel.history(limit=None, oldest_first=True):
                timestamp = message.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
                content = message.content or "[No text content]"
                
                # Handle embeds
                if message.embeds:
                    for embed in message.embeds:
                        if embed.title:
                            content += f"\n[EMBED] Title: {embed.title}"
                        if embed.description:
                            content += f"\n[EMBED] Description: {embed.description}"
                
                # Handle attachments
                if message.attachments:
                    attachments = "\n".join([f"[ATTACHMENT] {att.filename} ({att.url})" for att in message.attachments])
                    content += f"\n{attachments}"
                
                # Handle reactions
                if message.reactions:
                    reactions = ", ".join([f"{reaction.emoji}({reaction.count})" for reaction in message.reactions])
                    content += f"\n[REACTIONS] {reactions}"
                
                messages.append(f"[{timestamp}] {message.author.display_name} ({message.author.id}): {content}")
                message_count += 1
            
            transcript_header = f"""=== TICKET TRANSCRIPT ===
Channel: {channel.name}
Guild: {channel.guild.name}
Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
Total Messages: {message_count}
========================

"""
            
            return transcript_header + "\n".join(messages)
            
        except Exception as e:
            print(f"Error creating transcript: {e}")
            return f"Error creating transcript: {str(e)}"
    
    async def _get_ticket_info(self) -> Optional[Dict]:
        """Get ticket information from database"""
        try:
            if self.bot.db.is_postgresql:
                ticket = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM tickets WHERE ticket_id = $1", self.ticket_id
                )
                return dict(ticket) if ticket else None
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM tickets WHERE ticket_id = ?", (self.ticket_id,)
                )
                ticket = await cursor.fetchone()
                if ticket:
                    # Convert to dict for SQLite
                    columns = ['id', 'ticket_id', 'guild_id', 'user_id', 'assignee_id', 'title', 'description', 'status', 'priority', 'channel_id', 'created_at', 'updated_at']
                    return dict(zip(columns, ticket))
                return None
        except Exception as e:
            print(f"Error getting ticket info: {e}")
            return None
    
    async def _send_transcript(self, guild: discord.Guild, transcript: str, ticket_info: Dict) -> bool:
        """Send transcript to configured channel"""
        try:
            # Get ticket config
            config = await self._get_ticket_config(str(guild.id))
            if not config:
                print("No ticket config found")
                return False
            
            transcript_channel_id = config.get('transcript_channel_id') or config.get('log_channel_id')
            if not transcript_channel_id:
                print("No transcript channel configured")
                return False
            
            transcript_channel = guild.get_channel(int(transcript_channel_id))
            if not transcript_channel:
                print(f"Transcript channel {transcript_channel_id} not found")
                return False
            
            # Create transcript file
            transcript_file = discord.File(
                fp=io.StringIO(transcript),
                filename=f"transcript_{self.ticket_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
            )
            
            # Create embed
            embed = discord.Embed(
                title=f"🎫 Ticket Transcript: {self.ticket_id}",
                description=f"**Title:** {ticket_info.get('title', 'Unknown')}\n**Guild:** {guild.name}",
                color=0x5865F2,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="📊 Stats", value=f"Lines: {len(transcript.split(chr(10)))}", inline=True)
            embed.add_field(name="📅 Closed", value=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), inline=True)
            embed.set_footer(text="devBot - Powered by EGOS")
            
            await transcript_channel.send(embed=embed, file=transcript_file)
            return True
            
        except Exception as e:
            print(f"Error sending transcript: {e}")
            return False
    
    async def _update_ticket_status(self):
        """Update ticket status to closed"""
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET status = $1, updated_at = $2 WHERE ticket_id = $3",
                    TicketStatus.CLOSED.value, datetime.utcnow(), self.ticket_id
                )
            else:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET status = ?, updated_at = ? WHERE ticket_id = ?",
                    (TicketStatus.CLOSED.value, datetime.utcnow(), self.ticket_id)
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error updating ticket status: {e}")
    
    async def _get_ticket_config(self, guild_id: str) -> Optional[Dict]:
        """Get ticket configuration for guild"""
        try:
            # Try user_data table first
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

class TicketCommands(app_commands.Group):
    """Ticket system commands"""
    
    def __init__(self, bot):
        super().__init__(name="ticket", description="Support ticket system")
        self.bot = bot
    
    @app_commands.command(name="create", description="Create a new support ticket")
    @app_commands.describe(
        title="Ticket title",
        description="Detailed description of the issue",
        priority="Ticket priority (low, medium, high)"
    )
    async def create_ticket(self, interaction: discord.Interaction, title: str, description: str, priority: str = "medium"):
        # Validate priority
        valid_priorities = ["low", "medium", "high"]
        if priority not in valid_priorities:
            priority = "medium"
        
        # Check if ticket system is configured
        config = await self._get_ticket_config(str(interaction.guild.id))
        if not config:
            embed = EmbedBuilder.error(
                "Ticket System Not Configured",
                "The ticket system has not been set up. Please ask an administrator to run `/ticket-system-setup`"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # Generate ticket ID
            ticket_id = self._generate_ticket_id()
            
            # Create ticket channel
            channel = await self._create_ticket_channel(interaction.guild, ticket_id, interaction.user, title, config)
            if not channel:
                embed = EmbedBuilder.error("Error", "Failed to create ticket channel. Please check bot permissions and configuration.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Save ticket to database
            await self._save_ticket_to_db(ticket_id, interaction.guild.id, interaction.user.id, title, description, priority, channel.id)
            
            # Create ticket embed
            embed = discord.Embed(
                title=f"🎫 Support Ticket: {ticket_id}",
                description=f"**Issue Description:**\n{description}",
                color=0x5865F2
            )
            embed.add_field(name="📋 Title", value=title, inline=False)
            embed.add_field(name="⚡ Priority", value=priority.title(), inline=True)
            embed.add_field(name="📊 Status", value="🟢 Open", inline=True)
            embed.add_field(name="👤 Created by", value=interaction.user.mention, inline=True)
            embed.add_field(name="👀 Visibility", value="🌐 **Public & Read-Only**", inline=False)
            embed.add_field(name="ℹ️ Access Info", value="• Everyone can **read** this ticket\n• Only you, assignees, and admins can **write**\n• Use `/ticket join` to request write access", inline=False)
            embed.timestamp = datetime.utcnow()
            embed.set_footer(text="devBot - Powered by EGOS")
            
            view = TicketCloseView(self.bot, ticket_id)
            
            # Send welcome message
            await channel.send(
                f"🎫 **Welcome {interaction.user.mention}!** Your support ticket has been created.\n\n"
                f"🌐 **This ticket is PUBLIC and READ-ONLY by default:**\n"
                f"• ✅ Everyone can see and read this conversation\n"
                f"• ❌ Only you, assignees, and admins can respond\n"
                f"• 💬 Others can request to join using `/ticket join`\n\n"
                f"📝 **You can participate** since you created this ticket.",
                embed=embed, 
                view=view
            )
            
            # Respond to user
            embed_response = EmbedBuilder.success(
                "🎫 Public Ticket Created Successfully",
                f"**Ticket ID:** `{ticket_id}`\n"
                f"**Channel:** {channel.mention}\n"
                f"**Priority:** {priority.title()}\n"
                f"**Visibility:** 🌐 **Public & Read-Only**\n\n"
                f"✅ **Your ticket is now visible to everyone** in the server\n"
                f"💬 **Only you, assignees, and admins** can respond\n"
                f"🔧 **Use `/ticket private`** if you need to make it private later"
            )
            await interaction.followup.send(embed=embed_response, ephemeral=True)
            
        except Exception as e:
            print(f"Error creating ticket: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to create ticket: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="assign", description="Assign a ticket to a user (Admin only)")
    @app_commands.describe(
        ticket_id="Ticket ID to assign",
        assignee="User to assign the ticket to"
    )
    async def assign_ticket(self, interaction: discord.Interaction, ticket_id: str, assignee: discord.Member):
        if not self._is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can assign tickets")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # Update database
            if self.bot.db.is_postgresql:
                result = await self.bot.db.connection.execute(
                    "UPDATE tickets SET assignee_id = $1, updated_at = $2 WHERE ticket_id = $3 AND guild_id = $4",
                    str(assignee.id), datetime.utcnow(), ticket_id, str(interaction.guild.id)
                )
                rows_affected = 1 if result == "UPDATE 1" else 0
            else:
                result = await self.bot.db.connection.execute(
                    "UPDATE tickets SET assignee_id = ?, updated_at = ? WHERE ticket_id = ? AND guild_id = ?",
                    (str(assignee.id), datetime.utcnow(), ticket_id, str(interaction.guild.id))
                )
                await self.bot.db.connection.commit()
                rows_affected = result.rowcount
            
            if rows_affected == 0:
                embed = EmbedBuilder.error("Not Found", f"Ticket {ticket_id} not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Update channel permissions
            await self._update_assignee_permissions(ticket_id, assignee, True)
            
            embed = EmbedBuilder.success(
                "Ticket Assigned",
                f"Ticket **{ticket_id}** has been assigned to {assignee.mention}"
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to assign ticket: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="unassign", description="Unassign a user from a ticket (Admin only)")
    @app_commands.describe(
        ticket_id="Ticket ID to unassign from",
        user="User to unassign from the ticket"
    )
    async def unassign_ticket(self, interaction: discord.Interaction, ticket_id: str, user: discord.Member):
        if not self._is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can unassign tickets")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # Get ticket info
            ticket = await self._get_ticket(ticket_id)
            
            if not ticket:
                embed = EmbedBuilder.error("Not Found", f"Ticket {ticket_id} not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check if user is assigned to this ticket
            assignee_id = ticket['assignee_id']
            if str(user.id) != assignee_id:
                embed = EmbedBuilder.error("Not Assigned", f"{user.mention} is not assigned to ticket {ticket_id}")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Remove assignment
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET assignee_id = NULL, updated_at = $1 WHERE ticket_id = $2",
                    datetime.utcnow(), ticket_id
                )
            else:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET assignee_id = NULL, updated_at = ? WHERE ticket_id = ?",
                    (datetime.utcnow(), ticket_id)
                )
                await self.bot.db.connection.commit()
            
            # Remove user permissions from ticket channel (but keep read access since it's public)
            await self._update_assignee_permissions(ticket_id, user, False)
            
            embed = EmbedBuilder.success(
                "Ticket Unassigned",
                f"{user.mention} has been unassigned from ticket **{ticket_id}**\n"
                f"They can still read the ticket (public access) but can no longer write."
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to unassign ticket: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="join", description="Request to join a ticket conversation")
    @app_commands.describe(ticket_id="ID of the ticket to join (optional if in ticket channel)")
    async def ticket_join(self, interaction: discord.Interaction, ticket_id: str = None):
        # Get ticket ID from channel if not provided
        if not ticket_id:
            if not interaction.channel.topic or "Support ticket:" not in interaction.channel.topic:
                embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels or with a ticket ID")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            ticket_id = interaction.channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        
        # Get ticket channel
        channel = await self._get_ticket_channel(ticket_id)
        if not channel:
            embed = EmbedBuilder.error("Not Found", f"Ticket {ticket_id} not found or channel deleted")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if user already has write access
        permissions = channel.permissions_for(interaction.user)
        if permissions.send_messages:
            embed = EmbedBuilder.warning("Already Joined", "You already have write access to this ticket conversation")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create join request
        embed = discord.Embed(
            title="🎫 Ticket Join Request",
            description=f"{interaction.user.mention} wants to join this ticket conversation",
            color=0xFEE75C
        )
        embed.add_field(name="👤 User", value=f"{interaction.user.mention}\n`{interaction.user}`", inline=True)
        embed.add_field(name="📅 Requested", value=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), inline=True)
        embed.add_field(name="🔍 Current Access", value="👀 **Read Only**\n(Can see all messages)", inline=True)
        embed.add_field(name="📝 Requesting", value="💬 **Write Access**\n(Can participate in conversation)", inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Only ticket creator, assignees, or admins can approve • devBot - Powered by EGOS")
        
        view = TicketJoinRequestView(self.bot, interaction.user, channel)
        
        # Send request to ticket channel
        await channel.send(embed=embed, view=view)
        
        # Notify user
        response_embed = EmbedBuilder.success(
            "📤 Join Request Sent",
            f"Your request to join ticket **{ticket_id}** has been sent.\n\n"
            f"👀 **Current Access:** You can read all messages\n"
            f"⏳ **Pending:** Write access (ability to respond)\n"
            f"✅ **Approval:** Ticket creator, assignees, or admins can approve"
        )
        await interaction.response.send_message(embed=response_embed, ephemeral=True)
    
    @app_commands.command(name="private", description="Make ticket private (only assigned users can read)")
    async def ticket_private(self, interaction: discord.Interaction):
        if not await self._is_ticket_channel(interaction.channel):
            embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        if not await self._can_manage_visibility(interaction.user, interaction.channel):
            embed = EmbedBuilder.error("Permission Denied", "Only ticket creator, assignee, or admins can change visibility")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        success = await self._set_ticket_visibility(interaction.channel, private=True)
        
        if success:
            embed = EmbedBuilder.success("🔒 Ticket Set to Private", "This ticket is now **private** - only assigned users and admins can read it")
        else:
            embed = EmbedBuilder.error("Error", "Failed to set ticket visibility")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="public", description="Make ticket public (everyone can read)")
    async def ticket_public(self, interaction: discord.Interaction):
        if not await self._is_ticket_channel(interaction.channel):
            embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        if not await self._can_manage_visibility(interaction.user, interaction.channel):
            embed = EmbedBuilder.error("Permission Denied", "Only ticket creator, assignee, or admins can change visibility")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        success = await self._set_ticket_visibility(interaction.channel, private=False)
        
        if success:
            embed = EmbedBuilder.success("🌐 Ticket Set to Public", "This ticket is now **public** - everyone can read it (but only assigned users can write)")
        else:
            embed = EmbedBuilder.error("Error", "Failed to set ticket visibility")
        
        await interaction.response.send_message(embed=embed)
    
    # Helper methods
    def _generate_ticket_id(self) -> str:
        """Generate a unique ticket ID"""
        return f"TKT-{uuid.uuid4().hex[:8].upper()}"
    
    def _is_admin(self, user: discord.Member) -> bool:
        """Check if user is admin"""
        return hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(user)
    
    async def _get_ticket_config(self, guild_id: str) -> Optional[Dict]:
        """Get ticket configuration for guild"""
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
    
    async def _create_ticket_channel(self, guild: discord.Guild, ticket_id: str, user: discord.Member, title: str, config: Dict) -> Optional[discord.TextChannel]:
        """Create a ticket channel with proper permissions"""
        try:
            category_id = config.get('category_id')
            if not category_id:
                return None
            
            category = guild.get_channel(int(category_id))
            if not category:
                return None
            
            # Set up permissions - PUBLIC READ-ONLY by default
            overwrites = {
                # Everyone can read but not write
                guild.default_role: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=False,
                    add_reactions=False,
                    attach_files=False
                ),
                # Ticket creator can read and write
                user: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    add_reactions=True,
                    attach_files=True
                ),
                # Bot can manage everything
                guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_messages=True,
                    add_reactions=True,
                    attach_files=True
                )
            }
            
            # Add admin roles
            if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager:
                admin_role_ids = self.bot.admin_manager.get_admin_roles(str(guild.id))
                for role_id in admin_role_ids:
                    role = guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(
                            read_messages=True,
                            send_messages=True,
                            add_reactions=True,
                            attach_files=True
                        )
            
            # Create channel
            channel = await guild.create_text_channel(
                name=f"ticket-{ticket_id.lower()}",
                category=category,
                topic=f"Support ticket: {ticket_id} | Created by {user.display_name} | 🌐 Public & Read-Only",
                overwrites=overwrites
            )
            
            return channel
            
        except Exception as e:
            print(f"Error creating ticket channel: {e}")
            return None
    
    async def _save_ticket_to_db(self, ticket_id: str, guild_id: int, user_id: int, title: str, description: str, priority: str, channel_id: int):
        """Save ticket to database"""
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO tickets (ticket_id, guild_id, user_id, title, description, status, priority, channel_id, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                    ticket_id, str(guild_id), str(user_id), title, description, 
                    TicketStatus.OPEN.value, priority, str(channel_id), datetime.utcnow()
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT INTO tickets (ticket_id, guild_id, user_id, title, description, status, priority, channel_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ticket_id, str(guild_id), str(user_id), title, description, 
                     TicketStatus.OPEN.value, priority, str(channel_id), datetime.utcnow())
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error saving ticket to database: {e}")
            raise
    
    async def _get_tickets(self, guild_id: str, status: str = "all", user: discord.Member = None):
        """Get tickets from database"""
        try:
            if self.bot.db.is_postgresql:
                query = "SELECT * FROM tickets WHERE guild_id = $1"
                params = [guild_id]
                param_count = 1
                
                if status != "all":
                    param_count += 1
                    query += f" AND status = ${param_count}"
                    params.append(status)
                
                if user:
                    param_count += 1
                    query += f" AND user_id = ${param_count}"
                    params.append(str(user.id))
                
                query += " ORDER BY created_at DESC LIMIT 10"
                return await self.bot.db.connection.fetch(query, *params)
            else:
                query = "SELECT * FROM tickets WHERE guild_id = ?"
                params = [guild_id]
                
                if status != "all":
                    query += " AND status = ?"
                    params.append(status)
                
                if user:
                    query += " AND user_id = ?"
                    params.append(str(user.id))
                
                query += " ORDER BY created_at DESC LIMIT 10"
                
                cursor = await self.bot.db.connection.execute(query, params)
                return await cursor.fetchall()
                
        except Exception as e:
            print(f"Error getting tickets: {e}")
            return []
    
    async def _get_ticket_channel(self, ticket_id: str) -> Optional[discord.TextChannel]:
        """Get ticket channel by ticket ID"""
        try:
            if self.bot.db.is_postgresql:
                ticket = await self.bot.db.connection.fetchrow(
                    "SELECT channel_id, guild_id FROM tickets WHERE ticket_id = $1", ticket_id
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT channel_id, guild_id FROM tickets WHERE ticket_id = ?", (ticket_id,)
                )
                ticket = await cursor.fetchone()
            
            if not ticket:
                return None
            
            channel_id = ticket['channel_id'] if self.bot.db.is_postgresql else ticket[0]
            guild_id = ticket['guild_id'] if self.bot.db.is_postgresql else ticket[1]
            
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return None
            
            return guild.get_channel(int(channel_id))
            
        except Exception as e:
            print(f"Error getting ticket channel: {e}")
            return None
    
    async def _update_assignee_permissions(self, ticket_id: str, assignee: discord.Member, grant: bool):
        """Update assignee permissions on ticket channel"""
        try:
            channel = await self._get_ticket_channel(ticket_id)
            if channel:
                if grant:
                    await channel.set_permissions(assignee, read_messages=True, send_messages=True, add_reactions=True, attach_files=True)
                else:
                    await channel.set_permissions(assignee, read_messages=True, send_messages=False)
        except Exception as e:
            print(f"Error updating assignee permissions: {e}")
    
    async def _is_ticket_channel(self, channel: discord.TextChannel) -> bool:
        """Check if channel is a ticket channel"""
        return channel.topic and "Support ticket:" in channel.topic
    
    async def _can_manage_visibility(self, user: discord.Member, channel: discord.TextChannel) -> bool:
        """Check if user can manage ticket visibility"""
        try:
            # Check if admin
            if self._is_admin(user):
                return True
            
            # Get ticket ID from channel topic
            if not channel.topic or "Support ticket:" not in channel.topic:
                return False
            
            ticket_id = channel.topic.split("|")[0].replace("Support ticket:", "").strip()
            
            # Get ticket info
            if self.bot.db.is_postgresql:
                ticket = await self.bot.db.connection.fetchrow(
                    "SELECT user_id, assignee_id FROM tickets WHERE ticket_id = $1", ticket_id
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT user_id, assignee_id FROM tickets WHERE ticket_id = ?", (ticket_id,)
                )
                ticket = await cursor.fetchone()
            
            if not ticket:
                return False
            
            user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[0]
            assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[1]
            
            return str(user.id) in [user_id, assignee_id]
            
        except Exception as e:
            print(f"Error checking visibility permissions: {e}")
            return False
    
    async def _set_ticket_visibility(self, channel: discord.TextChannel, private: bool = True) -> bool:
        """Set ticket visibility"""
        try:
            guild = channel.guild
            
            if private:
                # Private: Only assignees and admins can read
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        read_messages=False, 
                        send_messages=False
                    )
                }
            else:
                # Public: Everyone can read, only assignees can write
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        read_messages=True,
                        send_messages=False,
                        add_reactions=False,
                        attach_files=False
                    )
                }
            
            # Always allow bot to manage
            overwrites[guild.me] = discord.PermissionOverwrite(
                read_messages=True, 
                send_messages=True, 
                manage_channels=True,
                manage_messages=True
            )
            
            # Get ticket info to preserve creator and assignee permissions
            if channel.topic and "Support ticket:" in channel.topic:
                ticket_id = channel.topic.split("|")[0].replace("Support ticket:", "").strip()
                
                if self.bot.db.is_postgresql:
                    ticket = await self.bot.db.connection.fetchrow(
                        "SELECT user_id, assignee_id FROM tickets WHERE ticket_id = $1", ticket_id
                    )
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT user_id, assignee_id FROM tickets WHERE ticket_id = ?", (ticket_id,)
                    )
                    ticket = await cursor.fetchone()
                
                if ticket:
                    # Creator permissions
                    user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[0]
                    creator = guild.get_member(int(user_id))
                    if creator:
                        overwrites[creator] = discord.PermissionOverwrite(
                            read_messages=True, 
                            send_messages=True,
                            add_reactions=True,
                            attach_files=True
                        )
                    
                    # Assignee permissions
                    assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[1]
                    if assignee_id:
                        assignee = guild.get_member(int(assignee_id))
                        if assignee:
                            overwrites[assignee] = discord.PermissionOverwrite(
                                read_messages=True, 
                                send_messages=True,
                                add_reactions=True,
                                attach_files=True
                            )
            
            # Admin role permissions
            if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager:
                admin_role_ids = self.bot.admin_manager.get_admin_roles(str(guild.id))
                for role_id in admin_role_ids:
                    role = guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(
                            read_messages=True, 
                            send_messages=True,
                            add_reactions=True,
                            attach_files=True
                        )
            
            await channel.edit(overwrites=overwrites)
            return True
            
        except Exception as e:
            print(f"Error setting ticket visibility: {e}")
            return False
    
    async def _get_ticket(self, ticket_id: str) -> Optional[Dict]:
        """Get ticket information from database"""
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
                    # Convert to dict for SQLite
                    columns = ['id', 'ticket_id', 'guild_id', 'user_id', 'assignee_id', 'title', 'description', 'status', 'priority', 'channel_id', 'created_at', 'updated_at']
                    return dict(zip(columns, ticket))
                return None
        except Exception as e:
            print(f"Error getting ticket info: {e}")
            return None

class Ticket(commands.Cog):
    """Support ticket system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.ticket_commands = TicketCommands(bot)
    
    async def cog_load(self):
        """Called when the cog is loaded"""
        self.bot.tree.add_command(self.ticket_commands)
        print("🎫 Ticket system loaded successfully")

async def setup(bot):
    """Setup function for the cog"""
    cog = Ticket(bot)
    await bot.add_cog(cog)
    
    # Print success message
    command_count = len(cog.ticket_commands.commands)
    print(f"🎫 Successfully loaded Ticket cog with {command_count} commands")
