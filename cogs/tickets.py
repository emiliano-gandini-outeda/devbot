import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional
import io

import discord
from discord import ButtonStyle, Interaction, SelectOption, app_commands
from discord.ext import commands
from discord.ui import Button, Select, View

# Import everything from helpers.py only
from utils.helpers import (
    EmbedBuilder,
    TicketStatus,
    TicketPriority,
    generate_ticket_id,
    get_ticket_channel,
    get_ticket_owner,
    is_support_staff,
    has_permissions,
    send_dm,
    log_to_channel,
    FieldNotFound
)

log = logging.getLogger(__name__)


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
        
        ticket = await self.bot.db.connection.fetchrow(
            "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
        )
        
        if not ticket:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return
        
        # Check if user is admin or assignee
        is_admin = self.bot.admin_manager.is_admin(interaction.user)
        assignee_id = ticket['assignee_id']
        user_id = ticket['user_id']
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
            
            # Clean up denial records since request was accepted
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "DELETE FROM user_data WHERE user_id = $1 AND guild_id = $2 AND data_type = $3 AND data_content->>'ticket_id' = $4",
                    str(self.requesting_user.id), str(interaction.guild.id), 'ticket_join_denial', ticket_id
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM user_data WHERE user_id = ? AND guild_id = ? AND data_type = ? AND json_extract(data_content, '$.ticket_id') = ?",
                    (str(self.requesting_user.id), str(interaction.guild.id), 'ticket_join_denial', ticket_id)
                )
                await self.bot.db.connection.commit()
            
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
        
        ticket = await self.bot.db.connection.fetchrow(
            "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
        )
        
        if not ticket:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return
        
        # Check if user is admin or assignee
        is_admin = self.bot.admin_manager.is_admin(interaction.user)
        assignee_id = ticket['assignee_id']
        user_id = ticket['user_id']
        is_assignee = str(interaction.user.id) == assignee_id
        is_creator = str(interaction.user.id) == user_id
        
        if not (is_admin or is_assignee or is_creator):
            await interaction.response.send_message("Only ticket assignees, creators, or admins can deny join requests!", ephemeral=True)
            return
        
        # Show modal for denial reason
        modal = DenialReasonModal(self.bot, self.requesting_user, interaction.user, ticket_id)
        await interaction.response.send_modal(modal)
        
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
        
        await interaction.edit_original_response(embed=embed, view=self)

class DenialReasonModal(discord.ui.Modal):
    def __init__(self, bot, requester: discord.Member, denier: discord.Member, ticket_id: str):
        super().__init__(title="Denial Reason")
        self.bot = bot
        self.requester = requester
        self.denier = denier
        self.ticket_id = ticket_id
        
        self.reason_input = discord.ui.TextInput(
            label="Reason for denial",
            placeholder="Please provide a reason for denying this request...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )
        self.add_item(self.reason_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Send DM to requester with denial reason
            embed = discord.Embed(
                title="❌ Ticket Join Request Denied",
                description=f"Your request to join ticket {self.ticket_id} was denied.",
                color=0xED4245
            )
            embed.add_field(name="Denied by", value=self.denier.display_name, inline=True)
            embed.add_field(name="Reason", value=self.reason_input.value, inline=False)
            embed.set_footer(text="Railway Bot")
            
            try:
                await self.requester.send(embed=embed)
                response_msg = f"Request denied and {self.requester.mention} has been notified with the reason."
            except discord.Forbidden:
                response_msg = f"Request denied but couldn't send DM to {self.requester.mention}."
            
            # Track the denial
            denial_data = {
                'ticket_id': self.ticket_id,
                'denied_at': datetime.utcnow().isoformat(),
                'denied_by': str(self.denier.id),
                'reason': self.reason_input.value
            }
            
            try:
                if self.bot.db.is_postgresql:
                    # Get current denial count
                    current_denials = await self.bot.db.connection.fetchval(
                        "SELECT COUNT(*) FROM user_data WHERE user_id = $1 AND guild_id = $2 AND data_type = $3 AND data_content->>'ticket_id' = $4",
                        str(self.requester.id), str(interaction.guild.id), 'ticket_join_denial', self.ticket_id
                    )
                    
                    # Insert new denial record
                    await self.bot.db.connection.execute(
                        """INSERT INTO user_data (user_id, guild_id, data_type, data_content)
                           VALUES ($1, $2, $3, $4)""",
                        str(self.requester.id), str(interaction.guild.id), 'ticket_join_denial', json.dumps(denial_data)
                    )
                else:
                    # Get current denial count
                    cursor = await self.bot.db.connection.execute(
                        "SELECT COUNT(*) FROM user_data WHERE user_id = ? AND guild_id = ? AND data_type = ? AND json_extract(data_content, '$.ticket_id') = ?",
                        (str(self.requester.id), str(interaction.guild.id), 'ticket_join_denial', self.ticket_id)
                    )
                    current_denials = (await cursor.fetchone())[0]
                    
                    # Insert new denial record
                    await self.bot.db.connection.execute(
                        """INSERT INTO user_data (user_id, guild_id, data_type, data_content)
                           VALUES (?, ?, ?, ?)""",
                        (str(self.requester.id), str(interaction.guild.id), 'ticket_join_denial', json.dumps(denial_data))
                    )
                    await self.bot.db.connection.commit()
                
                # Check if user has reached denial limit
                if current_denials + 1 >= 3:
                    response_msg += f"\n⚠️ {self.requester.mention} has been denied 3 times and can no longer request to join this ticket."
                    
            except Exception as e:
                print(f"Error tracking denial: {e}")
            
            embed_response = EmbedBuilder.success("Request Denied", response_msg)
            await interaction.response.send_message(embed=embed_response, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

class TicketView(discord.ui.View):
    def __init__(self, bot, ticket_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_id = ticket_id
    
    @discord.ui.button(label="Transcript & Close", style=discord.ButtonStyle.danger, emoji="📄")
    async def close_and_transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            assignee_id = ticket['assignee_id']
            
            # Check if user is admin, ticket creator, or assignee
            is_admin = self.bot.admin_manager.is_admin(interaction.user)
            is_creator = str(interaction.user.id) == ticket_user_id
            is_assignee = assignee_id and str(interaction.user.id) == assignee_id
            
            if not (is_admin or is_creator or is_assignee):
                embed = EmbedBuilder.error("Permission Denied", "Only admins, ticket creator, or assignees can close tickets")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            await interaction.response.defer()
            
            # Create transcript
            transcript = await self.create_transcript(interaction.channel)
            
            # Get ticket creator
            ticket_user = interaction.guild.get_member(int(ticket_user_id))
            
            # Send transcript
            success = await self.send_transcript(
                interaction.guild, transcript, self.ticket_id, ticket_user or interaction.user
            )
            
            # Update ticket status
            await self.bot.db.connection.execute(
                "UPDATE tickets SET status = $1, updated_at = $2 WHERE ticket_id = $3",
                TicketStatus.CLOSED.value, datetime.utcnow(), self.ticket_id
            )
            
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
            config_row = await self.bot.db.connection.fetchrow(
                "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                str(guild.id), 'ticket_config'
            )
            
            if not config_row:
                print(f"No ticket config found for guild {guild.id}")
                return False
            
            config = json.loads(config_row['data_content'])
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
            embed.set_footer(text="Railway Bot")
            
            await transcript_channel.send(embed=embed, file=transcript_file)
            print(f"Transcript sent successfully for ticket {ticket_id}")
            return True
            
        except Exception as e:
            print(f"Error sending transcript: {e}")
            return False

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
            
            # Create ticket channel with PUBLIC READ-ONLY permissions by default
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            
            # Add admin roles with write permissions
            if self.bot.admin_manager:
                admin_role_ids = self.bot.admin_manager.get_admin_roles(str(interaction.guild.id))
                for role_id in admin_role_ids:
                    role = interaction.guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
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
            embed.add_field(name="Visibility", value="🌐 Public (Read-only)", inline=True)
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
                f"Priority: {priority.title()}\n"
                f"Visibility: Public (everyone can read, only you and admins can write)"
            )
            await interaction.followup.send(embed=embed_response, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create ticket: {str(e)}")
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
        
        # Check if user has been denied too many times for this ticket
        if self.bot.db.is_postgresql:
            denial_count = await self.bot.db.connection.fetchval(
                "SELECT COUNT(*) FROM user_data WHERE user_id = $1 AND guild_id = $2 AND data_type = $3 AND data_content->>'ticket_id' = $4",
                str(interaction.user.id), str(interaction.guild.id), 'ticket_join_denial', ticket_id
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT COUNT(*) FROM user_data WHERE user_id = ? AND guild_id = ? AND data_type = ? AND json_extract(data_content, '$.ticket_id') = ?",
                (str(interaction.user.id), str(interaction.guild.id), 'ticket_join_denial', ticket_id)
            )
            denial_count = (await cursor.fetchone())[0]

        # Check if user has been denied too many times
        if denial_count >= 3:
            embed = EmbedBuilder.error(
                "Access Denied", 
                f"You have been denied access to ticket {ticket_id} too many times ({denial_count} denials). You cannot make more join requests for this ticket."
            )
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
        
        # Respond to user first to avoid timeout
        response_embed = EmbedBuilder.success(
            "Request Sent",
            f"Your request to join ticket {ticket_id} has been sent. You'll be notified if it's accepted."
        )
        await interaction.response.send_message(embed=response_embed, ephemeral=True)
        
        # Create join request embed
        embed = discord.Embed(
            title="🎫 Ticket Join Request",
            description=f"{interaction.user.mention} wants to join this ticket",
            color=0xFEE75C
        )
        embed.add_field(name="User", value=f"{interaction.user.mention} ({interaction.user})", inline=True)
        embed.add_field(name="Requested", value=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), inline=True)
        if denial_count > 0:
            embed.add_field(name="Previous Denials", value=f"{denial_count}/3", inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Railway Bot")
        
        view = TicketJoinRequestView(self.bot, interaction.user, channel)
        
        # Send request to ticket channel
        await channel.send(embed=embed, view=view)
    
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
            
            ticket = await self.bot.db.connection.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
            )
            
            if not ticket:
                embed = EmbedBuilder.error("Error", "Ticket not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            user_id = ticket['user_id']
            assignee_id = ticket['assignee_id']
            
            if str(interaction.user.id) not in [user_id, assignee_id]:
                embed = EmbedBuilder.error("Permission Denied", "Only ticket creator, assignee, or admins can change visibility")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        
        success = await self.set_ticket_visibility(interaction.channel, private=True)
        
        if success:
            embed = EmbedBuilder.success("Ticket Set to Private", "🔒 This ticket is now private - only assigned users and admins can read it")
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
            
            ticket = await self.bot.db.connection.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
            )
            
            if not ticket:
                embed = EmbedBuilder.error("Error", "Ticket not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            user_id = ticket['user_id']
            assignee_id = ticket['assignee_id']
            
            if str(interaction.user.id) not in [user_id, assignee_id]:
                embed = EmbedBuilder.error("Permission Denied", "Only ticket creator, assignee, or admins can change visibility")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        
        success = await self.set_ticket_visibility(interaction.channel, private=False)
        
        if success:
            embed = EmbedBuilder.success("Ticket Set to Public", "🌐 This ticket is now public - everyone can read it (but only assigned users can write)")
        else:
            embed = EmbedBuilder.error("Error", "Failed to set ticket visibility")
        
        await interaction.response.send_message(embed=embed)
    
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
                
                ticket = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
                )
                
                if ticket:
                    # Creator permissions
                    user_id = ticket['user_id']
                    creator = guild.get_member(int(user_id))
                    if creator:
                        overwrites[creator] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                    
                    # Assignee permissions
                    assignee_id = ticket['assignee_id']
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
