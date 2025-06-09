import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder

class Logging(commands.Cog):
    """Server logging functionality"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="setup-logs", description="Setup logging channel (Admin only)")
    @app_commands.describe(log_channel="Channel where logs will be sent")
    async def setup_logs(self, interaction: discord.Interaction, log_channel: discord.TextChannel):
        if not self.bot.admin_manager.is_admin(interaction.user):
            embed = EmbedBuilder.error("Permission Denied", "Only administrators can setup logging")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            config = {
                'log_channel_id': str(log_channel.id),
                'setup_by': str(interaction.user.id),
                'setup_at': str(discord.utils.utcnow())
            }
            
            await self.bot.logging_manager.save_log_config(str(interaction.guild.id), config)
            
            embed = EmbedBuilder.success(
                "Logging Setup Complete",
                f"Server logs will now be sent to {log_channel.mention}\n\n"
                f"**Logged Events:**\n"
                f"• Message deletions and edits\n"
                f"• Channel creation, deletion, and updates\n"
                f"• Role creation, deletion, and assignments\n"
                f"• Command usage\n"
                f"• Member role updates"
            )
            
            await interaction.response.send_message(embed=embed)
            
            # Send test log
            test_embed = discord.Embed(
                title="🔧 Logging System Activated",
                description="Server logging has been successfully configured!",
                color=0x57F287
            )
            test_embed.add_field(name="Setup by", value=interaction.user.mention, inline=True)
            test_embed.add_field(name="Channel", value=log_channel.mention, inline=True)
            
            await log_channel.send(embed=test_embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to setup logging: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Log message deletions"""
        await self.bot.logging_manager.log_message_delete(message)
    
    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        """Log message edits"""
        await self.bot.logging_manager.log_message_edit(before, after)
    
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """Log channel creation"""
        await self.bot.logging_manager.log_channel_create(channel)
    
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Log channel deletion"""
        await self.bot.logging_manager.log_channel_delete(channel)
    
    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        """Log channel updates"""
        await self.bot.logging_manager.log_channel_update(before, after)
    
    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        """Log role creation"""
        await self.bot.logging_manager.log_role_create(role)
    
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        """Log role deletion"""
        await self.bot.logging_manager.log_role_delete(role)
    
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Log member role updates"""
        await self.bot.logging_manager.log_member_role_update(before, after)
    
    @commands.Cog.listener()
    async def on_interaction(self, interaction):
        """Log command usage"""
        if interaction.type == discord.InteractionType.application_command:
            await self.bot.logging_manager.log_command_use(interaction)
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Check for workflow triggers"""
        await self.bot.workflow_manager.check_message_triggers(message)
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Check for member join workflow triggers"""
        await self.bot.workflow_manager.check_member_join_triggers(member)
    
    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        """Check for thread create workflow triggers"""
        await self.bot.workflow_manager.check_thread_create_triggers(thread)

async def setup(bot):
    cog = Logging(bot)
    await bot.add_cog(cog)
    
    # Ensure commands are added to the tree
    for command in cog.__cog_app_commands__:
        if command not in bot.tree.get_commands():
            bot.tree.add_command(command)
    
    print(f"📊 Successfully loaded Logging cog with {len(cog.get_app_commands())} commands")
