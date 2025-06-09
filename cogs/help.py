import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder

class HelpDropdown(discord.ui.Select):
    def __init__(self, bot, is_admin: bool):
        self.bot = bot
        self.is_admin = is_admin
        
        options = [
            discord.SelectOption(
                label="📝 Basic Commands",
                description="Essential commands for all users",
                emoji="📝",
                value="basic"
            ),
            discord.SelectOption(
                label="🎫 Ticket System",
                description="Support ticket management",
                emoji="🎫",
                value="tickets"
            ),
            discord.SelectOption(
                label="🗨️ Conversations",
                description="Thread and message management",
                emoji="🗨️",
                value="conversations"
            ),
            discord.SelectOption(
                label="⏰ Reminders",
                description="Personal and channel reminders",
                emoji="⏰",
                value="reminders"
            ),
            discord.SelectOption(
                label="🔔 Notifications",
                description="Keyword alerts and muting",
                emoji="🔔",
                value="notifications"
            ),
            discord.SelectOption(
                label="🔗 Integrations",
                description="Google, Notion, Trello connections",
                emoji="🔗",
                value="integrations"
            ),
            discord.SelectOption(
                label="🤖 AI Features",
                description="Summarization, translation, analysis",
                emoji="🤖",
                value="ai"
            ),
            discord.SelectOption(
                label="👥 Roles & Permissions",
                description="Role management and permissions",
                emoji="👥",
                value="roles"
            ),
            discord.SelectOption(
                label="🔒 Privacy & Data",
                description="Data export and privacy controls",
                emoji="🔒",
                value="privacy"
            )
        ]
        
        if is_admin:
            options.extend([
                discord.SelectOption(
                    label="🛡️ Admin Commands",
                    description="Administrator-only commands",
                    emoji="🛡️",
                    value="admin"
                ),
                discord.SelectOption(
                    label="⚙️ Workflows",
                    description="Automation and workflow management",
                    emoji="⚙️",
                    value="workflows"
                ),
                discord.SelectOption(
                    label="📊 Logging",
                    description="Server logging configuration",
                    emoji="📊",
                    value="logging"
                )
            ])
        
        super().__init__(
            placeholder="Choose a category to view commands...",
            min_values=1,
            max_values=1,
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        embed = self.get_category_embed(category)
        await interaction.response.edit_message(embed=embed, view=self.view)
    
    def get_category_embed(self, category: str) -> discord.Embed:
        embeds = {
            "basic": self.get_basic_embed(),
            "tickets": self.get_tickets_embed(),
            "conversations": self.get_conversations_embed(),
            "reminders": self.get_reminders_embed(),
            "notifications": self.get_notifications_embed(),
            "integrations": self.get_integrations_embed(),
            "ai": self.get_ai_embed(),
            "roles": self.get_roles_embed(),
            "privacy": self.get_privacy_embed(),
            "admin": self.get_admin_embed(),
            "workflows": self.get_workflows_embed(),
            "logging": self.get_logging_embed()
        }
        return embeds.get(category, self.get_basic_embed())
    
    def get_basic_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="📝 Basic Commands",
            description="Essential commands available to all users",
            color=0x5865F2
        )
        
        commands = [
            "`/help` - Show this help menu",
            "`/user-permissions [user]` - Show user permissions",
            "`/role-info <role>` - Show role information",
            "`/export-data` - Export your personal data",
            "`/privacy-policy` - View privacy policy"
        ]
        
        embed.add_field(
            name="Available Commands",
            value="\n".join(commands),
            inline=False
        )
        
        return embed
    
    def get_tickets_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎫 Ticket System",
            description="Support ticket management commands",
            color=0x5865F2
        )
        
        user_commands = [
            "`/ticket create <title> <description> [priority]` - Create a new support ticket",
            "`/ticket join` - Request to join current ticket",
            "`/ticket private` - Make ticket private (assigned users only)",
            "`/ticket public` - Make ticket public (everyone can read)",
            "`/ticket list [status] [user]` - List tickets"
        ]
        
        embed.add_field(
            name="User Commands",
            value="\n".join(user_commands),
            inline=False
        )
        
        if self.is_admin:
            admin_commands = [
                "`/ticket-system-setup <category> <transcript_channel>` - Setup ticket system",
                "`/ticket assign <ticket_id> <assignee>` - Assign ticket to user"
            ]
            
            embed.add_field(
                name="Admin Commands",
                value="\n".join(admin_commands),
                inline=False
            )
        
        return embed
    
    def get_conversations_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🗨️ Conversations",
            description="Thread and message management",
            color=0x5865F2
        )
        
        commands = [
            "`/create-thread <message_id> <name>` - Create thread from message",
            "`/rename-thread <new_name>` - Rename current thread",
            "`/search-messages <query> [limit]` - Search messages in channel"
        ]
        
        embed.add_field(
            name="Available Commands",
            value="\n".join(commands),
            inline=False
        )
        
        if self.is_admin:
            embed.add_field(
                name="Admin Commands",
                value="`/archive-thread` - Archive current thread",
                inline=False
            )
        
        return embed
    
    def get_reminders_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="⏰ Reminders",
            description="Personal and channel reminder system",
            color=0x5865F2
        )
        
        commands = [
            "`/remind <time> <message>` - Set personal reminder",
            "`/list-reminders` - List your active reminders",
            "`/delete-reminder <number>` - Delete a reminder"
        ]
        
        embed.add_field(
            name="User Commands",
            value="\n".join(commands),
            inline=False
        )
        
        if self.is_admin:
            embed.add_field(
                name="Admin Commands",
                value="`/remind-channel <time> <message> [channel]` - Set channel reminder",
                inline=False
            )
        
        embed.add_field(
            name="Time Format Examples",
            value="`1h` = 1 hour\n`30m` = 30 minutes\n`2d` = 2 days\n`1h30m` = 1 hour 30 minutes",
            inline=False
        )
        
        return embed
    
    def get_notifications_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🔔 Notifications",
            description="Keyword alerts and notification management",
            color=0x5865F2
        )
        
        commands = [
            "`/add-keyword <keyword>` - Add keyword to monitor",
            "`/remove-keyword <keyword>` - Remove keyword from monitoring",
            "`/list-keywords` - List your monitored keywords"
        ]
        
        embed.add_field(
            name="Available Commands",
            value="\n".join(commands),
            inline=False
        )
        
        embed.add_field(
            name="How It Works",
            value="• Get notified when your keywords are mentioned\n• Notifications sent via DM\n• Keywords are case-insensitive",
            inline=False
        )
        
        return embed
    
    def get_integrations_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🔗 Integrations",
            description="External service integrations",
            color=0x5865F2
        )
        
        google_commands = [
            "`/google-connect` - Connect your Google account",
            "`/calendar-events [count]` - Show upcoming calendar events"
        ]
        
        notion_commands = [
            "`/notion-databases` - List your Notion databases",
            "`/create-note <title> <content>` - Create Notion note"
        ]
        
        trello_commands = [
            "`/trello-boards` - List your Trello boards",
            "`/create-task <board_id> <list_name> <task_name>` - Create Trello task"
        ]
        
        embed.add_field(name="📅 Google Calendar", value="\n".join(google_commands), inline=False)
        embed.add_field(name="📚 Notion", value="\n".join(notion_commands), inline=False)
        embed.add_field(name="📋 Trello", value="\n".join(trello_commands), inline=False)
        
        return embed
    
    def get_ai_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🤖 AI Features",
            description="AI-powered productivity and analysis tools",
            color=0x5865F2
        )
        
        commands = [
            "`/summarize [count] [user]` - Summarize recent messages",
            "`/translate <text> <target_language>` - Translate text",
            "`/ask-ai <question>` - Ask AI assistant",
            "`/analyze-tone [count]` - Analyze message tone/sentiment"
        ]
        
        embed.add_field(
            name="Available Commands",
            value="\n".join(commands),
            inline=False
        )
        
        embed.add_field(
            name="Supported Languages",
            value="Spanish, French, German, Italian, Portuguese, and more",
            inline=False
        )
        
        return embed
    
    def get_roles_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="👥 Roles & Permissions",
            description="Role management and permission tools",
            color=0x5865F2
        )
        
        commands = [
            "`/user-permissions [user]` - Show user permissions",
            "`/role-info <role>` - Show role information",
            "`/see-user [user]` - View user information"
        ]
        
        embed.add_field(
            name="User Commands",
            value="\n".join(commands),
            inline=False
        )
        
        if self.is_admin:
            admin_commands = [
                "`/assign-role <user> <role>` - Assign role to user",
                "`/remove-role <user> <role>` - Remove role from user"
            ]
            
            embed.add_field(
                name="Admin Commands",
                value="\n".join(admin_commands),
                inline=False
            )
        
        return embed
    
    def get_privacy_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🔒 Privacy & Data",
            description="Data management and privacy controls",
            color=0x5865F2
        )
        
        commands = [
            "`/export-data` - Request export of your personal data",
            "`/delete-data` - Request deletion of your personal data",
            "`/privacy-policy` - View the bot's privacy policy",
            "`/get-data` - View summary of your stored data"
        ]
        
        embed.add_field(
            name="Available Commands",
            value="\n".join(commands),
            inline=False
        )
        
        embed.add_field(
            name="Your Rights",
            value="• Request data export in JSON format\n• Request complete data deletion\n• View what data is collected",
            inline=False
        )
        
        return embed
    
    def get_admin_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🛡️ Admin Commands",
            description="Administrator-only commands",
            color=0xED4245
        )
        
        admin_commands = [
            "`/add-admin-role <role>` - Add role to admin list",
            "`/remove-admin-role <role>` - Remove role from admin list",
            "`/list-admin-roles` - List all admin roles",
            "`/admin-panel` - View bot status and configuration",
            "`/ticket-system-setup <category> <transcript_channel>` - Setup tickets",
            "`/server-logs-setup <log_channel>` - Setup server logging",
            "`/ticket assign <ticket_id> <assignee>` - Assign ticket",
            "`/archive-thread` - Archive current thread",
            "`/assign-role <user> <role>` - Assign role to user",
            "`/remove-role <user> <role>` - Remove role from user",
            "`/get-data <user>` - Get user data (Admin only)"
        ]
        
        embed.add_field(
            name="Available Commands",
            value="\n".join(admin_commands),
            inline=False
        )
        
        embed.add_field(
            name="⚠️ Important",
            value="These commands require admin permissions or admin role assignment.",
            inline=False
        )
        
        return embed
    
    def get_workflows_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="⚙️ Workflows",
            description="Automation and workflow management",
            color=0x5865F2
        )
        
        commands = [
            "`/create-workflow <name> <trigger> [trigger_channel] [log_channel]` - Create workflow",
            "`/list-workflows` - List all server workflows",
            "`/toggle-workflow <workflow_name>` - Enable/disable workflow"
        ]
        
        embed.add_field(
            name="User Commands",
            value="\n".join(commands),
            inline=False
        )
        
        if self.is_admin:
            embed.add_field(
                name="Admin Commands",
                value="`/add-workflow-action <workflow_name> <action_type> [parameters]` - Add action to workflow",
                inline=False
            )
        
        embed.add_field(
            name="Trigger Types",
            value="• `message` - When messages are sent\n• `member_join` - When users join\n• `thread_create` - When threads are created\n• `channel_create` - When channels are created",
            inline=False
        )
        
        embed.add_field(
            name="Action Types",
            value="• `send_message` - Send message to channel\n• `add_role` - Add role to user\n• `create_channel` - Create new channel\n• `send_dm` - Send direct message",
            inline=False
        )
        
        return embed
    
    def get_logging_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="📊 Logging",
            description="Server logging and monitoring",
            color=0x5865F2
        )
        
        if self.is_admin:
            embed.add_field(
                name="Admin Commands",
                value="`/server-logs-setup <log_channel>` - Configure logging channel",
                inline=False
            )
        
        embed.add_field(
            name="Logged Events",
            value="• Message deletions and edits\n• Channel creation, deletion, updates\n• Role creation, deletion, assignments\n• Command usage\n• Workflow executions",
            inline=False
        )
        
        embed.add_field(
            name="Features",
            value="• Real-time event logging\n• Detailed event information\n• User action tracking\n• Audit trail maintenance",
            inline=False
        )
        
        return embed

class HelpView(discord.ui.View):
    def __init__(self, bot, is_admin: bool):
        super().__init__(timeout=300)
        self.add_item(HelpDropdown(bot, is_admin))
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

class Help(commands.Cog):
    """Help and command information with dropdown menu"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="help", description="Show available commands in an interactive menu")
    async def help_command(self, interaction: discord.Interaction):
        is_admin = self.bot.admin_manager.is_admin(interaction.user) if self.bot.admin_manager else False
        
        embed = discord.Embed(
            title="🤖 Bot Help Menu",
            description="Welcome to the Discord Bot help system! Use the dropdown menu below to explore different command categories.\n\n"
                       f"**Your Access Level:** {'Administrator' if is_admin else 'User'}\n"
                       f"**Total Categories:** {12 if is_admin else 9}",
            color=0x5865F2
        )
        
        embed.add_field(
            name="📋 Quick Start",
            value="• Select a category from the dropdown below\n"
                  "• Each category shows relevant commands\n"
                  "• Admin categories are only visible to administrators",
            inline=False
        )
        
        embed.add_field(
            name="🔧 Setup Commands",
            value="• `/ticket-system-setup` - Configure support tickets\n"
                  "• `/server-logs-setup` - Configure server logging\n"
                  "• `/add-admin-role` - Add admin roles",
            inline=True
        )
        
        embed.add_field(
            name="🚀 Popular Commands",
            value="• `/ticket create` - Get support\n"
                  "• `/remind` - Set reminders\n"
                  "• `/summarize` - AI summaries",
            inline=True
        )
        
        embed.set_footer(text="Select a category below to view detailed commands")
        
        view = HelpView(self.bot, is_admin)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    cog = Help(bot)
    await bot.add_cog(cog)
    
    # Sync commands to all guilds
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"❓ Synced Help commands to {guild.name}")
        except Exception as e:
            print(f"❌ Failed to sync Help commands to {guild.name}: {e}")
    
    print(f"❓ Successfully loaded Help cog with 1 command")
