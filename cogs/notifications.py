import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import json

class Notifications(commands.Cog):
    """Keyword notification system"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for keyword mentions"""
        if message.author.bot:
            return
        
        try:
            # Get keywords for this guild
            if self.bot.db.is_postgresql:
                keywords = await self.bot.db.connection.fetch(
                    "SELECT * FROM keywords WHERE guild_id = $1",
                    str(message.guild.id)
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM keywords WHERE guild_id = ?",
                    (str(message.guild.id),)
                )
                keywords = await cursor.fetchall()
            
            if not keywords:
                return
            
            message_content = message.content.lower()
            
            for keyword_row in keywords:
                if self.bot.db.is_postgresql:
                    keyword = keyword_row['keyword'].lower()
                    user_id = keyword_row['user_id']
                else:
                    keyword = keyword_row[3].lower()  # keyword column
                    user_id = keyword_row[2]  # user_id column
                
                if keyword in message_content:
                    # Don't notify if the user mentioned the keyword themselves
                    if str(message.author.id) == user_id:
                        continue
                    
                    user = message.guild.get_member(int(user_id))
                    if user:
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
                        except discord.Forbidden:
                            # User has DMs disabled, skip
                            pass
                        except Exception as e:
                            print(f"Error sending keyword notification: {e}")
        
        except Exception as e:
            print(f"Error in keyword listener: {e}")
    
    @app_commands.command(name="add-keyword", description="Add a keyword to get notified when it's mentioned")
    @app_commands.describe(keyword="Keyword to watch for")
    async def add_keyword(self, interaction: discord.Interaction, keyword: str):
        keyword = keyword.lower().strip()
        
        if len(keyword) < 2:
            embed = EmbedBuilder.error("Invalid Keyword", "Keywords must be at least 2 characters long")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # Check if keyword already exists for this user
            if self.bot.db.is_postgresql:
                existing = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM keywords WHERE guild_id = $1 AND user_id = $2 AND keyword = $3",
                    str(interaction.guild.id), str(interaction.user.id), keyword
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM keywords WHERE guild_id = ? AND user_id = ? AND keyword = ?",
                    (str(interaction.guild.id), str(interaction.user.id), keyword)
                )
                existing = await cursor.fetchone()
            
            if existing:
                embed = EmbedBuilder.warning("Already Exists", f"You're already watching for the keyword **{keyword}**")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Add keyword
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "INSERT INTO keywords (guild_id, user_id, keyword) VALUES ($1, $2, $3)",
                    str(interaction.guild.id), str(interaction.user.id), keyword
                )
            else:
                await self.bot.db.connection.execute(
                    "INSERT INTO keywords (guild_id, user_id, keyword) VALUES (?, ?, ?)",
                    (str(interaction.guild.id), str(interaction.user.id), keyword)
                )
                await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Keyword Added",
                f"You'll now be notified when **{keyword}** is mentioned in this server"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to add keyword: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="remove-keyword", description="Remove a keyword from your watch list")
    @app_commands.describe(keyword="Keyword to stop watching")
    async def remove_keyword(self, interaction: discord.Interaction, keyword: str):
        keyword = keyword.lower().strip()
        
        try:
            if self.bot.db.is_postgresql:
                result = await self.bot.db.connection.execute(
                    "DELETE FROM keywords WHERE guild_id = $1 AND user_id = $2 AND keyword = $3",
                    str(interaction.guild.id), str(interaction.user.id), keyword
                )
                rows_affected = 1 if result == "DELETE 1" else 0
            else:
                result = await self.bot.db.connection.execute(
                    "DELETE FROM keywords WHERE guild_id = ? AND user_id = ? AND keyword = ?",
                    (str(interaction.guild.id), str(interaction.user.id), keyword)
                )
                await self.bot.db.connection.commit()
                rows_affected = result.rowcount
            
            if rows_affected == 0:
                embed = EmbedBuilder.error("Not Found", f"You're not watching for the keyword **{keyword}**")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            embed = EmbedBuilder.success(
                "Keyword Removed",
                f"You'll no longer be notified when **{keyword}** is mentioned"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to remove keyword: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-keywords", description="List your watched keywords")
    async def list_keywords(self, interaction: discord.Interaction):
        try:
            if self.bot.db.is_postgresql:
                keywords = await self.bot.db.connection.fetch(
                    "SELECT keyword FROM keywords WHERE guild_id = $1 AND user_id = $2 ORDER BY keyword",
                    str(interaction.guild.id), str(interaction.user.id)
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT keyword FROM keywords WHERE guild_id = ? AND user_id = ? ORDER BY keyword",
                    (str(interaction.guild.id), str(interaction.user.id))
                )
                keywords = await cursor.fetchall()
            
            if not keywords:
                embed = EmbedBuilder.info("No Keywords", "You're not watching any keywords in this server")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            keyword_list = []
            for row in keywords:
                keyword = row['keyword'] if self.bot.db.is_postgresql else row[0]
                keyword_list.append(f"• {keyword}")
            
            embed = discord.Embed(
                title="🔔 Your Keywords",
                description="\n".join(keyword_list),
                color=0x5865F2
            )
            embed.set_footer(text=f"Watching {len(keyword_list)} keywords in this server")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch keywords: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    cog = Notifications(bot)
    await bot.add_cog(cog)
    
    # Sync commands to all guilds
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"✅ Synced Notifications commands to {guild.name}")
        except Exception as e:
            print(f"❌ Failed to sync Notifications commands to {guild.name}: {e}")
    
    print(f"🔔 Successfully loaded Notifications cog with {len(cog.get_app_commands())} commands")
