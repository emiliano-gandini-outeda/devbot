import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder

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
    
    @app_commands.command(name="ticket-setup", description="Setup ticket system (Admin only)")
    @app_commands.describe(
        category="Category where ticket channels will be created",
        transcript_channel="Channel where ticket transcripts will be sent"
    )
    async def ticket_setup(self, interaction: discord.Interaction, category: discord.CategoryChannel, transcript_channel: discord.TextChannel):
        if not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can setup the ticket system")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            config = {
                'category_id': str(category.id),
                'transcript_channel_id': str(transcript_channel.id),
                'setup_by': str(interaction.user.id),
                'setup_at': str(discord.utils.utcnow())
            }
            
            await self.bot.ticket_manager.save_ticket_config(str(interaction.guild.id), config)
            
            embed = EmbedBuilder.success(
                "Ticket System Setup",
                f"Ticket system has been configured successfully!\n\n"
                f"**Ticket Category:** {category.mention}\n"
                f"**Transcript Channel:** {transcript_channel.mention}\n\n"
                f"Users can now create tickets using `/create-ticket`"
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to setup ticket system: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Admin(bot))
