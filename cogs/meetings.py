import discord
from discord.ext import commands
from discord import app_commands
import json
import asyncio
from datetime import datetime, timedelta
import random
import string
from utils.helpers import EmbedBuilder, TimeParser

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
                    "SELECT user_id, data_content FROM user_data WHERE data_type = 'meetings'"
                )
                for row in rows:
                    guild_id = row['user_id']  # user_id field stores guild_id for configs
                    meetings_data = row['data_content']
                    
                    # Process each meeting
                    for meeting_id, meeting in meetings_data.items():
                        self.meetings[meeting_id] = meeting
                        
                        # Schedule meeting if it's in the future
                        if meeting['start_time'] > datetime.utcnow().isoformat():
                            self.schedule_meeting(meeting_id, meeting)
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT user_id, data_content FROM user_data WHERE data_type = 'meetings'"
                )
                rows = await cursor.fetchall()
                for row in rows:
                    guild_id = row[0]
                    meetings_data = json.loads(row[1])
                    
                    # Process each meeting
                    for meeting_id, meeting in meetings_data.items():
                        self.meetings[meeting_id] = meeting
                        
                        # Schedule meeting if it's in the future
                        start_time = datetime.fromisoformat(meeting['start_time'])
                        if start_time > datetime.utcnow():
                            self.schedule_meeting(meeting_id, meeting)
        except Exception as e:
            print(f"Error loading meetings: {e}")
    
    async def save_meetings(self, guild_id: str):
        """Save meetings to database"""
        try:
            # Filter meetings for this guild
            guild_meetings = {}
            for meeting_id, meeting in self.meetings.items():
                if meeting['guild_id'] == guild_id:
                    guild_meetings[meeting_id] = meeting
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO user_data (user_id, data_type, data_content) 
                       VALUES ($1, $2, $3) 
                       ON CONFLICT (user_id, data_type) DO UPDATE SET data_content = $3""",
                    guild_id, 'meetings', json.dumps(guild_meetings)
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO user_data (user_id, data_type, data_content) 
                       VALUES (?, ?, ?)""",
                    (guild_id, 'meetings', json.dumps(guild_meetings))
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error saving meetings: {e}")
    
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
            
            # Get guild and channel
            guild = self.bot.get_guild(int(meeting['guild_id']))
            if not guild:
                return
            
            channel = guild.get_channel(int(meeting['channel_id']))
            if not channel:
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
                title=f"🔔 Meeting Starting: {meeting['name']}",
                description=meeting['description'],
                color=0x57F287
            )
            
            embed.add_field(name="Meeting ID", value=meeting_id, inline=True)
            
            if voice_channel:
                embed.add_field(name="Voice Channel", value=voice_channel.mention, inline=True)
            
            if participants:
                mentions = " ".join([user.mention for user in participants])
                await channel.send(f"Meeting participants: {mentions}", embed=embed)
            else:
                await channel.send(embed=embed)
            
            # Mark meeting as started
            meeting['status'] = 'started'
            await self.save_meetings(meeting['guild_id'])
            
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
        await self.save_meetings(guild_id)
        
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
        
        # Remove meeting
        del self.meetings[meeting_id]
        await self.save_meetings(meeting['guild_id'])
        
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
        # Parse time
        duration = TimeParser.parse_duration(time)
        if not duration:
            embed = EmbedBuilder.error(
                "Invalid Time Format",
                "Please use format like: `1h`, `30m`, `2d`, `1h30m`"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        start_time = datetime.utcnow() + duration
        
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
        
        # Create meeting announcement embed
        embed = discord.Embed(
            title=f"📅 Meeting Scheduled: {name}",
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
        
        await interaction.response.send_message(embed=embed, view=view)
    
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
        
        # Cancel the meeting
        success = await self.bot.meeting_manager.cancel_meeting(meeting_id)
        
        if success:
            embed = EmbedBuilder.success(
                "Meeting Cancelled",
                f"Meeting **{meeting['name']}** has been cancelled"
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = EmbedBuilder.error("Error", "Failed to cancel meeting")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-meetings", description="List all scheduled meetings")
    async def list_meetings(self, interaction: discord.Interaction):
        # Filter meetings for this guild
        guild_id = str(interaction.guild.id)
        guild_meetings = []
        
        for meeting_id, meeting in self.bot.meeting_manager.meetings.items():
            if meeting['guild_id'] == guild_id and meeting['status'] == 'scheduled':
                guild_meetings.append(meeting)
        
        if not guild_meetings:
            embed = EmbedBuilder.info("No Meetings", "No meetings are currently scheduled")
            await interaction.response.send_message(embed=embed)
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
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    cog = Meetings(bot)
    await bot.add_cog(cog)
    
    # Ensure commands are added to the tree
    for command in cog.__cog_app_commands__:
        if command not in bot.tree.get_commands():
            bot.tree.add_command(command)
    
    print(f"📅 Successfully loaded Meetings cog with {len(cog.get_app_commands())} commands")
