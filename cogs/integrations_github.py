import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import json
import asyncio
import aiohttp
from datetime import datetime, timezone, timedelta
import logging
from typing import Dict, List, Optional, Any
from discord.ui import Select, View, Button
import os
from config.settings import Settings

logger = logging.getLogger(__name__)

def utc_now():
    """Get current UTC time as timezone-aware datetime"""
    return datetime.now(timezone.utc)

def ensure_timezone_aware(dt):
    """Ensure datetime is timezone-aware (UTC)"""
    if dt is None:
        return utc_now()
    
    if dt.tzinfo is None:
        # Assume naive datetime is UTC and make it timezone-aware
        return dt.replace(tzinfo=timezone.utc)
    
    # Convert to UTC if it has a different timezone
    return dt.astimezone(timezone.utc)

def parse_github_datetime(iso_string):
    """Parse GitHub API datetime string to timezone-aware datetime"""
    if iso_string is None:
        return None
    
    # GitHub returns ISO format like "2023-12-01T10:30:00Z"
    if iso_string.endswith('Z'):
        iso_string = iso_string[:-1] + '+00:00'
    
    return datetime.fromisoformat(iso_string)

def ensure_utc_datetime(dt):
    """Convert datetime to UTC timezone-aware datetime"""
    if dt is None:
        return utc_now()
    
    if isinstance(dt, str):
        # Handle ISO format strings from GitHub API
        return parse_github_datetime(dt)
    
    return ensure_timezone_aware(dt)

class GitHubAPI:
    """GitHub API client with rate limiting and authentication"""
    
    BASE_URL = "https://api.github.com"
    
    def __init__(self, token=None):
        self.token = token or getattr(Settings, 'GITHUB_TOKEN', None)
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Discord-Bot-GitHub-Integration"
        }
        
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"
        else:
            logger.warning("No GitHub token provided - API requests will be rate limited")
        
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
            # Calculate time to wait until reset
            now = utc_now().timestamp()
            wait_time = max(0, self.rate_limit_reset - now) + 1  # Add 1 second buffer
            
            if wait_time > 0:
                logger.warning(f"GitHub API rate limit reached. Waiting {wait_time:.2f} seconds")
                await asyncio.sleep(wait_time)
    
    def _update_rate_limit(self, headers):
        """Update rate limit information from response headers (sync method)"""
        try:
            if "X-RateLimit-Remaining" in headers:
                self.rate_limit_remaining = int(headers["X-RateLimit-Remaining"])
            
            if "X-RateLimit-Reset" in headers:
                self.rate_limit_reset = int(headers["X-RateLimit-Reset"])
                
            logger.debug(f"Rate limit: {self.rate_limit_remaining} remaining, resets at {self.rate_limit_reset}")
        except (ValueError, KeyError) as e:
            logger.warning(f"Failed to parse rate limit headers: {e}")
    
    async def request(self, method, endpoint, **kwargs):
        """Make a request to the GitHub API with rate limiting"""
        await self.ensure_session()
        await self._handle_rate_limit()
        
        url = f"{self.BASE_URL}{endpoint}"
        
        # Apply exponential backoff for retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with self.session.request(method, url, headers=self.headers, **kwargs) as response:
                    # Update rate limit info (sync call)
                    self._update_rate_limit(response.headers)
                    
                    if response.status == 403:
                        # Check if it's a rate limit issue
                        if self.rate_limit_remaining == 0:
                            logger.warning("Rate limited, waiting for reset...")
                            await self._handle_rate_limit()
                            continue
                        else:
                            # Other 403 error (permissions, etc.)
                            logger.error(f"GitHub API 403 error: {await response.text()}")
                            return None
                    
                    if response.status == 404:
                        logger.debug(f"GitHub API 404: {endpoint}")
                        return None  # Resource not found
                    
                    if response.status >= 400:
                        error_text = await response.text()
                        logger.error(f"GitHub API error {response.status}: {error_text}")
                        response.raise_for_status()
                    
                    return await response.json()
            
            except aiohttp.ClientResponseError as e:
                if e.status == 404:
                    return None
                
                if attempt < max_retries - 1:
                    # Exponential backoff
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
    
    async def get_repository(self, owner, repo):
        """Get repository information"""
        return await self.request("GET", f"/repos/{owner}/{repo}")
    
    async def get_commits(self, owner, repo, since=None, per_page=5):
        """Get recent commits to the default branch"""
        params = {"per_page": per_page}
        if since:
            # Ensure since is timezone-aware
            since_utc = ensure_timezone_aware(since)
            params["since"] = since_utc.isoformat()
        
        return await self.request("GET", f"/repos/{owner}/{repo}/commits", params=params)
    
    async def get_releases(self, owner, repo, per_page=5):
        """Get recent releases"""
        return await self.request("GET", f"/repos/{owner}/{repo}/releases", params={"per_page": per_page})
    
    async def get_issues(self, owner, repo, state="open", since=None, per_page=5):
        """Get recent issues"""
        params = {"state": state, "per_page": per_page}
        if since:
            since_utc = ensure_timezone_aware(since)
            params["since"] = since_utc.isoformat()
        
        return await self.request("GET", f"/repos/{owner}/{repo}/issues", params=params)
    
    async def get_pulls(self, owner, repo, state="open", per_page=5):
        """Get recent pull requests"""
        params = {"state": state, "per_page": per_page}
        return await self.request("GET", f"/repos/{owner}/{repo}/pulls", params=params)

class RepoEventTypes:
    """Event types for repository tracking"""
    COMMITS = "commits"
    RELEASES = "releases"
    ISSUES = "issues"
    PULLS = "pulls"
    STARS = "stars"
    
    @classmethod
    def all(cls):
        return [cls.COMMITS, cls.RELEASES, cls.ISSUES, cls.PULLS, cls.STARS]
    
    @classmethod
    def get_emoji(cls, event_type):
        emojis = {
            cls.COMMITS: "📝",
            cls.RELEASES: "🚀",
            cls.ISSUES: "❗",
            cls.PULLS: "🔄",
            cls.STARS: "⭐"
        }
        return emojis.get(event_type, "📊")
    
    @classmethod
    def get_name(cls, event_type):
        names = {
            cls.COMMITS: "Commits",
            cls.RELEASES: "Releases",
            cls.ISSUES: "Issues",
            cls.PULLS: "Pull Requests",
            cls.STARS: "Stars"
        }
        return names.get(event_type, "Unknown")

class GitHubIntegrations(commands.Cog):
    """GitHub repository tracking"""
    
    def __init__(self, bot):
        self.bot = bot
        self.github = GitHubAPI()
        self.repo_cache = {}  # Cache for repository data
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
            
            # Load tracked repositories into cache
            await self.load_tracked_repos()
            
            # Start background task
            self.check_task = self.bot.loop.create_task(self.check_repo_updates())
            
            self.initialized = True
            logger.info("✅ GitHub integration initialized")
            
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
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, repo_name)
                )
            """)
            
            # GitHub repository state table with proper timezone handling
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
                    last_checked TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
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
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, guild_id, repo_name, event_type)
                )
            """)
            
            logger.info("✅ GitHub tables created/verified")
        except Exception as e:
            logger.error(f"❌ Failed to create GitHub tables: {e}")
            raise
    
    async def load_tracked_repos(self):
        """Load tracked repositories into cache with proper error handling"""
        try:
            repos = await self.bot.db.connection.fetch(
                "SELECT * FROM github_tracked_repos"
            )
            
            self.repo_cache = {}  # Reset cache
            
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
                        logger.info(f"Initializing state for {repo_name} in guild {guild_id}")
                        await self.initialize_repo_state(guild_id, repo_name)
                        
                        # Fetch the newly created state
                        state = await self.bot.db.connection.fetchrow(
                            "SELECT * FROM github_repo_state WHERE guild_id = $1 AND repo_name = $2",
                            guild_id, repo_name
                        )
                    
                    # Add to cache with timezone-aware datetime
                    cache_key = f"{guild_id}:{repo_name}"
                    self.repo_cache[cache_key] = {
                        "channel_id": repo['channel_id'],
                        "added_by": repo['added_by'],
                        "created_at": ensure_timezone_aware(repo['created_at']),
                        "state": {
                            "last_commit_sha": state['last_commit_sha'] or "",
                            "last_release_id": state['last_release_id'] or "",
                            "last_issue_number": state['last_issue_number'] or 0,
                            "last_pr_number": state['last_pr_number'] or 0,
                            "stars_count": state['stars_count'] or 0,
                            "last_checked": ensure_timezone_aware(state['last_checked'])
                        }
                    }
                    
                except Exception as e:
                    logger.error(f"Failed to load state for {repo_name}: {e}")
                    continue
            
            logger.info(f"✅ Loaded {len(self.repo_cache)} tracked repositories")
            
        except Exception as e:
            logger.error(f"❌ Failed to load tracked repositories: {e}")
            # Initialize empty cache instead of crashing
            self.repo_cache = {}
    
    async def initialize_repo_state(self, guild_id: str, repo_name: str):
        """Initialize repository state with current GitHub data"""
        try:
            owner, repo = repo_name.split("/", 1)
            
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
                    guild_id, repo_name, "", "", 0, 0, 0, utc_now()
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
                # Filter out PRs
                actual_issues = [issue for issue in issues if 'pull_request' not in issue]
                if actual_issues:
                    last_issue_number = actual_issues[0]['number']
            
            # Get latest PR number
            last_pr_number = 0
            pulls = await self.github.get_pulls(owner, repo, per_page=1)
            if pulls:
                last_pr_number = pulls[0]['number']
            
            # Save initial state with timezone-aware datetime
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
                last_issue_number, last_pr_number, stars, utc_now()
            )
            
            logger.info(f"✅ Initialized state for {repo_name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize state for {repo_name}: {e}")
            # Create minimal state to prevent future errors
            await self.bot.db.connection.execute(
                """INSERT INTO github_repo_state 
                   (guild_id, repo_name, last_commit_sha, last_release_id, 
                    last_issue_number, last_pr_number, stars_count, last_checked)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                   ON CONFLICT (guild_id, repo_name) DO NOTHING""",
                guild_id, repo_name, "", "", 0, 0, 0, utc_now()
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
            
            # Add to database with timezone-aware datetime
            await self.bot.db.connection.execute(
                "INSERT INTO github_tracked_repos (guild_id, repo_name, channel_id, added_by, created_at) VALUES ($1, $2, $3, $4, $5)",
                str(interaction.guild.id), repo, str(channel.id), str(interaction.user.id), utc_now()
            )
            
            # Initialize repo state
            await self.initialize_repo_state(str(interaction.guild.id), repo)
            
            # Set up default subscriptions for the user
            for event_type in RepoEventTypes.all():
                await self.bot.db.connection.execute(
                    """INSERT INTO github_subscriptions (user_id, guild_id, repo_name, event_type, enabled, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6)
                       ON CONFLICT (user_id, guild_id, repo_name, event_type) DO UPDATE SET enabled = $5""",
                    str(interaction.user.id), str(interaction.guild.id), repo, event_type, True, utc_now()
                )
            
            # Add to cache
            cache_key = f"{interaction.guild.id}:{repo}"
            self.repo_cache[cache_key] = {
                "channel_id": str(channel.id),
                "added_by": str(interaction.user.id),
                "created_at": utc_now(),
                "state": {
                    "last_commit_sha": "",
                    "last_release_id": "",
                    "last_issue_number": 0,
                    "last_pr_number": 0,
                    "stars_count": repository.get("stargazers_count", 0),
                    "last_checked": utc_now()
                }
            }
            
            # Create success embed
            embed = discord.Embed(
                title="✅ Repository Tracked",
                description=f"Now tracking `{repo}` in {channel.mention}",
                color=0x2EA043,  # GitHub green
                url=repository["html_url"],
                timestamp=utc_now()  # Use timezone-aware datetime
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
                name="Notifications",
                value="You'll receive updates for:\n" + "\n".join([
                    f"{RepoEventTypes.get_emoji(event)} {RepoEventTypes.get_name(event)}"
                    for event in RepoEventTypes.all()
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
            is_admin = interaction.user.guild_permissions.manage_guild
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
    
    @app_commands.command(name="list-repos", description="List tracked GitHub repositories with subscription options")
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
            
            # Create view with dropdown
            view = RepoListView(self.bot, repos, interaction.user.id, str(interaction.guild.id))
            
            embed = discord.Embed(
                title="🐙 Tracked GitHub Repositories",
                description=f"This server is tracking **{len(repos)}** repositories.\n\n"
                            "Select a repository below to view details and manage notifications:",
                color=0x333333,  # GitHub dark
                timestamp=utc_now()  # Use timezone-aware datetime
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
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
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
        """Check for updates to a specific repository with proper state validation"""
        try:
            owner, repo = repo_name.split("/", 1)
            cache_key = f"{guild_id}:{repo_name}"
            
            # Get current state from database (always fresh)
            state = await self.bot.db.connection.fetchrow(
                "SELECT * FROM github_repo_state WHERE guild_id = $1 AND repo_name = $2",
                guild_id, repo_name
            )
            
            if not state:
                logger.warning(f"No state found for {repo_name} in guild {guild_id}, initializing...")
                await self.initialize_repo_state(guild_id, repo_name)
                
                # Fetch the newly created state
                state = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM github_repo_state WHERE guild_id = $1 AND repo_name = $2",
                    guild_id, repo_name
                )
                
                if not state:
                    logger.error(f"Failed to initialize state for {repo_name}")
                    return
            
            # Convert database state to proper format with timezone-aware datetimes
            current_state = {
                'last_commit_sha': state['last_commit_sha'] or "",
                'last_release_id': state['last_release_id'] or "",
                'last_issue_number': state['last_issue_number'] or 0,
                'last_pr_number': state['last_pr_number'] or 0,
                'stars_count': state['stars_count'] or 0,
                'last_checked': ensure_timezone_aware(state['last_checked'])
            }
            
            # Check for new commits
            await self._check_commits(owner, repo, current_state, channel, guild_id, repo_name)
            
            # Check for new releases
            await self._check_releases(owner, repo, current_state, channel, guild_id, repo_name)
            
            # Check for new issues
            await self._check_issues(owner, repo, current_state, channel, guild_id, repo_name)
            
            # Check for new pull requests
            await self._check_pulls(owner, repo, current_state, channel, guild_id, repo_name)
            
            # Check for star changes
            await self._check_stars(owner, repo, current_state, channel, guild_id, repo_name)
            
            # Update last checked time with timezone-aware datetime
            await self.bot.db.connection.execute(
                "UPDATE github_repo_state SET last_checked = $1 WHERE guild_id = $2 AND repo_name = $3",
                utc_now(), guild_id, repo_name
            )
            
            # Update cache
            if cache_key in self.repo_cache:
                self.repo_cache[cache_key]["state"]["last_checked"] = utc_now()
            
        except Exception as e:
            logger.error(f"Error checking updates for {repo_name}: {e}")
    
    async def _check_commits(self, owner: str, repo: str, state: dict, channel: discord.TextChannel, guild_id: str, repo_name: str):
        """Check for new commits"""
        try:
            # Get recent commits since last check
            since_time = state['last_checked'] - timedelta(hours=1)  # Look back 1 hour to be safe
            commits = await self.github.get_commits(owner, repo, since=since_time, per_page=10)
            
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
            
            # Find new commits (those that came after the last one we recorded)
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
                
                # Send notifications for new commits (limit to 3 to avoid spam)
                for commit in new_commits[:3]:
                    await self._send_commit_notification(commit, repo_name, channel, guild_id)
                    await asyncio.sleep(1)  # Brief delay between notifications
                
        except Exception as e:
            logger.error(f"Error checking commits for {repo_name}: {e}")
    
    async def _check_releases(self, owner: str, repo: str, state: dict, channel: discord.TextChannel, guild_id: str, repo_name: str):
        """Check for new releases"""
        try:
            # Get recent releases
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
            # Get recent issues (exclude PRs)
            since_time = state['last_checked'] - timedelta(hours=1)
            issues = await self.github.get_issues(owner, repo, since=since_time, per_page=10)
            
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
            # Get recent pull requests
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
            # Get current repository data
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
            # Get subscribers for this event type
            subscribers = await self._get_subscribers(guild_id, repo_name, RepoEventTypes.COMMITS)
            if not subscribers:
                return
            
            # Extract commit info
            sha = commit['sha'][:7]
            message = commit['commit']['message'].split('\n')[0]  # First line only
            author = commit['commit']['author']['name']
            date = ensure_timezone_aware(parse_github_datetime(commit['commit']['author']['date']))
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
                timestamp=date  # Use timezone-aware datetime
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
            # Get subscribers for this event type
            subscribers = await self._get_subscribers(guild_id, repo_name, RepoEventTypes.RELEASES)
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
            
            # Create embed with timezone-aware datetime
            created_at = ensure_timezone_aware(parse_github_datetime(release.get('created_at')))
            
            embed = discord.Embed(
                title=f"🚀 New {'Pre-release' if is_prerelease else 'Release'} for {repo_name}",
                description=f"**{name}**\n\n{body}" if body else f"**{name}**",
                color=0x6F42C1,  # GitHub purple
                url=url,
                timestamp=created_at
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
            # Get subscribers for this event type
            subscribers = await self._get_subscribers(guild_id, repo_name, RepoEventTypes.ISSUES)
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
            
            # Create embed with timezone-aware datetime
            created_at = ensure_timezone_aware(parse_github_datetime(issue.get('created_at')))
            
            embed = discord.Embed(
                title=f"❗ New Issue in {repo_name}",
                description=f"**#{number}: {title}**\n\n{body}" if body else f"**#{number}: {title}**",
                color=0xD73A49,  # GitHub red
                url=url,
                timestamp=created_at
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
            # Get subscribers for this event type
            subscribers = await self._get_subscribers(guild_id, repo_name, RepoEventTypes.PULLS)
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
            
            # Create embed with timezone-aware datetime
            created_at = ensure_timezone_aware(parse_github_datetime(pull.get('created_at')))
            
            embed = discord.Embed(
                title=f"🔄 New Pull Request in {repo_name}",
                description=f"**#{number}: {title}**\n\n{body}" if body else f"**#{number}: {title}**",
                color=0x28A745,  # GitHub green
                url=url,
                timestamp=created_at
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
            # Get subscribers for this event type
            subscribers = await self._get_subscribers(guild_id, repo_name, RepoEventTypes.STARS)
            if not subscribers:
                return
            
            # Create embed with timezone-aware datetime
            emoji = "⭐" if diff > 0 else "💫"
            title = f"{emoji} Star Update for {repo_name}"
            
            embed = discord.Embed(
                title=title,
                description=f"**{'+' if diff > 0 else ''}{diff} stars**\nNow at {stars:,} total stars",
                color=0xFFD700,  # Gold
                url=f"https://github.com/{repo_name}",
                timestamp=utc_now()
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
                timestamp=utc_now()  # Use timezone-aware datetime
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
                description=f"View details and manage notifications",
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
        if interaction.user.id != int(self.user_id):
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return
        
        selected_repo = self.values[0]
        
        # Get repo details
        repo_data = next((repo for repo in self.repos if repo['repo_name'] == selected_repo), None)
        if not repo_data:
            await interaction.response.send_message("Repository not found!", ephemeral=True)
            return
        
        # Get user subscription status
        subscriptions = {}
        for event_type in RepoEventTypes.all():
            sub = await self.bot.db.connection.fetchrow(
                """SELECT enabled FROM github_subscriptions 
                   WHERE user_id = $1 AND guild_id = $2 AND repo_name = $3 AND event_type = $4""",
                str(self.user_id), self.guild_id, selected_repo, event_type
            )
            
            subscriptions[event_type] = sub and sub['enabled'] if sub else False
        
        # Get channel info
        channel = interaction.guild.get_channel(int(repo_data['channel_id']))
        channel_mention = channel.mention if channel else "Unknown Channel"
        
        # Get repo state
        state = await self.bot.db.connection.fetchrow(
            "SELECT * FROM github_repo_state WHERE guild_id = $1 AND repo_name = $2",
            self.guild_id, selected_repo
        )
        
        stars = state['stars_count'] if state else 0
        
        embed = discord.Embed(
            title=f"🐙 {selected_repo}",
            description=f"Repository details and notification settings",
            color=0x333333,
            url=f"https://github.com/{selected_repo}",
            timestamp=utc_now()  # Use timezone-aware datetime
        )
        
        embed.add_field(name="Channel", value=channel_mention, inline=True)
        embed.add_field(name="Stars", value=f"⭐ {stars:,}", inline=True)
        
        # Format created_at with timezone-aware datetime
        created_at = ensure_timezone_aware(repo_data['created_at'])
        embed.add_field(name="Added", value=f"<t:{int(created_at.timestamp())}:R>", inline=True)
        
        # Add subscription status
        status_text = "\n".join([
            f"{RepoEventTypes.get_emoji(event)} **{RepoEventTypes.get_name(event)}**: {'🔔 On' if subscriptions.get(event, False) else '🔕 Off'}"
            for event in RepoEventTypes.all()
        ])
        
        embed.add_field(
            name="Your Notification Settings",
            value=status_text,
            inline=False
        )
        
        # Create toggle buttons view
        view = RepoSettingsView(self.bot, selected_repo, self.user_id, self.guild_id, subscriptions)

        await interaction.response.edit_message(embed=embed, view=view)

class RepoSettingsView(discord.ui.View):
    def __init__(self, bot, repo_name, user_id, guild_id, subscriptions):
        super().__init__(timeout=300)
        self.bot = bot
        self.repo_name = repo_name
        self.user_id = user_id
        self.guild_id = guild_id
        self.subscriptions = subscriptions
        
        # Add toggle buttons for each event type
        for event_type in RepoEventTypes.all():
            is_enabled = subscriptions.get(event_type, False)
            
            button = Button(
                label=f"{RepoEventTypes.get_emoji(event_type)} {RepoEventTypes.get_name(event_type)}: {'On' if is_enabled else 'Off'}",
                style=discord.ButtonStyle.success if is_enabled else discord.ButtonStyle.secondary,
                custom_id=f"toggle_{event_type}"
            )
            
            button.callback = self.make_toggle_callback(event_type)
            self.add_item(button)
        
        # Add back button
        back_button = Button(label="← Back to List", style=discord.ButtonStyle.primary)
        back_button.callback = self.back_to_list
        self.add_item(back_button)
    
    def make_toggle_callback(self, event_type):
        async def toggle_callback(interaction):
            if interaction.user.id != int(self.user_id):
                await interaction.response.send_message("You can only toggle your own notifications!", ephemeral=True)
                return
            
            try:
                # Toggle subscription
                new_status = not self.subscriptions.get(event_type, False)
                
                # Update database with timezone-aware datetime
                await self.bot.db.connection.execute(
                    """INSERT INTO github_subscriptions (user_id, guild_id, repo_name, event_type, enabled, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6)
                       ON CONFLICT (user_id, guild_id, repo_name, event_type) DO UPDATE SET enabled = $5""",
                    str(self.user_id), self.guild_id, self.repo_name, event_type, new_status, utc_now()
                )
                
                # Update local state
                self.subscriptions[event_type] = new_status
                
                # Update button
                for child in self.children:
                    if isinstance(child, Button) and child.custom_id == f"toggle_{event_type}":
                        child.label = f"{RepoEventTypes.get_emoji(event_type)} {RepoEventTypes.get_name(event_type)}: {'On' if new_status else 'Off'}"
                        child.style = discord.ButtonStyle.success if new_status else discord.ButtonStyle.secondary
                        break
                
                # Update embed
                embed = interaction.message.embeds[0]
                
                # Update subscription status field
                status_text = "\n".join([
                    f"{RepoEventTypes.get_emoji(event)} **{RepoEventTypes.get_name(event)}**: {'🔔 On' if self.subscriptions.get(event, False) else '🔕 Off'}"
                    for event in RepoEventTypes.all()
                ])
                
                # Find and update the field
                for i, field in enumerate(embed.fields):
                    if field.name == "Your Notification Settings":
                        embed.set_field_at(i, name=field.name, value=status_text, inline=field.inline)
                        break
                
                await interaction.response.edit_message(embed=embed, view=self)
                
            except Exception as e:
                logger.error(f"Error toggling subscription: {e}")
                await interaction.response.send_message("Failed to update subscription!", ephemeral=True)
        
        return toggle_callback
    
    async def back_to_list(self, interaction):
        if interaction.user.id != int(self.user_id):
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return
        
        # Get repos again
        repos = await self.bot.db.connection.fetch(
            "SELECT * FROM github_tracked_repos WHERE guild_id = $1 ORDER BY created_at DESC",
            self.guild_id
        )
        
        # Create new view
        view = RepoListView(self.bot, repos, self.user_id, self.guild_id)
        
        embed = discord.Embed(
            title="🐙 Tracked GitHub Repositories",
            description=f"This server is tracking **{len(repos)}** repositories.\n\n"
                        "Select a repository below to view details and manage notifications:",
            color=0x333333,
            timestamp=utc_now()
        )
        
        # Add repo list
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
        
        await interaction.response.edit_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(GitHubIntegrations(bot))
