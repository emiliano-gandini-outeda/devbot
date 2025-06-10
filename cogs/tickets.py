"""
Complete Tickets Cog - Full functionality with nuclear timestamp integration
All datetime operations use Unix integer timestamps to prevent database errors
"""

import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
from utils.ticket_manager import TicketManager, TicketJoinRequestView
from utils.timestamp_utils import (
    now_timestamp, timestamp_to_datetime, format_timestamp_for_discord, 
    get_relative_timestamp
)
from config.constants import TicketStatus, TicketPriority
import json
import asyncio
import io
import uuid
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)

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
            
            # Get ticket manager
            ticket_manager = self.bot.get_cog('Tickets').ticket_manager
            
            # Create transcript
            transcript = await ticket_manager.create_transcript(interaction.channel)
            
            # Get ticket info
            ticket_info = await ticket_manager.get_ticket_by_id(self.ticket_id)
            if not ticket_info:
                embed = EmbedBuilder.error("Error", "Ticket not found in database")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Send transcript
            transcript_sent = await ticket_manager.send_transcript(interaction.guild, transcript, self.ticket_id, interaction.user)
            
            # Update ticket status with nuclear timestamp
            await ticket_manager.update_ticket_status(self.ticket_id, TicketStatus.CLOSED.value)
            
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
                logger.error(f"Could not delete channel: {e}")
            
        except Exception as e:
            logger.error(f"Error closing ticket: {e}")
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
            ticket_manager = self.bot.get_cog('Tickets').ticket_manager
            ticket = await ticket_manager.get_ticket_by_id(self.ticket_id)
            
            if not ticket:
                return False
            
            user_id = ticket['user_id']
            assignee_id = ticket['assignee_id']
            
            return str(user.id) in [user_id, assignee_id]
            
        except Exception as e:
            logger.error(f"Error checking close permissions: {e}")
            return False

class TicketSetupModal(discord.ui.Modal, title="Ticket System Setup"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
    
    category_name = discord.ui.TextInput(
        label="Category Name",
        placeholder="Enter category name for tickets (e.g., 'Support Tickets')",
        default="Support Tickets",
        max_length=100
    )
    
    transcript_channel = discord.ui.TextInput(
        label="Transcript Channel Name",
        placeholder="Enter channel name for transcripts (e.g., 'ticket-transcripts')",
        default="ticket-transcripts",
        max_length=100
    )
    
    support_role = discord.ui.TextInput(
        label="Support Role Name (Optional)",
        placeholder="Enter support role name (leave empty if none)",
        required=False,
        max_length=100
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            guild = interaction.guild
            
            # Create or get category
            category = None
            for cat in guild.categories:
                if cat.name.lower() == self.category_name.value.lower():
                    category = cat
                    break
            
            if not category:
                category = await guild.create_category(
                    name=self.category_name.value,
                    reason="Ticket system setup"
                )
            
            # Create or get transcript channel
            transcript_channel = None
            for channel in guild.text_channels:
                if channel.name.lower() == self.transcript_channel.value.lower().replace(' ', '-'):
                    transcript_channel = channel
                    break
            
            if not transcript_channel:
                transcript_channel = await guild.create_text_channel(
                    name=self.transcript_channel.value.replace(' ', '-'),
                    category=category,
                    reason="Ticket system setup - transcript channel"
                )
            
            # Get support role if specified
            support_role = None
            if self.support_role.value:
                for role in guild.roles:
                    if role.name.lower() == self.support_role.value.lower():
                        support_role = role
                        break
            
            # Save configuration with nuclear timestamp
            ticket_manager = self.bot.get_cog('Tickets').ticket_manager
            success = await ticket_manager.save_ticket_config(
                str(guild.id),
                str(category.id),
                str(transcript_channel.id),
                str(support_role.id) if support_role else None
            )
            
            if success:
                embed = EmbedBuilder.success(
                    "✅ Ticket System Configured",
                    f"**Category:** {category.name}\n"
                    f"**Transcript Channel:** {transcript_channel.mention}\n"
                    f"**Support Role:** {support_role.mention if support_role else 'None'}\n\n"
                    f"🎫 Users can now create tickets using `/ticket create`"
                )
            else:
                embed = EmbedBuilder.error("Error", "Failed to save ticket configuration")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Setup modal error: {e}")
            embed = EmbedBuilder.error("Setup Error", f"Failed to setup ticket system: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

class TicketCommands(app_commands.Group):
    """Ticket system commands"""
    
    def __init__(self, bot):
        super().__init__(name="ticket", description="Support ticket system")
        self.bot = bot
        self.ticket_manager = TicketManager(bot)
    
    @app_commands.command(name="create", description="Create a new support ticket")
    @app_commands.describe(
        title="Ticket title",
        description="Detailed description of the issue",
        priority="Ticket priority (low, medium, high, critical)"
    )
    @app_commands.choices(priority=[
        app_commands.Choice(name="Low", value="low"),
        app_commands.Choice(name="Medium", value="medium"),
        app_commands.Choice(name="High", value="high"),
        app_commands.Choice(name="Critical", value="critical")
    ])
    async def create_ticket(self, interaction: discord.Interaction, title: str, description: str, priority: str = "medium"):
        # Check if ticket system is configured
        config = await self.ticket_manager.get_ticket_config(str(interaction.guild.id))
        if not config:
            embed = EmbedBuilder.error(
                "Ticket System Not Configured",
                "The ticket system has not been set up. Please ask an administrator to run `/setup-tickets`"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # Check if user already has an open ticket
            existing_tickets = await self.ticket_manager.get_user_tickets(str(interaction.guild.id), str(interaction.user.id), "open")
            if existing_tickets:
                ticket = existing_tickets[0]
                embed = EmbedBuilder.warning(
                    "Existing Ticket Found",
                    f"You already have an open ticket: <#{ticket['channel_id']}>\n"
                    "Please use your existing ticket or close it before creating a new one."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Generate ticket ID
            ticket_id = self.ticket_manager.generate_ticket_id()
            
            # Create ticket channel
            channel = await self.ticket_manager.create_ticket_channel(interaction.guild, ticket_id, interaction.user, title)
            if not channel:
                embed = EmbedBuilder.error("Error", "Failed to create ticket channel. Please check bot permissions and configuration.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Save ticket to database with nuclear timestamp
            await self.ticket_manager.save_ticket_to_database(
                ticket_id, str(interaction.guild.id), str(interaction.user.id), 
                title, description, priority, str(channel.id)
            )
            
            # Create ticket embed with nuclear timestamp
            created_timestamp = now_timestamp()
            embed = discord.Embed(
                title=f"🎫 Support Ticket: {ticket_id}",
                description=f"**Issue Description:**\n{description}",
                color=0x5865F2,
                timestamp=timestamp_to_datetime(created_timestamp)
            )
            embed.add_field(name="📋 Title", value=title, inline=False)
            embed.add_field(name="⚡ Priority", value=priority.title(), inline=True)
            embed.add_field(name="📊 Status", value="🟢 Open", inline=True)
            embed.add_field(name="👤 Created by", value=interaction.user.mention, inline=True)
            embed.add_field(name="👀 Visibility", value="🌐 **Public & Read-Only**", inline=False)
            embed.add_field(name="ℹ️ Access Info", value="• Everyone can **read** this ticket\n• Only you, assignees, and admins can **write**\n• Use `/ticket join` to request write access", inline=False)
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
            logger.error(f"Error creating ticket: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to create ticket: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
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
        ticket = await self.ticket_manager.get_ticket_by_id(ticket_id)
        if not ticket:
            embed = EmbedBuilder.error("Not Found", f"Ticket {ticket_id} not found")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        channel = interaction.guild.get_channel(int(ticket['channel_id']))
        if not channel:
            embed = EmbedBuilder.error("Channel Not Found", f"Ticket {ticket_id} channel has been deleted")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if user already has write access
        permissions = channel.permissions_for(interaction.user)
        if permissions.send_messages:
            embed = EmbedBuilder.warning("Already Joined", "You already have write access to this ticket conversation")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create join request with nuclear timestamp
        current_timestamp = now_timestamp()
        embed = discord.Embed(
            title="🎫 Ticket Join Request",
            description=f"{interaction.user.mention} wants to join this ticket conversation",
            color=0xFEE75C,
            timestamp=timestamp_to_datetime(current_timestamp)
        )
        embed.add_field(name="👤 User", value=f"{interaction.user.mention}\n`{interaction.user}`", inline=True)
        embed.add_field(name="📅 Requested", value=format_timestamp_for_discord(current_timestamp), inline=True)
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
        
        success = await self.ticket_manager.set_ticket_visibility(interaction.channel, private=True)
        
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
        
        success = await self.ticket_manager.set_ticket_visibility(interaction.channel, private=False)
        
        if success:
            embed = EmbedBuilder.success("🌐 Ticket Set to Public", "This ticket is now **public** - everyone can read it (but only assigned users can write)")
        else:
            embed = EmbedBuilder.error("Error", "Failed to set ticket visibility")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="list", description="List all tickets")
    @app_commands.describe(
        status="Filter by status (open, closed, all)",
        user="Filter by user (mention or ID)"
    )
    @app_commands.choices(status=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Open", value="open"),
        app_commands.Choice(name="Closed", value="closed")
    ])
    async def list_tickets(self, interaction: discord.Interaction, status: str = "all", user: discord.Member = None):
        await interaction.response.defer()
        
        try:
            # Get tickets based on filters
            if user:
                if status == "all":
                    tickets = await self.ticket_manager.get_user_tickets(str(interaction.guild.id), str(user.id))
                else:
                    tickets = await self.ticket_manager.get_user_tickets(str(interaction.guild.id), str(user.id), status)
            else:
                # Get all tickets for guild
                tickets = await self._get_guild_tickets(str(interaction.guild.id), status)
            
            if not tickets:
                embed = EmbedBuilder.info("No Tickets", "No tickets found matching your criteria")
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title="🎫 Support Tickets",
                color=0x5865F2,
                timestamp=timestamp_to_datetime(now_timestamp())
            )
            embed.set_footer(text="devBot - Powered by EGOS")
            
            for ticket in tickets[:10]:  # Limit to 10 tickets
                ticket_id = ticket['ticket_id']
                user_id = ticket['user_id']
                title = ticket['title']
                ticket_status = ticket['status']
                priority = ticket['priority']
                channel_id = ticket['channel_id']
                created_at = ticket['created_at']  # Already Unix timestamp
                
                ticket_user = interaction.guild.get_member(int(user_id))
                user_name = ticket_user.display_name if ticket_user else "Unknown"
                
                status_emoji = "🟢" if ticket_status == "open" else "🔴"
                priority_emoji = {"low": "🔵", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(priority, "🟡")
                
                # Create channel link if channel exists
                channel_link = "Channel Deleted"
                if channel_id:
                    channel = interaction.guild.get_channel(int(channel_id))
                    if channel:
                        channel_link = f"[#{channel.name}]({channel.jump_url})"
                
                embed.add_field(
                    name=f"{status_emoji} {ticket_id}",
                    value=f"**Title:** {title}\n"
                          f"**User:** {user_name}\n"
                          f"**Priority:** {priority_emoji} {priority.title()}\n"
                          f"**Status:** {ticket_status.title()}\n"
                          f"**Channel:** {channel_link}\n"
                          f"**Created:** {get_relative_timestamp(created_at)}",
                    inline=True
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error listing tickets: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to fetch tickets: {str(e)}")
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
            # Check if ticket exists
            ticket = await self.ticket_manager.get_ticket_by_id(ticket_id)
            if not ticket:
                embed = EmbedBuilder.error("Not Found", f"Ticket {ticket_id} not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Assign ticket
            await self.ticket_manager.assign_ticket(ticket_id, str(assignee.id))
            
            # Update channel permissions
            channel = interaction.guild.get_channel(int(ticket['channel_id']))
            if channel:
                await channel.set_permissions(assignee, read_messages=True, send_messages=True)
            
            embed = EmbedBuilder.success(
                "Ticket Assigned",
                f"Ticket **{ticket_id}** has been assigned to {assignee.mention}"
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error assigning ticket: {e}")
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
            ticket = await self.ticket_manager.get_ticket_by_id(ticket_id)
            if not ticket:
                embed = EmbedBuilder.error("Not Found", f"Ticket {ticket_id} not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check if user is assigned to this ticket
            if str(user.id) != ticket['assignee_id']:
                embed = EmbedBuilder.error("Not Assigned", f"{user.mention} is not assigned to ticket {ticket_id}")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Remove assignment
            await self.ticket_manager.assign_ticket(ticket_id, None)
            
            # Remove user permissions from ticket channel (but keep read access since it's public)
            channel = interaction.guild.get_channel(int(ticket['channel_id']))
            if channel:
                await channel.set_permissions(user, read_messages=True, send_messages=False)
            
            embed = EmbedBuilder.success(
                "Ticket Unassigned",
                f"{user.mention} has been unassigned from ticket **{ticket_id}**\n"
                f"They can still read the ticket (public access) but can no longer write."
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error unassigning ticket: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to unassign ticket: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="close", description="Close a ticket")
    @app_commands.describe(ticket_id="Ticket ID to close (optional if in ticket channel)")
    async def close_ticket(self, interaction: discord.Interaction, ticket_id: str = None):
        # Get ticket ID from channel if not provided
        if not ticket_id:
            if not interaction.channel.topic or "Support ticket:" not in interaction.channel.topic:
                embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels or with a ticket ID")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            ticket_id = interaction.channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        
        # Check permissions
        ticket = await self.ticket_manager.get_ticket_by_id(ticket_id)
        if not ticket:
            embed = EmbedBuilder.error("Not Found", f"Ticket {ticket_id} not found")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if user can close ticket
        can_close = (
            str(interaction.user.id) == ticket['user_id'] or  # Ticket creator
            str(interaction.user.id) == ticket['assignee_id'] or  # Assignee
            self._is_admin(interaction.user)  # Admin
        )
        
        if not can_close:
            embed = EmbedBuilder.error("Permission Denied", "Only ticket creator, assignee, or admins can close tickets")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # Create transcript
            channel = interaction.guild.get_channel(int(ticket['channel_id']))
            if channel:
                transcript = await self.ticket_manager.create_transcript(channel)
                transcript_sent = await self.ticket_manager.send_transcript(interaction.guild, transcript, ticket_id, interaction.user)
            else:
                transcript_sent = False
            
            # Update ticket status
            await self.ticket_manager.update_ticket_status(ticket_id, TicketStatus.CLOSED.value)
            
            # Send closure message
            if transcript_sent:
                embed = EmbedBuilder.success(
                    "🎫 Ticket Closed Successfully",
                    f"**Ticket {ticket_id}** has been closed and transcript saved."
                )
            else:
                embed = EmbedBuilder.warning(
                    "⚠️ Ticket Closed with Issues",
                    f"**Ticket {ticket_id}** has been closed.\n"
                    f"❌ **Transcript:** Could not be saved - check transcript channel configuration"
                )
            
            await interaction.followup.send(embed=embed)
            
            # Delete channel after delay if it exists
            if channel:
                await asyncio.sleep(5)
                try:
                    await channel.delete(reason=f"Ticket {ticket_id} closed")
                except Exception as e:
                    logger.error(f"Could not delete channel: {e}")
            
        except Exception as e:
            logger.error(f"Error closing ticket: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to close ticket: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    # Helper methods
    def _is_admin(self, user: discord.Member) -> bool:
        """Check if user is admin"""
        return hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(user)
    
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
            ticket = await self.ticket_manager.get_ticket_by_id(ticket_id)
            if not ticket:
                return False
            
            user_id = ticket['user_id']
            assignee_id = ticket['assignee_id']
            
            return str(user.id) in [user_id, assignee_id]
            
        except Exception as e:
            logger.error(f"Error checking visibility permissions: {e}")
            return False
    
    async def _get_guild_tickets(self, guild_id: str, status: str = "all"):
        """Get all tickets for a guild"""
        try:
            if status == "all":
                tickets = await self.bot.db.fetch(
                    "SELECT * FROM tickets WHERE guild_id = $1 ORDER BY created_at DESC LIMIT 50",
                    guild_id
                )
            else:
                tickets = await self.bot.db.fetch(
                    "SELECT * FROM tickets WHERE guild_id = $1 AND status = $2 ORDER BY created_at DESC LIMIT 50",
                    guild_id, status
                )
            return tickets
        except Exception as e:
            logger.error(f"Error getting guild tickets: {e}")
            return []

class Tickets(commands.Cog):
    """Support ticket system with nuclear timestamp integration"""
    
    def __init__(self, bot):
        self.bot = bot
        self.ticket_manager = TicketManager(bot)
        self.ticket_commands = TicketCommands(bot)
    
    async def cog_load(self):
        """Called when the cog is loaded"""
        self.bot.tree.add_command(self.ticket_commands)
        logger.info("🎫 Nuclear Ticket system loaded successfully")
    
    @app_commands.command(name="setup-tickets", description="🎫 Setup the ticket system (Admin only)")
    async def setup_tickets(self, interaction: discord.Interaction):
        """Setup ticket system for the guild"""
        # Check admin permissions
        if not interaction.user.guild_permissions.administrator:
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can setup the ticket system")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if already configured
        config = await self.ticket_manager.get_ticket_config(str(interaction.guild.id))
        if config:
            embed = EmbedBuilder.info(
                "Already Configured",
                f"Ticket system is already configured for this server.\n\n"
                f"**Category:** <#{config['category_id']}>\n"
                f"**Transcript Channel:** <#{config['transcript_channel_id']}>\n"
                f"**Support Role:** <@&{config['support_role_id']}>" if config.get('support_role_id') else "**Support Role:** None"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Show setup modal
        modal = TicketSetupModal(self.bot)
        await interaction.response.send_modal(modal)

async def setup(bot):
    """Setup function for the cog"""
    cog = Tickets(bot)
    await bot.add_cog(cog)
    
    # Print success message
    command_count = len(cog.ticket_commands.commands) + 1  # +1 for setup-tickets
    logger.info(f"🎫 Successfully loaded Tickets cog with {command_count} commands")
