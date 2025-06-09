import discord
from discord.ext import commands
from discord import app_commands
import json
import asyncio
from datetime import datetime, timedelta
import random
import string
from utils.helpers import EmbedBuilder, TimeParser
from typing import Dict, Any

class MeetingView(discord.ui.View):
    def __init__(self, bot, meeting_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.meeting_id = meeting_id
        self.participants = set()
    
    @discord.ui.button(label="Join Meeting", style=discord.ButtonStyle.primary, emoji="📅")
    async def join_meeting(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Add user to participants
        self.participants.add(interaction.user.id)
        
        # Get meeting data
        meeting = await self.bot.meeting_manager.get_meeting(self.meeting_id)
        if not meeting:
            await interaction.response.send_message("This meeting no longer exists.", ephemeral=True)
            return
        
        await interaction.response.send_message(f"You've joined the meeting: **{meeting['name']}**", ephemeral=True)

class MeetingManager:
    def __init__(self, bot):
        self.bot = bot
        self.meetings = {}  # meeting_id -> meeting_data
        self.active_views = {}  # meeting_id -> MeetingView
        self.scheduled_tasks = {}  # meeting_id -> task
    
    async def load_meetings(self):
        """Load meetings from database"""
        try:
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT * FROM meetings WHERE status = 'scheduled'"
                )
                for row in rows:
                    meeting_id = row['meeting_id']
                    meeting = {
                        'id': meeting_id,
                        'name': row['title'],
                        'description': row['description'],
                        'start_time': row['scheduled_time'].isoformat(),
                        'guild_id': row['guild_id'],
                        'creator_id': row['creator_id'],
                        'channel_id': None,  # Will be set when creating
                        'voice_channel_id': None,  # Will be set when creating
                        'status': row['status'],
                        'created_at': row['created_at'].isoformat()
                    }
                    self.meetings[meeting_id] = meeting
                    
                    # Schedule meeting if it's in the future
                    if row['scheduled_time'] > datetime.utcnow():
                        self.schedule_meeting(meeting_id, meeting)
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM meetings WHERE status = 'scheduled'"
                )
                rows = await cursor.fetchall()
                for row in rows:
                    meeting_id = row[1]  # meeting_id column
                    meeting = {
                        'id': meeting_id,
                        'name': row[4],  # title
                        'description': row[5],  # description
                        'start_time': row[6],  # scheduled_time
                        'guild_id': row[2],  # guild_id
                        'creator_id': row[3],  # creator_id
                        'channel_id': None,
                        'voice_channel_id': None,
                        'status': row[9],  # status
                        'created_at': row[11]  # created_at
                    }
                    self.meetings[meeting_id] = meeting
                    
                    # Schedule meeting if it's in the future
                    start_time = datetime.fromisoformat(row[6]) if isinstance(row[6], str) else row[6]
                    if start_time > datetime.utcnow():
                        self.schedule_meeting(meeting_id, meeting)
        except Exception as e:
            print(f"Error loading meetings: {e}")
    
    async def save_meeting(self, meeting: Dict[str, Any]):
        """Save meeting to database"""
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO meetings (meeting_id, guild_id, creator_id, title, description, scheduled_time, status)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)
                       ON CONFLICT (meeting_id) DO UPDATE SET
                       title = $4, description = $5, scheduled_time = $6, status = $7, updated_at = CURRENT_TIMESTAMP""",
                    meeting['id'], meeting['guild_id'], meeting['creator_id'],
                    meeting['name'], meeting['description'], 
                    datetime.fromisoformat(meeting['start_time']), meeting['status']
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO meetings (meeting_id, guild_id, creator_id, title, description, scheduled_time, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (meeting['id'], meeting['guild_id'], meeting['creator_id'],
                     meeting['name'], meeting['description'], meeting['start_time'], meeting['status'])
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error saving meeting: {e}")
    
    async def delete_meeting(self, meeting_id: str):
        """Delete meeting from database"""
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "DELETE FROM meetings WHERE meeting_id = $1", meeting_id
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM meetings WHERE meeting_id = ?", (meeting_id,)
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error deleting meeting: {e}")
    
    def generate_meeting_id(self) -> str:
        """Generate a unique meeting ID"""
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choices(chars, k=8))
    
    def schedule_meeting(self, meeting_id: str, meeting: Dict[str, Any]):
        """Schedule a meeting to start at the specified time"""
        start_time = datetime.fromisoformat(meeting['start_time'])
        delay = (start_time - datetime.utcnow()).total_seconds()
        
        if delay > 0:
            task = asyncio.create_task(self._start_meeting_task(meeting_id, delay))
            self.scheduled_tasks[meeting_id] = task
    
    async def _start_meeting_task(self, meeting_id: str, delay: float):
        """Task to start a meeting after delay"""
        await asyncio.sleep(delay)
        await self.start_meeting(meeting_id)
    
    async def start_meeting(self, meeting_id: str):
        """Start a scheduled meeting"""
        meeting = self.meetings.get(meeting_id)
        if not meeting:
            return
        
        guild = self.bot.get_guild(int(meeting['guild_id']))
        if not guild:
            return
        
        # Get announcement channel
        config = await self.bot.db.get_guild_config(str(guild.id))
        announcement_channel_id = config.get('announcement_channel_id') if config else None
        
        if announcement_channel_id:
            channel = guild.get_channel(int(announcement_channel_id))
            if channel:
                embed = discord.Embed(
                    title="🎯 Meeting Starting Now!",
                    description=f"**{meeting['name']}** is starting now!",
                    color=0x00FF00
                )
                embed.add_field(name="Description", value=meeting['description'], inline=False)
                embed.add_field(name="Meeting ID", value=meeting_id, inline=True)
                
                creator = guild.get_member(int(meeting['creator_id']))
                if creator:
                    embed.add_field(name="Host", value=creator.mention, inline=True)
                
                await channel.send(embed=embed)
        
        # Update meeting status
        meeting['status'] = 'active'
        await self.save_meeting(meeting)
        
        # Clean up scheduled task
        if meeting_id in self.scheduled_tasks:
            del self.scheduled_tasks[meeting_id]
    
    async def get_meeting(self, meeting_id: str) -> Dict[str, Any]:
        """Get meeting by ID"""
        return self.meetings.get(meeting_id)
    
    async def cancel_meeting(self, meeting_id: str):
        """Cancel a scheduled meeting"""
        if meeting_id in self.scheduled_tasks:
            self.scheduled_tasks[meeting_id].cancel()
            del self.scheduled_tasks[meeting_id]
        
        if meeting_id in self.meetings:
            del self.meetings[meeting_id]
        
        await self.delete_meeting(meeting_id)

class Meetings(commands.Cog):
    """Meeting scheduling and management"""
    
    def __init__(self, bot):
        self.bot = bot
        self.meeting_manager = MeetingManager(bot)
        self.bot.meeting_manager = self.meeting_manager
    
    async def cog_load(self):
        """Load meetings when cog is loaded"""
        await self.meeting_manager.load_meetings()
    
    @app_commands.command(name="create-meeting", description="Schedule a new meeting")
    @app_commands.describe(
        title="Meeting title",
        description="Meeting description",
        time="When to schedule the meeting (e.g., '2h', 'tomorrow 3pm', '2024-01-15 14:30')"
    )
    async def create_meeting(self, interaction: discord.Interaction, title: str, description: str, time: str):
        await interaction.response.defer()
        
        try:
            # Parse the time
            scheduled_time = TimeParser.parse_time(time)
            if not scheduled_time:
                embed = EmbedBuilder.error(
                    "Invalid Time Format",
                    "Please use formats like:\n"
                    "• `2h` (2 hours from now)\n"
                    "• `tomorrow 3pm`\n"
                    "• `2024-01-15 14:30`\n"
                    "• `next friday 2pm`"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Check if time is in the future
            if scheduled_time <= datetime.utcnow():
                embed = EmbedBuilder.error("Invalid Time", "Meeting time must be in the future")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Generate meeting ID
            meeting_id = self.meeting_manager.generate_meeting_id()
            
            # Create meeting data
            meeting = {
                'id': meeting_id,
                'name': title,
                'description': description,
                'start_time': scheduled_time.isoformat(),
                'guild_id': str(interaction.guild.id),
                'creator_id': str(interaction.user.id),
                'channel_id': None,
                'voice_channel_id': None,
                'status': 'scheduled',
                'created_at': datetime.utcnow().isoformat()
            }
            
            # Save meeting
            self.meeting_manager.meetings[meeting_id] = meeting
            await self.meeting_manager.save_meeting(meeting)
            
            # Schedule the meeting
            self.meeting_manager.schedule_meeting(meeting_id, meeting)
            
            # Create response embed
            embed = discord.Embed(
                title="📅 Meeting Scheduled",
                description=f"**{title}** has been scheduled!",
                color=0x00FF00
            )
            embed.add_field(name="Meeting ID", value=meeting_id, inline=True)
            embed.add_field(name="Scheduled Time", value=scheduled_time.strftime('%Y-%m-%d %H:%M UTC'), inline=True)
            embed.add_field(name="Host", value=interaction.user.mention, inline=True)
            embed.add_field(name="Description", value=description, inline=False)
            
            # Calculate time until meeting
            time_until = scheduled_time - datetime.utcnow()
            hours = int(time_until.total_seconds() // 3600)
            minutes = int((time_until.total_seconds() % 3600) // 60)
            embed.add_field(name="Starts In", value=f"{hours}h {minutes}m", inline=True)
            
            await interaction.followup.send(embed=embed)
            
            # Announce in configured channel
            config = await self.bot.db.get_guild_config(str(interaction.guild.id))
            announcement_channel_id = config.get('announcement_channel_id') if config else None
            
            if announcement_channel_id:
                channel = interaction.guild.get_channel(int(announcement_channel_id))
                if channel and channel != interaction.channel:
                    announce_embed = discord.Embed(
                        title="📅 New Meeting Scheduled",
                        description=f"**{title}** has been scheduled by {interaction.user.mention}",
                        color=0x5865F2
                    )
                    announce_embed.add_field(name="Meeting ID", value=meeting_id, inline=True)
                    announce_embed.add_field(name="Time", value=scheduled_time.strftime('%Y-%m-%d %H:%M UTC'), inline=True)
                    announce_embed.add_field(name="Description", value=description, inline=False)
                    
                    await channel.send(embed=announce_embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create meeting: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="admin-meeting", description="Create an admin-only meeting (Admin only)")
    @app_commands.describe(
        title="Meeting title",
        description="Meeting description",
        time="When to schedule the meeting"
    )
    async def admin_meeting(self, interaction: discord.Interaction, title: str, description: str, time: str):
        if not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can create admin meetings")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Use the same logic as create_meeting but mark as admin-only
        await self.create_meeting(interaction, f"[ADMIN] {title}", description, time)
    
    @app_commands.command(name="join-meeting", description="Join a meeting by ID")
    @app_commands.describe(meeting_id="Meeting ID to join")
    async def join_meeting(self, interaction: discord.Interaction, meeting_id: str):
        meeting = await self.meeting_manager.get_meeting(meeting_id.upper())
        
        if not meeting:
            embed = EmbedBuilder.error("Meeting Not Found", f"No meeting found with ID: {meeting_id}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        embed = discord.Embed(
            title=f"📅 {meeting['name']}",
            description=meeting['description'],
            color=0x5865F2
        )
        embed.add_field(name="Meeting ID", value=meeting['id'], inline=True)
        embed.add_field(name="Status", value=meeting['status'].title(), inline=True)
        
        creator = interaction.guild.get_member(int(meeting['creator_id']))
        if creator:
            embed.add_field(name="Host", value=creator.mention, inline=True)
        
        if meeting['status'] == 'scheduled':
            start_time = datetime.fromisoformat(meeting['start_time'])
            embed.add_field(name="Scheduled Time", value=start_time.strftime('%Y-%m-%d %H:%M UTC'), inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="cancel-meeting", description="Cancel a scheduled meeting")
    @app_commands.describe(meeting_id="Meeting ID to cancel")
    async def cancel_meeting(self, interaction: discord.Interaction, meeting_id: str):
        meeting = await self.meeting_manager.get_meeting(meeting_id.upper())
        
        if not meeting:
            embed = EmbedBuilder.error("Meeting Not Found", f"No meeting found with ID: {meeting_id}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check permissions
        if not (self.bot.admin_manager.is_admin(interaction.user) or str(interaction.user.id) == meeting['creator_id']):
            embed = EmbedBuilder.error("Permission Denied", "Only the meeting creator or administrators can cancel meetings")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await self.meeting_manager.cancel_meeting(meeting_id.upper())
        
        embed = EmbedBuilder.success(
            "Meeting Cancelled",
            f"Meeting **{meeting['name']}** (ID: {meeting_id.upper()}) has been cancelled"
        )
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="list-meetings", description="List all scheduled meetings")
    async def list_meetings(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            # Get meetings from database
            if self.bot.db.is_postgresql:
                meetings = await self.bot.db.connection.fetch(
                    "SELECT * FROM meetings WHERE guild_id = $1 AND status IN ('scheduled', 'active') ORDER BY scheduled_time ASC",
                    str(interaction.guild.id)
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM meetings WHERE guild_id = ? AND status IN ('scheduled', 'active') ORDER BY scheduled_time ASC",
                    (str(interaction.guild.id),)
                )
                meetings = await cursor.fetchall()
            
            if not meetings:
                embed = EmbedBuilder.info("No Meetings", "No scheduled meetings found")
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title="📅 Scheduled Meetings",
                color=0x5865F2
            )
            
            for meeting in meetings[:10]:  # Show first 10 meetings
                if self.bot.db.is_postgresql:
                    meeting_id = meeting['meeting_id']
                    title = meeting['title']
                    scheduled_time = meeting['scheduled_time']
                    status = meeting['status']
                    creator_id = meeting['creator_id']
                else:
                    meeting_id = meeting[1]
                    title = meeting[4]
                    scheduled_time = meeting[6]
                    status = meeting[9]
                    creator_id = meeting[3]
                
                creator = interaction.guild.get_member(int(creator_id))
                creator_name = creator.display_name if creator else "Unknown"
                
                status_emoji = "🟢" if status == "active" else "🔵"
                
                # Format time
                if isinstance(scheduled_time, str):
                    time_obj = datetime.fromisoformat(scheduled_time)
                else:
                    time_obj = scheduled_time
                
                time_str = time_obj.strftime('%Y-%m-%d %H:%M UTC')
                
                embed.add_field(
                    name=f"{status_emoji} {meeting_id}",
                    value=f"**{title}**\n"
                          f"Host: {creator_name}\n"
                          f"Time: {time_str}\n"
                          f"Status: {status.title()}",
                    inline=True
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch meetings: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    cog = Meetings(bot)
    await bot.add_cog(cog)
    
    # Ensure commands are added to the tree
    for command in cog.get_app_commands():
        if command not in bot.tree.get_commands():
            bot.tree.add_command(command)
    
    print(f"📅 Successfully loaded Meetings cog with {len(cog.get_app_commands())} commands")
