import discord
from discord.ext import commands
from discord import app_commands
import json
from utils.helpers import EmbedBuilder
from config.constants import WorkflowStatus

class Workflows(commands.Cog):
    """Automation workflows similar to Slack workflows"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="create-workflow", description="Create a new automation workflow")
    @app_commands.describe(
        name="Workflow name",
        trigger="Trigger type (message, reaction, join, schedule)",
        description="Workflow description"
    )
    async def create_workflow(self, interaction: discord.Interaction, name: str, trigger: str, description: str = ""):
        await interaction.response.defer()
        
        valid_triggers = ["message", "reaction", "join", "schedule"]
        if trigger not in valid_triggers:
            embed = EmbedBuilder.error(
                "Invalid Trigger",
                f"Trigger must be one of: {', '.join(valid_triggers)}"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        try:
            # Store workflow in database (adapted for PostgreSQL/SQLite)
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO workflows (name, guild_id, creator_id, trigger_type, trigger_data, actions, status)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    name, str(interaction.guild.id), str(interaction.user.id), trigger, 
                    json.dumps({}), json.dumps([]), WorkflowStatus.ACTIVE.value
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT INTO workflows (name, guild_id, creator_id, trigger_type, trigger_data, actions, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (name, str(interaction.guild.id), str(interaction.user.id), trigger, 
                     json.dumps({}), json.dumps([]), WorkflowStatus.ACTIVE.value)
                )
                await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Workflow Created",
                f"**{name}** workflow created successfully!\n"
                f"**Trigger:** {trigger}\n"
                f"**Status:** Active\n\n"
                f"Use `/add-workflow-action` to add actions to this workflow."
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create workflow: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="list-workflows", description="List all workflows in this server")
    async def list_workflows(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            if self.bot.db.is_postgresql:
                workflows = await self.bot.db.connection.fetch(
                    "SELECT * FROM workflows WHERE guild_id = $1 ORDER BY created_at DESC",
                    str(interaction.guild.id)
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM workflows WHERE guild_id = ? ORDER BY created_at DESC",
                    (str(interaction.guild.id),)
                )
                workflows = await cursor.fetchall()
            
            if not workflows:
                embed = EmbedBuilder.info("No Workflows", "No workflows found in this server")
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title="⚙️ Server Workflows",
                color=0x5865F2
            )
            
            for workflow in workflows[:10]:  # Show first 10 workflows
                if self.bot.db.is_postgresql:
                    creator_id = workflow['creator_id']
                    name = workflow['name']
                    trigger_type = workflow['trigger_type']
                    status = workflow['status']
                else:
                    creator_id = workflow[3]
                    name = workflow[1]
                    trigger_type = workflow[4]
                    status = workflow[7]
                
                creator = interaction.guild.get_member(int(creator_id))
                creator_name = creator.display_name if creator else "Unknown"
                
                status_emoji = "✅" if status == "active" else "⏸️"
                
                embed.add_field(
                    name=f"{status_emoji} {name}",
                    value=f"**Trigger:** {trigger_type}\n"
                          f"**Creator:** {creator_name}\n"
                          f"**Status:** {status.title()}",
                    inline=True
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to fetch workflows: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="toggle-workflow", description="Enable or disable a workflow")
    @app_commands.describe(workflow_name="Name of the workflow to toggle")
    async def toggle_workflow(self, interaction: discord.Interaction, workflow_name: str):
        await interaction.response.defer()
        
        try:
            # Get workflow (adapted for PostgreSQL/SQLite)
            if self.bot.db.is_postgresql:
                workflow = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM workflows WHERE guild_id = $1 AND name = $2",
                    str(interaction.guild.id), workflow_name
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM workflows WHERE guild_id = ? AND name = ?",
                    (str(interaction.guild.id), workflow_name)
                )
                workflow = await cursor.fetchone()
            
            if not workflow:
                embed = EmbedBuilder.error("Not Found", f"Workflow '{workflow_name}' not found")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Toggle status
            current_status = workflow['status'] if self.bot.db.is_postgresql else workflow[7]
            new_status = "inactive" if current_status == "active" else "active"
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "UPDATE workflows SET status = $1 WHERE id = $2",
                    new_status, workflow['id']
                )
            else:
                await self.bot.db.connection.execute(
                    "UPDATE workflows SET status = ? WHERE id = ?",
                    (new_status, workflow[0])
                )
                await self.bot.db.connection.commit()
            
            embed = EmbedBuilder.success(
                "Workflow Updated",
                f"Workflow **{workflow_name}** is now **{new_status}**"
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to toggle workflow: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Workflows(bot))
