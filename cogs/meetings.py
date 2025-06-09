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
        while True:
            # Generate a 6-character meeting ID
            meeting_id = ''.join(random.choice(chars) for _ in range(6))
            if meeting_id not in self.meetings:
                return meeting_id
    
    def schedule_meeting(self, meeting_id: str, meeting: dict):
        """Schedule a meeting to start at the specified time"""
        try:
            start_time = datetime.fromisoformat(meeting['start_time'])
            now = datetime.utcnow()
            
            if start_time > now:
                # Calculate seconds until meeting starts
                seconds = (start_time - now).total_seconds()
                
                # Schedule the task
                task = asyncio.create_task(self.start_meeting_at(meeting_id, seconds))
                self.scheduled_tasks[meeting_id] = task
        except Exception as e:
            print(f"Error scheduling meeting {meeting_id}: {e}")
    
    async def start_meeting_at(self, meeting_id: str, seconds: float):
        """Start a meeting after the specified delay"""
        try:
            # Wait until meeting time
            await asyncio.sleep(seconds)
            
            # Get meeting data
            meeting = self.meetings.get(meeting_id)
            if not meeting:
                return
            
            # Get guild
            guild = self.bot.get_guild(int(meeting['guild_id']))
            if not guild:
                return
            
            # Get announcement channel from meeting config
            announcement_channel = None
            try:
                if self.bot.db.is_postgresql:
                    config_row = await self.bot.db.connection.fetchrow(
                        "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                        str(guild.id), 'meeting_config'
                    )
                    if config_row:
                        config = json.loads(config_row['data_content'])
                        announcement_channel = guild.get_channel(int(config['announcement_channel_id']))
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT data_content FROM user_data WHERE user_id = ? AND data_type = ?",
                        (str(guild.id), 'meeting_config')
                    )
                    row = await cursor.fetchone()
                    if row:
                        config = json.loads(row[0])
                        announcement_channel = guild.get_channel(int(config['announcement_channel_id']))
            except Exception as e:
                print(f"Error getting meeting config for starting notification: {e}")
            
            # Fallback to original channel if no announcement channel
            if not announcement_channel and meeting['channel_id']:
                announcement_channel = guild.get_channel(int(meeting['channel_id']))
            
            if not announcement_channel:
                return
            
            # Get voice channel
            voice_channel = guild.get_channel(int(meeting['voice_channel_id']))
            
            # Get participants
            view = self.active_views.get(meeting_id)
            participants = []
            if view:
                for user_id in view.participants:
                    user = guild.get_member(user_id)
                    if user:
                        participants.append(user)
            
            # Create meeting start embed
            embed = discord.Embed(
                title=f"🔔 Meeting Starting Now: {meeting['name']}",
                description=meeting['description'],
                color=0x57F287
            )
            
            embed.add_field(name="Meeting ID", value=meeting_id, inline=True)
            
            if voice_channel:
                embed.add_field(name="Voice Channel", value=voice_channel.mention, inline=True)
            
            embed.add_field(name="Started", value=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), inline=True)
            
            if participants:
                participant_mentions = " ".join([user.mention for user in participants[:10]])  # Limit to 10 mentions
                if len(participants) > 10:
                    participant_mentions += f" and {len(participants) - 10} others"
                
                embed.add_field(
                    name=f"Participants ({len(participants)})",
                    value=participant_mentions,
                    inline=False
                )
                
                await announcement_channel.send(f"🔔 **Meeting participants:** {participant_mentions}", embed=embed)
            else:
                await announcement_channel.send(embed=embed)
            
            # Mark meeting as started
            meeting['status'] = 'started'
            await self.save_meeting(meeting)
            
        except asyncio.CancelledError:
            # Task was cancelled
            pass
        except Exception as e:
            print(f"Error starting meeting {meeting_id}: {e}")
    
    async def get_meeting(self, meeting_id: str) -> dict:
        """Get meeting data by ID"""
        return self.meetings.get(meeting_id)
    
    async def create_meeting(self, guild_id: str, creator_id: str, name: str, description: str, 
                           start_time: datetime, channel_id: str, voice_channel_id: str) -> str:
        """Create a new meeting"""
        meeting_id = self.generate_meeting_id()
        
        meeting = {
            'id': meeting_id,
            'name': name,
            'description': description,
            'start_time': start_time.isoformat(),
            'guild_id': guild_id,
            'creator_id': creator_id,
            'channel_id': channel_id,
            'voice_channel_id': voice_channel_id,
            'status': 'scheduled',
            'created_at': datetime.utcnow().isoformat()
        }
        
        self.meetings[meeting_id] = meeting
        await self.save_meeting(meeting)
        
        # Schedule the meeting
        self.schedule_meeting(meeting_id, meeting)
        
        return meeting_id
    
    async def cancel_meeting(self, meeting_id: str) -> bool:
        """Cancel a scheduled meeting"""
        meeting = self.meetings.get(meeting_id)
        if not meeting:
            return False
        
        # Cancel scheduled task if exists
        task = self.scheduled_tasks.get(meeting_id)
        if task:
            task.cancel()
            del self.scheduled_tasks[meeting_id]
        
        # Delete from database
        await self.delete_meeting(meeting_id)
        
        # Remove from memory
        del self.meetings[meeting_id]
        
        return True

class Meetings(commands.Cog):
    """Meeting scheduling and management"""
    
    def __init__(self, bot):
        self.bot = bot
        self.bot.meeting_manager = MeetingManager(bot)
    
    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.meeting_manager.load_meetings()
    
    @app_commands.command(name="create-meeting", description="Schedule a new meeting")
    @app_commands.describe(
        name="Meeting name",
        time="When to start the meeting (e.g., '1h', '30m', '2d')",
        description="Meeting description",
        voice_channel="Voice channel for the meeting"
    )
    async def create_meeting(self, interaction: discord.Interaction, name: str, time: str, 
                           description: str, voice_channel: discord.VoiceChannel):
        await interaction.response.defer()
        
        # Parse time
        duration = TimeParser.parse_duration(time)
        if not duration:
            embed = EmbedBuilder.error(
                "Invalid Time Format",
                "Please use format like: `1h`, `30m`, `2d`, `1h30m`"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        start_time = datetime.utcnow() + duration
        
        try:
            # Create meeting
            meeting_id = await self.bot.meeting_manager.create_meeting(
                str(interaction.guild.id),
                str(interaction.user.id),
                name,
                description,
                start_time,
                str(interaction.channel.id),
                str(voice_channel.id)
            )
            
            # Get meeting config to check for announcement channel
            announcement_channel = None
            try:
                if self.bot.db.is_postgresql:
                    config_row = await self.bot.db.connection.fetchrow(
                        "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                        str(interaction.guild.id), 'meeting_config'
                    )
                    if config_row:
                        config = json.loads(config_row['data_content'])
                        announcement_channel = interaction.guild.get_channel(int(config['announcement_channel_id']))
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT data_content FROM user_data WHERE user_id = ? AND data_type = ?",
                        (str(interaction.guild.id), 'meeting_config')
                    )
                    row = await cursor.fetchone()
                    if row:
                        config = json.loads(row[0])
                        announcement_channel = interaction.guild.get_channel(int(config['announcement_channel_id']))
            except Exception as e:
                print(f"Error getting meeting config: {e}")

            # Create meeting announcement embed
            embed = discord.Embed(
                title=f"📅 New Meeting: {name}",
                description=description,
                color=0x5865F2
            )

            embed.add_field(name="Organizer", value=interaction.user.mention, inline=True)
            embed.add_field(name="Meeting ID", value=meeting_id, inline=True)
            embed.add_field(name="Voice Channel", value=voice_channel.mention, inline=True)

            # Format start time
            time_str = start_time.strftime("%Y-%m-%d %H:%M UTC")
            time_until = TimeParser.format_timedelta(start_time - datetime.utcnow())
            embed.add_field(name="Start Time", value=f"{time_str}\n(in {time_until})", inline=False)

            embed.add_field(
                name="How to Join",
                value=f"• Click the button below\n• Use `/join-meeting {meeting_id}`\n• Join the voice channel at the scheduled time",
                inline=False
            )

            # Create view with join button
            view = MeetingView(self.bot, meeting_id)
            self.bot.meeting_manager.active_views[meeting_id] = view

            # Send to announcement channel if configured, otherwise to current channel
            if announcement_channel:
                await announcement_channel.send(embed=embed, view=view)
                # Confirm to user
                confirm_embed = EmbedBuilder.success(
                    "Meeting Created",
                    f"Meeting **{name}** has been created and announced in {announcement_channel.mention}!\n\n"
                    f"**Meeting ID:** {meeting_id}\n"
                    f"**Start Time:** {time_str} (in {time_until})"
                )
                await interaction.followup.send(embed=confirm_embed, ephemeral=True)
            else:
                # No announcement channel configured, send to current channel
                await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create meeting: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="admin-meeting", description="Create a server-wide meeting announcement (Admin only)")
    @app_commands.describe(
        name="Meeting name",
        time="When to start the meeting (e.g., '1h', '30m', '2d')",
        description="Meeting description",
        voice_channel="Voice channel for the meeting",
        mention_type="Who to mention (here or everyone)"
    )
    async def admin_meeting(self, interaction: discord.Interaction, name: str, time: str, 
                           description: str, voice_channel: discord.VoiceChannel, mention_type: str = "here"):
        if not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can create server-wide meetings")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        if mention_type not in ["here", "everyone"]:
            mention_type = "here"
        
        # Parse time
        duration = TimeParser.parse_duration(time)
        if not duration:
            embed = EmbedBuilder.error(
                "Invalid Time Format",
                "Please use format like: `1h`, `30m`, `2d`, `1h30m`"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        start_time = datetime.utcnow() + duration
        
        try:
            # Create meeting
            meeting_id = await self.bot.meeting_manager.create_meeting(
                str(interaction.guild.id),
                str(interaction.user.id),
                name,
                description,
                start_time,
                str(interaction.channel.id),
                str(voice_channel.id)
            )
            
            # Get meeting config to check for announcement channel
            announcement_channel = None
            try:
                if self.bot.db.is_postgresql:
                    config_row = await self.bot.db.connection.fetchrow(
                        "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                        str(interaction.guild.id), 'meeting_config'
                    )
                    if config_row:
                        config = json.loads(config_row['data_content'])
                        announcement_channel = interaction.guild.get_channel(int(config['announcement_channel_id']))
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT data_content FROM user_data WHERE user_id = ? AND data_type = ?",
                        (str(interaction.guild.id), 'meeting_config')
                    )
                    row = await cursor.fetchone()
                    if row:
                        config = json.loads(row[0])
                        announcement_channel = interaction.guild.get_channel(int(config['announcement_channel_id']))
            except Exception as e:
                print(f"Error getting meeting config: {e}")

            # Create meeting announcement embed
            embed = discord.Embed(
                title=f"📅 Server Meeting: {name}",
                description=description,
                color=0x5865F2
            )

            embed.add_field(name="Organizer", value=interaction.user.mention, inline=True)
            embed.add_field(name="Meeting ID", value=meeting_id, inline=True)
            embed.add_field(name="Voice Channel", value=voice_channel.mention, inline=True)

            # Format start time
            time_str = start_time.strftime("%Y-%m-%d %H:%M UTC")
            time_until = TimeParser.format_timedelta(start_time - datetime.utcnow())
            embed.add_field(name="Start Time", value=f"{time_str}\n(in {time_until})", inline=False)

            embed.add_field(
                name="How to Join",
                value=f"• Click the button below\n• Use `/join-meeting {meeting_id}`\n• Join the voice channel at the scheduled time",
                inline=False
            )

            # Create view with join button
            view = MeetingView(self.bot, meeting_id)
            self.bot.meeting_manager.active_views[meeting_id] = view

            # Send announcement with proper mention
            mention_text = "@here" if mention_type == "here" else "@everyone"
            if mention_type == "everyone":
                allowed_mentions = discord.AllowedMentions(everyone=True)
            else:
                allowed_mentions = discord.AllowedMentions(everyone=False)

            # Send to announcement channel if configured, otherwise to current channel
            if announcement_channel:
                await announcement_channel.send(
                    f"{mention_text} **Server Meeting Announcement**", 
                    embed=embed, 
                    view=view,
                    allowed_mentions=allowed_mentions
                )
                # Confirm to admin
                confirm_embed = EmbedBuilder.success(
                    "Server Meeting Created",
                    f"Server meeting **{name}** has been created and announced in {announcement_channel.mention}!\n\n"
                    f"**Meeting ID:** {meeting_id}\n"
                    f"**Start Time:** {time_str} (in {time_until})"
                )
                await interaction.followup.send(embed=confirm_embed, ephemeral=True)
            else:
                # No announcement channel configured, send to current channel
                await interaction.followup.send(
                    f"{mention_text} **Server Meeting Announcement**", 
                    embed=embed, 
                    view=view,
                    allowed_mentions=allowed_mentions
                )
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create meeting: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="join-meeting", description="Join a scheduled meeting")
    @app_commands.describe(meeting_id="ID of the meeting to join")
    async def join_meeting(self, interaction: discord.Interaction, meeting_id: str):
        # Check if meeting exists
        meeting = await self.bot.meeting_manager.get_meeting(meeting_id)
        if not meeting:
            embed = EmbedBuilder.error("Not Found", f"Meeting with ID {meeting_id} not found")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Add user to participants
        view = self.bot.meeting_manager.active_views.get(meeting_id)
        if view:
            view.participants.add(interaction.user.id)
        
        # Get voice channel
        guild = interaction.guild
        voice_channel = guild.get_channel(int(meeting['voice_channel_id']))
        
        embed = discord.Embed(
            title=f"✅ Joined Meeting: {meeting['name']}",
            description=meeting['description'],
            color=0x57F287
        )
        
        embed.add_field(name="Meeting ID", value=meeting_id, inline=True)
        
        if voice_channel:
            embed.add_field(name="Voice Channel", value=voice_channel.mention, inline=True)
        
        # Format start time
        start_time = datetime.fromisoformat(meeting['start_time'])
        time_str = start_time.strftime("%Y-%m-%d %H:%M UTC")
        
        if start_time > datetime.utcnow():
            time_until = TimeParser.format_timedelta(start_time - datetime.utcnow())
            embed.add_field(name="Starts", value=f"{time_str}\n(in {time_until})", inline=False)
        else:
            embed.add_field(name="Started", value=time_str, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="cancel-meeting", description="Cancel a scheduled meeting")
    @app_commands.describe(meeting_id="ID of the meeting to cancel")
    async def cancel_meeting(self, interaction: discord.Interaction, meeting_id: str):
        # Check if meeting exists
        meeting = await self.bot.meeting_manager.get_meeting(meeting_id)
        if not meeting:
            embed = EmbedBuilder.error("Not Found", f"Meeting with ID {meeting_id} not found")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if user is the creator or admin
        if meeting['creator_id'] != str(interaction.user.id) and not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error(
                "Permission Denied", 
                "Only the meeting creator or administrators can cancel meetings"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # Cancel the meeting
            success = await self.bot.meeting_manager.cancel_meeting(meeting_id)
            
            if success:
                embed = EmbedBuilder.success(
                    "Meeting Cancelled",
                    f"Meeting **{meeting['name']}** has been cancelled"
                )
                await interaction.followup.send(embed=embed)
            else:
                embed = EmbedBuilder.error("Error", "Failed to cancel meeting")
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to cancel meeting: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-meetings", description="List all scheduled meetings")
    async def list_meetings(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            # Filter meetings for this guild
            guild_id = str(interaction.guild.id)
            guild_meetings = []
            
            for meeting_id, meeting in self.bot.meeting_manager.meetings.items():
                if meeting['guild_id'] == guild_id and meeting['status'] == 'scheduled':
                    guild_meetings.append(meeting)
            
            if not guild_meetings:
                embed = EmbedBuilder.info("No Meetings", "No meetings are currently scheduled")
                await interaction.followup.send(embed=embed)
                return
            
            # Sort meetings by start time
            guild_meetings.sort(key=lambda m: m['start_time'])
            
            embed = discord.Embed(
                title="📅 Scheduled Meetings",
                description=f"There are {len(guild_meetings)} upcoming meetings",
                color=0x5865F2
            )
            
            for meeting in guild_meetings[:10]:  # Show up to 10 meetings
                start_time = datetime.fromisoformat(meeting['start_time'])
                time_str = start_time.strftime("%Y-%m-%d %H:%M UTC")
                
                if start_time > datetime.utcnow():
                    time_until = TimeParser.format_timedelta(start_time - datetime.utcnow())
                    time_field = f"{time_str}\n(in {time_until})"
                else:
                    time_field = f"{time_str}\n(starting now)"
                
                creator = interaction.guild.get_member(int(meeting['creator_id']))
                creator_name = creator.display_name if creator else "Unknown"
                
                voice_channel = interaction.guild.get_channel(int(meeting['voice_channel_id']))
                voice_name = voice_channel.name if voice_channel else "Unknown Channel"
                
                embed.add_field(
                    name=f"{meeting['name']} (ID: {meeting['id']})",
                    value=f"**Time:** {time_field}\n**Voice:** {voice_name}\n**Organizer:** {creator_name}",
                    inline=False
                )
            
            if len(guild_meetings) > 10:
                embed.set_footer(text=f"Showing 10 of {len(guild_meetings)} meetings")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to list meetings: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    cog = Meetings(bot)
    await bot.add_cog(cog)
    
    # Sync commands to all guilds
    for guild in bot.guilds:
        try:
            # Copy global commands to guild
            bot.tree.copy_global_to(guild=guild)
            
            # Add cog commands to guild
            for command in cog.get_app_commands():
                if command not in bot.tree.get_commands(guild=guild):
                    bot.tree.add_command(command, guild=guild)
            
            # Sync to guild
            await bot.tree.sync(guild=guild)
            print(f"✅ Synced Meetings commands to {guild.name}")
        except Exception as e:
            print(f"❌ Failed to sync Meetings commands to {guild.name}: {e}")
    
    print(f"📅 Successfully loaded Meetings cog with {len(cog.get_app_commands())} commands")
