import discord
from datetime import datetime, timedelta
from typing import Optional, List
import re
import asyncio
import os

class EmbedBuilder:
    @staticmethod
    def success(title: str, description: str = None) -> discord.Embed:
        embed = discord.Embed(
            title=f"✅ {title}",
            description=description,
            color=0x57F287
        )
        embed.timestamp = datetime.utcnow()
        embed.set_footer(text="Discord Bot")
        return embed
    
    @staticmethod
    def error(title: str, description: str = None) -> discord.Embed:
        embed = discord.Embed(
            title=f"❌ {title}",
            description=description,
            color=0xED4245
        )
        embed.timestamp = datetime.utcnow()
        embed.set_footer(text="Discord Bot")
        return embed
    
    @staticmethod
    def info(title: str, description: str = None) -> discord.Embed:
        embed = discord.Embed(
            title=f"ℹ️ {title}",
            description=description,
            color=0x5865F2
        )
        embed.timestamp = datetime.utcnow()
        embed.set_footer(text="Discord Bot")
        return embed
    
    @staticmethod
    def warning(title: str, description: str = None) -> discord.Embed:
        embed = discord.Embed(
            title=f"⚠️ {title}",
            description=description,
            color=0xFEE75C
        )
        embed.timestamp = datetime.utcnow()
        embed.set_footer(text="Discord Bot")
        return embed
    
class TimeParser:
    @staticmethod
    def parse_duration(duration_str: str) -> Optional[timedelta]:
        """Parse duration string like '1h', '30m', '2d' into timedelta"""
        pattern = r'(\d+)([smhd])'
        matches = re.findall(pattern, duration_str.lower())
        
        if not matches:
            return None
        
        total_seconds = 0
        for amount, unit in matches:
            amount = int(amount)
            if unit == 's':
                total_seconds += amount
            elif unit == 'm':
                total_seconds += amount * 60
            elif unit == 'h':
                total_seconds += amount * 3600
            elif unit == 'd':
                total_seconds += amount * 86400
        
        return timedelta(seconds=total_seconds)

class RailwayUtils:
    @staticmethod
    def get_deployment_info() -> dict:
        """Get Railway deployment information"""
        return {
            "environment": os.getenv('RAILWAY_ENVIRONMENT', 'unknown'),
            "service_id": os.getenv('RAILWAY_SERVICE_ID', 'unknown'),
            "deployment_id": os.getenv('RAILWAY_DEPLOYMENT_ID', 'unknown'),
            "project_id": os.getenv('RAILWAY_PROJECT_ID', 'unknown'),
            "region": os.getenv('RAILWAY_REGION', 'unknown'),
            "replica_id": os.getenv('RAILWAY_REPLICA_ID', 'unknown')
        }
    
    @staticmethod
    def is_production() -> bool:
        """Check if running in Railway production"""
        return os.getenv('RAILWAY_ENVIRONMENT') == 'production'

class Pagination:
    def __init__(self, entries: List, per_page: int = 10):
        self.entries = entries
        self.per_page = per_page
        self.pages = [entries[i:i + per_page] for i in range(0, len(entries), per_page)]
        self.current_page = 0
    
    def get_page(self, page_num: int = None) -> List:
        if page_num is not None:
            self.current_page = max(0, min(page_num, len(self.pages) - 1))
        return self.pages[self.current_page] if self.pages else []
    
    def next_page(self) -> List:
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
        return self.get_page()
    
    def prev_page(self) -> List:
        if self.current_page > 0:
            self.current_page -= 1
        return self.get_page()
    
    @property
    def page_info(self) -> str:
        if not self.pages:
            return "No entries"
        return f"Page {self.current_page + 1}/{len(self.pages)} ({len(self.entries)} total)"

async def safe_send(channel, content=None, embed=None, view=None):
    """Safely send message to channel with error handling"""
    try:
        return await channel.send(content=content, embed=embed, view=view)
    except discord.HTTPException as e:
        print(f"Failed to send message: {e}")
        return None
