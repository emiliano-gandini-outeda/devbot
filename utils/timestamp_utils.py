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

def datetime_to_timestamp(dt: datetime) -> int:
    """Convert datetime to Unix timestamp"""
    if dt is None:
        return now_timestamp()
    
    try:
        # Ensure timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        return int(dt.timestamp())
    except Exception as e:
        logger.error(f"Failed to convert datetime to timestamp: {e}")
        return now_timestamp()

def timestamp_to_datetime(timestamp: Union[int, float]) -> datetime:
    """Convert Unix timestamp to timezone-aware datetime"""
    try:
        if timestamp is None:
            timestamp = now_timestamp()
        
        return datetime.fromtimestamp(timestamp, timezone.utc)
    except Exception as e:
        logger.error(f"Failed to convert timestamp to datetime: {e}")
        return datetime.now(timezone.utc)

def format_timestamp_for_discord(timestamp: Union[int, float], style: str = "R") -> str:
    """Format timestamp for Discord display"""
    try:
        if timestamp is None:
            timestamp = now_timestamp()
        
        return f"<t:{int(timestamp)}:{style}>"
    except Exception as e:
        logger.error(f"Failed to format timestamp for Discord: {e}")
        return f"<t:{now_timestamp()}:{style}>"

def get_relative_timestamp(timestamp: Union[int, float]) -> str:
    """Get relative timestamp for Discord (e.g., '2 hours ago')"""
    return format_timestamp_for_discord(timestamp, "R")

def format_timestamp_for_display(timestamp: Union[int, float]) -> str:
    """Format timestamp for human-readable display"""
    try:
        dt = timestamp_to_datetime(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception as e:
        logger.error(f"Failed to format timestamp for display: {e}")
        return "Unknown"

def add_seconds_to_timestamp(timestamp: Union[int, float], seconds: int) -> int:
    """Add seconds to timestamp (safe integer arithmetic)"""
    try:
        return int(timestamp) + seconds
    except Exception as e:
        logger.error(f"Failed to add seconds to timestamp: {e}")
        return now_timestamp()

def subtract_seconds_from_timestamp(timestamp: Union[int, float], seconds: int) -> int:
    """Subtract seconds from timestamp (safe integer arithmetic)"""
    try:
        return int(timestamp) - seconds
    except Exception as e:
        logger.error(f"Failed to subtract seconds from timestamp: {e}")
        return now_timestamp()

def timestamp_difference(timestamp1: Union[int, float], timestamp2: Union[int, float]) -> int:
    """Get difference between two timestamps in seconds"""
    try:
        return int(timestamp1) - int(timestamp2)
    except Exception as e:
        logger.error(f"Failed to calculate timestamp difference: {e}")
        return 0

def is_timestamp_expired(timestamp: Union[int, float], expiry_seconds: int) -> bool:
    """Check if timestamp has expired"""
    try:
        current = now_timestamp()
        return (current - int(timestamp)) > expiry_seconds
    except Exception as e:
        logger.error(f"Failed to check timestamp expiry: {e}")
        return True

def hours_ago_timestamp(hours: int) -> int:
    """Get timestamp N hours ago"""
    return now_timestamp() - (hours * 3600)

def days_ago_timestamp(days: int) -> int:
    """Get timestamp N days ago"""
    return now_timestamp() - (days * 86400)

def minutes_ago_timestamp(minutes: int) -> int:
    """Get timestamp N minutes ago"""
    return now_timestamp() - (minutes * 60)

# Backward compatibility aliases
utc_now = lambda: timestamp_to_datetime(now_timestamp())
ensure_timezone_aware = timestamp_to_datetime
format_for_discord = format_timestamp_for_discord
now_for_db = now_timestamp
format_for_database = datetime_to_timestamp

# Export all functions
__all__ = [
    'now_timestamp',
    'datetime_to_timestamp', 
    'timestamp_to_datetime',
    'format_timestamp_for_discord',
    'get_relative_timestamp',
    'hours_ago_timestamp',
    'days_ago_timestamp',
    'minutes_ago_timestamp',
    'format_timestamp_for_display',
    'add_seconds_to_timestamp',
    'subtract_seconds_from_timestamp',
    'timestamp_difference',
    'is_timestamp_expired',
    'utc_now',
    'ensure_timezone_aware',
    'format_for_discord',
    'now_for_db',
    'format_for_database'
]
