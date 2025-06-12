import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
from datetime import datetime, timedelta
from utils.helpers import EmbedBuilder, TimeParser, generate_meeting_id

class PingChoice(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="@everyone",
                description="Ping everyone in the server",
                emoji="📢",
                value="everyone"
            ),
            discord.SelectOption(
                label="@here", 
                description="Ping only online members",
                emoji="👥",
                value="here"
            )
        ]
        
        super().__init__(
            placeholder="Select ping type (required)",
            min_values=1,
            max_values=1,
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        # Store the selected ping type in the view
        self.view.selected_ping = self.values[0]
        
        # Update the embed to show selection
        embed = discord.Embed(
            title="📅 Admin Meeting Creation",
            description=f"**Ping Type Selected:** {'@everyone' if self.values[0] == 'everyone' else '@here'}\n\nClick 'Create Meeting' to proceed.",
            color=0x5865F2
        )
        
        await interaction.response.edit_message(embed=embed, view=self.view)

class AdminMeetingView(discord.ui.View):
    def __init__(self, bot, meeting_data):
        super().__init__(timeout=300)
        self.bot = bot
        self.meeting_data = meeting_data
        self.selected_ping = None
        
        # Add ping selection dropdown
        self.add_item(PingChoice())
    
    @discord.ui.button(label="Create Meeting", style=discord.ButtonStyle.success, emoji="✅")
    async def create_meeting(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_ping:
            embed = EmbedBuilder.error(
                "Ping Required",
                "You must select a ping type (@everyone or @here) before creating the meeting."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # Create meeting in database
            meeting_id = generate_meeting_id()
            await self.bot.db.connection.execute(
                """INSERT INTO meetings (meeting_id, guild_id, creator_id, title, description, scheduled_time, voice_channel_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                meeting_id, str(interaction.guild.id), str(interaction.user.id),
                self.meeting_data['name'], self.meeting_data['description'], 
                self.meeting_data['start_time'], str(self.meeting_data['voice_channel'].id)
            )
            
            # Get meeting config for announcement channel
            config_row = await self.bot.db.connection.fetchrow(
                "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                str(interaction.guild.id), 'meeting_config'
            )
            
            # Create meeting announcement embed
            embed = discord.Embed(
                title=f"📅 Admin Meeting: {self.meeting_data['name']}",
                description=self.meeting_data['description'],
                color=0xED4245  # Red color to indicate admin meeting
            )

            embed.add_field(name="Organizer", value=interaction.user.mention, inline=True)
            embed.add_field(name="Meeting ID", value=meeting_id, inline=True)
            embed.add_field(name="Voice Channel", value=self.meeting_data['voice_channel'].mention, inline=True)

            # Format start time
            time_str = self.meeting_data['start_time'].strftime("%Y-%m-%d %H:%M UTC")
            time_until = TimeParser.format_timedelta(self.meeting_data['start_time'] - datetime.utcnow())
            embed.add_field(name="Start Time", value=f"{time_str}\n(in {time_until})", inline=False)

            embed.add_field(
                name="How to Join",
                value=f"• Click the button below\n• Use `/join-meeting {meeting_id}`\n• Join the voice channel at the scheduled time",
                inline=False
            )
            
            # Add admin indicator
            embed.add_field(
                name="🛡️ Admin Meeting",
                value="This meeting was created by an administrator.",
                inline=False
            )

            # Create view with join button for the actual meeting
            meeting_view = MeetingView(self.bot, meeting_id)

            # Send to announcement channel if configured
            announcement_channel = None
            if config_row:
                config = json.loads(config_row['data_content'])
                announcement_channel_id = config.get('announcement_channel_id')
                if announcement_channel_id:
                    announcement_channel = interaction.guild.get_channel(int(announcement_channel_id))

            # Send the meeting announcement with the selected ping
            if self.selected_ping == "everyone":
                allowed_mentions = discord.AllowedMentions(everyone=True)
                content = "@everyone - New admin meeting scheduled!"
            else:  # here
                allowed_mentions = discord.AllowedMentions(everyone=False, here=True)
                content = "@here - New admin meeting scheduled!"

            if announcement_channel:
                await announcement_channel.send(
                    content=content, 
                    embed=embed, 
                    view=meeting_view,
                    allowed_mentions=allowed_mentions
                )
            else:
                await interaction.followup.send(
                    content=content, 
                    embed=embed, 
                    view=meeting_view,
                    allowed_mentions=allowed_mentions
                )
            
            # Send confirmation to the admin
            ping_display = "@everyone" if self.selected_ping == "everyone" else "@here"
            confirm_embed = EmbedBuilder.success(
                "Admin Meeting Created",
                f"Meeting '{self.meeting_data['name']}' has been created with {ping_display} ping."
            )
            await interaction.followup.send(embed=confirm_embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create admin meeting: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_meeting(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = EmbedBuilder.info("Cancelled", "Admin meeting creation has been cancelled.")
        await interaction.response.edit_message(embed=embed, view=None)

class MeetingView(discord.ui.View):
    def __init__(self, bot, meeting_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.meeting_id = meeting_id
        self.participants = set()
    
    @discord.ui.button(label="Join Meeting", style=discord.ButtonStyle.primary, emoji="📅")
    async def join_meeting(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Add user to participants in database
        try:
            # Get current attendees
            meeting = await self.bot.db.connection.fetchrow(
                "SELECT attendees FROM meetings WHERE meeting_id = $1", self.meeting_id
            )
            
            if not meeting:
                await interaction.response.send_message("This meeting no longer exists.", ephemeral=True)
                return
            
            # Parse current attendees
            current_attendees = json.loads(meeting['attendees']) if meeting['attendees'] else []
            
            # Add user if not already in list
            user_id = str(interaction.user.id)
            if user_id not in current_attendees:
                current_attendees.append(user_id)
                
                # Update database
                await self.bot.db.connection.execute(
                    "UPDATE meetings SET attendees = $1 WHERE meeting_id = $2",
                    json.dumps(current_attendees), self.meeting_id
                )
            
            # Get meeting details for response
            meeting_details = await self.bot.db.connection.fetchrow(
                "SELECT * FROM meetings WHERE meeting_id = $1", self.meeting_id
            )
            
            await interaction.response.send_message(
                f"✅ You've joined the meeting: **{meeting_details['title']}**\n"
                f"You'll receive a notification when the meeting starts!", 
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error joining meeting: {str(e)}", 
                ephemeral=True
            )

class Meetings(commands.Cog):
    """Meeting scheduling and management"""
    
    def __init__(self, bot):
        self.bot = bot
        self.check_meeting_notifications.start()  # Start the background task
    
    def cog_unload(self):
        self.check_meeting_notifications.cancel()  # Stop the task when cog unloads
    
    @tasks.loop(seconds=30)  # Check every 30 seconds
    async def check_meeting_notifications(self):
        """Background task to check for meetings starting soon and send notifications"""
        try:
            # Get meetings starting in the next 30 seconds that haven't been notified
            now = datetime.utcnow()
            notification_time = now + timedelta(seconds=30)
        
            # Use execute_with_retry to avoid connection conflicts
            query = """SELECT * FROM meetings 
                       WHERE scheduled_time <= $1 AND scheduled_time > $2 
                       AND status = 'scheduled'"""
        
            # Get meetings using a separate query execution
            meetings = []
            try:
                async with asyncio.timeout(10):  # 10 second timeout
                    meetings = await self.bot.db.connection.fetch(query, notification_time, now)
            except asyncio.TimeoutError:
                print("Meeting notification query timed out")
                return
            except Exception as e:
                print(f"Database query error in meeting notifications: {e}")
                return
        
            # Process each meeting
            for meeting in meetings:
                try:
                    await self.send_meeting_starting_notification(meeting)
                except Exception as e:
                    print(f"Error processing meeting {meeting.get('meeting_id', 'unknown')}: {e}")
                
        except Exception as e:
            print(f"Error in meeting notification task: {e}")
    
    @check_meeting_notifications.before_loop
    async def before_check_meeting_notifications(self):
        """Wait until the bot is ready before starting the task"""
        await self.bot.wait_until_ready()
    
    async def send_meeting_starting_notification(self, meeting):
        """Send meeting starting notification to announcement channel and participants"""
        try:
            guild = self.bot.get_guild(int(meeting['guild_id']))
            if not guild:
                return
    
            # Get meeting config with timeout
            config_row = None
            try:
                async with asyncio.timeout(5):
                    config_row = await self.bot.db.connection.fetchrow(
                        "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                        meeting['guild_id'], 'meeting_config'
                    )
            except Exception as e:
                print(f"Error getting meeting config: {e}")
                return
        
            if not config_row:
                return
        
            config = json.loads(config_row['data_content'])
            announcement_channel_id = config.get('announcement_channel_id')
        
            if not announcement_channel_id:
                return
        
            announcement_channel = guild.get_channel(int(announcement_channel_id))
            if not announcement_channel:
                return
        
            # Get voice channel
            voice_channel = guild.get_channel(int(meeting['voice_channel_id']))
        
            # Create meeting starting embed
            embed = discord.Embed(
                title=f"🔔 Meeting Starting: {meeting['title']}",
                description=f"{meeting['description']}\n\n**The meeting is starting now!**",
                color=0xFEE75C  # Yellow for starting notification
            )
        
            embed.add_field(name="Meeting ID", value=meeting['meeting_id'], inline=True)
            if voice_channel:
                embed.add_field(name="Voice Channel", value=voice_channel.mention, inline=True)
        
            # Get organizer
            organizer = guild.get_member(int(meeting['creator_id']))
            if organizer:
                embed.add_field(name="Organizer", value=organizer.mention, inline=True)
        
            embed.add_field(
                name="Join Now",
                value=f"Click {voice_channel.mention if voice_channel else 'the voice channel'} to join!",
                inline=False
            )
        
            # Get attendees
            attendees = json.loads(meeting['attendees']) if meeting['attendees'] else []
        
            # Create mention string for attendees
            mentions = []
            valid_attendees = []
        
            for user_id in attendees:
                member = guild.get_member(int(user_id))
                if member:
                    mentions.append(member.mention)
                    valid_attendees.append(member)
        
            # Send to announcement channel with pings
            if mentions:
                content = f"🔔 **Meeting Starting!** {' '.join(mentions)}"
                allowed_mentions = discord.AllowedMentions(users=valid_attendees)
            else:
                content = "🔔 **Meeting Starting!**"
                allowed_mentions = discord.AllowedMentions.none()
        
            await announcement_channel.send(
                content=content,
                embed=embed,
                allowed_mentions=allowed_mentions
            )
        
            # Send DMs to attendees
            for member in valid_attendees:
                try:
                    dm_embed = discord.Embed(
                        title=f"🔔 Meeting Starting: {meeting['title']}",
                        description=f"Your meeting is starting now!\n\n**Server:** {guild.name}",
                        color=0xFEE75C
                    )
                
                    if voice_channel:
                        dm_embed.add_field(
                            name="Join Voice Channel",
                            value=f"Join {voice_channel.name} in {guild.name}",
                            inline=False
                        )
                
                    dm_embed.add_field(name="Meeting ID", value=meeting['meeting_id'], inline=True)
                
                    await member.send(embed=dm_embed)
                
                except discord.Forbidden:
                    # User has DMs disabled
                    pass
                except Exception as e:
                    print(f"Error sending DM to {member}: {e}")
        
            # Mark meeting as notified by updating status with timeout
            try:
                async with asyncio.timeout(5):
                    await self.bot.db.connection.execute(
                        "UPDATE meetings SET status = 'starting' WHERE meeting_id = $1",
                        meeting['meeting_id']
                    )
            except Exception as e:
                print(f"Error updating meeting status: {e}")
        
        except Exception as e:
            print(f"Error sending meeting starting notification: {e}")
    
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
        meeting_id = generate_meeting_id()
        
        try:
            # Create meeting in database
            await self.bot.db.connection.execute(
                """INSERT INTO meetings (meeting_id, guild_id, creator_id, title, description, scheduled_time, voice_channel_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                meeting_id, str(interaction.guild.id), str(interaction.user.id),
                name, description, start_time, str(voice_channel.id)
            )
            
            # Get meeting config for announcement channel
            config_row = await self.bot.db.connection.fetchrow(
                "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                str(interaction.guild.id), 'meeting_config'
            )
            
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

            # Send to announcement channel if configured
            announcement_channel = None
            if config_row:
                config = json.loads(config_row['data_content'])
                announcement_channel_id = config.get('announcement_channel_id')
                if announcement_channel_id:
                    announcement_channel = interaction.guild.get_channel(int(announcement_channel_id))

            if announcement_channel:
                await announcement_channel.send(embed=embed, view=view)
                # Send confirmation to user
                confirm_embed = EmbedBuilder.success(
                    "Meeting Created",
                    f"Meeting '{name}' has been created and announced in {announcement_channel.mention}!"
                )
                await interaction.followup.send(embed=confirm_embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create meeting: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="create-admin-meeting", description="Create an admin meeting with ping options (Admin only)")
    @app_commands.describe(
        name="Meeting name",
        time="When to start the meeting (e.g., '1h', '30m', '2d')",
        description="Meeting description", 
        voice_channel="Voice channel for the meeting"
    )
    async def create_admin_meeting(self, interaction: discord.Interaction, name: str, time: str,
                                 description: str, voice_channel: discord.VoiceChannel):
        # Check if user is admin
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can create admin meetings")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
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
        
        # Store meeting data
        meeting_data = {
            'name': name,
            'time': time,
            'description': description,
            'voice_channel': voice_channel,
            'start_time': start_time
        }
        
        # Create initial embed
        embed = discord.Embed(
            title="📅 Admin Meeting Creation",
            description=f"**Meeting:** {name}\n**Description:** {description}\n**Voice Channel:** {voice_channel.mention}\n\n**⚠️ You must select a ping type before creating the meeting.**",
            color=0x5865F2
        )
        
        # Format start time
        time_str = start_time.strftime("%Y-%m-%d %H:%M UTC")
        time_until = TimeParser.format_timedelta(start_time - datetime.utcnow())
        embed.add_field(name="Start Time", value=f"{time_str}\n(in {time_until})", inline=False)
        
        # Create view with ping selection
        view = AdminMeetingView(self.bot, meeting_data)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @app_commands.command(name="join-meeting", description="Join a scheduled meeting")
    @app_commands.describe(meeting_id="ID of the meeting to join")
    async def join_meeting(self, interaction: discord.Interaction, meeting_id: str):
        # Check if meeting exists
        meeting = await self.bot.db.connection.fetchrow(
            "SELECT * FROM meetings WHERE meeting_id = $1", meeting_id
        )
        
        if not meeting:
            embed = EmbedBuilder.error("Not Found", f"Meeting with ID {meeting_id} not found")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Add user to attendees
        try:
            current_attendees = json.loads(meeting['attendees']) if meeting['attendees'] else []
            user_id = str(interaction.user.id)
            
            if user_id not in current_attendees:
                current_attendees.append(user_id)
                await self.bot.db.connection.execute(
                    "UPDATE meetings SET attendees = $1 WHERE meeting_id = $2",
                    json.dumps(current_attendees), meeting_id
                )
        except Exception as e:
            print(f"Error updating attendees: {e}")
        
        # Get voice channel
        guild = interaction.guild
        voice_channel = guild.get_channel(int(meeting['voice_channel_id']))
        
        embed = discord.Embed(
            title=f"✅ Joined Meeting: {meeting['title']}",
            description=f"{meeting['description']}\n\n**You'll receive a notification when the meeting starts!**",
            color=0x57F287
        )
        
        embed.add_field(name="Meeting ID", value=meeting_id, inline=True)
        
        if voice_channel:
            embed.add_field(name="Voice Channel", value=voice_channel.mention, inline=True)
        
        # Format start time
        start_time = meeting['scheduled_time']
        time_str = start_time.strftime("%Y-%m-%d %H:%M UTC")
        
        if start_time > datetime.utcnow():
            time_until = TimeParser.format_timedelta(start_time - datetime.utcnow())
            embed.add_field(name="Starts", value=f"{time_str}\n(in {time_until})", inline=False)
        else:
            embed.add_field(name="Started", value=time_str, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-meetings", description="List all scheduled meetings")
    async def list_meetings(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            # Filter meetings for this guild
            guild_id = str(interaction.guild.id)
            meetings = await self.bot.db.connection.fetch(
                "SELECT * FROM meetings WHERE guild_id = $1 AND status IN ('scheduled', 'starting') ORDER BY scheduled_time ASC",
                guild_id
            )
            
            if not meetings:
                embed = EmbedBuilder.info("No Meetings", "No meetings are currently scheduled")
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title="📅 Scheduled Meetings",
                description=f"There are {len(meetings)} upcoming meetings",
                color=0x5865F2
            )
            
            for meeting in meetings[:10]:  # Show up to 10 meetings
                start_time = meeting['scheduled_time']
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
                
                # Count attendees
                attendees = json.loads(meeting['attendees']) if meeting['attendees'] else []
                attendee_count = len(attendees)
                
                embed.add_field(
                    name=f"{meeting['title']} (ID: {meeting['meeting_id']})",
                    value=f"**Time:** {time_field}\n**Voice:** {voice_name}\n**Organizer:** {creator_name}\n**Attendees:** {attendee_count}",
                    inline=False
                )
            
            if len(meetings) > 10:
                embed.set_footer(text=f"Showing 10 of {len(meetings)} meetings")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to list meetings: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Meetings(bot))