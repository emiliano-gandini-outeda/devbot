import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
import datetime
import traceback
import io
import contextlib
import textwrap
from typing import Optional

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_inactive_tickets.start()

    # Utility Functions
    async def get_ticket_config(self, guild_id: int):
        """Retrieves the ticket configuration for a guild from the database."""
        query = "SELECT config_data FROM ticket_configs WHERE guild_id = $1" if self.bot.db.is_postgresql else "SELECT config_data FROM ticket_configs WHERE guild_id = ?"
        result = await self.bot.db.fetch_one(query, str(guild_id))
        if result:
            return json.loads(result[0])
        return None

    async def set_ticket_config(self, guild_id: int, config_data: dict):
        """Sets the ticket configuration for a guild in the database."""
        query = """
            INSERT INTO ticket_configs (guild_id, config_data)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET config_data = $2
        """ if self.bot.db.is_postgresql else """
            INSERT OR REPLACE INTO ticket_configs (guild_id, config_data)
            VALUES (?, ?)
        """
        await self.bot.db.execute(query, str(guild_id), json.dumps(config_data))
        if not self.bot.db.is_postgresql:
            await self.bot.db.connection.commit()

    async def get_open_tickets(self, guild_id: int):
        """Retrieves all open tickets for a guild from the database."""
        query = "SELECT channel_id FROM tickets WHERE guild_id = $1 AND status = 'open'" if self.bot.db.is_postgresql else "SELECT channel_id FROM tickets WHERE guild_id = ? AND status = 'open'"
        results = await self.bot.db.fetch_all(query, str(guild_id))
        return [result[0] for result in results]

    async def create_ticket_channel(self, guild: discord.Guild, config: dict, user: discord.Member, ticket_id: str):
        """Creates a new ticket channel."""
        category_id = config.get('category_id')
        if not category_id:
            return None

        category = guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            return None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
        }

        channel_name = config.get('channel_name', 'ticket-{id}').replace('{id}', ticket_id)
        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Ticket created by {user.mention} | Ticket ID: {ticket_id}"
            )
            return channel
        except discord.Forbidden:
            return None
        except discord.HTTPException:
            return None

    async def log_ticket_action(self, guild_id: int, action: str, ticket_id: str, user_id: str, details: str = None):
        """Logs a ticket action to the database."""
        query = """
            INSERT INTO ticket_logs (guild_id, ticket_id, user_id, action, details, timestamp)
            VALUES ($1, $2, $3, $4, $5, $6)
        """ if self.bot.db.is_postgresql else """
            INSERT INTO ticket_logs (guild_id, ticket_id, user_id, action, details, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        await self.bot.db.execute(query, str(guild_id), ticket_id, user_id, action, details, datetime.datetime.utcnow())
        if not self.bot.db.is_postgresql:
            await self.bot.db.connection.commit()

    async def send_ticket_log_message(self, guild: discord.Guild, config: dict, action: str, ticket_id: str, user: discord.User, details: str = None):
        """Sends a message to the ticket log channel."""
        log_channel_id = config.get('log_channel_id')
        if not log_channel_id:
            return

        log_channel = guild.get_channel(int(log_channel_id))
        if not isinstance(log_channel, discord.TextChannel):
            return

        embed = discord.Embed(title=f"Ticket {action.title()}", color=discord.Color.blue())
        embed.add_field(name="Ticket ID", value=ticket_id, inline=False)
        embed.add_field(name="User", value=user.mention, inline=False)
        if details:
            embed.add_field(name="Details", value=details, inline=False)
        embed.timestamp = datetime.datetime.utcnow()

        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            pass

    async def close_ticket(self, channel: discord.TextChannel, closer: discord.User, reason: str = None):
        """Closes a ticket channel."""
        ticket_id = channel.topic.split("Ticket ID: ")[1] if channel.topic and "Ticket ID: " in channel.topic else None
        if not ticket_id:
            await channel.send("Could not determine ticket ID.  Please ensure the channel topic is set correctly.")
            return

        guild_id = str(channel.guild.id)

        # Update ticket status in the database
        query = "UPDATE tickets SET status = 'closed' WHERE guild_id = $1 AND channel_id = $2" if self.bot.db.is_postgresql else "UPDATE tickets SET status = 'closed' WHERE guild_id = ? AND channel_id = ?"
        await self.bot.db.execute(query, guild_id, str(channel.id))
        if not self.bot.db.is_postgresql:
            await self.bot.db.connection.commit()

        # Log the closure
        await self.log_ticket_action(guild_id, "closed", ticket_id, str(closer.id), reason)

        # Send log message
        config = await self.get_ticket_config(int(guild_id))
        if config:
            await self.send_ticket_log_message(channel.guild, config, "closed", ticket_id, closer, reason)

        # Archive the channel (optional, based on config)
        if config and config.get('archive_channel_id'):
            archive_channel_id = config['archive_channel_id']
            archive_channel = channel.guild.get_channel(int(archive_channel_id))
            if isinstance(archive_channel, discord.TextChannel):
                transcript = await self.generate_transcript(channel)
                if transcript:
                    try:
                        await archive_channel.send(f"Ticket {ticket_id} closed by {closer.mention}. Reason: {reason or 'No reason provided'}", file=discord.File(io.StringIO(transcript), filename=f"ticket-{ticket_id}.txt"))
                    except discord.errors.HTTPException:
                        await archive_channel.send(f"Ticket {ticket_id} closed by {closer.mention}. Reason: {reason or 'No reason provided'}. Transcript too large to send.")
                else:
                    await archive_channel.send(f"Ticket {ticket_id} closed by {closer.mention}. Reason: {reason or 'No reason provided'}. Could not generate transcript.")

        try:
            await channel.delete(reason=f"Ticket closed by {closer.name}: {reason or 'No reason provided'}")
        except discord.Forbidden:
            await channel.send("I do not have permissions to delete this channel.")
        except discord.HTTPException:
            await channel.send("Failed to delete the channel.")

    async def generate_transcript(self, channel: discord.TextChannel):
        """Generates a transcript of the ticket channel."""
        try:
            messages = []
            async for message in channel.history(limit=None, oldest_first=True):
                timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
                content = message.content.replace("\n", "\n> ")  # Add "> " to each new line
                messages.append(f"{timestamp} - {message.author.name}#{message.author.discriminator}: {content}")
                if message.attachments:
                    for attachment in message.attachments:
                        messages.append(f"{timestamp} - {message.author.name}#{message.author.discriminator}: Attachment: {attachment.url}")

            return "\n".join(messages)
        except Exception as e:
            print(f"Error generating transcript: {e}")
            return None

    # Commands and Listeners
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Handles reaction adds for ticket creation."""
        if payload.member.bot:
            return

        guild_id = str(payload.guild_id)
        config = await self.get_ticket_config(int(guild_id))
        if not config:
            return

        if str(payload.message_id) != config.get('message_id'):
            return

        if str(payload.emoji) != config.get('emoji'):
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        # Check if the user already has an open ticket
        open_tickets = await self.get_open_tickets(int(guild_id))
        for ticket_channel_id in open_tickets:
            ticket_channel = guild.get_channel(int(ticket_channel_id))
            if ticket_channel and ticket_channel.topic and str(member.id) in ticket_channel.topic:
                try:
                    await channel.send(f"{member.mention}, you already have an open ticket: {ticket_channel.mention}", delete_after=10)
                except discord.Forbidden:
                    pass
                except discord.HTTPException:
                    pass
                try:
                    await channel.remove_reaction(payload.emoji, member)
                except discord.Forbidden:
                    pass
                except discord.HTTPException:
                    pass
                return

        # Create the ticket
        ticket_id = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
        new_channel = await self.create_ticket_channel(guild, config, member, ticket_id)
        if not new_channel:
            try:
                await channel.send(f"{member.mention}, failed to create a ticket. Please contact an administrator.", delete_after=10)
            except discord.Forbidden:
                pass
            except discord.HTTPException:
                pass
            try:
                await channel.remove_reaction(payload.emoji, member)
            except discord.Forbidden:
                pass
            except discord.HTTPException:
                pass
            return

        # Store ticket information in the database
        query = """
            INSERT INTO tickets (guild_id, channel_id, user_id, ticket_id, status)
            VALUES ($1, $2, $3, $4, 'open')
        """ if self.bot.db.is_postgresql else """
            INSERT INTO tickets (guild_id, channel_id, user_id, ticket_id, status)
            VALUES (?, ?, ?, ?, 'open')
        """
        await self.bot.db.execute(query, guild_id, str(new_channel.id), str(member.id), ticket_id)
        if not self.bot.db.is_postgresql:
            await self.bot.db.connection.commit()

        # Log the ticket creation
        await self.log_ticket_action(guild_id, "created", ticket_id, str(member.id))

        # Send log message
        await self.send_ticket_log_message(guild, config, "created", ticket_id, member)

        # Send initial message to the ticket channel
        embed = discord.Embed(title="New Ticket", description=config.get('initial_message', 'Thank you for creating a ticket!  Please describe your issue.'), color=discord.Color.green())
        embed.add_field(name="User", value=member.mention, inline=False)
        embed.add_field(name="Ticket ID", value=ticket_id, inline=False)
        embed.timestamp = datetime.datetime.utcnow()
        try:
            await new_channel.send(f"{member.mention}", embed=embed)
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            pass

        try:
            await channel.remove_reaction(payload.emoji, member)
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            pass

    @app_commands.command(name="ticketsetup", description="Setup the ticket system.")
    @app_commands.describe(channel="The channel to send the ticket message to.")
    @app_commands.describe(category="The category to create tickets in.")
    @app_commands.describe(message="The message to send with the ticket reaction.")
    @app_commands.describe(emoji="The emoji to use for the ticket reaction.")
    @app_commands.describe(log_channel="The channel to send ticket logs to.")
    @app_commands.describe(archive_channel="The channel to archive closed tickets to.")
    async def ticket_setup(self, interaction: discord.Interaction,
                            channel: discord.TextChannel,
                            category: discord.CategoryChannel,
                            message: str,
                            emoji: str,
                            log_channel: Optional[discord.TextChannel] = None,
                            archive_channel: Optional[discord.TextChannel] = None):
        """Sets up the ticket system."""
        config = {
            'message_id': None,
            'channel_id': str(channel.id),
            'category_id': str(category.id),
            'message': message,
            'emoji': emoji,
            'log_channel_id': str(log_channel.id) if log_channel else None,
            'archive_channel_id': str(archive_channel.id) if archive_channel else None
        }

        embed = discord.Embed(title="Ticket System", description=message, color=discord.Color.blue())
        try:
            ticket_message = await channel.send(embed=embed)
            await ticket_message.add_reaction(emoji)
            config['message_id'] = str(ticket_message.id)
        except discord.Forbidden:
            await interaction.response.send_message("I do not have permissions to send messages or add reactions in that channel.", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.response.send_message("Failed to send the message or add the reaction.", ephemeral=True)
            return

        await self.set_ticket_config(interaction.guild.id, config)
        await interaction.response.send_message("Ticket system setup successfully!", ephemeral=True)

    @app_commands.command(name="close", description="Close the current ticket.")
    @app_commands.describe(reason="The reason for closing the ticket.")
    async def ticket_close(self, interaction: discord.Interaction, reason: str = None):
        """Closes the current ticket."""
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command can only be used in a text channel.", ephemeral=True)
            return

        if not interaction.channel.topic or "Ticket ID: " not in interaction.channel.topic:
            await interaction.response.send_message("This is not a valid ticket channel.", ephemeral=True)
            return

        await self.close_ticket(interaction.channel, interaction.user, reason)
        await interaction.response.send_message("Closing ticket...", ephemeral=True)

    @app_commands.command(name="add", description="Add a user to the current ticket.")
    @app_commands.describe(user="The user to add to the ticket.")
    async def ticket_add(self, interaction: discord.Interaction, user: discord.Member):
        """Adds a user to the current ticket."""
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command can only be used in a text channel.", ephemeral=True)
            return

        if not interaction.channel.topic or "Ticket ID: " not in interaction.channel.topic:
            await interaction.response.send_message("This is not a valid ticket channel.", ephemeral=True)
            return

        try:
            await interaction.channel.set_permissions(user, view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
            await interaction.response.send_message(f"{user.mention} has been added to the ticket.", ephemeral=True)
            ticket_id = interaction.channel.topic.split("Ticket ID: ")[1]
            await self.log_ticket_action(str(interaction.guild.id), "user_added", ticket_id, str(interaction.user.id), f"User added: {user.id}")
            config = await self.get_ticket_config(interaction.guild.id)
            if config:
                await self.send_ticket_log_message(interaction.guild, config, "user_added", ticket_id, interaction.user, f"User added: {user.id}")

        except discord.Forbidden:
            await interaction.response.send_message("I do not have permissions to manage channel permissions.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("Failed to add the user to the ticket.", ephemeral=True)

    @app_commands.command(name="remove", description="Remove a user from the current ticket.")
    @app_commands.describe(user="The user to remove from the ticket.")
    async def ticket_remove(self, interaction: discord.Interaction, user: discord.Member):
        """Removes a user from the current ticket."""
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command can only be used in a text channel.", ephemeral=True)
            return

        if not interaction.channel.topic or "Ticket ID: " not in interaction.channel.topic:
            await interaction.response.send_message("This is not a valid ticket channel.", ephemeral=True)
            return

        try:
            await interaction.channel.set_permissions(user, view_channel=False)
            await interaction.response.send_message(f"{user.mention} has been removed from the ticket.", ephemeral=True)
            ticket_id = interaction.channel.topic.split("Ticket ID: ")[1]
            await self.log_ticket_action(str(interaction.guild.id), "user_removed", ticket_id, str(interaction.user.id), f"User removed: {user.id}")
            config = await self.get_ticket_config(interaction.guild.id)
            if config:
                await self.send_ticket_log_message(interaction.guild, config, "user_removed", ticket_id, interaction.user, f"User removed: {user.id}")

        except discord.Forbidden:
            await interaction.response.send_message("I do not have permissions to manage channel permissions.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("Failed to remove the user from the ticket.", ephemeral=True)

    @app_commands.command(name="rename", description="Rename the current ticket channel.")
    @app_commands.describe(name="The new name for the channel.")
    async def ticket_rename(self, interaction: discord.Interaction, name: str):
        """Renames the current ticket channel."""
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command can only be used in a text channel.", ephemeral=True)
            return

        if not interaction.channel.topic or "Ticket ID: " not in interaction.channel.topic:
            await interaction.response.send_message("This is not a valid ticket channel.", ephemeral=True)
            return

        try:
            await interaction.channel.edit(name=name)
            await interaction.response.send_message(f"The channel has been renamed to {name}.", ephemeral=True)
            ticket_id = interaction.channel.topic.split("Ticket ID: ")[1]
            await self.log_ticket_action(str(interaction.guild.id), "renamed", ticket_id, str(interaction.user.id), f"Channel renamed to: {name}")
            config = await self.get_ticket_config(interaction.guild.id)
            if config:
                await self.send_ticket_log_message(interaction.guild, config, "renamed", ticket_id, interaction.user, f"Channel renamed to: {name}")

        except discord.Forbidden:
            await interaction.response.send_message("I do not have permissions to rename this channel.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("Failed to rename the channel.", ephemeral=True)

    @app_commands.command(name="ticket_join", description="Request to join a ticket.")
    @app_commands.describe(ticket_id="The ID of the ticket you want to join.")
    async def ticket_join(self, interaction: discord.Interaction, ticket_id: str):
        """Requests to join a ticket."""
        guild_id = str(interaction.guild.id)

        # Check if the ticket exists
        query = "SELECT channel_id FROM tickets WHERE guild_id = $1 AND ticket_id = $2" if self.bot.db.is_postgresql else "SELECT channel_id FROM tickets WHERE guild_id = ? AND ticket_id = ?"
        result = await self.bot.db.fetch_one(query, guild_id, ticket_id)
        if not result:
            await interaction.response.send_message("Invalid ticket ID.", ephemeral=True)
            return

        channel_id = result[0]
        channel = interaction.guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("The ticket channel does not exist.", ephemeral=True)
            return

        # Check if the user is already in the ticket
        if interaction.user in channel.members:
            await interaction.response.send_message("You are already in this ticket.", ephemeral=True)
            return

        # Check if a join request already exists
        query = "SELECT data_content FROM user_data WHERE user_id = $1 AND guild_id = $2 AND data_type = 'ticket_join_request'" if self.bot.db.is_postgresql else "SELECT data_content FROM user_data WHERE user_id = ? AND guild_id = ? AND data_type = 'ticket_join_request'"
        existing_request = await self.bot.db.fetch_one(query, str(interaction.user.id), guild_id)
        if existing_request:
            existing_data = json.loads(existing_request[0])
            if existing_data.get('ticket_id') == ticket_id:
                await interaction.response.send_message("You have already requested to join this ticket.", ephemeral=True)
                return

        # Store the join request in the database
        request_data = {
            'ticket_id': ticket_id,
            'user_id': str(interaction.user.id),
            'timestamp': datetime.datetime.utcnow().isoformat()
        }

        # Replace the PostgreSQL insert with:
        if self.bot.db.is_postgresql:
            await self.bot.db.connection.execute(
                """INSERT INTO user_data (user_id, guild_id, data_type, data_content)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (user_id, guild_id, data_type) DO NOTHING""",
                str(interaction.user.id), str(interaction.guild.id), 'ticket_join_request', json.dumps(request_data)
            )
        else:
            await self.bot.db.connection.execute(
                """INSERT OR IGNORE INTO user_data (user_id, guild_id, data_type, data_content)
           VALUES (?, ?, ?, ?)""",
                (str(interaction.user.id), str(interaction.guild.id), 'ticket_join_request', json.dumps(request_data))
            )
            await self.bot.db.connection.commit()

        # Notify the ticket channel
        await interaction.response.send_message("Your request to join the ticket has been sent.", ephemeral=True)
        await channel.send(f"{interaction.user.mention} has requested to join this ticket.  Please use `/add` to add them.")

    @tasks.loop(minutes=60)
    async def check_inactive_tickets(self):
        """Checks for inactive tickets and sends a reminder."""
        for guild in self.bot.guilds:
            config = await self.get_ticket_config(guild.id)
            if not config or not config.get('inactive_reminder'):
                continue

            inactive_days = config.get('inactive_days', 7)
            reminder_message = config.get('inactive_reminder', "This ticket has been inactive for {days} days.  Please respond or it will be closed.")
            close_after_reminder = config.get('close_after_reminder', 3)

            open_tickets = await self.get_open_tickets(guild.id)
            for channel_id in open_tickets:
                try:
                    channel = guild.get_channel(int(channel_id))
                    if not isinstance(channel, discord.TextChannel):
                        continue

                    last_message = None
                    try:
                        last_message = await channel.history(limit=1).flatten()
                        if last_message:
                            last_message = last_message[0]
                    except discord.Forbidden:
                        continue
                    except discord.HTTPException:
                        continue

                    if not last_message:
                        continue

                    inactive_time = datetime.datetime.utcnow() - last_message.created_at.replace(tzinfo=None)
                    if inactive_time.days >= inactive_days:
                        # Check if a reminder has already been sent
                        reminder_sent = False
                        async for message in channel.history(limit=20):
                            if message.author == self.bot.user and "This ticket has been inactive" in message.content:
                                reminder_sent = True
                                break

                        if not reminder_sent:
                            await channel.send(reminder_message.format(days=inactive_days))

                            # Schedule ticket closure
                            async def close_ticket_task():
                                await asyncio.sleep(close_after_reminder * 24 * 3600)  # Convert days to seconds
                                try:
                                    await self.close_ticket(channel, self.bot.user, reason=f"Ticket inactive for {inactive_days + close_after_reminder} days.")
                                except:
                                    pass # Handle if channel was already deleted

                            self.bot.loop.create_task(close_ticket_task())

                except Exception as e:
                    print(f"Error checking ticket inactivity in guild {guild.id}, channel {channel_id}: {e}")

    @check_inactive_tickets.before_loop
    async def before_check_inactive_tickets(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Tickets(bot))
