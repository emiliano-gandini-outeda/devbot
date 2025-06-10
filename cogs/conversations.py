import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import json
import asyncio
from datetime import datetime

class Conversations(commands.Cog):
    """Thread and conversation management"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="create-thread", description="Create a thread from a message")
    @app_commands.describe(
        message_id="ID of the message to create a thread from",
        name="Name for the new thread"
    )
    async def create_thread(self, interaction: discord.Interaction, message_id: str, name: str):
        try:
            # Convert message ID to int
            message_id = int(message_id)
            
            # Get the message
            try:
                message = await interaction.channel.fetch_message(message_id)
            except discord.NotFound:
                embed = EmbedBuilder.error("Message Not Found", "The specified message could not be found in this channel")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Create thread
            thread = await message.create_thread(name=name, auto_archive_duration=1440)  # 24 hours
            
            embed = EmbedBuilder.success(
                "Thread Created",
                f"Thread **{name}** has been created from the message"
            )
            await interaction.response.send_message(embed=embed)
            
            # Send welcome message in thread
            welcome_embed = discord.Embed(
                title=f"🧵 Thread: {name}",
                description=f"Thread created by {interaction.user.mention}",
                color=0x5865F2
            )
            await thread.send(embed=welcome_embed)
            
        except discord.Forbidden:
            embed = EmbedBuilder.error("Permission Denied", "I don't have permission to create threads in this channel")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except ValueError:
            embed = EmbedBuilder.error("Invalid ID", "Please provide a valid message ID")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create thread: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="rename-thread", description="Rename the current thread")
    @app_commands.describe(new_name="New name for the thread")
    async def rename_thread(self, interaction: discord.Interaction, new_name: str):
        if not isinstance(interaction.channel, discord.Thread):
            embed = EmbedBuilder.error("Not a Thread", "This command can only be used in threads")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            old_name = interaction.channel.name
            await interaction.channel.edit(name=new_name)
            
            embed = EmbedBuilder.success(
                "Thread Renamed",
                f"Thread renamed from **{old_name}** to **{new_name}**"
            )
            await interaction.response.send_message(embed=embed)
            
        except discord.Forbidden:
            embed = EmbedBuilder.error("Permission Denied", "I don't have permission to rename this thread")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to rename thread: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="archive-thread", description="Archive the current thread with transcript")
    async def archive_thread(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            embed = EmbedBuilder.error("Not a Thread", "This command can only be used in threads")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        if not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can archive threads")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # Get thread config
            if self.bot.db.is_postgresql:
                config_row = await self.bot.db.connection.fetchrow(
                    "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                    str(interaction.guild.id), 'thread_config'
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT data_content FROM user_data WHERE user_id = ? AND data_type = ?",
                    (str(interaction.guild.id), 'thread_config')
                )
                row = await cursor.fetchone()
                config_row = {'data_content': row[0]} if row else None
            
            if not config_row:
                embed = EmbedBuilder.error(
                    "Thread System Not Configured",
                    "Thread archiving has not been set up. Please ask an administrator to run `/setup-threads`"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            config = json.loads(config_row['data_content'])
            log_channel_id = config.get('thread_log_channel_id')
            
            if not log_channel_id:
                embed = EmbedBuilder.error("Configuration Error", "Thread log channel not configured")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            log_channel = interaction.guild.get_channel(int(log_channel_id))
            if not log_channel:
                embed = EmbedBuilder.error("Channel Not Found", "Thread log channel not found")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Generate transcript
            messages = []
            async for message in interaction.channel.history(limit=500, oldest_first=True):
                messages.append({
                    "author": str(message.author),
                    "content": message.content,
                    "timestamp": message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "attachments": [a.url for a in message.attachments]
                })
            
            # Create transcript embed
            transcript_embed = discord.Embed(
                title=f"📝 Thread Transcript: {interaction.channel.name}",
                description=f"Thread archived by {interaction.user.mention}",
                color=0x5865F2,
                timestamp=datetime.utcnow()
            )
            
            transcript_embed.add_field(name="Thread ID", value=str(interaction.channel.id), inline=True)
            transcript_embed.add_field(name="Message Count", value=str(len(messages)), inline=True)
            transcript_embed.add_field(name="Created At", value=interaction.channel.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"), inline=True)
            
            # Create transcript file
            transcript_text = f"# Thread Transcript: {interaction.channel.name}\n\n"
            transcript_text += f"Thread ID: {interaction.channel.id}\n"
            transcript_text += f"Created At: {interaction.channel.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            transcript_text += f"Archived By: {interaction.user} ({interaction.user.id})\n\n"
            
            for i, msg in enumerate(messages, 1):
                transcript_text += f"## Message {i}\n"
                transcript_text += f"Author: {msg['author']}\n"
                transcript_text += f"Time: {msg['timestamp']}\n"
                transcript_text += f"Content: {msg['content']}\n"
                
                if msg['attachments']:
                    transcript_text += f"Attachments: {', '.join(msg['attachments'])}\n"
                
                transcript_text += "\n"
            
            transcript_file = discord.File(
                fp=discord.utils.StringIO(transcript_text),
                filename=f"transcript_{interaction.channel.name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
            )
            
            # Send transcript to log channel
            await log_channel.send(embed=transcript_embed, file=transcript_file)
            
            # Archive the thread
            await interaction.channel.edit(archived=True, locked=True)
            
            embed = EmbedBuilder.success(
                "Thread Archived",
                f"Thread has been archived and transcript sent to {log_channel.mention}"
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to archive thread: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="search-messages", description="Search for messages in the current channel")
    @app_commands.describe(
        query="Text to search for",
        limit="Maximum number of messages to search (default: 100, max: 500)"
    )
    async def search_messages(self, interaction: discord.Interaction, query: str, limit: int = 100):
        await interaction.response.defer()
        
        try:
            # Validate limit
            if limit > 500:
                limit = 500
            elif limit < 1:
                limit = 100
            
            # Search messages
            messages = []
            async for message in interaction.channel.history(limit=limit):
                if query.lower() in message.content.lower():
                    messages.append(message)
            
            if not messages:
                embed = EmbedBuilder.info("No Results", f"No messages found containing '{query}'")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Create results embed
            embed = discord.Embed(
                title=f"🔍 Search Results: '{query}'",
                description=f"Found {len(messages)} messages in {interaction.channel.mention}",
                color=0x5865F2
            )
            
            # Add up to 10 results
            for i, message in enumerate(messages[:10], 1):
                content = message.content[:100] + "..." if len(message.content) > 100 else message.content
                embed.add_field(
                    name=f"Result {i} - {message.author}",
                    value=f"{content}\n[Jump to Message]({message.jump_url})",
                    inline=False
                )
            
            if len(messages) > 10:
                embed.set_footer(text=f"Showing 10 of {len(messages)} results")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to search messages: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="pin-message", description="Pin a message by ID")
    @app_commands.describe(message_id="ID of the message to pin")
    async def pin_message(self, interaction: discord.Interaction, message_id: str):
        if not interaction.channel.permissions_for(interaction.user).manage_messages:
            embed = EmbedBuilder.error("Permission Denied", "You need Manage Messages permission to pin messages")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # Convert message ID to int
            message_id = int(message_id)
            
            # Get the message
            try:
                message = await interaction.channel.fetch_message(message_id)
            except discord.NotFound:
                embed = EmbedBuilder.error("Message Not Found", "The specified message could not be found in this channel")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Pin the message
            await message.pin(reason=f"Pinned by {interaction.user}")
            
            embed = EmbedBuilder.success(
                "Message Pinned",
                f"Message has been pinned\n[Jump to Message]({message.jump_url})"
            )
            await interaction.response.send_message(embed=embed)
            
        except discord.Forbidden:
            embed = EmbedBuilder.error("Permission Denied", "I don't have permission to pin messages in this channel")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except ValueError:
            embed = EmbedBuilder.error("Invalid ID", "Please provide a valid message ID")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to pin message: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="unpin-message", description="Unpin a message by ID")
    @app_commands.describe(message_id="ID of the message to unpin")
    async def unpin_message(self, interaction: discord.Interaction, message_id: str):
        if not interaction.channel.permissions_for(interaction.user).manage_messages:
            embed = EmbedBuilder.error("Permission Denied", "You need Manage Messages permission to unpin messages")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # Convert message ID to int
            message_id = int(message_id)
            
            # Get the message
            try:
                message = await interaction.channel.fetch_message(message_id)
            except discord.NotFound:
                embed = EmbedBuilder.error("Message Not Found", "The specified message could not be found in this channel")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Unpin the message
            await message.unpin(reason=f"Unpinned by {interaction.user}")
            
            embed = EmbedBuilder.success(
                "Message Unpinned",
                f"Message has been unpinned\n[Jump to Message]({message.jump_url})"
            )
            await interaction.response.send_message(embed=embed)
            
        except discord.Forbidden:
            embed = EmbedBuilder.error("Permission Denied", "I don't have permission to unpin messages in this channel")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except ValueError:
            embed = EmbedBuilder.error("Invalid ID", "Please provide a valid message ID")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to unpin message: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Conversations(bot))
