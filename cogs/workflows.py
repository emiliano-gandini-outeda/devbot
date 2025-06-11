import discord
from discord.ext import commands
from discord import app_commands
import json
from utils.helpers import EmbedBuilder
from config.constants import WorkflowStatus
from datetime import datetime

class WorkflowActionView(discord.ui.View):
    def __init__(self, workflow_name: str, guild_id: str):
        super().__init__(timeout=300)
        self.workflow_name = workflow_name
        self.guild_id = guild_id

class ActionTypeSelect(discord.ui.Select):
    def __init__(self, workflow_name: str, guild_id: str):
        self.workflow_name = workflow_name
        self.guild_id = guild_id
        
        options = [
            discord.SelectOption(
                label="Send Message",
                description="Send a message to a channel",
                emoji="💬",
                value="send_message"
            ),
            discord.SelectOption(
                label="Send Embed",
                description="Send an embed with custom fields",
                emoji="📋",
                value="send_embed"
            ),
            discord.SelectOption(
                label="Delete Message",
                description="Delete the message that triggered the workflow",
                emoji="🗑️",
                value="delete_message"
            ),
            discord.SelectOption(
                label="Timeout User",
                description="Timeout the user who triggered the workflow",
                emoji="⏰",
                value="timeout_user"
            )
        ]
        
        super().__init__(
            placeholder="Choose an action type...",
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        action_type = self.values[0]
        
        if action_type == "send_message":
            modal = SendMessageModal(self.workflow_name, self.guild_id)
        elif action_type == "send_embed":
            modal = SendEmbedModal(self.workflow_name, self.guild_id)
        elif action_type == "delete_message":
            modal = DeleteMessageModal(self.workflow_name, self.guild_id)
        elif action_type == "timeout_user":
            modal = TimeoutUserModal(self.workflow_name, self.guild_id)
        
        await interaction.response.send_modal(modal)

class SendMessageModal(discord.ui.Modal):
    def __init__(self, workflow_name: str, guild_id: str):
        super().__init__(title="Add Send Message Action")
        self.workflow_name = workflow_name
        self.guild_id = guild_id
        
        self.channel_input = discord.ui.TextInput(
            label="Channel ID or 'same'",
            placeholder="Enter channel ID or 'same' for trigger channel",
            default="same",
            max_length=100
        )
        
        self.message_input = discord.ui.TextInput(
            label="Message Content",
            placeholder="Use {user} for user mention, {channel} for channel mention",
            style=discord.TextStyle.paragraph,
            max_length=2000
        )
        
        self.ping_input = discord.ui.TextInput(
            label="Ping Options (optional)",
            placeholder="@everyone, @here, or role ID",
            required=False,
            max_length=100
        )
        
        self.add_item(self.channel_input)
        self.add_item(self.message_input)
        self.add_item(self.ping_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        bot = interaction.client
        
        action_data = {
            "type": "send_message",
            "data": {
                "channel_id": self.channel_input.value,
                "message": self.message_input.value,
                "ping": self.ping_input.value if self.ping_input.value else None
            }
        }
        
        await self.add_action_to_workflow(bot, action_data)
        
        embed = EmbedBuilder.success(
            "Action Added",
            f"Send message action added to workflow **{self.workflow_name}**"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def add_action_to_workflow(self, bot, action_data):
        # Get current workflow
        workflow = await bot.db.connection.fetchrow(
            "SELECT * FROM workflows WHERE guild_id = $1 AND name = $2",
            self.guild_id, self.workflow_name
        )
        
        if workflow:
            current_actions = json.loads(workflow['actions']) if workflow['actions'] else []
            current_actions.append(action_data)
            
            await bot.db.connection.execute(
                "UPDATE workflows SET actions = $1 WHERE id = $2",
                json.dumps(current_actions), workflow['id']
            )

class SendEmbedModal(discord.ui.Modal):
    def __init__(self, workflow_name: str, guild_id: str):
        super().__init__(title="Add Send Embed Action")
        self.workflow_name = workflow_name
        self.guild_id = guild_id
        
        self.channel_input = discord.ui.TextInput(
            label="Channel ID or 'same'",
            placeholder="Enter channel ID or 'same' for trigger channel",
            default="same",
            max_length=100
        )
        
        self.title_input = discord.ui.TextInput(
            label="Embed Title",
            placeholder="Title of the embed",
            max_length=256
        )
        
        self.description_input = discord.ui.TextInput(
            label="Embed Description",
            placeholder="Main description of the embed",
            style=discord.TextStyle.paragraph,
            max_length=2048
        )
        
        self.fields_input = discord.ui.TextInput(
            label="Fields (3 max)",
            placeholder="Format: Field1|Value1|inline\nField2|Value2|inline\nField3|Value3|inline",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000
        )
        
        self.add_item(self.channel_input)
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.fields_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        bot = interaction.client
        
        # Parse fields
        fields = []
        if self.fields_input.value:
            field_lines = self.fields_input.value.strip().split('\n')
            for line in field_lines[:3]:  # Max 3 fields
                parts = line.split('|')
                if len(parts) >= 2:
                    field = {
                        "name": parts[0].strip(),
                        "value": parts[1].strip(),
                        "inline": len(parts) > 2 and parts[2].strip().lower() == "inline"
                    }
                    fields.append(field)
        
        action_data = {
            "type": "send_embed",
            "data": {
                "channel_id": self.channel_input.value,
                "title": self.title_input.value,
                "description": self.description_input.value,
                "fields": fields
            }
        }
        
        await self.add_action_to_workflow(bot, action_data)
        
        embed = EmbedBuilder.success(
            "Action Added",
            f"Send embed action added to workflow **{self.workflow_name}**"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def add_action_to_workflow(self, bot, action_data):
        # Get current workflow
        workflow = await bot.db.connection.fetchrow(
            "SELECT * FROM workflows WHERE guild_id = $1 AND name = $2",
            self.guild_id, self.workflow_name
        )
        
        if workflow:
            current_actions = json.loads(workflow['actions']) if workflow['actions'] else []
            current_actions.append(action_data)
            
            await bot.db.connection.execute(
                "UPDATE workflows SET actions = $1 WHERE id = $2",
                json.dumps(current_actions), workflow['id']
            )

class DeleteMessageModal(discord.ui.Modal):
    def __init__(self, workflow_name: str, guild_id: str):
        super().__init__(title="Add Delete Message Action")
        self.workflow_name = workflow_name
        self.guild_id = guild_id
        
        self.confirmation_input = discord.ui.TextInput(
            label="Confirmation",
            placeholder="Type 'DELETE' to confirm this action",
            max_length=10
        )
        
        self.add_item(self.confirmation_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        if self.confirmation_input.value.upper() != "DELETE":
            embed = EmbedBuilder.error(
                "Invalid Confirmation",
                "You must type 'DELETE' to confirm this action"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        bot = interaction.client
        
        action_data = {
            "type": "delete_message",
            "data": {}
        }
        
        await self.add_action_to_workflow(bot, action_data)
        
        embed = EmbedBuilder.success(
            "Action Added",
            f"Delete message action added to workflow **{self.workflow_name}**"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def add_action_to_workflow(self, bot, action_data):
        # Get current workflow
        workflow = await bot.db.connection.fetchrow(
            "SELECT * FROM workflows WHERE guild_id = $1 AND name = $2",
            self.guild_id, self.workflow_name
        )
        
        if workflow:
            current_actions = json.loads(workflow['actions']) if workflow['actions'] else []
            current_actions.append(action_data)
            
            await bot.db.connection.execute(
                "UPDATE workflows SET actions = $1 WHERE id = $2",
                json.dumps(current_actions), workflow['id']
            )

class TimeoutDurationSelect(discord.ui.Select):
    def __init__(self, workflow_name: str, guild_id: str):
        self.workflow_name = workflow_name
        self.guild_id = guild_id
        
        options = [
            discord.SelectOption(label="60 seconds", value="60"),
            discord.SelectOption(label="5 minutes", value="300"),
            discord.SelectOption(label="10 minutes", value="600"),
            discord.SelectOption(label="1 hour", value="3600"),
            discord.SelectOption(label="1 day", value="86400"),
            discord.SelectOption(label="1 week", value="604800")
        ]
        
        super().__init__(
            placeholder="Select timeout duration...",
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        duration_seconds = int(self.values[0])
        
        action_data = {
            "type": "timeout_user",
            "data": {
                "duration": duration_seconds
            }
        }
        
        # Get current workflow
        workflow = await bot.db.connection.fetchrow(
            "SELECT * FROM workflows WHERE guild_id = $1 AND name = $2",
            self.guild_id, self.workflow_name
        )
        
        if workflow:
            current_actions = json.loads(workflow['actions']) if workflow['actions'] else []
            current_actions.append(action_data)
            
            await bot.db.connection.execute(
                "UPDATE workflows SET actions = $1 WHERE id = $2",
                json.dumps(current_actions), workflow['id']
            )
        
        duration_text = {
            "60": "60 seconds",
            "300": "5 minutes", 
            "600": "10 minutes",
            "3600": "1 hour",
            "86400": "1 day",
            "604800": "1 week"
        }[str(duration_seconds)]
        
        embed = EmbedBuilder.success(
            "Action Added",
            f"Timeout user action ({duration_text}) added to workflow **{self.workflow_name}**"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class TimeoutUserModal(discord.ui.Modal):
    def __init__(self, workflow_name: str, guild_id: str):
        super().__init__(title="Add Timeout User Action")
        self.workflow_name = workflow_name
        self.guild_id = guild_id
    
    async def on_submit(self, interaction: discord.Interaction):
        # Show duration selection
        view = discord.ui.View()
        view.add_item(TimeoutDurationSelect(self.workflow_name, self.guild_id))
        
        embed = EmbedBuilder.info(
            "Select Timeout Duration",
            "Choose how long to timeout the user:"
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class Workflows(commands.Cog):
    """Automation workflows"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="create-workflow", description="Create a new automation workflow")
    @app_commands.describe(
        name="Workflow name",
        trigger="Trigger type (message:text, member_join, thread_create, channel_create)",
        trigger_channel="Channel to monitor for triggers (optional)",
        log_channel="Channel to log workflow executions (optional)"
    )
    async def create_workflow(self, interaction: discord.Interaction, name: str, trigger: str, trigger_channel: discord.TextChannel = None, log_channel: discord.TextChannel = None):
        await interaction.response.defer()
        
        valid_triggers = ["member_join", "thread_create", "channel_create"]
        
        # Check if it's a message trigger with text
        if trigger.startswith("message:"):
            if len(trigger.split(":", 1)) != 2 or not trigger.split(":", 1)[1].strip():
                embed = EmbedBuilder.error(
                    "Invalid Trigger Format",
                    "Message triggers must be in format: `message:keyword`\n"
                    "Example: `message:hello` (case insensitive)"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
        elif trigger not in valid_triggers:
            embed = EmbedBuilder.error(
                "Invalid Trigger",
                f"Trigger must be one of: {', '.join(valid_triggers)} or `message:text`\n"
                "Example: `message:hello` for case-insensitive keyword matching"
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
            
            # Extract keyword for display if it's a message trigger
            trigger_display = trigger
            if trigger.startswith("message:"):
                keyword = trigger.split(":", 1)[1]
                trigger_display = f"Message containing '{keyword}' (case insensitive)"
            
            embed = EmbedBuilder.success(
                "Workflow Created",
                f"**{name}** workflow created successfully!\n"
                f"**Trigger:** {trigger_display}\n"
                f"**Trigger Channel:** {trigger_channel.mention if trigger_channel else 'All channels'}\n"
                f"**Log Channel:** {log_channel.mention if log_channel else 'None'}\n"
                f"**Status:** Active\n\n"
                f"Use `/add-workflow-action` to add actions to this workflow."
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to create workflow: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="add-workflow-action", description="Add an action to an existing workflow")
    @app_commands.describe(workflow_name="Name of the workflow to add action to")
    async def add_workflow_action(self, interaction: discord.Interaction, workflow_name: str):
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Check if workflow exists
            workflow = await self.bot.db.connection.fetchrow(
                "SELECT * FROM workflows WHERE guild_id = $1 AND name = $2",
                str(interaction.guild.id), workflow_name
            )
            
            if not workflow:
                embed = EmbedBuilder.error("Not Found", f"Workflow '{workflow_name}' not found")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Show action type selection
            view = discord.ui.View()
            view.add_item(ActionTypeSelect(workflow_name, str(interaction.guild.id)))
            
            embed = EmbedBuilder.info(
                "Add Workflow Action",
                f"Select an action type to add to workflow **{workflow_name}**:"
            )
            
            embed.add_field(
                name="Available Actions",
                value="💬 **Send Message** - Send a message to a channel\n"
                      "📋 **Send Embed** - Send an embed with custom fields\n"
                      "🗑️ **Delete Message** - Delete the trigger message\n"
                      "⏰ **Timeout User** - Timeout the user who triggered",
                inline=False
            )
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to add workflow action: {str(e)}")
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
                actions = json.loads(workflow['actions']) if workflow['actions'] else []
                
                creator = interaction.guild.get_member(int(creator_id))
                creator_name = creator.display_name if creator else "Unknown"
                
                status_emoji = "✅" if status == "active" else "⏸️"
                
                # Get trigger info
                trigger_info = trigger_type
                if trigger_type.startswith("message:"):
                    keyword = trigger_type.split(":", 1)[1]
                    trigger_info = f"Message: '{keyword}'"
                
                if isinstance(trigger_data, dict) and 'channel_id' in trigger_data:
                    channel = interaction.guild.get_channel(int(trigger_data['channel_id']))
                    if channel:
                        trigger_info += f" in {channel.mention}"
                
                # Count actions by type
                action_counts = {}
                for action in actions:
                    action_type = action.get('type', 'unknown')
                    action_counts[action_type] = action_counts.get(action_type, 0) + 1
                
                action_summary = ", ".join([f"{count} {type.replace('_', ' ')}" for type, count in action_counts.items()]) if action_counts else "No actions"
                
                embed.add_field(
                    name=f"{status_emoji} {name}",
                    value=f"**Trigger:** {trigger_info}\n"
                          f"**Actions:** {action_summary}\n"
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
