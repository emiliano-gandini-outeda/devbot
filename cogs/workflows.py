import discord
from discord.ext import commands
from discord import app_commands
import json
from utils.helpers import EmbedBuilder
from config.constants import WorkflowStatus
from datetime import datetime

class Workflows(commands.Cog):
    """Automation workflows"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="create-workflow", description="Create a new automation workflow")
    @app_commands.describe(
        name="Workflow name",
        trigger="Trigger type (message, member_join, thread_create, channel_create)",
        trigger_channel="Channel to monitor for triggers (optional)",
        log_channel="Channel to log workflow executions (optional)"
    )
    async def create_workflow(self, interaction: discord.Interaction, name: str, trigger: str, trigger_channel: discord.TextChannel = None, log_channel: discord.TextChannel = None):
        await interaction.response.defer()
        
        valid_triggers = ["message", "member_join", "thread_create", "channel_create"]
        if trigger.startswith("message:") or trigger in valid_triggers:
            pass
        else:
            embed = EmbedBuilder.error(
                "Invalid Trigger",
                f"Trigger must be one of: {', '.join(valid_triggers)} or message:text (e.g., message:hello)"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        try:
            # Prepare trigger data
            trigger_data = {}
            if trigger_channel:
                trigger_data['channel_id'] = str(trigger_channel.id)
            if log_channel:
                trigger_data['log_channel_id'] = str(log_channel.id)
            
            # Store workflow in database
            await self.bot.db.connection.execute(
                """INSERT INTO workflows (name, guild_id, creator_id, trigger_type, trigger_data, actions, status)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                name, str(interaction.guild.id), str(interaction.user.id), trigger, 
                json.dumps(trigger_data), json.dumps([]), WorkflowStatus.ACTIVE.value
            )
            
            embed = EmbedBuilder.success(
                "Workflow Created",
                f"**{name}** workflow created successfully!\n"
                f"**Trigger:** {trigger}\n"
                f"**Trigger Channel:** {trigger_channel.mention if trigger_channel else 'All channels'}\n"
                f"**Log Channel:** {log_channel.mention if log_channel else 'None'}\n"
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
            workflows = await self.bot.db.connection.fetch(
                "SELECT * FROM workflows WHERE guild_id = $1 ORDER BY created_at DESC",
                str(interaction.guild.id)
            )
            
            if not workflows:
                embed = EmbedBuilder.info("No Workflows", "No workflows found in this server")
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title="⚙️ Server Workflows",
                color=0x5865F2
            )
            
            for workflow in workflows[:10]:  # Show first 10 workflows
                creator_id = workflow['creator_id']
                name = workflow['name']
                trigger_type = workflow['trigger_type']
                status = workflow['status']
                trigger_data = workflow['trigger_data']
                
                creator = interaction.guild.get_member(int(creator_id))
                creator_name = creator.display_name if creator else "Unknown"
                
                status_emoji = "✅" if status == "active" else "⏸️"
                
                # Get trigger channel info
                trigger_info = trigger_type
                if isinstance(trigger_data, dict) and 'channel_id' in trigger_data:
                    channel = interaction.guild.get_channel(int(trigger_data['channel_id']))
                    if channel:
                        trigger_info += f" in {channel.mention}"
                
                embed.add_field(
                    name=f"{status_emoji} {name}",
                    value=f"**Trigger:** {trigger_info}\n"
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
            # Get workflow
            workflow = await self.bot.db.connection.fetchrow(
                "SELECT * FROM workflows WHERE guild_id = $1 AND name = $2",
                str(interaction.guild.id), workflow_name
            )
            
            if not workflow:
                embed = EmbedBuilder.error("Not Found", f"Workflow '{workflow_name}' not found")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Toggle status
            current_status = workflow['status']
            new_status = "inactive" if current_status == "active" else "active"
            
            await self.bot.db.connection.execute(
                "UPDATE workflows SET status = $1 WHERE id = $2",
                new_status, workflow['id']
            )
            
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
