import discord
from discord.ext import commands
import json
from datetime import datetime
from typing import Optional, Dict, Any
import asyncio
import random
import string

class TicketJoinRequestView(discord.ui.View):
    def __init__(self, bot, requester: discord.Member, ticket_channel: discord.TextChannel):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.bot = bot
        self.requester = requester
        self.ticket_channel = ticket_channel
    
    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅")
    async def accept_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user can accept (must be assigned to ticket or admin)
        ticket_id = self.ticket_channel.topic.split("|")[0].replace("Support ticket: ", "").strip()
        
        # Get ticket info
        if self.bot.db.is_postgresql:
            ticket = await self.bot.db.connection.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
            )
            ticket = await cursor.fetchone()
        
        if not ticket:
            embed = discord.Embed(
                title="❌ Error",
                description="Ticket not found in database",
                color=0xED4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check permissions
        user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[3]
        assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[4]
        
        can_accept = (
            self.bot.admin_manager.is_admin(interaction.user) or
            str(interaction.user.id) == user_id or
            str(interaction.user.id) == assignee_id
        )
        
        # Prevent self-acceptance
        if str(interaction.user.id) == str(self.requester.id):
            embed = discord.Embed(
                title="❌ Error",
                description="You cannot accept your own join request",
                color=0xED4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        if not can_accept:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="Only ticket creator, assignee, or admins can accept join requests",
                color=0xED4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # Add user to ticket channel permissions
            await self.ticket_channel.set_permissions(
                self.requester,
                read_messages=True,
                send_messages=True
            )
            
            embed = discord.Embed(
                title="✅ Request Accepted",
                description=f"{self.requester.mention} has been added to this ticket by {interaction.user.mention}",
                color=0x57F287
            )
            
            await interaction.response.send_message(embed=embed)
            
            # Disable buttons
            for item in self.children:
                item.disabled = True
            await interaction.edit_original_response(view=self)
            
        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to add user to ticket: {str(e)}",
                color=0xED4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Same permission check as accept
        ticket_id = self.ticket_channel.topic.split("|")[0].replace("Support ticket: ", "").strip()
        
        if self.bot.db.is_postgresql:
            ticket = await self.bot.db.connection.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
            )
        else:
            cursor = await self.bot.db.connection.execute(
                "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
            )
            ticket = await cursor.fetchone()
        
        if not ticket:
            embed = discord.Embed(
                title="❌ Error",
                description="Ticket not found in database",
                color=0xED4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[3]
        assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[4]
        
        can_reject = (
            self.bot.admin_manager.is_admin(interaction.user) or
            str(interaction.user.id) == user_id or
            str(interaction.user.id) == assignee_id
        )
        
        if not can_reject:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="Only ticket creator, assignee, or admins can reject join requests",
                color=0xED4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        modal = RejectReasonModal(self.bot, self.requester, interaction.user)
        await interaction.response.send_modal(modal)
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)

class RejectReasonModal(discord.ui.Modal):
    def __init__(self, bot, requester: discord.Member, rejector: discord.Member):
        super().__init__(title="Rejection Reason")
        self.bot = bot
        self.requester = requester
        self.rejector = rejector
        
        self.reason_input = discord.ui.TextInput(
            label="Reason for rejection",
            placeholder="Please provide a reason for rejecting this request...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )
        self.add_item(self.reason_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Send DM to requester
            embed = discord.Embed(
                title="❌ Ticket Join Request Rejected",
                description=f"Your request to join the ticket in **{interaction.guild.name}** was rejected.",
                color=0xED4245
            )
            embed.add_field(name="Rejected by", value=self.rejector.display_name, inline=True)
            embed.add_field(name="Reason", value=self.reason_input.value, inline=False)
            
            try:
                await self.requester.send(embed=embed)
                response_msg = f"Request rejected and {self.requester.mention} has been notified."
            except discord.Forbidden:
                response_msg = f"Request rejected but couldn't send DM to {self.requester.mention}."
            
            embed_response = discord.Embed(
                title="❌ Request Rejected",
                description=response_msg,
                color=0xED4245
            )
            
            await interaction.response.send_message(embed=embed_response)
            
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

class TicketManager:
    def __init__(self, bot):
        self.bot = bot
        self.ticket_configs = {}  # guild_id -> config
    
    def generate_ticket_id(self) -> str:
        """Generate a 12-character random ticket ID"""
        characters = string.ascii_letters + string.digits
        return ''.join(random.choice(characters) for _ in range(12))
    
    async def load_ticket_configs(self):
        """Load ticket configurations from database"""
        try:
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT user_id, data_content FROM user_data WHERE data_type = 'ticket_config'"
                )
                for row in rows:
                    guild_id = row['user_id']  # user_id field stores guild_id for configs
                    config = row['data_content']
                    self.ticket_configs[guild_id] = config
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT user_id, data_content FROM user_data WHERE data_type = 'ticket_config'"
                )
                rows = await cursor.fetchall()
                for row in rows:
                    guild_id = row[0]  # user_id field stores guild_id for configs
                    config = json.loads(row[2])
                    self.ticket_configs[guild_id] = config
        except Exception as e:
            print(f"Error loading ticket configs: {e}")
    
    async def save_ticket_config(self, guild_id: str, config: Dict[str, Any]):
        """Save ticket configuration to database"""
        try:
            self.ticket_configs[guild_id] = config
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO user_data (user_id, data_type, data_content) 
                       VALUES ($1, $2, $3) 
                       ON CONFLICT (user_id, data_type) DO UPDATE SET data_content = $3""",
                    guild_id, 'ticket_config', json.dumps(config)
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO user_data (user_id, data_type, data_content) 
                       VALUES (?, ?, ?)""",
                    (guild_id, 'ticket_config', json.dumps(config))
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error saving ticket config: {e}")
    
    def get_ticket_config(self, guild_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket configuration for guild"""
        return self.ticket_configs.get(guild_id)
    
    async def create_ticket_channel(self, guild: discord.Guild, ticket_id: str, user: discord.Member, title: str) -> Optional[discord.TextChannel]:
        """Create a ticket channel in the configured category"""
        config = self.get_ticket_config(str(guild.id))
        if not config or 'category_id' not in config:
            return None
        
        try:
            category = guild.get_channel(int(config['category_id']))
            if not category or not isinstance(category, discord.CategoryChannel):
                return None
            
            # Create channel with specific permissions - read-only for everyone except creator and bot
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True, manage_channels=True)
            }
            
            # Add admin roles to overwrites
            admin_role_ids = self.bot.admin_manager.get_admin_roles(str(guild.id))
            for role_id in admin_role_ids:
                role = guild.get_role(int(role_id))
                if role:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            channel_name = f"ticket-{ticket_id.lower()}"
            channel = await category.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                topic=f"Support ticket: {ticket_id} | {title} | Created by {user.display_name}"
            )
            
            return channel
        except Exception as e:
            print(f"Error creating ticket channel: {e}")
            return None
    
    async def set_ticket_visibility(self, channel: discord.TextChannel, private: bool) -> bool:
        """Set ticket visibility (private = only assigned users, public = everyone can read)"""
        try:
            guild = channel.guild
            
            if private:
                # Private: Only assigned users and admins can read
                await channel.set_permissions(
                    guild.default_role,
                    read_messages=False,
                    send_messages=False
                )
            else:
                # Public: Everyone can read, but only assigned users can write
                await channel.set_permissions(
                    guild.default_role,
                    read_messages=True,
                    send_messages=False
                )
            
            return True
        except Exception as e:
            print(f"Error setting ticket visibility: {e}")
            return False
    
    async def create_transcript(self, channel: discord.TextChannel) -> str:
        """Create a text transcript of the ticket channel"""
        transcript_lines = []
        transcript_lines.append(f"Ticket Transcript: {channel.name}")
        transcript_lines.append(f"Created: {channel.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        transcript_lines.append(f"Topic: {channel.topic or 'No topic'}")
        transcript_lines.append("=" * 50)
        transcript_lines.append("")
        
        try:
            messages = []
            async for message in channel.history(limit=None, oldest_first=True):
                messages.append(message)
            
            for message in messages:
                timestamp = message.created_at.strftime('%Y-%m-%d %H:%M:%S')
                author = message.author.display_name
                content = message.content or "[No text content]"
                
                # Handle attachments
                if message.attachments:
                    for attachment in message.attachments:
                        content += f" [Attachment: {attachment.filename}]"
                
                # Handle embeds
                if message.embeds:
                    content += f" [Embed: {len(message.embeds)} embed(s)]"
                
                transcript_lines.append(f"[{timestamp}] {author}: {content}")
            
            transcript_lines.append("")
            transcript_lines.append("=" * 50)
            transcript_lines.append(f"Transcript generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
            
            return "\n".join(transcript_lines)
        except Exception as e:
            print(f"Error creating transcript: {e}")
            return f"Error creating transcript: {str(e)}"
    
    async def send_transcript(self, guild: discord.Guild, transcript_content: str, ticket_id: str, user: discord.Member):
        """Send transcript to configured transcript channel"""
        config = self.get_ticket_config(str(guild.id))
        if not config or 'transcript_channel_id' not in config:
            return False
        
        try:
            transcript_channel = guild.get_channel(int(config['transcript_channel_id']))
            if not transcript_channel:
                return False
            
            # Create file
            import io
            transcript_file = discord.File(
                io.StringIO(transcript_content),
                filename=f"transcript_{ticket_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            )
            
            embed = discord.Embed(
                title="📄 Ticket Transcript",
                description=f"Transcript for ticket {ticket_id}",
                color=0x5865F2
            )
            embed.add_field(name="User", value=user.mention, inline=True)
            embed.add_field(name="Closed", value=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), inline=True)
            embed.set_footer(text="devBot")
            
            await transcript_channel.send(embed=embed, file=transcript_file)
            return True
        except Exception as e:
            print(f"Error sending transcript: {e}")
            return False
