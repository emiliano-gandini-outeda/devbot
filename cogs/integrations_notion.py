import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import json

class NotionIntegrations(commands.Cog):
    """Notion integration commands"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="notion-databases", description="List your Notion databases")
    async def notion_databases(self, interaction: discord.Interaction):
        embed = EmbedBuilder.info(
            "Notion Integration",
            "Notion integration is not yet implemented. This feature will allow you to:\n\n"
            "• List your Notion databases\n"
            "• Create new pages and notes\n"
            "• Search your Notion workspace\n"
            "• Sync Discord messages to Notion\n\n"
            "Stay tuned for updates!"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="create-note", description="Create a new note in Notion")
    @app_commands.describe(
        title="Title for the note",
        content="Content of the note",
        database_id="Notion database ID (optional)"
    )
    async def create_note(self, interaction: discord.Interaction, title: str, content: str, database_id: str = None):
        embed = EmbedBuilder.info(
            "Notion Integration",
            "Notion integration is not yet implemented. This command would create a new note with:\n\n"
            f"**Title:** {title}\n"
            f"**Content:** {content[:100]}{'...' if len(content) > 100 else ''}\n"
            f"**Database:** {database_id or 'Default'}\n\n"
            "Stay tuned for updates!"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="notion-search", description="Search your Notion workspace")
    @app_commands.describe(query="Search query")
    async def notion_search(self, interaction: discord.Interaction, query: str):
        embed = EmbedBuilder.info(
            "Notion Integration",
            f"Notion search is not yet implemented. This would search for: **{query}**\n\n"
            "This feature will allow you to:\n"
            "• Search across all your Notion pages\n"
            "• Filter by database or page type\n"
            "• Get quick links to results\n\n"
            "Stay tuned for updates!"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    cog = NotionIntegrations(bot)
    await bot.add_cog(cog)
    
    # Ensure commands are added to the tree
    for command in cog.get_app_commands():
        if command not in bot.tree.get_commands():
            bot.tree.add_command(command)
    
    print(f"📚 Successfully loaded Notion Integrations cog with {len(cog.get_app_commands())} commands")
