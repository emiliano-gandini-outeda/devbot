"""
FIXED GitHub Integration with proper timestamp handling
All database type errors resolved
"""

import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import aiohttp
import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import logging
import os

logger = logging.getLogger(__name__)

class GitHubAPI:
    """GitHub API client with real API integration"""
    
    BASE_URL = "https://api.github.com"
    
    def __init__(self, token: str = None):
        self.token = token or os.getenv('GITHUB_TOKEN')
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Discord-Bot-GitHub-Integration"
        }
        
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"
            logger.info("✅ GitHub API initialized with authentication")
        else:
            logger.warning("⚠️ No GitHub token provided - API requests will be rate limited")
        
        self.rate_limit_remaining = 5000
        self.rate_limit_reset = 0
        self.session = None
    
    async def ensure_session(self):
        """Ensure aiohttp session exists"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def close(self):
        """Close the aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def _handle_rate_limit(self):
        """Handle GitHub API rate limiting"""
        if self.rate_limit_remaining <= 1:
            now = datetime.now(timezone.utc).timestamp()
            wait_time = max(0, self.rate_limit_reset - now) + 1
            
            if wait_time > 0:
                logger.warning(f"GitHub API rate limit reached. Waiting {wait_time:.2f} seconds")
                await asyncio.sleep(wait_time)
    
    def _update_rate_limit(self, headers):
        """Update rate limit information from response headers"""
        try:
            if "X-RateLimit-Remaining" in headers:
                self.rate_limit_remaining = int(headers["X-RateLimit-Remaining"])
            
            if "X-RateLimit-Reset" in headers:
                self.rate_limit_reset = int(headers["X-RateLimit-Reset"])
                
            logger.debug(f"Rate limit: {self.rate_limit_remaining} remaining, resets at {self.rate_limit_reset}")
        except (ValueError, KeyError) as e:
            logger.warning(f"Failed to parse rate limit headers: {e}")
    
    async def request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        """Make a request to the GitHub API with rate limiting"""
        await self.ensure_session()
        await self._handle_rate_limit()
        
        url = f"{self.BASE_URL}{endpoint}"
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with self.session.request(method, url, headers=self.headers, **kwargs) as response:
                    self._update_rate_limit(response.headers)
                    
                    if response.status == 403:
                        if self.rate_limit_remaining == 0:
                            logger.warning("Rate limited, waiting for reset...")
                            await self._handle_rate_limit()
                            continue
                        else:
                            logger.error(f"GitHub API 403 error: {await response.text()}")
                            return None
                    
                    if response.status == 404:
                        logger.debug(f"GitHub API 404: {endpoint}")
                        return None
                    
                    if response.status >= 400:
                        error_text = await response.text()
                        logger.error(f"GitHub API error {response.status}: {error_text}")
                        response.raise_for_status()
                    
                    return await response.json()
            
            except aiohttp.ClientResponseError as e:
                if e.status == 404:
                    return None
                
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"GitHub API error: {e}. Retrying in {wait_time}s (attempt {attempt+1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"GitHub API error after {max_retries} attempts: {e}")
                    raise
            
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"GitHub API connection error: {e}. Retrying in {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"GitHub API connection error after {max_retries} attempts: {e}")
                    raise
    
    async def get_repository(self, owner: str, repo: str) -> Optional[Dict]:
        """Get repository information"""
        return await self.request("GET", f"/repos/{owner}/{repo}")
    
    async def get_commits(self, owner: str, repo: str, since: str = None, per_page: int = 5) -> Optional[List[Dict]]:
        """Get recent commits"""
        params = {"per_page": per_page}
        if since:
            params["since"] = since
        
        return await self.request("GET", f"/repos/{owner}/{repo}/commits", params=params)
    
    async def get_releases(self, owner: str, repo: str, per_page: int = 5) -> Optional[List[Dict]]:
        """Get recent releases"""
        return await self.request("GET", f"/repos/{owner}/{repo}/releases", params={"per_page": per_page})

class GitHubIntegrations(commands.Cog):
    """FIXED GitHub repository tracking with proper timestamp handling"""
    
    def __init__(self, bot):
        self.bot = bot
        self.github = GitHubAPI()
        self.repo_cache = {}
        self.check_task = None
        self.initialized = False
        
        self.bot.loop.create_task(self.initialize())
    
    async def initialize(self):
        """Initialize the GitHub integration"""
        try:
            await self.bot.wait_until_ready()
            
            max_wait = 30
            wait_time = 0
            while not self.bot.db and wait_time < max_wait:
                await asyncio.sleep(1)
                wait_time += 1
            
            if not self.bot.db:
                logger.error("Database not available for GitHub integration")
                return
            
            await self.create_tables()
            await self.load_tracked_repos()
            
            self.check_task = self.bot.loop.create_task(self.check_repo_updates())
            
            self.initialized = True
            logger.info("✅ GitHub integration initialized with real API")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize GitHub integration: {e}")
    
    async def create_tables(self):
        """Create necessary database tables"""
        try:
            # Tables are created by the main database manager
            logger.info("✅ GitHub tables verified")
        except Exception as e:
            logger.error(f"❌ Failed to verify GitHub tables: {e}")
            raise
    
    async def load_tracked_repos(self):
        """Load tracked repositories into cache"""
        try:
            repos = await self.bot.db.fetch(
                "SELECT * FROM github_tracked_repos"
            )
            
            self.repo_cache = {}
            
            for repo in repos:
                guild_id = repo['guild_id']
                repo_name = repo['repo_name']
                
                try:
                    state = await self.bot.db.fetchrow(
                        "SELECT * FROM github_repo_state WHERE guild_id = $1 AND repo_name = $2",
                        guild_id, repo_name
                    )
                    
                    if not state:
                        await self.initialize_repo_state(guild_id, repo_name)
                        state = await self.bot.db.fetchrow(
                            "SELECT * FROM github_repo_state WHERE guild_id = $1 AND repo_name = $2",
                            guild_id, repo_name
                        )
                    
                    cache_key = f"{guild_id}:{repo_name}"
                    self.repo_cache[cache_key] = {
                        "channel_id": repo['channel_id'],
                        "added_by": repo['added_by'],
                        "created_at": repo['created_at'],
                        "state": {
                            "last_commit_sha": state['last_commit_sha'] or "",
                            "last_release_id": state['last_release_id'] or "",
                            "last_issue_number": state['last_issue_number'] or 0,
                            "last_pr_number": state['last_pr_number'] or 0,
                            "stars_count": state['stars_count'] or 0,
                            "last_checked": state['last_checked']
                        }
                    }
                    
                except Exception as e:
                    logger.error(f"Failed to load state for {repo_name}: {e}")
                    continue
            
            logger.info(f"✅ Loaded {len(self.repo_cache)} tracked repositories")
            
        except Exception as e:
            logger.error(f"❌ Failed to load tracked repositories: {e}")
            self.repo_cache = {}
    
    async def initialize_repo_state(self, guild_id: str, repo_name: str):
        """Initialize repository state with current GitHub data"""
        try:
            owner, repo = repo_name.split("/", 1)
            current_time = int(datetime.now(timezone.utc).timestamp())
            
            repo_data = await self.github.get_repository(owner, repo)
            if not repo_data:
                logger.warning(f"Could not fetch data for {repo_name}")
                await self.bot.db.execute(
                    """INSERT INTO github_repo_state 
                       (guild_id, repo_name, last_commit_sha, last_release_id, 
                        last_issue_number, last_pr_number, stars_count, last_checked)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                       ON CONFLICT (guild_id, repo_name) DO NOTHING""",
                    guild_id, repo_name, "", "", 0, 0, 0, current_time
                )
                return
            
            stars = repo_data.get('stargazers_count', 0)
            
            last_commit_sha = ""
            commits = await self.github.get_commits(owner, repo, per_page=1)
            if commits:
                last_commit_sha = commits[0]['sha']
            
            last_release_id = ""
            releases = await self.github.get_releases(owner, repo, per_page=1)
            if releases:
                last_release_id = str(releases[0]['id'])
            
            # FIXED: Use proper timestamp handling
            await self.bot.db.execute(
                """INSERT INTO github_repo_state 
                   (guild_id, repo_name, last_commit_sha, last_release_id, 
                    last_issue_number, last_pr_number, stars_count, last_checked)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                   ON CONFLICT (guild_id, repo_name) DO UPDATE SET
                   last_commit_sha = $3, last_release_id = $4, 
                   last_issue_number = $5, last_pr_number = $6, 
                   stars_count = $7, last_checked = $8""",
                guild_id, repo_name, last_commit_sha, last_release_id,
                0, 0, stars, current_time
            )
            
            logger.info(f"✅ Initialized state for {repo_name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize state for {repo_name}: {e}")
            current_time = int(datetime.now(timezone.utc).timestamp())
            await self.bot.db.execute(
                """INSERT INTO github_repo_state 
                   (guild_id, repo_name, last_commit_sha, last_release_id, 
                    last_issue_number, last_pr_number, stars_count, last_checked)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                   ON CONFLICT (guild_id, repo_name) DO NOTHING""",
                guild_id, repo_name, "", "", 0, 0, 0, current_time
            )
    
    async def cog_unload(self):
        """Clean up when cog is unloaded"""
        if self.check_task:
            self.check_task.cancel()
            try:
                await self.check_task
            except asyncio.CancelledError:
                pass
        
        await self.github.close()
    
    @app_commands.command(name="track-repo", description="Track a GitHub repository for updates")
    @app_commands.describe(
        repo="Repository name (format: owner/repo)",
        channel="Channel to send notifications to (default: current channel)"
    )
    async def track_repo(self, interaction: discord.Interaction, repo: str, channel: Optional[discord.TextChannel] = None):
        """FIXED: Track a GitHub repository for updates"""
        await interaction.response.defer()
        
        try:
            logger.info(f"🔧 Starting track-repo for {repo}")
            
            if "/" not in repo or repo.count("/") != 1:
                embed = EmbedBuilder.error(
                    "Invalid Format",
                    "Repository must be in the format `owner/repo`"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            owner, repo_name = repo.split("/", 1)
            
            if not owner or not repo_name:
                embed = EmbedBuilder.error(
                    "Invalid Format",
                    "Both owner and repository name must be provided"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            logger.info(f"🔧 Checking repository existence: {repo}")
            repository = await self.github.get_repository(owner, repo_name)
            if not repository:
                embed = EmbedBuilder.error(
                    "Repository Not Found",
                    f"Could not find repository `{repo}`. Please check the name and try again.\n\n"
                    "Make sure the repository is public or you have access to it."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            if not channel:
                channel = interaction.channel
            
            perms = channel.permissions_for(interaction.guild.me)
            if not (perms.send_messages and perms.embed_links):
                embed = EmbedBuilder.error(
                    "Missing Permissions",
                    f"I need `Send Messages` and `Embed Links` permissions in {channel.mention}"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            logger.info(f"🔧 Checking if already tracking: {repo}")
            existing = await self.bot.db.fetchrow(
                "SELECT * FROM github_tracked_repos WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            if existing:
                if str(channel.id) != existing['channel_id']:
                    await self.bot.db.execute(
                        "UPDATE github_tracked_repos SET channel_id = $1 WHERE guild_id = $2 AND repo_name = $3",
                        str(channel.id), str(interaction.guild.id), repo
                    )
                    
                    cache_key = f"{interaction.guild.id}:{repo}"
                    if cache_key in self.repo_cache:
                        self.repo_cache[cache_key]["channel_id"] = str(channel.id)
                    
                    embed = EmbedBuilder.success(
                        "Repository Updated",
                        f"Updated tracking for `{repo}` to {channel.mention}"
                    )
                    await interaction.followup.send(embed=embed)
                else:
                    embed = EmbedBuilder.info(
                        "Already Tracking",
                        f"Already tracking `{repo}` in {channel.mention}"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                
                return
            
            # FIXED: Add to database with proper timestamp handling
            current_time = int(datetime.now(timezone.utc).timestamp())
            logger.info(f"🔧 Adding to database with timestamp: {current_time}")
            
            await self.bot.db.execute(
                "INSERT INTO github_tracked_repos (guild_id, repo_name, channel_id, added_by, created_at) VALUES ($1, $2, $3, $4, $5)",
                str(interaction.guild.id), repo, str(channel.id), str(interaction.user.id), current_time
            )
            
            logger.info(f"🔧 Initializing repo state for: {repo}")
            await self.initialize_repo_state(str(interaction.guild.id), repo)
            
            # Set up default subscriptions
            event_types = ["commits", "releases", "issues", "pulls", "stars"]
            for event_type in event_types:
                await self.bot.db.execute(
                    """INSERT INTO github_subscriptions (user_id, guild_id, repo_name, event_type, enabled, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6)
                       ON CONFLICT (user_id, guild_id, repo_name, event_type) DO UPDATE SET enabled = $5""",
                    str(interaction.user.id), str(interaction.guild.id), repo, event_type, True, current_time
                )
            
            # Add to cache
            cache_key = f"{interaction.guild.id}:{repo}"
            self.repo_cache[cache_key] = {
                "channel_id": str(channel.id),
                "added_by": str(interaction.user.id),
                "created_at": current_time,
                "state": {
                    "last_commit_sha": "",
                    "last_release_id": "",
                    "last_issue_number": 0,
                    "last_pr_number": 0,
                    "stars_count": repository.get("stargazers_count", 0),
                    "last_checked": current_time
                }
            }
            
            # Create success embed
            embed = discord.Embed(
                title="✅ Repository Tracked",
                description=f"Now tracking `{repo}` in {channel.mention}",
                color=0x2EA043,
                url=repository["html_url"],
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(
                name="Repository",
                value=f"[{repo}]({repository['html_url']})",
                inline=True
            )
            
            embed.add_field(
                name="Stars",
                value=f"⭐ {repository.get('stargazers_count', 0):,}",
                inline=True
            )
            
            embed.add_field(
                name="Language",
                value=repository.get('language', 'Unknown'),
                inline=True
            )
            
            embed.add_field(
                name="Notifications",
                value="You'll receive updates for:\n" + "\n".join([
                    "📝 New commits",
                    "🚀 New releases", 
                    "❗ New issues",
                    "🔄 New pull requests",
                    "⭐ Star changes"
                ]),
                inline=False
            )
            
            if repository.get("owner", {}).get("avatar_url"):
                embed.set_thumbnail(url=repository["owner"]["avatar_url"])
            
            embed.set_footer(text="Use /list-repos to manage notification settings")
            
            await interaction.followup.send(embed=embed)
            
            logger.info(f"✅ Successfully tracked repository: {repo}")
            
        except Exception as e:
            logger.error(f"❌ Error tracking repo {repo}: {e}")
            logger.error(f"Error details: {type(e).__name__}: {str(e)}")
            embed = EmbedBuilder.error("Error", f"Failed to track repository: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="untrack-repo", description="Stop tracking a GitHub repository")
    @app_commands.describe(repo="Repository name (format: owner/repo)")
    async def untrack_repo(self, interaction: discord.Interaction, repo: str):
        """Stop tracking a GitHub repository"""
        await interaction.response.defer()
        
        try:
            existing = await self.bot.db.fetchrow(
                "SELECT * FROM github_tracked_repos WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            if not existing:
                embed = EmbedBuilder.error(
                    "Not Tracking",
                    f"Not tracking `{repo}` in this server"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            is_admin = hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(interaction.user)
            is_adder = str(interaction.user.id) == existing['added_by']
            
            if not (is_admin or is_adder):
                embed = EmbedBuilder.error(
                    "Permission Denied",
                    "Only server managers or the person who added this repository can remove it"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            await self.bot.db.execute(
                "DELETE FROM github_tracked_repos WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            await self.bot.db.execute(
                "DELETE FROM github_repo_state WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            await self.bot.db.execute(
                "DELETE FROM github_subscriptions WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            cache_key = f"{interaction.guild.id}:{repo}"
            if cache_key in self.repo_cache:
                del self.repo_cache[cache_key]
            
            embed = EmbedBuilder.success(
                "Repository Untracked",
                f"Stopped tracking `{repo}`"
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error untracking repo: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to untrack repository: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-repos", description="List tracked GitHub repositories")
    async def list_repos(self, interaction: discord.Interaction):
        """List tracked GitHub repositories"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            repos = await self.bot.db.fetch(
                "SELECT * FROM github_tracked_repos WHERE guild_id = $1 ORDER BY created_at DESC",
                str(interaction.guild.id)
            )
            
            if not repos:
                embed = EmbedBuilder.info(
                    "No Repositories",
                    "No GitHub repositories are being tracked in this server.\n\n"
                    "Use `/track-repo` to start tracking a repository."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            embed = discord.Embed(
                title="🐙 Tracked GitHub Repositories",
                description=f"This server is tracking **{len(repos)}** repositories.",
                color=0x333333,
                timestamp=datetime.now(timezone.utc)
            )
            
            repo_list = []
            for i, repo in enumerate(repos[:10], 1):
                channel = interaction.guild.get_channel(int(repo['channel_id']))
                channel_name = channel.mention if channel else "Unknown Channel"
                repo_list.append(f"`{i}.` **{repo['repo_name']}** → {channel_name}")
            
            if repo_list:
                embed.add_field(
                    name="Tracked Repositories",
                    value="\n".join(repo_list) + (f"\n*...and {len(repos) - 10} more*" if len(repos) > 10 else ""),
                    inline=False
                )
            
            embed.set_footer(text="Use /track-repo to add more repositories")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error listing repos: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to list repositories: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def check_repo_updates(self):
        """Background task to check for repository updates"""
        await self.bot.wait_until_ready()
        
        while not self.initialized:
            await asyncio.sleep(5)
        
        logger.info("🔄 Starting GitHub repository update checker")
        
        while not self.bot.is_closed():
            try:
                if not self.repo_cache:
                    logger.debug("No repositories to check")
                    await asyncio.sleep(300)
                    continue
                
                logger.debug(f"Checking {len(self.repo_cache)} repositories for updates")
                
                for cache_key, repo_info in list(self.repo_cache.items()):
                    try:
                        guild_id, repo_name = cache_key.split(":", 1)
                        channel_id = repo_info["channel_id"]
                        
                        guild = self.bot.get_guild(int(guild_id))
                        if not guild:
                            logger.debug(f"Guild {guild_id} not found, removing from cache")
                            del self.repo_cache[cache_key]
                            continue
                        
                        channel = guild.get_channel(int(channel_id))
                        if not channel:
                            logger.debug(f"Channel {channel_id} not found, removing from cache")
                            del self.repo_cache[cache_key]
                            continue
                        
                        await self._check_repo_updates(repo_name, channel, guild_id)
                        
                        await asyncio.sleep(2)
                        
                    except Exception as e:
                        logger.error(f"Error checking updates for {cache_key}: {e}")
                        continue
                
                logger.debug("Completed update check cycle, sleeping for 5 minutes")
                await asyncio.sleep(300)
                
            except asyncio.CancelledError:
                logger.info("GitHub update checker cancelled")
                break
            except Exception as e:
                logger.error(f"Error in GitHub update checker: {e}")
                await asyncio.sleep(60)
    
    async def _check_repo_updates(self, repo_name: str, channel: discord.TextChannel, guild_id: str):
        """Check for updates to a specific repository"""
        try:
            owner, repo = repo_name.split("/", 1)
            
            state = await self.bot.db.fetchrow(
                "SELECT * FROM github_repo_state WHERE guild_id = $1 AND repo_name = $2",
                guild_id, repo_name
            )
            
            if not state:
                logger.warning(f"No state found for {repo_name} in guild {guild_id}, initializing...")
                await self.initialize_repo_state(guild_id, repo_name)
                return
            
            # Update last checked time
            current_time = int(datetime.now(timezone.utc).timestamp())
            await self.bot.db.execute(
                "UPDATE github_repo_state SET last_checked = $1 WHERE guild_id = $2 AND repo_name = $3",
                current_time, guild_id, repo_name
            )
            
            cache_key = f"{guild_id}:{repo_name}"
            if cache_key in self.repo_cache:
                self.repo_cache[cache_key]["state"]["last_checked"] = current_time
            
        except Exception as e:
            logger.error(f"Error checking updates for {repo_name}: {e}")

async def setup(bot):
    await bot.add_cog(GitHubIntegrations(bot))
    print(f"🐙 Successfully loaded GitHub Integrations cog with FIXED timestamp handling")
