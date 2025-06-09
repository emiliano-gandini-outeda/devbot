import discord
from discord.ext import commands
from discord import app_commands
import json
from utils.helpers import EmbedBuilder

class Notifications(commands.Cog):
    """Notification management and keyword alerts"""
    
    def __init__(self, bot):
        self.bot = bot
        self.user_keywords = {}  # In-memory storage for keywords
        self.muted_threads = {}  # In-memory storage for muted threads
    
    async def load_user_keywords(self):
        """Load user keywords from database"""
        try:
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT user_id, data_content FROM user_data WHERE data_type = 'keywords'"
                )
                for row in rows:
                    user_id = row['user_id']
                    keywords = row['data_content'].get('keywords', []) if isinstance(row['data_content'], dict) else json.loads(row['data_content']).get('keywords', [])
                    self.user_keywords[user_id] = keywords
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT user_id, data_content FROM user_data WHERE data_type = 'keywords'"
                )
                rows = await cursor.fetchall()
                for row in rows:
                    user_id = row[0]
                    keywords = json.loads(row[1]).get('keywords', [])
                    self.user_keywords[user_id] = keywords
        except Exception as e:
            print(f"Error loading user keywords: {e}")
    
    async def save_user_keywords(self, user_id: str):
        """Save user keywords to database"""
        try:
            keywords = self.user_keywords.get(user_id, [])
            data = {"keywords": keywords}
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO user_data (user_id, data_type, data_content)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (user_id, data_type) DO UPDATE SET data_content = $3""",
                    user_id, 'keywords', json.dumps(data)
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO user_data (user_id, data_type, data_content)
                       VALUES (?, ?, ?)""",
                    (user_id, 'keywords', json.dumps(data))
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error saving user keywords: {e}")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Check for keyword alerts in messages"""
        if message.author.bot or not message.guild:
            return
        
        # Check for keyword mentions
        await self.check_keyword_alerts(message)
    
    async def check_keyword_alerts(self, message):
        """Check if message contains any user's keywords"""
        content_lower = message.content.lower()
        
        for user_id, keywords in self.user_keywords.items():
            if user_id == str(message.author.id):
                continue  # Don't alert users about their own messages
            
            for keyword in keywords:
                if keyword.lower() in content_lower:
                    user = self.bot.get_user(int(user_id))
                    if user:
                        await self.send_keyword_alert(user, message, keyword)
                        break
    
    async def send_keyword_alert(self, user, message, keyword):
        """Send keyword alert to user via DM"""
        try:
            embed = discord.Embed(
                title="🔔 Keyword Alert",
                description=f"Your keyword **{keyword}** was mentioned",
                color=0x5865F2
            )
            embed.add_field(name="Server", value=message.guild.name, inline=True)
            embed.add_field(name="Channel", value=message.channel.mention, inline=True)
            embed.add_field(name="Author", value=message.author.mention, inline=True)
            embed.add_field(name="Message", value=message.content[:1000], inline=False)
            embed.add_field(name="Jump to Message", value=f"[Click here]({message.jump_url})", inline=False)
            
            # Try to send DM
            try:
                await user.send(embed=embed)
            except discord.Forbidden:
                # If DM fails, try to send in the same channel as a mention
                try:
                    alert_embed = discord.Embed(
                        title="🔔 Keyword Alert",
                        description=f"{user.mention} Your keyword **{keyword}** was mentioned in this message: {message.jump_url}",
                        color=0x5865F2
                    )
                    await message.channel.send(embed=alert_embed, delete_after=30)
                except:
                    pass  # If both fail, silently ignore
        except Exception as e:
            print(f"Error sending keyword alert: {e}")
    
    @app_commands.command(name="add-keyword", description="Add a keyword to get notified about")
    @app_commands.describe(keyword="Keyword to monitor for mentions")
    async def add_keyword(self, interaction: discord.Interaction, keyword: str):
        user_id = str(interaction.user.id)
        
        if user_id not in self.user_keywords:
            self.user_keywords[user_id] = []
        
        if keyword.lower() in [k.lower() for k in self.user_keywords[user_id]]:
            embed = EmbedBuilder.warning("Already Exists", f"You're already monitoring the keyword: **{keyword}**")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        if len(self.user_keywords[user_id]) >= 10:
            embed = EmbedBuilder.error("Limit Reached", "You can only monitor up to 10 keywords")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        self.user_keywords[user_id].append(keyword)
        await self.save_user_keywords(user_id)
        
        embed = EmbedBuilder.success(
            "Keyword Added",
            f"You'll now receive notifications when **{keyword}** is mentioned"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="remove-keyword", description="Remove a keyword from monitoring")
    @app_commands.describe(keyword="Keyword to stop monitoring")
    async def remove_keyword(self, interaction: discord.Interaction, keyword: str):
        user_id = str(interaction.user.id)
        
        if user_id not in self.user_keywords or not self.user_keywords[user_id]:
            embed = EmbedBuilder.error("No Keywords", "You don't have any keywords being monitored")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Find and remove keyword (case insensitive)
        removed = False
        for i, k in enumerate(self.user_keywords[user_id]):
            if k.lower() == keyword.lower():
                self.user_keywords[user_id].pop(i)
                removed = True
                break
        
        if not removed:
            embed = EmbedBuilder.error("Not Found", f"Keyword **{keyword}** is not being monitored")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await self.save_user_keywords(user_id)
        
        embed = EmbedBuilder.success(
            "Keyword Removed",
            f"You'll no longer receive notifications for **{keyword}**"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-keywords", description="List your monitored keywords")
    async def list_keywords(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        if user_id not in self.user_keywords or not self.user_keywords[user_id]:
            embed = EmbedBuilder.info("No Keywords", "You don't have any keywords being monitored")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        keywords = self.user_keywords[user_id]
        embed = discord.Embed(
            title="🔔 Your Monitored Keywords",
            description="\n".join([f"• {keyword}" for keyword in keywords]),
            color=0x5865F2
        )
        embed.set_footer(text=f"Monitoring {len(keywords)}/10 keywords • devBot")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    cog = Notifications(bot)
    await bot.add_cog(cog)
    
    # Load user keywords on startup
    await cog.load_user_keywords()
    
    # Ensure commands are added to the tree
    for command in cog.__cog_app_commands__:
        if command not in bot.tree.get_commands():
            bot.tree.add_command(command)
    
    print(f"🔔 Successfully loaded Notifications cog with {len(cog.get_app_commands())} commands")
