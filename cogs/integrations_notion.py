import discord
from discord.ext import commands
from discord import app_commands
from utils.notion_api import NotionAPI
from utils.helpers import EmbedBuilder

class NotionIntegrations(commands.Cog):
    """Notion workspace integrations"""
    
    def __init__(self, bot):
        self.bot = bot
        self.notion = NotionAPI()
    
    @app_commands.command(name="notion-databases", description="List your Notion databases")
    async def notion_databases(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            databases = await self.notion.get_databases()
            
            if not databases:
                embed = EmbedBuilder.info("No Databases", "No Notion databases found or invalid token")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            embed = discord.Embed(
                title="📚 Your Notion Databases",
                color=0x000000
            )
            
            for db in databases[:10]:  # Show first 10 databases
                title = db.get('title', [{}])[0].get('plain_text', 'Untitled')
                embed.add_field(
                    name=title,
                    value=f"ID: `{db['id']}`\nURL: [Open]({db['url']})",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch databases: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="create-note", description="Create a quick note in Notion")
    @app_commands.describe(
        title="Note title",
        content="Note content",
        database_id="Database ID (optional)"
    )
    async def create_note(self, interaction: discord.Interaction, title: str, content: str, database_id: str = None):
        await interaction.response.defer()
        
        embed = EmbedBuilder.railway_info(
            "Feature Coming Soon",
            "Notion note creation will be available in the next Railway deployment!"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    cog = NotionIntegrations(bot)
    await bot.add_cog(cog)
    
    # Ensure commands are added to the tree
    for command in cog.__cog_app_commands__:
        if command not in bot.tree.get_commands():
            bot.tree.add_command(command)
    
    print(f"📚 Successfully loaded Notion Integrations cog with {len(cog.get_app_commands())} commands")
