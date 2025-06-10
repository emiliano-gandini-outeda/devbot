"""
Bulletproof datetime utilities for Discord bot.
All datetime operations are timezone-aware (UTC) to prevent database query errors.
"""

from datetime import datetime, timezone, timedelta
import logging
from typing import Union, Optional

logger = logging.getLogger(__name__)

def utc_now() -> datetime:
    """Get current UTC time as timezone-aware datetime"""
    return datetime.now(timezone.utc)

def ensure_timezone_aware(dt: Union[datetime, str, None]) -> datetime:
    """
    Ensure datetime is timezone-aware (UTC).
    
    Args:
        dt: datetime object, string, or None
        
    Returns:
        timezone-aware datetime in UTC
    """
    if dt is None:
        return utc_now()
    
    if isinstance(dt, str):
        return parse_iso_datetime(dt)
    
    if not isinstance(dt, datetime):
        logger.warning(f"Expected datetime object, got {type(dt)}: {dt}")
        return utc_now()
    
    if dt.tzinfo is None:
        # Assume naive datetime is UTC and make it timezone-aware
        logger.debug(f"Converting naive datetime to UTC: {dt}")
        return dt.replace(tzinfo=timezone.utc)
    
    # Convert to UTC if it has a different timezone
    return dt.astimezone(timezone.utc)

def parse_iso_datetime(iso_string: Union[str, None]) -> datetime:
    """
    Parse ISO datetime string to timezone-aware datetime.
    
    Args:
        iso_string: ISO format datetime string
        
    Returns:
        timezone-aware datetime in UTC
    """
    if iso_string is None:
        return utc_now()
    
    if not isinstance(iso_string, str):
        return ensure_timezone_aware(iso_string)
    
    try:
        # Handle various ISO formats
        if iso_string.endswith('Z'):
            # Replace Z with +00:00 for proper parsing
            iso_string = iso_string[:-1] + '+00:00'
        elif iso_string.endswith('+00:00') or iso_string.endswith('-00:00'):
            # Already has timezone info
            pass
        elif 'T' in iso_string and '+' not in iso_string and '-' not in iso_string[-6:]:
            # Assume UTC if no timezone specified
            iso_string += '+00:00'
        elif ' ' in iso_string and 'T' not in iso_string:
            # Handle space-separated format
            iso_string = iso_string.replace(' ', 'T') + '+00:00'
        
        parsed_dt = datetime.fromisoformat(iso_string)
        return ensure_timezone_aware(parsed_dt)
        
    except ValueError as e:
        logger.warning(f"Failed to parse datetime string '{iso_string}': {e}")
        return utc_now()

def parse_github_datetime(iso_string: Union[str, None]) -> datetime:
    """
    Parse GitHub API datetime string to timezone-aware datetime.
    GitHub returns ISO format like "2023-12-01T10:30:00Z"
    
    Args:
        iso_string: GitHub API datetime string
        
    Returns:
        timezone-aware datetime in UTC
    """
    return parse_iso_datetime(iso_string)

def format_for_database(dt: Union[datetime, str, None]) -> datetime:
    """
    Format datetime for database insertion.
    
    Args:
        dt: datetime object, string, or None
        
    Returns:
        timezone-aware datetime in UTC ready for database
    """
    result = ensure_timezone_aware(dt)
    logger.debug(f"Formatted datetime for database: {result} (tzinfo: {result.tzinfo})")
    return result

def format_for_discord(dt: Union[datetime, str, None], style: str = 'f') -> str:
    """
    Format datetime for Discord timestamp display.
    
    Args:
        dt: datetime object, string, or None
        style: Discord timestamp style (f, F, d, D, t, T, R)
        
    Returns:
        Discord timestamp string
    """
    if dt is None:
        return "Unknown"
    
    dt = ensure_timezone_aware(dt)
    timestamp = int(dt.timestamp())
    return f"<t:{timestamp}:{style}>"

def get_relative_time(dt: Union[datetime, str, None]) -> str:
    """
    Get relative time string for Discord (e.g., "2 hours ago").
    
    Args:
        dt: datetime object, string, or None
        
    Returns:
        Discord relative timestamp string
    """
    return format_for_discord(dt, 'R')

def safe_datetime_subtract(dt1: Union[datetime, str, None], dt2: Union[datetime, str, None]) -> timedelta:
    """
    Safely subtract two datetimes, ensuring both are timezone-aware.
    
    Args:
        dt1: First datetime (minuend)
        dt2: Second datetime (subtrahend)
        
    Returns:
        timedelta representing dt1 - dt2
    """
    dt1_aware = ensure_timezone_aware(dt1)
    dt2_aware = ensure_timezone_aware(dt2)
    
    return dt1_aware - dt2_aware

def safe_datetime_add(dt: Union[datetime, str, None], delta: timedelta) -> datetime:
    """
    Safely add a timedelta to a datetime, ensuring timezone awareness.
    
    Args:
        dt: datetime to add to
        delta: timedelta to add
        
    Returns:
        timezone-aware datetime
    """
    dt_aware = ensure_timezone_aware(dt)
    return dt_aware + delta

def hours_ago(hours: int) -> datetime:
    """
    Get a timezone-aware datetime N hours ago from now.
    
    Args:
        hours: Number of hours ago
        
    Returns:
        timezone-aware datetime in UTC
    """
    return utc_now() - timedelta(hours=hours)

def minutes_ago(minutes: int) -> datetime:
    """
    Get a timezone-aware datetime N minutes ago from now.
    
    Args:
        minutes: Number of minutes ago
        
    Returns:
        timezone-aware datetime in UTC
    """
    return utc_now() - timedelta(minutes=minutes)

def days_ago(days: int) -> datetime:
    """
    Get a timezone-aware datetime N days ago from now.
    
    Args:
        days: Number of days ago
        
    Returns:
        timezone-aware datetime in UTC
    """
    return utc_now() - timedelta(days=days)

def datetime_to_timestamp(dt: Union[datetime, str, None]) -> int:
    """
    Convert datetime to Unix timestamp.
    
    Args:
        dt: datetime object, string, or None
        
    Returns:
        Unix timestamp as integer
    """
    dt_aware = ensure_timezone_aware(dt)
    return int(dt_aware.timestamp())

def timestamp_to_datetime(timestamp: Union[int, float]) -> datetime:
    """
    Convert Unix timestamp to timezone-aware datetime.
    
    Args:
        timestamp: Unix timestamp
        
    Returns:
        timezone-aware datetime in UTC
    """
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)

# Export commonly used functions
__all__ = [
    'utc_now',
    'ensure_timezone_aware', 
    'parse_iso_datetime',
    'parse_github_datetime',
    'format_for_database',
    'format_for_discord',
    'get_relative_time',
    'safe_datetime_subtract',
    'safe_datetime_add',
    'hours_ago',
    'minutes_ago',
    'days_ago',
    'datetime_to_timestamp',
    'timestamp_to_datetime'
]
