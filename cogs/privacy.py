import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime
from utils.helpers import EmbedBuilder
import io

class ConfirmDeleteView(discord.ui.View):
    def __init__(self, bot, user_id: int):
        super().__init__(timeout=60)
        self.bot = bot
        self.user_id = user_id
    
    @discord.ui.button(label="Yes, Delete My Data", style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You can only delete your own data!", ephemeral=True)
            return
        
        try:
            user_id_str = str(self.user_id)
            
            # Delete user data from all tables
            await self.bot.db.connection.execute("DELETE FROM tickets WHERE user_id = $1", user_id_str)
            await self.bot.db.connection.execute("DELETE FROM reminders WHERE user_id = $1", user_id_str)
            await self.bot.db.connection.execute("DELETE FROM workflows WHERE creator_id = $1", user_id_str)
            await self.bot.db.connection.execute("DELETE FROM users WHERE discord_id = $1", user_id_str)
            await self.bot.db.connection.execute("DELETE FROM user_data WHERE user_id = $1", user_id_str)
            await self.bot.db.connection.execute("DELETE FROM keywords WHERE user_id = $1", user_id_str)
            
            embed = EmbedBuilder.success(
                "Data Deleted",
                "All your personal data has been permanently deleted from Railway systems."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Deletion Failed", f"Failed to delete data: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = EmbedBuilder.info("Cancelled", "Data deletion request has been cancelled")
        await interaction.response.send_message(embed=embed, ephemeral=True)

class Privacy(commands.Cog):
    """Data privacy and GDPR compliance"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="export-data", description="Export your personal data")
    async def export_data(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_id_str = str(interaction.user.id)
            export_data = {}
            
            # Get user data from all tables
            tickets = await self.bot.db.connection.fetch("SELECT * FROM tickets WHERE user_id = $1", user_id_str)
            reminders = await self.bot.db.connection.fetch("SELECT * FROM reminders WHERE user_id = $1", user_id_str)
            keywords = await self.bot.db.connection.fetch("SELECT * FROM keywords WHERE user_id = $1", user_id_str)
            user_data = await self.bot.db.connection.fetch("SELECT * FROM user_data WHERE user_id = $1", user_id_str)
            
            # Format data for export
            export_data["tickets"] = [dict(ticket) for ticket in tickets]
            export_data["reminders"] = [dict(reminder) for reminder in reminders]
            export_data["keywords"] = [dict(keyword) for keyword in keywords]
            export_data["user_data"] = [dict(data) for data in user_data]
            
            # Add metadata
            export_data["metadata"] = {
                "exported_at": datetime.utcnow().isoformat(),
                "user_id": user_id_str,
                "username": interaction.user.name
            }
            
            # Create JSON file
            export_json = json.dumps(export_data, indent=2, default=str)
            
            # Create file
            filename = f"user_data_export_{interaction.user.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            file = discord.File(fp=io.StringIO(export_json), filename=filename)
            
            embed = EmbedBuilder.success(
                "Data Export Complete",
                "Your personal data has been exported. Please check the attached file."
            )
            
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Export Failed", f"Failed to export data: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="delete-data", description="Request deletion of your personal data")
    async def delete_data(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚠️ Delete Personal Data",
            description="Are you sure you want to delete all your personal data?\n\n"
                       "**This action is permanent and cannot be undone.**\n\n"
                       "The following data will be deleted:\n"
                       "• Tickets\n"
                       "• Reminders\n"
                       "• Keywords\n"
                       "• User preferences\n"
                       "• Other stored data",
            color=0xED4245
        )
        
        view = ConfirmDeleteView(self.bot, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @app_commands.command(name="get-data", description="View summary of your stored data")
    async def get_data(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_id_str = str(interaction.user.id)
            
            # Count data in each table
            ticket_count = await self.bot.db.connection.fetchval(
                "SELECT COUNT(*) FROM tickets WHERE user_id = $1", user_id_str
            )
            
            reminder_count = await self.bot.db.connection.fetchval(
                "SELECT COUNT(*) FROM reminders WHERE user_id = $1", user_id_str
            )
            
            keyword_count = await self.bot.db.connection.fetchval(
                "SELECT COUNT(*) FROM keywords WHERE user_id = $1", user_id_str
            )
            
            user_data_count = await self.bot.db.connection.fetchval(
                "SELECT COUNT(*) FROM user_data WHERE user_id = $1", user_id_str
            )
            
            embed = discord.Embed(
                title="📊 Your Data Summary",
                description="Here's a summary of your data stored by Railway Bot",
                color=0x5865F2
            )
            
            embed.add_field(name="Tickets", value=f"{ticket_count} tickets", inline=True)
            embed.add_field(name="Reminders", value=f"{reminder_count} reminders", inline=True)
            embed.add_field(name="Keywords", value=f"{keyword_count} keywords", inline=True)
            embed.add_field(name="Other Data", value=f"{user_data_count} items", inline=True)
            
            embed.add_field(
                name="Data Management",
                value="• Use `/export-data` to export your data\n"
                      "• Use `/delete-data` to delete your data\n"
                      "• Use `/privacy-policy` to view our privacy policy",
                inline=False
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch data summary: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Privacy(bot))
