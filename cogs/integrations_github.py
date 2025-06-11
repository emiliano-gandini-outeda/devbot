import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import json
import asyncio
import aiohttp
from datetime import datetime, timedelta
import logging
from typing import List, Dict, Optional, Any
from discord.ui import Select, View, Button
from config.settings import Settings

logger = logging.getLogger(__name__)

class GitHubIntegrations(commands.Cog):
    """GitHub repository tracking with real API integration"""
    
    def __init__(self, bot):
        self.bot = bot
        self.github_token = Settings.GITHUB_TOKEN
        self.session = None
        self.tracking_task = None
        self.tracking_started = False
        
        # Don't start tracking immediately - wait for proper initialization
        logger.info("🐙 GitHub integration initialized, tracking will start after bot is ready")
    
    async def cog_load(self):
        """Called when the cog is loaded - start tracking with delay"""
        # Wait a bit longer to ensure all systems are ready
        await asyncio.sleep(10)  # 10 second delay after cog load
        await self.start_tracking()
    
    async def start_tracking(self):
        """Initialize the tracking system with proper delays"""
        if self.tracking_started:
            return
            
        try:
            # Wait for bot to be fully ready
            await self.bot.wait_until_ready()
            
            # Additional delay to ensure database operations are complete
            logger.info("🐙 Waiting for database operations to complete...")
            await asyncio.sleep(15)  # 15 second delay to avoid DB conflicts
            
            # Test database connection first
            if not self.bot.db or not self.bot.db.connection:
                logger.error("❌ Database not available for GitHub tracking")
                return
            
            # Test a simple query to ensure DB is ready
            try:
                await self.bot.db.connection.fetchval("SELECT 1")
                logger.info("✅ Database connection verified for GitHub tracking")
            except Exception as e:
                logger.error(f"❌ Database not ready for GitHub tracking: {e}")
                # Retry after another delay
                await asyncio.sleep(30)
                return await self.start_tracking()
            
            # Create HTTP session with GitHub headers
            if not self.session:
                self.session = aiohttp.ClientSession(
                    headers={
                        'Authorization': f'token {self.github_token}',
                        'Accept': 'application/vnd.github.v3+json',
                        'User-Agent': 'Discord-Bot-GitHub-Tracker'
                    }
                )
                logger.info("✅ GitHub API session created")
            
            # Start the background tracking task
            if not self.tracking_task or self.tracking_task.done():
                self.tracking_task = self.bot.loop.create_task(self.check_repo_updates())
                self.tracking_started = True
                logger.info("✅ GitHub tracking system started successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to start GitHub tracking: {e}")
            # Retry after delay
            await asyncio.sleep(60)
            await self.start_tracking()
    
    async def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.tracking_started = False
        if self.session:
            await self.session.close()
        if self.tracking_task:
            self.tracking_task.cancel()
    
    async def github_api_request(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Make a request to the GitHub API"""
        if not self.github_token:
            logger.error("GitHub token not configured")
            return None
        
        if not self.session:
            logger.error("GitHub session not initialized")
            return None
        
        url = f"https://api.github.com{endpoint}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 404:
                    logger.warning(f"GitHub API 404: {endpoint}")
                    return None
                elif response.status == 403:
                    logger.error(f"GitHub API rate limit exceeded: {endpoint}")
                    return None
                else:
                    logger.error(f"GitHub API error {response.status}: {endpoint}")
                    return None
        except Exception as e:
            logger.error(f"GitHub API request failed: {e}")
            return None
    
    async def get_repo_data(self, repo_name: str) -> Optional[Dict[str, Any]]:
        """Get comprehensive repository data from GitHub API"""
        try:
            # Get basic repo info
            repo_data = await self.github_api_request(f"/repos/{repo_name}")
            if not repo_data:
                return None
            
            # Get latest commits
            commits_data = await self.github_api_request(f"/repos/{repo_name}/commits?per_page=10")
            if not commits_data:
                commits_data = []
            
            # Get branches
            branches_data = await self.github_api_request(f"/repos/{repo_name}/branches?per_page=100")
            if not branches_data:
                branches_data = []
            
            # Get recent stargazers (for star change notifications)
            stargazers_data = await self.github_api_request(f"/repos/{repo_name}/stargazers?per_page=10")
            if not stargazers_data:
                stargazers_data = []
            
            return {
                'repo': repo_data,
                'commits': commits_data,
                'branches': branches_data,
                'stargazers': stargazers_data
            }
        except Exception as e:
            logger.error(f"Error getting repo data for {repo_name}: {e}")
            return None
    
    @app_commands.command(name="setup-github-tracking", description="Configure GitHub tracking channel (Admin Only)")
    @app_commands.describe(channel="Channel where GitHub notifications will be sent")
    async def setup_github_tracking(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer()
        
        # Check if user is admin
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error(
                "Permission Denied",
                "Only administrators can configure GitHub tracking."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        try:
            # Store tracking configuration
            config_data = {
                'tracking_channel_id': str(channel.id),
                'configured_by': str(interaction.user.id),
                'configured_at': datetime.utcnow().isoformat()
            }
            
            await self.bot.db.connection.execute(
                """INSERT INTO user_data (user_id, guild_id, data_type, data_content) 
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (user_id, guild_id, data_type) 
                   DO UPDATE SET data_content = $4, updated_at = CURRENT_TIMESTAMP""",
                str(interaction.guild.id), str(interaction.guild.id), 'github_tracking_config', json.dumps(config_data)
            )
            
            embed = EmbedBuilder.success(
                "GitHub Tracking Configured",
                f"GitHub notifications will be sent to {channel.mention}\n\n"
                f"Users can now use `/track-repo` to start tracking repositories."
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Configuration Error", f"Failed to configure tracking: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="track-repo", description="Track a GitHub repository for updates")
    @app_commands.describe(
        repo="Repository name (format: owner/repo)",
        ping_me="Whether you want to be pinged for updates (default: True)"
    )
    async def track_repo(self, interaction: discord.Interaction, repo: str, ping_me: bool = True):
        await interaction.response.defer()
        
        if not self.github_token:
            embed = EmbedBuilder.error(
                "GitHub Not Configured",
                "GitHub integration is not properly configured. Please contact an administrator."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        try:
            # Validate repository format
            if "/" not in repo or len(repo.split("/")) != 2:
                embed = EmbedBuilder.error(
                    "Invalid Format",
                    "Repository must be in the format `owner/repo` (e.g., `microsoft/vscode`)"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Check if repository exists
            repo_data = await self.get_repo_data(repo)
            if not repo_data:
                embed = EmbedBuilder.error(
                    "Repository Not Found",
                    f"Could not find repository `{repo}` or it's not accessible."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Get tracking config
            config = await self.bot.db.connection.fetchrow(
                "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                str(interaction.guild.id), 'github_tracking_config'
            )
            
            if not config:
                embed = EmbedBuilder.error(
                    "GitHub Tracking Not Configured",
                    "GitHub tracking has not been set up. Please ask an administrator to run `/setup-github-tracking`"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            config_data = json.loads(config['data_content'])
            tracking_channel_id = config_data.get('tracking_channel_id')
            
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
                "SELECT * FROM github_tracked_repos WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            if existing:
                embed = EmbedBuilder.warning(
                    "Already Tracking",
                    f"Already tracking `{repo}` in {channel.mention}"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Add to database with initial data
            current_time = datetime.utcnow()
            initial_data = {
                'stars': repo_data['repo']['stargazers_count'],
                'last_commit_sha': repo_data['commits'][0]['sha'] if repo_data['commits'] else '',
                'last_commit_message': repo_data['commits'][0]['commit']['message'] if repo_data['commits'] else '',
                'last_commit_author': repo_data['commits'][0]['commit']['author']['name'] if repo_data['commits'] else '',
                'last_commit_date': repo_data['commits'][0]['commit']['author']['date'] if repo_data['commits'] else '',
                'branches': [branch['name'] for branch in repo_data['branches']],
                'last_check': current_time.isoformat(),
                'recent_stargazers': [user['login'] for user in repo_data['stargazers'][-5:]]  # Last 5 stargazers
            }
            
            await self.bot.db.connection.execute(
                "INSERT INTO github_tracked_repos (guild_id, repo_name, channel_id, added_by) VALUES ($1, $2, $3, $4)",
                str(interaction.guild.id), repo, str(channel.id), str(interaction.user.id)
            )
            
            # Store initial tracking data
            await self.bot.db.connection.execute(
                """INSERT INTO user_data (user_id, guild_id, data_type, data_content) 
                   VALUES ($1, $2, $3, $4)""",
                f"github_repo_{repo.replace('/', '_')}", str(interaction.guild.id), 'github_repo_data', json.dumps(initial_data)
            )
            
            # Set up user subscription
            if ping_me:
                await self.bot.db.connection.execute(
                    """INSERT INTO github_subscriptions (user_id, guild_id, repo_name, enabled) 
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (user_id, guild_id, repo_name) DO UPDATE SET enabled = $4""",
                    str(interaction.user.id), str(interaction.guild.id), repo, True
                )
            
            embed = EmbedBuilder.success(
                "Repository Tracked",
                f"Now tracking **{repo}** in {channel.mention}\n\n"
                f"**Current Stats:**\n"
                f"⭐ Stars: {repo_data['repo']['stargazers_count']:,}\n"
                f"🍴 Forks: {repo_data['repo']['forks_count']:,}\n"
                f"🌿 Branches: {len(repo_data['branches'])}\n"
                f"📝 Latest commit: {repo_data['commits'][0]['commit']['message'][:50] + '...' if repo_data['commits'] and len(repo_data['commits'][0]['commit']['message']) > 50 else repo_data['commits'][0]['commit']['message'] if repo_data['commits'] else 'None'}\n\n"
                f"**Notifications:** {'🔔 Enabled' if ping_me else '🔕 Disabled'}"
            )
            await interaction.followup.send(embed=embed)
            
            # Send initial status to tracking channel
            await self._send_repo_status(repo, channel, repo_data)
            
        except Exception as e:
            logger.error(f"Error tracking repo {repo}: {e}")
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
                    f"Not tracking `{repo}` in this server"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Remove user subscriptions
            await self.bot.db.connection.execute(
                "DELETE FROM github_subscriptions WHERE guild_id = $1 AND repo_name = $2",
                str(interaction.guild.id), repo
            )
            
            # Remove tracking data
            await self.bot.db.connection.execute(
                "DELETE FROM user_data WHERE user_id = $1 AND guild_id = $2 AND data_type = $3",
                f"github_repo_{repo.replace('/', '_')}", str(interaction.guild.id), 'github_repo_data'
            )
            
            embed = EmbedBuilder.success(
                "Tracking Stopped",
                f"Stopped tracking `{repo}`"
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to untrack repository: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-repos", description="List tracked GitHub repositories")
    async def list_repos(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get tracked repos for this guild
            repos = await self.bot.db.connection.fetch(
                "SELECT * FROM github_tracked_repos WHERE guild_id = $1 ORDER BY created_at DESC",
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
                description=f"This server is tracking **{len(repos)}** repositories\n\nSelect a repository below to view details and toggle notifications:",
                color=0x333333  # GitHub dark
            )
            
            # Add a preview of tracked repos
            repo_list = []
            for i, repo in enumerate(repos[:5]):  # Show first 5
                repo_list.append(f"{i+1}. **{repo['repo_name']}**")
            
            if repo_list:
                embed.add_field(
                    name="Currently Tracking",
                    value="\n".join(repo_list) + (f"\n... and {len(repos) - 5} more" if len(repos) > 5 else ""),
                    inline=False
                )
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to list repositories: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="repo-update", description="Get immediate update for a tracked repository")
    async def repo_update(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get tracked repos for this guild
            repos = await self.bot.db.connection.fetch(
                "SELECT * FROM github_tracked_repos WHERE guild_id = $1 ORDER BY created_at DESC",
                str(interaction.guild.id)
            )
            
            if not repos:
                embed = EmbedBuilder.info("No Repositories", "No GitHub repositories are being tracked in this server")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Create view with dropdown for repo selection
            view = RepoUpdateView(self.bot, repos, interaction.user.id, str(interaction.guild.id))
            
            embed = discord.Embed(
                title="🔄 Repository Update",
                description=f"Select a repository to get an immediate update (overrides 15-minute delay):\n\n**{len(repos)}** repositories available",
                color=0x333333  # GitHub dark
            )
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to load repositories: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def check_repo_updates(self):
        """Background task to check for repository updates every 15 minutes"""
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            try:
                logger.info("🔍 Checking GitHub repository updates...")
                
                # Get all tracked repos
                repos = await self.bot.db.connection.fetch("SELECT * FROM github_tracked_repos")
                
                for repo in repos:
                    try:
                        await self._check_single_repo_updates(repo)
                        # Small delay between repos to avoid rate limiting
                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.error(f"Error checking updates for {repo['repo_name']}: {e}")
                
                logger.info(f"✅ Finished checking {len(repos)} repositories")
                
                # Sleep for 15 minutes (900 seconds) - reduced from 30 minutes
                await asyncio.sleep(900)
                
            except Exception as e:
                logger.error(f"Error in repository update check: {e}")
                await asyncio.sleep(300)  # Sleep 5 minutes on error
    
    async def _check_single_repo_updates(self, repo_record, force_update=False):
        """Check for updates to a specific repository"""
        guild_id = repo_record['guild_id']
        repo_name = repo_record['repo_name']
        channel_id = repo_record['channel_id']
        
        logger.info(f"🔍 Checking updates for {repo_name} (force: {force_update})")
        
        # Check if guild and channel still exist
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            logger.warning(f"Guild {guild_id} not found for repo {repo_name}")
            return
        
        channel = guild.get_channel(int(channel_id))
        if not channel:
            logger.warning(f"Channel {channel_id} not found for repo {repo_name}")
            return
        
        # Get current repo data from GitHub
        current_data = await self.get_repo_data(repo_name)
        if not current_data:
            logger.warning(f"Could not fetch data for {repo_name}")
            return
        
        # Get stored data
        stored_data_record = await self.bot.db.connection.fetchrow(
            "SELECT data_content FROM user_data WHERE user_id = $1 AND guild_id = $2 AND data_type = $3",
            f"github_repo_{repo_name.replace('/', '_')}", guild_id, 'github_repo_data'
        )
        
        if not stored_data_record:
            logger.warning(f"No stored data found for {repo_name}, initializing...")
            # Initialize with current data if missing
            initial_data = {
                'stars': current_data['repo']['stargazers_count'],
                'last_commit_sha': current_data['commits'][0]['sha'] if current_data['commits'] else '',
                'last_commit_message': current_data['commits'][0]['commit']['message'] if current_data['commits'] else '',
                'last_commit_author': current_data['commits'][0]['commit']['author']['name'] if current_data['commits'] else '',
                'last_commit_date': current_data['commits'][0]['commit']['author']['date'] if current_data['commits'] else '',
                'branches': [branch['name'] for branch in current_data['branches']],
                'last_check': datetime.utcnow().isoformat(),
                'recent_stargazers': [user['login'] for user in current_data['stargazers'][-5:]]
            }
            
            await self.bot.db.connection.execute(
                """INSERT INTO user_data (user_id, guild_id, data_type, data_content) 
                   VALUES ($1, $2, $3, $4)""",
                f"github_repo_{repo_name.replace('/', '_')}", guild_id, 'github_repo_data', json.dumps(initial_data)
            )
            
            if force_update:
                embed = EmbedBuilder.info(
                    "Repository Initialized",
                    f"✅ **{repo_name}** data has been initialized.\nFuture updates will be detected from this baseline."
                )
                await channel.send(embed=embed)
            return
        
        stored_data = json.loads(stored_data_record['data_content'])
        updates = []
        
        logger.info(f"📊 Comparing data for {repo_name}:")
        logger.info(f"  Current stars: {current_data['repo']['stargazers_count']}, Stored: {stored_data.get('stars', 0)}")
        logger.info(f"  Current commit: {current_data['commits'][0]['sha'][:8] if current_data['commits'] else 'None'}, Stored: {stored_data.get('last_commit_sha', '')[:8] if stored_data.get('last_commit_sha') else 'None'}")
        
        # Check for star changes
        current_stars = current_data['repo']['stargazers_count']
        stored_stars = stored_data.get('stars', 0)
        
        if current_stars != stored_stars:
            star_diff = current_stars - stored_stars
            logger.info(f"⭐ Star change detected: {star_diff}")
            if star_diff > 0:
                # Get new stargazers
                recent_stargazers = [user['login'] for user in current_data['stargazers'][-abs(star_diff):]]
                if recent_stargazers:
                    stargazer_mentions = ", ".join([f"**{user}**" for user in recent_stargazers[-3:]])  # Show last 3
                    updates.append({
                        'type': 'stars',
                        'message': f"⭐ **+{star_diff} new star{'s' if star_diff != 1 else ''}** (now at {current_stars:,})",
                        'details': f"Recent stargazers: {stargazer_mentions}" + (f" and {len(recent_stargazers) - 3} more" if len(recent_stargazers) > 3 else "")
                    })
            elif star_diff < 0:
                updates.append({
                    'type': 'stars',
                    'message': f"⭐ **{star_diff} stars** (now at {current_stars:,})",
                    'details': None
                })
        
        # Check for new commits
        if current_data['commits']:
            current_commit = current_data['commits'][0]
            current_commit_sha = current_commit['sha']
            stored_commit_sha = stored_data.get('last_commit_sha', '')
            
            if current_commit_sha != stored_commit_sha:
                logger.info(f"📝 New commit detected: {current_commit_sha[:8]}")
                commit_message = current_commit['commit']['message'].split('\n')[0]  # First line only
                commit_author = current_commit['commit']['author']['name']
                commit_date = datetime.fromisoformat(current_commit['commit']['author']['date'].replace('Z', '+00:00'))
                
                # Try to get the actual branch name from the commit
                branch_name = "main"  # Default
                try:
                    # Get branches that contain this commit
                    branches_with_commit = await self.github_api_request(f"/repos/{repo_name}/commits/{current_commit_sha}/branches-where-head")
                    if branches_with_commit and len(branches_with_commit) > 0:
                        branch_name = branches_with_commit[0]['name']
                except:
                    pass  # Use default if API call fails
                
                updates.append({
                    'type': 'commit',
                    'message': f"📝 **New commit** on `{branch_name}`",
                    'details': f"**{commit_message}**\nBy **{commit_author}** • <t:{int(commit_date.timestamp())}:R>"
                })
        
        # Check for new branches
        current_branches = set(branch['name'] for branch in current_data['branches'])
        stored_branches = set(stored_data.get('branches', []))
        new_branches = current_branches - stored_branches
        deleted_branches = stored_branches - current_branches
        
        if new_branches:
            logger.info(f"🌿 New branches detected: {list(new_branches)}")
            for branch_name in list(new_branches)[:3]:  # Show max 3 new branches
                updates.append({
                    'type': 'branch',
                    'message': f"🌿 **New branch created:** `{branch_name}`",
                    'details': None
                })
        
        if deleted_branches:
            logger.info(f"🗑️ Deleted branches detected: {list(deleted_branches)}")
            for branch_name in list(deleted_branches)[:3]:  # Show max 3 deleted branches
                updates.append({
                    'type': 'branch',
                    'message': f"🗑️ **Branch deleted:** `{branch_name}`",
                    'details': None
                })
        
        # Send updates if any found or if forced
        if updates:
            logger.info(f"📤 Sending {len(updates)} updates for {repo_name}")
            await self._send_updates(repo_name, channel, guild_id, updates)
        elif force_update:
            # Send a "no updates" message for forced updates
            embed = EmbedBuilder.info(
                "Repository Up to Date",
                f"✅ **{repo_name}** is up to date.\nNo new commits, stars, or branch changes detected."
            )
            await channel.send(embed=embed)
        else:
            logger.info(f"📭 No updates found for {repo_name}")
        
        # Update stored data
        new_stored_data = {
            'stars': current_stars,
            'last_commit_sha': current_data['commits'][0]['sha'] if current_data['commits'] else '',
            'last_commit_message': current_data['commits'][0]['commit']['message'] if current_data['commits'] else '',
            'last_commit_author': current_data['commits'][0]['commit']['author']['name'] if current_data['commits'] else '',
            'last_commit_date': current_data['commits'][0]['commit']['author']['date'] if current_data['commits'] else '',
            'branches': list(current_branches),
            'last_check': datetime.utcnow().isoformat(),
            'recent_stargazers': [user['login'] for user in current_data['stargazers'][-5:]]
        }
        
        await self.bot.db.connection.execute(
            """UPDATE user_data SET data_content = $1, updated_at = CURRENT_TIMESTAMP 
               WHERE user_id = $2 AND guild_id = $3 AND data_type = $4""",
            json.dumps(new_stored_data),
            f"github_repo_{repo_name.replace('/', '_')}", guild_id, 'github_repo_data'
        )
        
        logger.info(f"✅ Updated stored data for {repo_name}")
    
    async def _send_updates(self, repo_name: str, channel: discord.TextChannel, guild_id: str, updates: List[Dict]):
        """Send update notifications to the channel"""
        try:
            # Get subscribers
            subscribers = await self.bot.db.connection.fetch(
                "SELECT user_id FROM github_subscriptions WHERE guild_id = $1 AND repo_name = $2 AND enabled = TRUE",
                guild_id, repo_name
            )
            
            # Create embed
            embed = discord.Embed(
                title=f"🐙 {repo_name} Updates",
                color=0x333333,  # GitHub dark
                timestamp=datetime.utcnow(),
                url=f"https://github.com/{repo_name}"
            )
            
            # Add updates to embed
            for i, update in enumerate(updates[:5]):  # Max 5 updates per message
                field_name = update['message']
                field_value = update['details'] if update['details'] else "No additional details"
                embed.add_field(name=field_name, value=field_value, inline=False)
            
            embed.set_footer(text="GitHub Tracking • Updates checked every 15 minutes")
            
            # Prepare message content
            content = ""
            if subscribers:
                mentions = [f"<@{sub['user_id']}>" for sub in subscribers[:10]]  # Max 10 mentions
                if mentions:
                    content = " ".join(mentions)
                    if len(subscribers) > 10:
                        content += f" and {len(subscribers) - 10} others"
            
            # Create view with Track Repo button
            view = TrackRepoButtonView(repo_name)
            
            # Send the message
            if content:
                await channel.send(content=content, embed=embed, view=view)
            else:
                await channel.send(embed=embed, view=view)
                
        except Exception as e:
            logger.error(f"Error sending updates for {repo_name}: {e}")
    
    async def _send_repo_status(self, repo_name: str, channel: discord.TextChannel, repo_data: Dict):
        """Send initial repository status when tracking starts"""
        try:
            repo_info = repo_data['repo']
            
            embed = discord.Embed(
                title=f"🐙 {repo_name}",
                description=f"Started tracking **{repo_name}**\n\n{repo_info.get('description', 'No description available')}",
                color=0x333333,  # GitHub dark
                url=repo_info['html_url']
            )
            
            embed.add_field(name="⭐ Stars", value=f"{repo_info['stargazers_count']:,}", inline=True)
            embed.add_field(name="🍴 Forks", value=f"{repo_info['forks_count']:,}", inline=True)
            embed.add_field(name="👁️ Watchers", value=f"{repo_info['watchers_count']:,}", inline=True)
            
            embed.add_field(name="🌿 Branches", value=f"{len(repo_data['branches'])}", inline=True)
            embed.add_field(name="📝 Language", value=repo_info.get('language', 'Unknown'), inline=True)
            embed.add_field(name="📅 Created", value=f"<t:{int(datetime.fromisoformat(repo_info['created_at'].replace('Z', '+00:00')).timestamp())}:D>", inline=True)
            
            if repo_data['commits']:
                latest_commit = repo_data['commits'][0]
                commit_date = datetime.fromisoformat(latest_commit['commit']['author']['date'].replace('Z', '+00:00'))
                embed.add_field(
                    name="📝 Latest Commit",
                    value=f"**{latest_commit['commit']['message'].split(chr(10))[0][:100]}**\nBy {latest_commit['commit']['author']['name']} • <t:{int(commit_date.timestamp())}:R>",
                    inline=False
                )
            
            embed.add_field(
                name="🔔 Notifications",
                value="You'll receive updates about:\n• ⭐ Star changes\n• 📝 New commits\n• 🌿 New/deleted branches",
                inline=False
            )
            
            embed.set_footer(text="GitHub Tracking • Updates checked every 15 minutes")
            
            await channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error sending repo status for {repo_name}: {e}")

# UI Components
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
                value=repo_name,
                emoji="🐙"
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
        
        embed.add_field(name="📢 Channel", value=channel_mention, inline=True)
        embed.add_field(name="👤 Added by", value=added_by_name, inline=True)
        embed.add_field(name="🔔 Your notifications", value="🔔 Enabled" if is_subscribed else "🔕 Disabled", inline=True)
        embed.add_field(name="📅 Added", value=f"<t:{int(repo_data['created_at'].timestamp())}:R>", inline=True)
        
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
            embed.set_field_at(2, name="🔔 Your notifications", value="🔔 Enabled" if new_status else "🔕 Disabled", inline=True)
            
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
            "SELECT * FROM github_tracked_repos WHERE guild_id = $1 ORDER BY created_at DESC",
            self.guild_id
        )
        
        view = RepoListView(self.bot, repos, self.user_id, self.guild_id)
        
        embed = discord.Embed(
            title="🐙 Tracked GitHub Repositories",
            description=f"This server is tracking **{len(repos)}** repositories\n\nSelect a repository below to view details and toggle notifications:",
            color=0x333333
        )
        
        # Add a preview of tracked repos
        repo_list = []
        for i, repo in enumerate(repos[:5]):  # Show first 5
            repo_list.append(f"{i+1}. **{repo['repo_name']}**")
        
        if repo_list:
            embed.add_field(
                name="Currently Tracking",
                value="\n".join(repo_list) + (f"\n... and {len(repos) - 5} more" if len(repos) > 5 else ""),
                inline=False
            )
        
        await interaction.response.edit_message(embed=embed, view=view)

class RepoUpdateView(discord.ui.View):
    def __init__(self, bot, repos, user_id, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.repos = repos
        
        # Add dropdown for repo selection
        self.add_item(RepoUpdateDropdown(bot, repos, user_id, guild_id))

class RepoUpdateDropdown(discord.ui.Select):
    def __init__(self, bot, repos, user_id, guild_id):
        options = []
        for repo in repos[:25]:  # Discord limits to 25 options
            repo_name = repo['repo_name']
            options.append(discord.SelectOption(
                label=repo_name,
                description=f"Get immediate update for {repo_name}",
                value=repo_name,
                emoji="🔄"
            ))
        
        super().__init__(
            placeholder="Select a repository to update immediately...",
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
        
        await interaction.response.defer(ephemeral=True)
        
        selected_repo = self.values[0]
        
        # Get repo details
        repo_data = next((repo for repo in self.repos if repo['repo_name'] == selected_repo), None)
        if not repo_data:
            await interaction.followup.send("Repository not found!", ephemeral=True)
            return
        
        try:
            # Get the GitHub integration cog
            github_cog = self.bot.get_cog('GitHubIntegrations')
            if not github_cog:
                await interaction.followup.send("GitHub integration not available!", ephemeral=True)
                return
            
            # Force check this specific repository
            await github_cog._check_single_repo_updates(repo_data, force_update=True)
            
            embed = EmbedBuilder.success(
                "Repository Updated",
                f"✅ **{selected_repo}** has been checked for updates!\n\n"
                f"Check the tracking channel for any new notifications.\n"
                f"If no updates were posted, the repository is up to date."
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error updating repo {selected_repo}: {e}")
            embed = EmbedBuilder.error("Update Failed", f"Failed to update repository: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

class TrackRepoButtonView(discord.ui.View):
    def __init__(self, repo_name):
        super().__init__(timeout=None)  # Persistent view
        self.repo_name = repo_name
        
        # Add Track Repo button
        track_button = Button(
            label="Track Repo",
            style=discord.ButtonStyle.primary,
            emoji="🐙"
        )
        track_button.callback = self.track_repo_callback
        self.add_item(track_button)
    
    async def track_repo_callback(self, interaction: discord.Interaction):
        try:
            # Check if user is already tracking this repo
            existing = await interaction.client.db.connection.fetchrow(
                "SELECT enabled FROM github_subscriptions WHERE user_id = $1 AND guild_id = $2 AND repo_name = $3",
                str(interaction.user.id), str(interaction.guild.id), self.repo_name
            )
            
            if existing:
                if existing['enabled']:
                    embed = EmbedBuilder.info(
                        "Already Tracking",
                        f"You're already tracking **{self.repo_name}** with notifications enabled!"
                    )
                else:
                    # Re-enable notifications
                    await interaction.client.db.connection.execute(
                        "UPDATE github_subscriptions SET enabled = TRUE WHERE user_id = $1 AND guild_id = $2 AND repo_name = $3",
                        str(interaction.user.id), str(interaction.guild.id), self.repo_name
                    )
                    embed = EmbedBuilder.success(
                        "Notifications Enabled",
                        f"✅ Re-enabled notifications for **{self.repo_name}**!"
                    )
            else:
                # Add new subscription
                await interaction.client.db.connection.execute(
                    """INSERT INTO github_subscriptions (user_id, guild_id, repo_name, enabled) 
                       VALUES ($1, $2, $3, TRUE)""",
                    str(interaction.user.id), str(interaction.guild.id), self.repo_name
                )
                embed = EmbedBuilder.success(
                    "Now Tracking",
                    f"✅ You're now tracking **{self.repo_name}**!\n\n"
                    f"You'll receive notifications for:\n"
                    f"• ⭐ Star changes\n"
                    f"• 📝 New commits\n"
                    f"• 🌿 New/deleted branches"
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in track repo button: {e}")
            embed = EmbedBuilder.error("Error", f"Failed to track repository: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(GitHubIntegrations(bot))
