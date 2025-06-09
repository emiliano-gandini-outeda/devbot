import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder, generate_ticket_id
from config.constants import TicketStatus, TicketPriority
from datetime import datetime
import json
import asyncio

class TicketView(discord.ui.View):
    def __init__(self, bot, ticket_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_id = ticket_id
    
    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Check permissions
            ticket = await self.bot.db.connection.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1", self.ticket_id
            )
            
            if not ticket:
                embed = EmbedBuilder.error("Error", "Ticket not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            ticket_user_id = ticket['user_id']
            
            if not (self.bot.admin_manager.is_admin(interaction.user) or str(interaction.user.id) == ticket_user_id):
                embed = EmbedBuilder.error("Permission Denied", "Only admins or the ticket creator can close tickets")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            await interaction.response.defer()
            
            # Update ticket status
            await self.bot.db.connection.execute(
                "UPDATE tickets SET status = $1, updated_at = $2 WHERE ticket_id = $3",
                TicketStatus.CLOSED.value, datetime.utcnow(), self.ticket_id
            )
            
            embed = EmbedBuilder.success(
                "Ticket Closed", 
                f"Ticket {self.ticket_id} has been closed successfully."
            )
            
            await interaction.followup.send(embed=embed)
            
            # Delete channel after 5 seconds
            await asyncio.sleep(5)
            try:
                await interaction.channel.delete(reason=f"Ticket {self.ticket_id} closed")
            except:
                pass
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to close ticket: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

class TicketJoinRequestView(discord.ui.View):
    def __init__(self, bot, requester: discord.Member, ticket_channel: discord.TextChannel):
        super().__init__(timeout=None)
        self.bot = bot
        self.requester = requester
        self.ticket_channel = ticket_channel
    
    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Check if user is ticket creator, assignee, or admin
            if interaction.user.id == self.requester.id:
                embed = EmbedBuilder.error("Permission Denied", "You cannot approve your own join request")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Get ticket info from channel topic
            if not self.ticket_channel.topic or "Support ticket:" not in self.ticket_channel.topic:
                embed = EmbedBuilder.error("Error", "Invalid ticket channel")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            ticket_id = self.ticket_channel.topic.split("|")[0].replace("Support ticket:", "").strip()
            
            # Get ticket from database
            ticket = await self.bot.db.connection.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
            )
            
            if not ticket:
                embed = EmbedBuilder.error("Error", "Ticket not found in database")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check if user is ticket creator, assignee, or admin
            is_creator = str(interaction.user.id) == ticket['user_id']
            is_assignee = ticket['assignee_id'] and str(interaction.user.id) == ticket['assignee_id']
            is_admin = self.bot.admin_manager.is_admin(interaction.user)
            
            if not (is_creator or is_assignee or is_admin):
                embed = EmbedBuilder.error("Permission Denied", "Only ticket creator, assignee, or admins can approve join requests")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Add user to ticket channel
            await self.ticket_channel.set_permissions(self.requester, read_messages=True, send_messages=True)
            
            # Disable buttons
            for child in self.children:
                child.disabled = True
            
            await interaction.response.edit_message(view=self)
            
            # Send notification
            embed = EmbedBuilder.success(
                "Join Request Approved",
                f"{self.requester.mention} has been added to the ticket by {interaction.user.mention}"
            )
            await self.ticket_channel.send(embed=embed)
            
            # Notify requester
            try:
                user_embed = EmbedBuilder.success(
                    "Join Request Approved",
                    f"Your request to join ticket {ticket_id} has been approved.\n"
                    f"You can now access the ticket channel: {self.ticket_channel.mention}"
                )
                await self.requester.send(embed=user_embed)
            except:
                pass
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to approve join request: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Check if user is ticket creator, assignee, or admin
            if interaction.user.id == self.requester.id:
                embed = EmbedBuilder.error("Permission Denied", "You cannot deny your own join request")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Get ticket info from channel topic
            if not self.ticket_channel.topic or "Support ticket:" not in self.ticket_channel.topic:
                embed = EmbedBuilder.error("Error", "Invalid ticket channel")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            ticket_id = self.ticket_channel.topic.split("|")[0].replace("Support ticket:", "").strip()
            
            # Get ticket from database
            ticket = await self.bot.db.connection.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
            )
            
            if not ticket:
                embed = EmbedBuilder.error("Error", "Ticket not found in database")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check if user is ticket creator, assignee, or admin
            is_creator = str(interaction.user.id) == ticket['user_id']
            is_assignee = ticket['assignee_id'] and str(interaction.user.id) == ticket['assignee_id']
            is_admin = self.bot.admin_manager.is_admin(interaction.user)
            
            if not (is_creator or is_assignee or is_admin):
                embed = EmbedBuilder.error("Permission Denied", "Only ticket creator, assignee, or admins can deny join requests")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Disable buttons
            for child in self.children:
                child.disabled = True
            
            await interaction.response.edit_message(view=self)
            
            # Send notification
            embed = EmbedBuilder.error(
                "Join Request Denied",
                f"{self.requester.mention}'s request to join the ticket has been denied by {interaction.user.mention}"
            )
            await self.ticket_channel.send(embed=embed)
            
            # Notify requester
            try:
                user_embed = EmbedBuilder.error(
                    "Join Request Denied",
                    f"Your request to join ticket {ticket_id} has been denied."
                )
                await self.requester.send(embed=user_embed)
            except:
                pass
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to deny join request: {str(e)}")
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
        try:
            config_row = await self.bot.db.connection.fetchrow(
                "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                str(interaction.guild.id), 'ticket_config'
            )
            
            if not config_row:
                embed = EmbedBuilder.error(
                    "Ticket System Not Configured",
                    "The ticket system has not been set up. Please ask an administrator to run `/ticket-system-setup`"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            config = json.loads(config_row['data_content'])
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to check ticket configuration: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        valid_priorities = ["low", "medium", "high"]
        if priority not in valid_priorities:
            priority = "medium"
        
        ticket_id = generate_ticket_id()
        
        await interaction.response.defer()
        
        try:
            # Get category
            category_id = config.get('category_id')
            category = interaction.guild.get_channel(int(category_id)) if category_id else None
            
            if not category:
                embed = EmbedBuilder.error("Error", "Ticket category not found. Please reconfigure the ticket system.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Create ticket channel
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            
            channel = await category.create_text_channel(
                name=f"ticket-{ticket_id}",
                topic=f"Support ticket: {ticket_id} | Created by: {interaction.user}",
                overwrites=overwrites
            )
            
            # Create ticket in database
            await self.bot.db.connection.execute(
                """INSERT INTO tickets (ticket_id, guild_id, user_id, title, description, status, priority, channel_id, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                ticket_id, str(interaction.guild.id), str(interaction.user.id), 
                title, description, TicketStatus.OPEN.value, priority, str(channel.id), datetime.utcnow()
            )
            
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
            embed.set_footer(text="devBot - Powered by EGOS")
            
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
    
    @app_commands.command(name="private", description="Make ticket private (only assigned users can read)")
    async def ticket_private(self, interaction: discord.Interaction):
        # Check if this is a ticket channel
        if not interaction.channel.topic or "Support ticket:" not in interaction.channel.topic:
            embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get ticket ID from channel topic
        ticket_id = interaction.channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        
        # Get ticket from database
        ticket = await self.bot.db.connection.fetchrow(
            "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
        )
        
        if not ticket:
            embed = EmbedBuilder.error("Error", "Ticket not found in database")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check permissions
        is_creator = str(interaction.user.id) == ticket['user_id']
        is_assignee = ticket['assignee_id'] and str(interaction.user.id) == ticket['assignee_id']
        is_admin = self.bot.admin_manager.is_admin(interaction.user)
        
        if not (is_creator or is_assignee or is_admin):
            embed = EmbedBuilder.error("Permission Denied", "Only ticket creator, assignee, or admins can change visibility")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # Update channel permissions
            await interaction.channel.set_permissions(interaction.guild.default_role, read_messages=False)
            
            # Get ticket creator and assignee
            creator = interaction.guild.get_member(int(ticket['user_id']))
            assignee = None
            if ticket['assignee_id']:
                assignee = interaction.guild.get_member(int(ticket['assignee_id']))
            
            # Set permissions for creator and assignee
            if creator:
                await interaction.channel.set_permissions(creator, read_messages=True, send_messages=True)
            
            if assignee:
                await interaction.channel.set_permissions(assignee, read_messages=True, send_messages=True)
            
            embed = EmbedBuilder.success(
                "Ticket Set to Private",
                "This ticket is now private - only assigned users and admins can read it"
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to set ticket to private: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="public", description="Make ticket public (everyone can read)")
    async def ticket_public(self, interaction: discord.Interaction):
        # Check if this is a ticket channel
        if not interaction.channel.topic or "Support ticket:" not in interaction.channel.topic:
            embed = EmbedBuilder.error("Not a Ticket", "This command can only be used in ticket channels")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get ticket ID from channel topic
        ticket_id = interaction.channel.topic.split("|")[0].replace("Support ticket:", "").strip()
        
        # Get ticket from database
        ticket = await self.bot.db.connection.fetchrow(
            "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
        )
        
        if not ticket:
            embed = EmbedBuilder.error("Error", "Ticket not found in database")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check permissions
        is_creator = str(interaction.user.id) == ticket['user_id']
        is_assignee = ticket['assignee_id'] and str(interaction.user.id) == ticket['assignee_id']
        is_admin = self.bot.admin_manager.is_admin(interaction.user)
        
        if not (is_creator or is_assignee or is_admin):
            embed = EmbedBuilder.error("Permission Denied", "Only ticket creator, assignee, or admins can change visibility")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # Update channel permissions
            await interaction.channel.set_permissions(interaction.guild.default_role, read_messages=True, send_messages=False)
            
            # Get ticket creator and assignee
            creator = interaction.guild.get_member(int(ticket['user_id']))
            assignee = None
            if ticket['assignee_id']:
                assignee = interaction.guild.get_member(int(ticket['assignee_id']))
            
            # Set permissions for creator and assignee
            if creator:
                await interaction.channel.set_permissions(creator, read_messages=True, send_messages=True)
            
            if assignee:
                await interaction.channel.set_permissions(assignee, read_messages=True, send_messages=True)
            
            embed = EmbedBuilder.success(
                "Ticket Set to Public",
                "This ticket is now public - everyone can read it (but only assigned users can write)"
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to set ticket to public: {str(e)}")
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
        ticket = await self.bot.db.connection.fetchrow(
            "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
        )
        
        if not ticket:
            embed = EmbedBuilder.error("Not Found", f"Ticket with ID {ticket_id} not found")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get ticket channel
        channel_id = ticket['channel_id']
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
        embed.set_footer(text="devBot - Powered by EGOS")
        
        view = TicketJoinRequestView(self.bot, interaction.user, channel)
        
        # Send request to ticket channel
        await channel.send(embed=embed, view=view)
        
        # Notify user
        response_embed = EmbedBuilder.success(
            "Request Sent",
            f"Your request to join ticket {ticket_id} has been sent. You'll be notified if it's accepted."
        )
        await interaction.response.send_message(embed=response_embed, ephemeral=True)
    
    @app_commands.command(name="list", description="List all tickets")
    @app_commands.describe(
        status="Filter by status (open, closed, all)",
        user="Filter by user (mention or ID)"
    )
    async def list_tickets(self, interaction: discord.Interaction, status: str = "all", user: discord.Member = None):
        await interaction.response.defer()
        
        try:
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
            
            if not tickets:
                embed = EmbedBuilder.info("No Tickets", "No tickets found matching your criteria")
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title="🎫 Support Tickets",
                color=0x5865F2
            )
            embed.set_footer(text="devBot - Powered by EGOS")
            
            for ticket in tickets:
                ticket_id = ticket['ticket_id']
                user_id = ticket['user_id']
                title = ticket['title']
                status = ticket['status']
                priority = ticket['priority']
                channel_id = ticket['channel_id']
                
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
            result = await self.bot.db.connection.execute(
                "UPDATE tickets SET assignee_id = $1, updated_at = $2 WHERE ticket_id = $3 AND guild_id = $4",
                str(assignee.id), datetime.utcnow(), ticket_id, str(interaction.guild.id)
            )
            
            if "UPDATE 0" in str(result):
                embed = EmbedBuilder.error("Not Found", f"Ticket {ticket_id} not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Add assignee to ticket channel permissions
            ticket = await self.bot.db.connection.fetchrow(
                "SELECT channel_id FROM tickets WHERE ticket_id = $1", ticket_id
            )
            
            if ticket and ticket['channel_id']:
                channel = interaction.guild.get_channel(int(ticket['channel_id']))
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

class Tickets(commands.Cog):
    """Support ticket system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.ticket_commands = TicketCommands(bot)
        self.bot.tree.add_command(self.ticket_commands)

async def setup(bot):
    await bot.add_cog(Tickets(bot))
