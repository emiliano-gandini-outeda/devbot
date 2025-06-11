import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import asyncio
import logging
from typing import Set, Dict, List, Tuple

logger = logging.getLogger(__name__)

class Notifications(commands.Cog):
    """Keyword notification system with improved concurrency handling"""
    
    def __init__(self, bot):
        self.bot = bot
        # Use separate locks for different operations to reduce contention
        self._db_lock = asyncio.Lock()
        self._processing_lock = asyncio.Lock()
        self._processing_messages: Set[str] = set()
        
        # Cache for frequently accessed data
        self._keyword_cache: Dict[str, List[Dict]] = {}
        self._cache_expiry: Dict[str, float] = {}
        self._cache_duration = 60  # Cache for 1 minute
        
        # Rate limiting
        self._last_process_time: Dict[str, float] = {}
        self._min_process_interval = 0.1  # Minimum 100ms between processes per guild
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for keyword mentions with improved concurrency"""
        if message.author.bot or not message.guild:
            return
        
        # Create unique message identifier
        message_key = f"{message.guild.id}:{message.id}"
        
        # Check if already processing this message
        async with self._processing_lock:
            if message_key in self._processing_messages:
                return
            self._processing_messages.add(message_key)
        
        try:
            # Rate limiting per guild
            guild_key = str(message.guild.id)
            current_time = asyncio.get_event_loop().time()
            
            if guild_key in self._last_process_time:
                time_since_last = current_time - self._last_process_time[guild_key]
                if time_since_last < self._min_process_interval:
                    await asyncio.sleep(self._min_process_interval - time_since_last)
            
            self._last_process_time[guild_key] = current_time
            
            # Process notifications with timeout
            try:
                async with asyncio.timeout(10):  # 10 second timeout
                    await self._process_keyword_notifications(message)
            except asyncio.TimeoutError:
                logger.warning(f"Keyword processing timed out for message {message_key}")
            
        except Exception as e:
            logger.error(f"Error in keyword listener for {message_key}: {e}")
        finally:
            # Always remove from processing set
            async with self._processing_lock:
                self._processing_messages.discard(message_key)
    
    async def _get_keywords_cached(self, guild_id: str) -> List[Dict]:
        """Get keywords with caching to reduce database load"""
        current_time = asyncio.get_event_loop().time()
        
        # Check cache first
        if (guild_id in self._keyword_cache and 
            guild_id in self._cache_expiry and 
            current_time < self._cache_expiry[guild_id]):
            return self._keyword_cache[guild_id]
        
        # Fetch from database with retry logic
        keywords = await self._fetch_keywords_with_retry(guild_id)
        
        # Update cache
        self._keyword_cache[guild_id] = keywords
        self._cache_expiry[guild_id] = current_time + self._cache_duration
        
        return keywords
    
    async def _fetch_keywords_with_retry(self, guild_id: str, max_retries: int = 3) -> List[Dict]:
        """Fetch keywords with retry logic for database conflicts"""
        for attempt in range(max_retries):
            try:
                # Use a shorter timeout for individual queries
                async with asyncio.timeout(5):
                    keywords = await self.bot.db.connection.fetch(
                        "SELECT user_id, keyword FROM keywords WHERE guild_id = $1",
                        guild_id
                    )
                    return [dict(row) for row in keywords] if keywords else []
                    
            except asyncio.TimeoutError:
                logger.warning(f"Database query timeout on attempt {attempt + 1} for guild {guild_id}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    logger.error(f"All database query attempts failed for guild {guild_id}")
                    return []
                    
            except Exception as e:
                logger.warning(f"Database error on attempt {attempt + 1} for guild {guild_id}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                else:
                    logger.error(f"All database attempts failed for guild {guild_id}: {e}")
                    return []
    
    async def _process_keyword_notifications(self, message):
        """Process keyword notifications with optimized database access"""
        try:
            guild_id = str(message.guild.id)
            
            # Get keywords with caching
            keywords = await self._get_keywords_cached(guild_id)
            
            if not keywords:
                return
            
            message_content = message.content.lower()
            notifications_to_send: List[Tuple[discord.Member, str]] = []
            
            # Process keywords efficiently
            for keyword_row in keywords:
                keyword = keyword_row['keyword'].lower()
                user_id = keyword_row['user_id']
                
                # Skip if keyword not in message
                if keyword not in message_content:
                    continue
                
                # Skip if user mentioned their own keyword
                if str(message.author.id) == user_id:
                    continue
                
                # Get user object
                user = message.guild.get_member(int(user_id))
                if user:
                    notifications_to_send.append((user, keyword))
            
            # Send notifications with proper error handling
            if notifications_to_send:
                await self._send_notifications_batch(notifications_to_send, message)
                
        except Exception as e:
            logger.error(f"Error processing keyword notifications: {e}")
    
    async def _send_notifications_batch(self, notifications: List[Tuple[discord.Member, str]], message):
        """Send notifications in batches with rate limiting"""
        for i, (user, keyword) in enumerate(notifications):
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
                
                # Rate limiting between notifications
                if i < len(notifications) - 1:  # Don't sleep after last notification
                    await asyncio.sleep(0.2)  # 200ms between notifications
                    
            except discord.Forbidden:
                # User has DMs disabled
                logger.debug(f"Cannot send DM to {user.display_name} (DMs disabled)")
            except discord.HTTPException as e:
                logger.warning(f"HTTP error sending notification to {user.display_name}: {e}")
            except Exception as e:
                logger.error(f"Error sending notification to {user.display_name}: {e}")
    
    def _invalidate_cache(self, guild_id: str):
        """Invalidate cache for a guild when keywords are modified"""
        if guild_id in self._keyword_cache:
            del self._keyword_cache[guild_id]
        if guild_id in self._cache_expiry:
            del self._cache_expiry[guild_id]
    
    @app_commands.command(name="add-keyword", description="Add a keyword to get notified when it's mentioned")
    @app_commands.describe(keyword="Keyword to watch for")
    async def add_keyword(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer(ephemeral=True)
        
        keyword = keyword.lower().strip()
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        if len(keyword) < 2:
            embed = EmbedBuilder.error("Invalid Keyword", "Keywords must be at least 2 characters long")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        if len(keyword) > 50:
            embed = EmbedBuilder.error("Invalid Keyword", "Keywords must be 50 characters or less")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        try:
            # Use database lock for write operations
            async with self._db_lock:
                # Check if keyword already exists
                existing = await self.bot.db.connection.fetchrow(
                    "SELECT id FROM keywords WHERE guild_id = $1 AND user_id = $2 AND keyword = $3",
                    guild_id, user_id, keyword
                )
                
                if existing:
                    embed = EmbedBuilder.warning("Already Exists", f"You're already watching for the keyword **{keyword}**")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                # Check user's keyword limit
                user_keywords = await self.bot.db.connection.fetchval(
                    "SELECT COUNT(*) FROM keywords WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id
                )
                
                if user_keywords >= 20:
                    embed = EmbedBuilder.error(
                        "Keyword Limit Reached", 
                        "You can only watch up to 20 keywords per server. Remove some keywords first."
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                # Add keyword
                await self.bot.db.connection.execute(
                    "INSERT INTO keywords (guild_id, user_id, keyword) VALUES ($1, $2, $3)",
                    guild_id, user_id, keyword
                )
                
                # Invalidate cache
                self._invalidate_cache(guild_id)
            
            embed = EmbedBuilder.success(
                "Keyword Added",
                f"You'll now be notified when **{keyword}** is mentioned in this server\n\n"
                f"**Keywords watched:** {user_keywords + 1}/20"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error adding keyword: {e}")
            embed = EmbedBuilder.error("Error", "Failed to add keyword. Please try again.")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="remove-keyword", description="Remove a keyword from your watch list")
    @app_commands.describe(keyword="Keyword to stop watching")
    async def remove_keyword(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer(ephemeral=True)
        
        keyword = keyword.lower().strip()
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        try:
            async with self._db_lock:
                result = await self.bot.db.connection.execute(
                    "DELETE FROM keywords WHERE guild_id = $1 AND user_id = $2 AND keyword = $3",
                    guild_id, user_id, keyword
                )
                
                # Invalidate cache
                self._invalidate_cache(guild_id)
            
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
            logger.error(f"Error removing keyword: {e}")
            embed = EmbedBuilder.error("Error", "Failed to remove keyword. Please try again.")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-keywords", description="List your watched keywords")
    async def list_keywords(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        try:
            keywords = await self.bot.db.connection.fetch(
                "SELECT keyword, created_at FROM keywords WHERE guild_id = $1 AND user_id = $2 ORDER BY keyword",
                guild_id, user_id
            )
            
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
            logger.error(f"Error listing keywords: {e}")
            embed = EmbedBuilder.error("Error", "Failed to fetch keywords. Please try again.")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="clear-keywords", description="Remove all your keywords from this server")
    async def clear_keywords(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        try:
            async with self._db_lock:
                # Get count first
                count = await self.bot.db.connection.fetchval(
                    "SELECT COUNT(*) FROM keywords WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id
                )
                
                if count == 0:
                    embed = EmbedBuilder.info("No Keywords", "You don't have any keywords to clear")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                # Delete all keywords
                await self.bot.db.connection.execute(
                    "DELETE FROM keywords WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id
                )
                
                # Invalidate cache
                self._invalidate_cache(guild_id)
            
            embed = EmbedBuilder.success(
                "Keywords Cleared",
                f"Removed {count} keyword{'s' if count != 1 else ''} from your watch list"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error clearing keywords: {e}")
            embed = EmbedBuilder.error("Error", "Failed to clear keywords. Please try again.")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Notifications(bot))
