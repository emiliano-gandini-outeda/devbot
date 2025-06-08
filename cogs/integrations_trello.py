import discord
from discord.ext import commands
from discord import app_commands
from utils.trello_api import TrelloAPI
from utils.helpers import EmbedBuilder

class TrelloIntegrations(commands.Cog):
    """Trello project management integrations"""
    
    def __init__(self, bot):
        self.bot = bot
        self.trello = TrelloAPI()
    
    @app_commands.command(name="trello-boards", description="List your Trello boards")
    async def trello_boards(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            boards = await self.trello.get_boards()
            
            if not boards:
                embed = EmbedBuilder.info("No Boards", "No Trello boards found or invalid credentials")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            embed = discord.Embed(
                title="📋 Your Trello Boards",
                color=0x0079BF
            )
            
            for board in boards[:10]:  # Show first 10 boards
                embed.add_field(
                    name=board['name'],
                    value=f"ID: `{board['id']}`\n[Open Board]({board['url']})",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch boards: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="create-task", description="Create a new task in Trello")
    @app_commands.describe(
        board_id="Trello board ID",
        list_name="List name (e.g., 'To Do')",
        task_name="Task name",
        description="Task description"
    )
    async def create_task(self, interaction: discord.Interaction, board_id: str, list_name: str, task_name: str, description: str = ""):
        await interaction.response.defer()
        
        embed = EmbedBuilder.railway_info(
            "Feature Coming Soon",
            "Trello task creation will be available in the next Railway deployment!"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(TrelloIntegrations(bot))
