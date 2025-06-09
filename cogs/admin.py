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
                      f"**Commands:** {len(self.bot.tree.get_commands(guild=interaction.guild))}",
                inline=True
            )
            
            # Database Status
            if self.bot.db and self.bot.db.connection:
                db_status = "🟢 Connected (PostgreSQL)"
                
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
            
            # Admin Manager Status
            admin_status = "🟢 Active" if self.bot.admin_manager else "🔴 Inactive"
            
            embed.add_field(
                name="🔧 Admin Manager",
                value=admin_status,
                inline=True
            )
            
            embed.set_footer(text=f"Powered by Railway 🚄 • Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to load admin panel: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Admin(bot))
