"""
NUCLEAR DATETIME SOLUTION: Unix timestamps only
Zero datetime objects in database operations
"""
import time
from datetime import datetime, timezone
from typing import Union, Optional
import logging

logger = logging.getLogger(__name__)

def now_timestamp() -> int:
    """Get current Unix timestamp (integer)"""
    return int(time.time())

def datetime_to_timestamp(dt: Union[datetime, str, None]) -> int:
    """Convert datetime to Unix timestamp"""
    if dt is None:
        return now_timestamp()
    
    if isinstance(dt, str):
        try:
            # Parse ISO string
            if dt.endswith('Z'):
                dt = dt[:-1] + '+00:00'
            dt = datetime.fromisoformat(dt)
        except (ValueError, TypeError):
            logger.warning(f"Failed to parse datetime string: {dt}")
            return now_timestamp()
    
    if isinstance(dt, datetime):
        # Ensure timezone aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    
    return now_timestamp()

def timestamp_to_datetime(timestamp: Union[int, float, None]) -> datetime:
    """Convert Unix timestamp to timezone-aware datetime"""
    if timestamp is None:
        timestamp = now_timestamp()
    
    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        logger.warning(f"Invalid timestamp: {timestamp}")
        return datetime.now(timezone.utc)

def format_timestamp_for_discord(timestamp: Union[int, float, None], style: str = 'f') -> str:
    """Format Unix timestamp for Discord display"""
    if timestamp is None:
        timestamp = now_timestamp()
    
    try:
        return f"<t:{int(timestamp)}:{style}>"
    except (ValueError, TypeError):
        return "Unknown time"

def get_relative_timestamp(timestamp: Union[int, float, None]) -> str:
    """Get relative time for Discord"""
    return format_timestamp_for_discord(timestamp, 'R')

def hours_ago_timestamp(hours: int) -> int:
    """Get timestamp N hours ago"""
    return now_timestamp() - (hours * 3600)

def days_ago_timestamp(days: int) -> int:
    """Get timestamp N days ago"""
    return now_timestamp() - (days * 86400)

def minutes_ago_timestamp(minutes: int) -> int:
    """Get timestamp N minutes ago"""
    return now_timestamp() - (minutes * 60)

# Export all functions
__all__ = [
    'now_timestamp',
    'datetime_to_timestamp', 
    'timestamp_to_datetime',
    'format_timestamp_for_discord',
    'get_relative_timestamp',
    'hours_ago_timestamp',
    'days_ago_timestamp',
    'minutes_ago_timestamp'
]
