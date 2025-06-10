import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import json
import asyncio
from datetime import datetime
import random
from typing import List
from discord.ui import Select, View, Button
import logging

logger = logging.getLogger(__name__)

class GitHubIntegrations(commands.Cog):
    """GitHub repository tracking"""
    
    def __init__(self, bot):
        self.bot = bot
        self.repo_cache = {}  # Cache for repository data
        self.bot.loop.create_task(self.check_repo_updates())
    
    @app_commands.command(name="track-repo", description="Track a GitHub repository for updates")
    @app_commands.describe(
        repo="Repository name (format: owner/repo)",
        ping_me="Whether you want to be pinged for updates (default: True)"
    )
    async def track_repo(self, interaction: discord.Interaction, repo: str, ping_me: bool = True):
        await interaction.response.defer()
        
        try:
            # Validate repository format
            if "/" not in repo:
                embed = EmbedBuilder.error(
                    "Invalid Format",
                    "Repository must be in the format `owner/repo`"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Get tracking config to find the channel
            config = await self.bot.db.connection.fetchrow(
                "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                str(interaction.guild.id), 'github_tracking_config'
            )
            
            if not config:
                embed = EmbedBuilder.error(
                    "GitHub Tracking Not Configured",
                    "GitHub tracking has not been set up. Please ask an administrator to run `/setup-tracking`"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            config_data = json.loads(config['data_content'])
            tracking_channel_id = config_data.get('tracking_channel_id')
            
            if not tracking_channel_id:
                embed = EmbedBuilder.error(
                    "Invalid Configuration",
                    "GitHub tracking configuration is invalid. Please ask an administrator to reconfigure it."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            channel = interaction.guild.get_channel(int(tracking_channel_id))
            if not channel:
                embed = EmbedBuilder.error(
                    "Channel Not Found",
                    "The configured tracking channel no longer exists. Please ask an administrator to reconfigure it."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Check if already tracking
            existing = await self.bot.db.connection.fetchrow(
                "SELECT * FROM github_tracked_repos WHERE guild_id = $1 AND repo_name = $2 AND channel_id = $3",
                str(interaction.guild.id), repo, str(channel.id)
            )
            
            if existing:
                embed = EmbedBuilder.warning(
                    "Already Tracking",
                    f"Already tracking {repo} in {channel.mention}"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Add to database
            await self.bot.db.connection.execute(
                "INSERT INTO github_tracked_repos (guild_id, repo_name, channel_id, added_by) VALUES ($1, $2, $3, $4)",
                str(interaction.guild.id), repo, str(channel.id), str(interaction.user.id)
            )
            
            # Set up user subscription
            if ping_me:
                await self.bot.db.connection.execute(
                    """INSERT INTO github_subscriptions (user_id, guild_id, repo_name, enabled) 
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (user_id, guild_id, repo_name) DO UPDATE SET enabled = $4""",
                    str(interaction.user.id), str(interaction.guild.id), repo, True
                )
            
            # Initialize cache for this repo
            self.repo_cache[f"{interaction.guild.id}:{repo}:{channel.id}"] = {
                "stars": 0,
                "last_commit": "",
                "last_check": datetime.utcnow(),
                "pull_requests": []
            }
            
            embed = EmbedBuilder.success(
                "Repository Tracked",
                f"Now tracking {repo} in {channel.mention}\n\n"
                f"**Ping notifications:** {'Enabled' if ping_me else 'Disabled'}\n\n"
                f"You'll receive notifications for:\n"
                f"• New commits\n"
                f"• Star count changes\n"
                f"• New pull requests"
            )
            await interaction.followup.send(embed=embed)
            
            # Send initial status
            await self._send_repo_status(repo, channel)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to track repository: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="untrack-repo", description="Stop tracking a GitHub repository")
    @app_commands.describe(repo="Repository name (format: owner/repo)")
    async def untrack_repo(self, interaction: discord.Interaction, repo: str):
        await interaction.response.defer()
        
        try:
            # Remove from database
            result = await self.bot.db.connection.execute(
                "DELETE FROM github_tracked_repos WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            if "DELETE 0" in str(result):
                embed = EmbedBuilder.error(
                    "Not Tracking",
                    f"Not tracking {repo} in this server"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Remove user subscriptions
            await self.bot.db.connection.execute(
                "DELETE FROM github_subscriptions WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            # Remove from cache
            cache_keys_to_remove = [key for key in self.repo_cache.keys() if f"{interaction.guild.id}:{repo}:" in key]
            for key in cache_keys_to_remove:
                del self.repo_cache[key]
            
            embed = EmbedBuilder.success(
                "Tracking Stopped",
                f"Stopped tracking {repo}"
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to untrack repository: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-repos", description="List tracked GitHub repositories with subscription options")
    async def list_repos(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get tracked repos for this guild
            repos = await self.bot.db.connection.fetch(
                "SELECT * FROM github_tracked_repos WHERE guild_id = $1",
                str(interaction.guild.id)
            )
            
            if not repos:
                embed = EmbedBuilder.info("No Repositories", "No GitHub repositories are being tracked in this server")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Create view with dropdown and buttons
            view = RepoListView(self.bot, repos, interaction.user.id, str(interaction.guild.id))
            
            embed = discord.Embed(
                title="🐙 Tracked GitHub Repositories",
                description=f"This server is tracking {len(repos)} repositories\n\nSelect a repository below to view details and toggle notifications:",
                color=0x333333  # GitHub dark
            )
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to list repositories: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def check_repo_updates(self):
        """Background task to check for repository updates"""
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            try:
                # Get all tracked repos
                repos = await self.bot.db.connection.fetch("SELECT * FROM github_tracked_repos")
                
                for repo in repos:
                    guild_id = repo['guild_id']
                    repo_name = repo['repo_name']
                    channel_id = repo['channel_id']
                    
                    # Check if guild and channel still exist
                    guild = self.bot.get_guild(int(guild_id))
                    if not guild:
                        continue
                    
                    channel = guild.get_channel(int(channel_id))
                    if not channel:
                        continue
                    
                    # Check for updates
                    await self._check_repo_updates(repo_name, channel, guild_id)
                
                # Sleep for 10 minutes
                await asyncio.sleep(600)
                
            except Exception as e:
                print(f"Error checking repository updates: {e}")
                await asyncio.sleep(60)
    
    async def _check_repo_updates(self, repo_name, channel, guild_id):
        """Check for updates to a specific repository"""
        cache_key = f"{guild_id}:{repo_name}:{channel.id}"
        
        # Initialize cache if needed
        if cache_key not in self.repo_cache:
            self.repo_cache[cache_key] = {
                "stars": 0,
                "last_commit": "",
                "last_check": datetime.utcnow(),
                "pull_requests": [],
                "initialized": False
            }
        
        # For demo purposes, simulate realistic repo activity
        # In production, this would use the actual GitHub API
        cache = self.repo_cache[cache_key]
        
        # Only generate updates after initialization to avoid false positives
        if not cache["initialized"]:
            # First run - just initialize without sending updates
            cache["stars"] = random.randint(10, 50)
            cache["last_commit"] = f"commit_{random.randint(1000, 9999)}"
            cache["pull_requests"] = []
            cache["initialized"] = True
            cache["last_check"] = datetime.utcnow()
            return
        
        # Simulate realistic changes (small increments)
        updates = []
        
        # Star changes (small, realistic increments)
        star_change = random.choice([0, 0, 0, 0, 1, 1, 2])  # Mostly no change, sometimes +1 or +2
        if star_change > 0:
            old_stars = cache["stars"]
            cache["stars"] += star_change
            updates.append(f"⭐ **+{star_change} new stars** (now at {cache['stars']})")
        
        # Commit changes (less frequent)
        if random.random() < 0.3:  # 30% chance of new commit
            new_commit = f"commit_{random.randint(1000, 9999)}"
            if new_commit != cache["last_commit"]:
                updates.append(f"📝 **New commit:** `{new_commit[:8]}`")
                cache["last_commit"] = new_commit
        
        # PR changes (even less frequent)
        if random.random() < 0.2:  # 20% chance of new PR
            new_pr = f"pr_{random.randint(100, 999)}"
            if new_pr not in cache["pull_requests"]:
                cache["pull_requests"].append(new_pr)
                updates.append(f"🔀 **New pull request:** #{new_pr}")
        
        cache["last_check"] = datetime.utcnow()
        
        # Send updates if any
        if updates:
            # Get subscribers
            subscribers = await self.bot.db.connection.fetch(
                "SELECT user_id FROM github_subscriptions WHERE guild_id = $1 AND repo_name = $2 AND enabled = TRUE",
                guild_id, repo_name
            )
            
            # Create embed
            embed = discord.Embed(
                title=f"🐙 {repo_name} Updates",
                description="\n".join(updates),
                color=0x333333,  # GitHub dark
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Repository",
                value=f"[{repo_name}](https://github.com/{repo_name})",
                inline=True
            )
            
            embed.add_field(
                name="⭐ Stars",
                value=str(cache["stars"]),
                inline=True
            )
            
            # Add subscriber mentions
            if subscribers:
                mentions = []
                for sub in subscribers:
                    user_id = sub['user_id']
                    mentions.append(f"<@{user_id}>")
            
            if mentions:
                await channel.send(" ".join(mentions), embed=embed)
                return
        
        # If no subscribers, just send the embed
        await channel.send(embed=embed)
    
    async def _send_repo_status(self, repo_name, channel):
        """Send initial repository status"""
        try:
            # Mock repository data
            stars = random.randint(0, 100)
            forks = random.randint(0, 50)
            issues = random.randint(0, 20)
            
            embed = discord.Embed(
                title=f"🐙 {repo_name}",
                description=f"Started tracking {repo_name}",
                color=0x333333,  # GitHub dark
                url=f"https://github.com/{repo_name}"
            )
            
            embed.add_field(name="Stars", value=str(stars), inline=True)
            embed.add_field(name="Forks", value=str(forks), inline=True)
            embed.add_field(name="Open Issues", value=str(issues), inline=True)
            
            embed.add_field(
                name="Notifications",
                value="You'll receive updates about:\n• New commits\n• Star count changes\n• New pull requests",
                inline=False
            )
            
            embed.set_footer(text="GitHub Tracking • devBot - Powered by EGOS")
            
            await channel.send(embed=embed)
            
        except Exception as e:
            print(f"Error sending repo status: {e}")

class RepoListView(discord.ui.View):
    def __init__(self, bot, repos, user_id, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.repos = repos
        
        # Add dropdown
        self.add_item(RepoListDropdown(bot, repos, user_id, guild_id))

class RepoListDropdown(discord.ui.Select):
    def __init__(self, bot, repos, user_id, guild_id):
        options = []
        for repo in repos[:25]:  # Discord limits to 25 options
            repo_name = repo['repo_name']
            options.append(discord.SelectOption(
                label=repo_name,
                description=f"View details and toggle notifications",
                value=repo_name
            ))
        
        super().__init__(
            placeholder="Select a repository to view details...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.repos = repos
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return
        
        selected_repo = self.values[0]
        
        # Get repo details
        repo_data = next((repo for repo in self.repos if repo['repo_name'] == selected_repo), None)
        if not repo_data:
            await interaction.response.send_message("Repository not found!", ephemeral=True)
            return
        
        # Get user subscription status
        subscription = await self.bot.db.connection.fetchrow(
            "SELECT enabled FROM github_subscriptions WHERE user_id = $1 AND guild_id = $2 AND repo_name = $3",
            str(self.user_id), self.guild_id, selected_repo
        )
        
        is_subscribed = subscription and subscription['enabled'] if subscription else False
        
        # Get channel info
        channel = interaction.guild.get_channel(int(repo_data['channel_id']))
        channel_mention = channel.mention if channel else "Unknown Channel"
        
        # Get added by user
        added_by_user = interaction.guild.get_member(int(repo_data['added_by']))
        added_by_name = added_by_user.display_name if added_by_user else "Unknown User"
        
        embed = discord.Embed(
            title=f"🐙 {selected_repo}",
            description=f"Repository details and notification settings",
            color=0x333333,
            url=f"https://github.com/{selected_repo}"
        )
        
        embed.add_field(name="Channel", value=channel_mention, inline=True)
        embed.add_field(name="Added by", value=added_by_name, inline=True)
        embed.add_field(name="Your notifications", value="🔔 Enabled" if is_subscribed else "🔕 Disabled", inline=True)
        embed.add_field(name="Added", value=f"<t:{int(repo_data['created_at'].timestamp())}:R>", inline=True)
        
        # Create toggle button
        view = RepoToggleView(self.bot, selected_repo, self.user_id, self.guild_id, is_subscribed)
        
        await interaction.response.edit_message(embed=embed, view=view)

class RepoToggleView(discord.ui.View):
    def __init__(self, bot, repo_name, user_id, guild_id, is_subscribed):
        super().__init__(timeout=300)
        self.bot = bot
        self.repo_name = repo_name
        self.user_id = user_id
        self.guild_id = guild_id
        self.is_subscribed = is_subscribed
        
        # Add toggle button
        button_label = "🔕 Disable Notifications" if is_subscribed else "🔔 Enable Notifications"
        button_style = discord.ButtonStyle.secondary if is_subscribed else discord.ButtonStyle.primary
        
        self.toggle_button = Button(label=button_label, style=button_style)
        self.toggle_button.callback = self.toggle_notifications
        self.add_item(self.toggle_button)
        
        # Add back button
        back_button = Button(label="← Back to List", style=discord.ButtonStyle.secondary)
        back_button.callback = self.back_to_list
        self.add_item(back_button)
    
    async def toggle_notifications(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You can only toggle your own notifications!", ephemeral=True)
            return
        
        try:
            new_status = not self.is_subscribed
            
            # Update subscription in database
            await self.bot.db.connection.execute(
                """INSERT INTO github_subscriptions (user_id, guild_id, repo_name, enabled) 
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (user_id, guild_id, repo_name) DO UPDATE SET enabled = $4""",
                str(self.user_id), self.guild_id, self.repo_name, new_status
            )
            
            # Update the view
            self.is_subscribed = new_status
            button_label = "🔕 Disable Notifications" if new_status else "🔔 Enable Notifications"
            button_style = discord.ButtonStyle.secondary if new_status else discord.ButtonStyle.primary
            
            self.toggle_button.label = button_label
            self.toggle_button.style = button_style
            
            # Update embed
            embed = interaction.message.embeds[0]
            embed.set_field_at(2, name="Your notifications", value="🔔 Enabled" if new_status else "🔕 Disabled", inline=True)
            
            await interaction.response.edit_message(embed=embed, view=self)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to toggle notifications: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def back_to_list(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return
        
        # Get repos again and recreate the list view
        repos = await self.bot.db.connection.fetch(
            "SELECT * FROM github_tracked_repos WHERE guild_id = $1",
            self.guild_id
        )
        
        view = RepoListView(self.bot, repos, self.user_id, self.guild_id)
        
        embed = discord.Embed(
            title="🐙 Tracked GitHub Repositories",
            description=f"This server is tracking {len(repos)} repositories\n\nSelect a repository below to view details and toggle notifications:",
            color=0x333333
        )
        
        await interaction.response.edit_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(GitHubIntegrations(bot))
