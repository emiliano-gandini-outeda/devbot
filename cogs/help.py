import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder

class Help(commands.Cog):
    """Help and command information"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="help", description="Show available commands")
    async def help_command(self, interaction: discord.Interaction):
        is_admin = self.bot.admin_manager.is_admin(interaction.user)
        
        embed = discord.Embed(
            title="🤖 Bot Commands",
            description="Here are the available commands based on your permissions:",
            color=0x5865F2
        )
        
        # Basic Commands (Everyone)
        basic_commands = [
            "`/create-thread` - Create a new thread from a message",
            "`/rename-thread` - Rename the current thread",
            "`/search-messages` - Search for messages in the current channel",
            "`/remind` - Set a personal reminder",
            "`/list-reminders` - List your active reminders",
            "`/delete-reminder` - Delete a reminder by number",
            "`/add-keyword` - Add a keyword to get notified about",
            "`/remove-keyword` - Remove a keyword from monitoring",
            "`/list-keywords` - List your monitored keywords",
            "`/create-ticket` - Create a new support ticket",
            "`/user-permissions` - Show user permissions in current channel",
            "`/role-info` - Show information about a role",
            "`/export-data` - Request export of your personal data",
            "`/privacy-policy` - View the bot's privacy policy"
        ]
        
        embed.add_field(
            name="📝 Basic Commands",
            value="\n".join(basic_commands),
            inline=False
        )
        
        # Integration Commands
        integration_commands = [
            "`/google-connect` - Connect your Google account",
            "`/calendar-events` - Show your upcoming calendar events",
            "`/notion-databases` - List your Notion databases",
            "`/trello-boards` - List your Trello boards"
        ]
        
        embed.add_field(
            name="🔗 Integrations",
            value="\n".join(integration_commands),
            inline=False
        )
        
        # AI Commands
        ai_commands = [
            "`/summarize` - Summarize recent messages in this channel",
            "`/translate` - Translate text to another language",
            "`/ask-ai` - Ask a question to the AI assistant",
            "`/analyze-tone` - Analyze the tone of recent messages"
        ]
        
        embed.add_field(
            name="🤖 AI Features",
            value="\n".join(ai_commands),
            inline=False
        )
        
        # Notification Commands
        notification_commands = [
            "`/mute-thread` - Mute notifications from current thread",
            "`/unmute-thread` - Unmute notifications from current thread",
            "`/notification-settings` - View your notification settings"
        ]
        
        embed.add_field(
            name="🔔 Notifications",
            value="\n".join(notification_commands),
            inline=False
        )
        
        # Admin Commands (Only for admins)
        if is_admin:
            admin_commands = [
                "`/add-admin-role` - Add a role to the admin list (Administrator only)",
                "`/remove-admin-role` - Remove a role from the admin list (Administrator only)",
                "`/list-admin-roles` - List all admin roles",
                "`/ticket-setup` - Setup ticket system",
                "`/archive-thread` - Archive the current thread",
                "`/assign-role` - Assign a role to a user",
                "`/remove-role` - Remove a role from a user",
                "`/list-tickets` - List all tickets",
                "`/assign-ticket` - Assign a ticket to a user",
                "`/create-workflow` - Create a new automation workflow",
                "`/add-workflow-action` - Add an action to a workflow",
                "`/list-workflows` - List all workflows in this server",
                "`/toggle-workflow` - Enable or disable a workflow",
                "`/remind-channel` - Set a channel reminder"
            ]
            
            embed.add_field(
                name="🛡️ Admin Commands",
                value="\n".join(admin_commands),
                inline=False
            )
            
            embed.add_field(
                name="ℹ️ Admin Note",
                value="You have admin access and can use all commands above.",
                inline=False
            )
        else:
            embed.add_field(
                name="🛡️ Admin Commands",
                value="You need admin permissions to see admin commands.\nAsk an administrator to add your role using `/add-admin-role`",
                inline=False
            )
        
        embed.set_footer(text="Use the commands with their parameters as shown in Discord's slash command interface")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Help(bot))
