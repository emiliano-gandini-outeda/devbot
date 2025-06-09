import discord
from datetime import datetime, timedelta
import re
from typing import Optional

class EmbedBuilder:
    """Helper class for creating consistent embeds"""
    
    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        embed = discord.Embed(title=f"✅ {title}", description=description, color=0x57F287)
        embed.set_footer(text="devBot")
        return embed
    
    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        embed = discord.Embed(title=f"❌ {title}", description=description, color=0xED4245)
        embed.set_footer(text="devBot")
        return embed
    
    @staticmethod
    def warning(title: str, description: str) -> discord.Embed:
        embed = discord.Embed(title=f"⚠️ {title}", description=description, color=0xFEE75C)
        embed.set_footer(text="devBot")
        return embed
    
    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        embed = discord.Embed(title=f"ℹ️ {title}", description=description, color=0x5865F2)
        embed.set_footer(text="devBot")
        return embed

class TimeParser:
    """Helper class for parsing time durations"""
    
    @staticmethod
    def parse_duration(time_str: str) -> Optional[timedelta]:
        """Parse duration string like '1h30m', '2d', '45s' into timedelta"""
        if not time_str:
            return None
        
        # Remove spaces and convert to lowercase
        time_str = time_str.replace(' ', '').lower()
        
        # Pattern to match time components
        pattern = r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?'
        match = re.match(pattern, time_str)
        
        if not match:
            return None
        
        days, hours, minutes, seconds = match.groups()
        
        # Convert to integers, defaulting to 0
        days = int(days) if days else 0
        hours = int(hours) if hours else 0
        minutes = int(minutes) if minutes else 0
        seconds = int(seconds) if seconds else 0
        
        # Check if at least one component was provided
        if days == 0 and hours == 0 and minutes == 0 and seconds == 0:
            return None
        
        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    
    @staticmethod
    def format_timedelta(td: timedelta) -> str:
        """Format timedelta to human readable string"""
        total_seconds = int(td.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if seconds > 0:
            parts.append(f"{seconds}s")
        
        return " ".join(parts) if parts else "0s"
