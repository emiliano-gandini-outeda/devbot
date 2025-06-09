import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import json
from datetime import datetime
from utils.helpers import EmbedBuilder
import asyncio
from typing import List

class GitHubIntegrations(commands.Cog):
    """GitHub repository tracking and integration"""
    
    def __init__(self, bot):
        self.bot = bot
        self.check_updates_task = None
        self.repo_cache = {}  # Cache for repo data to track changes
    
    async def cog_load(self):
        """Start background task when cog is loaded"""
        await asyncio.sleep(5)  # Wait for bot to be ready
        self.check_updates_task = self.bot.loop.create_task(self.check_updates_loop())
    
    def cog_unload(self):
        """Cancel background task when cog is unloaded"""
        if self.check_updates_task:
            self.check_updates_task.cancel()
    
    async def get_tracked_repos(self, guild_id: str) -> List[dict]:
        """Get tracked repositories for a guild from database"""
        try:
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT * FROM github_tracked_repos WHERE guild_id = $1", guild_id
                )
                return [dict(row) for row in rows]
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM github_tracked_repos WHERE guild_id = ?", (guild_id,)
                )
                rows = await cursor.fetchall()
                repos = []
                for row in rows:
                    repos.append({
                        'id': row[0],
                        'guild_id': row[1],
                        'repo_name': row[2],
                        'channel_id': row[3],
                        'added_by': row[4],
                        'created_at': row[5]
                    })
                return repos
        except Exception as e:
            print(f"Error getting tracked repos: {e}")
            return []
    
    async def add_tracked_repo(self, guild_id: str, repo_name: str, channel_id: str, added_by: str):
        """Add tracked repository to database"""
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO github_tracked_repos (guild_id, repo_name, channel_id, added_by)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (guild_id, repo_name, channel_id) DO NOTHING""",
                    guild_id, repo_name, channel_id, added_by
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR IGNORE INTO github_tracked_repos (guild_id, repo_name, channel_id, added_by)
                       VALUES (?, ?, ?, ?)""",
                    (guild_id, repo_name, channel_id, added_by)
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error adding tracked repo: {e}")
    
    async def remove_tracked_repo(self, guild_id: str, repo_name: str, channel_id: str):
        """Remove tracked repository from database"""
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "DELETE FROM github_tracked_repos WHERE guild_id = $1 AND repo_name = $2 AND channel_id = $3",
                    guild_id, repo_name, channel_id
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM github_tracked_repos WHERE guild_id = ? AND repo_name = ? AND channel_id = ?",
                    (guild_id, repo_name, channel_id)
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error removing tracked repo: {e}")
    
    @app_commands.command(name="track-repo", description="Track a GitHub repository for updates")
    @app_commands.describe(
        repo="Repository name (format: owner/repo)",
        channel="Channel to send updates to"
    )
    async def track_repo(self, interaction: discord.Interaction, repo: str, channel: discord.TextChannel):
        await interaction.response.defer()
        
        # Validate repo format
        if "/" not in repo:
            embed = EmbedBuilder.error(
                "Invalid Format", 
                "Repository must be in format `owner/repo` (e.g., `discord/discord-api-docs`)"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        try:
            # Check if repo exists
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.github.com/repos/{repo}", 
                                      headers={"Accept": "application/vnd.github.v3+json"}) as response:
                    if response.status != 200:
                        embed = EmbedBuilder.error(
                            "Repository Not Found", 
                            f"Could not find repository: {repo}"
                        )
                        await interaction.followup.send(embed=embed, ephemeral=True)
                        return
                    
                    repo_data = await response.json()
            
            # Check if already tracking
            guild_id = str(interaction.guild.id)
            tracked_repos = await self.get_tracked_repos(guild_id)
            
            for tracked in tracked_repos:
                if tracked['repo_name'] == repo and tracked['channel_id'] == str(channel.id):
                    embed = EmbedBuilder.warning(
                        "Already Tracking", 
                        f"Already tracking {repo} in {channel.mention}"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
            
            # Add to tracked repos
            await self.add_tracked_repo(guild_id, repo, str(channel.id), str(interaction.user.id))
            
            # Initialize cache for this repo
            cache_key = f"{guild_id}:{repo}"
            self.repo_cache[cache_key] = await self.get_repo_data(repo)
            
            # Create success embed
            embed = discord.Embed(
                title=f"📊 Now Tracking: {repo}",
                description=f"Successfully tracking GitHub repository in {channel.mention}",
                color=0x5865F2,
                url=f"https://github.com/{repo}"
            )
            
            embed.add_field(name="Repository", value=repo_data['full_name'], inline=True)
            embed.add_field(name="Stars", value=f"⭐ {repo_data['stargazers_count']}", inline=True)
            embed.add_field(name="Forks", value=f"🍴 {repo_data['forks_count']}", inline=True)
            embed.add_field(name="Description", value=repo_data['description'] or "No description", inline=False)
            
            embed.set_thumbnail(url=repo_data['owner']['avatar_url'])
            embed.set_footer(text="Updates will be posted in this channel • Use /subscribe-repo to get pinged")
            
            await interaction.followup.send(embed=embed)
            
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
        
        guild_id = str(interaction.guild.id)
        tracked_repos = await self.get_tracked_repos(guild_id)
        
        if not tracked_repos:
            embed = EmbedBuilder.error("Not Tracking", "No repositories are being tracked in this server")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Find and remove the tracked repo
        found = False
        for tracked in tracked_repos:
            if tracked['repo_name'] == repo and tracked['channel_id'] == str(channel.id):
                await self.remove_tracked_repo(guild_id, repo, str(channel.id))
                
                # Remove from cache
                cache_key = f"{guild_id}:{repo}"
                if cache_key in self.repo_cache:
                    del self.repo_cache[cache_key]
                
                found = True
                break
        
        if not found:
            embed = EmbedBuilder.error(
                "Not Found", 
                f"Not tracking {repo} in {channel.mention}"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        embed = EmbedBuilder.success(
            "Tracking Stopped",
            f"Stopped tracking {repo} in {channel.mention}"
        )
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="list-repos", description="List all tracked GitHub repositories")
    async def list_repos(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        guild_id = str(interaction.guild.id)
        tracked_repos = await self.get_tracked_repos(guild_id)
        
        if not tracked_repos:
            embed = EmbedBuilder.info("No Repositories", "No GitHub repositories are being tracked in this server")
            await interaction.followup.send(embed=embed)
            return
        
        embed = discord.Embed(
            title="📊 Tracked GitHub Repositories",
            description=f"This server is tracking {len(tracked_repos)} repositories",
            color=0x5865F2
        )
        
        for tracked in tracked_repos:
            repo = tracked['repo_name']
            channel = interaction.guild.get_channel(int(tracked['channel_id']))
            channel_mention = channel.mention if channel else "Unknown Channel"
            
            embed.add_field(
                name=repo,
                value=f"**Channel:** {channel_mention}\n**URL:** [View on GitHub](https://github.com/{repo})",
                inline=True
            )
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="subscribe-repo", description="Subscribe to notifications for a tracked repository")
    @app_commands.describe(repo="Repository name (format: owner/repo)")
    async def subscribe_repo(self, interaction: discord.Interaction, repo: str):
        await interaction.response.defer(ephemeral=True)
        
        try:
            guild_id = str(interaction.guild.id)
            user_id = str(interaction.user.id)
            
            # Check if repo is tracked in this server
            tracked_repos = await self.get_tracked_repos(guild_id)
            repo_tracked = any(tracked['repo_name'] == repo for tracked in tracked_repos)
            
            if not repo_tracked:
                embed = EmbedBuilder.error(
                    "Repository Not Tracked",
                    f"Repository {repo} is not being tracked in this server. Use `/track-repo` first."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Add subscription
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO github_subscriptions (user_id, guild_id, repo_name, enabled) 
                       VALUES ($1, $2, $3, TRUE) 
                       ON CONFLICT (user_id, guild_id, repo_name) DO UPDATE SET enabled = TRUE""",
                    user_id, guild_id, repo
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO github_subscriptions (user_id, guild_id, repo_name, enabled) 
                       VALUES (?, ?, ?, 1)""",
                    (user_id, guild_id, repo)
                )
                await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Subscribed!",
                f"You will now be pinged for updates to **{repo}**"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to subscribe: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="unsubscribe-repo", description="Unsubscribe from notifications for a repository")
    @app_commands.describe(repo="Repository name (format: owner/repo)")
    async def unsubscribe_repo(self, interaction: discord.Interaction, repo: str):
        await interaction.response.defer(ephemeral=True)
        
        try:
            guild_id = str(interaction.guild.id)
            user_id = str(interaction.user.id)
            
            # Remove subscription
            if self.bot.db.is_postgresql:
                result = await self.bot.db.connection.execute(
                    "DELETE FROM github_subscriptions WHERE user_id = $1 AND guild_id = $2 AND repo_name = $3",
                    user_id, guild_id, repo
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM github_subscriptions WHERE user_id = ? AND guild_id = ? AND repo_name = ?",
                    (user_id, guild_id, repo)
                )
                await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Unsubscribed!",
                f"You will no longer be pinged for updates to **{repo}**"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to unsubscribe: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def get_repo_data(self, repo: str) -> dict:
        """Get current repository data from GitHub API"""
        try:
            data = {}
            
            # Get basic repo info
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.github.com/repos/{repo}") as response:
                    if response.status == 200:
                        repo_info = await response.json()
                        data['stars'] = repo_info['stargazers_count']
                        data['forks'] = repo_info['forks_count']
            
            # Get latest commit
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.github.com/repos/{repo}/commits") as response:
                    if response.status == 200:
                        commits = await response.json()
                        if commits:
                            data['latest_commit'] = commits[0]['sha']
            
            # Get open PRs
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.github.com/repos/{repo}/pulls?state=open") as response:
                    if response.status == 200:
                        pulls = await response.json()
                        data['open_prs'] = len(pulls)
                        data['pr_numbers'] = [pr['number'] for pr in pulls]
            
            return data
        except Exception as e:
            print(f"Error getting repo data for {repo}: {e}")
            return {}
    
    async def check_updates_loop(self):
        """Background task to check for repository updates"""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.check_all_repos()
            except Exception as e:
                print(f"Error checking repo updates: {e}")
            
            # Check every 10 minutes
            await asyncio.sleep(600)
    
    async def check_all_repos(self):
        """Check all tracked repositories for updates"""
        try:
            # Get all unique repos being tracked
            all_repos = set()
            guild_repos = {}
            
            for guild in self.bot.guilds:
                guild_id = str(guild.id)
                tracked_repos = await self.get_tracked_repos(guild_id)
                guild_repos[guild_id] = tracked_repos
                
                for repo_data in tracked_repos:
                    all_repos.add(repo_data['repo_name'])
            
            # Check each unique repo for updates
            for repo in all_repos:
                try:
                    cache_key = f"global:{repo}"
                    old_data = self.repo_cache.get(cache_key, {})
                    new_data = await self.get_repo_data(repo)
                    
                    if not new_data:
                        continue
                    
                    # Check for changes and notify all guilds tracking this repo
                    notifications = await self.check_repo_changes(repo, old_data, new_data)
                    
                    if notifications:
                        # Send notifications to all guilds tracking this repo
                        for guild_id, tracked_repos in guild_repos.items():
                            guild = self.bot.get_guild(int(guild_id))
                            if not guild:
                                continue
                            
                            for repo_data in tracked_repos:
                                if repo_data['repo_name'] == repo:
                                    channel = guild.get_channel(int(repo_data['channel_id']))
                                    if channel:
                                        subscribers = await self.get_repo_subscribers(guild_id, repo)
                                        
                                        for notification in notifications:
                                            # Add mentions if there are subscribers
                                            content = None
                                            if subscribers:
                                                mentions = []
                                                for user_id in subscribers:
                                                    user = guild.get_member(int(user_id))
                                                    if user:
                                                        mentions.append(user.mention)
                                                if mentions:
                                                    content = " ".join(mentions[:10])  # Limit mentions
                                            
                                            await channel.send(content=content, embed=notification)
                    
                    # Update cache
                    self.repo_cache[cache_key] = new_data
                    
                except Exception as e:
                    print(f"Error checking repo {repo}: {e}")
                    
        except Exception as e:
            print(f"Error in check_all_repos: {e}")
    
    async def check_repo_changes(self, repo: str, old_data: dict, new_data: dict) -> List[discord.Embed]:
        """Check for changes in repository data and return notification embeds"""
        notifications = []
        
        try:
            # Check for new stars
            old_stars = old_data.get('stars', 0)
            new_stars = new_data.get('stars', 0)
            
            if new_stars > old_stars and old_stars > 0:  # Don't notify on first check
                embed = discord.Embed(
                    title=f"⭐ New Stars: {repo}",
                    description=f"Repository gained {new_stars - old_stars} new stars!",
                    color=0xFFD700,
                    url=f"https://github.com/{repo}"
                )
                embed.add_field(name="Total Stars", value=f"⭐ {new_stars}", inline=True)
                embed.set_footer(text=f"GitHub • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
                notifications.append(embed)
            
            # Check for new commits
            old_commit = old_data.get('latest_commit')
            new_commit = new_data.get('latest_commit')
            
            if old_commit and new_commit and old_commit != new_commit:
                embed = discord.Embed(
                    title=f"🔄 New Commits: {repo}",
                    description="New commits pushed to repository",
                    color=0x5865F2,
                    url=f"https://github.com/{repo}/commits"
                )
                embed.set_footer(text=f"GitHub • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
                notifications.append(embed)
            
            # Check for new PRs
            old_pr_numbers = set(old_data.get('pr_numbers', []))
            new_pr_numbers = set(new_data.get('pr_numbers', []))
            new_prs = new_pr_numbers - old_pr_numbers
            
            if new_prs:
                embed = discord.Embed(
                    title=f"🔀 New Pull Request: {repo}",
                    description=f"{len(new_prs)} new pull request(s) opened",
                    color=0x6F42C1,
                    url=f"https://github.com/{repo}/pulls"
                )
                embed.add_field(name="PR Numbers", value=", ".join([f"#{pr}" for pr in new_prs]), inline=False)
                embed.set_footer(text=f"GitHub • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
                notifications.append(embed)
            
        except Exception as e:
            print(f"Error checking repo changes for {repo}: {e}")
        
        return notifications

    async def get_repo_subscribers(self, guild_id: str, repo: str) -> List[str]:
        """Get list of users subscribed to a repository"""
        try:
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT user_id FROM github_subscriptions WHERE guild_id = $1 AND repo_name = $2 AND enabled = TRUE",
                    guild_id, repo
                )
                return [row['user_id'] for row in rows]
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT user_id FROM github_subscriptions WHERE guild_id = ? AND repo_name = ? AND enabled = 1",
                    (guild_id, repo)
                )
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
        except Exception as e:
            print(f"Error getting repo subscribers: {e}")
            return []

async def setup(bot):
    github_cog = GitHubIntegrations(bot)
    await bot.add_cog(github_cog)
    print(f"🐙 Successfully loaded GitHub Integrations cog with {len(github_cog.get_app_commands())} commands")
