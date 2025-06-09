import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
from datetime import datetime
import asyncio

class Conversations(commands.Cog):
    """Thread and conversation management"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="create-thread", description="Create a thread from a message")
    @app_commands.describe(
        message_id="ID of the message to create thread from",
        name="Name for the thread"
    )
    async def create_thread(self, interaction: discord.Interaction, message_id: str, name: str):
        try:
            # Get the message
            try:
                message = await interaction.channel.fetch_message(int(message_id))
            except (discord.NotFound, ValueError):
                embed = EmbedBuilder.error("Message Not Found", "Could not find a message with that ID in this channel")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Create thread
            thread = await message.create_thread(name=name, auto_archive_duration=1440)  # 24 hours
            
            embed = EmbedBuilder.success(
                "Thread Created",
                f"Created thread {thread.mention} from [this message]({message.jump_url})"
            )
            await interaction.response.send_message(embed=embed)
            
            # Send welcome message in thread
            welcome_embed = discord.Embed(
                title="🧵 Thread Created",
                description=f"This thread was created by {interaction.user.mention}",
                color=0x5865F2
            )
            welcome_embed.add_field(name="Original Message", value=f"[Jump to message]({message.jump_url})", inline=False)
            await thread.send(embed=welcome_embed)
            
        except discord.Forbidden:
            embed = EmbedBuilder.error("Permission Error", "I don't have permission to create threads in this channel")
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
            embed = EmbedBuilder.error("Permission Error", "I don't have permission to rename this thread")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to rename thread: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="archive-thread", description="Archive the current thread (Admin only)")
    async def archive_thread(self, interaction: discord.Interaction):
        if not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can archive threads")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        if not isinstance(interaction.channel, discord.Thread):
            embed = EmbedBuilder.error("Not a Thread", "This command can only be used in threads")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            thread_name = interaction.channel.name
            
            # Create transcript before archiving
            transcript = await self.create_thread_transcript(interaction.channel)
            
            # Send transcript to configured channel
            await self.send_thread_transcript(interaction.guild, transcript, thread_name)
            
            # Archive the thread
            await interaction.channel.edit(archived=True)
            
            embed = EmbedBuilder.success(
                "Thread Archived",
                f"Thread **{thread_name}** has been archived and transcript saved"
            )
            await interaction.response.send_message(embed=embed)
            
        except discord.Forbidden:
            embed = EmbedBuilder.error("Permission Error", "I don't have permission to archive this thread")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to archive thread: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="search-messages", description="Search for messages in this channel")
    @app_commands.describe(
        query="Text to search for",
        limit="Number of messages to search (default: 100)"
    )
    async def search_messages(self, interaction: discord.Interaction, query: str, limit: int = 100):
        await interaction.response.defer()
        
        if limit > 500:
            limit = 500
        elif limit < 1:
            limit = 100
        
        try:
            found_messages = []
            query_lower = query.lower()
            
            async for message in interaction.channel.history(limit=limit):
                if query_lower in message.content.lower():
                    found_messages.append(message)
                    if len(found_messages) >= 10:  # Limit results to 10
                        break
            
            if not found_messages:
                embed = EmbedBuilder.info("No Results", f"No messages found containing '{query}' in the last {limit} messages")
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title=f"🔍 Search Results for '{query}'",
                description=f"Found {len(found_messages)} messages",
                color=0x5865F2
            )
            
            for i, message in enumerate(found_messages[:5], 1):  # Show first 5 results
                content = message.content[:100] + "..." if len(message.content) > 100 else message.content
                embed.add_field(
                    name=f"{i}. {message.author.display_name}",
                    value=f"{content}\n[Jump to message]({message.jump_url})",
                    inline=False
                )
            
            if len(found_messages) > 5:
                embed.set_footer(text=f"Showing 5 of {len(found_messages)} results")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to search messages: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="pin-message", description="Pin a message by ID")
    @app_commands.describe(message_id="ID of the message to pin")
    async def pin_message(self, interaction: discord.Interaction, message_id: str):
        if not interaction.user.guild_permissions.manage_messages:
            embed = EmbedBuilder.error("Permission Denied", "You need Manage Messages permission to pin messages")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            message = await interaction.channel.fetch_message(int(message_id))
            await message.pin()
            
            embed = EmbedBuilder.success(
                "Message Pinned",
                f"[Message]({message.jump_url}) by {message.author.mention} has been pinned"
            )
            await interaction.response.send_message(embed=embed)
            
        except discord.NotFound:
            embed = EmbedBuilder.error("Message Not Found", "Could not find a message with that ID in this channel")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.Forbidden:
            embed = EmbedBuilder.error("Permission Error", "I don't have permission to pin messages in this channel")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to pin message: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="unpin-message", description="Unpin a message by ID")
    @app_commands.describe(message_id="ID of the message to unpin")
    async def unpin_message(self, interaction: discord.Interaction, message_id: str):
        if not interaction.user.guild_permissions.manage_messages:
            embed = EmbedBuilder.error("Permission Denied", "You need Manage Messages permission to unpin messages")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            message = await interaction.channel.fetch_message(int(message_id))
            await message.unpin()
            
            embed = EmbedBuilder.success(
                "Message Unpinned",
                f"[Message]({message.jump_url}) by {message.author.mention} has been unpinned"
            )
            await interaction.response.send_message(embed=embed)
            
        except discord.NotFound:
            embed = EmbedBuilder.error("Message Not Found", "Could not find a message with that ID in this channel")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.Forbidden:
            embed = EmbedBuilder.error("Permission Error", "I don't have permission to unpin messages in this channel")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to unpin message: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def create_thread_transcript(self, thread: discord.Thread) -> str:
        """Create a transcript of a thread"""
        transcript_lines = []
        transcript_lines.append(f"Thread Transcript: {thread.name}")
        transcript_lines.append(f"Created: {thread.created_at.strftime('%Y-%m-%d %H:%M UTC')}")
        transcript_lines.append(f"Archived: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        transcript_lines.append("=" * 50)
        
        try:
            async for message in thread.history(limit=None, oldest_first=True):
                timestamp = message.created_at.strftime('%Y-%m-%d %H:%M UTC')
                author = f"{message.author.display_name} ({message.author})"
                content = message.content or "[No text content]"
                
                transcript_lines.append(f"[{timestamp}] {author}: {content}")
                
                # Add attachment info
                if message.attachments:
                    for attachment in message.attachments:
                        transcript_lines.append(f"    📎 Attachment: {attachment.filename} ({attachment.url})")
                
                # Add embed info
                if message.embeds:
                    for embed in message.embeds:
                        transcript_lines.append(f"    📋 Embed: {embed.title or 'No title'}")
        
        except Exception as e:
            transcript_lines.append(f"Error reading messages: {str(e)}")
        
        return "\n".join(transcript_lines)
    
    async def send_thread_transcript(self, guild: discord.Guild, transcript: str, thread_name: str):
        """Send thread transcript to configured channel"""
        try:
            # Get thread config
            if self.bot.db.is_postgresql:
                config_row = await self.bot.db.connection.fetchrow(
                    "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                    str(guild.id), 'thread_config'
                )
                if config_row:
                    import json
                    config = json.loads(config_row['data_content'])
                    log_channel_id = config.get('thread_log_channel_id')
                    
                    if log_channel_id:
                        channel = guild.get_channel(int(log_channel_id))
                        if channel:
                            # Create file
                            file = discord.File(
                                fp=discord.utils.StringIO(transcript),
                                filename=f"thread_transcript_{thread_name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
                            )
                            
                            embed = discord.Embed(
                                title="🧵 Thread Archived",
                                description=f"Thread **{thread_name}** has been archived",
                                color=0x5865F2,
                                timestamp=datetime.utcnow()
                            )
                            
                            await channel.send(embed=embed, file=file)
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT data_content FROM user_data WHERE user_id = ? AND data_type = ?",
                    (str(guild.id), 'thread_config')
                )
                row = await cursor.fetchone()
                if row:
                    import json
                    config = json.loads(row[0])
                    log_channel_id = config.get('thread_log_channel_id')
                    
                    if log_channel_id:
                        channel = guild.get_channel(int(log_channel_id))
                        if channel:
                            # Create file
                            file = discord.File(
                                fp=discord.utils.StringIO(transcript),
                                filename=f"thread_transcript_{thread_name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
                            )
                            
                            embed = discord.Embed(
                                title="🧵 Thread Archived",
                                description=f"Thread **{thread_name}** has been archived",
                                color=0x5865F2,
                                timestamp=datetime.utcnow()
                            )
                            
                            await channel.send(embed=embed, file=file)
        
        except Exception as e:
            print(f"Error sending thread transcript: {e}")

async def setup(bot):
    cog = Conversations(bot)
    await bot.add_cog(cog)
    
    # Ensure commands are added to the tree
    for command in cog.get_app_commands():
        if command not in bot.tree.get_commands():
            bot.tree.add_command(command)
    
    print(f"🗨️ Successfully loaded Conversations cog with {len(cog.get_app_commands())} commands")
