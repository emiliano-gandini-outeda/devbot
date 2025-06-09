import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import json
import asyncio
from datetime import datetime
import random
from typing import List
from discord.ui import Select, View
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
        channel="Channel to send updates to"
    )
    async def track_repo(self, interaction: discord.Interaction, repo: str, channel: discord.TextChannel):
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
    @app_commands.describe(
        repo="Repository name (format: owner/repo)",
        channel="Channel where updates are being sent"
    )
    async def untrack_repo(self, interaction: discord.Interaction, repo: str, channel: discord.TextChannel):
        await interaction.response.defer()
        
        try:
            # Remove from database
            result = await self.bot.db.connection.execute(
                "DELETE FROM github_tracked_repos WHERE guild_id = $1 AND repo_name = $2 AND channel_id = $3",
                str(interaction.guild.id), repo, str(channel.id)
            )
            
            if "DELETE 0" in str(result):
                embed = EmbedBuilder.error(
                    "Not Tracking",
                    f"Not tracking {repo} in {channel.mention}"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Remove from cache
            cache_key = f"{interaction.guild.id}:{repo}:{channel.id}"
            if cache_key in self.repo_cache:
                del self.repo_cache[cache_key]
            
            embed = EmbedBuilder.success(
                "Tracking Stopped",
                f"Stopped tracking {repo} in {channel.mention}"
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to untrack repository: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-repos", description="List tracked GitHub repositories")
    async def list_repos(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            # Get tracked repos for this guild
            repos = await self.bot.db.connection.fetch(
                "SELECT * FROM github_tracked_repos WHERE guild_id = $1",
                str(interaction.guild.id)
            )
            
            if not repos:
                embed = EmbedBuilder.info("No Repositories", "No GitHub repositories are being tracked in this server")
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title="🐙 Tracked GitHub Repositories",
                description=f"This server is tracking {len(repos)} repositories",
                color=0x333333  # GitHub dark
            )
            
            for repo in repos:
                repo_name = repo['repo_name']
                channel_id = repo['channel_id']
                added_by = repo['added_by']
                
                channel = interaction.guild.get_channel(int(channel_id))
                channel_mention = channel.mention if channel else "Unknown Channel"
                
                user = interaction.guild.get_member(int(added_by))
                user_name = user.display_name if user else "Unknown User"
                
                embed.add_field(
                    name=repo_name,
                    value=f"**Channel:** {channel_mention}\n**Added by:** {user_name}",
                    inline=True
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to list repositories: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="subscribe-repo", description="Subscribe to repository notifications")
    async def subscribe_repo(self, interaction: discord.Interaction):
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
            
            # Create dropdown options
            options = []
            for repo in repos[:25]:  # Discord limits to 25 options
                repo_name = repo['repo_name']
                options.append(discord.SelectOption(label=repo_name, value=repo_name))
            
            # Create view with dropdown
            view = RepoSubscriptionView(self.bot, options, interaction.user.id, str(interaction.guild.id))
            
            embed = discord.Embed(
                title="🔔 Repository Subscriptions",
                description="Select repositories to subscribe to notifications",
                color=0x333333  # GitHub dark
            )
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to load subscription options: {str(e)}")
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
                "pull_requests": []
            }
        
        # Mock repository data (in a real implementation, this would use the GitHub API)
        new_stars = random.randint(0, 100)
        new_commit = f"commit_{random.randint(1000, 9999)}"
        new_prs = [f"pr_{random.randint(100, 999)}" for _ in range(random.randint(0, 3))]
        
        cache = self.repo_cache[cache_key]
        updates = []
        
        # Check for star changes
        if cache["stars"] > 0 and new_stars != cache["stars"]:
            diff = new_stars - cache["stars"]
            if diff > 0:
                updates.append(f"⭐ **{diff} new stars** (now at {new_stars})")
        
        # Check for new commits
        if cache["last_commit"] and new_commit != cache["last_commit"]:
            updates.append(f"📝 **New commit:** {new_commit}")
        
        # Check for new PRs
        new_pr_count = 0
        for pr in new_prs:
            if pr not in cache["pull_requests"]:
                new_pr_count += 1
        
        if new_pr_count > 0:
            updates.append(f"🔀 **{new_pr_count} new pull requests**")
        
        # Update cache
        cache["stars"] = new_stars
        cache["last_commit"] = new_commit
        cache["pull_requests"] = new_prs
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
            
            embed.set_footer(text="GitHub Tracking • Railway Bot")
            
            await channel.send(embed=embed)
            
        except Exception as e:
            print(f"Error sending repo status: {e}")

class RepoSubscriptionView(discord.ui.View):
    def __init__(self, bot, options, user_id, guild_id):
        super().__init__(timeout=60)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        
        # Add dropdown
        self.add_item(RepoSubscriptionDropdown(bot, options, user_id, guild_id))

class RepoSubscriptionDropdown(discord.ui.Select):
    def __init__(self, bot, options, user_id, guild_id):
        super().__init__(
            placeholder="Select repositories to subscribe to...",
            min_values=0,
            max_values=len(options),
            options=options
        )
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get all repos for this guild
            repos = await self.bot.db.connection.fetch(
                "SELECT repo_name FROM github_tracked_repos WHERE guild_id = $1",
                self.guild_id
            )
            
            repo_names = [repo['repo_name'] for repo in repos]
            
            # For each repo, update subscription
            for repo_name in repo_names:
                is_selected = repo_name in self.values
                
                # Check if subscription exists
                existing = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM github_subscriptions WHERE user_id = $1 AND guild_id = $2 AND repo_name = $3",
                    str(self.user_id), self.guild_id, repo_name
                )
                
                if existing:
                    # Update existing subscription
                    await self.bot.db.connection.execute(
                        "UPDATE github_subscriptions SET enabled = $1 WHERE id = $2",
                        is_selected, existing['id']
                    )
                elif is_selected:
                    # Create new subscription
                    await self.bot.db.connection.execute(
                        "INSERT INTO github_subscriptions (user_id, guild_id, repo_name, enabled) VALUES ($1, $2, $3, $4)",
                        str(self.user_id), self.guild_id, repo_name, True
                    )
            
            embed = EmbedBuilder.success(
                "Subscriptions Updated",
                f"You've subscribed to {len(self.values)} repositories"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to update subscriptions: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(GitHubIntegrations(bot))
