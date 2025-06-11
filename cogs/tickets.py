import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

import discord
from discord import ButtonStyle, Interaction, SelectOption, app_commands
from discord.app_commands import Choice
from discord.ext import commands, tasks
from discord.ui import Button, Select, View

# from cogs.utils.embed_builder import EmbedBuilder  # Assuming this is in utils
# from cogs.utils.views import ConfirmView  # Assuming this is in utils

# Assuming EmbedBuilder and ConfirmView are defined elsewhere or imported correctly
# For demonstration purposes, let's define them as placeholders:
class EmbedBuilder:
    @staticmethod
    def success(title, description):
        embed = discord.Embed(title=title, description=description, color=discord.Color.green())
        return embed

    @staticmethod
    def error(title, description):
        embed = discord.Embed(title=title, description=description, color=discord.Color.red())
        return embed

    @staticmethod
    def warning(title, description):
        embed = discord.Embed(title=title, description=description, color=discord.Color.orange())
        return embed

class ConfirmView(View):
    def __init__(self, user):
        super().__init__(timeout=60)
        self.user = user
        self.value = None

    async def interaction_check(self, interaction):
        if interaction.user != self.user:
            await interaction.response.send_message("This is not for you!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self.message.edit(view=self)

    @discord.ui.button(label="Confirm", style=ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.defer()
        self.stop()

log = logging.getLogger(__name__)

class TicketJoinRequestView(discord.ui.View):
    def __init__(self, bot, user, channel):
        super().__init__(timeout=None)
        self.bot = bot
        self.user = user
        self.channel = channel
        self.message = None

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green, custom_id="ticket_join_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if the user has manage channel permissions
        permissions = interaction.channel.permissions_for(interaction.user)
        if not permissions.manage_channels:
            await interaction.response.send_message("You do not have permission to accept this request.", ephemeral=True)
            return

        # Grant the user access to the channel
        await self.channel.set_permissions(self.user, send_messages=True, read_messages=True, view_channel=True)

        # Edit the embed to show that the request was accepted
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = "🎫 Ticket Join Request - Accepted"
        embed.description = f"Request to join this ticket was accepted by {interaction.user.mention}"

        # Disable the buttons
        for child in self.children:
            child.disabled = True

        # Update the message
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red, custom_id="ticket_join_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if the user has manage channel permissions
        permissions = interaction.channel.permissions_for(interaction.user)
        if not permissions.manage_channels:
            await interaction.response.send_message("You do not have permission to deny this request.", ephemeral=True)
            return

        # Edit the embed to show that the request was denied
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "🎫 Ticket Join Request - Denied"
        embed.description = f"Request to join this ticket was denied by {interaction.user.mention}"

        # Disable the buttons
        for child in self.children:
            child.disabled = True

        # Update the message
        await interaction.response.edit_message(embed=embed, view=self)

class Ticket(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ticket_message_cache = {}  # Store message content for editing
        self.check_inactive_tickets.start()

    async def cog_load(self):
        log.info(f"{self.__class__.__name__} loaded!")

    async def cog_unload(self):
        self.check_inactive_tickets.cancel()
        log.info(f"{self.__class__.__name__} unloaded!")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if not message.guild:
            return

        if not isinstance(message.channel, discord.Thread):
            return

        ticket = await self.get_ticket_by_channel_id(message.channel.id)
        if not ticket:
            return

        # Log the message to the database
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "INSERT INTO ticket_messages (ticket_id, author_id, content, created_at) VALUES ($1, $2, $3, $4)",
                    ticket['ticket_id'], str(message.author.id), message.content, message.created_at
                )
            else:
                await self.bot.db.connection.execute(
                    "INSERT INTO ticket_messages (ticket_id, author_id, content, created_at) VALUES (?, ?, ?, ?)",
                    (ticket['ticket_id'], str(message.author.id), message.content, message.created_at)
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            log.error(f"Error logging ticket message: {e}")

    async def get_ticket_by_channel_id(self, channel_id):
        if self.bot.db.is_postgresql:
            ticket = await self.bot.db.connection.fetchrow(
                "SELECT * FROM tickets WHERE channel_id = $1",
                str(channel_id)
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT * FROM tickets WHERE channel_id = ?",
                (str(channel_id),)
            )
            ticket = await cursor.fetchone()
        return ticket

    async def get_ticket_by_id(self, ticket_id):
        if self.bot.db.is_postgresql:
            ticket = await self.bot.db.connection.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1",
                ticket_id
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT * FROM tickets WHERE ticket_id = ?",
                (ticket_id,)
            )
            ticket = await cursor.fetchone()
        return ticket

    async def get_guild_config(self, guild_id):
        if self.bot.db.is_postgresql:
            config = await self.bot.db.connection.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1",
                str(guild_id)
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT * FROM guild_config WHERE guild_id = ?",
                (str(guild_id),)
            )
            config = await cursor.fetchone()
        return config

    async def create_ticket(self, interaction, category, reason):
        guild_config = await self.get_guild_config(interaction.guild.id)
        if not guild_config:
            embed = EmbedBuilder.error("Configuration Error", "Ticket system is not configured for this server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Get the ticket number
        if self.bot.db.is_postgresql:
            ticket_number = await self.bot.db.connection.fetchval(
                "SELECT COUNT(*) FROM tickets WHERE guild_id = $1",
                str(interaction.guild.id)
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT COUNT(*) FROM tickets WHERE guild_id = ?",
                (str(interaction.guild.id),)
            )
            ticket_number = (await cursor.fetchone())[0]
        ticket_number = ticket_number + 1

        # Get the category
        if self.bot.db.is_postgresql:
            ticket_category = await self.bot.db.connection.fetchrow(
                "SELECT * FROM ticket_categories WHERE category_id = $1 AND guild_id = $2",
                category, str(interaction.guild.id)
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT * FROM ticket_categories WHERE category_id = ? AND guild_id = ?",
                (category, str(interaction.guild.id))
            )
            ticket_category = await cursor.fetchone()

        if not ticket_category:
            embed = EmbedBuilder.error("Category Not Found", "The selected category does not exist.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Get the category object
        category_obj = interaction.guild.get_channel(int(ticket_category['category_id']))
        if not category_obj:
            embed = EmbedBuilder.error("Category Not Found", "The selected category does not exist in the server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Get the support role
        support_role = interaction.guild.get_role(int(guild_config['support_role_id']))
        if not support_role:
            embed = EmbedBuilder.error("Role Not Found", "The support role does not exist in the server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Create the ticket channel
        try:
            channel = await interaction.guild.create_thread(
                name=f"ticket-{ticket_number:04d}",
                message=None,
                auto_archive_duration=1440,
                type=discord.ChannelType.public_thread,
                reason=f"Ticket created by {interaction.user}"
            )
            await channel.edit(category=category_obj)
        except Exception as e:
            embed = EmbedBuilder.error("Channel Creation Error", f"Failed to create the ticket channel.\n\`\`\`{e}\`\`\`")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Set channel permissions
        await channel.set_permissions(interaction.user, send_messages=True, read_messages=True, view_channel=True)
        await channel.set_permissions(support_role, send_messages=True, read_messages=True, view_channel=True)
        await channel.set_permissions(interaction.guild.default_role, view_channel=False)

        # Send the ticket embed
        embed = discord.Embed(
            title=f"Ticket #{ticket_number:04d} - {ticket_category['category_name']}",
            description=f"{interaction.user.mention} has opened a ticket.\n\n**Reason:** {reason}",
            color=0x84e1ff
        )
        embed.add_field(name="Category", value=ticket_category['category_name'], inline=True)
        embed.add_field(name="Ticket ID", value=f"{ticket_number:04d}", inline=True)
        embed.add_field(name="Opened By", value=interaction.user.mention, inline=False)
        embed.set_footer(text="Railway Bot")
        message = await channel.send(f"{interaction.user.mention} {support_role.mention}", embed=embed)
        await message.pin()

        # Add the ticket to the database
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "INSERT INTO tickets (ticket_id, guild_id, channel_id, creator_id, category_id, reason, created_at, closed) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                    ticket_number, str(interaction.guild.id), str(channel.id), str(interaction.user.id), category, reason, datetime.utcnow(), False
                )
            else:
                await self.bot.db.connection.execute(
                    "INSERT INTO tickets (ticket_id, guild_id, channel_id, creator_id, category_id, reason, created_at, closed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (ticket_number, str(interaction.guild.id), str(channel.id), str(interaction.user.id), category, reason, datetime.utcnow(), False)
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            embed = EmbedBuilder.error("Database Error", f"Failed to add the ticket to the database.\n\`\`\`{e}\`\`\`")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            await channel.delete()
            return

        # Send confirmation to the user
        embed = EmbedBuilder.success(
            "Ticket Created",
            f"Your ticket has been created in {channel.mention}."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ticket", description="Opens a ticket")
    @app_commands.describe(category="The category for the ticket")
    @app_commands.describe(reason="The reason for opening the ticket")
    @app_commands.choices(category=[])
    async def ticket(self, interaction: discord.Interaction, category: str, reason: str):
        await self.create_ticket(interaction, category, reason)

    @ticket.autocomplete("category")
    async def ticket_autocomplete(self, interaction: discord.Interaction, current: str):
        guild_config = await self.get_guild_config(interaction.guild.id)
        if not guild_config:
            return []

        if self.bot.db.is_postgresql:
            categories = await self.bot.db.connection.fetch(
                "SELECT * FROM ticket_categories WHERE guild_id = $1 AND category_name ILIKE $2 LIMIT 25",
                str(interaction.guild.id), f"%{current}%"
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT * FROM ticket_categories WHERE guild_id = ? AND category_name LIKE ? LIMIT 25",
                (str(interaction.guild.id), f"%{current}%")
            )
            categories = await cursor.fetchall()

        return [Choice(name=category['category_name'], value=category['category_id']) for category in categories]

    @app_commands.command(name="close", description="Closes the ticket")
    async def close(self, interaction: discord.Interaction):
        ticket = await self.get_ticket_by_channel_id(interaction.channel.id)
        if not ticket:
            embed = EmbedBuilder.error("Not a Ticket", "This channel is not a ticket.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if the user has permission to close the ticket
        guild_config = await self.get_guild_config(interaction.guild.id)
        if not guild_config:
            embed = EmbedBuilder.error("Configuration Error", "Ticket system is not configured for this server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        support_role = interaction.guild.get_role(int(guild_config['support_role_id']))
        if not support_role:
            embed = EmbedBuilder.error("Role Not Found", "The support role does not exist in the server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not (support_role in interaction.user.roles or interaction.user.guild_permissions.administrator):
            embed = EmbedBuilder.error("Missing Permissions", "You do not have permission to close this ticket.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Confirm close
        view = ConfirmView(interaction.user)
        embed = EmbedBuilder.warning("Confirmation", "Are you sure you want to close this ticket?")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if view.value is None:
            embed = EmbedBuilder.error("Timeout", "Ticket close timed out.")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        elif not view.value:
            embed = EmbedBuilder.error("Cancelled", "Ticket close cancelled.")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Close the ticket
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET closed = $1, closed_at = $2 WHERE ticket_id = $3",
                    True, datetime.utcnow(), ticket['ticket_id']
                )
            else:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET closed = ?, closed_at = ? WHERE ticket_id = ?",
                    (True, datetime.utcnow(), ticket['ticket_id'])
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            embed = EmbedBuilder.error("Database Error", f"Failed to update the ticket in the database.\n\`\`\`{e}\`\`\`")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = EmbedBuilder.success("Ticket Closed", "The ticket has been closed.")
        await interaction.channel.send(embed=embed)
        await interaction.channel.edit(archived=True, locked=True)

    @app_commands.command(name="add", description="Adds a user to the ticket")
    @app_commands.describe(user="The user to add to the ticket")
    async def add(self, interaction: discord.Interaction, user: discord.Member):
        ticket = await self.get_ticket_by_channel_id(interaction.channel.id)
        if not ticket:
            embed = EmbedBuilder.error("Not a Ticket", "This channel is not a ticket.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if the user has permission to add users to the ticket
        guild_config = await self.get_guild_config(interaction.guild.id)
        if not guild_config:
            embed = EmbedBuilder.error("Configuration Error", "Ticket system is not configured for this server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        support_role = interaction.guild.get_role(int(guild_config['support_role_id']))
        if not support_role:
            embed = EmbedBuilder.error("Role Not Found", "The support role does not exist in the server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not (support_role in interaction.user.roles or interaction.user.guild_permissions.administrator):
            embed = EmbedBuilder.error("Missing Permissions", "You do not have permission to add users to this ticket.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Add the user to the ticket
        try:
            await interaction.channel.set_permissions(user, send_messages=True, read_messages=True, view_channel=True)
        except Exception as e:
            embed = EmbedBuilder.error("Permission Error", f"Failed to add the user to the ticket.\n\`\`\`{e}\`\`\`")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = EmbedBuilder.success("User Added", f"{user.mention} has been added to the ticket.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="remove", description="Removes a user from the ticket")
    @app_commands.describe(user="The user to remove from the ticket")
    async def remove(self, interaction: discord.Interaction, user: discord.Member):
        ticket = await self.get_ticket_by_channel_id(interaction.channel.id)
        if not ticket:
            embed = EmbedBuilder.error("Not a Ticket", "This channel is not a ticket.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if the user has permission to remove users from the ticket
        guild_config = await self.get_guild_config(interaction.guild.id)
        if not guild_config:
            embed = EmbedBuilder.error("Configuration Error", "Ticket system is not configured for this server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        support_role = interaction.guild.get_role(int(guild_config['support_role_id']))
        if not support_role:
            embed = EmbedBuilder.error("Role Not Found", "The support role does not exist in the server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not (support_role in interaction.user.roles or interaction.user.guild_permissions.administrator):
            embed = EmbedBuilder.error("Missing Permissions", "You do not have permission to remove users from this ticket.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Remove the user from the ticket
        try:
            await interaction.channel.set_permissions(user, send_messages=False, read_messages=False, view_channel=False)
        except Exception as e:
            embed = EmbedBuilder.error("Permission Error", f"Failed to remove the user from the ticket.\n\`\`\`{e}\`\`\`")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = EmbedBuilder.success("User Removed", f"{user.mention} has been removed from the ticket.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rename", description="Renames the ticket")
    @app_commands.describe(name="The new name for the ticket")
    async def rename(self, interaction: discord.Interaction, name: str):
        ticket = await self.get_ticket_by_channel_id(interaction.channel.id)
        if not ticket:
            embed = EmbedBuilder.error("Not a Ticket", "This channel is not a ticket.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if the user has permission to rename the ticket
        guild_config = await self.get_guild_config(interaction.guild.id)
        if not guild_config:
            embed = EmbedBuilder.error("Configuration Error", "Ticket system is not configured for this server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        support_role = interaction.guild.get_role(int(guild_config['support_role_id']))
        if not support_role:
            embed = EmbedBuilder.error("Role Not Found", "The support role does not exist in the server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not (support_role in interaction.user.roles or interaction.user.guild_permissions.administrator):
            embed = EmbedBuilder.error("Missing Permissions", "You do not have permission to rename this ticket.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Rename the ticket
        try:
            await interaction.channel.edit(name=name)
        except Exception as e:
            embed = EmbedBuilder.error("Channel Error", f"Failed to rename the ticket.\n\`\`\`{e}\`\`\`")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = EmbedBuilder.success("Ticket Renamed", f"The ticket has been renamed to {name}.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="forceclose", description="Force closes a ticket, bypassing confirmation")
    async def forceclose(self, interaction: discord.Interaction):
        ticket = await self.get_ticket_by_channel_id(interaction.channel.id)
        if not ticket:
            embed = EmbedBuilder.error("Not a Ticket", "This channel is not a ticket.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if the user has permission to close the ticket
        guild_config = await self.get_guild_config(interaction.guild.id)
        if not guild_config:
            embed = EmbedBuilder.error("Configuration Error", "Ticket system is not configured for this server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        support_role = interaction.guild.get_role(int(guild_config['support_role_id']))
        if not support_role:
            embed = EmbedBuilder.error("Role Not Found", "The support role does not exist in the server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not (support_role in interaction.user.roles or interaction.user.guild_permissions.administrator):
            embed = EmbedBuilder.error("Missing Permissions", "You do not have permission to close this ticket.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Close the ticket
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET closed = $1, closed_at = $2 WHERE ticket_id = $3",
                    True, datetime.utcnow(), ticket['ticket_id']
                )
            else:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET closed = ?, closed_at = ? WHERE ticket_id = ?",
                    (True, datetime.utcnow(), ticket['ticket_id'])
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            embed = EmbedBuilder.error("Database Error", f"Failed to update the ticket in the database.\n\`\`\`{e}\`\`\`")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = EmbedBuilder.success("Ticket Closed", "The ticket has been closed.")
        await interaction.response.send_message(embed=embed)
        await interaction.channel.edit(archived=True, locked=True)

    @app_commands.command(name="ticket_join", description="Request to join a ticket")
    @app_commands.describe(ticket_id="The ID of the ticket you want to join")
    async def ticket_join(self, interaction: discord.Interaction, ticket_id: int):
        # Get the ticket
        ticket = await self.get_ticket_by_id(ticket_id)
        if not ticket:
            embed = EmbedBuilder.error("Ticket Not Found", "The specified ticket does not exist.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if ticket is closed
        if ticket['closed']:
            embed = EmbedBuilder.error("Ticket Closed", "This ticket is closed.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if user has already made too many requests for this ticket
        if self.bot.db.is_postgresql:
            request_count = await self.bot.db.connection.fetchval(
                "SELECT COUNT(*) FROM user_data WHERE user_id = $1 AND guild_id = $2 AND data_type = $3 AND data_content->>'ticket_id' = $4",
                str(interaction.user.id), str(interaction.guild.id), 'ticket_join_request', ticket_id
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT COUNT(*) FROM user_data WHERE user_id = ? AND guild_id = ? AND data_type = ? AND json_extract(data_content, '$.ticket_id') = ?",
                (str(interaction.user.id), str(interaction.guild.id), 'ticket_join_request', ticket_id)
            )
            request_count = (await cursor.fetchone())[0]

        if request_count >= 5:
            embed = EmbedBuilder.error("Request Limit Reached", "You have already made 5 join requests for this ticket. Please wait for a response.")
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
        embed.set_footer(text="Railway Bot")
        
        view = TicketJoinRequestView(self.bot, interaction.user, channel)
        
        # Send request to ticket channel
        await channel.send(embed=embed, view=view)
        
        # Log the request to prevent spam - use UPSERT to avoid duplicate key errors
        request_data = {
            'ticket_id': ticket_id,
            'requested_at': datetime.utcnow().isoformat(),
            'channel_id': str(channel.id),
            'request_count': request_count + 1
        }

        try:
            if self.bot.db.is_postgresql:
                # Use ON CONFLICT DO UPDATE for PostgreSQL
                await self.bot.db.connection.execute(
                    """INSERT INTO user_data (user_id, guild_id, data_type, data_content)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (user_id, guild_id, data_type) 
                       DO UPDATE SET data_content = $4, updated_at = CURRENT_TIMESTAMP""",
                    str(interaction.user.id), str(interaction.guild.id), 'ticket_join_request', json.dumps(request_data)
                )
            else:
                # Use INSERT OR REPLACE for SQLite
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO user_data (user_id, guild_id, data_type, data_content)
                       VALUES (?, ?, ?, ?)""",
                    (str(interaction.user.id), str(interaction.guild.id), 'ticket_join_request', json.dumps(request_data))
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            # If there's still an error, log it but don't fail the request
            print(f"Warning: Could not log join request: {e}")
        
        # Notify user
        response_embed = EmbedBuilder.success(
            "Request Sent",
            f"Your request to join ticket {ticket_id} has been sent. You'll be notified if it's accepted.\n"
            f"Requests made for this ticket: {request_count + 1}/5"
        )
        await interaction.response.send_message(embed=response_embed, ephemeral=True)

    @app_commands.command(name="config", description="Configures the ticket system")
    @app_commands.describe(support_role="The role that can manage tickets")
    @app_commands.describe(log_channel="The channel to log ticket activity")
    async def config(self, interaction: discord.Interaction, support_role: discord.Role, log_channel: discord.TextChannel = None):
        # Check if the user has administrator permissions
        if not interaction.user.guild_permissions.administrator:
            embed = EmbedBuilder.error("Missing Permissions", "You do not have permission to configure the ticket system.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Configure the ticket system
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO guild_config (guild_id, support_role_id, log_channel_id)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (guild_id)
                       DO UPDATE SET support_role_id = $2, log_channel_id = $3""",
                    str(interaction.guild.id), str(support_role.id), str(log_channel.id) if log_channel else None
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO guild_config (guild_id, support_role_id, log_channel_id)
                       VALUES (?, ?, ?)""",
                    (str(interaction.guild.id), str(support_role.id), str(log_channel.id) if log_channel else None)
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            embed = EmbedBuilder.error("Database Error", f"Failed to configure the ticket system.\n\`\`\`{e}\`\`\`")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = EmbedBuilder.success("Ticket System Configured", f"The ticket system has been configured.\nSupport Role: {support_role.mention}\nLog Channel: {log_channel.mention if log_channel else 'None'}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="category_add", description="Adds a ticket category")
    @app_commands.describe(name="The name of the category")
    @app_commands.describe(category="The category channel")
    async def category_add(self, interaction: discord.Interaction, name: str, category: discord.CategoryChannel):
        # Check if the user has administrator permissions
        if not interaction.user.guild_permissions.administrator:
            embed = EmbedBuilder.error("Missing Permissions", "You do not have permission to add ticket categories.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Add the ticket category
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "INSERT INTO ticket_categories (category_id, guild_id, category_name) VALUES ($1, $2, $3)",
                    str(category.id), str(interaction.guild.id), name
                )
            else:
                await self.bot.db.connection.execute(
                    "INSERT INTO ticket_categories (category_id, guild_id, category_name) VALUES (?, ?, ?)",
                    (str(category.id), str(interaction.guild.id), name)
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            embed = EmbedBuilder.error("Database Error", f"Failed to add the ticket category.\n\`\`\`{e}\`\`\`")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = EmbedBuilder.success("Ticket Category Added", f"The ticket category {name} has been added.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="category_remove", description="Removes a ticket category")
    @app_commands.describe(category="The category channel")
    async def category_remove(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        # Check if the user has administrator permissions
        if not interaction.user.guild_permissions.administrator:
            embed = EmbedBuilder.error("Missing Permissions", "You do not have permission to remove ticket categories.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Remove the ticket category
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "DELETE FROM ticket_categories WHERE category_id = $1 AND guild_id = $2",
                    str(category.id), str(interaction.guild.id)
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM ticket_categories WHERE category_id = ? AND guild_id = ?",
                    (str(category.id), str(interaction.guild.id))
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            embed = EmbedBuilder.error("Database Error", f"Failed to remove the ticket category.\n\`\`\`{e}\`\`\`")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = EmbedBuilder.success("Ticket Category Removed", f"The ticket category {category.name} has been removed.")
        await interaction.response.send_message(embed=embed)

    @tasks.loop(minutes=60)
    async def check_inactive_tickets(self):
        log.info("Checking for inactive tickets...")
        # Define the inactivity threshold (e.g., 7 days)
        inactivity_threshold = 7  # days

        # Get all open tickets
        if self.bot.db.is_postgresql:
            open_tickets = await self.bot.db.connection.fetch(
                "SELECT * FROM tickets WHERE closed = $1",
                False
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT * FROM tickets WHERE closed = ?",
                (False,)
            )
            open_tickets = await cursor.fetchall()

        for ticket in open_tickets:
            # Get the channel
            guild = self.bot.get_guild(int(ticket['guild_id']))
            if not guild:
                log.warning(f"Guild not found for ticket {ticket['ticket_id']}")
                continue

            channel = guild.get_channel(int(ticket['channel_id']))
            if not channel:
                log.warning(f"Channel not found for ticket {ticket['ticket_id']}")
                continue

            # Get the last message in the channel
            try:
                if isinstance(channel, discord.Thread):
                    last_message = None
                    async for message in channel.history(limit=1):
                        last_message = message
                    if last_message:
                        time_difference = datetime.utcnow() - last_message.created_at
                    else:
                        # If there are no messages, consider it inactive since creation
                        time_difference = datetime.utcnow() - ticket['created_at']
                else:
                    log.warning(f"Channel is not a thread for ticket {ticket['ticket_id']}")
                    continue
            except Exception as e:
                log.error(f"Error getting last message for ticket {ticket['ticket_id']}: {e}")
                continue

            # Check if the ticket is inactive
            if time_difference.days >= inactivity_threshold:
                log.info(f"Closing inactive ticket {ticket['ticket_id']}")
                try:
                    # Close the ticket in the database
                    if self.bot.db.is_postgresql:
                        await self.bot.db.connection.execute(
                            "UPDATE tickets SET closed = $1, closed_at = $2 WHERE ticket_id = $3",
                            True, datetime.utcnow(), ticket['ticket_id']
                        )
                    else:
                        await self.bot.db.connection.execute(
                            "UPDATE tickets SET closed = ?, closed_at = ? WHERE ticket_id = ?",
                            (True, datetime.utcnow(), ticket['ticket_id'])
                        )
                        await self.bot.db.connection.commit()

                    # Send a message to the channel
                    embed = EmbedBuilder.warning("Inactive Ticket", "This ticket has been closed due to inactivity.")
                    await channel.send(embed=embed)

                    # Archive the channel
                    await channel.edit(archived=True, locked=True)

                except Exception as e:
                    log.error(f"Error closing ticket {ticket['ticket_id']}: {e}")

    @check_inactive_tickets.before_loop
    async def before_check_inactive_tickets(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Ticket(bot))
