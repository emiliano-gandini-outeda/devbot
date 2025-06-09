import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
from datetime import datetime

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

    # Renamed from bot_status to status_check to avoid Discord.py naming conflict
    @app_commands.command(name="status-check", description="Check bot status and loaded features (Admin only)")
    async def status_check(self, interaction: discord.Interaction):
        if not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can check bot status")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🤖 Bot Status",
            color=0x5865F2
        )
        
        # Loaded cogs
        loaded_cogs = list(self.bot.cogs.keys())
        embed.add_field(
            name=f"📦 Loaded Cogs ({len(loaded_cogs)})",
            value="\n".join([f"✅ {cog}" for cog in loaded_cogs]) if loaded_cogs else "None",
            inline=False
        )
        
        # Slash commands
        commands = self.bot.tree.get_commands()
        embed.add_field(
            name=f"⚡ Slash Commands ({len(commands)})",
            value=f"Total registered: {len(commands)}\nUse `/help` to see all commands",
            inline=True
        )
        
        # Database status
        db_status = "✅ Connected" if self.bot.db and self.bot.db.connection else "❌ Disconnected"
        embed.add_field(
            name="🗄️ Database",
            value=db_status,
            inline=True
        )
        
        # Managers status
        managers = {
            "Admin Manager": "✅" if self.bot.admin_manager else "❌",
            "Ticket Manager": "✅" if self.bot.ticket_manager else "❌",
            "Logging Manager": "✅" if self.bot.logging_manager else "❌",
            "Workflow Manager": "✅" if self.bot.workflow_manager else "❌"
        }
        
        embed.add_field(
            name="🔧 Managers",
            value="\n".join([f"{status} {name}" for name, status in managers.items()]),
            inline=False
        )
        
        # Guild configs
        guild_id = str(interaction.guild.id)
        configs = {
            "Ticket System": "✅" if self.bot.ticket_manager.get_ticket_config(guild_id) else "❌",
            "Logging System": "✅" if self.bot.logging_manager.get_log_config(guild_id) else "❌",
            "Admin Roles": "✅" if self.bot.admin_manager.get_admin_roles(guild_id) else "❌"
        }
        
        embed.add_field(
            name="⚙️ Server Configuration",
            value="\n".join([f"{status} {name}" for name, status in configs.items()]),
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="get-data", description="Get all data for a user (Admin only)")
    @app_commands.describe(user="User to get data for")
    async def get_data(self, interaction: discord.Interaction, user: discord.Member):
        if not self.bot.admin_manager.is_admin(interaction.user):
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
            
            # Get reminders
            if self.bot.db.is_postgresql:
                reminders = await self.bot.db.connection.fetch(
                    "SELECT * FROM reminders WHERE user_id = $1", user_id
                )
                
                data["reminders"] = []
                for reminder in reminders:
                    data["reminders"].append({
                        "message": reminder['message'],
                        "remind_at": str(reminder['remind_at']),
                        "type": reminder['type'],
                        "created_at": str(reminder['created_at'])
                    })
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM reminders WHERE user_id = ?", (user_id,)
                )
                reminders = await cursor.fetchall()
                
                data["reminders"] = []
                for reminder in reminders:
                    data["reminders"].append({
                        "message": reminder[4],
                        "remind_at": reminder[5],
                        "type": reminder[6],
                        "created_at": reminder[8]
                    })
            
            # Get workflows created by user
            if self.bot.db.is_postgresql:
                workflows = await self.bot.db.connection.fetch(
                    "SELECT * FROM workflows WHERE creator_id = $1 AND guild_id = $2", 
                    user_id, str(interaction.guild.id)
                )
                
                data["workflows"] = []
                for workflow in workflows:
                    data["workflows"].append({
                        "name": workflow['name'],
                        "trigger_type": workflow['trigger_type'],
                        "status": workflow['status'],
                        "created_at": str(workflow['created_at'])
                    })
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM workflows WHERE creator_id = ? AND guild_id = ?", 
                    (user_id, str(interaction.guild.id))
                )
                workflows = await cursor.fetchall()
                
                data["workflows"] = []
                for workflow in workflows:
                    data["workflows"].append({
                        "name": workflow[1],
                        "trigger_type": workflow[4],
                        "status": workflow[7],
                        "created_at": workflow[8]
                    })
            
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

    @commands.command(name='list_commands')
    @commands.is_owner()
    async def list_commands_cmd(self, ctx):
        """List all commands and their registration status"""
        all_commands = self.bot.tree.get_commands()
        
        # Group by cog
        cog_commands = {}
        for cmd in all_commands:
            cog_name = getattr(cmd, "_cog_name", "Unknown")
            if cog_name not in cog_commands:
                cog_commands[cog_name] = []
            cog_commands[cog_name].append(cmd)
        
        for cog_name, cmds in cog_commands.items():
            commands_text = "\n".join([f"- /{cmd.name}" for cmd in cmds])
            await ctx.send(f"**{cog_name} Commands**:\n```\n{commands_text}\n```")
        
        await ctx.send(f"Total commands: {len(all_commands)}")

async def setup(bot):
    await bot.add_cog(Admin(bot))
