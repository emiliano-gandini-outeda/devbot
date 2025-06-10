import discord
from discord.ext import commands
import uuid
import json
import asyncio
import io
from datetime import datetime
from typing import Optional, Dict, Any

class TicketManager:
    """Centralized ticket management system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.ticket_configs = {}  # Cache for ticket configurations
    
    def generate_ticket_id(self) -> str:
        """Generate a unique ticket ID"""
        return f"TKT-{uuid.uuid4().hex[:8].upper()}"
    
    async def get_ticket_config(self, guild_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket configuration for a guild"""
        try:
            print(f"🔍 Getting ticket config for guild {guild_id}")
            
            # Check cache first
            if guild_id in self.ticket_configs:
                print(f"✅ Found cached config for guild {guild_id}")
                return self.ticket_configs[guild_id]
            
            # Try to get from database
            config = None
            
            # Method 1: Check user_data table
            try:
                if self.bot.db.is_postgresql:
                    row = await self.bot.db.connection.fetchrow(
                        "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
                        guild_id, 'ticket_config'
                    )
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT data_content FROM user_data WHERE user_id = ? AND data_type = ?",
                        (guild_id, 'ticket_config')
                    )
                    row = await cursor.fetchone()
                
                if row:
                    data_content = row['data_content'] if self.bot.db.is_postgresql else row[0]
                    if isinstance(data_content, str):
                        config = json.loads(data_content)
                    else:
                        config = data_content
                    print(f"✅ Found config in user_data table: {config}")
            except Exception as e:
                print(f"⚠️ Error checking user_data table: {e}")
            
            # Method 2: Check ticket_configs table (if exists)
            if not config:
                try:
                    if self.bot.db.is_postgresql:
                        row = await self.bot.db.connection.fetchrow(
                            "SELECT * FROM ticket_configs WHERE guild_id = $1", guild_id
                        )
                        if row:
                            config = {
                                'category_id': row['category_id'],
                                'support_role_id': row['support_role_id'],
                                'log_channel_id': row['log_channel_id'],
                                'transcript_channel_id': row['log_channel_id'],  # Use log_channel as transcript
                                'auto_close_hours': row['auto_close_hours'],
                                'max_tickets_per_user': row['max_tickets_per_user']
                            }
                            print(f"✅ Found config in ticket_configs table: {config}")
                    else:
                        cursor = await self.bot.db.connection.execute(
                            "SELECT * FROM ticket_configs WHERE guild_id = ?", (guild_id,)
                        )
                        row = await cursor.fetchone()
                        if row:
                            config = {
                                'category_id': row[2],
                                'support_role_id': row[3],
                                'log_channel_id': row[4],
                                'transcript_channel_id': row[4],  # Use log_channel as transcript
                                'auto_close_hours': row[5],
                                'max_tickets_per_user': row[6]
                            }
                            print(f"✅ Found config in ticket_configs table: {config}")
                except Exception as e:
                    print(f"⚠️ Error checking ticket_configs table (table may not exist): {e}")
            
            # Cache the config if found
            if config:
                self.ticket_configs[guild_id] = config
                print(f"💾 Cached config for guild {guild_id}")
            else:
                print(f"❌ No ticket config found for guild {guild_id}")
            
            return config
            
        except Exception as e:
            print(f"❌ Error getting ticket config: {e}")
            return None
    
    async def save_ticket_config(self, guild_id: str, config: Dict[str, Any]):
        """Save ticket configuration to database"""
        try:
            print(f"💾 Saving ticket config for guild {guild_id}: {config}")
            
            # Save to user_data table
            config_json = json.dumps(config)
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO user_data (user_id, data_type, data_content, created_at)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (user_id, data_type) DO UPDATE SET
                       data_content = $3, created_at = $4""",
                    guild_id, 'ticket_config', config_json, datetime.utcnow()
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO user_data (user_id, data_type, data_content, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (guild_id, 'ticket_config', config_json, datetime.utcnow())
                )
                await self.bot.db.connection.commit()
            
            # Update cache
            self.ticket_configs[guild_id] = config
            print(f"✅ Saved and cached ticket config for guild {guild_id}")
            
        except Exception as e:
            print(f"❌ Error saving ticket config: {e}")
            raise
    
    async def create_ticket_channel(self, guild: discord.Guild, ticket_id: str, user: discord.Member, title: str) -> Optional[discord.TextChannel]:
        """Create a ticket channel with proper permissions"""
        try:
            print(f"🎫 Creating ticket channel for {ticket_id}")
            
            # Get ticket config
            config = await self.get_ticket_config(str(guild.id))
            if not config:
                print(f"❌ No ticket config found for guild {guild.id}")
                return None
            
            category_id = config.get('category_id')
            if not category_id:
                print(f"❌ No category_id in ticket config")
                return None
            
            category = guild.get_channel(int(category_id))
            if not category:
                print(f"❌ Category channel {category_id} not found")
                return None
            
            print(f"🔧 Setting up PUBLIC READ-ONLY permissions for ticket-{ticket_id.lower()}")
            
            # Set up permissions - PUBLIC READ-ONLY by default
            overwrites = {
                # Everyone can read but not write (PUBLIC READ-ONLY)
                guild.default_role: discord.PermissionOverwrite(
                    read_messages=True,      # ✅ Can see the ticket
                    send_messages=False,     # ❌ Cannot write messages
                    add_reactions=False,     # ❌ Cannot add reactions
                    attach_files=False       # ❌ Cannot attach files
                ),
                # Ticket creator can read and write
                user: discord.PermissionOverwrite(
                    read_messages=True,      # ✅ Can see the ticket
                    send_messages=True,      # ✅ Can write messages
                    add_reactions=True,      # ✅ Can add reactions
                    attach_files=True        # ✅ Can attach files
                ),
                # Bot can manage everything
                guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_messages=True,
                    add_reactions=True,
                    attach_files=True
                )
            }
            
            # Add admin roles with write permissions
            if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager:
                admin_role_ids = self.bot.admin_manager.get_admin_roles(str(guild.id))
                for role_id in admin_role_ids:
                    role = guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(
                            read_messages=True,
                            send_messages=True,
                            add_reactions=True,
                            attach_files=True
                        )
                        print(f"✅ Added admin role {role.name} with write permissions")
            
            # Create the channel
            channel = await guild.create_text_channel(
                name=f"ticket-{ticket_id.lower()}",
                category=category,
                topic=f"Support ticket: {ticket_id} | Created by {user.display_name} | 🌐 Public & Read-Only",
                overwrites=overwrites
            )
            
            print(f"✅ Created PUBLIC READ-ONLY ticket channel: {channel.name}")
            return channel
            
        except Exception as e:
            print(f"❌ Error creating ticket channel: {e}")
            return None
    
    async def set_ticket_visibility(self, channel: discord.TextChannel, private: bool = True) -> bool:
        """Set ticket visibility (private or public)"""
        try:
            guild = channel.guild
            
            print(f"🔧 Setting ticket {channel.name} to {'PRIVATE' if private else 'PUBLIC READ-ONLY'}")
            
            if private:
                # Private: Only assignees and admins can read
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        read_messages=False, 
                        send_messages=False
                    )
                }
            else:
                # Public: Everyone can read, only assignees can write
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        read_messages=True,      # ✅ Can read
                        send_messages=False,     # ❌ Cannot write
                        add_reactions=False,     # ❌ Cannot react
                        attach_files=False       # ❌ Cannot attach files
                    )
                }
            
            # Always allow bot to manage
            overwrites[guild.me] = discord.PermissionOverwrite(
                read_messages=True, 
                send_messages=True, 
                manage_channels=True,
                manage_messages=True,
                add_reactions=True,
                attach_files=True
            )
            
            # Get ticket info to preserve creator and assignee permissions
            if channel.topic and "Support ticket:" in channel.topic:
                ticket_id = channel.topic.split("|")[0].replace("Support ticket:", "").strip()
                
                if self.bot.db.is_postgresql:
                    ticket = await self.bot.db.connection.fetchrow(
                        "SELECT user_id, assignee_id FROM tickets WHERE ticket_id = $1", ticket_id
                    )
                else:
                    cursor = await self.bot.db.connection.execute(
                        "SELECT user_id, assignee_id FROM tickets WHERE ticket_id = ?", (ticket_id,)
                    )
                    ticket = await cursor.fetchone()
                
                if ticket:
                    # Creator permissions
                    user_id = ticket['user_id'] if self.bot.db.is_postgresql else ticket[0]
                    creator = guild.get_member(int(user_id))
                    if creator:
                        overwrites[creator] = discord.PermissionOverwrite(
                            read_messages=True, 
                            send_messages=True,
                            add_reactions=True,
                            attach_files=True
                        )
                    
                    # Assignee permissions
                    assignee_id = ticket['assignee_id'] if self.bot.db.is_postgresql else ticket[1]
                    if assignee_id:
                        assignee = guild.get_member(int(assignee_id))
                        if assignee:
                            overwrites[assignee] = discord.PermissionOverwrite(
                                read_messages=True, 
                                send_messages=True,
                                add_reactions=True,
                                attach_files=True
                            )
            
            # Admin role permissions
            if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager:
                admin_role_ids = self.bot.admin_manager.get_admin_roles(str(guild.id))
                for role_id in admin_role_ids:
                    role = guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(
                            read_messages=True, 
                            send_messages=True,
                            add_reactions=True,
                            attach_files=True
                        )
            
            await channel.edit(overwrites=overwrites)
            
            # Update channel topic
            if channel.topic:
                if private:
                    new_topic = channel.topic.replace("🌐 Public & Read-Only", "🔒 Private")
                else:
                    new_topic = channel.topic.replace("🔒 Private", "🌐 Public & Read-Only")
                await channel.edit(topic=new_topic)
            
            print(f"✅ Updated ticket visibility successfully")
            return True
            
        except Exception as e:
            print(f"❌ Error setting ticket visibility: {e}")
            return False
    
    async def create_transcript(self, channel: discord.TextChannel) -> str:
        """Create a transcript of the ticket channel"""
        try:
            print(f"📝 Creating transcript for {channel.name}")
            
            messages = []
            message_count = 0
            
            async for message in channel.history(limit=None, oldest_first=True):
                timestamp = message.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
                content = message.content or "[No text content]"
                
                # Handle embeds
                if message.embeds:
                    for embed in message.embeds:
                        if embed.title:
                            content += f"\n[EMBED] Title: {embed.title}"
                        if embed.description:
                            content += f"\n[EMBED] Description: {embed.description}"
                
                # Handle attachments
                if message.attachments:
                    attachments = "\n".join([f"[ATTACHMENT] {att.filename} ({att.url})" for att in message.attachments])
                    content += f"\n{attachments}"
                
                # Handle reactions
                if message.reactions:
                    reactions = ", ".join([f"{reaction.emoji}({reaction.count})" for reaction in message.reactions])
                    content += f"\n[REACTIONS] {reactions}"
                
                messages.append(f"[{timestamp}] {message.author.display_name} ({message.author.id}): {content}")
                message_count += 1
            
            transcript_header = f"""=== TICKET TRANSCRIPT ===
Channel: {channel.name}
Guild: {channel.guild.name}
Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
Total Messages: {message_count}
========================

"""
            
            print(f"✅ Created transcript with {message_count} messages")
            return transcript_header + "\n".join(messages)
            
        except Exception as e:
            print(f"❌ Error creating transcript: {e}")
            return f"Error creating transcript: {str(e)}"
    
    async def send_transcript(self, guild: discord.Guild, ticket_id: str, transcript: str, ticket_info: Dict) -> bool:
        """Send transcript to configured channel"""
        try:
            print(f"📤 Sending transcript for ticket {ticket_id}")
            
            # Get ticket config
            config = await self.get_ticket_config(str(guild.id))
            if not config:
                print(f"❌ No ticket config found")
                return False
            
            # Get transcript channel ID (try transcript_channel_id first, then log_channel_id)
            transcript_channel_id = config.get('transcript_channel_id') or config.get('log_channel_id')
            if not transcript_channel_id:
                print(f"❌ No transcript channel configured")
                return False
            
            transcript_channel = guild.get_channel(int(transcript_channel_id))
            if not transcript_channel:
                print(f"❌ Transcript channel {transcript_channel_id} not found")
                return False
            
            # Create transcript file
            transcript_file = discord.File(
                fp=io.StringIO(transcript),
                filename=f"transcript_{ticket_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
            )
            
            # Create embed
            embed = discord.Embed(
                title=f"🎫 Ticket Transcript: {ticket_id}",
                description=f"**Title:** {ticket_info.get('title', 'Unknown')}\n**Guild:** {guild.name}",
                color=0x5865F2,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="📊 Stats", value=f"Lines: {len(transcript.split(chr(10)))}", inline=True)
            embed.add_field(name="📅 Closed", value=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), inline=True)
            embed.set_footer(text="devBot - Powered by EGOS")
            
            await transcript_channel.send(embed=embed, file=transcript_file)
            print(f"✅ Transcript sent successfully")
            return True
            
        except Exception as e:
            print(f"❌ Error sending transcript: {e}")
            return False
    
    async def close_ticket(self, ticket_id: str, channel: discord.TextChannel, closer: discord.Member) -> bool:
        """Close a ticket and create transcript"""
        try:
            print(f"🔒 Closing ticket {ticket_id}")
            
            # Create transcript
            transcript = await self.create_transcript(channel)
            
            # Get ticket info
            ticket_info = await self.get_ticket_info(ticket_id)
            if not ticket_info:
                print(f"❌ Ticket {ticket_id} not found in database")
                return False
            
            # Send transcript
            transcript_sent = await self.send_transcript(channel.guild, ticket_id, transcript, ticket_info)
            
            # Update ticket status
            await self.update_ticket_status(ticket_id, "closed")
            
            print(f"✅ Ticket {ticket_id} closed successfully")
            return transcript_sent
            
        except Exception as e:
            print(f"❌ Error closing ticket: {e}")
            return False
    
    async def get_ticket_info(self, ticket_id: str) -> Optional[Dict]:
        """Get ticket information from database"""
        try:
            print(f"🔍 Getting info for ticket {ticket_id}")
            
            if self.bot.db.is_postgresql:
                ticket = await self.bot.db.connection.fetchrow(
                    "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
                )
                result = dict(ticket) if ticket else None
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
                )
                ticket = await cursor.fetchone()
                if ticket:
                    # Convert to dict for SQLite
                    columns = ['id', 'ticket_id', 'guild_id', 'user_id', 'assignee_id', 'title', 'description', 'status', 'priority', 'channel_id', 'created_at', 'updated_at']
                    result = dict(zip(columns, ticket))
                else:
                    result = None
            
            print(f"✅ Got ticket info: {result}")
            return result
            
        except Exception as e:
            print(f"❌ Error getting ticket info: {e}")
            return None
    
    async def update_ticket_status(self, ticket_id: str, status: str):
        """Update ticket status in database"""
        try:
            print(f"🔄 Updating ticket {ticket_id} status to {status}")
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET status = $1, updated_at = $2 WHERE ticket_id = $3",
                    status, datetime.utcnow(), ticket_id
                )
            else:
                await self.bot.db.connection.execute(
                    "UPDATE tickets SET status = ?, updated_at = ? WHERE ticket_id = ?",
                    (status, datetime.utcnow(), ticket_id)
                )
                await self.bot.db.connection.commit()
            
            print(f"✅ Updated ticket status successfully")
            
        except Exception as e:
            print(f"❌ Error updating ticket status: {e}")
    
    async def assign_ticket(self, ticket_id: str, guild_id: str, assignee_id: str) -> bool:
        """Assign a ticket to a user"""
        try:
            print(f"👤 Assigning ticket {ticket_id} to user {assignee_id}")
            
            if self.bot.db.is_postgresql:
                result = await self.bot.db.connection.execute(
                    "UPDATE tickets SET assignee_id = $1, updated_at = $2 WHERE ticket_id = $3 AND guild_id = $4",
                    assignee_id, datetime.utcnow(), ticket_id, guild_id
                )
                rows_affected = 1 if result == "UPDATE 1" else 0
            else:
                result = await self.bot.db.connection.execute(
                    "UPDATE tickets SET assignee_id = ?, updated_at = ? WHERE ticket_id = ? AND guild_id = ?",
                    (assignee_id, datetime.utcnow(), ticket_id, guild_id)
                )
                await self.bot.db.connection.commit()
                rows_affected = result.rowcount
            
            print(f"✅ Ticket assignment updated, rows affected: {rows_affected}")
            return rows_affected > 0
            
        except Exception as e:
            print(f"❌ Error assigning ticket: {e}")
            return False
    
    async def get_ticket_channel(self, ticket_id: str) -> Optional[discord.TextChannel]:
        """Get ticket channel by ticket ID"""
        try:
            print(f"🔍 Getting channel for ticket {ticket_id}")
            
            if self.bot.db.is_postgresql:
                ticket = await self.bot.db.connection.fetchrow(
                    "SELECT channel_id, guild_id FROM tickets WHERE ticket_id = $1", ticket_id
                )
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT channel_id, guild_id FROM tickets WHERE ticket_id = ?", (ticket_id,)
                )
                ticket = await cursor.fetchone()
            
            if not ticket:
                print(f"❌ Ticket {ticket_id} not found in database")
                return None
            
            channel_id = ticket['channel_id'] if self.bot.db.is_postgresql else ticket[0]
            guild_id = ticket['guild_id'] if self.bot.db.is_postgresql else ticket[1]
            
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                print(f"❌ Guild {guild_id} not found")
                return None
            
            channel = guild.get_channel(int(channel_id))
            print(f"✅ Found channel: {channel.name if channel else None}")
            return channel
            
        except Exception as e:
            print(f"❌ Error getting ticket channel: {e}")
            return None
    
    async def update_assignee_permissions(self, ticket_id: str, assignee: discord.Member, grant: bool):
        """Update assignee permissions on ticket channel"""
        try:
            print(f"🔧 {'Granting' if grant else 'Removing'} write permissions for {assignee.display_name} on ticket {ticket_id}")
            
            channel = await self.get_ticket_channel(ticket_id)
            if channel:
                if grant:
                    await channel.set_permissions(assignee, read_messages=True, send_messages=True, add_reactions=True, attach_files=True)
                else:
                    await channel.set_permissions(assignee, read_messages=True, send_messages=False)
                print(f"✅ Updated permissions successfully")
            else:
                print(f"❌ Channel not found for ticket {ticket_id}")
                
        except Exception as e:
            print(f"❌ Error updating assignee permissions: {e}")
