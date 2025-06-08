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
        """Send keyword alert to user"""
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
            embed.set_footer(text="Powered by Railway 🚄")
            
            await user.send(embed=embed)
        except discord.Forbidden:
            pass  # User has DMs disabled
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
        embed.set_footer(text=f"Monitoring {len(keywords)}/10 keywords • Railway 🚄")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="mute-thread", description="Mute notifications from current thread")
    async def mute_thread(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            embed = EmbedBuilder.error("Not a Thread", "This command can only be used in threads")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        user_id = str(interaction.user.id)
        thread_id = str(interaction.channel.id)
        
        if user_id not in self.muted_threads:
            self.muted_threads[user_id] = []
        
        if thread_id in self.muted_threads[user_id]:
            embed = EmbedBuilder.warning("Already Muted", "This thread is already muted for you")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        self.muted_threads[user_id].append(thread_id)
        
        embed = EmbedBuilder.success(
            "Thread Muted",
            f"You'll no longer receive keyword notifications from **{interaction.channel.name}**"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="unmute-thread", description="Unmute notifications from current thread")
    async def unmute_thread(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            embed = EmbedBuilder.error("Not a Thread", "This command can only be used in threads")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        user_id = str(interaction.user.id)
        thread_id = str(interaction.channel.id)
        
        if user_id not in self.muted_threads or thread_id not in self.muted_threads[user_id]:
            embed = EmbedBuilder.warning("Not Muted", "This thread is not muted for you")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        self.muted_threads[user_id].remove(thread_id)
        
        embed = EmbedBuilder.success(
            "Thread Unmuted",
            f"You'll now receive keyword notifications from **{interaction.channel.name}**"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="notification-settings", description="View your notification settings")
    async def notification_settings(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        embed = discord.Embed(
            title="🔔 Your Notification Settings",
            color=0x5865F2
        )
        
        # Keywords
        keywords = self.user_keywords.get(user_id, [])
        if keywords:
            embed.add_field(
                name=f"Keywords ({len(keywords)}/10)",
                value="\n".join([f"• {k}" for k in keywords]) or "None",
                inline=False
            )
        else:
            embed.add_field(name="Keywords", value="None configured", inline=False)
        
        # Muted threads
        muted = self.muted_threads.get(user_id, [])
        if muted:
            muted_names = []
            for thread_id in muted[:5]:  # Show first 5
                thread = self.bot.get_channel(int(thread_id))
                if thread:
                    muted_names.append(f"• {thread.name}")
            
            embed.add_field(
                name=f"Muted Threads ({len(muted)})",
                value="\n".join(muted_names) or "None",
                inline=False
            )
        else:
            embed.add_field(name="Muted Threads", value="None", inline=False)
        
        embed.set_footer(text="Powered by Railway 🚄")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Notifications(bot))
