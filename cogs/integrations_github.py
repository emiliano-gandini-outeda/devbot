import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import json
from datetime import datetime
from utils.helpers import EmbedBuilder
import asyncio
from typing import List
from discord.ui import Select, View
import logging

logger = logging.getLogger(__name__)

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
    async def subscribe_repo(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            guild_id = str(interaction.guild.id)
            tracked_repos = await self.get_tracked_repos(guild_id)
            
            if not tracked_repos:
                embed = EmbedBuilder.error(
                    "No Repositories",
                    "No repositories are being tracked in this server. Use `/track-repo` to start tracking repositories."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Get user's current subscriptions
            user_subscriptions = await self.get_user_subscriptions(str(interaction.user.id), guild_id)
            
            # Create dropdown view
            view = RepoSubscriptionView(self, interaction.user.id, guild_id, tracked_repos, user_subscriptions)
            
            embed = discord.Embed(
                title="📊 Subscribe to Repository Updates",
                description="Select repositories you want to be notified about from the dropdown below.",
                color=0x5865F2
            )
            
            embed.add_field(
                name="📋 Available Repositories",
                value=f"{len(tracked_repos)} repositories are being tracked in this server",
                inline=False
            )
            
            if user_subscriptions:
                subscribed_list = "\n".join([f"• {repo}" for repo in user_subscriptions])
                embed.add_field(
                    name="✅ Currently Subscribed",
                    value=subscribed_list,
                    inline=False
                )
            
            embed.set_footer(text="Select repositories from the dropdown to subscribe or unsubscribe")
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to load subscription menu: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def get_user_subscriptions(self, user_id: str, guild_id: str) -> List[str]:
        """Get list of repositories user is subscribed to"""
        try:
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT repo_name FROM github_subscriptions WHERE user_id = $1 AND guild_id = $2 AND enabled = TRUE",
                    user_id, guild_id
                )
                return [row['repo_name'] for row in rows]
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT repo_name FROM github_subscriptions WHERE user_id = ? AND guild_id = ? AND enabled = 1",
                    (user_id, guild_id)
                )
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
        except Exception as e:
            print(f"Error getting user subscriptions: {e}")
            return []
    
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

class RepoSubscriptionView(View):
    """View for repository subscription dropdown"""
    
    def __init__(self, cog, user_id: int, guild_id: str, tracked_repos: List[dict], user_subscriptions: List[str]):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog
        self.user_id = str(user_id)
        self.guild_id = guild_id
        self.tracked_repos = tracked_repos
        self.user_subscriptions = user_subscriptions
        
        # Create select options
        options = []
        for repo_data in tracked_repos:
            repo_name = repo_data['repo_name']
            is_subscribed = repo_name in user_subscriptions
            
            # Get channel info
            channel_id = repo_data['channel_id']
            guild = cog.bot.get_guild(int(guild_id))
            channel = guild.get_channel(int(channel_id)) if guild else None
            channel_name = f"#{channel.name}" if channel else "Unknown Channel"
            
            options.append(discord.SelectOption(
                label=repo_name,
                description=f"Updates in {channel_name} • {'✅ Subscribed' if is_subscribed else '🔔 Click to subscribe'}",
                value=repo_name,
                emoji="✅" if is_subscribed else "🔔"
            ))
        
        # Add the select dropdown
        self.repo_select = RepoSelect(options, self.user_subscriptions)
        self.add_item(self.repo_select)
    
    async def on_timeout(self):
        """Called when the view times out"""
        for item in self.children:
            item.disabled = True

class RepoSelect(Select):
    """Select dropdown for repository subscriptions"""
    
    def __init__(self, options: List[discord.SelectOption], current_subscriptions: List[str]):
        super().__init__(
            placeholder="Select repositories to subscribe/unsubscribe...",
            min_values=1,
            max_values=min(len(options), 25),  # Discord limit is 25
            options=options
        )
        self.current_subscriptions = current_subscriptions
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            view = self.view
            cog = view.cog
            user_id = view.user_id
            guild_id = view.guild_id
            
            selected_repos = self.values
            changes_made = []
            
            for repo in selected_repos:
                is_currently_subscribed = repo in self.current_subscriptions
                
                if is_currently_subscribed:
                    # Unsubscribe
                    if cog.bot.db.is_postgresql:
                        await cog.bot.db.connection.execute(
                            "DELETE FROM github_subscriptions WHERE user_id = $1 AND guild_id = $2 AND repo_name = $3",
                            user_id, guild_id, repo
                        )
                    else:
                        await cog.bot.db.connection.execute(
                            "DELETE FROM github_subscriptions WHERE user_id = ? AND guild_id = ? AND repo_name = ?",
                            (user_id, guild_id, repo)
                        )
                        await cog.bot.db.connection.commit()
                    
                    changes_made.append(f"🔕 Unsubscribed from **{repo}**")
                    
                else:
                    # Subscribe
                    if cog.bot.db.is_postgresql:
                        await cog.bot.db.connection.execute(
                            """INSERT INTO github_subscriptions (user_id, guild_id, repo_name, enabled) 
                               VALUES ($1, $2, $3, TRUE) 
                               ON CONFLICT (user_id, guild_id, repo_name) DO UPDATE SET enabled = TRUE""",
                            user_id, guild_id, repo
                        )
                    else:
                        await cog.bot.db.connection.execute(
                            """INSERT OR REPLACE INTO github_subscriptions (user_id, guild_id, repo_name, enabled) 
                               VALUES (?, ?, ?, 1)""",
                            (user_id, guild_id, repo)
                        )
                        await cog.bot.db.connection.commit()
                    
                    changes_made.append(f"🔔 Subscribed to **{repo}**")
            
            # Create response embed
            if changes_made:
                embed = discord.Embed(
                    title="✅ Subscription Changes Applied",
                    description="\n".join(changes_made),
                    color=0x00FF00
                )
                embed.set_footer(text="You will now receive notifications based on your subscriptions")
            else:
                embed = EmbedBuilder.info(
                    "No Changes",
                    "No subscription changes were made."
                )
            
            # Update the view with new subscription status
            updated_subscriptions = await cog.get_user_subscriptions(user_id, guild_id)
            
            # Update select options
            new_options = []
            for option in self.options:
                repo_name = option.value
                is_subscribed = repo_name in updated_subscriptions
                
                # Find the original repo data for channel info
                channel_name = "Unknown Channel"
                for repo_data in view.tracked_repos:
                    if repo_data['repo_name'] == repo_name:
                        channel_id = repo_data['channel_id']
                        guild = cog.bot.get_guild(int(guild_id))
                        channel = guild.get_channel(int(channel_id)) if guild else None
                        channel_name = f"#{channel.name}" if channel else "Unknown Channel"
                        break
                
                new_options.append(discord.SelectOption(
                    label=repo_name,
                    description=f"Updates in {channel_name} • {'✅ Subscribed' if is_subscribed else '🔔 Click to subscribe'}",
                    value=repo_name,
                    emoji="✅" if is_subscribed else "🔔"
                ))
            
            # Update the select options
            self.options = new_options
            self.current_subscriptions = updated_subscriptions
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to update subscriptions: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    github_cog = GitHubIntegrations(bot)
    await bot.add_cog(github_cog)
    
    # Explicitly register commands to the tree
    commands_to_register = [
        github_cog.track_repo,
        github_cog.untrack_repo,
        github_cog.list_repos,
        github_cog.subscribe_repo
    ]
    
    for command in commands_to_register:
        if command not in bot.tree.get_commands():
            bot.tree.add_command(command)
            logger.info(f"Registered GitHub command: {command.name}")
    
    logger.info(f"🐙 Successfully loaded GitHub Integrations cog with {len(github_cog.get_app_commands())} commands")
    logger.info(f"GitHub commands registered: {[cmd.name for cmd in commands_to_register]}")
