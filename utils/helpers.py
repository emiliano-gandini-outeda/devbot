import discord
from datetime import datetime, timedelta
import re
from typing import Optional, Union
import random
import string
import json
from enum import Enum

class EmbedBuilder:
    """Helper class for creating consistent embeds"""
    
    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"✅ {title}",
            description=description,
            color=0x57F287
        )
        embed.set_footer(text="Railway Bot")
        return embed
    
    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"❌ {title}",
            description=description,
            color=0xED4245
        )
        embed.set_footer(text="Railway Bot")
        return embed
    
    @staticmethod
    def warning(title: str, description: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"⚠️ {title}",
            description=description,
            color=0xFEE75C
        )
        embed.set_footer(text="Railway Bot")
        return embed
    
    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"ℹ️ {title}",
            description=description,
            color=0x5865F2
        )
        embed.set_footer(text="Railway Bot")
        return embed

class TimeParser:
    """Helper class for parsing time strings"""
    
    @staticmethod
    def parse_duration(time_str: str) -> Optional[timedelta]:
        """Parse time string like '1h30m' into timedelta"""
        if not time_str:
            return None
        
        # Pattern to match time components
        pattern = r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?'
        match = re.match(pattern, time_str.lower())
        
        if not match:
            return None
        
        days, hours, minutes, seconds = match.groups()
        
        total_seconds = 0
        if days:
            total_seconds += int(days) * 86400
        if hours:
            total_seconds += int(hours) * 3600
        if minutes:
            total_seconds += int(minutes) * 60
        if seconds:
            total_seconds += int(seconds)
        
        if total_seconds == 0:
            return None
        
        return timedelta(seconds=total_seconds)
    
    @staticmethod
    def format_timedelta(td: timedelta) -> str:
        """Format timedelta to human readable string"""
        total_seconds = int(td.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        
        return " ".join(parts) if parts else "< 1m"

# Ticket system constants
class TicketStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    PENDING = "pending"

class TicketPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

def format_user_mention(user_id: Union[str, int]) -> str:
    """Format a user ID as a Discord mention"""
    return f"<@{user_id}>"

def format_channel_mention(channel_id: Union[str, int]) -> str:
    """Format a channel ID as a Discord mention"""
    return f"<#{channel_id}>"

def format_role_mention(role_id: Union[str, int]) -> str:
    """Format a role ID as a Discord mention"""
    return f"<@&{role_id}>"

def truncate_string(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate a string to a maximum length"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix

def is_valid_discord_id(discord_id: Union[str, int]) -> bool:
    """Check if a Discord ID is valid (17-19 digits)"""
    try:
        id_str = str(discord_id)
        return len(id_str) >= 17 and len(id_str) <= 19 and id_str.isdigit()
    except:
        return False

def generate_ticket_id() -> str:
    """Generate a unique ticket ID"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def generate_meeting_id() -> str:
    """Generate a unique meeting ID"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# Ticket system helper functions
async def get_ticket_channel(bot, guild_id: int, user_id: int = None, ticket_id: str = None) -> Optional[discord.TextChannel]:
    """Get a ticket channel by user ID or ticket ID"""
    try:
        if ticket_id:
            # Find by ticket ID
            ticket = await bot.db.connection.fetchrow(
                "SELECT channel_id FROM tickets WHERE ticket_id = $1 AND guild_id = $2",
                ticket_id, str(guild_id)
            )
            if ticket and ticket['channel_id']:
                guild = bot.get_guild(guild_id)
                if guild:
                    return guild.get_channel(int(ticket['channel_id']))
        elif user_id:
            # Find by user ID (open tickets only)
            ticket = await bot.db.connection.fetchrow(
                "SELECT channel_id FROM tickets WHERE user_id = $1 AND guild_id = $2 AND status = 'open'",
                str(user_id), str(guild_id)
            )
            if ticket and ticket['channel_id']:
                guild = bot.get_guild(guild_id)
                if guild:
                    return guild.get_channel(int(ticket['channel_id']))
    except Exception as e:
        print(f"Error getting ticket channel: {e}")
    return None

async def get_ticket_owner(bot, channel_id: int) -> Optional[str]:
    """Get the owner (creator) of a ticket by channel ID"""
    try:
        ticket = await bot.db.connection.fetchrow(
            "SELECT user_id FROM tickets WHERE channel_id = $1",
            str(channel_id)
        )
        return ticket['user_id'] if ticket else None
    except Exception as e:
        print(f"Error getting ticket owner: {e}")
        return None

def is_support_staff(guild: discord.Guild, user: discord.Member) -> bool:
    """Check if a user is support staff (has manage_channels permission)"""
    return user.guild_permissions.manage_channels or user.guild_permissions.administrator

def has_permissions(**perms):
    """Decorator to check if user has required permissions"""
    def decorator(func):
        async def wrapper(self, ctx, *args, **kwargs):
            if not any(getattr(ctx.author.guild_permissions, perm, False) for perm in perms):
                embed = EmbedBuilder.error(
                    "Permission Denied",
                    f"You need one of these permissions: {', '.join(perms)}"
                )
                await ctx.send(embed=embed)
                return
            return await func(self, ctx, *args, **kwargs)
        return wrapper
    return decorator

async def send_dm(user: discord.Member, embed: discord.Embed = None, content: str = None) -> bool:
    """Send a DM to a user, return True if successful"""
    try:
        if embed:
            await user.send(embed=embed)
        elif content:
            await user.send(content)
        return True
    except discord.Forbidden:
        return False
    except Exception as e:
        print(f"Error sending DM: {e}")
        return False

async def log_to_channel(bot, guild_id: int, message: str, log_type: str = "general") -> bool:
    """Log a message to the configured log channel"""
    try:
        # Get log channel from config
        config_row = await bot.db.connection.fetchrow(
            "SELECT data_content FROM user_data WHERE user_id = $1 AND data_type = $2",
            str(guild_id), 'log_config'
        )
        
        if not config_row:
            return False
        
        config = json.loads(config_row['data_content'])
        log_channel_id = config.get('log_channel_id')
        
        if not log_channel_id:
            return False
        
        guild = bot.get_guild(guild_id)
        if not guild:
            return False
        
        log_channel = guild.get_channel(int(log_channel_id))
        if not log_channel:
            return False
        
        embed = EmbedBuilder.info(f"{log_type.title()} Log", message)
        await log_channel.send(embed=embed)
        return True
        
    except Exception as e:
        print(f"Error logging to channel: {e}")
        return False

# Exception classes
class FieldNotFound(Exception):
    """Raised when a required field is not found"""
    pass

# Placeholder functions for compatibility
async def get_expiry_date(*args, **kwargs):
    """Placeholder function"""
    return None

async def parse_expiry_date(*args, **kwargs):
    """Placeholder function"""
    return None

async def update_expiry_date(*args, **kwargs):
    """Placeholder function"""
    return None

def get_role(*args, **kwargs):
    """Placeholder function"""
    return None

def get_ticket_type(*args, **kwargs):
    """Placeholder function"""
    return None
