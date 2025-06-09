import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
from datetime import datetime
import json

class Admin(commands.Cog):
    """Admin management commands"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="add-admin-role", description="Add a role to the admin list (Administrator only)")
    @app_commands.describe(role="Role to add to admin list")
    @app_commands.default_permissions(administrator=True)
    async def add_admin_role(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.user.guild_permissions.administrator:
            embed = EmbedBuilder.error("Permission Denied", "Only server administrators can manage admin roles")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            if not self.bot.admin_manager:
                embed = EmbedBuilder.error("Error", "Admin manager not available")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
            success = await self.bot.admin_manager.add_admin_role(str(interaction.guild.id), str(role.id))
            
            if success:
                embed = EmbedBuilder.success(
                    "Admin Role Added",
                    f"Role {role.mention} has been added to the admin list.\n"
                    f"Members with this role now have access to admin commands."
                )
            else:
                embed = EmbedBuilder.warning("Already Added", f"Role {role.mention} is already in the admin list")
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to add admin role: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="remove-admin-role", description="Remove a role from the admin list (Administrator only)")
    @app_commands.describe(role="Role to remove from admin list")
    @app_commands.default_permissions(administrator=True)
    async def remove_admin_role(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.user.guild_permissions.administrator:
            embed = EmbedBuilder.error("Permission Denied", "Only server administrators can manage admin roles")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            if not self.bot.admin_manager:
                embed = EmbedBuilder.error("Error", "Admin manager not available")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
            success = await self.bot.admin_manager.remove_admin_role(str(interaction.guild.id), str(role.id))
            
            if success:
                embed = EmbedBuilder.success(
                    "Admin Role Removed",
                    f"Role {role.mention} has been removed from the admin list."
                )
            else:
                embed = EmbedBuilder.warning("Not Found", f"Role {role.mention} is not in the admin list")
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to remove admin role: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-admin-roles", description="List all admin roles")
    async def list_admin_roles(self, interaction: discord.Interaction):
        try:
            if not self.bot.admin_manager:
                embed = EmbedBuilder.error("Error", "Admin manager not available")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
            admin_role_ids = self.bot.admin_manager.get_admin_roles(str(interaction.guild.id))
            
            if not admin_role_ids:
                embed = EmbedBuilder.info("No Admin Roles", "No roles have been added to the admin list")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            embed = discord.Embed(
                title="🛡️ Admin Roles",
                color=0x5865F2
            )
            
            role_mentions = []
            for role_id in admin_role_ids:
                role = interaction.guild.get_role(int(role_id))
                if role:
                    role_mentions.append(f"• {role.mention}")
                else:
                    role_mentions.append(f"• Deleted Role (ID: {role_id})")
            
            embed.add_field(
                name="Roles with Admin Access",
                value="\n".join(role_mentions) if role_mentions else "None",
                inline=False
            )
            
            embed.add_field(
                name="Note",
                value="Server administrators always have admin access regardless of roles.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to list admin roles: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="admin-panel", description="View bot status and server configuration (Admin only)")
    async def admin_panel(self, interaction: discord.Interaction):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can access the admin panel")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            embed = discord.Embed(
                title="🛡️ Admin Panel",
                description=f"Server: **{interaction.guild.name}**",
                color=0x5865F2
            )
            
            # Bot Status
            embed.add_field(
                name="🤖 Bot Status",
                value=f"**Status:** 🟢 Online\n"
                      f"**Guilds:** {len(self.bot.guilds)}\n"
                      f"**Users:** {sum(g.member_count for g in self.bot.guilds)}\n"
                      f"**Commands:** {len(self.bot.tree.get_commands())}",
                inline=True
            )
            
            # Database Status
            if self.bot.db and self.bot.db.connection:
                db_type = "PostgreSQL" if self.bot.db.is_postgresql else "SQLite"
                db_status = f"🟢 Connected ({db_type})"
                
                # Test connection
                try:
                    await self.bot.db.test_connection()
                    db_status += "\n✅ Connection Test: Passed"
                except:
                    db_status += "\n❌ Connection Test: Failed"
            else:
                db_status = "🔴 Disconnected"
            
            embed.add_field(
                name="🗄️ Database",
                value=db_status,
                inline=True
            )
            
            # Managers Status
            managers = {
                "Admin Manager": "🟢" if self.bot.admin_manager else "🔴",
                "Ticket Manager": "🟢" if self.bot.ticket_manager else "🔴",
                "Logging Manager": "🟢" if self.bot.logging_manager else "🔴",
                "Workflow Manager": "🟢" if self.bot.workflow_manager else "🔴"
            }
            
            embed.add_field(
                name="🔧 System Managers",
                value="\n".join([f"{status} {name}" for name, status in managers.items()]),
                inline=False
            )
            
            # Server Configuration Status
            guild_id = str(interaction.guild.id)
            configs = await self.get_server_configs(guild_id)
            
            config_status = []
            for service, status in configs.items():
                emoji = "🟢" if status['configured'] else "🔴"
                config_status.append(f"{emoji} **{service}**")
                if status['configured'] and status.get('details'):
                    config_status.append(f"   └ {status['details']}")
            
            embed.add_field(
                name="⚙️ Server Services",
                value="\n".join(config_status) if config_status else "No services configured",
                inline=False
            )
            
            # Quick Actions
            embed.add_field(
                name="🚀 Quick Setup",
                value="Use these commands to configure services:\n"
                      "• `/ticket-system-setup` - Ticket system\n"
                      "• `/setup-meetings` - Meeting announcements\n"
                      "• `/server-logs-setup` - Server logging\n"
                      "• `/setup-tracking` - GitHub tracking\n"
                      "• `/setup-reminders` - Reminder system",
                inline=False
            )
            
            embed.set_footer(text=f"Powered by Railway 🚄 • Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to load admin panel: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def get_server_configs(self, guild_id: str):
        """Get configuration status for all server services"""
        configs = {
            "Ticket System": {"configured": False, "details": None},
            "Meeting System": {"configured": False, "details": None},
            "Logging System": {"configured": False, "details": None},
            "GitHub Tracking": {"configured": False, "details": None},
            "Reminder System": {"configured": False, "details": None},
            "Thread Logging": {"configured": False, "details": None}
        }
        
        try:
            # Check ticket system
            if self.bot.ticket_manager:
                ticket_config = self.bot.ticket_manager.get_ticket_config(guild_id)
                if ticket_config:
                    configs["Ticket System"]["configured"] = True
                    category = self.bot.get_channel(int(ticket_config.get('category_id', 0)))
                    if category:
                        configs["Ticket System"]["details"] = f"Category: #{category.name}"
            
            # Check other configs from database
            if self.bot.db:
                config_types = [
                    ('meeting_config', 'Meeting System', 'announcement_channel_id'),
                    ('github_tracking_config', 'GitHub Tracking', 'tracking_channel_id'),
                    ('reminder_config', 'Reminder System', 'reminder_channel_id'),
                    ('thread_config', 'Thread Logging', 'thread_log_channel_id')
                ]
                
                for config_type, service_name, channel_key in config_types:
                    try:
                        if self.bot.db.is_postgresql:
                            result = await self.bot.db.connection.fetchrow(
                                "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                                guild_id, config_type
                            )
                        else:
                            cursor = await self.bot.db.connection.execute(
                                "SELECT data_content FROM user_data WHERE user_id = ? AND data_type = ?",
                                (guild_id, config_type)
                            )
                            result = await cursor.fetchone()
                        
                        if result:
                            data = json.loads(result['data_content'] if self.bot.db.is_postgresql else result[0])
                            configs[service_name]["configured"] = True
                            
                            if channel_key in data:
                                channel = self.bot.get_channel(int(data[channel_key]))
                                if channel:
                                    configs[service_name]["details"] = f"Channel: #{channel.name}"
                    except Exception:
                        continue
                
                # Check logging system
                if self.bot.logging_manager:
                    log_config = self.bot.logging_manager.get_log_config(guild_id)
                    if log_config:
                        configs["Logging System"]["configured"] = True
                        channel = self.bot.get_channel(int(log_config.get('log_channel_id', 0)))
                        if channel:
                            configs["Logging System"]["details"] = f"Channel: #{channel.name}"
            
        except Exception as e:
            print(f"Error getting server configs: {e}")
        
        return configs
    
    @app_commands.command(name="get-data", description="Get all data for a user (Admin only)")
    @app_commands.describe(user="User to get data for")
    async def get_data(self, interaction: discord.Interaction, user: discord.Member):
        if not self.bot.admin_manager or not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can use this command")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_id = str(user.id)
            data = {}
            
            # Get user profile data
            data["profile"] = {
                "discord_id": user_id,
                "username": user.name,
                "display_name": user.display_name,
                "joined_at": user.joined_at.isoformat() if user.joined_at else None,
                "created_at": user.created_at.isoformat(),
                "roles": [role.name for role in user.roles[1:]],  # Skip @everyone
                "avatar_url": str(user.display_avatar.url)
            }
            
            # Get tickets created by user
            if self.bot.db:
                try:
                    if self.bot.db.is_postgresql:
                        tickets = await self.bot.db.connection.fetch(
                            "SELECT * FROM tickets WHERE user_id = $1 AND guild_id = $2", 
                            user_id, str(interaction.guild.id)
                        )
                        
                        data["tickets"] = []
                        for ticket in tickets:
                            data["tickets"].append({
                                "ticket_id": ticket['ticket_id'],
                                "title": ticket['title'],
                                "description": ticket['description'],
                                "status": ticket['status'],
                                "priority": ticket['priority'],
                                "created_at": str(ticket['created_at'])
                            })
                    else:
                        cursor = await self.bot.db.connection.execute(
                            "SELECT * FROM tickets WHERE user_id = ? AND guild_id = ?", 
                            (user_id, str(interaction.guild.id))
                        )
                        tickets = await cursor.fetchall()
                        
                        data["tickets"] = []
                        for ticket in tickets:
                            data["tickets"].append({
                                "ticket_id": ticket[1],
                                "title": ticket[5],
                                "description": ticket[6],
                                "status": ticket[7],
                                "priority": ticket[8],
                                "created_at": ticket[10]
                            })
                except Exception:
                    data["tickets"] = []
            
            # Create and send file with data
            import io
            import json
            
            file_content = json.dumps(data, indent=2)
            file = discord.File(
                io.BytesIO(file_content.encode('utf-8')),
                filename=f"user_data_{user.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            
            embed = EmbedBuilder.success(
                "User Data Retrieved",
                f"Data for {user.mention} has been retrieved and is attached as a JSON file."
            )
            
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to retrieve user data: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    cog = Admin(bot)
    await bot.add_cog(cog)
    
    # Manually add each command to the tree to ensure registration
    commands_to_add = [
        cog.add_admin_role,
        cog.remove_admin_role,
        cog.list_admin_roles,
        cog.admin_panel,
        cog.get_data
    ]
    
    for command in commands_to_add:
        if command not in bot.tree.get_commands():
            bot.tree.add_command(command)
    
    print(f"🛡️ Successfully loaded Admin cog with {len(commands_to_add)} commands")
