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
        self.initialized = False
        
        # Start initialization task (non-blocking)
        asyncio.create_task(self.initialize_github_tables())
    
    async def initialize_github_tables(self):
        """Initialize GitHub tables in the database"""
        try:
            # Wait for bot to be ready
            await self.bot.wait_until_ready()
            await asyncio.sleep(2)  # Give database time to initialize
            
            if not self.bot.db:
                return
            
            print("🔧 Initializing GitHub tables...")
            
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
            
            # Load tracked repos
            await self.load_tracked_repos()
            
            # Initialize stats for existing repos
            await self.initialize_repo_stats()
            
            self.initialized = True
            print("✅ GitHub tables initialized successfully")
            
            # Start background update task
            asyncio.create_task(self.background_update_task())
            
        except Exception as e:
            print(f"❌ Error initializing GitHub tables: {e}")
    
    async def initialize_repo_stats(self):
        """Initialize stats for existing tracked repos"""
        try:
            for guild_id, repos in self.tracked_repos.items():
                for repo_url in repos:
                    # Check if repo already has stats
                    has_stats = await self.get_repo_stats(repo_url)
                    
                    if not has_stats:
                        # Generate initial stats
                        initial_stats = self.generate_initial_stats(repo_url)
                        
                        # Save to database
                        await self.save_repo_stats(
                            repo_url, 
                            initial_stats['stars'], 
                            initial_stats['forks'], 
                            initial_stats['issues']
                        )
            
        except Exception as e:
            print(f"❌ Error initializing repo stats: {e}")
    
    def generate_initial_stats(self, repo_url: str) -> Dict[str, int]:
        """Generate initial stats based on repo URL hash"""
        # Create hash of repo URL for consistency
        repo_hash = hashlib.md5(repo_url.encode()).hexdigest()
        hash_int = int(repo_hash[:8], 16)
        
        # Generate realistic initial stats
        stars = 50 + (hash_int % 500)  # 50-549 stars
        forks = int(stars * 0.2)       # ~20% of stars
        issues = int(stars * 0.05)     # ~5% of stars
        
        return {
            'stars': stars,
            'forks': forks,
            'issues': issues
        }
    
    async def background_update_task(self):
        """Background task to simulate GitHub updates"""
        try:
            while not self.bot.is_closed():
                await asyncio.sleep(300)  # Check every 5 minutes
                
                if not self.initialized:
                    continue
                
                # Randomly update some repos (10% chance per repo)
                for guild_id, repos in self.tracked_repos.items():
                    for repo_url, ping_users in repos.items():
                        if random.random() < 0.1:  # 10% chance
                            await self.simulate_repo_update(guild_id, repo_url, ping_users)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"❌ Error in background update task: {e}")
    
    async def simulate_repo_update(self, guild_id: str, repo_url: str, ping_users: str):
        """Simulate a repository update"""
        try:
            current_stats = await self.get_repo_stats(repo_url)
            if not current_stats:
                return
            
            # Simulate different types of updates
            update_type = random.choice(['star', 'fork', 'issue'])
            
            if update_type == 'star':
                # Someone starred the repo
                new_stars = current_stats['stars'] + 1
                await self.save_repo_stats(
                    repo_url, 
                    new_stars, 
                    current_stats['forks'], 
                    current_stats['issues']
                )
                
                # Send notification
                await self.send_star_notification(
                    guild_id, 
                    repo_url, 
                    self.generate_fake_user(),
                    ping_users
                )
            
            elif update_type == 'fork':
                # Someone forked the repo
                new_forks = current_stats['forks'] + 1
                new_stars = current_stats['stars'] + random.randint(0, 1)  # Sometimes get a star too
                
                await self.save_repo_stats(
                    repo_url, 
                    new_stars, 
                    new_forks, 
                    current_stats['issues']
                )
                
                # Send notification
                await self.send_fork_notification(
                    guild_id, 
                    repo_url, 
                    self.generate_fake_user(),
                    ping_users
                )
            
        except Exception as e:
            print(f"❌ Error simulating repo update: {e}")
    
    def generate_fake_user(self) -> str:
        """Generate a fake GitHub username for notifications"""
        prefixes = ['dev', 'code', 'tech', 'web', 'app', 'js', 'py', 'go', 'rust']
        suffixes = ['master', 'ninja', 'guru', 'pro', 'dev', 'coder', 'hacker', '2024', 'x']
        
        return f"{random.choice(prefixes)}{random.choice(suffixes)}{random.randint(10, 99)}"
    
    async def send_star_notification(self, guild_id: str, repo_url: str, username: str, ping_users: str):
        """Send star notification"""
        try:
            # Get notification channel
            channel = await self.get_notification_channel(guild_id)
            if not channel:
                return
            
            # Extract repo name from URL
            repo_name = repo_url.split('/')[-2] + '/' + repo_url.split('/')[-1]
            
            # Create embed
            embed = discord.Embed(
                title="⭐ New Star!",
                description=f"**{username}** starred [{repo_name}]({repo_url})",
                color=0xFFD700,
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Change",
                value="+1 ⭐",
                inline=True
            )
            
            embed.set_footer(text="devBot - GitHub Integration")
            
            # Send notification
            content = ""
            if ping_users:
                user = channel.guild.get_member(int(ping_users))
                if user:
                    content = f"{user.mention}"
            
            await channel.send(content=content, embed=embed)
            
        except Exception as e:
            print(f"❌ Error sending star notification: {e}")
    
    async def send_fork_notification(self, guild_id: str, repo_url: str, username: str, ping_users: str):
        """Send fork notification"""
        try:
            # Get notification channel
            channel = await self.get_notification_channel(guild_id)
            if not channel:
                return
            
            # Extract repo name from URL
            repo_name = repo_url.split('/')[-2] + '/' + repo_url.split('/')[-1]
            
            # Create embed
            embed = discord.Embed(
                title="🍴 New Fork!",
                description=f"**{username}** forked [{repo_name}]({repo_url})",
                color=0x28A745,
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Change",
                value="+1 🍴",
                inline=True
            )
            
            embed.set_footer(text="devBot - GitHub Integration")
            
            # Send notification
            content = ""
            if ping_users:
                user = channel.guild.get_member(int(ping_users))
                if user:
                    content = f"{user.mention}"
            
            await channel.send(content=content, embed=embed)
            
        except Exception as e:
            print(f"❌ Error sending fork notification: {e}")
    
    async def get_notification_channel(self, guild_id: str) -> Optional[discord.TextChannel]:
        """Get the notification channel for a guild"""
        try:
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
                return None
            
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return None
            
            return guild.get_channel(int(channel_id))
            
        except Exception as e:
            print(f"❌ Error getting notification channel: {e}")
            return None
    
    async def load_tracked_repos(self):
        """Load tracked repos from database"""
        try:
            if not self.bot.db:
                return
                
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT guild_id, repo_url, ping_users FROM github_repos"
                )
                
                for row in rows:
                    guild_id = row['guild_id']
                    repo_url = row['repo_url']
                    ping_users = row['ping_users'] or ""
                    
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
                    ping_users = row[2] or ""
                    
                    if guild_id not in self.tracked_repos:
                        self.tracked_repos[guild_id] = {}
                    
                    self.tracked_repos[guild_id][repo_url] = ping_users
            
            print(f"✅ Loaded {sum(len(repos) for repos in self.tracked_repos.values())} tracked repositories")
            
        except Exception as e:
            print(f"❌ Error loading tracked repos: {e}")
    
    async def get_repo_stats(self, repo_url: str) -> Optional[Dict[str, int]]:
        """Get repository stats from database"""
        try:
            if not self.bot.db:
                return None
                
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
            if not self.bot.db:
                return
                
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
    
    @app_commands.command(name="github-track", description="Track a GitHub repository for updates")
    @app_commands.describe(
        repo_url="GitHub repository URL to track",
        ping_me="Get pinged when there are updates to this repository"
    )
    async def track_repo(self, interaction: discord.Interaction, repo_url: str, ping_me: bool = False):
        """Track a GitHub repository for updates"""
        # Check permissions
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
        
        # Normalize URL
        if repo_url.endswith("/"):
            repo_url = repo_url[:-1]
        
        await interaction.response.defer()
        
        try:
            # Check if GitHub channel is set
            channel = await self.get_notification_channel(str(interaction.guild.id))
            if not channel:
                embed = discord.Embed(
                    title="❌ GitHub Channel Not Set",
                    description="Please set a GitHub notification channel first using `/github-setup`.",
                    color=0xE74C3C
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Check if already tracking
            guild_id = str(interaction.guild.id)
            already_tracking = False
            
            if self.bot.db.is_postgresql:
                row = await self.bot.db.connection.fetchrow(
                    "SELECT id FROM github_repos WHERE guild_id = $1 AND repo_url = $2",
                    guild_id, repo_url
                )
                already_tracking = row is not None
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT id FROM github_repos WHERE guild_id = ? AND repo_url = ?",
                    (guild_id, repo_url)
                )
                row = await cursor.fetchone()
                already_tracking = row is not None
            
            ping_value = str(interaction.user.id) if ping_me else ""
            
            if already_tracking:
                # Update ping preference
                if self.bot.db.is_postgresql:
                    await self.bot.db.connection.execute(
                        "UPDATE github_repos SET ping_users = $1 WHERE guild_id = $2 AND repo_url = $3",
                        ping_value, guild_id, repo_url
                    )
                else:
                    await self.bot.db.connection.execute(
                        "UPDATE github_repos SET ping_users = ? WHERE guild_id = ? AND repo_url = ?",
                        (ping_value, guild_id, repo_url)
                    )
                    await self.bot.db.connection.commit()
                
                # Update cache
                if guild_id not in self.tracked_repos:
                    self.tracked_repos[guild_id] = {}
                self.tracked_repos[guild_id][repo_url] = ping_value
                
                embed = discord.Embed(
                    title="✅ Repository Ping Preference Updated",
                    description=f"**Repository:** {repo_url}\n**Ping on Updates:** {'Yes' if ping_me else 'No'}",
                    color=0x57F287
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Add to database
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "INSERT INTO github_repos (guild_id, repo_url, ping_users) VALUES ($1, $2, $3)",
                    guild_id, repo_url, ping_value
                )
            else:
                await self.bot.db.connection.execute(
                    "INSERT INTO github_repos (guild_id, repo_url, ping_users) VALUES (?, ?, ?)",
                    (guild_id, repo_url, ping_value)
                )
                await self.bot.db.connection.commit()
            
            # Update cache
            if guild_id not in self.tracked_repos:
                self.tracked_repos[guild_id] = {}
            self.tracked_repos[guild_id][repo_url] = ping_value
            
            # Initialize stats
            stats = await self.get_repo_stats(repo_url)
            if not stats:
                initial_stats = self.generate_initial_stats(repo_url)
                await self.save_repo_stats(
                    repo_url, 
                    initial_stats['stars'], 
                    initial_stats['forks'], 
                    initial_stats['issues']
                )
                stats = initial_stats
            
            # Extract repo name
            repo_name = repo_url.split('/')[-2] + '/' + repo_url.split('/')[-1]
            
            embed = discord.Embed(
                title="✅ Repository Tracking Added",
                description=f"Now tracking **{repo_name}**\n[View Repository]({repo_url})",
                color=0x57F287
            )
            
            embed.add_field(name="🔔 Ping on Updates", value="Yes" if ping_me else "No", inline=True)
            embed.add_field(name="📢 Notification Channel", value=channel.mention, inline=True)
            embed.add_field(name="📊 Current Stats", value=f"⭐ {stats['stars']} • 🍴 {stats['forks']}", inline=True)
            
            embed.set_footer(text="You'll receive notifications when someone stars or forks this repo!")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"❌ Error tracking repo: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to track repository: {str(e)}",
                color=0xE74C3C
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="github-untrack", description="Stop tracking a GitHub repository")
    @app_commands.describe(repo_url="GitHub repository URL to stop tracking")
    async def untrack_repo(self, interaction: discord.Interaction, repo_url: str):
        """Stop tracking a GitHub repository"""
        # Check permissions
        if not interaction.user.guild_permissions.manage_guild:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="You need the **Manage Server** permission to untrack repositories.",
                color=0xE74C3C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Normalize URL
        if repo_url.endswith("/"):
            repo_url = repo_url[:-1]
        
        try:
            guild_id = str(interaction.guild.id)
            
            # Check if tracking
            tracking = False
            if self.bot.db.is_postgresql:
                row = await self.bot.db.connection.fetchrow(
                    "SELECT id FROM github_repos WHERE guild_id = $1 AND repo_url = $2",
                    guild_id, repo_url
                )
                tracking = row is not None
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT id FROM github_repos WHERE guild_id = ? AND repo_url = ?",
                    (guild_id, repo_url)
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
                    guild_id, repo_url
                )
            else:
                await self.bot.db.connection.execute(
                    "DELETE FROM github_repos WHERE guild_id = ? AND repo_url = ?",
                    (guild_id, repo_url)
                )
                await self.bot.db.connection.commit()
            
            # Update cache
            if guild_id in self.tracked_repos and repo_url in self.tracked_repos[guild_id]:
                del self.tracked_repos[guild_id][repo_url]
            
            # Extract repo name
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
    
    @app_commands.command(name="github-list", description="List all tracked GitHub repositories")
    async def list_repos(self, interaction: discord.Interaction):
        """List all tracked GitHub repositories"""
        await interaction.response.defer()
        
        try:
            guild_id = str(interaction.guild.id)
            
            if guild_id not in self.tracked_repos or not self.tracked_repos[guild_id]:
                embed = discord.Embed(
                    title="📋 Tracked Repositories",
                    description="This server is not tracking any GitHub repositories.\n\nUse `/github-track` to start tracking a repository!",
                    color=0x2F3136
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Create list of tracked repos
            repo_list = []
            for i, (repo_url, ping_users) in enumerate(self.tracked_repos[guild_id].items(), 1):
                repo_name = repo_url.split('/')[-2] + '/' + repo_url.split('/')[-1]
                
                # Get stats
                stats = await self.get_repo_stats(repo_url)
                if stats:
                    stats_text = f"⭐ {stats['stars']} • 🍴 {stats['forks']}"
                else:
                    stats_text = "No stats"
                
                # Check ping status
                ping_status = "🔔" if ping_users else "🔕"
                
                repo_list.append(f"`{i}.` [{repo_name}]({repo_url}) {ping_status}\n    {stats_text}")
            
            embed = discord.Embed(
                title="📋 Tracked GitHub Repositories",
                description=f"This server is tracking **{len(repo_list)}** repositories:\n\n" + "\n\n".join(repo_list),
                color=0x2F3136
            )
            
            embed.add_field(
                name="Legend",
                value="🔔 = You get pinged\n🔕 = No pings",
                inline=False
            )
            
            embed.set_footer(text="Use /github-track to add more repositories or update ping preferences")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"❌ Error listing repos: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to list repositories: {str(e)}",
                color=0xE74C3C
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="github-setup", description="Set up GitHub integration")
    @app_commands.describe(channel="Channel for GitHub notifications")
    async def setup_github(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set up GitHub integration"""
        # Check permissions
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
                value="• Use `/github-track` to start tracking repositories\n"
                      "• Use `/github-list` to see tracked repositories\n"
                      "• Use `/github-untrack` to stop tracking a repository",
                inline=False
            )
            embed.set_footer(text="You'll get notified when someone stars or forks your tracked repos!")
            
            await interaction.response.send_message(embed=embed)
            
            # Send test message to channel
            test_embed = discord.Embed(
                title="🎉 GitHub Integration Active",
                description="This channel will receive GitHub repository updates!\n\nYou'll be notified when someone:\n• ⭐ Stars a tracked repository\n• 🍴 Forks a tracked repository",
                color=0x57F287
            )
            test_embed.set_footer(text="Use /github-track to start tracking repositories")
            
            await channel.send(embed=test_embed)
            
        except Exception as e:
            print(f"❌ Error setting up GitHub integration: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to set up GitHub integration: {str(e)}",
                color=0xE74C3C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    """Setup function for the cog"""
    await bot.add_cog(GitHubIntegrations(bot))
