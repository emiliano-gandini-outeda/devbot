import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import json

class Setup(commands.Cog):
    """Server setup and configuration commands"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="setup-tickets", description="Setup ticket system (Admin only)")
    @app_commands.describe(
        category="Category where ticket channels will be created",
        transcript_channel="Channel where ticket transcripts will be sent"
    )
    async def setup_tickets(self, interaction: discord.Interaction, category: discord.CategoryChannel, transcript_channel: discord.TextChannel):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can setup the ticket system")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            config = {
                'category_id': str(category.id),
                'transcript_channel_id': str(transcript_channel.id),
                'setup_by': str(interaction.user.id),
                'setup_at': str(discord.utils.utcnow())
            }
            
            # Store in user_data table using the ticket manager
            if hasattr(self.bot, 'ticket_manager') and self.bot.ticket_manager:
                await self.bot.ticket_manager.save_ticket_config(str(interaction.guild.id), config)
            else:
                # Fallback if ticket_manager is not available
                guild_id = str(interaction.guild.id)
                if self.bot.db.is_postgresql:
                    await self.bot.db.connection.execute(
                        """INSERT INTO user_data (user_id, guild_id, data_type, data_content) 
                           VALUES ($1, $2, $3, $4)
                           ON CONFLICT (user_id, guild_id, data_type) 
                           DO UPDATE SET data_content = $4""",
                        guild_id, guild_id, 'ticket_config', json.dumps(config)
                    )
                else:
                    await self.bot.db.connection.execute(
                        """INSERT OR REPLACE INTO user_data (user_id, guild_id, data_type, data_content) 
                           VALUES (?, ?, ?, ?)""",
                        (guild_id, guild_id, 'ticket_config', json.dumps(config))
                    )
                    await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Ticket System Setup",
                f"Ticket system has been configured successfully!\n\n"
                f"**Ticket Category:** {category.mention}\n"
                f"**Transcript Channel:** {transcript_channel.mention}\n\n"
                f"Users can now create tickets using `/ticket create`"
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to setup ticket system: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="setup-logs", description="Setup logging channel (Admin only)")
    @app_commands.describe(log_channel="Channel where logs will be sent")
    async def setup_logs(self, interaction: discord.Interaction, log_channel: discord.TextChannel):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can setup logging")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            config = {
                'log_channel_id': str(log_channel.id),
                'setup_by': str(interaction.user.id),
                'setup_at': str(discord.utils.utcnow())
            }
            
            await self.bot.logging_manager.save_log_config(str(interaction.guild.id), config)
            
            embed = EmbedBuilder.success(
                "Logging Setup Complete",
                f"Server logs will now be sent to {log_channel.mention}\n\n"
                f"**Logged Events:**\n"
                f"• Message deletions and edits\n"
                f"• Channel creation, deletion, and updates\n"
                f"• Role creation, deletion, and assignments\n"
                f"• Command usage\n"
                f"• Member role updates"
            )
            
            await interaction.response.send_message(embed=embed)
            
            # Send test log
            test_embed = discord.Embed(
                title="🔧 Logging System Activated",
                description="Server logging has been successfully configured!",
                color=0x57F287
            )
            test_embed.add_field(name="Setup by", value=interaction.user.mention, inline=True)
            test_embed.add_field(name="Channel", value=log_channel.mention, inline=True)
            test_embed.set_footer(text="devBot - Powered by EGOS")
            
            await log_channel.send(embed=test_embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to setup logging: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="setup-meetings", description="Setup meeting system (Admin only)")
    @app_commands.describe(
        announcement_channel="Channel where ALL meetings will be automatically announced",
        voice_channel="Default voice channel for meetings"
    )
    async def setup_meetings(self, interaction: discord.Interaction, announcement_channel: discord.TextChannel, voice_channel: discord.VoiceChannel):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can setup meetings")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            config = {
                'announcement_channel_id': str(announcement_channel.id),
                'default_voice_channel_id': str(voice_channel.id),
                'setup_by': str(interaction.user.id),
                'setup_at': str(discord.utils.utcnow())
            }
            
            guild_id = str(interaction.guild.id)
            
            # Delete existing config first, then insert new one
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "DELETE FROM user_data WHERE user_id = $1 AND data_type = $2",
                    guild_id, 'meeting_config'
                )
                await self.bot.db.connection.execute(
                    "INSERT INTO user_data (user_id, guild_id, data_type, data_content) VALUES ($1, $2, $3, $4)",
                    guild_id, guild_id, 'meeting_config', json.dumps(config)
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM user_data WHERE user_id = ? AND data_type = ?",
                    (guild_id, 'meeting_config')
                )
                await self.bot.db.connection.execute(
                    "INSERT INTO user_data (user_id, guild_id, data_type, data_content) VALUES (?, ?, ?, ?)",
                    (guild_id, guild_id, 'meeting_config', json.dumps(config))
                )
                await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Meeting System Setup",
                f"Meeting system has been configured!\n\n"
                f"**Announcement Channel:** {announcement_channel.mention}\n"
                f"**Default Voice Channel:** {voice_channel.mention}\n\n"
                f"✅ **All meetings will now be automatically announced in {announcement_channel.mention}**\n\n"
                f"Users can create meetings using `/create-meeting`\n"
                f"Admins can create server-wide meetings using `/admin-meeting`"
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to setup meetings: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="setup-reminders", description="Setup reminder system (Admin only)")
    @app_commands.describe(
        reminder_channel="Channel where reminders will be sent when DMs fail"
    )
    async def setup_reminders(self, interaction: discord.Interaction, reminder_channel: discord.TextChannel):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can setup reminders")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            config = {
                'reminder_channel_id': str(reminder_channel.id),
                'setup_by': str(interaction.user.id),
                'setup_at': str(discord.utils.utcnow())
            }
            
            guild_id = str(interaction.guild.id)
            
            # Delete existing config first, then insert new one
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "DELETE FROM user_data WHERE user_id = $1 AND data_type = $2",
                    guild_id, 'reminder_config'
                )
                await self.bot.db.connection.execute(
                    "INSERT INTO user_data (user_id, guild_id, data_type, data_content) VALUES ($1, $2, $3, $4)",
                    guild_id, guild_id, 'reminder_config', json.dumps(config)
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM user_data WHERE user_id = ? AND data_type = ?",
                    (guild_id, 'reminder_config')
                )
                await self.bot.db.connection.execute(
                    "INSERT INTO user_data (user_id, guild_id, data_type, data_content) VALUES (?, ?, ?, ?)",
                    (guild_id, guild_id, 'reminder_config', json.dumps(config))
                )
                await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Reminder System Setup",
                f"Reminder system has been configured!\n\n"
                f"**Fallback Channel:** {reminder_channel.mention}\n\n"
                f"When DMs fail, reminders will be sent to this channel.\n"
                f"Users can now create reminders using `/remind`"
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to setup reminders: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="setup-threads", description="Setup thread logging (Admin only)")
    @app_commands.describe(
        thread_log_channel="Channel where thread transcripts will be sent"
    )
    async def setup_threads(self, interaction: discord.Interaction, thread_log_channel: discord.TextChannel):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can setup thread logging")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            config = {
                'thread_log_channel_id': str(thread_log_channel.id),
                'setup_by': str(interaction.user.id),
                'setup_at': str(discord.utils.utcnow())
            }
            
            guild_id = str(interaction.guild.id)
            
            # Delete existing config first, then insert new one
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "DELETE FROM user_data WHERE user_id = $1 AND data_type = $2",
                    guild_id, 'thread_config'
                )
                await self.bot.db.connection.execute(
                    "INSERT INTO user_data (user_id, guild_id, data_type, data_content) VALUES ($1, $2, $3, $4)",
                    guild_id, guild_id, 'thread_config', json.dumps(config)
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM user_data WHERE user_id = ? AND data_type = ?",
                    (guild_id, 'thread_config')
                )
                await self.bot.db.connection.execute(
                    "INSERT INTO user_data (user_id, guild_id, data_type, data_content) VALUES (?, ?, ?, ?)",
                    (guild_id, guild_id, 'thread_config', json.dumps(config))
                )
                await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Thread Logging Setup",
                f"Thread logging has been configured!\n\n"
                f"**Thread Log Channel:** {thread_log_channel.mention}\n\n"
                f"When threads are archived, transcripts will be sent to this channel.\n"
                f"Use `/archive-thread` to archive threads with transcripts."
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to setup thread logging: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Setup(bot))
    print(f"⚙️ Successfully loaded Setup cog")
