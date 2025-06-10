import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import json
from datetime import datetime

class Admin(commands.Cog):
    """Administrator commands for server management"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="admin-panel", description="View bot status and server configuration (Admin only)")
    async def admin_panel(self, interaction: discord.Interaction):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can access the admin panel")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get setup status for various systems
            setups = await self._get_setup_status(str(interaction.guild.id))
            
            embed = discord.Embed(
                title="🛡️ Admin Panel",
                description=f"**Server:** {interaction.guild.name}\n**Bot Status:** 🟢 Online",
                color=0x5865F2,
                timestamp=datetime.utcnow()
            )
            
            # Bot Statistics
            embed.add_field(
                name="📊 Bot Statistics",
                value=f"**Guilds:** {len(self.bot.guilds)}\n"
                      f"**Users:** {sum(guild.member_count for guild in self.bot.guilds)}\n"
                      f"**Commands:** {len(self.bot.tree.get_commands())}",
                inline=True
            )
            
            # Server Statistics
            embed.add_field(
                name="🏠 Server Statistics",
                value=f"**Members:** {interaction.guild.member_count}\n"
                      f"**Channels:** {len(interaction.guild.channels)}\n"
                      f"**Roles:** {len(interaction.guild.roles)}",
                inline=True
            )
            
            # Database Status
            try:
                await self.bot.db.test_connection()
                db_status = "🟢 Connected"
            except:
                db_status = "🔴 Disconnected"
            
            embed.add_field(
                name="💾 Database Status",
                value=f"**Connection:** {db_status}\n"
                      f"**Type:** PostgreSQL\n"
                      f"**Tables:** Initialized",
                inline=True
            )
            
            # Setup Status
            setup_status = []
            for system, status in setups.items():
                emoji = "✅" if status else "❌"
                setup_status.append(f"{emoji} {system}")
            
            embed.add_field(
                name="⚙️ System Setup Status",
                value="\n".join(setup_status) if setup_status else "No systems configured",
                inline=False
            )
            
            # Admin Roles
            admin_roles = self.bot.admin_manager.get_admin_roles(str(interaction.guild.id)) if self.bot.admin_manager else []
            if admin_roles:
                role_mentions = []
                for role_id in admin_roles:
                    role = interaction.guild.get_role(int(role_id))
                    if role:
                        role_mentions.append(role.mention)
                
                embed.add_field(
                    name="👑 Admin Roles",
                    value="\n".join(role_mentions) if role_mentions else "No admin roles found",
                    inline=True
                )
            else:
                embed.add_field(
                    name="👑 Admin Roles",
                    value="No admin roles configured",
                    inline=True
                )
            
            embed.set_footer(text="devBot - Powered by EGOS")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to load admin panel: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def _get_setup_status(self, guild_id: str) -> dict:
        """Get setup status for various systems"""
        setups = {
            "Ticket System": False,
            "GitHub Tracking": False,
            "Logging": False,
            "Meetings": False,
            "Reminders": False,
            "Threads": False
        }
        
        try:
            # Check user_data table for configurations
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT data_type FROM user_data WHERE user_id = $1",
                    guild_id
                )
                
                for row in rows:
                    data_type = row['data_type']
                    if data_type == 'ticket_config':
                        setups["Ticket System"] = True
                    elif data_type == 'github_tracking_config':
                        setups["GitHub Tracking"] = True
                    elif data_type == 'meeting_config':
                        setups["Meetings"] = True
                    elif data_type == 'reminder_config':
                        setups["Reminders"] = True
                    elif data_type == 'thread_config':
                        setups["Threads"] = True
            
            # Check log_configs table for logging setup
            log_config = await self.bot.db.connection.fetchrow(
                "SELECT id FROM log_configs WHERE guild_id = $1", guild_id
            )
            if log_config:
                setups["Logging"] = True
            
        except Exception as e:
            print(f"Error checking setup status: {e}")
        
        return setups
    
    @app_commands.command(name="add-admin-role", description="Add a role to the admin list (Admin only)")
    @app_commands.describe(role="Role to add to admin list")
    async def add_admin_role(self, interaction: discord.Interaction, role: discord.Role):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can manage admin roles")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            success = await self.bot.admin_manager.add_admin_role(str(interaction.guild.id), str(role.id))
            
            if success:
                embed = EmbedBuilder.success(
                    "Admin Role Added",
                    f"Role {role.mention} has been added to the admin list"
                )
            else:
                embed = EmbedBuilder.warning(
                    "Already Admin Role",
                    f"Role {role.mention} is already in the admin list"
                )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to add admin role: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="remove-admin-role", description="Remove a role from the admin list (Admin only)")
    @app_commands.describe(role="Role to remove from admin list")
    async def remove_admin_role(self, interaction: discord.Interaction, role: discord.Role):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can manage admin roles")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            success = await self.bot.admin_manager.remove_admin_role(str(interaction.guild.id), str(role.id))
            
            if success:
                embed = EmbedBuilder.success(
                    "Admin Role Removed",
                    f"Role {role.mention} has been removed from the admin list"
                )
            else:
                embed = EmbedBuilder.warning(
                    "Not Admin Role",
                    f"Role {role.mention} is not in the admin list"
                )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to remove admin role: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-admin-roles", description="List all admin roles (Admin only)")
    async def list_admin_roles(self, interaction: discord.Interaction):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can view admin roles")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            admin_role_ids = self.bot.admin_manager.get_admin_roles(str(interaction.guild.id))
            
            if not admin_role_ids:
                embed = EmbedBuilder.info("No Admin Roles", "No admin roles have been configured for this server")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            role_mentions = []
            for role_id in admin_role_ids:
                role = interaction.guild.get_role(int(role_id))
                if role:
                    role_mentions.append(f"• {role.mention} (`{role.name}`)")
                else:
                    role_mentions.append(f"• Unknown Role (`{role_id}`)")
            
            embed = discord.Embed(
                title="👑 Admin Roles",
                description=f"**Total Admin Roles:** {len(admin_role_ids)}\n\n" + "\n".join(role_mentions),
                color=0x5865F2
            )
            embed.set_footer(text="devBot - Powered by EGOS")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to list admin roles: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="get-data", description="Get user's data in JSON format (Admin only)")
    @app_commands.describe(user="User to get data for")
    async def get_data(self, interaction: discord.Interaction, user: discord.Member):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can access user data")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_data = {}
            
            # Get user from users table
            if self.bot.db.is_postgresql:
                user_row = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM users WHERE discord_id = $1", str(user.id)
                )
                if user_row:
                    user_data['profile'] = dict(user_row)
                
                # Get user data entries
                data_rows = await self.bot.db.connection.fetch(
                    "SELECT * FROM user_data WHERE user_id = $1", str(user.id)
                )
                if data_rows:
                    user_data['data_entries'] = [dict(row) for row in data_rows]
                
                # Get tickets
                ticket_rows = await self.bot.db.connection.fetch(
                    "SELECT * FROM tickets WHERE user_id = $1", str(user.id)
                )
                if ticket_rows:
                    user_data['tickets'] = [dict(row) for row in ticket_rows]
                
                # Get reminders
                reminder_rows = await self.bot.db.connection.fetch(
                    "SELECT * FROM reminders WHERE user_id = $1", str(user.id)
                )
                if reminder_rows:
                    user_data['reminders'] = [dict(row) for row in reminder_rows]
                
                # Get keywords
                keyword_rows = await self.bot.db.connection.fetch(
                    "SELECT * FROM keywords WHERE user_id = $1", str(user.id)
                )
                if keyword_rows:
                    user_data['keywords'] = [dict(row) for row in keyword_rows]
                
                # Get GitHub subscriptions
                github_rows = await self.bot.db.connection.fetch(
                    "SELECT * FROM github_subscriptions WHERE user_id = $1", str(user.id)
                )
                if github_rows:
                    user_data['github_subscriptions'] = [dict(row) for row in github_rows]
            
            if not user_data:
                embed = EmbedBuilder.info("No Data Found", f"No data found for user {user.mention}")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Convert to JSON
            json_data = json.dumps(user_data, indent=2, default=str)
            
            # Create file
            import io
            file = discord.File(
                io.StringIO(json_data),
                filename=f"user_data_{user.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            )
            
            embed = discord.Embed(
                title="📊 User Data Export",
                description=f"**User:** {user.mention}\n**Data Categories:** {len(user_data)}\n**Export Time:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
                color=0x5865F2
            )
            embed.set_footer(text="devBot - Powered by EGOS")
            
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to get user data: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Admin(bot))
