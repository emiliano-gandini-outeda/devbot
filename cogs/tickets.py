import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder, generate_ticket_id
from config.constants import TicketStatus, TicketPriority
from datetime import datetime
import json

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
            import asyncio
            await asyncio.sleep(5)
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
            embed.set_footer(text="Railway Bot")
            
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
            embed.set_footer(text="Railway Bot")
            
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
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
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
