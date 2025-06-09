import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import json

class TrelloIntegrations(commands.Cog):
    """Trello integration commands"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="trello-boards", description="List your Trello boards")
    async def trello_boards(self, interaction: discord.Interaction):
        embed = EmbedBuilder.info(
            "Trello Integration",
            "Trello integration is not yet implemented. This feature will allow you to:\n\n"
            "• List your Trello boards\n"
            "• View board lists and cards\n"
            "• Create new cards from Discord\n"
            "• Get notifications for card updates\n\n"
            "Stay tuned for updates!"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="create-task", description="Create a new task in Trello")
    @app_commands.describe(
        board_id="Trello board ID",
        list_name="Name of the list to add the task to",
        task_name="Name of the task",
        description="Task description (optional)"
    )
    async def create_task(self, interaction: discord.Interaction, board_id: str, list_name: str, task_name: str, description: str = None):
        embed = EmbedBuilder.info(
            "Trello Integration",
            "Trello integration is not yet implemented. This command would create a new task with:\n\n"
            f"**Board ID:** {board_id}\n"
            f"**List:** {list_name}\n"
            f"**Task:** {task_name}\n"
            f"**Description:** {description or 'None'}\n\n"
            "Stay tuned for updates!"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="trello-card", description="Get information about a Trello card")
    @app_commands.describe(card_id="Trello card ID")
    async def trello_card(self, interaction: discord.Interaction, card_id: str):
        embed = EmbedBuilder.info(
            "Trello Integration",
            f"Trello integration is not yet implemented. This would show details for card: **{card_id}**\n\n"
            "This feature will show:\n"
            "• Card title and description\n"
            "• Due date and labels\n"
            "• Members and checklist progress\n"
            "• Recent activity\n\n"
            "Stay tuned for updates!"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    cog = TrelloIntegrations(bot)
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
            print(f"✅ Synced Trello Integrations commands to {guild.name}")
        except Exception as e:
            print(f"❌ Failed to sync Trello Integrations commands to {guild.name}: {e}")
    
    print(f"📋 Successfully loaded Trello Integrations cog with {len(cog.get_app_commands())} commands")
