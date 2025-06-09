import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime
from utils.helpers import EmbedBuilder
import io

class Privacy(commands.Cog):
    """Privacy and data management commands"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="export-data", description="Request export of your personal data")
    async def export_data(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_id = str(interaction.user.id)
            
            # Collect user data from various tables
            data_export = {
                "user_info": {
                    "discord_id": user_id,
                    "username": interaction.user.name,
                    "export_date": datetime.utcnow().isoformat(),
                    "platform": "Railway 🚄"
                },
                "tickets": [],
                "reminders": [],
                "workflows": []
            }
            
            # Get user's tickets (adapted for PostgreSQL/SQLite)
            if self.bot.db.is_postgresql:
                tickets = await self.bot.db.connection.fetch(
                    "SELECT * FROM tickets WHERE user_id = $1", user_id
                )
                for ticket in tickets:
                    data_export["tickets"].append({
                        "ticket_id": ticket['ticket_id'],
                        "title": ticket['title'],
                        "description": ticket['description'],
                        "status": ticket['status'],
                        "created_at": str(ticket['created_at'])
                    })
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM tickets WHERE user_id = ?", (user_id,)
                )
                tickets = await cursor.fetchall()
                for ticket in tickets:
                    data_export["tickets"].append({
                        "ticket_id": ticket[1],
                        "title": ticket[5],
                        "description": ticket[6],
                        "status": ticket[7],
                        "created_at": ticket[10]
                    })
            
            # Get user's reminders
            if self.bot.db.is_postgresql:
                reminders = await self.bot.db.connection.fetch(
                    "SELECT * FROM reminders WHERE user_id = $1", user_id
                )
                for reminder in reminders:
                    data_export["reminders"].append({
                        "message": reminder['message'],
                        "remind_at": str(reminder['remind_at']),
                        "type": reminder['type'],
                        "created_at": str(reminder['created_at'])
                    })
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM reminders WHERE user_id = ?", (user_id,)
                )
                reminders = await cursor.fetchall()
                for reminder in reminders:
                    data_export["reminders"].append({
                        "message": reminder[4],
                        "remind_at": reminder[5],
                        "type": reminder[6],
                        "created_at": reminder[8]
                    })
            
            # Get user's workflows
            if self.bot.db.is_postgresql:
                workflows = await self.bot.db.connection.fetch(
                    "SELECT * FROM workflows WHERE creator_id = $1", user_id
                )
                for workflow in workflows:
                    data_export["workflows"].append({
                        "name": workflow['name'],
                        "trigger_type": workflow['trigger_type'],
                        "status": workflow['status'],
                        "created_at": str(workflow['created_at'])
                    })
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM workflows WHERE creator_id = ?", (user_id,)
                )
                workflows = await cursor.fetchall()
                for workflow in workflows:
                    data_export["workflows"].append({
                        "name": workflow[1],
                        "trigger_type": workflow[4],
                        "status": workflow[7],
                        "created_at": workflow[8]
                    })
            
            # Create and send the export file
            export_json = json.dumps(data_export, indent=2, default=str)

            file_buffer = io.BytesIO(export_json.encode('utf-8'))
            file = discord.File(
                file_buffer,
                filename=f"data_export_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )

            embed = EmbedBuilder.success(
                "Data Export Ready",
                "Your personal data has been exported. This includes:\n"
                "• Support tickets\n"
                "• Reminders\n"
                "• Workflows you created\n\n"
                "The data is provided in JSON format."
            )

            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Export Failed", f"Failed to export data: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="delete-data", description="Request deletion of your personal data")
    async def delete_data(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚠️ Data Deletion Request",
            description=(
                "This will permanently delete all your personal data from Railway including:\n"
                "• Support tickets\n"
                "• Reminders\n"
                "• Workflows\n"
                "• Integration tokens\n\n"
                "**This action cannot be undone!**\n\n"
                "Are you sure you want to continue?"
            ),
            color=0xED4245
        )
        
        view = ConfirmDeleteView(self.bot, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @app_commands.command(name="privacy-policy", description="View the bot's privacy policy")
    async def privacy_policy(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔒 Privacy Policy",
            description=(
                "**Data Collection:**\n"
                "• Discord user ID and username\n"
                "• Messages for ticket/reminder content\n"
                "• Integration tokens (encrypted)\n\n"
                
                "**Data Usage:**\n"
                "• Provide bot functionality\n"
                "• Store user preferences\n"
                "• Enable integrations\n\n"
                
                "**Data Storage:**\n"
                "• Stored securely in Railway PostgreSQL\n"
                "• Not shared with third parties\n"
                "• Retained only as long as necessary\n\n"
                
                "**Your Rights:**\n"
                "• Request data export\n"
                "• Request data deletion\n"
                "• Opt out of data collection\n\n"
                
                "**Contact:**\n"
                "For privacy concerns, contact the bot administrator."
            ),
            color=0x5865F2
        )
        embed.set_footer(text="Deployed on Railway 🚄")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="get-data", description="Get information about your stored data")
    async def get_data(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_id = str(interaction.user.id)
            guild_id = str(interaction.guild.id)
            data_summary = {}
            
            # Check tickets
            if self.bot.db.is_postgresql:
                tickets = await self.bot.db.connection.fetch(
                    "SELECT COUNT(*) as count FROM tickets WHERE user_id = $1 AND guild_id = $2",
                    user_id, guild_id
                )
                data_summary['tickets'] = tickets[0]['count'] if tickets else 0
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT COUNT(*) as count FROM tickets WHERE user_id = ? AND guild_id = ?",
                    (user_id, guild_id)
                )
                result = await cursor.fetchone()
                data_summary['tickets'] = result[0] if result else 0
            
            # Check reminders
            if self.bot.db.is_postgresql:
                reminders = await self.bot.db.connection.fetch(
                    "SELECT COUNT(*) as count FROM reminders WHERE user_id = $1 AND guild_id = $2",
                    user_id, guild_id
                )
                data_summary['reminders'] = reminders[0]['count'] if reminders else 0
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT COUNT(*) as count FROM reminders WHERE user_id = ? AND guild_id = ?",
                    (user_id, guild_id)
                )
                result = await cursor.fetchone()
                data_summary['reminders'] = result[0] if result else 0
            
            # Check keywords
            if self.bot.db.is_postgresql:
                keywords = await self.bot.db.connection.fetch(
                    "SELECT COUNT(*) as count FROM keywords WHERE user_id = $1 AND guild_id = $2",
                    user_id, guild_id
                )
                data_summary['keywords'] = keywords[0]['count'] if keywords else 0
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT COUNT(*) as count FROM keywords WHERE user_id = ? AND guild_id = ?",
                    (user_id, guild_id)
                )
                result = await cursor.fetchone()
                data_summary['keywords'] = result[0] if result else 0
            
            embed = discord.Embed(
                title="📊 Your Data Summary",
                description=f"Data stored for {interaction.user.mention} in {interaction.guild.name}",
                color=0x5865F2
            )
            
            embed.add_field(name="🎫 Tickets", value=str(data_summary['tickets']), inline=True)
            embed.add_field(name="⏰ Reminders", value=str(data_summary['reminders']), inline=True)
            embed.add_field(name="🔔 Keywords", value=str(data_summary['keywords']), inline=True)
            
            total_items = sum(data_summary.values())
            embed.add_field(name="📈 Total Items", value=str(total_items), inline=False)
            
            embed.add_field(
                name="ℹ️ Data Types",
                value="• **Tickets**: Support tickets you've created\n"
                      "• **Reminders**: Reminders you've set\n"
                      "• **Keywords**: Keywords you're watching for notifications",
                inline=False
            )
            
            embed.set_footer(text="Use /privacy-policy to learn more about data handling")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to retrieve data summary: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

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
            
            # Delete user data from all tables (adapted for PostgreSQL/SQLite)
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute("DELETE FROM tickets WHERE user_id = $1", user_id_str)
                await self.bot.db.connection.execute("DELETE FROM reminders WHERE user_id = $1", user_id_str)
                await self.bot.db.connection.execute("DELETE FROM workflows WHERE creator_id = $1", user_id_str)
                await self.bot.db.connection.execute("DELETE FROM users WHERE discord_id = $1", user_id_str)
                await self.bot.db.connection.execute("DELETE FROM user_data WHERE user_id = $1", user_id_str)
            else:
                await self.bot.db.connection.execute("DELETE FROM tickets WHERE user_id = ?", (user_id_str,))
                await self.bot.db.connection.execute("DELETE FROM reminders WHERE user_id = ?", (user_id_str,))
                await self.bot.db.connection.execute("DELETE FROM workflows WHERE creator_id = ?", (user_id_str,))
                await self.bot.db.connection.execute("DELETE FROM users WHERE discord_id = ?", (user_id_str,))
                await self.bot.db.connection.execute("DELETE FROM user_data WHERE user_id = ?", (user_id_str,))
                await self.bot.db.connection.commit()
            
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
        embed = EmbedBuilder.info("Cancelled", "Data deletion request has been cancelled.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    cog = Privacy(bot)
    await bot.add_cog(cog)
    
    # Ensure commands are added to the tree
    for command in cog.get_app_commands():
        if command not in bot.tree.get_commands():
            bot.tree.add_command(command)
    
    print(f"🔒 Successfully loaded Privacy cog with {len(cog.get_app_commands())} commands")
