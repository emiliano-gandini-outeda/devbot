"""
Enhanced GitHub Integration with Real API Calls
Uses existing GITHUB_TOKEN environment variable for authentication
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
    
    async def get_issues(self, owner: str, repo: str, state: str = "open", since: str = None, per_page: int = 5) -> Optional[List[Dict]]:
        """Get recent issues"""
        params = {"state": state, "per_page": per_page}
        if since:
            params["since"] = since
        
        return await self.request("GET", f"/repos/{owner}/{repo}/issues", params=params)
    
    async def get_pulls(self, owner: str, repo: str, state: str = "open", per_page: int = 5) -> Optional[List[Dict]]:
        """Get recent pull requests"""
        params = {"state": state, "per_page": per_page}
        return await self.request("GET", f"/repos/{owner}/{repo}/pulls", params=params)

class GitHubIntegrations(commands.Cog):
    """Enhanced GitHub repository tracking with real API integration"""
    
    def __init__(self, bot):
        self.bot = bot
        self.github = GitHubAPI()
        self.repo_cache = {}
        self.check_task = None
        self.initialized = False
        
        # Initialize after bot is ready
        self.bot.loop.create_task(self.initialize())
    
    async def initialize(self):
        """Initialize the GitHub integration"""
        try:
            await self.bot.wait_until_ready()
            
            # Wait for database to be ready
            max_wait = 30
            wait_time = 0
            while not self.bot.db and wait_time < max_wait:
                await asyncio.sleep(1)
                wait_time += 1
            
            if not self.bot.db:
                logger.error("Database not available for GitHub integration")
                return
            
            # Create necessary tables
            await self.create_tables()
            
            # Load tracked repositories
            await self.load_tracked_repos()
            
            # Start background task
            self.check_task = self.bot.loop.create_task(self.check_repo_updates())
            
            self.initialized = True
            logger.info("✅ GitHub integration initialized with real API")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize GitHub integration: {e}")
    
    async def create_tables(self):
        """Create necessary database tables"""
        try:
            # GitHub tracked repositories table
            await self.bot.db.connection.execute("""
                CREATE TABLE IF NOT EXISTS github_tracked_repos (
                    id SERIAL PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    repo_name TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    added_by TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    UNIQUE(guild_id, repo_name)
                )
            """)
            
            # GitHub repository state table
            await self.bot.db.connection.execute("""
                CREATE TABLE IF NOT EXISTS github_repo_state (
                    id SERIAL PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    repo_name TEXT NOT NULL,
                    last_commit_sha TEXT,
                    last_release_id TEXT,
                    last_issue_number INTEGER DEFAULT 0,
                    last_pr_number INTEGER DEFAULT 0,
                    stars_count INTEGER DEFAULT 0,
                    last_checked INTEGER NOT NULL,
                    UNIQUE(guild_id, repo_name)
                )
            """)
            
            # GitHub user subscriptions table
            await self.bot.db.connection.execute("""
                CREATE TABLE IF NOT EXISTS github_subscriptions (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    repo_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT TRUE,
                    created_at INTEGER NOT NULL,
                    UNIQUE(user_id, guild_id, repo_name, event_type)
                )
            """)
            
            logger.info("✅ GitHub tables created/verified")
        except Exception as e:
            logger.error(f"❌ Failed to create GitHub tables: {e}")
            raise
    
    async def load_tracked_repos(self):
        """Load tracked repositories into cache"""
        try:
            repos = await self.bot.db.connection.fetch(
                "SELECT * FROM github_tracked_repos"
            )
            
            self.repo_cache = {}
            
            for repo in repos:
                guild_id = repo['guild_id']
                repo_name = repo['repo_name']
                
                try:
                    # Get repo state
                    state = await self.bot.db.connection.fetchrow(
                        "SELECT * FROM github_repo_state WHERE guild_id = $1 AND repo_name = $2",
                        guild_id, repo_name
                    )
                    
                    if not state:
                        # Initialize state if it doesn't exist
                        await self.initialize_repo_state(guild_id, repo_name)
                        state = await self.bot.db.connection.fetchrow(
                            "SELECT * FROM github_repo_state WHERE guild_id = $1 AND repo_name = $2",
                            guild_id, repo_name
                        )
                    
                    # Add to cache
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
            
            # Get current repository data
            repo_data = await self.github.get_repository(owner, repo)
            if not repo_data:
                logger.warning(f"Could not fetch data for {repo_name}")
                # Initialize with empty state
                await self.bot.db.connection.execute(
                    """INSERT INTO github_repo_state 
                       (guild_id, repo_name, last_commit_sha, last_release_id, 
                        last_issue_number, last_pr_number, stars_count, last_checked)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                       ON CONFLICT (guild_id, repo_name) DO NOTHING""",
                    guild_id, repo_name, "", "", 0, 0, 0, current_time
                )
                return
            
            # Get initial data
            stars = repo_data.get('stargazers_count', 0)
            
            # Get latest commit
            last_commit_sha = ""
            commits = await self.github.get_commits(owner, repo, per_page=1)
            if commits:
                last_commit_sha = commits[0]['sha']
            
            # Get latest release
            last_release_id = ""
            releases = await self.github.get_releases(owner, repo, per_page=1)
            if releases:
                last_release_id = str(releases[0]['id'])
            
            # Get latest issue number
            last_issue_number = 0
            issues = await self.github.get_issues(owner, repo, per_page=1)
            if issues:
                actual_issues = [issue for issue in issues if 'pull_request' not in issue]
                if actual_issues:
                    last_issue_number = actual_issues[0]['number']
            
            # Get latest PR number
            last_pr_number = 0
            pulls = await self.github.get_pulls(owner, repo, per_page=1)
            if pulls:
                last_pr_number = pulls[0]['number']
            
            # Save initial state
            await self.bot.db.connection.execute(
                """INSERT INTO github_repo_state 
                   (guild_id, repo_name, last_commit_sha, last_release_id, 
                    last_issue_number, last_pr_number, stars_count, last_checked)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                   ON CONFLICT (guild_id, repo_name) DO UPDATE SET
                   last_commit_sha = $3, last_release_id = $4, 
                   last_issue_number = $5, last_pr_number = $6, 
                   stars_count = $7, last_checked = $8""",
                guild_id, repo_name, last_commit_sha, last_release_id,
                last_issue_number, last_pr_number, stars, current_time
            )
            
            logger.info(f"✅ Initialized state for {repo_name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize state for {repo_name}: {e}")
            # Create minimal state to prevent future errors
            current_time = int(datetime.now(timezone.utc).timestamp())
            await self.bot.db.connection.execute(
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
        """Track a GitHub repository for updates"""
        await interaction.response.defer()
        
        try:
            # Validate repository format
            if "/" not in repo or repo.count("/") != 1:
                embed = EmbedBuilder.error(
                    "Invalid Format",
                    "Repository must be in the format `owner/repo`"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            owner, repo_name = repo.split("/", 1)
            
            # Validate repository name format
            if not owner or not repo_name:
                embed = EmbedBuilder.error(
                    "Invalid Format",
                    "Both owner and repository name must be provided"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Check if repository exists
            repository = await self.github.get_repository(owner, repo_name)
            if not repository:
                embed = EmbedBuilder.error(
                    "Repository Not Found",
                    f"Could not find repository `{repo}`. Please check the name and try again.\n\n"
                    "Make sure the repository is public or you have access to it."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Use current channel if none specified
            if not channel:
                channel = interaction.channel
            
            # Check bot permissions in channel
            perms = channel.permissions_for(interaction.guild.me)
            if not (perms.send_messages and perms.embed_links):
                embed = EmbedBuilder.error(
                    "Missing Permissions",
                    f"I need `Send Messages` and `Embed Links` permissions in {channel.mention}"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Check if already tracking
            existing = await self.bot.db.connection.fetchrow(
                "SELECT * FROM github_tracked_repos WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            if existing:
                # Update channel if different
                if str(channel.id) != existing['channel_id']:
                    await self.bot.db.connection.execute(
                        "UPDATE github_tracked_repos SET channel_id = $1 WHERE guild_id = $2 AND repo_name = $3",
                        str(channel.id), str(interaction.guild.id), repo
                    )
                    
                    # Update cache
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
            
            # Add to database
            current_time = int(datetime.now(timezone.utc).timestamp())
            await self.bot.db.connection.execute(
                "INSERT INTO github_tracked_repos (guild_id, repo_name, channel_id, added_by, created_at) VALUES ($1, $2, $3, $4, $5)",
                str(interaction.guild.id), repo, str(channel.id), str(interaction.user.id), current_time
            )
            
            # Initialize repo state
            await self.initialize_repo_state(str(interaction.guild.id), repo)
            
            # Set up default subscriptions for the user
            event_types = ["commits", "releases", "issues", "pulls", "stars"]
            for event_type in event_types:
                await self.bot.db.connection.execute(
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
                color=0x2EA043,  # GitHub green
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
            
            # Send initial status to the channel
            await self._send_repo_status(repo, channel, repository)
            
        except Exception as e:
            logger.error(f"Error tracking repo: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to track repository: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="untrack-repo", description="Stop tracking a GitHub repository")
    @app_commands.describe(repo="Repository name (format: owner/repo)")
    async def untrack_repo(self, interaction: discord.Interaction, repo: str):
        """Stop tracking a GitHub repository"""
        await interaction.response.defer()
        
        try:
            # Check if tracking
            existing = await self.bot.db.connection.fetchrow(
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
            
            # Check permissions (only admins or the person who added it can remove)
            is_admin = hasattr(self.bot, 'admin_manager') and self.bot.admin_manager and self.bot.admin_manager.is_admin(interaction.user)
            is_adder = str(interaction.user.id) == existing['added_by']
            
            if not (is_admin or is_adder):
                embed = EmbedBuilder.error(
                    "Permission Denied",
                    "Only server managers or the person who added this repository can remove it"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Remove from database
            await self.bot.db.connection.execute(
                "DELETE FROM github_tracked_repos WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            # Remove state
            await self.bot.db.connection.execute(
                "DELETE FROM github_repo_state WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            # Remove subscriptions
            await self.bot.db.connection.execute(
                "DELETE FROM github_subscriptions WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            # Remove from cache
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
        """List tracked GitHub repositories with subscription options"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get tracked repos for this guild
            repos = await self.bot.db.connection.fetch(
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
                color=0x333333,  # GitHub dark
                timestamp=datetime.now(timezone.utc)
            )
            
            # Add a summary of tracked repos
            repo_list = []
            for i, repo in enumerate(repos[:10], 1):  # Show first 10
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
        
        # Wait for initialization to complete
        while not self.initialized:
            await asyncio.sleep(5)
        
        logger.info("🔄 Starting GitHub repository update checker")
        
        while not self.bot.is_closed():
            try:
                if not self.repo_cache:
                    logger.debug("No repositories to check")
                    await asyncio.sleep(300)  # 5 minutes
                    continue
                
                logger.debug(f"Checking {len(self.repo_cache)} repositories for updates")
                
                for cache_key, repo_info in list(self.repo_cache.items()):
                    try:
                        guild_id, repo_name = cache_key.split(":", 1)
                        channel_id = repo_info["channel_id"]
                        
                        # Check if guild and channel still exist
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
                        
                        # Check for updates
                        await self._check_repo_updates(repo_name, channel, guild_id)
                        
                        # Sleep briefly between repos to avoid rate limiting
                        await asyncio.sleep(2)
                        
                    except Exception as e:
                        logger.error(f"Error checking updates for {cache_key}: {e}")
                        continue
                
                # Sleep for 5 minutes between full checks
                logger.debug("Completed update check cycle, sleeping for 5 minutes")
                await asyncio.sleep(300)
                
            except asyncio.CancelledError:
                logger.info("GitHub update checker cancelled")
                break
            except Exception as e:
                logger.error(f"Error in GitHub update checker: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying
    
    async def _check_repo_updates(self, repo_name: str, channel: discord.TextChannel, guild_id: str):
        """Check for updates to a specific repository"""
        try:
            owner, repo = repo_name.split("/", 1)
            cache_key = f"{guild_id}:{repo_name}"
            
            # Get current state from database
            state = await self.bot.db.connection.fetchrow(
                "SELECT * FROM github_repo_state WHERE guild_id = $1 AND repo_name = $2",
                guild_id, repo_name
            )
            
            if not state:
                logger.warning(f"No state found for {repo_name} in guild {guild_id}, initializing...")
                await self.initialize_repo_state(guild_id, repo_name)
                return
            
            # Check for new commits, releases, issues, PRs, and star changes
            await self._check_commits(owner, repo, state, channel, guild_id, repo_name)
            await self._check_releases(owner, repo, state, channel, guild_id, repo_name)
            await self._check_issues(owner, repo, state, channel, guild_id, repo_name)
            await self._check_pulls(owner, repo, state, channel, guild_id, repo_name)
            await self._check_stars(owner, repo, state, channel, guild_id, repo_name)
            
            # Update last checked time
            current_time = int(datetime.now(timezone.utc).timestamp())
            await self.bot.db.connection.execute(
                "UPDATE github_repo_state SET last_checked = $1 WHERE guild_id = $2 AND repo_name = $3",
                current_time, guild_id, repo_name
            )
            
            # Update cache
            if cache_key in self.repo_cache:
                self.repo_cache[cache_key]["state"]["last_checked"] = current_time
            
        except Exception as e:
            logger.error(f"Error checking updates for {repo_name}: {e}")
    
    async def _check_commits(self, owner: str, repo: str, state: dict, channel: discord.TextChannel, guild_id: str, repo_name: str):
        """Check for new commits"""
        try:
            commits = await self.github.get_commits(owner, repo, per_page=5)
            if not commits:
                return
            
            last_commit_sha = state['last_commit_sha']
            
            # If no previous commit, just store the latest
            if not last_commit_sha:
                await self.bot.db.connection.execute(
                    "UPDATE github_repo_state SET last_commit_sha = $1 WHERE guild_id = $2 AND repo_name = $3",
                    commits[0]['sha'], guild_id, repo_name
                )
                return
            
            # Find new commits
            new_commits = []
            for commit in commits:
                if commit['sha'] == last_commit_sha:
                    break
                new_commits.append(commit)
            
            # Update last commit SHA if we have new commits
            if new_commits:
                await self.bot.db.connection.execute(
                    "UPDATE github_repo_state SET last_commit_sha = $1 WHERE guild_id = $2 AND repo_name = $3",
                    new_commits[0]['sha'], guild_id, repo_name
                )
                
                # Send notifications for new commits (limit to 3)
                for commit in new_commits[:3]:
                    await self._send_commit_notification(commit, repo_name, channel, guild_id)
                    await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"Error checking commits for {repo_name}: {e}")
    
    async def _check_releases(self, owner: str, repo: str, state: dict, channel: discord.TextChannel, guild_id: str, repo_name: str):
        """Check for new releases"""
        try:
            releases = await self.github.get_releases(owner, repo, per_page=5)
            if not releases:
                return
            
            last_release_id = state['last_release_id']
            
            # If no previous release, just store the latest
            if not last_release_id:
                await self.bot.db.connection.execute(
                    "UPDATE github_repo_state SET last_release_id = $1 WHERE guild_id = $2 AND repo_name = $3",
                    str(releases[0]['id']), guild_id, repo_name
                )
                return
            
            # Find new releases
            new_releases = []
            for release in releases:
                if str(release['id']) == last_release_id:
                    break
                new_releases.append(release)
            
            # Update last release ID if we have new releases
            if new_releases:
                await self.bot.db.connection.execute(
                    "UPDATE github_repo_state SET last_release_id = $1 WHERE guild_id = $2 AND repo_name = $3",
                    str(new_releases[0]['id']), guild_id, repo_name
                )
                
                # Send notifications for new releases
                for release in new_releases:
                    await self._send_release_notification(release, repo_name, channel, guild_id)
                    await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"Error checking releases for {repo_name}: {e}")
    
    async def _check_issues(self, owner: str, repo: str, state: dict, channel: discord.TextChannel, guild_id: str, repo_name: str):
        """Check for new issues"""
        try:
            issues = await self.github.get_issues(owner, repo, per_page=10)
            if not issues:
                return
            
            # Filter out pull requests
            issues = [issue for issue in issues if 'pull_request' not in issue]
            if not issues:
                return
            
            last_issue_number = state['last_issue_number']
            
            # If no previous issue, just store the latest
            if last_issue_number == 0:
                await self.bot.db.connection.execute(
                    "UPDATE github_repo_state SET last_issue_number = $1 WHERE guild_id = $2 AND repo_name = $3",
                    issues[0]['number'], guild_id, repo_name
                )
                return
            
            # Find new issues
            new_issues = []
            for issue in issues:
                if issue['number'] <= last_issue_number:
                    continue
                new_issues.append(issue)
            
            # Update last issue number if we have new issues
            if new_issues:
                max_issue_number = max(issue['number'] for issue in new_issues)
                await self.bot.db.connection.execute(
                    "UPDATE github_repo_state SET last_issue_number = $1 WHERE guild_id = $2 AND repo_name = $3",
                    max_issue_number, guild_id, repo_name
                )
                
                # Send notifications for new issues (limit to 3)
                for issue in new_issues[:3]:
                    await self._send_issue_notification(issue, repo_name, channel, guild_id)
                    await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"Error checking issues for {repo_name}: {e}")
    
    async def _check_pulls(self, owner: str, repo: str, state: dict, channel: discord.TextChannel, guild_id: str, repo_name: str):
        """Check for new pull requests"""
        try:
            pulls = await self.github.get_pulls(owner, repo, per_page=10)
            if not pulls:
                return
            
            last_pr_number = state['last_pr_number']
            
            # If no previous PR, just store the latest
            if last_pr_number == 0:
                await self.bot.db.connection.execute(
                    "UPDATE github_repo_state SET last_pr_number = $1 WHERE guild_id = $2 AND repo_name = $3",
                    pulls[0]['number'], guild_id, repo_name
                )
                return
            
            # Find new PRs
            new_pulls = []
            for pull in pulls:
                if pull['number'] <= last_pr_number:
                    continue
                new_pulls.append(pull)
            
            # Update last PR number if we have new PRs
            if new_pulls:
                max_pr_number = max(pull['number'] for pull in new_pulls)
                await self.bot.db.connection.execute(
                    "UPDATE github_repo_state SET last_pr_number = $1 WHERE guild_id = $2 AND repo_name = $3",
                    max_pr_number, guild_id, repo_name
                )
                
                # Send notifications for new PRs (limit to 3)
                for pull in new_pulls[:3]:
                    await self._send_pr_notification(pull, repo_name, channel, guild_id)
                    await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"Error checking pull requests for {repo_name}: {e}")
    
    async def _check_stars(self, owner: str, repo: str, state: dict, channel: discord.TextChannel, guild_id: str, repo_name: str):
        """Check for star count changes"""
        try:
            repo_data = await self.github.get_repository(owner, repo)
            if not repo_data:
                return
            
            stars = repo_data.get('stargazers_count', 0)
            old_stars = state['stars_count']
            
            # If significant change in stars, send notification
            if old_stars > 0 and abs(stars - old_stars) >= 5:
                diff = stars - old_stars
                await self._send_stars_notification(repo_name, stars, diff, channel, guild_id)
            
            # Always update star count
            await self.bot.db.connection.execute(
                "UPDATE github_repo_state SET stars_count = $1 WHERE guild_id = $2 AND repo_name = $3",
                stars, guild_id, repo_name
            )
            
        except Exception as e:
            logger.error(f"Error checking stars for {repo_name}: {e}")
    
    async def _send_commit_notification(self, commit: dict, repo_name: str, channel: discord.TextChannel, guild_id: str):
        """Send notification for a new commit"""
        try:
            # Get subscribers for commits
            subscribers = await self._get_subscribers(guild_id, repo_name, "commits")
            if not subscribers:
                return
            
            # Extract commit info
            sha = commit['sha'][:7]
            message = commit['commit']['message'].split('\n')[0]  # First line only
            author = commit['commit']['author']['name']
            url = commit['html_url']
            
            # Truncate long commit messages
            if len(message) > 100:
                message = message[:97] + "..."
            
            # Create embed
            embed = discord.Embed(
                title=f"📝 New Commit to {repo_name}",
                description=f"**{message}**",
                color=0x0366D6,  # GitHub blue
                url=url,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(name="Author", value=author, inline=True)
            embed.add_field(name="Commit", value=f"[{sha}]({url})", inline=True)
            
            # Add avatar if available
            if commit.get('author') and commit['author'] and commit['author'].get('avatar_url'):
                embed.set_thumbnail(url=commit['author']['avatar_url'])
            
            # Add mentions
            mentions = " ".join([f"<@{sub}>" for sub in subscribers])
            
            if mentions:
                await channel.send(mentions, embed=embed)
            else:
                await channel.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error sending commit notification: {e}")
    
    async def _send_release_notification(self, release: dict, repo_name: str, channel: discord.TextChannel, guild_id: str):
        """Send notification for a new release"""
        try:
            # Get subscribers for releases
            subscribers = await self._get_subscribers(guild_id, repo_name, "releases")
            if not subscribers:
                return
            
            # Extract release info
            name = release.get('name') or release['tag_name']
            tag = release['tag_name']
            body = release.get('body', '') or ""
            author = release['author']['login']
            is_prerelease = release.get('prerelease', False)
            url = release['html_url']
            
            # Truncate body if too long
            if len(body) > 500:
                body = body[:497] + "..."
            
            # Create embed
            embed = discord.Embed(
                title=f"🚀 New {'Pre-release' if is_prerelease else 'Release'} for {repo_name}",
                description=f"**{name}**\n\n{body}" if body else f"**{name}**",
                color=0x6F42C1,  # GitHub purple
                url=url,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(name="Tag", value=tag, inline=True)
            embed.add_field(name="Author", value=author, inline=True)
            
            # Add avatar
            if release['author'].get('avatar_url'):
                embed.set_thumbnail(url=release['author']['avatar_url'])
            
            # Add mentions
            mentions = " ".join([f"<@{sub}>" for sub in subscribers])
            
            if mentions:
                await channel.send(mentions, embed=embed)
            else:
                await channel.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error sending release notification: {e}")
    
    async def _send_issue_notification(self, issue: dict, repo_name: str, channel: discord.TextChannel, guild_id: str):
        """Send notification for a new issue"""
        try:
            # Get subscribers for issues
            subscribers = await self._get_subscribers(guild_id, repo_name, "issues")
            if not subscribers:
                return
            
            # Extract issue info
            number = issue['number']
            title = issue['title']
            body = issue.get('body', '') or ""
            author = issue['user']['login']
            url = issue['html_url']
            
            # Truncate body if too long
            if len(body) > 300:
                body = body[:297] + "..."
            
            # Create embed
            embed = discord.Embed(
                title=f"❗ New Issue in {repo_name}",
                description=f"**#{number}: {title}**\n\n{body}" if body else f"**#{number}: {title}**",
                color=0xD73A49,  # GitHub red
                url=url,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(name="Author", value=author, inline=True)
            
            # Add avatar
            if issue['user'].get('avatar_url'):
                embed.set_thumbnail(url=issue['user']['avatar_url'])
            
            # Add mentions
            mentions = " ".join([f"<@{sub}>" for sub in subscribers])
            
            if mentions:
                await channel.send(mentions, embed=embed)
            else:
                await channel.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error sending issue notification: {e}")
    
    async def _send_pr_notification(self, pull: dict, repo_name: str, channel: discord.TextChannel, guild_id: str):
        """Send notification for a new pull request"""
        try:
            # Get subscribers for pull requests
            subscribers = await self._get_subscribers(guild_id, repo_name, "pulls")
            if not subscribers:
                return
            
            # Extract PR info
            number = pull['number']
            title = pull['title']
            body = pull.get('body', '') or ""
            author = pull['user']['login']
            url = pull['html_url']
            
            # Get branch info
            base = pull['base']['ref']
            head = pull['head']['ref']
            
            # Truncate body if too long
            if len(body) > 300:
                body = body[:297] + "..."
            
            # Create embed
            embed = discord.Embed(
                title=f"🔄 New Pull Request in {repo_name}",
                description=f"**#{number}: {title}**\n\n{body}" if body else f"**#{number}: {title}**",
                color=0x28A745,  # GitHub green
                url=url,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(name="Author", value=author, inline=True)
            embed.add_field(name="Branches", value=f"`{head}` → `{base}`", inline=True)
            
            # Add avatar
            if pull['user'].get('avatar_url'):
                embed.set_thumbnail(url=pull['user']['avatar_url'])
            
            # Add mentions
            mentions = " ".join([f"<@{sub}>" for sub in subscribers])
            
            if mentions:
                await channel.send(mentions, embed=embed)
            else:
                await channel.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error sending PR notification: {e}")
    
    async def _send_stars_notification(self, repo_name: str, stars: int, diff: int, channel: discord.TextChannel, guild_id: str):
        """Send notification for star count changes"""
        try:
            # Get subscribers for stars
            subscribers = await self._get_subscribers(guild_id, repo_name, "stars")
            if not subscribers:
                return
            
            # Create embed
            emoji = "⭐" if diff > 0 else "💫"
            title = f"{emoji} Star Update for {repo_name}"
            
            embed = discord.Embed(
                title=title,
                description=f"**{'+' if diff > 0 else ''}{diff} stars**\nNow at {stars:,} total stars",
                color=0xFFD700,  # Gold
                url=f"https://github.com/{repo_name}",
                timestamp=datetime.now(timezone.utc)
            )
            
            # Add mentions
            mentions = " ".join([f"<@{sub}>" for sub in subscribers])
            
            if mentions:
                await channel.send(mentions, embed=embed)
            else:
                await channel.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error sending stars notification: {e}")
    
    async def _get_subscribers(self, guild_id: str, repo_name: str, event_type: str) -> List[str]:
        """Get list of user IDs subscribed to this event type for this repo"""
        try:
            subscribers = await self.bot.db.connection.fetch(
                """SELECT user_id FROM github_subscriptions 
                   WHERE guild_id = $1 AND repo_name = $2 AND event_type = $3 AND enabled = TRUE""",
                guild_id, repo_name, event_type
            )
            
            return [sub['user_id'] for sub in subscribers]
        except Exception as e:
            logger.error(f"Error getting subscribers: {e}")
            return []
    
    async def _send_repo_status(self, repo_name: str, channel: discord.TextChannel, repo_data: dict):
        """Send initial repository status"""
        try:
            # Extract repo info
            description = repo_data.get('description', 'No description')
            stars = repo_data.get('stargazers_count', 0)
            forks = repo_data.get('forks_count', 0)
            open_issues = repo_data.get('open_issues_count', 0)
            language = repo_data.get('language', 'Unknown')
            default_branch = repo_data.get('default_branch', 'main')
            
            embed = discord.Embed(
                title=f"🐙 {repo_name}",
                description=f"{description}\n\nNow tracking this repository for updates!",
                color=0x333333,  # GitHub dark
                url=repo_data['html_url'],
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(name="Stars", value=f"⭐ {stars:,}", inline=True)
            embed.add_field(name="Forks", value=f"🍴 {forks:,}", inline=True)
            embed.add_field(name="Issues", value=f"❗ {open_issues:,}", inline=True)
            embed.add_field(name="Language", value=language, inline=True)
            embed.add_field(name="Default Branch", value=default_branch, inline=True)
            
            embed.add_field(
                name="Notifications",
                value="You'll receive updates about:\n"
                      "• 📝 New commits\n"
                      "• 🚀 New releases\n"
                      "• ❗ New issues\n"
                      "• 🔄 New pull requests\n"
                      "• ⭐ Star count changes",
                inline=False
            )
            
            # Add owner avatar as thumbnail
            if repo_data.get('owner', {}).get('avatar_url'):
                embed.set_thumbnail(url=repo_data['owner']['avatar_url'])
            
            embed.set_footer(text="GitHub Tracking • Use /list-repos to manage notification settings")
            
            await channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error sending repo status: {e}")

async def setup(bot):
    await bot.add_cog(GitHubIntegrations(bot))
    print(f"🐙 Successfully loaded GitHub Integrations cog with real API")
