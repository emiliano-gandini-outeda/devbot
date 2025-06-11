import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import asyncio
from collections import deque

class DatabaseQueue:
    """Queue system for database operations to prevent concurrent access"""
    
    def __init__(self):
        self._queue = deque()
        self._processing = False
        self._lock = asyncio.Lock()
    
    async def execute(self, operation):
        """Add operation to queue and wait for result"""
        future = asyncio.Future()
        await self._queue_operation(operation, future)
        return await future
    
    async def _queue_operation(self, operation, future):
        """Add operation to queue"""
        self._queue.append((operation, future))
        await self._process_queue()
    
    async def _process_queue(self):
        """Process queued operations sequentially"""
        async with self._lock:
            if self._processing:
                return
            
            self._processing = True
            
            try:
                while self._queue:
                    operation, future = self._queue.popleft()
                    try:
                        result = await operation()
                        future.set_result(result)
                    except Exception as e:
                        future.set_exception(e)
                    
                    # Small delay between operations
                    await asyncio.sleep(0.01)
            finally:
                self._processing = False

class Notifications(commands.Cog):
    """Keyword notification system"""
    
    def __init__(self, bot):
        self.bot = bot
        self._db_queue = DatabaseQueue()
        self._processing_messages = set()
        self._notification_semaphore = asyncio.Semaphore(5)  # Limit concurrent notifications
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for keyword mentions"""
        if message.author.bot or not message.guild:
            return
        
        # Prevent processing the same message multiple times
        message_key = f"{message.guild.id}:{message.id}"
        if message_key in self._processing_messages:
            return
        
        self._processing_messages.add(message_key)
        
        try:
            # Process notifications asynchronously without blocking
            asyncio.create_task(self._process_keyword_notifications_async(message, message_key))
        except Exception as e:
            print(f"Error starting keyword notification processing: {e}")
            self._processing_messages.discard(message_key)
    
    async def _process_keyword_notifications_async(self, message, message_key):
        """Process keyword notifications asynchronously"""
        try:
            async with self._notification_semaphore:
                await self._process_keyword_notifications(message)
        except Exception as e:
            print(f"Error processing keyword notifications: {e}")
        finally:
            self._processing_messages.discard(message_key)
    
    async def _process_keyword_notifications(self, message):
        """Process keyword notifications for a message"""
        try:
            # Get keywords using the database queue
            async def get_keywords():
                return await self.bot.db.connection.fetch(
                    "SELECT * FROM keywords WHERE guild_id = $1",
                    str(message.guild.id)
                )
            
            keywords = await self._db_queue.execute(get_keywords)
            
            if not keywords:
                return
            
            message_content = message.content.lower()
            notifications_to_send = []
            
            # Process all keywords and collect notifications to send
            for keyword_row in keywords:
                keyword = keyword_row['keyword'].lower()
                user_id = keyword_row['user_id']
                
                if keyword in message_content:
                    # Don't notify if the user mentioned the keyword themselves
                    if str(message.author.id) == user_id:
                        continue
                    
                    user = message.guild.get_member(int(user_id))
                    if user:
                        notifications_to_send.append((user, keyword))
            
            # Send all notifications with rate limiting
            for i, (user, keyword) in enumerate(notifications_to_send):
                try:
                    embed = discord.Embed(
                        title="🔔 Keyword Mentioned",
                        description=f"Your keyword **{keyword}** was mentioned in {message.channel.mention}",
                        color=0xFEE75C
                    )
                    embed.add_field(name="Message", value=message.content[:1000], inline=False)
                    embed.add_field(name="Author", value=message.author.mention, inline=True)
                    embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                    embed.add_field(name="Jump to Message", value=f"[Click here]({message.jump_url})", inline=True)
                    embed.set_footer(text="devBot Keyword Notification")
                    
                    await user.send(embed=embed)
                    
                    # Progressive delay to prevent rate limiting
                    if i < len(notifications_to_send) - 1:
                        await asyncio.sleep(0.2 + (i * 0.1))
                    
                except discord.Forbidden:
                    # User has DMs disabled, skip
                    pass
                except discord.HTTPException as e:
                    if e.status == 429:  # Rate limited
                        print(f"Rate limited sending notification to {user.display_name}, waiting...")
                        await asyncio.sleep(5)
                    else:
                        print(f"HTTP error sending keyword notification to {user.display_name}: {e}")
                except Exception as e:
                    print(f"Error sending keyword notification to {user.display_name}: {e}")
        
        except Exception as e:
            print(f"Error in keyword notification processing: {e}")
    
    @app_commands.command(name="add-keyword", description="Add a keyword to get notified when it's mentioned")
    @app_commands.describe(keyword="Keyword to watch for")
    async def add_keyword(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer(ephemeral=True)
        
        keyword = keyword.lower().strip()
        
        if len(keyword) < 2:
            embed = EmbedBuilder.error("Invalid Keyword", "Keywords must be at least 2 characters long")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        if len(keyword) > 50:
            embed = EmbedBuilder.error("Invalid Keyword", "Keywords must be 50 characters or less")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        try:
            # Check if keyword already exists and get count using database queue
            async def check_keyword_and_count():
                existing = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM keywords WHERE guild_id = $1 AND user_id = $2 AND keyword = $3",
                    str(interaction.guild.id), str(interaction.user.id), keyword
                )
                
                if existing:
                    return "exists", 0
                
                count = await self.bot.db.connection.fetchval(
                    "SELECT COUNT(*) FROM keywords WHERE guild_id = $1 AND user_id = $2",
                    str(interaction.guild.id), str(interaction.user.id)
                )
                
                return "new", count
            
            status, user_keywords = await self._db_queue.execute(check_keyword_and_count)
            
            if status == "exists":
                embed = EmbedBuilder.warning("Already Exists", f"You're already watching for the keyword **{keyword}**")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            if user_keywords >= 20:
                embed = EmbedBuilder.error(
                    "Keyword Limit Reached", 
                    "You can only watch up to 20 keywords per server. Remove some keywords first."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Add keyword using database queue
            async def add_keyword_to_db():
                await self.bot.db.connection.execute(
                    "INSERT INTO keywords (guild_id, user_id, keyword) VALUES ($1, $2, $3)",
                    str(interaction.guild.id), str(interaction.user.id), keyword
                )
                return True
            
            await self._db_queue.execute(add_keyword_to_db)
            
            embed = EmbedBuilder.success(
                "Keyword Added",
                f"You'll now be notified when **{keyword}** is mentioned in this server\n\n"
                f"**Keywords watched:** {user_keywords + 1}/20"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to add keyword: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="remove-keyword", description="Remove a keyword from your watch list")
    @app_commands.describe(keyword="Keyword to stop watching")
    async def remove_keyword(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer(ephemeral=True)
        
        keyword = keyword.lower().strip()
        
        try:
            async def remove_keyword_from_db():
                result = await self.bot.db.connection.execute(
                    "DELETE FROM keywords WHERE guild_id = $1 AND user_id = $2 AND keyword = $3",
                    str(interaction.guild.id), str(interaction.user.id), keyword
                )
                return result
            
            result = await self._db_queue.execute(remove_keyword_from_db)
            
            if "DELETE 0" in str(result):
                embed = EmbedBuilder.error("Not Found", f"You're not watching for the keyword **{keyword}**")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            embed = EmbedBuilder.success(
                "Keyword Removed",
                f"You'll no longer be notified when **{keyword}** is mentioned"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to remove keyword: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-keywords", description="List your watched keywords")
    async def list_keywords(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            async def get_user_keywords():
                return await self.bot.db.connection.fetch(
                    "SELECT keyword, created_at FROM keywords WHERE guild_id = $1 AND user_id = $2 ORDER BY keyword",
                    str(interaction.guild.id), str(interaction.user.id)
                )
            
            keywords = await self._db_queue.execute(get_user_keywords)
            
            if not keywords:
                embed = EmbedBuilder.info("No Keywords", "You're not watching any keywords in this server")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            keyword_list = []
            for i, row in enumerate(keywords, 1):
                keyword = row['keyword']
                keyword_list.append(f"{i}. **{keyword}**")
            
            # Split into multiple embeds if too many keywords
            if len(keyword_list) <= 20:
                embed = discord.Embed(
                    title="🔔 Your Keywords",
                    description="\n".join(keyword_list),
                    color=0x5865F2
                )
                embed.set_footer(text=f"Watching {len(keyword_list)}/20 keywords in this server")
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                # Split into chunks of 20
                for i in range(0, len(keyword_list), 20):
                    chunk = keyword_list[i:i+20]
                    embed = discord.Embed(
                        title=f"🔔 Your Keywords (Part {i//20 + 1})",
                        description="\n".join(chunk),
                        color=0x5865F2
                    )
                    embed.set_footer(text=f"Watching {len(keyword_list)}/20 keywords in this server")
                    await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch keywords: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="clear-keywords", description="Remove all your keywords from this server")
    async def clear_keywords(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            async def clear_user_keywords():
                # Get count first
                count = await self.bot.db.connection.fetchval(
                    "SELECT COUNT(*) FROM keywords WHERE guild_id = $1 AND user_id = $2",
                    str(interaction.guild.id), str(interaction.user.id)
                )
                
                if count == 0:
                    return 0
                
                # Delete all keywords
                await self.bot.db.connection.execute(
                    "DELETE FROM keywords WHERE guild_id = $1 AND user_id = $2",
                    str(interaction.guild.id), str(interaction.user.id)
                )
                
                return count
            
            count = await self._db_queue.execute(clear_user_keywords)
            
            if count == 0:
                embed = EmbedBuilder.info("No Keywords", "You don't have any keywords to clear")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            embed = EmbedBuilder.success(
                "Keywords Cleared",
                f"Removed {count} keyword{'s' if count != 1 else ''} from your watch list"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to clear keywords: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Notifications(bot))
