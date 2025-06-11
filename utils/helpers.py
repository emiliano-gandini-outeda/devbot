import discord
from datetime import datetime, timedelta
import re
from typing import Optional, Union
import asyncio

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
    import random
    import string
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def generate_meeting_id() -> str:
    """Generate a unique meeting ID"""
    import random
    import string
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# Additional functions needed for tickets.py
class FieldNotFound(Exception):
    """Exception raised when a required field is not found"""
    pass

def has_permissions(**perms):
    """Decorator to check if user has required permissions"""
    def decorator(func):
        async def wrapper(self, ctx, *args, **kwargs):
            if not any(getattr(ctx.author.guild_permissions, perm, False) for perm in perms):
                embed = EmbedBuilder.error("Permission Denied", "You don't have permission to use this command.")
                await ctx.send(embed=embed)
                return
            return await func(self, ctx, *args, **kwargs)
        return wrapper
    return decorator

async def get_ticket_channel(bot, guild_id: int, user_id: int = None, ticket_id: str = None) -> Optional[discord.TextChannel]:
    """Get ticket channel by user ID or ticket ID"""
    try:
        guild = bot.get_guild(guild_id)
        if not guild:
            return None
        
        if ticket_id:
            # Search by ticket ID in channel topic
            for channel in guild.text_channels:
                if channel.topic and ticket_id in channel.topic:
                    return channel
        
        if user_id:
            # Search by user ID in channel topic
            for channel in guild.text_channels:
                if channel.topic and str(user_id) in channel.topic:
                    return channel
        
        return None
    except Exception:
        return None

async def get_ticket_owner(bot, channel_id: int) -> Optional[str]:
    """Get ticket owner user ID from channel"""
    try:
        channel = bot.get_channel(channel_id)
        if not channel or not channel.topic:
            return None
        
        # Extract user ID from topic
        if "User ID:" in channel.topic:
            user_id = channel.topic.split("User ID:")[1].strip().split()[0]
            return user_id
        
        return None
    except Exception:
        return None

async def get_ticket_type(bot, channel_id: int) -> Optional[str]:
    """Get ticket type from channel"""
    # This is a simplified implementation
    return "general"

def get_role(guild: discord.Guild, role_identifier: Union[str, int]) -> Optional[discord.Role]:
    """Get role by ID or name"""
    try:
        if isinstance(role_identifier, int) or role_identifier.isdigit():
            return guild.get_role(int(role_identifier))
        else:
            return discord.utils.get(guild.roles, name=role_identifier)
    except Exception:
        return None

def is_support_staff(guild: discord.Guild, user: discord.Member) -> bool:
    """Check if user is support staff"""
    # Check if user has manage_channels permission or is admin
    return user.guild_permissions.manage_channels or user.guild_permissions.administrator

async def log_to_channel(bot, guild_id: int, message: str, log_type: str = "general"):
    """Log message to configured log channel"""
    try:
        # This is a simplified implementation
        # In a real implementation, you'd get the log channel from config
        pass
    except Exception:
        pass

async def send_dm(user: discord.Member, embed: discord.Embed = None, content: str = None):
    """Send DM to user"""
    try:
        if embed:
            await user.send(embed=embed)
        elif content:
            await user.send(content)
    except discord.Forbidden:
        # User has DMs disabled
        pass
    except Exception:
        pass

def get_expiry_date(time_str: str) -> Optional[datetime]:
    """Get expiry date from time string"""
    duration = TimeParser.parse_duration(time_str)
    if duration:
        return datetime.utcnow() + duration
    return None

def parse_expiry_date(date_str: str) -> Optional[datetime]:
    """Parse expiry date string"""
    return get_expiry_date(date_str)

async def update_expiry_date(bot, item_id: str, new_date: datetime):
    """Update expiry date for an item"""
    # This is a placeholder implementation
    pass
 