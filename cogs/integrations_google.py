import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import json
from datetime import datetime, timedelta
import asyncio

class GoogleIntegrations(commands.Cog):
    """Google Workspace integration"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="google-connect", description="Connect your Google account")
    async def google_connect(self, interaction: discord.Interaction):
        # This would normally use OAuth2 flow, but we'll mock it for this implementation
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Check if user already has a token
            user_data = await self.bot.db.connection.fetchrow(
                "SELECT * FROM users WHERE discord_id = $1", str(interaction.user.id)
            )
            
            if user_data and user_data['google_token']:
                embed = EmbedBuilder.info(
                    "Already Connected",
                    "Your Google account is already connected. Use `/google-disconnect` to disconnect it."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Create mock auth URL
            auth_url = "https://accounts.google.com/o/oauth2/auth?client_id=mock_client_id&redirect_uri=https://example.com/callback&scope=https://www.googleapis.com/auth/calendar.readonly&response_type=code"
            
            embed = discord.Embed(
                title="🔗 Connect Google Account",
                description="Click the link below to connect your Google account. This will give devBot read-only access to your Google Calendar.",
                color=0x4285F4  # Google blue
            )
            
            embed.add_field(
                name="Authorization Link",
                value=f"[Click here to connect]({auth_url})",
                inline=False
            )
            
            embed.add_field(
                name="Next Steps",
                value="1. Click the link above\n2. Sign in to your Google account\n3. Authorize the requested permissions\n4. Copy the code from the redirect URL\n5. Use `/google-auth-code <code>` to complete the connection",
                inline=False
            )
            
            embed.set_footer(text="Your data is kept private and secure")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to start Google connection: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="calendar-events", description="Show your upcoming Google Calendar events")
    @app_commands.describe(count="Number of events to show (default: 5, max: 10)")
    async def calendar_events(self, interaction: discord.Interaction, count: int = 5):
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Validate count
            if count > 10:
                count = 10
            elif count < 1:
                count = 5
            
            # Check if user has connected Google account
            user_data = await self.bot.db.connection.fetchrow(
                "SELECT * FROM users WHERE discord_id = $1", str(interaction.user.id)
            )
            
            if not user_data or not user_data['google_token']:
                embed = EmbedBuilder.error(
                    "Not Connected",
                    "Your Google account is not connected. Use `/google-connect` to connect it."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Mock calendar events
            events = self._mock_calendar_events(count)
            
            embed = discord.Embed(
                title="📅 Your Upcoming Events",
                description=f"Showing your next {len(events)} calendar events",
                color=0x4285F4  # Google blue
            )
            
            for event in events:
                embed.add_field(
                    name=f"{event['title']}",
                    value=f"**When:** {event['start']}\n**Where:** {event['location']}\n**Calendar:** {event['calendar']}",
                    inline=False
                )
            
            embed.set_footer(text="Google Calendar • devBot")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch calendar events: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="create-event", description="Create a new Google Calendar event")
    @app_commands.describe(
        title="Event title",
        date="Event date (YYYY-MM-DD)",
        time="Event time (HH:MM)",
        duration="Event duration in minutes (default: 60)"
    )
    async def create_event(self, interaction: discord.Interaction, title: str, date: str, time: str, duration: int = 60):
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Check if user has connected Google account
            user_data = await self.bot.db.connection.fetchrow(
                "SELECT * FROM users WHERE discord_id = $1", str(interaction.user.id)
            )
            
            if not user_data or not user_data['google_token']:
                embed = EmbedBuilder.error(
                    "Not Connected",
                    "Your Google account is not connected. Use `/google-connect` to connect it."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Validate date and time format
            try:
                event_datetime = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            except ValueError:
                embed = EmbedBuilder.error(
                    "Invalid Format",
                    "Please use the format YYYY-MM-DD for date and HH:MM for time"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Mock event creation
            embed = discord.Embed(
                title="🚧 Feature Coming Soon",
                description="Creating Google Calendar events is coming soon!",
                color=0xFEE75C
            )
            
            embed.add_field(
                name="Event Details",
                value=f"**Title:** {title}\n**Date:** {date}\n**Time:** {time}\n**Duration:** {duration} minutes",
                inline=False
            )
            
            embed.add_field(
                name="Note",
                value="This feature is under development. Check back soon!",
                inline=False
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create event: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    def _mock_calendar_events(self, count):
        """Generate mock calendar events"""
        calendars = ["Work", "Personal", "Family", "Project X"]
        locations = ["Office", "Home", "Conference Room A", "Virtual Meeting", "Coffee Shop"]
        
        events = []
        now = datetime.utcnow()
        
        for i in range(count):
            event_time = now + timedelta(days=i, hours=random.randint(0, 23), minutes=random.randint(0, 59))
            
            events.append({
                "title": f"Mock Event {i+1}",
                "start": event_time.strftime("%Y-%m-%d %H:%M"),
                "location": random.choice(locations),
                "calendar": random.choice(calendars)
            })
        
        return events

async def setup(bot):
    await bot.add_cog(GoogleIntegrations(bot))
