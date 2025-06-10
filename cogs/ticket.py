import discord
from discord.ext import commands
from discord import app_commands
import uuid
from datetime import datetime
from utils.helpers import EmbedBuilder
from config.constants import TicketStatus
from utils.ticket_manager import TicketJoinRequestView
import asyncio
from typing import Optional

class TicketView(discord.ui.View):
    def __init__(self, bot, ticket_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_id = ticket_id
    
    @discord.ui.button(label="Transcribe and Close", style=discord.ButtonStyle.danger, emoji="📄")
    async def transcribe_and_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            print(f"🎫 Starting ticket closure process for {self.ticket_id}")
            
            # Check if user is admin or ticket creator
            if self.bot.db.is_postgresql:
                ticket = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM tickets WHERE ticket_id = $1", self.ticket_id
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM tickets WHERE ticket_id = ?", (self.ticket_id,)
                )
                ticket = await cursor.fetchone()
            
            if not ticket:
                embed = EmbedBuilder.error("Error", "Ticket not found in database")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            ticket_user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[3]
            
            # Check permissions
            is_admin = hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(interaction.user)
            is_creator = str(interaction.user.id) == ticket_user_id
            
            if not (is_admin or is_creator):
                embed = EmbedBuilder.error("Permission Denied", "Only admins or the ticket creator can close tickets")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            await interaction.response.defer()
            
            print(f"📝 Creating transcript for ticket {self.ticket_id}")
            
            # Create transcript
            transcript = await self.bot.ticket_manager.create_transcript(interaction.channel)
            
            # Get ticket creator
            ticket_user = interaction.guild.get_member(int(ticket_user_id))
            
            print(f"📤 Sending transcript for ticket {self.ticket_id}")
            
            # Send transcript
            success = await self.bot.ticket_manager.send_transcript(
                interaction.guild, transcript, self.ticket_id, ticket_user or interaction.user
            )
            
            # Update ticket status in database
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
                
                print(f"✅ Updated ticket {self.ticket_id} status to closed")
                
            except Exception as db_error:
                print(f"⚠️ Database update error: {db_error}")
            
            # Send closure message
            if success:
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
            
            print(f"⏰ Waiting 10 seconds before deleting channel for ticket {self.ticket_id}")
            
            # Delete channel after 10 seconds
            await asyncio.sleep(10)
            try:
                await interaction.channel.delete(reason=f"Ticket {self.ticket_id} closed and transcribed")
                print(f"🗑️ Deleted channel for ticket {self.ticket_id}")
            except Exception as delete_error:
                print(f"⚠️ Could not delete channel: {delete_error}")
            
        except Exception as e:
            print(f"❌ Error in ticket closure: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to close ticket: {str(e)}")
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except:
                await interaction.response.send_message(embed=embed, ephemeral=True)

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
        # Check if ticket system is configured
        config = await self.bot.ticket_manager.get_ticket_config(str(interaction.guild.id))
        if not config:
            embed = EmbedBuilder.error(
                "Ticket System Not Configured",
                "The ticket system has not been set up. Please ask an administrator to run `/ticket-system-setup`"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        valid_priorities = ["low", "medium", "high"]
        if priority not in valid_priorities:
            priority = "medium"
        
        ticket_id = self.bot.ticket_manager.generate_ticket_id()
        
        await interaction.response.defer()
        
        try:
            print(f"🎫 Creating PUBLIC READ-ONLY ticket {ticket_id}")
            
            # Create ticket channel (PUBLIC AND READ-ONLY BY DEFAULT)
            channel = await self.bot.ticket_manager.create_ticket_channel(
                interaction.guild, ticket_id, interaction.user, title
            )
            
            if not channel:
                embed = EmbedBuilder.error("Error", "Failed to create ticket channel. Please check bot permissions and ticket system configuration.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Create ticket in database
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO tickets (ticket_id, guild_id, user_id, title, description, status, priority, channel_id, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                    ticket_id, str(interaction.guild.id), str(interaction.user.id), 
                    title, description, TicketStatus.OPEN.value, priority, str(channel.id), datetime.utcnow()
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT INTO tickets (ticket_id, guild_id, user_id, title, description, status, priority, channel_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ticket_id, str(interaction.guild.id), str(interaction.user.id), 
                     title, description, TicketStatus.OPEN.value, priority, str(channel.id), datetime.utcnow())
                )
                await self.bot.db.connection.commit()
            
            # Create ticket embed for the channel
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
            
            view = TicketView(self.bot, ticket_id)
            
            # Send initial message in ticket channel
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
            
            print(f"✅ Created PUBLIC READ-ONLY ticket {ticket_id} in {channel.name}")
            
        except Exception as e:
            print(f"❌ Error creating ticket: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to create ticket: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="assign", description="Assign a ticket to a user (Admin only)")
    @app_commands.describe(
        ticket_id="Ticket ID to assign",
        assignee="User to assign the ticket to"
    )
    async def assign_ticket(self, interaction: discord.Interaction, ticket_id: str, assignee: discord.Member):
        if not (hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(interaction.user)):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can assign tickets")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
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
            
            # Add assignee to ticket channel permissions
            if self.bot.db.is_postgresql:
                ticket = await self.bot.db.connection.fetchrow(
                    "SELECT channel_id FROM tickets WHERE ticket_id = $1", ticket_id
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT channel_id FROM tickets WHERE ticket_id = ?", (ticket_id,)
                )
                ticket = await cursor.fetchone()
            
            if ticket:
                channel_id = ticket['channel_id'] if self.bot.db.is_postgresql else ticket[0]
                channel = interaction.guild.get_channel(int(channel_id))
                if channel:
                    await channel.set_permissions(assignee, read_messages=True, send_messages=True)
            
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
        if not (hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(interaction.user)):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can unassign tickets")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # Get ticket info
            if self.bot.db.is_postgresql:
                ticket = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM tickets WHERE ticket_id = $1 AND guild_id = $2",
                    ticket_id, str(interaction.guild.id)
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM tickets WHERE ticket_id = ? AND guild_id = ?",
                    (ticket_id, str(interaction.guild.id))
                )
                ticket = await cursor.fetchone()
            
            if not ticket:
                embed = EmbedBuilder.error("Not Found", f"Ticket {ticket_id} not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check if user is assigned to this ticket
            assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[4]
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
            channel_id = ticket['channel_id'] if self.bot.db.is_postgresql else ticket[9]
            if channel_id:
                channel = interaction.guild.get_channel(int(channel_id))
                if channel:
                    # Reset to default public read-only permissions
                    await channel.set_permissions(user, read_messages=True, send_messages=False)
            
            embed = EmbedBuilder.success(
                "Ticket Unassigned",
                f"{user.mention} has been unassigned from ticket **{ticket_id}**\n"
                f"They can still read the ticket (public access) but can no longer write."
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to unassign ticket: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list", description="List all tickets")
    @app_commands.describe(
        status="Filter by status (open, closed, all)",
        user="Filter by user (mention or ID)"
    )
    async def list_tickets(self, interaction: discord.Interaction, status: str = "all", user: discord.Member = None):
        await interaction.response.defer()
        
        try:
            # Build query based on database type
            if self.bot.db.is_postgresql:
                query = "SELECT * FROM tickets WHERE guild_id = $1"
                params = [str(interaction.guild.id)]
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
                tickets = await self.bot.db.connection.fetch(query, *params)
            else:
                query = "SELECT * FROM tickets WHERE guild_id = ?"
                params = [str(interaction.guild.id)]
                
                if status != "all":
                    query += " AND status = ?"
                    params.append(status)
                
                if user:
                    query += " AND user_id = ?"
                    params.append(str(user.id))
                
                query += " ORDER BY created_at DESC LIMIT 10"
                
                cursor = await self.bot.db.connection.execute(query, params)
                tickets = await cursor.fetchall()
            
            if not tickets:
                embed = EmbedBuilder.info("No Tickets", "No tickets found matching your criteria")
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title="🎫 Support Tickets",
                description="📋 Recent tickets (showing up to 10)",
                color=0x5865F2
            )
            embed.set_footer(text="devBot - Powered by EGOS")
            
            for ticket in tickets:
                if self.bot.db.is_postgresql:
                    ticket_id = ticket['ticket_id']
                    user_id = ticket['user_id']
                    title = ticket['title']
                    status = ticket['status']
                    priority = ticket['priority']
                    channel_id = ticket['channel_id']
                else:
                    ticket_id = ticket[1]
                    user_id = ticket[3]
                    title = ticket[5]
                    status = ticket[7]
                    priority = ticket[8]
                    channel_id = ticket[9]
                
                ticket_user = interaction.guild.get_member(int(user_id))
                user_name = ticket_user.display_name if ticket_user else "Unknown"
                
                status_emoji = "🟢" if status == "open" else "🔴"
                priority_emoji = {"low": "🔵", "medium": "🟡", "high": "🔴"}.get(priority, "🟡")
                
                # Create channel link if channel exists
                channel_link = "❌ Channel Deleted"
                if channel_id:
                    channel = interaction.guild.get_channel(int(channel_id))
                    if channel:
                        channel_link = f"[#{channel.name}]({channel.jump_url})"
                
                embed.add_field(
                    name=f"{status_emoji} {ticket_id}",
                    value=f"**Title:** {title}\n"
                          f"**User:** {user_name}\n"
                          f"**Priority:** {priority_emoji} {priority.title()}\n"
                          f"**Status:** {status.title()}\n"
                          f"**Channel:** {channel_link}",
                    inline=True
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch tickets: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="join", description="Request to join a ticket conversation")
    @app_commands.describe(ticket_id="ID of the ticket to join (optional, not needed if in ticket channel)")
    async def ticket_join(self, interaction: discord.Interaction, ticket_id: str = None):
        # If no ticket ID provided, check if we're in a ticket channel
        if not ticket_id:
            if not interaction.channel.topic or "Support ticket:" not in interaction.channel.topic:
                embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels or with a ticket ID")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Extract ticket ID from channel topic
            ticket_id = interaction.channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        
        # Get ticket information
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
            embed = EmbedBuilder.error("Not Found", f"Ticket with ID {ticket_id} not found")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get ticket channel
        channel_id = ticket['channel_id'] if self.bot.db.is_postgresql else ticket[9]
        if not channel_id:
            embed = EmbedBuilder.error("Channel Not Found", "The ticket channel no longer exists")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        channel = interaction.guild.get_channel(int(channel_id))
        if not channel:
            embed = EmbedBuilder.error("Channel Not Found", "The ticket channel no longer exists")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if user already has write access
        permissions = channel.permissions_for(interaction.user)
        if permissions.send_messages:
            embed = EmbedBuilder.warning("Already Joined", "You already have write access to this ticket conversation")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create join request embed
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
        # Check if this is a ticket channel
        if not interaction.channel.topic or "Support ticket:" not in interaction.channel.topic:
            embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check permissions
        is_admin = hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(interaction.user)
        
        if not is_admin:
            # Check if user is ticket creator or assignee
            ticket_id = interaction.channel.topic.split("|")[0].replace("Support ticket: ", "").strip()
            
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
                embed = EmbedBuilder.error("Error", "Ticket not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[3]
            assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[4]
            
            if str(interaction.user.id) not in [user_id, assignee_id]:
                embed = EmbedBuilder.error("Permission Denied", "Only ticket creator, assignee, or admins can change visibility")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        
        success = await self.bot.ticket_manager.set_ticket_visibility(interaction.channel, private=True)
        
        if success:
            embed = EmbedBuilder.success("🔒 Ticket Set to Private", "This ticket is now **private** - only assigned users and admins can read it")
        else:
            embed = EmbedBuilder.error("Error", "Failed to set ticket visibility")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="public", description="Make ticket public (everyone can read)")
    async def ticket_public(self, interaction: discord.Interaction):
        # Check if this is a ticket channel
        if not interaction.channel.topic or "Support ticket:" not in interaction.channel.topic:
            embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check permissions (same as ticket-private)
        is_admin = hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(interaction.user)
        
        if not is_admin:
            ticket_id = interaction.channel.topic.split("|")[0].replace("Support ticket: ", "").strip()
            
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
                embed = EmbedBuilder.error("Error", "Ticket not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[3]
            assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[4]
            
            if str(interaction.user.id) not in [user_id, assignee_id]:
                embed = EmbedBuilder.error("Permission Denied", "Only ticket creator, assignee, or admins can change visibility")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        
        success = await self.bot.ticket_manager.set_ticket_visibility(interaction.channel, private=False)
        
        if success:
            embed = EmbedBuilder.success("🌐 Ticket Set to Public", "This ticket is now **public** - everyone can read it (but only assigned users can write)")
        else:
            embed = EmbedBuilder.error("Error", "Failed to set ticket visibility")
        
        await interaction.response.send_message(embed=embed)

class Ticket(commands.Cog):
    """Support ticket system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.ticket_commands = TicketCommands(bot)
    
    async def cog_load(self):
        # Add the ticket commands group to the command tree
        self.bot.tree.add_command(self.ticket_commands)

async def setup(bot):
    cog = Ticket(bot)
    await bot.add_cog(cog)
    
    # Ensure all commands are properly registered
    # The ticket commands are registered in cog_load
    
    # Print success message with command count
    command_count = len(cog.ticket_commands.commands)
    print(f"🎫 Successfully loaded Ticket cog with {command_count} commands")
