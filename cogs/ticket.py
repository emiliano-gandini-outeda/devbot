import discord
from discord.ext import commands
from discord import app_commands
import uuid
from datetime import datetime
from utils.helpers import EmbedBuilder
from config.constants import TicketStatus
from utils.ticket_manager import TicketJoinRequestView
import asyncio

class TicketView(discord.ui.View):
    def __init__(self, bot, ticket_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_id = ticket_id
    
    @discord.ui.button(label="Close & Transcript", style=discord.ButtonStyle.danger, emoji="📄")
    async def close_and_transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
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
            
            if not (self.bot.admin_manager.is_admin(interaction.user) or str(interaction.user.id) == ticket_user_id):
                embed = EmbedBuilder.error("Permission Denied", "Only admins or the ticket creator can close tickets")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            await interaction.response.defer()
            
            # Create transcript
            transcript = await self.bot.ticket_manager.create_transcript(interaction.channel)
            
            # Get ticket creator
            ticket_user = interaction.guild.get_member(int(ticket_user_id))
            
            # Send transcript
            success = await self.bot.ticket_manager.send_transcript(
                interaction.guild, transcript, self.ticket_id, ticket_user or interaction.user
            )
            
            # Update ticket status
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
            
            if success:
                embed = EmbedBuilder.success(
                    "Ticket Closed", 
                    f"Ticket {self.ticket_id} has been closed and transcript saved.\n"
                    f"This channel will be deleted in 10 seconds."
                )
            else:
                embed = EmbedBuilder.warning(
                    "Ticket Closed", 
                    f"Ticket {self.ticket_id} has been closed but transcript could not be saved.\n"
                    f"This channel will be deleted in 10 seconds."
                )
            
            await interaction.followup.send(embed=embed)
            
            # Delete channel after 10 seconds
            await asyncio.sleep(10)
            try:
                await interaction.channel.delete(reason=f"Ticket {self.ticket_id} closed")
            except:
                pass
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to close ticket: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

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
        config = self.bot.ticket_manager.get_ticket_config(str(interaction.guild.id))
        if not config:
            embed = EmbedBuilder.error(
                "Ticket System Not Configured",
                "The ticket system has not been set up. Please ask an administrator to run `/setup ticket`"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        valid_priorities = ["low", "medium", "high"]
        if priority not in valid_priorities:
            priority = "medium"
        
        ticket_id = self.bot.ticket_manager.generate_ticket_id()
        
        await interaction.response.defer()
        
        try:
            # Create ticket channel
            channel = await self.bot.ticket_manager.create_ticket_channel(
                interaction.guild, ticket_id, interaction.user, title
            )
            
            if not channel:
                embed = EmbedBuilder.error("Error", "Failed to create ticket channel. Please check bot permissions.")
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
                title=f"🎫 Ticket: {ticket_id}",
                description=description,
                color=0x5865F2
            )
            embed.add_field(name="Title", value=title, inline=False)
            embed.add_field(name="Priority", value=priority.title(), inline=True)
            embed.add_field(name="Status", value="Open", inline=True)
            embed.add_field(name="Created by", value=interaction.user.mention, inline=True)
            embed.timestamp = datetime.utcnow()
            embed.set_footer(text="devBot")
            
            view = TicketView(self.bot, ticket_id)
            
            # Send initial message in ticket channel
            await channel.send(f"Welcome {interaction.user.mention}! Your ticket has been created.", embed=embed, view=view)
            
            # Respond to user
            embed_response = EmbedBuilder.success(
                "Ticket Created",
                f"Your ticket **{ticket_id}** has been created!\n"
                f"Channel: {channel.mention}\n"
                f"Priority: {priority.title()}"
            )
            await interaction.followup.send(embed=embed_response, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create ticket: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="assign", description="Assign a ticket to a user (Admin only)")
    @app_commands.describe(
        ticket_id="Ticket ID to assign",
        assignee="User to assign the ticket to"
    )
    async def assign_ticket(self, interaction: discord.Interaction, ticket_id: str, assignee: discord.Member):
        if not self.bot.admin_manager.is_admin(interaction.user):
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
        if not self.bot.admin_manager.is_admin(interaction.user):
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
            
            # Remove user permissions from ticket channel
            channel_id = ticket['channel_id'] if self.bot.db.is_postgresql else ticket[9]
            if channel_id:
                channel = interaction.guild.get_channel(int(channel_id))
                if channel:
                    await channel.set_permissions(user, overwrite=None)
            
            embed = EmbedBuilder.success(
                "Ticket Unassigned",
                f"{user.mention} has been unassigned from ticket **{ticket_id}**"
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
                color=0x5865F2
            )
            embed.set_footer(text="devBot")
            
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
                          f"**Status:** {status.title()}\n"
                          f"**Channel:** {channel_link}",
                    inline=True
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch tickets: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="join", description="Request to join a ticket")
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
        
        # Check if user already has access
        permissions = channel.permissions_for(interaction.user)
        if permissions.send_messages:
            embed = EmbedBuilder.warning("Already Joined", "You already have access to this ticket")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create join request embed
        embed = discord.Embed(
            title="🎫 Ticket Join Request",
            description=f"{interaction.user.mention} wants to join this ticket",
            color=0xFEE75C
        )
        embed.add_field(name="User", value=f"{interaction.user.mention} ({interaction.user})", inline=True)
        embed.add_field(name="Requested", value=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="devBot")
        
        view = TicketJoinRequestView(self.bot, interaction.user, channel)
        
        # Send request to ticket channel
        await channel.send(embed=embed, view=view)
        
        # Notify user
        response_embed = EmbedBuilder.success(
            "Request Sent",
            f"Your request to join ticket {ticket_id} has been sent. You'll be notified if it's accepted."
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
        if not self.bot.admin_manager.is_admin(interaction.user):
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
            embed = EmbedBuilder.success("Ticket Set to Private", "This ticket is now private - only assigned users and admins can read it")
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
        if not self.bot.admin_manager.is_admin(interaction.user):
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
            embed = EmbedBuilder.success("Ticket Set to Public", "This ticket is now public - everyone can read it (but only assigned users can write)")
        else:
            embed = EmbedBuilder.error("Error", "Failed to set ticket visibility")
        
        await interaction.response.send_message(embed=embed)

class Ticket(commands.Cog):
    """Support ticket system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.ticket_commands = TicketCommands(bot)
        self.bot.tree.add_command(self.ticket_commands)

async def setup(bot):
    cog = Ticket(bot)
    await bot.add_cog(cog)
    print(f"🎫 Successfully loaded Ticket cog")
