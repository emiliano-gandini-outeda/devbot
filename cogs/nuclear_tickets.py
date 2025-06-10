"""
NUCLEAR TICKET SYSTEM: Complete rebuild with setup command
Zero datetime objects, Unix timestamps only
"""
import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
from utils.nuclear_ticket_manager import NuclearTicketManager
from utils.timestamp_utils import (
    now_timestamp, timestamp_to_datetime, format_timestamp_for_discord,
    get_relative_timestamp
)
import asyncio
import logging

logger = logging.getLogger(__name__)

class TicketCloseView(discord.ui.View):
    """View for closing tickets"""
    
    def __init__(self, bot, ticket_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_id = ticket_id
    
    @discord.ui.button(label="Close & Transcript", style=discord.ButtonStyle.danger, emoji="📄")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer()
            
            # Get ticket manager
            ticket_manager = self.bot.get_cog('NuclearTickets').ticket_manager
            
            # Create transcript
            transcript = await ticket_manager.create_transcript(interaction.channel)
            
            # Update status
            await ticket_manager.update_ticket_status(self.ticket_id, "closed")
            
            # Send transcript
            transcript_sent = await ticket_manager.send_transcript(
                interaction.guild, transcript, self.ticket_id, interaction.user
            )
            
            # Send closure message
            if transcript_sent:
                embed = EmbedBuilder.success(
                    "🎫 Ticket Closed",
                    f"Ticket {self.ticket_id} has been closed and transcript saved.\n"
                    f"This channel will be deleted in 10 seconds."
                )
            else:
                embed = EmbedBuilder.warning(
                    "⚠️ Ticket Closed",
                    f"Ticket {self.ticket_id} has been closed.\n"
                    f"Warning: Transcript could not be saved.\n"
                    f"This channel will be deleted in 10 seconds."
                )
            
            await interaction.followup.send(embed=embed)
            
            # Delete channel
            await asyncio.sleep(10)
            try:
                await interaction.channel.delete(reason=f"Ticket {self.ticket_id} closed")
            except Exception as e:
                logger.error(f"Could not delete channel: {e}")
            
        except Exception as e:
            logger.error(f"Error closing ticket: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to close ticket: {str(e)}")
            try:
                await interaction.followup.send(embed=embed)
            except:
                await interaction.response.send_message(embed=embed, ephemeral=True)

class TicketJoinView(discord.ui.View):
    """View for joining tickets"""
    
    def __init__(self, bot, requesting_user: discord.Member, channel: discord.TextChannel):
        super().__init__(timeout=300)
        self.bot = bot
        self.requesting_user = requesting_user
        self.channel = channel
    
    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Grant write permissions
            await self.channel.set_permissions(
                self.requesting_user, 
                read_messages=True, 
                send_messages=True
            )
            
            # Update embed
            embed = discord.Embed(
                title="✅ Join Request Approved",
                description=f"{self.requesting_user.mention} can now participate in this ticket",
                color=0x57F287,
                timestamp=timestamp_to_datetime(now_timestamp())
            )
            
            # Disable buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
            # Welcome message
            await self.channel.send(f"🎉 {self.requesting_user.mention} Welcome to the ticket!")
            
        except Exception as e:
            logger.error(f"Error approving join: {e}")
            await interaction.response.send_message("❌ Failed to approve join request", ephemeral=True)
    
    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Update embed
            embed = discord.Embed(
                title="❌ Join Request Denied",
                description=f"{self.requesting_user.mention}'s request was denied",
                color=0xED4245,
                timestamp=timestamp_to_datetime(now_timestamp())
            )
            
            # Disable buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
        except Exception as e:
            logger.error(f"Error denying join: {e}")
            await interaction.response.send_message("❌ Failed to deny join request", ephemeral=True)

class NuclearTickets(commands.Cog):
    """Nuclear ticket system with complete setup"""
    
    def __init__(self, bot):
        self.bot = bot
        self.ticket_manager = NuclearTicketManager(bot)
        logger.info("🚀 Nuclear Tickets cog loaded")
    
    @app_commands.command(name="setup-tickets", description="Setup the ticket system (Admin only)")
    @app_commands.describe(
        category="Category where ticket channels will be created",
        transcript_channel="Channel where ticket transcripts will be sent",
        support_role="Role that can manage tickets (optional)"
    )
    async def setup_tickets(self, interaction: discord.Interaction, 
                          category: discord.CategoryChannel, 
                          transcript_channel: discord.TextChannel,
                          support_role: discord.Role = None):
        """Setup ticket system for the guild"""
        
        # Check permissions
        if not interaction.user.guild_permissions.manage_guild:
            embed = EmbedBuilder.error("Permission Denied", "You need `Manage Server` permission to setup tickets")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # Check bot permissions
            bot_perms = category.permissions_for(interaction.guild.me)
            if not (bot_perms.manage_channels and bot_perms.send_messages):
                embed = EmbedBuilder.error(
                    "Missing Permissions",
                    f"I need `Manage Channels` and `Send Messages` permissions in {category.mention}"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            transcript_perms = transcript_channel.permissions_for(interaction.guild.me)
            if not (transcript_perms.send_messages and transcript_perms.attach_files):
                embed = EmbedBuilder.error(
                    "Missing Permissions", 
                    f"I need `Send Messages` and `Attach Files` permissions in {transcript_channel.mention}"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Save configuration
            success = await self.ticket_manager.save_ticket_config(
                str(interaction.guild.id),
                str(category.id),
                str(transcript_channel.id),
                str(support_role.id) if support_role else None
            )
            
            if not success:
                embed = EmbedBuilder.error("Setup Failed", "Failed to save ticket configuration")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Success message
            embed = discord.Embed(
                title="✅ Ticket System Setup Complete",
                description="The ticket system has been successfully configured!",
                color=0x57F287,
                timestamp=timestamp_to_datetime(now_timestamp())
            )
            
            embed.add_field(name="📁 Ticket Category", value=category.mention, inline=True)
            embed.add_field(name="📄 Transcript Channel", value=transcript_channel.mention, inline=True)
            
            if support_role:
                embed.add_field(name="👥 Support Role", value=support_role.mention, inline=True)
            
            embed.add_field(
                name="🎫 Ready to Use",
                value="Users can now create tickets with `/ticket create`",
                inline=False
            )
            
            embed.set_footer(text="Nuclear Ticket System - Powered by EGOS")
            
            await interaction.followup.send(embed=embed)
            
            # Send test message to transcript channel
            test_embed = discord.Embed(
                title="🔧 Ticket System Activated",
                description="Ticket transcripts will be sent to this channel",
                color=0x5865F2,
                timestamp=timestamp_to_datetime(now_timestamp())
            )
            test_embed.add_field(name="Setup by", value=interaction.user.mention, inline=True)
            
            await transcript_channel.send(embed=test_embed)
            
        except Exception as e:
            logger.error(f"Error setting up tickets: {e}")
            embed = EmbedBuilder.error("Setup Error", f"Failed to setup ticket system: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="ticket", description="Create a new support ticket")
    @app_commands.describe(
        title="Brief title for your ticket",
        description="Detailed description of your issue",
        priority="Priority level of your ticket"
    )
    @app_commands.choices(priority=[
        app_commands.Choice(name="Low", value="low"),
        app_commands.Choice(name="Medium", value="medium"),
        app_commands.Choice(name="High", value="high"),
        app_commands.Choice(name="Critical", value="critical")
    ])
    async def create_ticket(self, interaction: discord.Interaction, 
                          title: str, description: str, priority: str = "medium"):
        """Create a new support ticket"""
        
        # Check if ticket system is setup
        if not await self.ticket_manager.is_ticket_system_setup(str(interaction.guild.id)):
            embed = EmbedBuilder.error(
                "Ticket System Not Setup",
                "The ticket system has not been configured for this server.\n\n"
                "Ask an administrator to run `/setup-tickets` first."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # Check for existing open tickets
            existing_tickets = await self.ticket_manager.get_user_tickets(
                str(interaction.guild.id), str(interaction.user.id), "open"
            )
            
            if existing_tickets:
                ticket = existing_tickets[0]
                embed = EmbedBuilder.warning(
                    "Existing Ticket Found",
                    f"You already have an open ticket: <#{ticket['channel_id']}>\n"
                    "Please use your existing ticket or close it first."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Generate ticket ID
            ticket_id = self.ticket_manager.generate_ticket_id()
            
            # Create channel
            channel = await self.ticket_manager.create_ticket_channel(
                interaction.guild, ticket_id, interaction.user, title
            )
            
            if not channel:
                embed = EmbedBuilder.error("Error", "Failed to create ticket channel")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Save to database
            await self.ticket_manager.save_ticket_to_database(
                ticket_id, str(interaction.guild.id), str(interaction.user.id),
                title, description, priority, str(channel.id)
            )
            
            # Create ticket embed
            current_timestamp = now_timestamp()
            embed = discord.Embed(
                title=f"🎫 Support Ticket: {ticket_id}",
                description=f"**Issue:** {description}",
                color=0x5865F2,
                timestamp=timestamp_to_datetime(current_timestamp)
            )
            
            embed.add_field(name="📋 Title", value=title, inline=False)
            embed.add_field(name="⚡ Priority", value=priority.title(), inline=True)
            embed.add_field(name="📊 Status", value="🟢 Open", inline=True)
            embed.add_field(name="👤 Created by", value=interaction.user.mention, inline=True)
            embed.add_field(
                name="👀 Visibility", 
                value="🌐 **Public** - Everyone can read, only assigned users can write", 
                inline=False
            )
            
            embed.set_footer(text="Nuclear Ticket System - Powered by EGOS")
            
            # Create close view
            view = TicketCloseView(self.bot, ticket_id)
            
            # Send welcome message
            await channel.send(
                f"🎫 **Welcome {interaction.user.mention}!**\n\n"
                f"Your support ticket has been created. This ticket is **public** - "
                f"everyone can read the conversation, but only you and support staff can respond.\n\n"
                f"**Ticket ID:** `{ticket_id}`\n"
                f"**Priority:** {priority.title()}",
                embed=embed,
                view=view
            )
            
            # Response to user
            response_embed = EmbedBuilder.success(
                "🎫 Ticket Created",
                f"**Ticket ID:** `{ticket_id}`\n"
                f"**Channel:** {channel.mention}\n"
                f"**Priority:** {priority.title()}\n\n"
                f"Your ticket is now **public** and visible to everyone in the server."
            )
            
            await interaction.followup.send(embed=response_embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error creating ticket: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to create ticket: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="ticket-join", description="Request to join a ticket conversation")
    async def ticket_join(self, interaction: discord.Interaction):
        """Request to join the current ticket"""
        
        # Check if in ticket channel
        if not interaction.channel.topic or "Support ticket:" not in interaction.channel.topic:
            embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if user already has write access
        perms = interaction.channel.permissions_for(interaction.user)
        if perms.send_messages:
            embed = EmbedBuilder.warning("Already Joined", "You already have write access to this ticket")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create join request
        current_timestamp = now_timestamp()
        embed = discord.Embed(
            title="🎫 Ticket Join Request",
            description=f"{interaction.user.mention} wants to join this ticket conversation",
            color=0xFEE75C,
            timestamp=timestamp_to_datetime(current_timestamp)
        )
        
        embed.add_field(name="👤 User", value=interaction.user.mention, inline=True)
        embed.add_field(name="📅 Requested", value=format_timestamp_for_discord(current_timestamp), inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Only ticket creator, assignees, or admins can approve")
        
        view = TicketJoinView(self.bot, interaction.user, interaction.channel)
        
        await interaction.channel.send(embed=embed, view=view)
        
        # Response to user
        response_embed = EmbedBuilder.success(
            "📤 Join Request Sent",
            f"Your request to join this ticket has been sent.\n"
            f"You can currently **read** all messages.\n"
            f"Waiting for approval to **write** messages."
        )
        await interaction.response.send_message(embed=response_embed, ephemeral=True)
    
    @app_commands.command(name="ticket-list", description="List your tickets")
    @app_commands.describe(status="Filter by ticket status")
    @app_commands.choices(status=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Open", value="open"),
        app_commands.Choice(name="Closed", value="closed")
    ])
    async def list_tickets(self, interaction: discord.Interaction, status: str = "all"):
        """List user's tickets"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get tickets
            if status == "all":
                tickets = await self.ticket_manager.get_user_tickets(
                    str(interaction.guild.id), str(interaction.user.id)
                )
            else:
                tickets = await self.ticket_manager.get_user_tickets(
                    str(interaction.guild.id), str(interaction.user.id), status
                )
            
            if not tickets:
                embed = EmbedBuilder.info("No Tickets", f"You have no {status} tickets")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Create embed
            embed = discord.Embed(
                title=f"🎫 Your {status.title()} Tickets",
                color=0x5865F2,
                timestamp=timestamp_to_datetime(now_timestamp())
            )
            
            for ticket in tickets[:10]:  # Limit to 10
                ticket_id = ticket['ticket_id']
                title = ticket['title']
                ticket_status = ticket['status']
                priority = ticket['priority']
                channel_id = ticket['channel_id']
                created_at = ticket['created_at']
                
                status_emoji = "🟢" if ticket_status == "open" else "🔴"
                priority_emoji = {"low": "🔵", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(priority, "🟡")
                
                # Check if channel exists
                channel = interaction.guild.get_channel(int(channel_id)) if channel_id else None
                channel_link = channel.mention if channel else "Channel Deleted"
                
                embed.add_field(
                    name=f"{status_emoji} {ticket_id}",
                    value=f"**Title:** {title}\n"
                          f"**Priority:** {priority_emoji} {priority.title()}\n"
                          f"**Status:** {ticket_status.title()}\n"
                          f"**Channel:** {channel_link}\n"
                          f"**Created:** {get_relative_timestamp(created_at)}",
                    inline=True
                )
            
            embed.set_footer(text="Nuclear Ticket System - Powered by EGOS")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error listing tickets: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to list tickets: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    """Setup the nuclear tickets cog"""
    await bot.add_cog(NuclearTickets(bot))
    logger.info("✅ Nuclear Tickets cog loaded successfully")
