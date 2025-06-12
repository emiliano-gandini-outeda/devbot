import discord
from discord.ext import commands
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

            # Send the meeting announcement with the selected ping
            if self.selected_ping == "everyone":
                allowed_mentions = discord.AllowedMentions(everyone=True)
                content = "@everyone - New admin meeting scheduled!"
            else:  # here
                allowed_mentions = discord.AllowedMentions(everyone=False, here=True)
                content = "@here - New admin meeting scheduled!"

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
        # Add user to participants
        self.participants.add(interaction.user.id)
        
        # Get meeting data
        meeting = await self.bot.db.connection.fetchrow(
            "SELECT * FROM meetings WHERE meeting_id = $1", self.meeting_id
        )
        
        if not meeting:
            await interaction.response.send_message("This meeting no longer exists.", ephemeral=True)
            return
        
        await interaction.response.send_message(f"You've joined the meeting: **{meeting['title']}**", ephemeral=True)

class Meetings(commands.Cog):
    """Meeting scheduling and management"""
    
    def __init__(self, bot):
        self.bot = bot
    
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
        
        # Get voice channel
        guild = interaction.guild
        voice_channel = guild.get_channel(int(meeting['voice_channel_id']))
        
        embed = discord.Embed(
            title=f"✅ Joined Meeting: {meeting['title']}",
            description=meeting['description'],
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
                "SELECT * FROM meetings WHERE guild_id = $1 AND status = 'scheduled' ORDER BY scheduled_time ASC",
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
                
                embed.add_field(
                    name=f"{meeting['title']} (ID: {meeting['meeting_id']})",
                    value=f"**Time:** {time_field}\n**Voice:** {voice_name}\n**Organizer:** {creator_name}",
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