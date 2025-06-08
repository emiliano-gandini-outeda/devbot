import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder

class Roles(commands.Cog):
    """Role and permission management"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="assign-role", description="Assign a role to a user")
    @app_commands.describe(
        user="User to assign role to",
        role="Role to assign"
    )
    @app_commands.default_permissions(manage_roles=True)
    async def assign_role(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role):
        try:
            if role >= interaction.guild.me.top_role:
                embed = EmbedBuilder.error(
                    "Permission Error",
                    "I cannot assign a role that is higher than or equal to my highest role"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            if role in user.roles:
                embed = EmbedBuilder.warning("Already Assigned", f"{user.mention} already has the {role.mention} role")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            await user.add_roles(role, reason=f"Assigned by {interaction.user}")
            
            embed = EmbedBuilder.success(
                "Role Assigned",
                f"Successfully assigned {role.mention} to {user.mention}"
            )
            await interaction.response.send_message(embed=embed)
            
        except discord.Forbidden:
            embed = EmbedBuilder.error("Permission Error", "I don't have permission to manage this role")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to assign role: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="remove-role", description="Remove a role from a user")
    @app_commands.describe(
        user="User to remove role from",
        role="Role to remove"
    )
    @app_commands.default_permissions(manage_roles=True)
    async def remove_role(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role):
        try:
            if role not in user.roles:
                embed = EmbedBuilder.warning("Not Assigned", f"{user.mention} doesn't have the {role.mention} role")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            await user.remove_roles(role, reason=f"Removed by {interaction.user}")
            
            embed = EmbedBuilder.success(
                "Role Removed",
                f"Successfully removed {role.mention} from {user.mention}"
            )
            await interaction.response.send_message(embed=embed)
            
        except discord.Forbidden:
            embed = EmbedBuilder.error("Permission Error", "I don't have permission to manage this role")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to remove role: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="user-permissions", description="Show user permissions in current channel")
    @app_commands.describe(user="User to check permissions for")
    async def user_permissions(self, interaction: discord.Interaction, user: discord.Member = None):
        if not user:
            user = interaction.user
        
        permissions = interaction.channel.permissions_for(user)
        
        embed = discord.Embed(
            title=f"🔐 Permissions for {user.display_name}",
            description=f"Permissions in {interaction.channel.mention}",
            color=0x5865F2
        )
        
        # Key permissions to display
        key_perms = [
            ("Send Messages", permissions.send_messages),
            ("Read Message History", permissions.read_message_history),
            ("Manage Messages", permissions.manage_messages),
            ("Manage Channels", permissions.manage_channels),
            ("Administrator", permissions.administrator),
            ("Manage Guild", permissions.manage_guild),
            ("Manage Roles", permissions.manage_roles),
            ("Kick Members", permissions.kick_members),
            ("Ban Members", permissions.ban_members)
        ]
        
        allowed = []
        denied = []
        
        for perm_name, has_perm in key_perms:
            if has_perm:
                allowed.append(f"✅ {perm_name}")
            else:
                denied.append(f"❌ {perm_name}")
        
        if allowed:
            embed.add_field(name="Allowed", value="\n".join(allowed), inline=True)
        
        if denied:
            embed.add_field(name="Denied", value="\n".join(denied[:10]), inline=True)  # Limit to 10 to avoid overflow
        
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="role-info", description="Show information about a role")
    @app_commands.describe(role="Role to get information about")
    async def role_info(self, interaction: discord.Interaction, role: discord.Role):
        embed = discord.Embed(
            title=f"📋 Role Information: {role.name}",
            color=role.color if role.color != discord.Color.default() else 0x5865F2
        )
        
        embed.add_field(name="ID", value=role.id, inline=True)
        embed.add_field(name="Members", value=len(role.members), inline=True)
        embed.add_field(name="Position", value=role.position, inline=True)
        embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
        embed.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True)
        embed.add_field(name="Created", value=role.created_at.strftime("%Y-%m-%d %H:%M UTC"), inline=True)
        
        if role.permissions.administrator:
            embed.add_field(name="⚠️ Administrator", value="This role has administrator permissions", inline=False)
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Roles(bot))
