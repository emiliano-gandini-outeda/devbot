import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

import discord
from discord import ButtonStyle, Interaction, SelectOption, app_commands
from discord.ext import commands, tasks
from discord.ui import Button, Select, View

# from cogs.utils.embed_builder import EmbedBuilder
from utils.helpers import EmbedBuilder
from utils.helpers import (
    get_expiry_date,
    get_role,
    get_ticket_channel,
    get_ticket_owner,
    get_ticket_type,
    has_permissions,
    is_support_staff,
    log_to_channel,
    parse_expiry_date,
    send_dm,
    update_expiry_date,
)

log = logging.getLogger(__name__)


class TicketButton(Button):
    def __init__(self, bot, ticket_type, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot
        self.ticket_type = ticket_type

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user

        # Check if the user already has an open ticket
        existing_ticket = await get_ticket_channel(self.bot, guild.id, user.id)
        if existing_ticket:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"You already have an open ticket at {existing_ticket.mention}. Please close that ticket before creating a new one.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Get ticket config
        ticket_config = await self.bot.db.get_ticket_config(guild.id, self.ticket_type)
        if not ticket_config:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"This ticket type is not configured. Please contact a server administrator.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Get category
        category_id = ticket_config.get("category_id")
        if not category_id:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"This ticket type is not configured with a category. Please contact a server administrator.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        category = guild.get_channel(int(category_id))
        if not category:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"The category for this ticket type is invalid. Please contact a server administrator.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Get support role
        support_role_id = ticket_config.get("support_role_id")
        if not support_role_id:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"This ticket type is not configured with a support role. Please contact a server administrator.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        support_role = guild.get_role(int(support_role_id))
        if not support_role:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"The support role for this ticket type is invalid. Please contact a server administrator.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Get ticket name
        ticket_name = ticket_config.get("name")
        if not ticket_name:
            ticket_name = "ticket-{user_name}"

        ticket_name = ticket_name.replace("{user_name}", user.name)
        ticket_name = ticket_name.replace("{user_id}", str(user.id))

        # Get overwrites
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True
            ),
            support_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True
            ),
        }

        # Create the ticket
        try:
            channel = await guild.create_text_channel(
                ticket_name, category=category, overwrites=overwrites
            )
        except Exception as e:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"There was an error creating the ticket. Please contact a server administrator.\n\n`{e}`",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Set ticket topic
        await channel.edit(topic=f"Ticket for {user.mention} | User ID: {user.id}")

        # Set slowmode
        slowmode = ticket_config.get("slowmode")
        if slowmode:
            try:
                await channel.edit(slowmode_delay=int(slowmode))
            except Exception as e:
                log.error(f"Error setting slowmode for ticket {channel.id}: {e}")

        # Send intro message
        intro_message = ticket_config.get("intro_message")
        if intro_message:
            intro_message = intro_message.replace("{user_mention}", user.mention)
            intro_message = intro_message.replace("{user_name}", user.name)
            intro_message = intro_message.replace("{user_id}", str(user.id))
            intro_message = intro_message.replace("{support_role}", support_role.mention)

            try:
                await channel.send(intro_message)
            except Exception as e:
                log.error(f"Error sending intro message for ticket {channel.id}: {e}")

        # Add close button
        close_button = Button(
            label="Close Ticket",
            style=ButtonStyle.danger,
            emoji="🔒",
            custom_id="close_ticket",
        )
        view = View()
        view.add_item(close_button)

        # Send embed
        embed = EmbedBuilder.success(
            "Ticket Created", f"Your ticket has been created at {channel.mention}."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        # Send ticket created message to ticket channel
        embed = EmbedBuilder.success(
            "Ticket Created",
            f"{user.mention} has created a ticket. {support_role.mention} will be with you shortly.",
        )
        await channel.send(embed=embed, view=view)

        # Log ticket creation
        await self.bot.db.create_ticket(
            guild.id, channel.id, user.id, self.ticket_type
        )

        # Log to log channel
        log_message = f"{user.mention} created ticket {channel.mention} ({self.ticket_type})"
        await log_to_channel(self.bot, guild.id, log_message, "ticket")


class TicketModal(discord.ui.Modal):
    def __init__(self, bot, ticket_type, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot
        self.ticket_type = ticket_type
        self.add_item(
            discord.ui.TextInput(
                label="Please describe your issue",
                style=discord.TextStyle.paragraph,
                placeholder="Please be as detailed as possible.",
                required=True,
                max_length=2000,
            )
        )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user
        description = self.children[0].value

        # Check if the user already has an open ticket
        existing_ticket = await get_ticket_channel(self.bot, guild.id, user.id)
        if existing_ticket:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"You already have an open ticket at {existing_ticket.mention}. Please close that ticket before creating a new one.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Get ticket config
        ticket_config = await self.bot.db.get_ticket_config(guild.id, self.ticket_type)
        if not ticket_config:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"This ticket type is not configured. Please contact a server administrator.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Get category
        category_id = ticket_config.get("category_id")
        if not category_id:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"This ticket type is not configured with a category. Please contact a server administrator.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        category = guild.get_channel(int(category_id))
        if not category:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"The category for this ticket type is invalid. Please contact a server administrator.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Get support role
        support_role_id = ticket_config.get("support_role_id")
        if not support_role_id:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"This ticket type is not configured with a support role. Please contact a server administrator.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        support_role = guild.get_role(int(support_role_id))
        if not support_role:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"The support role for this ticket type is invalid. Please contact a server administrator.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Get ticket name
        ticket_name = ticket_config.get("name")
        if not ticket_name:
            ticket_name = "ticket-{user_name}"

        ticket_name = ticket_name.replace("{user_name}", user.name)
        ticket_name = ticket_name.replace("{user_id}", str(user.id))

        # Get overwrites
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True
            ),
            support_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True
            ),
        }

        # Create the ticket
        try:
            channel = await guild.create_text_channel(
                ticket_name, category=category, overwrites=overwrites
            )
        except Exception as e:
            embed = EmbedBuilder.error(
                "Ticket Creation Failed",
                f"There was an error creating the ticket. Please contact a server administrator.\n\n`{e}`",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Set ticket topic
        await channel.edit(topic=f"Ticket for {user.mention} | User ID: {user.id}")

        # Set slowmode
        slowmode = ticket_config.get("slowmode")
        if slowmode:
            try:
                await channel.edit(slowmode_delay=int(slowmode))
            except Exception as e:
                log.error(f"Error setting slowmode for ticket {channel.id}: {e}")

        # Send intro message
        intro_message = ticket_config.get("intro_message")
        if intro_message:
            intro_message = intro_message.replace("{user_mention}", user.mention)
            intro_message = intro_message.replace("{user_name}", user.name)
            intro_message = intro_message.replace("{user_id}", str(user.id))
            intro_message = intro_message.replace("{support_role}", support_role.mention)

            try:
                await channel.send(intro_message)
            except Exception as e:
                log.error(f"Error sending intro message for ticket {channel.id}: {e}")

        # Add close button
        close_button = Button(
            label="Close Ticket",
            style=ButtonStyle.danger,
            emoji="🔒",
            custom_id="close_ticket",
        )
        view = View()
        view.add_item(close_button)

        # Send embed
        embed = EmbedBuilder.success(
            "Ticket Created", f"Your ticket has been created at {channel.mention}."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        # Send ticket created message to ticket channel
        embed = EmbedBuilder.success(
            "Ticket Created",
            f"{user.mention} has created a ticket. {support_role.mention} will be with you shortly.",
        )
        embed.add_field(name="Description", value=description, inline=False)
        await channel.send(embed=embed, view=view)

        # Log ticket creation
        await self.bot.db.create_ticket(
            guild.id, channel.id, user.id, self.ticket_type
        )

        # Log to log channel
        log_message = f"{user.mention} created ticket {channel.mention} ({self.ticket_type})"
        await log_to_channel(self.bot, guild.id, log_message, "ticket")


class TicketSelect(Select):
    def __init__(self, bot, ticket_types, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot
        self.ticket_types = ticket_types
        options = []
        for ticket_type in ticket_types:
            options.append(
                SelectOption(
                    label=ticket_type.get("display_name"),
                    value=ticket_type.get("ticket_type"),
                    description=ticket_type.get("description"),
                    emoji=ticket_type.get("emoji"),
                )
            )
        self.options = options

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket_type = interaction.data.get("values")[0]
        for t in self.ticket_types:
            if t.get("ticket_type") == ticket_type:
                selected_ticket_type = t
                break

        use_modal = selected_ticket_type.get("use_modal")
        if use_modal:
            modal = TicketModal(
                self.bot,
                ticket_type,
                title=f"{selected_ticket_type.get('display_name')} Request",
            )
            await interaction.response.send_modal(modal)
        else:
            button = TicketButton(
                self.bot,
                ticket_type,
                label=selected_ticket_type.get("display_name"),
                style=ButtonStyle.primary,
                emoji=selected_ticket_type.get("emoji"),
            )
            await button.callback(interaction)


class TicketView(View):
    def __init__(self, bot, ticket_types, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_item(TicketSelect(bot, ticket_types))


class TicketJoinRequestView(View):
    def __init__(self, bot, user, channel, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot
        self.user = user
        self.channel = channel

        accept_button = Button(
            label="Accept",
            style=ButtonStyle.success,
            emoji="✅",
            custom_id="accept_ticket_join",
        )
        deny_button = Button(
            label="Deny", style=ButtonStyle.danger, emoji="❌", custom_id="deny_ticket_join"
        )

        accept_button.callback = self.accept_ticket_join
        deny_button.callback = self.deny_ticket_join

        self.add_item(accept_button)
        self.add_item(deny_button)

    async def accept_ticket_join(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        user = self.user

        # Add user to ticket
        await channel.set_permissions(
            user, view_channel=True, send_messages=True, attach_files=True
        )

        # Send message to ticket channel
        embed = EmbedBuilder.success(
            "Ticket Join Request Accepted", f"{user.mention} has been added to the ticket."
        )
        await interaction.followup.send(embed=embed)

        # Send message to user
        embed = EmbedBuilder.success(
            "Ticket Join Request Accepted",
            f"Your request to join ticket {channel.mention} has been accepted.",
        )
        await send_dm(user, embed=embed)

        # Disable buttons
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        # Remove request from database
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "DELETE FROM user_data WHERE user_id = $1 AND guild_id = $2 AND data_type = $3",
                    str(user.id),
                    str(interaction.guild.id),
                    "ticket_join_request",
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM user_data WHERE user_id = ? AND guild_id = ? AND data_type = ?",
                    (str(user.id), str(interaction.guild.id), "ticket_join_request"),
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            log.error(f"Error deleting join request: {e}")

    async def deny_ticket_join(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        user = self.user

        # Send message to ticket channel
        embed = EmbedBuilder.error(
            "Ticket Join Request Denied", f"{user.mention}'s request to join has been denied."
        )
        await interaction.followup.send(embed=embed)

        # Send message to user
        embed = EmbedBuilder.error(
            "Ticket Join Request Denied",
            f"Your request to join ticket {channel.mention} has been denied.",
        )
        await send_dm(user, embed=embed)

        # Disable buttons
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        # Remove request from database
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "DELETE FROM user_data WHERE user_id = $1 AND guild_id = $2 AND data_type = $3",
                    str(user.id),
                    str(interaction.guild.id),
                    "ticket_join_request",
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM user_data WHERE user_id = ? AND guild_id = ? AND data_type = ?",
                    (str(user.id), str(interaction.guild.id), "ticket_join_request"),
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            log.error(f"Error deleting join request: {e}")


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="ticket", invoke_without_command=True, aliases=["tickets"])
    @has_permissions(manage_guild=True)
    async def ticket_group(self, ctx):
        """
        Ticket management commands.
        """
        await ctx.send_help(ctx.command)

    @ticket_group.command(name="createpanel", aliases=["panel"])
    @has_permissions(manage_guild=True)
    async def create_panel(self, ctx, channel: discord.TextChannel = None):
        """
        Creates a ticket panel in the specified channel.
        """
        if not channel:
            channel = ctx.channel

        ticket_types = await self.bot.db.get_ticket_types(ctx.guild.id)
        if not ticket_types:
            embed = EmbedBuilder.error(
                "Ticket Panel Creation Failed",
                "There are no ticket types configured for this server. Please add some ticket types using the `ticket type` commands.",
            )
            return await ctx.send(embed=embed)

        view = TicketView(self.bot, ticket_types)
        embed = EmbedBuilder.success(
            "Ticket Panel", "Please select the type of ticket you would like to create."
        )
        await channel.send(embed=embed, view=view)

        embed = EmbedBuilder.success(
            "Ticket Panel Created", f"Ticket panel created in {channel.mention}."
        )
        await ctx.send(embed=embed)

        # Log to log channel
        log_message = f"{ctx.author.mention} created a ticket panel in {channel.mention}"
        await log_to_channel(self.bot, ctx.guild.id, log_message, "ticket")

    @ticket_group.group(name="type", aliases=["types"], invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def ticket_type_group(self, ctx):
        """
        Ticket type management commands.
        """
        await ctx.send_help(ctx.command)

    @ticket_type_group.command(name="add")
    @has_permissions(manage_guild=True)
    async def add_ticket_type(
        self,
        ctx,
        ticket_type: str,
        display_name: str,
        description: str,
        emoji: str,
        category: discord.CategoryChannel,
        support_role: discord.Role,
        use_modal: bool = False,
        slowmode: int = 0,
        intro_message: str = None,
        name: str = None,
    ):
        """
        Adds a ticket type to the server.
        """
        if await self.bot.db.get_ticket_config(ctx.guild.id, ticket_type):
            embed = EmbedBuilder.error(
                "Ticket Type Creation Failed",
                "A ticket type with that name already exists. Please use a different name.",
            )
            return await ctx.send(embed=embed)

        try:
            await self.bot.db.add_ticket_config(
                ctx.guild.id,
                ticket_type,
                display_name,
                description,
                emoji,
                category.id,
                support_role.id,
                use_modal,
                slowmode,
                intro_message,
                name,
            )
        except Exception as e:
            embed = EmbedBuilder.error(
                "Ticket Type Creation Failed",
                f"There was an error creating the ticket type. Please contact a server administrator.\n\n`{e}`",
            )
            return await ctx.send(embed=embed)

        embed = EmbedBuilder.success(
            "Ticket Type Created", f"Ticket type `{ticket_type}` has been created."
        )
        await ctx.send(embed=embed)

        # Log to log channel
        log_message = f"{ctx.author.mention} created ticket type `{ticket_type}`"
        await log_to_channel(self.bot, ctx.guild.id, log_message, "ticket")

    @ticket_type_group.command(name="remove", aliases=["delete", "del"])
    @has_permissions(manage_guild=True)
    async def remove_ticket_type(self, ctx, ticket_type: str):
        """
        Removes a ticket type from the server.
        """
        if not await self.bot.db.get_ticket_config(ctx.guild.id, ticket_type):
            embed = EmbedBuilder.error(
                "Ticket Type Removal Failed",
                "A ticket type with that name does not exist. Please use a different name.",
            )
            return await ctx.send(embed=embed)

        try:
            await self.bot.db.remove_ticket_config(ctx.guild.id, ticket_type)
        except Exception as e:
            embed = EmbedBuilder.error(
                "Ticket Type Removal Failed",
                f"There was an error removing the ticket type. Please contact a server administrator.\n\n`{e}`",
            )
            return await ctx.send(embed=embed)

        embed = EmbedBuilder.success(
            "Ticket Type Removed", f"Ticket type `{ticket_type}` has been removed."
        )
        await ctx.send(embed=embed)

        # Log to log channel
        log_message = f"{ctx.author.mention} removed ticket type `{ticket_type}`"
        await log_to_channel(self.bot, ctx.guild.id, log_message, "ticket")

    @ticket_type_group.command(name="edit")
    @has_permissions(manage_guild=True)
    async def edit_ticket_type(
        self,
        ctx,
        ticket_type: str,
        *,
        options: str,
    ):
        """
        Edits a ticket type.

        Usage:
            !ticket type edit <ticket_type> option1=value1 option2=value2

        Options:
            display_name: The name that will be displayed on the ticket panel.
            description: The description that will be displayed on the ticket panel.
            emoji: The emoji that will be displayed on the ticket panel.
            category: The category that the ticket will be created in.
            support_role: The role that will be pinged when a ticket is created.
            use_modal: Whether or not to use a modal when creating a ticket. (True/False)
            slowmode: The slowmode delay in seconds.
            intro_message: The message that will be sent when a ticket is created.
            name: The name of the ticket channel.
        """
        if not await self.bot.db.get_ticket_config(ctx.guild.id, ticket_type):
            embed = EmbedBuilder.error(
                "Ticket Type Edit Failed",
                "A ticket type with that name does not exist. Please use a different name.",
            )
            return await ctx.send(embed=embed)

        # Parse options
        option_dict = {}
        options = options.split(" ")
        for option in options:
            try:
                option_name, option_value = option.split("=")
                option_dict[option_name] = option_value
            except ValueError:
                embed = EmbedBuilder.error(
                    "Ticket Type Edit Failed",
                    "Invalid option format. Please use `option=value`.",
                )
                return await ctx.send(embed=embed)

        # Edit ticket type
        try:
            await self.bot.db.edit_ticket_config(ctx.guild.id, ticket_type, option_dict)
        except Exception as e:
            embed = EmbedBuilder.error(
                "Ticket Type Edit Failed",
                f"There was an error editing the ticket type. Please contact a server administrator.\n\n`{e}`",
            )
            return await ctx.send(embed=embed)

        embed = EmbedBuilder.success(
            "Ticket Type Edited", f"Ticket type `{ticket_type}` has been edited."
        )
        await ctx.send(embed=embed)

        # Log to log channel
        log_message = f"{ctx.author.mention} edited ticket type `{ticket_type}`"
        await log_to_channel(self.bot, ctx.guild.id, log_message, "ticket")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: Interaction):
        if interaction.custom_id == "close_ticket":
            channel = interaction.channel
            guild = interaction.guild
            user = interaction.user

            # Check if the user has permission to close the ticket
            ticket_owner = await get_ticket_owner(self.bot, channel.id)
            if ticket_owner:
                ticket_owner = guild.get_member(int(ticket_owner))

            if not is_support_staff(interaction.guild, interaction.user):
                if ticket_owner != user:
                    embed = EmbedBuilder.error(
                        "Ticket Close Failed",
                        "You do not have permission to close this ticket.",
                    )
                    return await interaction.response.send_message(
                        embed=embed, ephemeral=True
                    )

            # Close the ticket
            embed = EmbedBuilder.success(
                "Ticket Closed", f"This ticket has been closed by {user.mention}."
            )
            await interaction.response.send_message(embed=embed)

            # Delete the ticket after 5 seconds
            await asyncio.sleep(5)
            try:
                await channel.delete()
            except Exception as e:
                log.error(f"Error deleting ticket {channel.id}: {e}")

            # Remove ticket from database
            try:
                await self.bot.db.remove_ticket(channel.id)
            except Exception as e:
                log.error(f"Error removing ticket from database: {e}")

            # Log to log channel
            log_message = f"{user.mention} closed ticket `{channel.name}`"
            await log_to_channel(self.bot, guild.id, log_message, "ticket")

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
    
        # Respond to user first to avoid timeout
        response_embed = EmbedBuilder.success(
            "Request Sent",
            f"Your request to join ticket {ticket_id} has been sent. You'll be notified if it's accepted.\n"
            f"Requests made: {request_count + 1}/5"
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
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Railway Bot")
    
        view = TicketJoinRequestView(self.bot, interaction.user, channel)
    
        # Send request to ticket channel
        await channel.send(embed=embed, view=view)
    
        # Log the request to prevent spam - use UPSERT to handle duplicates
        request_data = {
            'ticket_id': ticket_id,
            'requested_at': datetime.utcnow().isoformat(),
            'channel_id': str(channel.id)
        }

        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO user_data (user_id, guild_id, data_type, data_content)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (user_id, guild_id, data_type) 
                       DO UPDATE SET data_content = $4, updated_at = CURRENT_TIMESTAMP""",
                    str(interaction.user.id), str(interaction.guild.id), 'ticket_join_request', json.dumps(request_data)
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO user_data (user_id, guild_id, data_type, data_content)
                       VALUES (?, ?, ?, ?)""",
                    (str(interaction.user.id), str(interaction.guild.id), 'ticket_join_request', json.dumps(request_data))
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error logging join request: {e}")
            # Continue anyway since the request was already sent and user was notified

async def setup(bot):
    await bot.add_cog(Tickets(bot))
