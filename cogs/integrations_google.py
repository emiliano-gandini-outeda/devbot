import discord
from discord.ext import commands
from discord import app_commands
from utils.oauth_google import GoogleOAuthManager
from utils.helpers import EmbedBuilder
import json

class GoogleIntegrations(commands.Cog):
    """Google Workspace integrations"""
    
    def __init__(self, bot):
        self.bot = bot
        self.oauth_manager = GoogleOAuthManager()
    
    @app_commands.command(name="google-connect", description="Connect your Google account")
    async def google_connect(self, interaction: discord.Interaction):
        state = f"{interaction.user.id}_{interaction.guild.id}"
        auth_url = self.oauth_manager.get_auth_url(state)
        
        embed = EmbedBuilder.info(
            "Google Authentication",
            f"[Click here to connect your Google account]({auth_url})\n\n"
            "This will allow you to:\n"
            "• View and create calendar events\n"
            "• Access Google Drive files\n"
            "• Receive calendar notifications"
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="calendar-events", description="Show your upcoming calendar events")
    @app_commands.describe(count="Number of events to show (max 10)")
    async def calendar_events(self, interaction: discord.Interaction, count: int = 5):
        if count > 10:
            count = 10
        
        await interaction.response.defer()
        
        # Get user's Google token from database
        user = await self.bot.db.get_user(str(interaction.user.id))
        if not user or not user.get('google_token'):
            embed = EmbedBuilder.error(
                "Not Connected",
                "Please connect your Google account first using `/google-connect`"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        try:
            token_data = json.loads(user['google_token'])
            events = await self.oauth_manager.get_calendar_events(
                token_data['access_token'], 
                max_results=count
            )
            
            if not events:
                embed = EmbedBuilder.info("No Events", "No upcoming calendar events found")
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title="📅 Upcoming Calendar Events",
                color=0x4285F4
            )
            
            for event in events:
                title = event.get('summary', 'No Title')
                start = event.get('start', {})
                start_time = start.get('dateTime', start.get('date', 'No time specified'))
                
                embed.add_field(
                    name=title,
                    value=f"**Time:** {start_time}\n**Location:** {event.get('location', 'No location')}",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch calendar events: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="create-event", description="Create a new calendar event")
    @app_commands.describe(
        title="Event title",
        date="Date (YYYY-MM-DD)",
        time="Time (HH:MM)",
        duration="Duration in minutes"
    )
    async def create_event(self, interaction: discord.Interaction, title: str, date: str, time: str, duration: int = 60):
        await interaction.response.defer()
        
        # This would require implementing Google Calendar API event creation
        embed = EmbedBuilder.railway_info(
            "Feature Coming Soon",
            "Calendar event creation will be available in the next Railway deployment!"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    cog = GoogleIntegrations(bot)
    await bot.add_cog(cog)
    
    # Ensure commands are added to the tree
    for command in cog.__cog_app_commands__:
        if command not in bot.tree.get_commands():
            bot.tree.add_command(command)
    
    print(f"📅 Successfully loaded Google Integrations cog with {len(cog.get_app_commands())} commands")
