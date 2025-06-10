import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import asyncio
from utils.helpers import EmbedBuilder, TimeParser
from config.constants import ReminderType
import logging

logger = logging.getLogger(__name__)

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
            
            # Check if database is available
            if not self.bot.db or not self.bot.db.connection:
                return
            
            # Get due reminders with proper database compatibility
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
                rows = await cursor.fetchall()
                
                # Convert SQLite rows to dict format
                due_reminders = []
                if rows:
                    columns = [description[0] for description in cursor.description]
                    due_reminders = [dict(zip(columns, row)) for row in rows]
            
            for reminder in due_reminders:
                try:
                    await self.send_reminder(reminder)
                    
                    # Delete non-recurring reminders
                    if not reminder.get('recurring', False):
                        if self.bot.db.is_postgresql:
                            await self.bot.db.connection.execute(
                                "DELETE FROM reminders WHERE id = $1", reminder['id']
                            )
                        else:
                            await self.bot.db.connection.execute(
                                "DELETE FROM reminders WHERE id = ?", (reminder['id'],)
                            )
                            await self.bot.db.connection.commit()
                    else:
                        # Handle recurring reminders (basic implementation)
                        next_remind = current_time + timedelta(days=1)  # Daily recurrence
                        if self.bot.db.is_postgresql:
                            await self.bot.db.connection.execute(
                                "UPDATE reminders SET remind_at = $1 WHERE id = $2",
                                next_remind, reminder['id']
                            )
                        else:
                            await self.bot.db.connection.execute(
                                "UPDATE reminders SET remind_at = ? WHERE id = ?",
                                (next_remind, reminder['id'])
                            )
                            await self.bot.db.connection.commit()
                except Exception as e:
                    logger.error(f"Error processing reminder {reminder['id']}: {e}")
            
        except Exception as e:
            if "operation is in progress" not in str(e).lower():
                logger.error(f"Error in check_reminders: {e}")
    
    async def send_reminder(self, reminder):
        """Send a reminder to the appropriate channel/user"""
        try:
            user_id = reminder['user_id']
            guild_id = reminder['guild_id']
            channel_id = reminder['channel_id']
            message = reminder['message']
            remind_at = reminder['remind_at']
            reminder_type = reminder.get('type', 'personal')
            send_dm = reminder.get('send_dm', True)
            
            user = self.bot.get_user(int(user_id))
            if not user:
                return
            
            embed = discord.Embed(
                title="⏰ Reminder",
                description=message,
                color=0xFEE75C
            )
            embed.set_footer(text=f"Reminder set for {remind_at} • Railway Bot")
            
            if reminder_type == ReminderType.PERSONAL.value:
                # Send DM if enabled
                if send_dm:
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
                    # Send in channel only
                    if guild_id:
                        guild = self.bot.get_guild(int(guild_id))
                        if guild:
                            channel = guild.get_channel(int(channel_id)) if channel_id else guild.system_channel or guild.text_channels[0]
                            await channel.send(f"{user.mention}", embed=embed)
            else:
                # Send in channel
                if channel_id:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        await channel.send(f"{user.mention}", embed=embed)
                        
        except Exception as e:
            logger.error(f"Error sending reminder: {e}")
    
    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()
    
    @app_commands.command(name="remind", description="Set a personal reminder")
    @app_commands.describe(
        time="When to remind (e.g., '1h', '30m', '2d')",
        message="Reminder message",
        send_dm="Also send reminder via DM (default: True)"
    )
    async def remind(self, interaction: discord.Interaction, time: str, message: str, send_dm: bool = True):
        duration = TimeParser.parse_duration(time)
        if not duration:
            embed = EmbedBuilder.error(
                "Invalid Time Format",
                "Please use format like: `1h`, `30m`, `2d`, `1h30m`"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if time is within the 9-year limit
        nine_years_seconds = 9 * 365.25 * 24 * 60 * 60
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
                    """INSERT INTO reminders (user_id, guild_id, channel_id, message, remind_at, type, created_at, send_dm)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    str(interaction.user.id), str(interaction.guild.id), str(interaction.channel.id),
                    message, remind_at, ReminderType.PERSONAL.value, datetime.utcnow(), send_dm
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT INTO reminders (user_id, guild_id, channel_id, message, remind_at, type, created_at, send_dm)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(interaction.user.id), str(interaction.guild.id), str(interaction.channel.id),
                     message, remind_at, ReminderType.PERSONAL.value, datetime.utcnow(), send_dm)
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
    
    @app_commands.command(name="remind-channel", description="Set a channel reminder (Admin only)")
    @app_commands.describe(
        time="When to remind (e.g., '1h', '30m', '2d')",
        message="Reminder message",
        channel="Channel to send reminder to"
    )
    async def remind_channel(self, interaction: discord.Interaction, time: str, message: str, channel: discord.TextChannel = None):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can set channel reminders")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
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
                rows = await cursor.fetchall()
                
                # Convert SQLite rows to dict format
                reminders = []
                if rows:
                    columns = [description[0] for description in cursor.description]
                    reminders = [dict(zip(columns, row)) for row in rows]
            
            if not reminders:
                embed = EmbedBuilder.info("No Reminders", "You don't have any active reminders")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            embed = discord.Embed(
                title="⏰ Your Reminders",
                color=0xFEE75C
            )
            
            for i, reminder in enumerate(reminders[:10], 1):  # Show first 10
                message = reminder['message']
                remind_time = reminder['remind_at']
                reminder_id = reminder['id']
                
                # Handle datetime parsing for SQLite
                if isinstance(remind_time, str):
                    remind_time = datetime.fromisoformat(remind_time.replace('Z', '+00:00'))
                
                time_left = remind_time - datetime.utcnow()
                
                if time_left.total_seconds() > 0:
                    time_str = f"In {TimeParser.format_timedelta(time_left)}"
                else:
                    time_str = "Overdue"
                
                embed.add_field(
                    name=f"{i}. {message[:50]}{'...' if len(message) > 50 else ''}",
                    value=f"**When:** {remind_time.strftime('%Y-%m-%d %H:%M UTC')}\n**Status:** {time_str}\n**ID:** {reminder_id}",
                    inline=False
                )
            
            embed.set_footer(text="Railway Bot")
            await interaction.followup.send(embed=embed, ephemeral=True)
            
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
                row = await cursor.fetchone()
                
                reminder = None
                if row:
                    columns = [description[0] for description in cursor.description]
                    reminder = dict(zip(columns, row))
            
            if not reminder:
                embed = EmbedBuilder.error("Not Found", f"Reminder #{reminder_number} not found")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            reminder_id = reminder['id']
            reminder_message = reminder['message']
            
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

async def setup(bot):
    await bot.add_cog(Reminders(bot))
