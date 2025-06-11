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
            ),
            discord.SelectOption(
                label="📅 Meetings",
                description="Meeting scheduling and management",
                emoji="📅",
                value="meetings"
            ),
            discord.SelectOption(
                label="⚙️ Setup Commands",
                description="Server configuration and setup",
                emoji="⚙️",
                value="setup"
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
            "logging": self.get_logging_embed(),
            "meetings": self.get_meetings_embed(),
            "setup": self.get_setup_embed()
        }
        return embeds.get(category, self.get_basic_embed())
    
    def get_basic_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="📝 Basic Commands",
            description="Essential commands available to all users",
            color=0x5865F2
        )
        
        commands = [
            "`/help` - Show this help menu with interactive categories",
            "`/user-permissions [user]` - Show user permissions in current channel", 
            "`/role-info <role>` - Show detailed information about a role",
            "`/see-user [user]` - View comprehensive user information and stats",
            "`/privacy-export-data` - Export your personal data in JSON format",
            "`/privacy-get-data` - View summary of your stored data",
            "`/privacy-policy` - View the bot's privacy policy",
            "`/terms-of-service` - View the bot's terms of service"
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
            description="Comprehensive support ticket management",
            color=0x5865F2
        )
        
        user_commands = [
            "`/ticket create <title> <description> [priority]` - Create a new support ticket",
            "`/ticket join [ticket_id]` - Request to join an existing ticket", 
            "`/ticket close [ticket_id]` - Close a ticket with transcript",
            "`/ticket private` - Make current ticket private (assigned users only)",
            "`/ticket public` - Make current ticket public (everyone can read)",
            "`/ticket list [status] [user]` - List tickets with optional filters"
        ]
        
        embed.add_field(
            name="User Commands",
            value="\n".join(user_commands),
            inline=False
        )
        
        if self.is_admin:
            admin_commands = [
                "`/setup-tickets <category> <transcript_channel>` - Configure ticket system",
                "`/ticket assign <ticket_id> <assignee>` - Assign ticket to specific user"
            ]
            
            embed.add_field(
                name="Admin Commands",
                value="\n".join(admin_commands),
                inline=False
            )
        
        embed.add_field(
            name="Features",
            value="• Public/private ticket visibility\n• Join request system with approval\n• Automatic transcripts\n• Priority levels (low, medium, high)",
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
            "`/create-thread <message_id> <name>` - Create thread from existing message",
            "`/rename-thread <new_name>` - Rename the current thread",
            "`/search-messages <query> [limit]` - Search messages in current channel",
            "`/pin-message <message_id>` - Pin a message by its ID",
            "`/unpin-message <message_id>` - Unpin a message by its ID"
        ]
        
        embed.add_field(
            name="Available Commands",
            value="\n".join(commands),
            inline=False
        )
        
        if self.is_admin:
            embed.add_field(
                name="Admin Commands", 
                value="`/archive-thread` - Archive current thread with transcript",
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
            "`/remind <time> <message> [send_dm]` - Set personal reminder with DM option",
            "`/list-reminders` - List all your active reminders with details", 
            "`/delete-reminder <number>` - Delete a reminder by its list number"
        ]
        
        embed.add_field(
            name="User Commands",
            value="\n".join(commands),
            inline=False
        )
        
        if self.is_admin:
            admin_commands = [
                "`/remind-channel <time> <message> [channel]` - Set channel-wide reminder",
                "`/setup-reminders <reminder_channel>` - Configure reminder fallback channel"
            ]
            
            embed.add_field(
                name="Admin Commands",
                value="\n".join(admin_commands),
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
            "`/add-keyword <keyword>` - Add keyword to monitor for mentions",
            "`/remove-keyword <keyword>` - Remove keyword from monitoring list",
            "`/list-keywords` - List all your monitored keywords in this server"
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
            "`/google-connect` - Connect your Google account for calendar access",
            "`/calendar-events [count]` - Show your upcoming Google Calendar events",
            "`/create-event <title> <date> <time> [duration]` - Create new calendar event"
        ]
        
        github_commands = [
            "`/track-repo <repo>` - Track GitHub repository for updates",
            "`/list-repos` - List tracked repositories with toggle options", 
            "`/untrack-repo <repo>` - Stop tracking a repository"
        ]
        
        notion_commands = [
            "`/notion-databases` - List your Notion databases (Coming Soon)",
            "`/create-note <title> <content> [database_id]` - Create note in Notion (Coming Soon)",
            "`/notion-search <query>` - Search your Notion workspace (Coming Soon)"
        ]
        
        trello_commands = [
            "`/trello-boards` - List your Trello boards (Coming Soon)",
            "`/create-task <board_id> <list_name> <task_name> [description]` - Create Trello task (Coming Soon)",
            "`/board-cards <board_id>` - View cards in a Trello board (Coming Soon)"
        ]
        
        embed.add_field(name="📅 Google Calendar", value="\n".join(google_commands), inline=False)
        embed.add_field(name="🐙 GitHub", value="\n".join(github_commands), inline=False)
        embed.add_field(name="📝 Notion", value="\n".join(notion_commands), inline=False)
        embed.add_field(name="📋 Trello", value="\n".join(trello_commands), inline=False)
        
        if self.is_admin:
            embed.add_field(
                name="🔧 Admin Setup",
                value="`/setup-github-tracking <channel>` - Configure GitHub notifications channel",
                inline=False
            )
        
        return embed
    
    def get_ai_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🤖 AI Features",
            description="AI-powered productivity and analysis tools",
            color=0x5865F2
        )
        
        commands = [
            "`/summarize [count] [user]` - Summarize recent messages (max 50 messages)",
            "`/translate <text> <target_language>` - Translate text to another language",
            "`/ask-ai <question>` - Ask the AI assistant a question",
            "`/analyze-tone [count]` - Analyze tone/sentiment of recent messages"
        ]
        
        embed.add_field(
            name="Available Commands",
            value="\n".join(commands),
            inline=False
        )
        
        embed.add_field(
            name="Features",
            value="• Message summarization with user filtering\n• Multi-language translation support\n• AI-powered question answering\n• Sentiment analysis and tone detection",
            inline=False
        )
        
        embed.add_field(
            name="Note",
            value="AI features use mock implementations for demonstration. Real implementations would integrate with OpenAI or similar services.",
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
            "`/user-permissions [user]` - Show user permissions in current channel",
            "`/role-info <role>` - Show detailed role information and stats", 
            "`/see-user [user]` - View comprehensive user information"
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
            "`/privacy-export-data` - Export all your personal data in JSON format",
            "`/privacy-delete-data [data_type]` - Delete your data (tickets/reminders/keywords/all)",
            "`/privacy-get-data` - View summary of your stored data",
            "`/privacy-policy` - View the bot's privacy policy",
            "`/terms-of-service` - View the bot's terms of service"
        ]
        
        embed.add_field(
            name="Available Commands",
            value="\n".join(commands),
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
            "`/add-admin-role <role>` - Add role to admin permissions list",
            "`/remove-admin-role <role>` - Remove role from admin permissions",
            "`/list-admin-roles` - List all roles with admin access",
            "`/admin-panel` - View bot status and server configuration dashboard",
            "`/get-data <user>` - Export user's data in JSON format (Admin only)"
        ]
        
        embed.add_field(
            name="Available Commands",
            value="\n".join(admin_commands),
            inline=False
        )
        
        return embed
    
    def get_workflows_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="⚙️ Workflows",
            description="Automation and workflow management",
            color=0x5865F2
        )
        
        if self.is_admin:
            admin_commands = [
                "`/create-workflow <name> <trigger> [trigger_channel] [log_channel]` - Create automation workflow",
                "`/list-workflows` - List all server workflows with status",
                "`/toggle-workflow <workflow_name>` - Enable/disable a workflow"
            ]
        
            embed.add_field(
                name="Admin Commands",
                value="\n".join(admin_commands),
                inline=False
            )
        
            embed.add_field(
                name="Trigger Types",
                value="• `message` - When a message is sent\n• `member_join` - When a member joins\n• `thread_create` - When a thread is created\n• `channel_create` - When a channel is created\n• `message:text` - When specific text is mentioned",
                inline=False
            )
        
            embed.add_field(
                name="Features",
                value="• Custom trigger conditions\n• Channel-specific triggers\n• Workflow logging\n• Enable/disable workflows\n• Action chaining support",
                inline=False
            )
        else:
            embed.add_field(
                name="Access Denied",
                value="Workflow management is only available to administrators.",
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
            admin_commands = [
                "`/logging-setup <log_channel> [events]` - Configure server logging system",
                "`/logging-export [data_type]` - Export server data (logs/tickets/reminders/all)",
                "`/delete-data <data_type> <confirm>` - Delete server data (requires CONFIRM)",
                "`/setup-logs <log_channel>` - Setup basic logging channel"
            ]
            
            embed.add_field(
                name="Admin Commands",
                value="\n".join(admin_commands),
                inline=False
            )
        
        embed.add_field(
            name="Logged Events",
            value="• Message deletions and edits\n• Channel creation, deletion, updates\n• Role creation, deletion, assignments\n• Command usage",
            inline=False
        )
        
        return embed

    def get_meetings_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="📅 Meetings",
            description="Meeting scheduling and management system",
            color=0x5865F2
        )
        
        commands = [
            "`/create-meeting <name> <time> <description> <voice_channel>` - Schedule a new meeting",
            "`/join-meeting <meeting_id>` - Join a scheduled meeting by ID",
            "`/list-meetings` - List all upcoming scheduled meetings"
        ]
        
        embed.add_field(
            name="Available Commands",
            value="\n".join(commands),
            inline=False
        )
        
        if self.is_admin:
            admin_commands = [
                "`/setup-meetings <announcement_channel> <voice_channel>` - Configure meeting system"
            ]
            
            embed.add_field(
                name="Admin Commands", 
                value="\n".join(admin_commands),
                inline=False
            )
        
        embed.add_field(
            name="Time Format Examples",
            value="`1h` = 1 hour\n`30m` = 30 minutes\n`2d` = 2 days\n`1h30m` = 1 hour 30 minutes",
            inline=False
        )
        
        return embed

    def get_setup_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="⚙️ Setup Commands",
            description="Server configuration and setup commands (Admin only)",
            color=0x5865F2
        )
        
        if self.is_admin:
            setup_commands = [
                "`/setup-tickets <category> <transcript_channel>` - Configure ticket system",
                "`/setup-github-tracking <channel>` - Configure GitHub notifications",
                "`/setup-logs <log_channel>` - Configure basic logging",
                "`/setup-meetings <announcement_channel> <voice_channel>` - Configure meetings",
                "`/setup-reminders <reminder_channel>` - Configure reminder fallback channel",
                "`/setup-threads <thread_log_channel>` - Configure thread logging"
            ]
            
            embed.add_field(
                name="Setup Commands",
                value="\n".join(setup_commands),
                inline=False
            )
            
            embed.add_field(
                name="Note",
                value="These commands configure various bot features for your server. Run them once to enable the corresponding functionality.",
                inline=False
            )
        else:
            embed.add_field(
                name="Access Denied",
                value="Setup commands are only available to administrators.",
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
            description="Welcome to the devBot help system! Use the dropdown menu below to explore different command categories.\n\n"
                       f"**Your Access Level:** {'Administrator' if is_admin else 'User'}\n"
                       f"**Total Categories:** {14 if is_admin else 11}",
            color=0x5865F2
        )
        
        embed.add_field(
            name="📋 Quick Start",
            value="• Select a category from the dropdown below\n"
                  "• Each category shows relevant commands\n"
                  "• Admin categories are only visible to administrators",
            inline=False
        )
        
        embed.set_footer(text="Select a category below to view detailed commands")
        
        view = HelpView(self.bot, is_admin)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Help(bot))
