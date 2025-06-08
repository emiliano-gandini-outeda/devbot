import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
from utils.helpers import EmbedBuilder, safe_send

class Conversations(commands.Cog):
    """Conversation management commands similar to Slack threads"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="create-thread", description="Create a new thread from a message")
    @app_commands.describe(
        message_id="ID of the message to create thread from",
        name="Name for the thread"
    )
    async def create_thread(self, interaction: discord.Interaction, message_id: str, name: str):
        try:
            message = await interaction.channel.fetch_message(int(message_id))
            thread = await message.create_thread(name=name)
            
            embed = EmbedBuilder.success(
                "Thread Created",
                f"Created thread **{name}** from [message]({message.jump_url})\n"
                f"Thread: {thread.mention}"
            )
            await interaction.response.send_message(embed=embed)
            
        except discord.NotFound:
            embed = EmbedBuilder.error("Message Not Found", "Could not find the specified message")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create thread: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="archive-thread", description="Archive the current thread")
    async def archive_thread(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            embed = EmbedBuilder.error("Not a Thread", "This command can only be used in threads")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            await interaction.channel.edit(archived=True)
            embed = EmbedBuilder.success("Thread Archived", f"Thread **{interaction.channel.name}** has been archived")
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to archive thread: {str(e)}")
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
                f"Renamed thread from **{old_name}** to **{new_name}**"
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to rename thread: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="search-messages", description="Search for messages in the current channel")
    @app_commands.describe(
        query="Text to search for",
        limit="Number of messages to return (max 20)"
    )
    async def search_messages(self, interaction: discord.Interaction, query: str, limit: int = 10):
        if limit > 20:
            limit = 20
        
        await interaction.response.defer()
        
        messages = []
        async for message in interaction.channel.history(limit=1000):
            if query.lower() in message.content.lower():
                messages.append(message)
                if len(messages) >= limit:
                    break
        
        if not messages:
            embed = EmbedBuilder.info("No Results", f"No messages found containing '{query}'")
            await interaction.followup.send(embed=embed)
            return
        
        embed = discord.Embed(
            title=f"🔍 Search Results for '{query}'",
            description=f"Found {len(messages)} messages",
            color=0x5865F2
        )
        
        for i, msg in enumerate(messages[:5]):  # Show first 5 results
            content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
            embed.add_field(
                name=f"{i+1}. {msg.author.display_name}",
                value=f"[{content}]({msg.jump_url})\n{msg.created_at.strftime('%Y-%m-%d %H:%M')}",
                inline=False
            )
        
        if len(messages) > 5:
            embed.add_field(
                name="More Results",
                value=f"... and {len(messages) - 5} more messages",
                inline=False
            )
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Conversations(bot))
