"""
Timezone utilities for consistent datetime handling across the bot.
This module provides functions to ensure all datetime objects are timezone-aware
and properly formatted for database operations.
"""

from datetime import datetime, timezone, timedelta
import pytz
import logging
from typing import Union, Optional

logger = logging.getLogger(__name__)

def utc_now():
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

def validate_datetime_for_db(dt: Union[datetime, str, None], field_name: str = "datetime") -> datetime:
    """
    Validate and prepare datetime for database operations.
    
    Args:
        dt: datetime object to validate
        field_name: name of the field for error messages
        
    Returns:
        timezone-aware datetime in UTC
        
    Raises:
        ValueError: if datetime cannot be processed
    """
    try:
        result = ensure_timezone_aware(dt)
        if result is None:
            raise ValueError(f"{field_name} cannot be None")
        
        # Ensure it's a valid datetime
        if not isinstance(result, datetime):
            raise ValueError(f"{field_name} must be a datetime object")
        
        # Ensure it has timezone info
        if result.tzinfo is None:
            raise ValueError(f"{field_name} must be timezone-aware")
        
        return result
    except Exception as e:
        logger.error(f"Failed to validate {field_name}: {e}")
        raise ValueError(f"Invalid {field_name}: {e}")

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

def safe_datetime_compare(dt1: datetime, dt2: datetime) -> int:
    """
    Safely compare two datetime objects, ensuring both are timezone-aware.
    
    Args:
        dt1: First datetime
        dt2: Second datetime
        
    Returns:
        -1 if dt1 < dt2, 0 if dt1 == dt2, 1 if dt1 > dt2
    """
    dt1_aware = ensure_timezone_aware(dt1)
    dt2_aware = ensure_timezone_aware(dt2)
    
    if dt1_aware < dt2_aware:
        return -1
    elif dt1_aware > dt2_aware:
        return 1
    else:
        return 0

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

# Convenience functions for common operations
def now_for_db() -> datetime:
    """Get current time formatted for database insertion"""
    return utc_now()

def parse_user_datetime(user_input: str, default_timezone: str = 'UTC') -> Optional[datetime]:
    """
    Parse user-provided datetime string with timezone handling.
    
    Args:
        user_input: user-provided datetime string
        default_timezone: default timezone if none specified
        
    Returns:
        timezone-aware datetime in UTC or None if parsing fails
    """
    if not user_input:
        return None
    
    try:
        # Try parsing as ISO first
        return parse_iso_datetime(user_input)
    except:
        try:
            # Try parsing without timezone, assume default
            dt = datetime.fromisoformat(user_input)
            if dt.tzinfo is None:
                # Apply default timezone
                tz = pytz.timezone(default_timezone)
                dt = tz.localize(dt)
            return dt.astimezone(timezone.utc)
        except Exception as e:
            logger.warning(f"Failed to parse user datetime '{user_input}': {e}")
            return None

def ensure_utc_datetime(dt: Optional[Union[datetime, str]]) -> datetime:
    """
    Alias for ensure_timezone_aware for backward compatibility.
    """
    return ensure_timezone_aware(dt)

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
    'validate_datetime_for_db',
    'safe_datetime_subtract',
    'safe_datetime_add',
    'now_for_db',
    'parse_user_datetime',
    'datetime_to_timestamp',
    'timestamp_to_datetime'
]
