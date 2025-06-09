import discord
from discord.ext import commands
from discord import app_commands
import json
from utils.helpers import EmbedBuilder
from config.constants import WorkflowStatus
import traceback

class Workflows(commands.Cog):
    """Automation workflows similar to Slack workflows"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="create-workflow", description="Create a new automation workflow")
    @app_commands.describe(
        name="Workflow name",
        trigger="Trigger type (message, member_join, thread_create, channel_create)",
        trigger_channel="Channel to monitor for triggers (leave empty for all channels)",
        log_channel="Channel to log workflow executions (optional)"
    )
    async def create_workflow(self, interaction: discord.Interaction, name: str, trigger: str, trigger_channel: discord.TextChannel = None, log_channel: discord.TextChannel = None):
        await interaction.response.defer()
        
        valid_triggers = ["message", "member_join", "thread_create", "channel_create"]
        if trigger not in valid_triggers:
            embed = EmbedBuilder.error(
                "Invalid Trigger",
                f"Trigger must be one of: {', '.join(valid_triggers)}"
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
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO workflows (name, guild_id, creator_id, trigger_type, trigger_data, actions, status)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    name, str(interaction.guild.id), str(interaction.user.id), trigger, 
                    json.dumps(trigger_data), json.dumps([]), WorkflowStatus.ACTIVE.value
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT INTO workflows (name, guild_id, creator_id, trigger_type, trigger_data, actions, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (name, str(interaction.guild.id), str(interaction.user.id), trigger, 
                     json.dumps(trigger_data), json.dumps([]), WorkflowStatus.ACTIVE.value)
                )
                await self.bot.db.connection.commit()
            
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
                    trigger_data = workflow['trigger_data']
                else:
                    creator_id = workflow[3]
                    name = workflow[1]
                    trigger_type = workflow[4]
                    status = workflow[7]
                    trigger_data = json.loads(workflow[5]) if workflow[5] else {}
                
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

    @app_commands.command(name="add-workflow-action", description="Add an action to a workflow (Admin only)")
    @app_commands.describe(
        workflow_name="Name of the workflow",
        action_type="Type of action (send_message, add_role, create_channel, send_dm)",
        channel="Channel for the action (use 'same' for trigger channel or mention specific channel)",
        message="Message to send (for send_message and send_dm actions)",
        role="Role to add (for add_role action)",
        channel_name="Name for new channel (for create_channel action)"
    )
    async def add_workflow_action(self, interaction: discord.Interaction, workflow_name: str, action_type: str, channel: str = "same", message: str = None, role: discord.Role = None, channel_name: str = None):
        if not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can modify workflows")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        valid_actions = ["send_message", "add_role", "create_channel", "send_dm"]
        if action_type not in valid_actions:
            embed = EmbedBuilder.error(
                "Invalid Action Type",
                f"Action type must be one of: {', '.join(valid_actions)}"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        try:
            # Get workflow
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
            
            # Prepare action data
            action_data = {}
            
            # Parse channel
            if channel == "same":
                action_data['channel_id'] = "same"
            else:
                # Try to extract channel ID from mention
                if channel.startswith('<#') and channel.endswith('>'):
                    channel_id = channel[2:-1]
                    target_channel = interaction.guild.get_channel(int(channel_id))
                    if target_channel:
                        action_data['channel_id'] = channel_id
                    else:
                        embed = EmbedBuilder.error("Invalid Channel", "The specified channel was not found")
                        await interaction.followup.send(embed=embed, ephemeral=True)
                        return
                else:
                    embed = EmbedBuilder.error("Invalid Channel", "Please mention a channel (e.g., #general) or use 'same'")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
            
            # Add action-specific data
            if action_type == "send_message":
                if not message:
                    embed = EmbedBuilder.error("Missing Parameter", "Message is required for send_message action")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                action_data['message'] = message
            
            elif action_type == "add_role":
                if not role:
                    embed = EmbedBuilder.error("Missing Parameter", "Role is required for add_role action")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                action_data['role_id'] = str(role.id)
            
            elif action_type == "create_channel":
                if not channel_name:
                    embed = EmbedBuilder.error("Missing Parameter", "Channel name is required for create_channel action")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                action_data['name'] = channel_name
                action_data['type'] = 'text'  # Default to text channel
            
            elif action_type == "send_dm":
                if not message:
                    embed = EmbedBuilder.error("Missing Parameter", "Message is required for send_dm action")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                action_data['message'] = message
            
            # Get current actions
            current_actions = workflow['actions'] if self.bot.db.is_postgresql else workflow[6]
            if isinstance(current_actions, str):
                current_actions = json.loads(current_actions)
            elif current_actions is None:
                current_actions = []
            
            # Add new action
            new_action = {
                "type": action_type,
                "data": action_data,
                "added_by": str(interaction.user.id),
                "added_at": str(discord.utils.utcnow())
            }
            current_actions.append(new_action)
            
            # Update workflow
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "UPDATE workflows SET actions = $1 WHERE id = $2",
                    json.dumps(current_actions), workflow['id']
                )
            else:
                await self.bot.db.connection.execute(
                    "UPDATE workflows SET actions = ? WHERE id = ?",
                    (json.dumps(current_actions), workflow[0])
                )
                await self.bot.db.connection.commit()
            
            # Format action description - Fixed f-string backslash issue
            action_desc = f"**Type:** {action_type}\n"
            if action_type == "send_message":
                channel_text = 'Same as trigger' if channel == 'same' else f'<#{action_data["channel_id"]}>'
                action_desc += f"**Channel:** {channel_text}\n"
                message_preview = message[:100] + ('...' if len(message) > 100 else '')
                action_desc += f"**Message:** {message_preview}"
            elif action_type == "add_role":
                action_desc += f"**Role:** {role.mention}"
            elif action_type == "create_channel":
                action_desc += f"**Channel Name:** {channel_name}"
            elif action_type == "send_dm":
                message_preview = message[:100] + ('...' if len(message) > 100 else '')
                action_desc += f"**Message:** {message_preview}"
            
            embed = EmbedBuilder.success(
                "Action Added",
                f"Added action to workflow **{workflow_name}**\n\n{action_desc}"
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to add workflow action: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    try:
        cog = Workflows(bot)
        await bot.add_cog(cog)
        
        # Ensure commands are added to the tree
        for command in cog.__cog_app_commands__:
            if command not in bot.tree.get_commands():
                bot.tree.add_command(command)
        
        # List all commands from this cog for debugging
        commands = [c.name for c in cog.get_app_commands()]
        print(f"🔄 Successfully loaded {len(commands)} workflow commands: {', '.join(commands)}")
    except Exception as e:
        print(f"❌ Failed to load Workflows cog: {e}")
        traceback.print_exc()
