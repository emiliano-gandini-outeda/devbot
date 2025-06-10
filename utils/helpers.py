import discord
from datetime import datetime, timedelta
import re
from typing import Optional, Union

class EmbedBuilder:
    """Helper class for creating consistent embeds"""
    
    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"✅ {title}",
            description=description,
            color=0x57F287
        )
        embed.set_footer(text="devBot - Powered by EGOS")
        return embed
    
    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"❌ {title}",
            description=description,
            color=0xED4245
        )
        embed.set_footer(text="devBot - Powered by EGOS")
        return embed
    
    @staticmethod
    def warning(title: str, description: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"⚠️ {title}",
            description=description,
            color=0xFEE75C
        )
        embed.set_footer(text="devBot - Powered by EGOS")
        return embed
    
    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"ℹ️ {title}",
            description=description,
            color=0x5865F2
        )
        embed.set_footer(text="devBot - Powered by EGOS")
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
