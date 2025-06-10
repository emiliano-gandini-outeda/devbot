import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import asyncio
import logging
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class GitHubIntegration(commands.Cog):
    """GitHub integration for tracking repositories and receiving notifications"""
    
    def __init__(self, bot):
        self.bot = bot
        self.github_token = self.bot.config.GITHUB_TOKEN if hasattr(self.bot, 'config') else None
        self.check_task = None
        self.headers = {"Authorization": f"token {self.github_token}"} if self.github_token else {}
        self.session = None
        self.is_running = False
        
        # Start background task when cog is loaded
        bot.loop.create_task(self.start_background_task())
    
    async def start_background_task(self):
        """Start the background task for checking GitHub repositories"""
        await self.bot.wait_until_ready()
        
        # Create aiohttp session
        self.session = aiohttp.ClientSession()
        
        # Start background task
        if not self.check_task:
            self.check_task = self.bot.loop.create_task(self.check_repositories_task())
            logger.info("Started GitHub repository check task")
    
    async def cog_unload(self):
        """Clean up when cog is unloaded"""
        if self.check_task:
            self.check_task.cancel()
        
        if self.session:
            await self.session.close()
    
    @app_commands.command(name="github-setup", description="Set up GitHub integration for this server")
    @app_commands.checks.has_permissions(administrator=True)
    async def github_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set up GitHub integration for this server"""
        if not self.bot.db:
            await interaction.response.send_message("❌ Database connection is not available.", ephemeral=True)
            return
        
        try:
            # Check if GitHub integration is already set up
            if self.bot.db.is_postgresql:
                query = "SELECT * FROM github_channels WHERE guild_id = $1"
                params = [str(interaction.guild_id)]
            else:
                query = "SELECT * FROM github_channels WHERE guild_id = ?"
                params = (str(interaction.guild_id),)
            
            existing = await self.bot.db.execute_query(query, params, fetch_type='one')
            
            if existing:
                # Update existing configuration
                if self.bot.db.is_postgresql:
                    query = "UPDATE github_channels SET channel_id = $1 WHERE guild_id = $2"
                    params = [str(channel.id), str(interaction.guild_id)]
                else:
                    query = "UPDATE github_channels SET channel_id = ? WHERE guild_id = ?"
                    params = (str(channel.id), str(interaction.guild_id))
                
                await self.bot.db.execute_query(query, params)
                
                await interaction.response.send_message(
                    f"✅ GitHub integration updated! Notifications will now be sent to {channel.mention}",
                    ephemeral=True
                )
            else:
                # Create new configuration
                if self.bot.db.is_postgresql:
                    query = "INSERT INTO github_channels (guild_id, channel_id) VALUES ($1, $2)"
                    params = [str(interaction.guild_id), str(channel.id)]
                else:
                    query = "INSERT INTO github_channels (guild_id, channel_id) VALUES (?, ?)"
                    params = (str(interaction.guild_id), str(channel.id))
                
                await self.bot.db.execute_query(query, params)
                
                await interaction.response.send_message(
                    f"✅ GitHub integration set up! Notifications will be sent to {channel.mention}\n\n"
                    f"Use `/github-track <repo_url>` to start tracking repositories.",
                    ephemeral=True
                )
        except Exception as e:
            logger.error(f"Error setting up GitHub integration: {e}")
            await interaction.response.send_message(
                f"❌ An error occurred: {str(e)}",
                ephemeral=True
            )
    
    @app_commands.command(name="github-track", description="Track a GitHub repository")
    @app_commands.describe(repo_url="GitHub repository URL (e.g., https://github.com/username/repo)")
    async def github_track(self, interaction: discord.Interaction, repo_url: str):
        """Track a GitHub repository"""
        if not self.bot.db:
            await interaction.response.send_message("❌ Database connection is not available.", ephemeral=True)
            return
        
        # Validate repository URL
        repo_pattern = r"https?://github\.com/([^/]+)/([^/]+)"
        match = re.match(repo_pattern, repo_url)
        
        if not match:
            await interaction.response.send_message(
                "❌ Invalid GitHub repository URL. Please use the format: https://github.com/username/repo",
                ephemeral=True
            )
            return
        
        owner, repo = match.groups()
        repo_url = f"https://github.com/{owner}/{repo}"
        
        try:
            # Check if GitHub integration is set up
            if self.bot.db.is_postgresql:
                query = "SELECT * FROM github_channels WHERE guild_id = $1"
                params = [str(interaction.guild_id)]
            else:
                query = "SELECT * FROM github_channels WHERE guild_id = ?"
                params = (str(interaction.guild_id),)
            
            channel_config = await self.bot.db.execute_query(query, params, fetch_type='one')
            
            if not channel_config:
                await interaction.response.send_message(
                    "❌ GitHub integration is not set up for this server. Please use `/github-setup` first.",
                    ephemeral=True
                )
                return
            
            # Check if repository exists
            if self.session:
                api_url = f"https://api.github.com/repos/{owner}/{repo}"
                async with self.session.get(api_url, headers=self.headers) as response:
                    if response.status != 200:
                        await interaction.response.send_message(
                            f"❌ Repository not found or not accessible: {repo_url}",
                            ephemeral=True
                        )
                        return
                    
                    repo_data = await response.json()
            
            # Check if repository is already tracked
            if self.bot.db.is_postgresql:
                query = "SELECT * FROM github_repos WHERE guild_id = $1 AND repo_url = $2"
                params = [str(interaction.guild_id), repo_url]
            else:
                query = "SELECT * FROM github_repos WHERE guild_id = ? AND repo_url = ?"
                params = (str(interaction.guild_id), repo_url)
            
            existing = await self.bot.db.execute_query(query, params, fetch_type='one')
            
            if existing:
                await interaction.response.send_message(
                    f"❌ Repository {repo_url} is already being tracked.",
                    ephemeral=True
                )
                return
            
            # Add repository to tracking list
            if self.bot.db.is_postgresql:
                query = "INSERT INTO github_repos (guild_id, repo_url) VALUES ($1, $2)"
                params = [str(interaction.guild_id), repo_url]
            else:
                query = "INSERT INTO github_repos (guild_id, repo_url) VALUES (?, ?)"
                params = (str(interaction.guild_id), repo_url)
            
            await self.bot.db.execute_query(query, params)
            
            # Add initial stats
            if self.session and repo_data:
                if self.bot.db.is_postgresql:
                    query = """
                    INSERT INTO github_repo_stats (repo_url, stars, forks, issues, last_updated)
                    VALUES ($1, $2, $3, $4, NOW())
                    ON CONFLICT (repo_url) DO UPDATE
                    SET stars = $2, forks = $3, issues = $4, last_updated = NOW()
                    """
                    params = [
                        repo_url,
                        repo_data.get('stargazers_count', 0),
                        repo_data.get('forks_count', 0),
                        repo_data.get('open_issues_count', 0)
                    ]
                else:
                    query = """
                    INSERT OR REPLACE INTO github_repo_stats (repo_url, stars, forks, issues, last_updated)
                    VALUES (?, ?, ?, ?, datetime('now'))
                    """
                    params = (
                        repo_url,
                        repo_data.get('stargazers_count', 0),
                        repo_data.get('forks_count', 0),
                        repo_data.get('open_issues_count', 0)
                    )
                
                await self.bot.db.execute_query(query, params)
            
            await interaction.response.send_message(
                f"✅ Now tracking repository: {repo_url}\n\n"
                f"You'll receive notifications about new issues, pull requests, and releases.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error tracking GitHub repository: {e}")
            await interaction.response.send_message(
                f"❌ An error occurred: {str(e)}",
                ephemeral=True
            )
    
    @app_commands.command(name="github-untrack", description="Stop tracking a GitHub repository")
    @app_commands.describe(repo_url="GitHub repository URL to stop tracking")
    async def github_untrack(self, interaction: discord.Interaction, repo_url: str):
        """Stop tracking a GitHub repository"""
        if not self.bot.db:
            await interaction.response.send_message("❌ Database connection is not available.", ephemeral=True)
            return
        
        try:
            # Validate repository URL
            repo_pattern = r"https?://github\.com/([^/]+)/([^/]+)"
            match = re.match(repo_pattern, repo_url)
            
            if match:
                owner, repo = match.groups()
                repo_url = f"https://github.com/{owner}/{repo}"
            
            # Remove repository from tracking list
            if self.bot.db.is_postgresql:
                query = "DELETE FROM github_repos WHERE guild_id = $1 AND repo_url = $2"
                params = [str(interaction.guild_id), repo_url]
            else:
                query = "DELETE FROM github_repos WHERE guild_id = ? AND repo_url = ?"
                params = (str(interaction.guild_id), repo_url)
            
            result = await self.bot.db.execute_query(query, params)
            
            # Check if any rows were affected
            if self.bot.db.is_postgresql:
                if result == "DELETE 0":
                    await interaction.response.send_message(
                        f"❌ Repository {repo_url} is not being tracked.",
                        ephemeral=True
                    )
                    return
            else:
                # For SQLite, we need to check differently
                if self.bot.db.is_postgresql:
                    query = "SELECT COUNT(*) FROM github_repos WHERE guild_id = $1 AND repo_url = $2"
                    params = [str(interaction.guild_id), repo_url]
                else:
                    query = "SELECT COUNT(*) FROM github_repos WHERE guild_id = ? AND repo_url = ?"
                    params = (str(interaction.guild_id), repo_url)
                
                count = await self.bot.db.execute_query(query, params, fetch_type='val')
                if count > 0:
                    await interaction.response.send_message(
                        f"❌ Failed to remove repository {repo_url} from tracking.",
                        ephemeral=True
                    )
                    return
            
            await interaction.response.send_message(
                f"✅ Stopped tracking repository: {repo_url}",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error untracking GitHub repository: {e}")
            await interaction.response.send_message(
                f"❌ An error occurred: {str(e)}",
                ephemeral=True
            )
    
    @app_commands.command(name="github-list", description="List tracked GitHub repositories")
    async def github_list(self, interaction: discord.Interaction):
        """List tracked GitHub repositories"""
        if not self.bot.db:
            await interaction.response.send_message("❌ Database connection is not available.", ephemeral=True)
            return
        
        try:
            # Get tracked repositories
            if self.bot.db.is_postgresql:
                query = "SELECT * FROM github_repos WHERE guild_id = $1"
                params = [str(interaction.guild_id)]
            else:
                query = "SELECT * FROM github_repos WHERE guild_id = ?"
                params = (str(interaction.guild_id),)
            
            repos = await self.bot.db.execute_query(query, params, fetch_type='all')
            
            if not repos:
                await interaction.response.send_message(
                    "❌ No GitHub repositories are being tracked in this server.",
                    ephemeral=True
                )
                return
            
            # Create embed
            embed = discord.Embed(
                title="📋 Tracked GitHub Repositories",
                description=f"This server is tracking {len(repos)} GitHub repositories.",
                color=0x2F3136
            )
            
            for i, repo in enumerate(repos, 1):
                repo_url = repo.get('repo_url') if isinstance(repo, dict) else repo[2]
                
                # Get repository stats if available
                if self.bot.db.is_postgresql:
                    query = "SELECT * FROM github_repo_stats WHERE repo_url = $1"
                    params = [repo_url]
                else:
                    query = "SELECT * FROM github_repo_stats WHERE repo_url = ?"
                    params = (repo_url,)
                
                stats = await self.bot.db.execute_query(query, params, fetch_type='one')
                
                if stats:
                    stars = stats.get('stars', 0) if isinstance(stats, dict) else stats[2]
                    forks = stats.get('forks', 0) if isinstance(stats, dict) else stats[3]
                    issues = stats.get('issues', 0) if isinstance(stats, dict) else stats[4]
                    
                    embed.add_field(
                        name=f"{i}. {repo_url}",
                        value=f"⭐ Stars: {stars} | 🍴 Forks: {forks} | ❗ Issues: {issues}",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name=f"{i}. {repo_url}",
                        value="No stats available",
                        inline=False
                    )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error listing GitHub repositories: {e}")
            await interaction.response.send_message(
                f"❌ An error occurred: {str(e)}",
                ephemeral=True
            )
    
    async def check_repositories_task(self):
        """Background task to check for repository updates"""
        try:
            self.is_running = True
            logger.info("Starting GitHub repository check task")
            
            while not self.bot.is_closed():
                try:
                    if not self.bot.db or not self.session:
                        await asyncio.sleep(60)
                        continue
                    
                    # Get all tracked repositories
                    if self.bot.db.is_postgresql:
                        query = """
                        SELECT gr.guild_id, gr.repo_url, gc.channel_id
                        FROM github_repos gr
                        JOIN github_channels gc ON gr.guild_id = gc.guild_id
                        """
                    else:
                        query = """
                        SELECT gr.guild_id, gr.repo_url, gc.channel_id
                        FROM github_repos gr
                        JOIN github_channels gc ON gr.guild_id = gc.guild_id
                        """
                    
                    repos = await self.bot.db.execute_query(query, fetch_type='all')
                    
                    if not repos:
                        await asyncio.sleep(300)  # Sleep for 5 minutes if no repos
                        continue
                    
                    for repo_data in repos:
                        guild_id = repo_data.get('guild_id') if isinstance(repo_data, dict) else repo_data[0]
                        repo_url = repo_data.get('repo_url') if isinstance(repo_data, dict) else repo_data[1]
                        channel_id = repo_data.get('channel_id') if isinstance(repo_data, dict) else repo_data[2]
                        
                        # Extract owner and repo name
                        repo_pattern = r"https?://github\.com/([^/]+)/([^/]+)"
                        match = re.match(repo_pattern, repo_url)
                        
                        if not match:
                            continue
                        
                        owner, repo = match.groups()
                        
                        # Check repository stats
                        await self.check_repository_updates(guild_id, channel_id, owner, repo, repo_url)
                        
                        # Sleep briefly between repositories to avoid rate limiting
                        await asyncio.sleep(2)
                    
                    # Sleep for 10 minutes before next check
                    await asyncio.sleep(600)
                    
                except asyncio.CancelledError:
                    logger.info("GitHub repository check task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in GitHub repository check task: {e}")
                    await asyncio.sleep(300)  # Sleep for 5 minutes on error
        
        finally:
            self.is_running = False
            logger.info("GitHub repository check task ended")
    
    async def check_repository_updates(self, guild_id, channel_id, owner, repo, repo_url):
        """Check for updates to a specific repository"""
        try:
            # Get channel
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return
            
            # Get current stats
            api_url = f"https://api.github.com/repos/{owner}/{repo}"
            async with self.session.get(api_url, headers=self.headers) as response:
                if response.status != 200:
                    return
                
                repo_data = await response.json()
            
            # Get previous stats
            if self.bot.db.is_postgresql:
                query = "SELECT * FROM github_repo_stats WHERE repo_url = $1"
                params = [repo_url]
            else:
                query = "SELECT * FROM github_repo_stats WHERE repo_url = ?"
                params = (repo_url,)
            
            prev_stats = await self.bot.db.execute_query(query, params, fetch_type='one')
            
            # If no previous stats, just save current stats
            if not prev_stats:
                if self.bot.db.is_postgresql:
                    query = """
                    INSERT INTO github_repo_stats (repo_url, stars, forks, issues, last_updated)
                    VALUES ($1, $2, $3, $4, NOW())
                    """
                    params = [
                        repo_url,
                        repo_data.get('stargazers_count', 0),
                        repo_data.get('forks_count', 0),
                        repo_data.get('open_issues_count', 0)
                    ]
                else:
                    query = """
                    INSERT INTO github_repo_stats (repo_url, stars, forks, issues, last_updated)
                    VALUES (?, ?, ?, ?, datetime('now'))
                    """
                    params = (
                        repo_url,
                        repo_data.get('stargazers_count', 0),
                        repo_data.get('forks_count', 0),
                        repo_data.get('open_issues_count', 0)
                    )
                
                await self.bot.db.execute_query(query, params)
                return
            
            # Extract previous stats
            prev_stars = prev_stats.get('stars', 0) if isinstance(prev_stats, dict) else prev_stats[2]
            prev_forks = prev_stats.get('forks', 0) if isinstance(prev_stats, dict) else prev_stats[3]
            prev_issues = prev_stats.get('issues', 0) if isinstance(prev_stats, dict) else prev_stats[4]
            
            # Current stats
            curr_stars = repo_data.get('stargazers_count', 0)
            curr_forks = repo_data.get('forks_count', 0)
            curr_issues = repo_data.get('open_issues_count', 0)
            
            # Check for significant changes
            changes = []
            
            if curr_stars > prev_stars:
                changes.append(f"⭐ Stars: {prev_stars} → {curr_stars} (+{curr_stars - prev_stars})")
            
            if curr_forks > prev_forks:
                changes.append(f"🍴 Forks: {prev_forks} → {curr_forks} (+{curr_forks - prev_forks})")
            
            if curr_issues != prev_issues:
                if curr_issues > prev_issues:
                    changes.append(f"❗ Issues: {prev_issues} → {curr_issues} (+{curr_issues - prev_issues})")
                else:
                    changes.append(f"❗ Issues: {prev_issues} → {curr_issues} (-{prev_issues - curr_issues})")
            
            # Check for new releases
            async with self.session.get(f"https://api.github.com/repos/{owner}/{repo}/releases/latest", headers=self.headers) as response:
                if response.status == 200:
                    release_data = await response.json()
                    release_date = datetime.strptime(release_data.get('published_at'), "%Y-%m-%dT%H:%M:%SZ")
                    
                    # If release is newer than last update
                    last_updated = prev_stats.get('last_updated') if isinstance(prev_stats, dict) else prev_stats[5]
                    
                    if isinstance(last_updated, str):
                        try:
                            last_updated = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            last_updated = datetime.strptime(last_updated, "%Y-%m-%dT%H:%M:%S")
                    
                    if release_date > last_updated:
                        changes.append(f"🚀 New release: [{release_data.get('tag_name')}]({release_data.get('html_url')})")
            
            # Send notification if there are changes
            if changes:
                embed = discord.Embed(
                    title=f"📊 GitHub Repository Update: {owner}/{repo}",
                    url=repo_url,
                    description="\n".join(changes),
                    color=0x2F3136,
                    timestamp=datetime.utcnow()
                )
                
                embed.set_footer(text=f"GitHub Integration | {owner}/{repo}")
                
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    logger.warning(f"Missing permissions to send messages in channel {channel.id}")
                except discord.HTTPException as e:
                    logger.error(f"Error sending GitHub update notification: {e}")
            
            # Update stats in database
            if self.bot.db.is_postgresql:
                query = """
                UPDATE github_repo_stats
                SET stars = $1, forks = $2, issues = $3, last_updated = NOW()
                WHERE repo_url = $4
                """
                params = [curr_stars, curr_forks, curr_issues, repo_url]
            else:
                query = """
                UPDATE github_repo_stats
                SET stars = ?, forks = ?, issues = ?, last_updated = datetime('now')
                WHERE repo_url = ?
                """
                params = (curr_stars, curr_forks, curr_issues, repo_url)
            
            await self.bot.db.execute_query(query, params)
            
        except Exception as e:
            logger.error(f"Error checking repository updates for {repo_url}: {e}")

async def setup(bot):
    await bot.add_cog(GitHubIntegration(bot))
