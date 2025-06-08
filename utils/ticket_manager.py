import discord
from discord.ext import commands
import json
from datetime import datetime
from typing import Optional, Dict, Any
import asyncio

class TicketManager:
    def __init__(self, bot):
        self.bot = bot
        self.ticket_configs = {}  # guild_id -> config
    
    async def load_ticket_configs(self):
        """Load ticket configurations from database"""
        try:
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT guild_id, data_content FROM user_data WHERE data_type = 'ticket_config'"
                )
                for row in rows:
                    guild_id = row['guild_id']
                    config = row['data_content']
                    self.ticket_configs[guild_id] = config
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT guild_id, data_content FROM user_data WHERE data_type = 'ticket_config'"
                )
                rows = await cursor.fetchall()
                for row in rows:
                    guild_id = row[1]
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
            
            # Create channel with specific permissions
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)
            }
            
            channel_name = f"ticket-{ticket_id.split('-')[1].lower()}"
            channel = await category.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                topic=f"Support ticket: {title} | Created by {user.display_name}"
            )
            
            return channel
        except Exception as e:
            print(f"Error creating ticket channel: {e}")
            return None
    
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
            
            await transcript_channel.send(embed=embed, file=transcript_file)
            return True
        except Exception as e:
            print(f"Error sending transcript: {e}")
            return False
