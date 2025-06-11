"""
Ticket System Discord Interface
Handles all Discord slash commands and user interactions
"""

import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
from utils.ticket_manager import TicketManager
from datetime import datetime, timezone
import json
import asyncio
from typing import Optional

class TicketJoinRequestView(discord.ui.View):
    """View for handling ticket join requests"""
    
    def __init__(self, bot, requesting_user: discord.Member, ticket_channel: discord.TextChannel):
        super().__init__(timeout=300)
        self.bot = bot
        self.requesting_user = requesting_user
        self.ticket_channel = ticket_channel
    
    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success)
    async def approve_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Check if user can approve
            if not await self._can_approve(interaction.user):
                await interaction.response.send_message("❌ Only ticket assignees or admins can approve join requests", ephemeral=True)
                return
            
            # Get ticket manager
            ticket_manager = self.bot.get_cog('Tickets').ticket_manager
            
            # Get ticket ID from channel topic
            ticket_id = self.ticket_channel.topic.split("|")[0].replace("Support ticket:", "").strip()
            
            # Assign user to ticket
            success = await ticket_manager.assign_user_to_ticket(ticket_id, str(self.requesting_user.id))
            if not success:
                await interaction.response.send_message("❌ Failed to assign user to ticket", ephemeral=True)
                return
            
            # Grant write permissions
            await self.ticket_channel.set_permissions(self.requesting_user, read_messages=True, send_messages=True)
            
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
            
            # Welcome message
            await self.ticket_channel.send(f"🎉 {self.requesting_user.mention} Welcome to the ticket conversation! You can now participate.")
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Error approving join request: {str(e)}", ephemeral=True)
    
    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger)
    async def deny_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Check if user can deny
            if not await self._can_approve(interaction.user):
                await interaction.response.send_message("❌ Only ticket assignees or admins can deny join requests", ephemeral=True)
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
            await interaction.response.send_message(f"❌ Error denying join request: {str(e)}", ephemeral=True)
    
    async def _can_approve(self, user: discord.Member) -> bool:
        """Check if user can approve join requests"""
        try:
            # Check if admin
            if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(user):
                return True
            
            # Get ticket ID and check if user is assigned
            ticket_id = self.ticket_channel.topic.split("|")[0].replace("Support ticket:", "").strip()
            ticket_manager = self.bot.get_cog('Tickets').ticket_manager
            ticket = await ticket_manager.get_ticket(ticket_id)
            
            if ticket:
                return ticket_manager.can_manage_ticket(user, ticket)
            
            return False
            
        except Exception:
            return False

class TicketCloseView(discord.ui.View):
    """View for closing tickets with transcript generation"""
    
    def __init__(self, bot, ticket_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_id = ticket_id
    
    @discord.ui.button(label="🔒 Close & Generate Transcript", style=discord.ButtonStyle.danger)
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Get ticket manager
            ticket_manager = self.bot.get_cog('Tickets').ticket_manager
            
            # Get ticket
            ticket = await ticket_manager.get_ticket(self.ticket_id)
            if not ticket:
                await interaction.response.send_message("❌ Ticket not found", ephemeral=True)
                return
            
            # Check permissions
            if not ticket_manager.can_manage_ticket(interaction.user, ticket):
                await interaction.response.send_message("❌ Only ticket assignees or admins can close tickets", ephemeral=True)
                return
            
            await interaction.response.defer()
            
            # Create transcript
            transcript = await ticket_manager.create_transcript(interaction.channel)
            
            # Send transcript
            transcript_sent = await ticket_manager.send_transcript(interaction.guild, transcript, self.ticket_id, interaction.user)
            
            # Update ticket status
            await ticket_manager.update_ticket_status(self.ticket_id, 'closed')
            
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
            embed = EmbedBuilder.error("Error", f"Failed to close ticket: {str(e)}")
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except:
                await interaction.response.send_message(embed=embed, ephemeral=True)

class TicketSetupModal(discord.ui.Modal):
    """Modal for ticket system setup"""
    
    def __init__(self, bot):
        super().__init__(title="Ticket System Setup")
        self.bot = bot
        
        self.category_input = discord.ui.TextInput(
            label="Ticket Category ID",
            placeholder="Enter the category ID where ticket channels will be created",
            required=True,
            max_length=20
        )
        self.add_item(self.category_input)
        
        self.transcript_input = discord.ui.TextInput(
            label="Transcript Channel ID",
            placeholder="Enter the channel ID where transcripts will be sent",
            required=True,
            max_length=20
        )
        self.add_item(self.transcript_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Validate category
            category = interaction.guild.get_channel(int(self.category_input.value))
            if not category or not isinstance(category, discord.CategoryChannel):
                await interaction.response.send_message("❌ Invalid category ID. Please provide a valid category channel ID.", ephemeral=True)
                return
            
            # Validate transcript channel
            transcript_channel = interaction.guild.get_channel(int(self.transcript_input.value))
            if not transcript_channel or not isinstance(transcript_channel, discord.TextChannel):
                await interaction.response.send_message("❌ Invalid transcript channel ID. Please provide a valid text channel ID.", ephemeral=True)
                return
            
            # Save configuration
            ticket_manager = self.bot.get_cog('Tickets').ticket_manager
            config = {
                'category_id': str(category.id),
                'transcript_channel_id': str(transcript_channel.id),
                'setup_by': str(interaction.user.id),
                'setup_at': ticket_manager.current_timestamp()
            }
            
            success = await ticket_manager.save_ticket_config(str(interaction.guild.id), config)
            
            if success:
                embed = EmbedBuilder.success(
                    "✅ Ticket System Configured",
                    f"**Ticket Category:** {category.mention}\n"
                    f"**Transcript Channel:** {transcript_channel.mention}\n\n"
                    f"✅ **The ticket system is now ready!**\n"
                    f"Users can create tickets using `/ticket create`"
                )
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("❌ Failed to save ticket configuration. Please try again.", ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("❌ Invalid channel IDs. Please provide valid numeric channel IDs.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error setting up ticket system: {str(e)}", ephemeral=True)

class Tickets(commands.Cog):
    """Support ticket system with enhanced features"""
    
    def __init__(self, bot):
        self.bot = bot
        self.ticket_manager = TicketManager(bot)
    
    @app_commands.command(name="setup-tickets", description="Setup the ticket system (Admin only)")
    async def setup_tickets(self, interaction: discord.Interaction):
        """Setup ticket system configuration"""
        if not (hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(interaction.user)):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can setup the ticket system")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        modal = TicketSetupModal(self.bot)
        await interaction.response.send_modal(modal)
    
    @app_commands.command(name="ticket", description="Create a new support ticket")
    @app_commands.describe(
        title="Brief title for your ticket",
        description="Detailed description of your issue",
        priority="Priority level (low, medium, high)"
    )
    @app_commands.choices(priority=[
        app_commands.Choice(name="Low", value="low"),
        app_commands.Choice(name="Medium", value="medium"),
        app_commands.Choice(name="High", value="high")
    ])
    async def create_ticket(self, interaction: discord.Interaction, title: str, description: str, priority: str = "medium"):
        """Create a new support ticket"""
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
                channel = interaction.guild.get_channel(int(ticket['channel_id']))
                embed = EmbedBuilder.warning(
                    "Existing Ticket Found",
                    f"You already have an open ticket: {channel.mention if channel else 'Channel not found'}\n"
                    "Please use your existing ticket or close it before creating a new one."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Create ticket
            ticket_data = await self.ticket_manager.create_ticket(interaction.guild, interaction.user, title, description, priority)
            
            if not ticket_data:
                embed = EmbedBuilder.error("Error", "Failed to create ticket. Please check bot permissions and configuration.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Get the created channel
            channel = interaction.guild.get_channel(int(ticket_data['channel_id']))
            
            # Create ticket embed for the channel
            embed = discord.Embed(
                title=f"🎫 Support Ticket: {ticket_data['ticket_id']}",
                description=f"**Issue Description:**\n{description}",
                color=0x5865F2,
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="📋 Title", value=title, inline=False)
            embed.add_field(name="⚡ Priority", value=priority.title(), inline=True)
            embed.add_field(name="📊 Status", value="🟢 Open", inline=True)
            embed.add_field(name="👤 Created by", value=interaction.user.mention, inline=True)
            embed.add_field(name="👀 Visibility", value="🌐 **Public & Read-Only**", inline=False)
            embed.add_field(name="ℹ️ Access Info", value="• Everyone can **read** this ticket\n• Only you, assignees, and admins can **write**\n• Use `/ticket-join` to request write access", inline=False)
            embed.set_footer(text="devBot - Powered by EGOS")
            
            view = TicketCloseView(self.bot, ticket_data['ticket_id'])
            
            # Send welcome message
            await channel.send(
                f"🎫 **Welcome {interaction.user.mention}!** Your support ticket has been created.\n\n"
                f"🌐 **This ticket is PUBLIC and READ-ONLY by default:**\n"
                f"• ✅ Everyone can see and read this conversation\n"
                f"• ❌ Only you, assignees, and admins can respond\n"
                f"• 💬 Others can request to join using `/ticket-join`\n\n"
                f"📝 **You can participate** since you created this ticket.",
                embed=embed, 
                view=view
            )
            
            # Respond to user
            embed_response = EmbedBuilder.success(
                "🎫 Public Ticket Created Successfully",
                f"**Ticket ID:** `{ticket_data['ticket_id']}`\n"
                f"**Channel:** {channel.mention}\n"
                f"**Priority:** {priority.title()}\n"
                f"**Visibility:** 🌐 **Public & Read-Only**\n\n"
                f"✅ **Your ticket is now visible to everyone** in the server\n"
                f"💬 **Only you, assignees, and admins** can respond\n"
                f"🔧 **Use `/ticket-private`** if you need to make it private later"
            )
            await interaction.followup.send(embed=embed_response, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create ticket: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="ticket-join", description="Request to join a ticket conversation")
    @app_commands.describe(ticket_id="ID of the ticket to join (optional if in ticket channel)")
    async def ticket_join(self, interaction: discord.Interaction, ticket_id: Optional[str] = None):
        """Request to join a ticket conversation"""
        # Get ticket ID from channel if not provided
        if not ticket_id:
            if not interaction.channel.topic or "Support ticket:" not in interaction.channel.topic:
                embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels or with a ticket ID")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            ticket_id = interaction.channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        
        # Get ticket
        ticket = await self.ticket_manager.get_ticket(ticket_id)
        if not ticket:
            embed = EmbedBuilder.error("Not Found", f"Ticket {ticket_id} not found")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        channel = interaction.guild.get_channel(int(ticket['channel_id']))
        if not channel:
            embed = EmbedBuilder.error("Channel Not Found", f"Ticket {ticket_id} channel has been deleted")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if user already has access
        if self.ticket_manager.can_access_ticket(interaction.user, ticket):
            embed = EmbedBuilder.warning("Already Assigned", "You already have access to this ticket conversation")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create join request
        embed = discord.Embed(
            title="🎫 Ticket Join Request",
            description=f"{interaction.user.mention} wants to join this ticket conversation",
            color=0xFEE75C,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="👤 User", value=f"{interaction.user.mention}\n`{interaction.user}`", inline=True)
        embed.add_field(name="📅 Requested", value=f"<t:{int(datetime.now(timezone.utc).timestamp())}:R>", inline=True)
        embed.add_field(name="🔍 Current Access", value="👀 **Read Only**\n(Can see all messages)", inline=True)
        embed.add_field(name="📝 Requesting", value="💬 **Write Access**\n(Can participate in conversation)", inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Only ticket assignees or admins can approve • devBot - Powered by EGOS")
        
        view = TicketJoinRequestView(self.bot, interaction.user, channel)
        
        # Send request to ticket channel
        await channel.send(embed=embed, view=view)
        
        # Notify user
        response_embed = EmbedBuilder.success(
            "📤 Join Request Sent",
            f"Your request to join ticket **{ticket_id}** has been sent.\n\n"
            f"👀 **Current Access:** You can read all messages\n"
            f"⏳ **Pending:** Write access (ability to respond)\n"
            f"✅ **Approval:** Ticket assignees or admins can approve"
        )
        await interaction.response.send_message(embed=response_embed, ephemeral=True)
    
    @app_commands.command(name="ticket-private", description="Make ticket private (only assigned users can read)")
    async def ticket_private(self, interaction: discord.Interaction):
        """Make ticket private"""
        if not interaction.channel.topic or "Support ticket:" not in interaction.channel.topic:
            embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        ticket_id = interaction.channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        ticket = await self.ticket_manager.get_ticket(ticket_id)
        
        if not ticket or not self.ticket_manager.can_manage_ticket(interaction.user, ticket):
            embed = EmbedBuilder.error("Permission Denied", "Only ticket assignees or admins can change visibility")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        success = await self.ticket_manager.set_ticket_visibility(interaction.channel, private=True)
        
        if success:
            embed = EmbedBuilder.success("🔒 Ticket Set to Private", "This ticket is now **private** - only assigned users and admins can read it")
        else:
            embed = EmbedBuilder.error("Error", "Failed to set ticket visibility")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="ticket-public", description="Make ticket public (everyone can read)")
    async def ticket_public(self, interaction: discord.Interaction):
        """Make ticket public"""
        if not interaction.channel.topic or "Support ticket:" not in interaction.channel.topic:
            embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        ticket_id = interaction.channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        ticket = await self.ticket_manager.get_ticket(ticket_id)
        
        if not ticket or not self.ticket_manager.can_manage_ticket(interaction.user, ticket):
            embed = EmbedBuilder.error("Permission Denied", "Only ticket assignees or admins can change visibility")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        success = await self.ticket_manager.set_ticket_visibility(interaction.channel, private=False)
        
        if success:
            embed = EmbedBuilder.success("🌐 Ticket Set to Public", "This ticket is now **public** - everyone can read it (but only assigned users can write)")
        else:
            embed = EmbedBuilder.error("Error", "Failed to set ticket visibility")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="ticket-list", description="List tickets")
    @app_commands.describe(
        status="Filter by status (open, closed, all)",
        user="Filter by user (mention or ID)"
    )
    @app_commands.choices(status=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Open", value="open"),
        app_commands.Choice(name="Closed", value="closed")
    ])
    async def list_tickets(self, interaction: discord.Interaction, status: str = "all", user: Optional[discord.Member] = None):
        """List tickets with filters"""
        await interaction.response.defer()
        
        try:
            if user:
                if status == "all":
                    tickets = await self.ticket_manager.get_user_tickets(str(interaction.guild.id), str(user.id))
                else:
                    tickets = await self.ticket_manager.get_user_tickets(str(interaction.guild.id), str(user.id), status)
            else:
                if status == "all":
                    tickets = await self.ticket_manager.get_guild_tickets(str(interaction.guild.id))
                else:
                    tickets = await self.ticket_manager.get_guild_tickets(str(interaction.guild.id), status)
            
            if not tickets:
                embed = EmbedBuilder.info("No Tickets", "No tickets found matching your criteria")
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title="🎫 Support Tickets",
                color=0x5865F2,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text="devBot - Powered by EGOS")
            
            for ticket in tickets[:10]:  # Limit to 10 tickets
                ticket_id = ticket['ticket_id']
                user_id = ticket['user_id']
                title = ticket['title']
                ticket_status = ticket['status']
                priority = ticket['priority']
                channel_id = ticket['channel_id']
                created_at = ticket['created_at']
                
                ticket_user = interaction.guild.get_member(int(user_id))
                user_name = ticket_user.display_name if ticket_user else "Unknown"
                
                status_emoji = "🟢" if ticket_status == "open" else "🔴"
                priority_emoji = {"low": "🔵", "medium": "🟡", "high": "🔴"}.get(priority, "🟡")
                
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
                          f"**Created:** <t:{created_at}:R>",
                    inline=True
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch tickets: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="ticket-assign", description="Assign a user to a ticket (Admin only)")
    @app_commands.describe(
        ticket_id="Ticket ID to assign",
        user="User to assign to the ticket"
    )
    async def assign_ticket(self, interaction: discord.Interaction, ticket_id: str, user: discord.Member):
        """Assign a user to a ticket"""
        if not (hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(interaction.user)):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can assign tickets")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # Check if ticket exists
            ticket = await self.ticket_manager.get_ticket(ticket_id)
            if not ticket:
                embed = EmbedBuilder.error("Not Found", f"Ticket {ticket_id} not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Assign user
            success = await self.ticket_manager.assign_user_to_ticket(ticket_id, str(user.id))
            if not success:
                embed = EmbedBuilder.error("Error", "Failed to assign user to ticket")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Update channel permissions
            channel = interaction.guild.get_channel(int(ticket['channel_id']))
            if channel:
                await channel.set_permissions(user, read_messages=True, send_messages=True)
            
            embed = EmbedBuilder.success(
                "Ticket Assigned",
                f"Ticket **{ticket_id}** has been assigned to {user.mention}"
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to assign ticket: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Tickets(bot))
    print(f"🎫 Successfully loaded Tickets cog")
