import discord
from datetime import datetime, timedelta
import re
from typing import Optional, Union

class EmbedBuilder:
    """Helper class for creating consistent embeds"""
    
    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        """Create a success embed"""
        embed = discord.Embed(
            title=f"✅ {title}",
            description=description,
            color=0x57F287,
            timestamp=datetime.utcnow()
        )
        return embed
    
    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        """Create an error embed"""
        embed = discord.Embed(
            title=f"❌ {title}",
            description=description,
            color=0xED4245,
            timestamp=datetime.utcnow()
        )
        return embed
    
    @staticmethod
    def warning(title: str, description: str) -> discord.Embed:
        """Create a warning embed"""
        embed = discord.Embed(
            title=f"⚠️ {title}",
            description=description,
            color=0xFEE75C,
            timestamp=datetime.utcnow()
        )
        return embed
    
    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        """Create an info embed"""
        embed = discord.Embed(
            title=f"ℹ️ {title}",
            description=description,
            color=0x5865F2,
            timestamp=datetime.utcnow()
        )
        return embed

class TimeParser:
    """Helper class for parsing time strings"""
    
    @staticmethod
    def parse_duration(time_str: str) -> Optional[timedelta]:
        """Parse a time string like '1h30m' into a timedelta"""
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
        
        # Check if any time was specified
        if days == 0 and hours == 0 and minutes == 0 and seconds == 0:
            return None
        
        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    
    @staticmethod
    def format_timedelta(td: timedelta) -> str:
        """Format a timedelta into a human-readable string"""
        total_seconds = int(td.total_seconds())
        
        if total_seconds <= 0:
            return "now"
        
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
        if seconds > 0 and days == 0:  # Only show seconds if less than a day
            parts.append(f"{seconds}s")
        
        return " ".join(parts) if parts else "now"
    
    @staticmethod
    def parse_time_input(time_input: str) -> Optional[datetime]:
        """Parse various time input formats"""
        try:
            # Try parsing as duration first
            duration = TimeParser.parse_duration(time_input)
            if duration:
                return datetime.utcnow() + duration
            
            # Try parsing as absolute time (basic formats)
            time_formats = [
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d %H:%M:%S",
                "%m/%d/%Y %H:%M",
                "%m/%d/%Y %I:%M %p",
                "%H:%M",
                "%I:%M %p"
            ]
            
            for fmt in time_formats:
                try:
                    parsed_time = datetime.strptime(time_input, fmt)
                    
                    # If only time was provided, assume today
                    if fmt in ["%H:%M", "%I:%M %p"]:
                        now = datetime.utcnow()
                        parsed_time = parsed_time.replace(
                            year=now.year,
                            month=now.month,
                            day=now.day
                        )
                        
                        # If the time has already passed today, assume tomorrow
                        if parsed_time <= now:
                            parsed_time += timedelta(days=1)
                    
                    return parsed_time
                except ValueError:
                    continue
            
            return None
        except Exception:
            return None

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
