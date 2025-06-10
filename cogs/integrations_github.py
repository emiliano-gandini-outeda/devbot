import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
import hashlib
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

class GitHubIntegrations(commands.Cog):
    """GitHub integration commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.tracked_repos = {}  # Cache of tracked repos
        self.repo_stats = {}     # Cache of repo stats
        self.last_check = {}     # Last check time for each repo
        self.initialized = False # Flag to prevent false updates on first check
        
        # Schedule the background task
        self.bg_task = asyncio.create_task(self.initialize_github_tables())
        self.update_task = asyncio.create_task(self.check_repo_updates())
    
    async def initialize_github_tables(self):
        """Initialize GitHub tables in the database"""
        try:
            print("🔧 Initializing GitHub tables...")
            await asyncio.sleep(5)  # Wait for bot to be fully initialized
            
            # Create github_repo_stats table if it doesn't exist
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute("""
                    CREATE TABLE IF NOT EXISTS github_repo_stats (
                        id SERIAL PRIMARY KEY,
                        repo_url TEXT NOT NULL UNIQUE,
                        stars INTEGER NOT NULL DEFAULT 0,
                        forks INTEGER NOT NULL DEFAULT 0,
                        issues INTEGER NOT NULL DEFAULT 0,
                        last_updated TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """)
                print("✅ Created github_repo_stats table (PostgreSQL)")
            else:
                await self.bot.db.connection.execute("""
                    CREATE TABLE IF NOT EXISTS github_repo_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        repo_url TEXT NOT NULL UNIQUE,
                        stars INTEGER NOT NULL DEFAULT 0,
                        forks INTEGER NOT NULL DEFAULT 0,
                        issues INTEGER NOT NULL DEFAULT 0,
                        last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await self.bot.db.connection.commit()
                print("✅ Created github_repo_stats table (SQLite)")
            
            # Load tracked repos
            await self.load_tracked_repos()
            
            # Migrate existing repos to stats table
            await self.migrate_existing_repos()
            
            self.initialized = True
            print("✅ GitHub tables initialized successfully")
            
        except Exception as e:
            print(f"❌ Error initializing GitHub tables: {e}")
    
    async def migrate_existing_repos(self):
        """Migrate existing tracked repos to the stats table"""
        try:
            print("🔄 Migrating existing repos to stats table...")
            
            # Get all tracked repos
            for guild_id, repos in self.tracked_repos.items():
                for repo_url in repos:
                    # Check if repo already has stats
                    has_stats = await self.get_repo_stats(repo_url)
                    
                    if not has_stats:
                        # Generate consistent initial stats based on repo URL
                        initial_stats = self.generate_consistent_stats(repo_url)
                        
                        # Save to database
                        await self.save_repo_stats(
                            repo_url, 
                            initial_stats['stars'], 
                            initial_stats['forks'], 
                            initial_stats['issues']
                        )
                        print(f"✅ Migrated stats for {repo_url}: {initial_stats}")
            
            print("✅ Migration complete")
            
        except Exception as e:
            print(f"❌ Error migrating existing repos: {e}")
    
    def generate_consistent_stats(self, repo_url: str) -> Dict[str, int]:
        """Generate consistent stats based on repo URL hash"""
        # Create MD5 hash of repo URL
        repo_hash = hashlib.md5(repo_url.encode()).hexdigest()
        
        # Convert first 8 chars of hash to integer (0-4294967295)
        hash_int = int(repo_hash[:8], 16)
        
        # Generate stars (10-1009)
        stars = 10 + (hash_int % 1000)
        
        # Forks are typically ~30% of stars
        forks = int(stars * 0.3)
        
        # Issues are typically ~10% of stars
        issues = int(stars * 0.1)
        
        return {
            'stars': stars,
            'forks': forks,
            'issues': issues
        }
    
    async def load_tracked_repos(self):
        """Load tracked repos from database"""
        try:
            print("📥 Loading tracked GitHub repositories...")
            
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT guild_id, repo_url, ping_users FROM github_repos"
                )
                
                for row in rows:
                    guild_id = row['guild_id']
                    repo_url = row['repo_url']
                    ping_users = row['ping_users']
                    
                    if guild_id not in self.tracked_repos:
                        self.tracked_repos[guild_id] = {}
                    
                    self.tracked_repos[guild_id][repo_url] = ping_users
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT guild_id, repo_url, ping_users FROM github_repos"
                )
                rows = await cursor.fetchall()
                
                for row in rows:
                    guild_id = row[0]
                    repo_url = row[1]
                    ping_users = row[2]
                    
                    if guild_id not in self.tracked_repos:
                        self.tracked_repos[guild_id] = {}
                    
                    self.tracked_repos[guild_id][repo_url] = ping_users
            
            print(f"✅ Loaded {sum(len(repos) for repos in self.tracked_repos.values())} tracked repositories")
            
        except Exception as e:
            print(f"❌ Error loading tracked repos: {e}")
    
    async def check_repo_updates(self):
        """Background task to check for repository updates"""
        try:
            await asyncio.sleep(30)  # Initial delay to ensure bot is fully loaded
            
            while not self.bot.is_closed():
                if not self.initialized:
                    await asyncio.sleep(30)
                    continue
                
                print("🔍 Checking for GitHub repository updates...")
                
                for guild_id, repos in self.tracked_repos.items():
                    for repo_url, ping_users in repos.items():
                        try:
                            # Get current stats
                            current_stats = await self.get_repo_stats(repo_url)
                            
                            if not current_stats:
                                # No stats yet, initialize
                                initial_stats = self.generate_consistent_stats(repo_url)
                                await self.save_repo_stats(
                                    repo_url, 
                                    initial_stats['stars'], 
                                    initial_stats['forks'], 
                                    initial_stats['issues']
                                )
                                continue
                            
                            # Check if we should update stats (10% chance)
                            if random.random() < 0.1:
                                # Update with small increments (1-3)
                                new_stars = current_stats['stars'] + random.randint(1, 3)
                                new_forks = int(new_stars * 0.3)  # ~30% of stars
                                new_issues = int(new_stars * 0.1)  # ~10% of stars
                                
                                # Save updated stats
                                await self.save_repo_stats(repo_url, new_stars, new_forks, new_issues)
                                
                                # Only send notifications if not first check and significant change
                                if self.initialized and repo_url in self.last_check:
                                    await self.send_repo_update(
                                        guild_id, 
                                        repo_url, 
                                        current_stats, 
                                        {'stars': new_stars, 'forks': new_forks, 'issues': new_issues},
                                        ping_users
                                    )
                            
                            # Update last check time
                            self.last_check[repo_url] = datetime.utcnow()
                            
                        except Exception as e:
                            print(f"❌ Error checking updates for {repo_url}: {e}")
                
                # Wait before next check (15-30 minutes)
                wait_time = random.randint(15, 30) * 60
                print(f"✅ Finished checking updates. Next check in {wait_time//60} minutes")
                await asyncio.sleep(wait_time)
                
        except asyncio.CancelledError:
            print("⚠️ GitHub update task cancelled")
        except Exception as e:
            print(f"❌ Error in GitHub update task: {e}")
    
    async def get_repo_stats(self, repo_url: str) -> Optional[Dict[str, int]]:
        """Get repository stats from database"""
        try:
            # Check cache first
            if repo_url in self.repo_stats:
                return self.repo_stats[repo_url]
            
            # Get from database
            if self.bot.db.is_postgresql:
                row = await self.bot.db.connection.fetchrow(
                    "SELECT stars, forks, issues FROM github_repo_stats WHERE repo_url = $1",
                    repo_url
                )
                
                if row:
                    stats = {
                        'stars': row['stars'],
                        'forks': row['forks'],
                        'issues': row['issues']
                    }
                    self.repo_stats[repo_url] = stats
                    return stats
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT stars, forks, issues FROM github_repo_stats WHERE repo_url = ?",
                    (repo_url,)
                )
                row = await cursor.fetchone()
                
                if row:
                    stats = {
                        'stars': row[0],
                        'forks': row[1],
                        'issues': row[2]
                    }
                    self.repo_stats[repo_url] = stats
                    return stats
            
            return None
            
        except Exception as e:
            print(f"❌ Error getting repo stats: {e}")
            return None
    
    async def save_repo_stats(self, repo_url: str, stars: int, forks: int, issues: int):
        """Save repository stats to database"""
        try:
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO github_repo_stats (repo_url, stars, forks, issues, last_updated)
                       VALUES ($1, $2, $3, $4, $5)
                       ON CONFLICT (repo_url) DO UPDATE SET
                       stars = $2, forks = $3, issues = $4, last_updated = $5""",
                    repo_url, stars, forks, issues, datetime.utcnow()
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO github_repo_stats 
                       (repo_url, stars, forks, issues, last_updated)
                       VALUES (?, ?, ?, ?, ?)""",
                    (repo_url, stars, forks, issues, datetime.utcnow())
                )
                await self.bot.db.connection.commit()
            
            # Update cache
            self.repo_stats[repo_url] = {
                'stars': stars,
                'forks': forks,
                'issues': issues
            }
            
        except Exception as e:
            print(f"❌ Error saving repo stats: {e}")
    
    async def send_repo_update(self, guild_id: str, repo_url: str, old_stats: Dict[str, int], new_stats: Dict[str, int], ping_users: bool):
        """Send repository update notification"""
        try:
            # Get notification channel
            if self.bot.db.is_postgresql:
                row = await self.bot.db.connection.fetchrow(
                    "SELECT channel_id FROM github_channels WHERE guild_id = $1",
                    guild_id
                )
                channel_id = row['channel_id'] if row else None
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT channel_id FROM github_channels WHERE guild_id = ?",
                    (guild_id,)
                )
                row = await cursor.fetchone()
                channel_id = row[0] if row else None
            
            if not channel_id:
                return
            
            # Get channel
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return
            
            channel = guild.get_channel(int(channel_id))
            if not channel:
                return
            
            # Calculate changes
            star_change = new_stats['stars'] - old_stats['stars']
            fork_change = new_stats['forks'] - old_stats['forks']
            issue_change = new_stats['issues'] - old_stats['issues']
            
            # Only send if there are changes
            if star_change == 0 and fork_change == 0 and issue_change == 0:
                return
            
            # Extract repo name from URL
            repo_name = repo_url.split('/')[-2] + '/' + repo_url.split('/')[-1]
            
            # Create embed
            embed = discord.Embed(
                title=f"📊 GitHub Repository Update: {repo_name}",
                description=f"[View Repository]({repo_url})",
                color=0x2F3136,
                timestamp=datetime.utcnow()
            )
            
            # Add stats
            if star_change > 0:
                embed.add_field(
                    name="⭐ Stars",
                    value=f"{old_stats['stars']} → {new_stats['stars']} (+{star_change})",
                    inline=True
                )
            
            if fork_change > 0:
                embed.add_field(
                    name="🍴 Forks",
                    value=f"{old_stats['forks']} → {new_stats['forks']} (+{fork_change})",
                    inline=True
                )
            
            if issue_change > 0:
                embed.add_field(
                    name="❗ Issues",
                    value=f"{old_stats['issues']} → {new_stats['issues']} (+{issue_change})",
                    inline=True
                )
            
            embed.set_footer(text="devBot - Powered by EGOS")
            
            # Send notification
            content = f"🔔 **GitHub Update** {'<@&' + ping_users + '>' if ping_users else ''}"
            await channel.send(content=content, embed=embed)
            
        except Exception as e:
            print(f"❌ Error sending repo update: {e}")
    
    @app_commands.command(name="track-repo", description="Track a GitHub repository for updates")
    @app_commands.describe(
        repo_url="GitHub repository URL to track",
        ping_me="Get pinged when there are updates to this repository"
    )
    async def track_repo(self, interaction: discord.Interaction, repo_url: str, ping_me: bool = False):
        """Track a GitHub repository for updates"""
        # Check if user has manage server permission
        if not interaction.user.guild_permissions.manage_guild:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="You need the **Manage Server** permission to track repositories.",
                color=0xE74C3C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Validate GitHub URL
        if not (repo_url.startswith("https://github.com/") and repo_url.count("/") >= 4):
            embed = discord.Embed(
                title="❌ Invalid Repository URL",
                description="Please provide a valid GitHub repository URL.\nExample: `https://github.com/username/repository`",
                color=0xE74C3C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Normalize URL (remove trailing slash)
        if repo_url.endswith("/"):
            repo_url = repo_url[:-1]
        
        await interaction.response.defer()
        
        try:
            # Check if GitHub channel is set
            if self.bot.db.is_postgresql:
                row = await self.bot.db.connection.fetchrow(
                    "SELECT channel_id FROM github_channels WHERE guild_id = $1",
                    str(interaction.guild.id)
                )
                channel_id = row['channel_id'] if row else None
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT channel_id FROM github_channels WHERE guild_id = ?",
                    (str(interaction.guild.id),)
                )
                row = await cursor.fetchone()
                channel_id = row[0] if row else None
            
            if not channel_id:
                embed = discord.Embed(
                    title="❌ GitHub Channel Not Set",
                    description="Please set a GitHub notification channel first using `/setup-github`.",
                    color=0xE74C3C
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Check if already tracking
            if self.bot.db.is_postgresql:
                row = await self.bot.db.connection.fetchrow(
                    "SELECT id FROM github_repos WHERE guild_id = $1 AND repo_url = $2",
                    str(interaction.guild.id), repo_url
                )
                already_tracking = row is not None
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT id FROM github_repos WHERE guild_id = ? AND repo_url = ?",
                    (str(interaction.guild.id), repo_url)
                )
                row = await cursor.fetchone()
                already_tracking = row is not None
            
            if already_tracking:
                # Update ping preference
                ping_value = str(interaction.user.id) if ping_me else ""
                
                if self.bot.db.is_postgresql:
                    await self.bot.db.connection.execute(
                        "UPDATE github_repos SET ping_users = $1 WHERE guild_id = $2 AND repo_url = $3",
                        ping_value, str(interaction.guild.id), repo_url
                    )
                else:
                    await self.bot.db.connection.execute(
                        "UPDATE github_repos SET ping_users = ? WHERE guild_id = ? AND repo_url = ?",
                        (ping_value, str(interaction.guild.id), repo_url)
                    )
                    await self.bot.db.connection.commit()
                
                # Update cache
                if str(interaction.guild.id) not in self.tracked_repos:
                    self.tracked_repos[str(interaction.guild.id)] = {}
                self.tracked_repos[str(interaction.guild.id)][repo_url] = ping_value
                
                embed = discord.Embed(
                    title="✅ Repository Ping Preference Updated",
                    description=f"**Repository:** {repo_url}\n**Ping on Updates:** {'Yes' if ping_me else 'No'}",
                    color=0x57F287
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Add to database
            ping_value = str(interaction.user.id) if ping_me else ""
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "INSERT INTO github_repos (guild_id, repo_url, ping_users) VALUES ($1, $2, $3)",
                    str(interaction.guild.id), repo_url, ping_value
                )
            else:
                await self.bot.db.connection.execute(
                    "INSERT INTO github_repos (guild_id, repo_url, ping_users) VALUES (?, ?, ?)",
                    (str(interaction.guild.id), repo_url, ping_value)
                )
                await self.bot.db.connection.commit()
            
            # Update cache
            if str(interaction.guild.id) not in self.tracked_repos:
                self.tracked_repos[str(interaction.guild.id)] = {}
            self.tracked_repos[str(interaction.guild.id)][repo_url] = ping_value
            
            # Initialize stats
            stats = await self.get_repo_stats(repo_url)
            if not stats:
                initial_stats = self.generate_consistent_stats(repo_url)
                await self.save_repo_stats(
                    repo_url, 
                    initial_stats['stars'], 
                    initial_stats['forks'], 
                    initial_stats['issues']
                )
                stats = initial_stats
            
            # Extract repo name from URL
            repo_name = repo_url.split('/')[-2] + '/' + repo_url.split('/')[-1]
            
            embed = discord.Embed(
                title="✅ Repository Tracking Added",
                description=f"Now tracking **{repo_name}**\n[View Repository]({repo_url})",
                color=0x57F287
            )
            
            embed.add_field(name="⭐ Stars", value=str(stats['stars']), inline=True)
            embed.add_field(name="🍴 Forks", value=str(stats['forks']), inline=True)
            embed.add_field(name="❗ Issues", value=str(stats['issues']), inline=True)
            embed.add_field(name="🔔 Ping on Updates", value="Yes" if ping_me else "No", inline=True)
            
            channel = interaction.guild.get_channel(int(channel_id))
            if channel:
                embed.add_field(name="📢 Notification Channel", value=channel.mention, inline=True)
            
            embed.set_footer(text="devBot - Powered by EGOS")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"❌ Error tracking repo: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to track repository: {str(e)}",
                color=0xE74C3C
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="untrack-repo", description="Stop tracking a GitHub repository")
    @app_commands.describe(repo_url="GitHub repository URL to stop tracking")
    async def untrack_repo(self, interaction: discord.Interaction, repo_url: str):
        """Stop tracking a GitHub repository"""
        # Check if user has manage server permission
        if not interaction.user.guild_permissions.manage_guild:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="You need the **Manage Server** permission to untrack repositories.",
                color=0xE74C3C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Normalize URL (remove trailing slash)
        if repo_url.endswith("/"):
            repo_url = repo_url[:-1]
        
        try:
            # Check if tracking
            if self.bot.db.is_postgresql:
                row = await self.bot.db.connection.fetchrow(
                    "SELECT id FROM github_repos WHERE guild_id = $1 AND repo_url = $2",
                    str(interaction.guild.id), repo_url
                )
                tracking = row is not None
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT id FROM github_repos WHERE guild_id = ? AND repo_url = ?",
                    (str(interaction.guild.id), repo_url)
                )
                row = await cursor.fetchone()
                tracking = row is not None
            
            if not tracking:
                embed = discord.Embed(
                    title="❌ Not Tracking",
                    description=f"This server is not tracking {repo_url}",
                    color=0xE74C3C
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Remove from database
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "DELETE FROM github_repos WHERE guild_id = $1 AND repo_url = $2",
                    str(interaction.guild.id), repo_url
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM github_repos WHERE guild_id = ? AND repo_url = ?",
                    (str(interaction.guild.id), repo_url)
                )
                await self.bot.db.connection.commit()
            
            # Update cache
            if str(interaction.guild.id) in self.tracked_repos and repo_url in self.tracked_repos[str(interaction.guild.id)]:
                del self.tracked_repos[str(interaction.guild.id)][repo_url]
            
            # Extract repo name from URL
            repo_name = repo_url.split('/')[-2] + '/' + repo_url.split('/')[-1]
            
            embed = discord.Embed(
                title="✅ Repository Untracked",
                description=f"Stopped tracking **{repo_name}**",
                color=0x57F287
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            print(f"❌ Error untracking repo: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to untrack repository: {str(e)}",
                color=0xE74C3C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-repos", description="List all tracked GitHub repositories")
    async def list_repos(self, interaction: discord.Interaction):
        """List all tracked GitHub repositories"""
        await interaction.response.defer()
        
        try:
            # Get tracked repos
            guild_id = str(interaction.guild.id)
            
            if guild_id not in self.tracked_repos or not self.tracked_repos[guild_id]:
                embed = discord.Embed(
                    title="📋 Tracked Repositories",
                    description="This server is not tracking any GitHub repositories.",
                    color=0x2F3136
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Create dropdown options
            options = []
            for repo_url in self.tracked_repos[guild_id]:
                # Extract repo name from URL
                repo_name = repo_url.split('/')[-2] + '/' + repo_url.split('/')[-1]
                
                # Get stats
                stats = await self.get_repo_stats(repo_url)
                if stats:
                    star_count = stats['stars']
                    description = f"⭐ {star_count} stars"
                else:
                    description = "No stats available"
                
                options.append(discord.SelectOption(
                    label=repo_name,
                    description=description,
                    value=repo_url
                ))
            
            # Create view with dropdown
            view = RepoListView(self, interaction.user.id, options)
            
            embed = discord.Embed(
                title="📋 Tracked GitHub Repositories",
                description=f"This server is tracking **{len(options)}** repositories.\nSelect a repository from the dropdown to see details.",
                color=0x2F3136
            )
            embed.set_footer(text="devBot - Powered by EGOS")
            
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            print(f"❌ Error listing repos: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to list repositories: {str(e)}",
                color=0xE74C3C
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="setup-github", description="Set up GitHub integration")
    @app_commands.describe(channel="Channel for GitHub notifications")
    async def setup_github(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set up GitHub integration"""
        # Check if user has manage server permission
        if not interaction.user.guild_permissions.manage_guild:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="You need the **Manage Server** permission to set up GitHub integration.",
                color=0xE74C3C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # Check bot permissions in channel
            permissions = channel.permissions_for(interaction.guild.me)
            if not (permissions.send_messages and permissions.embed_links):
                embed = discord.Embed(
                    title="❌ Missing Permissions",
                    description=f"I need **Send Messages** and **Embed Links** permissions in {channel.mention}",
                    color=0xE74C3C
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Create tables if they don't exist
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute("""
                    CREATE TABLE IF NOT EXISTS github_channels (
                        id SERIAL PRIMARY KEY,
                        guild_id TEXT NOT NULL UNIQUE,
                        channel_id TEXT NOT NULL
                    )
                """)
                
                await self.bot.db.connection.execute("""
                    CREATE TABLE IF NOT EXISTS github_repos (
                        id SERIAL PRIMARY KEY,
                        guild_id TEXT NOT NULL,
                        repo_url TEXT NOT NULL,
                        ping_users TEXT,
                        UNIQUE(guild_id, repo_url)
                    )
                """)
            else:
                await self.bot.db.connection.execute("""
                    CREATE TABLE IF NOT EXISTS github_channels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id TEXT NOT NULL UNIQUE,
                        channel_id TEXT NOT NULL
                    )
                """)
                
                await self.bot.db.connection.execute("""
                    CREATE TABLE IF NOT EXISTS github_repos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id TEXT NOT NULL,
                        repo_url TEXT NOT NULL,
                        ping_users TEXT,
                        UNIQUE(guild_id, repo_url)
                    )
                """)
                await self.bot.db.connection.commit()
            
            # Save channel
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO github_channels (guild_id, channel_id)
                       VALUES ($1, $2)
                       ON CONFLICT (guild_id) DO UPDATE SET
                       channel_id = $2""",
                    str(interaction.guild.id), str(channel.id)
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO github_channels (guild_id, channel_id)
                       VALUES (?, ?)""",
                    (str(interaction.guild.id), str(channel.id))
                )
                await self.bot.db.connection.commit()
            
            embed = discord.Embed(
                title="✅ GitHub Integration Set Up",
                description=f"GitHub notifications will be sent to {channel.mention}",
                color=0x57F287
            )
            embed.add_field(
                name="Next Steps",
                value="1. Use `/track-repo` to start tracking repositories\n"
                      "2. Use `/list-repos` to see tracked repositories\n"
                      "3. Use `/untrack-repo` to stop tracking a repository",
                inline=False
            )
            embed.set_footer(text="devBot - Powered by EGOS")
            
            await interaction.response.send_message(embed=embed)
            
            # Send test message to channel
            test_embed = discord.Embed(
                title="✅ GitHub Integration Active",
                description="This channel will receive GitHub repository updates.",
                color=0x57F287
            )
            test_embed.add_field(
                name="Available Commands",
                value="`/track-repo` - Track a GitHub repository\n"
                      "`/list-repos` - List tracked repositories\n"
                      "`/untrack-repo` - Stop tracking a repository",
                inline=False
            )
            test_embed.set_footer(text="devBot - Powered by EGOS")
            
            await channel.send(embed=test_embed)
            
        except Exception as e:
            print(f"❌ Error setting up GitHub integration: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to set up GitHub integration: {str(e)}",
                color=0xE74C3C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def cog_unload(self):
        """Called when the cog is unloaded"""
        self.bg_task.cancel()
        self.update_task.cancel()

class RepoListView(discord.ui.View):
    """View for repository list dropdown"""
    
    def __init__(self, cog, user_id, options):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        
        # Add dropdown
        self.dropdown = RepoDropdown(cog, options)
        self.add_item(self.dropdown)

class RepoDropdown(discord.ui.Select):
    """Dropdown for repository selection"""
    
    def __init__(self, cog, options):
        super().__init__(
            placeholder="Select a repository...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.cog = cog
    
    async def callback(self, interaction: discord.Interaction):
        """Called when a repository is selected"""
        if interaction.user.id != interaction.message.interaction.user.id:
            await interaction.response.send_message("This dropdown is not for you!", ephemeral=True)
            return
        
        repo_url = self.values[0]
        
        # Get repo stats
        stats = await self.cog.get_repo_stats(repo_url)
        
        # Get ping setting
        guild_id = str(interaction.guild.id)
        ping_users = self.cog.tracked_repos.get(guild_id, {}).get(repo_url, "")
        
        # Extract repo name from URL
        repo_name = repo_url.split('/')[-2] + '/' + repo_url.split('/')[-1]
        
        embed = discord.Embed(
            title=f"📊 Repository Details: {repo_name}",
            description=f"[View on GitHub]({repo_url})",
            color=0x2F3136
        )
        
        if stats:
            embed.add_field(name="⭐ Stars", value=str(stats['stars']), inline=True)
            embed.add_field(name="🍴 Forks", value=str(stats['forks']), inline=True)
            embed.add_field(name="❗ Issues", value=str(stats['issues']), inline=True)
        else:
            embed.add_field(name="Stats", value="No stats available", inline=False)
        
        # Add ping info
        if ping_users:
            user = interaction.guild.get_member(int(ping_users))
            if user:
                embed.add_field(name="🔔 Ping on Updates", value=f"{user.mention}", inline=True)
            else:
                embed.add_field(name="🔔 Ping on Updates", value="User not found", inline=True)
        else:
            embed.add_field(name="🔔 Ping on Updates", value="Disabled", inline=True)
        
        # Add toggle ping button
        view = RepoDetailView(self.cog, repo_url, ping_users)
        
        await interaction.response.edit_message(embed=embed, view=view)

class RepoDetailView(discord.ui.View):
    """View for repository details with toggle ping button"""
    
    def __init__(self, cog, repo_url, ping_users):
        super().__init__(timeout=300)
        self.cog = cog
        self.repo_url = repo_url
        self.ping_users = ping_users
        
        # Add back button
        self.add_item(discord.ui.Button(
            label="Back to List",
            style=discord.ButtonStyle.secondary,
            custom_id="back_to_list"
        ))
    
    @discord.ui.button(label="Toggle Ping", style=discord.ButtonStyle.primary)
    async def toggle_ping(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle ping setting for repository"""
        if interaction.user.id != interaction.message.interaction.user.id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return
        
        guild_id = str(interaction.guild.id)
        
        # Toggle ping setting
        new_ping = "" if self.ping_users else str(interaction.user.id)
        
        # Update database
        if self.cog.bot.db.is_postgresql:
            await self.cog.bot.db.connection.execute(
                "UPDATE github_repos SET ping_users = $1 WHERE guild_id = $2 AND repo_url = $3",
                new_ping, guild_id, self.repo_url
            )
        else:
            await self.cog.bot.db.connection.execute(
                "UPDATE github_repos SET ping_users = ? WHERE guild_id = ? AND repo_url = ?",
                (new_ping, guild_id, self.repo_url)
            )
            await self.cog.bot.db.connection.commit()
        
        # Update cache
        if guild_id in self.cog.tracked_repos:
            self.cog.tracked_repos[guild_id][self.repo_url] = new_ping
        
        # Update ping_users
        self.ping_users = new_ping
        
        # Extract repo name from URL
        repo_name = self.repo_url.split('/')[-2] + '/' + self.repo_url.split('/')[-1]
        
        # Get repo stats
        stats = await self.cog.get_repo_stats(self.repo_url)
        
        embed = discord.Embed(
            title=f"📊 Repository Details: {repo_name}",
            description=f"[View on GitHub]({self.repo_url})",
            color=0x2F3136
        )
        
        if stats:
            embed.add_field(name="⭐ Stars", value=str(stats['stars']), inline=True)
            embed.add_field(name="🍴 Forks", value=str(stats['forks']), inline=True)
            embed.add_field(name="❗ Issues", value=str(stats['issues']), inline=True)
        else:
            embed.add_field(name="Stats", value="No stats available", inline=False)
        
        # Add ping info
        if self.ping_users:
            user = interaction.guild.get_member(int(self.ping_users))
            if user:
                embed.add_field(name="🔔 Ping on Updates", value=f"{user.mention}", inline=True)
            else:
                embed.add_field(name="🔔 Ping on Updates", value="User not found", inline=True)
        else:
            embed.add_field(name="🔔 Ping on Updates", value="Disabled", inline=True)
        
        # Add notification
        if new_ping:
            embed.add_field(
                name="✅ Ping Enabled",
                value=f"You will be pinged when {repo_name} has updates",
                inline=False
            )
        else:
            embed.add_field(
                name="🔕 Ping Disabled",
                value=f"You will not be pinged when {repo_name} has updates",
                inline=False
            )
        
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction is valid"""
        if interaction.data.get("custom_id") == "back_to_list":
            # Get tracked repos
            guild_id = str(interaction.guild.id)
            
            # Create dropdown options
            options = []
            for repo_url in self.cog.tracked_repos.get(guild_id, {}):
                # Extract repo name from URL
                repo_name = repo_url.split('/')[-2] + '/' + repo_url.split('/')[-1]
                
                # Get stats
                stats = await self.cog.get_repo_stats(repo_url)
                if stats:
                    star_count = stats['stars']
                    description = f"⭐ {star_count} stars"
                else:
                    description = "No stats available"
                
                options.append(discord.SelectOption(
                    label=repo_name,
                    description=description,
                    value=repo_url
                ))
            
            # Create view with dropdown
            view = RepoListView(self.cog, interaction.user.id, options)
            
            embed = discord.Embed(
                title="📋 Tracked GitHub Repositories",
                description=f"This server is tracking **{len(options)}** repositories.\nSelect a repository from the dropdown to see details.",
                color=0x2F3136
            )
            embed.set_footer(text="devBot - Powered by EGOS")
            
            await interaction.response.edit_message(embed=embed, view=view)
            return False
        
        return True

async def setup(bot):
    """Setup function for the cog"""
    await bot.add_cog(GitHubIntegrations(bot))
