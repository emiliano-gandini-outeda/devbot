import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
from datetime import datetime, timedelta
import asyncio
from utils.helpers import EmbedBuilder, TimeParser
from config.constants import ReminderType

class Reminders(commands.Cog):
    """Reminder system for users and channels"""
    
    def __init__(self, bot):
        self.bot = bot
        self.check_reminders.start()
    
    def cog_unload(self):
        self.check_reminders.cancel()
    
    @tasks.loop(minutes=1)
    async def check_reminders(self):
        """Check for due reminders every minute"""
        try:
            current_time = datetime.utcnow()
            
            if self.bot.db.is_postgresql:
                due_reminders = await self.bot.db.connection.fetch(
                    "SELECT * FROM reminders WHERE remind_at <= $1",
                    current_time
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM reminders WHERE remind_at <= ?",
                    (current_time,)
                )
                due_reminders = await cursor.fetchall()
            
            for reminder in due_reminders:
                await self.send_reminder(reminder)
                
                # Delete non-recurring reminders
                recurring = reminder['recurring'] if self.bot.db.is_postgresql else reminder[7]
                reminder_id = reminder['id'] if self.bot.db.is_postgresql else reminder[0]
                
                if not recurring:
                    if self.bot.db.is_postgresql:
                        await self.bot.db.connection.execute(
                            "DELETE FROM reminders WHERE id = $1", reminder_id
                        )
                    else:
                        await self.bot.db.connection.execute(
                            "DELETE FROM reminders WHERE id = ?", (reminder_id,)
                        )
                else:
                    # Handle recurring reminders (basic implementation)
                    next_remind = current_time + timedelta(days=1)  # Daily recurrence
                    if self.bot.db.is_postgresql:
                        await self.bot.db.connection.execute(
                            "UPDATE reminders SET remind_at = $1 WHERE id = $2",
                            next_remind, reminder_id
                        )
                    else:
                        await self.bot.db.connection.execute(
                            "UPDATE reminders SET remind_at = ? WHERE id = ?",
                            (next_remind, reminder_id)
                        )
            
            if due_reminders and not self.bot.db.is_postgresql:
                await self.bot.db.connection.commit()
                
        except Exception as e:
            print(f"Error checking reminders: {e}")
    
    async def send_reminder(self, reminder):
        """Send a reminder to the appropriate channel/user"""
        try:
            if self.bot.db.is_postgresql:
                user_id = reminder['user_id']
                guild_id = reminder['guild_id']
                channel_id = reminder['channel_id']
                message = reminder['message']
                remind_at = reminder['remind_at']
                reminder_type = reminder['type']
            else:
                user_id = reminder[1]
                guild_id = reminder[2]
                channel_id = reminder[3]
                message = reminder[4]
                remind_at = reminder[5]
                reminder_type = reminder[6]
            
            user = self.bot.get_user(int(user_id))
            if not user:
                return
            
            embed = discord.Embed(
                title="⏰ Reminder",
                description=message,
                color=0xFEE75C
            )
            embed.set_footer(text=f"Reminder set for {remind_at} • Railway 🚄")
            
            if reminder_type == ReminderType.PERSONAL.value:
                # Send DM
                try:
                    await user.send(embed=embed)
                except discord.Forbidden:
                    # If DM fails, try to send in guild channel
                    if guild_id:
                        guild = self.bot.get_guild(int(guild_id))
                        if guild:
                            channel = guild.system_channel or guild.text_channels[0]
                            await channel.send(f"{user.mention}", embed=embed)
            else:
                # Send in channel
                if channel_id:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        await channel.send(f"{user.mention}", embed=embed)
                        
        except Exception as e:
            print(f"Error sending reminder: {e}")
    
    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()
    
    @app_commands.command(name="remind", description="Set a personal reminder")
    @app_commands.describe(
        time="When to remind (e.g., '1h', '30m', '2d')",
        message="Reminder message"
    )
    async def remind(self, interaction: discord.Interaction, time: str, message: str):
        duration = TimeParser.parse_duration(time)
        if not duration:
            embed = EmbedBuilder.error(
                "Invalid Time Format",
                "Please use format like: `1h`, `30m`, `2d`, `1h30m`"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if time is within the 9-year limit
        nine_years_seconds = 9 * 365.25 * 24 * 60 * 60  # Approximately 9 years in seconds
        if duration.total_seconds() > nine_years_seconds:
            embed = EmbedBuilder.error(
                "Time Limit Exceeded",
                "Reminder time cannot exceed 9 years."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        remind_at = datetime.utcnow() + duration
        
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO reminders (user_id, guild_id, channel_id, message, remind_at, type, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    str(interaction.user.id), str(interaction.guild.id), str(interaction.channel.id),
                    message, remind_at, ReminderType.PERSONAL.value, datetime.utcnow()
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT INTO reminders (user_id, guild_id, channel_id, message, remind_at, type, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (str(interaction.user.id), str(interaction.guild.id), str(interaction.channel.id),
                     message, remind_at, ReminderType.PERSONAL.value, datetime.utcnow())
                )
                await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Reminder Set",
                f"I'll remind you about: **{message}**\n"
                f"**When:** {remind_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"**In:** {time}"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to set reminder: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="remind-channel", description="Set a channel reminder")
    @app_commands.describe(
        time="When to remind (e.g., '1h', '30m', '2d')",
        message="Reminder message",
        channel="Channel to send reminder to"
    )
    async def remind_channel(self, interaction: discord.Interaction, time: str, message: str, channel: discord.TextChannel = None):
        if not channel:
            channel = interaction.channel
        
        duration = TimeParser.parse_duration(time)
        if not duration:
            embed = EmbedBuilder.error(
                "Invalid Time Format",
                "Please use format like: `1h`, `30m`, `2d`, `1h30m`"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if time is within the 9-year limit
        nine_years_seconds = 9 * 365.25 * 24 * 60 * 60  # Approximately 9 years in seconds
        if duration.total_seconds() > nine_years_seconds:
            embed = EmbedBuilder.error(
                "Time Limit Exceeded",
                "Reminder time cannot exceed 9 years."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        remind_at = datetime.utcnow() + duration
        
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO reminders (user_id, guild_id, channel_id, message, remind_at, type, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    str(interaction.user.id), str(interaction.guild.id), str(channel.id),
                    message, remind_at, ReminderType.CHANNEL.value, datetime.utcnow()
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT INTO reminders (user_id, guild_id, channel_id, message, remind_at, type, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (str(interaction.user.id), str(interaction.guild.id), str(channel.id),
                     message, remind_at, ReminderType.CHANNEL.value, datetime.utcnow())
                )
                await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Channel Reminder Set",
                f"I'll remind in {channel.mention} about: **{message}**\n"
                f"**When:** {remind_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"**In:** {time}"
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to set reminder: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="edit-reminder", description="Edit an existing reminder")
    @app_commands.describe(
        reminder_number="Number of the reminder to edit (from /list-reminders)",
        new_time="New time for the reminder (optional, e.g., '1h', '30m', '2d')",
        new_message="New message for the reminder (optional)"
    )
    async def edit_reminder(
        self, 
        interaction: discord.Interaction, 
        reminder_number: int, 
        new_time: str = None, 
        new_message: str = None
    ):
        if not new_time and not new_message:
            embed = EmbedBuilder.error(
                "Missing Parameters",
                "You must provide either a new time or a new message."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        try:
            # Get the reminder
            if self.bot.db.is_postgresql:
                reminder = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM reminders WHERE user_id = $1 ORDER BY remind_at ASC LIMIT 1 OFFSET $2",
                    str(interaction.user.id), reminder_number - 1
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM reminders WHERE user_id = ? ORDER BY remind_at ASC LIMIT 1 OFFSET ?",
                    (str(interaction.user.id), reminder_number - 1)
                )
                reminder = await cursor.fetchone()
            
            if not reminder:
                embed = EmbedBuilder.error("Not Found", f"Reminder #{reminder_number} not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
            # Extract current values
            reminder_id = reminder['id'] if self.bot.db.is_postgresql else reminder[0]
            current_message = reminder['message'] if self.bot.db.is_postgresql else reminder[4]
            current_remind_at = reminder['remind_at'] if self.bot.db.is_postgresql else reminder[5]
            
            # Calculate new remind_at if time is provided
            new_remind_at = current_remind_at
            if new_time:
                duration = TimeParser.parse_duration(new_time)
                if not duration:
                    embed = EmbedBuilder.error(
                        "Invalid Time Format",
                        "Please use format like: `1h`, `30m`, `2d`, `1h30m`"
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                    
                new_remind_at = datetime.utcnow() + duration
                
                # Check if time is within the 9-year limit
                nine_years_seconds = 9 * 365.25 * 24 * 60 * 60  # Approximately 9 years in seconds
                if duration.total_seconds() > nine_years_seconds:
                    embed = EmbedBuilder.error(
                        "Time Limit Exceeded",
                        "Reminder time cannot exceed 9 years."
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
            
            # Use provided message or keep existing one
            final_message = new_message if new_message else current_message
            
            # Update the reminder in the database
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "UPDATE reminders SET message = $1, remind_at = $2 WHERE id = $3",
                    final_message, new_remind_at, reminder_id
                )
            else:
                await self.bot.db.connection.execute(
                    "UPDATE reminders SET message = ?, remind_at = ? WHERE id = ?",
                    (final_message, new_remind_at, reminder_id)
                )
                await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Reminder Updated",
                f"**Original Message:** {current_message}\n" +
                (f"**New Message:** {final_message}\n" if new_message else "") +
                (f"**New Time:** {new_remind_at.strftime('%Y-%m-%d %H:%M UTC')}" if new_time else "")
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to edit reminder: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="list-reminders", description="List your active reminders")
    async def list_reminders(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            if self.bot.db.is_postgresql:
                reminders = await self.bot.db.connection.fetch(
                    "SELECT * FROM reminders WHERE user_id = $1 ORDER BY remind_at ASC",
                    str(interaction.user.id)
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM reminders WHERE user_id = ? ORDER BY remind_at ASC",
                    (str(interaction.user.id),)
                )
                reminders = await cursor.fetchall()
            
            if not reminders:
                embed = EmbedBuilder.info("No Reminders", "You don't have any active reminders")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Create reminder list view with delete buttons
            view = ReminderListView(self.bot, reminders, self.bot.db.is_postgresql, interaction.user.id)
            
            embed = discord.Embed(
                title="⏰ Your Reminders",
                color=0xFEE75C
            )
            
            for i, reminder in enumerate(reminders[:10], 1):  # Show first 10
                if self.bot.db.is_postgresql:
                    message = reminder['message']
                    remind_time = reminder['remind_at']
                    reminder_id = reminder['id']
                else:
                    message = reminder[4]
                    remind_time = datetime.fromisoformat(reminder[5].replace('Z', '+00:00')) if isinstance(reminder[5], str) else reminder[5]
                    reminder_id = reminder[0]
                
                time_left = remind_time - datetime.utcnow()
                
                if time_left.total_seconds() > 0:
                    time_str = f"In {self.format_timedelta(time_left)}"
                else:
                    time_str = "Overdue"
                
                embed.add_field(
                    name=f"{i}. {message[:50]}{'...' if len(message) > 50 else ''}",
                    value=f"**When:** {remind_time.strftime('%Y-%m-%d %H:%M UTC')}\n**Status:** {time_str}\n**ID:** {reminder_id}",
                    inline=False
                )
            
            embed.set_footer(text="Powered by Railway 🚄 • Use buttons below to delete reminders")
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch reminders: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="delete-reminder", description="Delete a reminder by its number")
    @app_commands.describe(reminder_number="Number of the reminder to delete (from /list-reminders)")
    async def delete_reminder(self, interaction: discord.Interaction, reminder_number: int):
        try:
            if self.bot.db.is_postgresql:
                reminder = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM reminders WHERE user_id = $1 ORDER BY remind_at ASC LIMIT 1 OFFSET $2",
                    str(interaction.user.id), reminder_number - 1
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM reminders WHERE user_id = ? ORDER BY remind_at ASC LIMIT 1 OFFSET ?",
                    (str(interaction.user.id), reminder_number - 1)
                )
                reminder = await cursor.fetchone()
            
            if not reminder:
                embed = EmbedBuilder.error("Not Found", f"Reminder #{reminder_number} not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            reminder_id = reminder['id'] if self.bot.db.is_postgresql else reminder[0]
            reminder_message = reminder['message'] if self.bot.db.is_postgresql else reminder[4]
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "DELETE FROM reminders WHERE id = $1", reminder_id
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM reminders WHERE id = ?", (reminder_id,)
                )
                await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Reminder Deleted",
                f"Deleted reminder: **{reminder_message}**"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to delete reminder: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    def format_timedelta(self, td):
        """Format timedelta to human readable string"""
        total_seconds = int(td.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        
        return " ".join(parts) if parts else "< 1m"

class ReminderListView(discord.ui.View):
    def __init__(self, bot, reminders, is_postgresql, user_id):
        super().__init__(timeout=60)
        self.bot = bot
        self.reminders = reminders
        self.is_postgresql = is_postgresql
        self.user_id = user_id
        
        # Add buttons for each reminder (up to 5 to avoid cluttering the UI)
        for i, reminder in enumerate(reminders[:5], 1):
            reminder_id = reminder['id'] if is_postgresql else reminder[0]
            button = DeleteReminderButton(i, reminder_id)
            self.add_item(button)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.user_id

class DeleteReminderButton(discord.ui.Button):
    def __init__(self, number, reminder_id):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label=f"Delete #{number}",
            custom_id=f"delete_reminder_{reminder_id}"
        )
        self.reminder_id = reminder_id
    
    async def callback(self, interaction: discord.Interaction):
        try:
            bot = interaction.client
            if bot.db.is_postgresql:
                # First get the reminder to confirm it exists
                reminder = await bot.db.connection.fetchrow(
                    "SELECT * FROM reminders WHERE id = $1 AND user_id = $2",
                    self.reminder_id, str(interaction.user.id)
                )
                
                if reminder:
                    await bot.db.connection.execute(
                        "DELETE FROM reminders WHERE id = $1", self.reminder_id
                    )
            else:
                cursor = await bot.db.connection.execute(
                    "SELECT * FROM reminders WHERE id = ? AND user_id = ?",
                    (self.reminder_id, str(interaction.user.id))
                )
                reminder = await cursor.fetchone()
                
                if reminder:
                    await bot.db.connection.execute(
                        "DELETE FROM reminders WHERE id = ?", (self.reminder_id,)
                    )
                    await bot.db.connection.commit()
            
            if reminder:
                embed = EmbedBuilder.success(
                    "Reminder Deleted",
                    f"Reminder #{self.custom_id.split('_')[-1]} has been deleted."
                )
            else:
                embed = EmbedBuilder.error(
                    "Not Found", 
                    "Reminder not found or already deleted."
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to delete reminder: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Reminders(bot))
