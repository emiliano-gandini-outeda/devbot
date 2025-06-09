import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import json
from datetime import datetime

class Logging(commands.Cog):
    """Server logging and audit system"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="setup-logs", description="Configure server logging (Admin only)")
    @app_commands.describe(
        log_channel="Channel to send logs to",
        events="Events to log (comma-separated: message_delete, message_edit, member_join, member_leave)"
    )
    async def setup_logs(self, interaction: discord.Interaction, log_channel: discord.TextChannel, events: str = "message_delete,message_edit,member_join,member_leave"):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can configure logging")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        valid_events = ["message_delete", "message_edit", "member_join", "member_leave", "role_update", "channel_create", "channel_delete"]
        event_list = [e.strip() for e in events.split(",")]
        
        # Validate events
        invalid_events = [e for e in event_list if e not in valid_events]
        if invalid_events:
            embed = EmbedBuilder.error(
                "Invalid Events",
                f"Invalid events: {', '.join(invalid_events)}\n"
                f"Valid events: {', '.join(valid_events)}"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # Save logging configuration
            config = {
                'log_channel_id': str(log_channel.id),
                'events': event_list,
                'enabled': True
            }
            
            await self.bot.db.connection.execute(
                """INSERT INTO user_data (user_id, guild_id, data_type, data_content)
                   VALUES ($1, $1, $2, $3)
                   ON CONFLICT (user_id, guild_id, data_type) DO UPDATE SET
                   data_content = $3, updated_at = CURRENT_TIMESTAMP""",
                str(interaction.guild.id), 'logging_config', json.dumps(config)
            )
            
            embed = EmbedBuilder.success(
                "Logging Configured",
                f"Server logging has been set up!\n"
                f"**Log Channel:** {log_channel.mention}\n"
                f"**Events:** {', '.join(event_list)}"
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to configure logging: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="export-data", description="Export server data (Admin only)")
    @app_commands.describe(data_type="Type of data to export (logs, tickets, reminders, all)")
    async def export_data(self, interaction: discord.Interaction, data_type: str = "all"):
        if not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can export data")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        valid_types = ["logs", "tickets", "reminders", "all"]
        if data_type not in valid_types:
            embed = EmbedBuilder.error(
                "Invalid Data Type",
                f"Data type must be one of: {', '.join(valid_types)}"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        try:
            export_data = {}
            guild_id = str(interaction.guild.id)
            
            if data_type in ["logs", "all"]:
                # Export logs (if any logging system is implemented)
                export_data["logs"] = {"message": "Logs export not yet implemented"}
            
            if data_type in ["tickets", "all"]:
                # Export tickets
                if self.bot.db.is_postgresql:
                    tickets = await self.bot.db.connection.fetch(
                        "SELECT * FROM tickets WHERE guild_id = $1", guild_id
                    )
                    export_data["tickets"] = [dict(ticket) for ticket in tickets]
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT * FROM tickets WHERE guild_id = ?", (guild_id,)
                    )
                    tickets = await cursor.fetchall()
                    export_data["tickets"] = [dict(ticket) for ticket in tickets]
            
            if data_type in ["reminders", "all"]:
                # Export reminders
                if self.bot.db.is_postgresql:
                    reminders = await self.bot.db.connection.fetch(
                        "SELECT * FROM reminders WHERE guild_id = $1", guild_id
                    )
                    export_data["reminders"] = [dict(reminder) for reminder in reminders]
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT * FROM reminders WHERE guild_id = ?", (guild_id,)
                    )
                    reminders = await cursor.fetchall()
                    export_data["reminders"] = [dict(reminder) for reminder in reminders]
            
            # Create JSON file
            export_json = json.dumps(export_data, indent=2, default=str)
            
            # Create file
            filename = f"{interaction.guild.name}_{data_type}_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            
            # Send file
            file = discord.File(
                fp=discord.utils.StringIO(export_json),
                filename=filename
            )
            
            embed = EmbedBuilder.success(
                "Data Exported",
                f"Successfully exported {data_type} data for {interaction.guild.name}"
            )
            
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to export data: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="delete-data", description="Delete server data (Admin only)")
    @app_commands.describe(
        data_type="Type of data to delete (tickets, reminders, keywords)",
        confirm="Type 'CONFIRM' to proceed with deletion"
    )
    async def delete_data(self, interaction: discord.Interaction, data_type: str, confirm: str):
        if not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can delete data")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        if confirm != "CONFIRM":
            embed = EmbedBuilder.error(
                "Confirmation Required",
                "To delete data, you must type 'CONFIRM' in the confirm parameter"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        valid_types = ["tickets", "reminders", "keywords"]
        if data_type not in valid_types:
            embed = EmbedBuilder.error(
                "Invalid Data Type",
                f"Data type must be one of: {', '.join(valid_types)}"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            guild_id = str(interaction.guild.id)
            
            if data_type == "tickets":
                if self.bot.db.is_postgresql:
                    result = await self.bot.db.connection.execute(
                        "DELETE FROM tickets WHERE guild_id = $1", guild_id
                    )
                else:
                    result = await self.bot.db.connection.execute(
                        "DELETE FROM tickets WHERE guild_id = ?", (guild_id,)
                    )
                    await self.bot.db.connection.commit()
            
            elif data_type == "reminders":
                if self.bot.db.is_postgresql:
                    result = await self.bot.db.connection.execute(
                        "DELETE FROM reminders WHERE guild_id = $1", guild_id
                    )
                else:
                    result = await self.bot.db.connection.execute(
                        "DELETE FROM reminders WHERE guild_id = ?", (guild_id,)
                    )
                    await self.bot.db.connection.commit()
            
            elif data_type == "keywords":
                if self.bot.db.is_postgresql:
                    result = await self.bot.db.connection.execute(
                        "DELETE FROM keywords WHERE guild_id = $1", guild_id
                    )
                else:
                    result = await self.bot.db.connection.execute(
                        "DELETE FROM keywords WHERE guild_id = ?", (guild_id,)
                    )
                    await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Data Deleted",
                f"Successfully deleted all {data_type} data for this server"
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to delete data: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="privacy-policy", description="View the bot's privacy policy")
    async def privacy_policy(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔒 Privacy Policy",
            description="Information about how Railway Bot handles your data",
            color=0x5865F2
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
            value="• Data is stored securely on Railway\n• No data is shared with third parties\n• Data can be deleted upon request",
            inline=False
        )
        
        embed.add_field(
            name="Your Rights",
            value="• Request data export\n• Request data deletion\n• Contact support for questions",
            inline=False
        )
        
        embed.set_footer(text="For questions, contact the bot administrator")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Event listeners for logging
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Log deleted messages"""
        if message.author.bot:
            return
        
        await self._log_event("message_delete", message.guild, {
            "author": str(message.author),
            "channel": str(message.channel),
            "content": message.content[:1000] if message.content else "No content",
            "timestamp": datetime.utcnow().isoformat()
        })
    
    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        """Log edited messages"""
        if before.author.bot or before.content == after.content:
            return
        
        await self._log_event("message_edit", before.guild, {
            "author": str(before.author),
            "channel": str(before.channel),
            "before": before.content[:500] if before.content else "No content",
            "after": after.content[:500] if after.content else "No content",
            "timestamp": datetime.utcnow().isoformat()
        })
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Log member joins"""
        await self._log_event("member_join", member.guild, {
            "user": str(member),
            "user_id": str(member.id),
            "account_created": member.created_at.isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        })
    
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Log member leaves"""
        await self._log_event("member_leave", member.guild, {
            "user": str(member),
            "user_id": str(member.id),
            "roles": [role.name for role in member.roles[1:]],  # Skip @everyone
            "timestamp": datetime.utcnow().isoformat()
        })
    
    async def _log_event(self, event_type: str, guild: discord.Guild, data: dict):
        """Internal method to log events"""
        try:
            # Get logging configuration
            if self.bot.db.is_postgresql:
                config_row = await self.bot.db.connection.fetch(
                    "SELECT config_value FROM guild_configs WHERE guild_id = $1 AND config_key = $2",
                    str(guild.id), 'logging'
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT config_value FROM guild_configs WHERE guild_id = ? AND config_key = ?",
                    (str(guild.id), 'logging')
                )
                config_row = await cursor.fetchone()
            
            if not config_row:
                return
            
            config = json.loads(config_row['config_value'] if self.bot.db.is_postgresql else config_row[0])
            
            if not config.get('enabled', False) or event_type not in config.get('events', []):
                return
            
            log_channel_id = config.get('log_channel_id')
            if not log_channel_id:
                return
            
            channel = guild.get_channel(int(log_channel_id))
            if not channel:
                return
            
            # Create log embed
            embed = discord.Embed(
                title=f"📝 {event_type.replace('_', ' ').title()}",
                color=0x5865F2,
                timestamp=datetime.utcnow()
            )
            
            for key, value in data.items():
                if key != 'timestamp':
                    embed.add_field(name=key.title(), value=str(value), inline=True)
            
            await channel.send(embed=embed)
            
        except Exception as e:
            print(f"Error logging event {event_type}: {e}")

async def setup(bot):
    await bot.add_cog(Logging(bot))
