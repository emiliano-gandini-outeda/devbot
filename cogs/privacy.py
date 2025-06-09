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
                "All your personal data has been permanently deleted from our systems."
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
    
    @app_commands.command(name="privacy-export-data", description="Export your personal data")
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
    
    @app_commands.command(name="privacy-delete-data", description="Request deletion of your personal data")
    @app_commands.describe(
        data_type="Type of data to delete (tickets, reminders, keywords, all)"
    )
    async def delete_data(self, interaction: discord.Interaction, data_type: str = "all"):
        valid_types = ["tickets", "reminders", "keywords", "all"]
        if data_type not in valid_types:
            embed = EmbedBuilder.error(
                "Invalid Data Type",
                f"Data type must be one of: {', '.join(valid_types)}"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        embed = discord.Embed(
            title="⚠️ Delete Personal Data",
            description=f"Are you sure you want to delete your {data_type} data?\n\n"
                       "**This action is permanent and cannot be undone.**\n\n"
                       f"The following data will be deleted:\n"
                       f"{'• All your personal data' if data_type == 'all' else f'• Your {data_type}'}\n",
            color=0xED4245
        )
        
        view = ConfirmDeleteView(self.bot, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @app_commands.command(name="privacy-get-data", description="View summary of your stored data")
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
                description="Here's a summary of your data stored by devBot",
                color=0x5865F2
            )
            
            embed.add_field(name="Tickets", value=f"{ticket_count} tickets", inline=True)
            embed.add_field(name="Reminders", value=f"{reminder_count} reminders", inline=True)
            embed.add_field(name="Keywords", value=f"{keyword_count} keywords", inline=True)
            embed.add_field(name="Other Data", value=f"{user_data_count} items", inline=True)
            
            embed.add_field(
                name="Data Management",
                value="• Use `/privacy-export-data` to export your data\n"
                      "• Use `/privacy-delete-data` to delete your data\n"
                      "• Use `/privacy-policy` to view our privacy policy",
                inline=False
            )
            
            embed.set_footer(text="devBot - Powered by EGOS")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch data summary: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="privacy-policy", description="View the bot's privacy policy")
    async def privacy_policy(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔒 Privacy Policy",
            description="Information about how devBot handles your data",
            color=0x5865F2,
            url="https://github.com/emiliano-gandini-outeda/devbot/blob/main/PRIVACY_POLICY.txt"
        )
        
        embed.add_field(
            name="Data Collection",
            value="• Server configurations\n• User commands and interactions\n• Ticket and reminder data\n• Message content for keyword notifications",
            inline=False
        )
        
        embed.add_field(
            name="Data Usage",
            value="• Provide bot functionality\n• Improve user experience\n• Debug and error tracking",
            inline=False
        )
        
        embed.add_field(
            name="Data Storage",
            value="• Data is stored securely\n• No data is shared with third parties\n• Data can be deleted upon request",
            inline=False
        )
        
        embed.add_field(
            name="Your Rights",
            value="• Request data export\n• Request data deletion\n• Contact support for questions",
            inline=False
        )
        
        embed.set_footer(text="devBot - Powered by EGOS")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="terms-of-service", description="View the bot's terms of service")
    async def terms_of_service(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📜 Terms of Service",
            description="Terms and conditions for using devBot",
            color=0x5865F2,
            url="https://github.com/emiliano-gandini-outeda/devbot/blob/main/TERMS_OF_SERVICE.txt"
        )
        
        embed.add_field(
            name="Usage Agreement",
            value="By using devBot, you agree to abide by these terms and conditions.",
            inline=False
        )
        
        embed.add_field(
            name="Acceptable Use",
            value="• Do not use the bot for illegal activities\n• Do not attempt to exploit or abuse the bot\n• Do not use the bot to harass or spam others",
            inline=False
        )
        
        embed.add_field(
            name="Limitations",
            value="• The bot is provided 'as is' without warranties\n• We reserve the right to modify or terminate services\n• We are not responsible for any damages resulting from bot use",
            inline=False
        )
        
        embed.set_footer(text="devBot - Powered by EGOS")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="get-data", description="Get all data for a specific user (Admin only)")
    @app_commands.describe(user="User to get data for")
    async def get_user_data(self, interaction: discord.Interaction, user: discord.Member):
        # Check if admin
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can use this command")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_id_str = str(user.id)
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
            
            # Add user profile data
            export_data["profile"] = {
                "discord_id": user_id_str,
                "username": user.name,
                "display_name": user.display_name,
                "joined_at": user.joined_at.isoformat() if user.joined_at else None,
                "created_at": user.created_at.isoformat(),
                "roles": [role.name for role in user.roles[1:]],  # Skip @everyone
                "avatar_url": str(user.display_avatar.url)
            }
            
            # Add metadata
            export_data["metadata"] = {
                "exported_at": datetime.utcnow().isoformat(),
                "exported_by": str(interaction.user.id),
                "exported_by_name": interaction.user.name
            }
            
            # Create JSON file
            export_json = json.dumps(export_data, indent=2, default=str)
            
            # Create file
            filename = f"user_data_{user.name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            file = discord.File(fp=io.StringIO(export_json), filename=filename)
            
            embed = EmbedBuilder.success(
                "User Data Retrieved",
                f"Data for {user.mention} has been retrieved and is attached as a JSON file."
            )
            
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to retrieve user data: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Privacy(bot))
