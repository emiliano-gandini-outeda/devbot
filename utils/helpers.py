import discord
import uuid
from datetime import datetime, timezone
from typing import Optional

class EmbedBuilder:
    """Helper class for creating consistent embeds"""
    
    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        """Create a success embed"""
        embed = discord.Embed(
            title=f"✅ {title}",
            description=description,
            color=0x57F287  # Green
        )
        embed.set_footer(text="devBot - Powered by EGOS")
        return embed
    
    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        """Create an error embed"""
        embed = discord.Embed(
            title=f"❌ {title}",
            description=description,
            color=0xED4245  # Red
        )
        embed.set_footer(text="devBot - Powered by EGOS")
        return embed
    
    @staticmethod
    def warning(title: str, description: str) -> discord.Embed:
        """Create a warning embed"""
        embed = discord.Embed(
            title=f"⚠️ {title}",
            description=description,
            color=0xFEE75C  # Yellow
        )
        embed.set_footer(text="devBot - Powered by EGOS")
        return embed
    
    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        """Create an info embed"""
        embed = discord.Embed(
            title=f"ℹ️ {title}",
            description=description,
            color=0x5865F2  # Blurple
        )
        embed.set_footer(text="devBot - Powered by EGOS")
        return embed

def generate_ticket_id() -> str:
    """Generate a unique ticket ID"""
    return f"TKT-{uuid.uuid4().hex[:8].upper()}"

def current_timestamp() -> int:
    """Get current Unix timestamp"""
    return int(datetime.now(timezone.utc).timestamp())

def format_timestamp(timestamp: int, style: str = "f") -> str:
    """Format Unix timestamp for Discord"""
    return f"<t:{timestamp}:{style}>"

def get_relative_time(timestamp: int) -> str:
    """Get relative time string for Discord"""
    return f"<t:{timestamp}:R>"
 