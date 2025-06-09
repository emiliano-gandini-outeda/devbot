import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import json
from datetime import datetime
from utils.helpers import EmbedBuilder
import asyncio

class GitHubIntegrations(commands.Cog):
    """GitHub repository tracking and integration"""
    
    def __init__(self, bot):
        self.bot = bot
        self.tracked_repos = {}  # guild_id -> [repo_data]
        self.check_updates_task = self.bot.loop.create_task(self.check_updates_loop())
    
    def cog_unload(self):
        """Cancel background task when cog is unloaded"""
        self.check_updates_task.cancel()
    
    async def load_tracked_repos(self):
        """Load tracked repositories from database"""
        try:
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT user_id, data_content FROM user_data WHERE data_type = 'github_repos'"
                )
                for row in rows:
                    guild_id = row['user_id']  # user_id field stores guild_id for configs
                    repos = row['data_content']
                    self.tracked_repos[guild_id] = repos
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT user_id, data_content FROM user_data WHERE data_type = 'github_repos'"
                )
                rows = await cursor.fetchall()
                for row in rows:
                    guild_id = row[0]  # user_id field stores guild_id for configs
                    repos = json.loads(row[1])
                    self.tracked_repos[guild_id] = repos
        except Exception as e:
            print(f"Error loading tracked repos: {e}")
    
    async def save_tracked_repos(self, guild_id: str):
        """Save tracked repositories to database"""
        try:
            repos = self.tracked_repos.get(guild_id, [])
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO user_data (user_id, data_type, data_content) 
                       VALUES ($1, $2, $3) 
                       ON CONFLICT (user_id, data_type) DO UPDATE SET data_content = $3""",
                    guild_id, 'github_repos', json.dumps(repos)
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO user_data (user_id, data_type, data_content) 
                       VALUES (?, ?, ?)""",
                    (guild_id, 'github_repos', json.dumps(repos))
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error saving tracked repos: {e}")
    
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
        
        # Check if repo exists and get initial data
        try:
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
            
            # Get latest commit
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.github.com/repos/{repo}/commits", 
                                      headers={"Accept": "application/vnd.github.v3+json"}) as response:
                    commits = await response.json()
                    latest_commit = commits[0] if commits and isinstance(commits, list) else None
            
            # Store tracking info
            guild_id = str(interaction.guild.id)
            if guild_id not in self.tracked_repos:
                self.tracked_repos[guild_id] = []
            
            # Check if already tracking
            for tracked in self.tracked_repos[guild_id]:
                if tracked.get('repo') == repo and tracked.get('channel_id') == str(channel.id):
                    embed = EmbedBuilder.warning(
                        "Already Tracking", 
                        f"Already tracking {repo} in {channel.mention}"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
            
            # Add to tracked repos
            self.tracked_repos[guild_id].append({
                'repo': repo,
                'channel_id': str(channel.id),
                'added_by': str(interaction.user.id),
                'added_at': datetime.utcnow().isoformat(),
                'last_commit': latest_commit['sha'] if latest_commit else None,
                'stars': repo_data['stargazers_count'],
                'last_checked': datetime.utcnow().isoformat()
            })
            
            # Save to database
            await self.save_tracked_repos(guild_id)
            
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
            
            if latest_commit:
                commit_msg = latest_commit['commit']['message']
                if len(commit_msg) > 100:
                    commit_msg = commit_msg[:97] + "..."
                embed.add_field(
                    name="Latest Commit",
                    value=f"[{commit_msg}]({latest_commit['html_url']})",
                    inline=False
                )
            
            embed.set_thumbnail(url=repo_data['owner']['avatar_url'])
            embed.set_footer(text="Updates will be posted in this channel")
            
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
        guild_id = str(interaction.guild.id)
        
        if guild_id not in self.tracked_repos or not self.tracked_repos[guild_id]:
            embed = EmbedBuilder.error("Not Tracking", "No repositories are being tracked in this server")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Find and remove the tracked repo
        removed = False
        for i, tracked in enumerate(self.tracked_repos[guild_id]):
            if tracked['repo'] == repo and tracked['channel_id'] == str(channel.id):
                self.tracked_repos[guild_id].pop(i)
                removed = True
                break
        
        if not removed:
            embed = EmbedBuilder.error(
                "Not Found", 
                f"Not tracking {repo} in {channel.mention}"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Save updated tracking list
        await self.save_tracked_repos(guild_id)
        
        embed = EmbedBuilder.success(
            "Tracking Stopped",
            f"Stopped tracking {repo} in {channel.mention}"
        )
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="list-repos", description="List all tracked GitHub repositories")
    async def list_repos(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        
        if guild_id not in self.tracked_repos or not self.tracked_repos[guild_id]:
            embed = EmbedBuilder.info("No Repositories", "No GitHub repositories are being tracked in this server")
            await interaction.response.send_message(embed=embed)
            return
        
        embed = discord.Embed(
            title="📊 Tracked GitHub Repositories",
            description=f"This server is tracking {len(self.tracked_repos[guild_id])} repositories",
            color=0x5865F2
        )
        
        for tracked in self.tracked_repos[guild_id]:
            repo = tracked['repo']
            channel = interaction.guild.get_channel(int(tracked['channel_id']))
            channel_mention = channel.mention if channel else "Unknown Channel"
            
            embed.add_field(
                name=repo,
                value=f"**Channel:** {channel_mention}\n**URL:** [View on GitHub](https://github.com/{repo})",
                inline=True
            )
        
        await interaction.response.send_message(embed=embed)
    
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
        for guild_id, repos in self.tracked_repos.items():
            for i, repo_data in enumerate(repos):
                try:
                    repo = repo_data['repo']
                    channel_id = repo_data['channel_id']
                    
                    # Get guild and channel
                    guild = self.bot.get_guild(int(guild_id))
                    if not guild:
                        continue
                    
                    channel = guild.get_channel(int(channel_id))
                    if not channel:
                        continue
                    
                    # Check for updates
                    updates = await self.check_repo_updates(repo, repo_data)
                    if updates:
                        # Update stored data
                        self.tracked_repos[guild_id][i].update(updates['new_data'])
                        await self.save_tracked_repos(guild_id)
                        
                        # Send update notifications
                        for update in updates['notifications']:
                            await channel.send(embed=update)
                
                except Exception as e:
                    print(f"Error checking repo {repo_data.get('repo', 'unknown')}: {e}")
    
    async def check_repo_updates(self, repo: str, repo_data: dict):
        """Check a single repository for updates"""
        try:
            notifications = []
            new_data = {
                'last_checked': datetime.utcnow().isoformat()
            }
            
            # Get repo info
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.github.com/repos/{repo}", 
                                      headers={"Accept": "application/vnd.github.v3+json"}) as response:
                    if response.status != 200:
                        return None
                    
                    repo_info = await response.json()
            
            # Check for star changes
            old_stars = repo_data.get('stars', 0)
            new_stars = repo_info['stargazers_count']
            new_data['stars'] = new_stars
            
            if new_stars > old_stars:
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
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.github.com/repos/{repo}/commits", 
                                      headers={"Accept": "application/vnd.github.v3+json"}) as response:
                    if response.status != 200:
                        return None
                    
                    commits = await response.json()
                    if not commits or not isinstance(commits, list):
                        return None
                    
                    latest_commit = commits[0]
            
            old_commit = repo_data.get('last_commit')
            new_commit = latest_commit['sha']
            new_data['last_commit'] = new_commit
            
            if old_commit and new_commit != old_commit:
                # Count new commits
                new_commits = []
                for commit in commits:
                    if commit['sha'] == old_commit:
                        break
                    new_commits.append(commit)
                
                if new_commits:
                    embed = discord.Embed(
                        title=f"🔄 New Commits: {repo}",
                        description=f"{len(new_commits)} new commits pushed to repository",
                        color=0x5865F2,
                        url=f"https://github.com/{repo}/commits"
                    )
                    
                    # Show up to 5 latest commits
                    for i, commit in enumerate(new_commits[:5]):
                        msg = commit['commit']['message'].split('\n')[0]
                        if len(msg) > 60:
                            msg = msg[:57] + "..."
                        
                        author = commit['commit']['author']['name']
                        embed.add_field(
                            name=f"Commit by {author}",
                            value=f"[{msg}]({commit['html_url']})",
                            inline=False
                        )
                    
                    if len(new_commits) > 5:
                        embed.add_field(
                            name="More Commits",
                            value=f"... and {len(new_commits) - 5} more commits",
                            inline=False
                        )
                    
                    embed.set_footer(text=f"GitHub • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
                    notifications.append(embed)
            
            # Check for new pull requests
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.github.com/repos/{repo}/pulls?state=open", 
                                      headers={"Accept": "application/vnd.github.v3+json"}) as response:
                    if response.status != 200:
                        return None
                    
                    pulls = await response.json()
            
            # Store current PR numbers
            current_prs = [pr['number'] for pr in pulls]
            old_prs = repo_data.get('pull_requests', [])
            new_data['pull_requests'] = current_prs
            
            # Find new PRs
            new_prs = [pr for pr in pulls if pr['number'] not in old_prs]
            
            for pr in new_prs[:3]:  # Show up to 3 new PRs
                embed = discord.Embed(
                    title=f"🔀 New Pull Request: {repo}",
                    description=pr['title'],
                    color=0x6F42C1,
                    url=pr['html_url']
                )
                
                embed.add_field(name="Author", value=pr['user']['login'], inline=True)
                embed.add_field(name="Number", value=f"#{pr['number']}", inline=True)
                
                if pr['body'] and len(pr['body']) > 0:
                    body = pr['body']
                    if len(body) > 100:
                        body = body[:97] + "..."
                    embed.add_field(name="Description", value=body, inline=False)
                
                embed.set_thumbnail(url=pr['user']['avatar_url'])
                embed.set_footer(text=f"GitHub • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
                notifications.append(embed)
            
            # Check for new branches
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.github.com/repos/{repo}/branches", 
                                      headers={"Accept": "application/vnd.github.v3+json"}) as response:
                    if response.status != 200:
                        return None
                    
                    branches = await response.json()
            
            # Store current branch names
            current_branches = [branch['name'] for branch in branches]
            old_branches = repo_data.get('branches', [])
            new_data['branches'] = current_branches
            
            # Find new branches
            new_branches = [branch for branch in current_branches if branch not in old_branches]
            
            if new_branches:
                embed = discord.Embed(
                    title=f"🌿 New Branches: {repo}",
                    description=f"{len(new_branches)} new branches created",
                    color=0x28A745,
                    url=f"https://github.com/{repo}/branches"
                )
                
                branch_list = "\n".join([f"• `{branch}`" for branch in new_branches[:10]])
                if len(new_branches) > 10:
                    branch_list += f"\n... and {len(new_branches) - 10} more"
                
                embed.add_field(name="New Branches", value=branch_list, inline=False)
                embed.set_footer(text=f"GitHub • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
                notifications.append(embed)
            
            return {
                'new_data': new_data,
                'notifications': notifications
            }
            
        except Exception as e:
            print(f"Error checking repo updates for {repo}: {e}")
            return None

async def setup(bot):
    github_cog = GitHubIntegrations(bot)
    await github_cog.load_tracked_repos()
    await bot.add_cog(github_cog)
