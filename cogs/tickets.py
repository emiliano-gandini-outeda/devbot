import discord
from discord.ext import commands
from discord import app_commands
import uuid
from datetime import datetime
from utils.helpers import EmbedBuilder
from config.constants import TicketStatus

class TicketView(discord.ui.View):
    def __init__(self, bot, ticket_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_id = ticket_id
    
    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            
            embed = EmbedBuilder.success("Ticket Closed", f"Ticket {self.ticket_id} has been closed")
            await interaction.response.send_message(embed=embed)
            
            # Disable all buttons
            for item in self.children:
                item.disabled = True
            await interaction.edit_original_response(view=self)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to close ticket: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

class Tickets(commands.Cog):
    """Support ticket system"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="create-ticket", description="Create a new support ticket")
    @app_commands.describe(
        title="Ticket title",
        description="Detailed description of the issue",
        priority="Ticket priority (low, medium, high)"
    )
    async def create_ticket(self, interaction: discord.Interaction, title: str, description: str, priority: str = "medium"):
        valid_priorities = ["low", "medium", "high"]
        if priority not in valid_priorities:
            priority = "medium"
        
        ticket_id = f"TICKET-{str(uuid.uuid4())[:8].upper()}"
        
        try:
            # Create ticket in database (adapted for PostgreSQL/SQLite)
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO tickets (ticket_id, guild_id, user_id, title, description, status, priority, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    ticket_id, str(interaction.guild.id), str(interaction.user.id), 
                    title, description, TicketStatus.OPEN.value, priority, datetime.utcnow()
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT INTO tickets (ticket_id, guild_id, user_id, title, description, status, priority, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ticket_id, str(interaction.guild.id), str(interaction.user.id), 
                     title, description, TicketStatus.OPEN.value, priority, datetime.utcnow())
                )
                await self.bot.db.connection.commit()
            
            # Create ticket embed
            embed = discord.Embed(
                title=f"🎫 New Ticket: {ticket_id}",
                description=description,
                color=0x5865F2
            )
            embed.add_field(name="Title", value=title, inline=False)
            embed.add_field(name="Priority", value=priority.title(), inline=True)
            embed.add_field(name="Status", value="Open", inline=True)
            embed.add_field(name="Created by", value=interaction.user.mention, inline=True)
            embed.timestamp = datetime.utcnow()
            embed.set_footer(text="Powered by Railway 🚄")
            
            view = TicketView(self.bot, ticket_id)
            
            await interaction.response.send_message(embed=embed, view=view)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create ticket: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-tickets", description="List all tickets")
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
            
            for ticket in tickets:
                if self.bot.db.is_postgresql:
                    ticket_id = ticket['ticket_id']
                    user_id = ticket['user_id']
                    title = ticket['title']
                    status = ticket['status']
                    priority = ticket['priority']
                else:
                    ticket_id = ticket[1]
                    user_id = ticket[3]
                    title = ticket[5]
                    status = ticket[7]
                    priority = ticket[8]
                
                ticket_user = interaction.guild.get_member(int(user_id))
                user_name = ticket_user.display_name if ticket_user else "Unknown"
                
                status_emoji = "🟢" if status == "open" else "🔴"
                priority_emoji = {"low": "🔵", "medium": "🟡", "high": "🔴"}.get(priority, "🟡")
                
                embed.add_field(
                    name=f"{status_emoji} {ticket_id}",
                    value=f"**Title:** {title}\n"
                          f"**User:** {user_name}\n"
                          f"**Priority:** {priority_emoji} {priority.title()}\n"
                          f"**Status:** {status.title()}",
                    inline=True
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch tickets: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="assign-ticket", description="Assign a ticket to a user")
    @app_commands.describe(
        ticket_id="Ticket ID to assign",
        assignee="User to assign the ticket to"
    )
    async def assign_ticket(self, interaction: discord.Interaction, ticket_id: str, assignee: discord.Member):
        try:
            if self.bot.db.is_postgresql:
                result = await self.bot.db.connection.execute(
                    "UPDATE tickets SET assignee_id = $1, updated_at = $2 WHERE ticket_id = $3 AND guild_id = $4",
                    str(assignee.id), datetime.utcnow(), ticket_id, str(interaction.guild.id)
                )
                # PostgreSQL returns command tag, check if any rows were affected
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
            
            embed = EmbedBuilder.success(
                "Ticket Assigned",
                f"Ticket **{ticket_id}** has been assigned to {assignee.mention}"
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to assign ticket: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Tickets(bot))
