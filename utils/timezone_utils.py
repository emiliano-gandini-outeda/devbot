"""
Timezone utilities for consistent datetime handling across the bot.
This module provides functions to ensure all datetime objects are timezone-aware
and properly formatted for database operations.
"""

from datetime import datetime, timezone
import pytz
import logging

logger = logging.getLogger(__name__)

def utc_now():
    """Get current UTC time as timezone-aware datetime"""
    return datetime.now(timezone.utc)

def ensure_timezone_aware(dt):
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
    
    if dt.tzinfo is None:
        # Assume naive datetime is UTC and make it timezone-aware
        return dt.replace(tzinfo=timezone.utc)
    
    # Convert to UTC if it has a different timezone
    return dt.astimezone(timezone.utc)

def parse_iso_datetime(iso_string):
    """
    Parse ISO datetime string to timezone-aware datetime.
    
    Args:
        iso_string: ISO format datetime string
        
    Returns:
        timezone-aware datetime in UTC
    """
    if iso_string is None:
        return None
    
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
        
        return datetime.fromisoformat(iso_string)
    except ValueError as e:
        logger.warning(f"Failed to parse datetime string '{iso_string}': {e}")
        return utc_now()

def parse_github_datetime(iso_string):
    """
    Parse GitHub API datetime string to timezone-aware datetime.
    GitHub returns ISO format like "2023-12-01T10:30:00Z"
    
    Args:
        iso_string: GitHub API datetime string
        
    Returns:
        timezone-aware datetime in UTC
    """
    return parse_iso_datetime(iso_string)

def format_for_database(dt):
    """
    Format datetime for database insertion.
    
    Args:
        dt: datetime object
        
    Returns:
        timezone-aware datetime in UTC
    """
    return ensure_timezone_aware(dt)

def format_for_discord(dt, style='f'):
    """
    Format datetime for Discord timestamp display.
    
    Args:
        dt: datetime object
        style: Discord timestamp style (f, F, d, D, t, T, R)
        
    Returns:
        Discord timestamp string
    """
    if dt is None:
        return "Unknown"
    
    dt = ensure_timezone_aware(dt)
    timestamp = int(dt.timestamp())
    return f"<t:{timestamp}:{style}>"

def get_relative_time(dt):
    """
    Get relative time string for Discord (e.g., "2 hours ago").
    
    Args:
        dt: datetime object
        
    Returns:
        Discord relative timestamp string
    """
    return format_for_discord(dt, 'R')

def validate_datetime_for_db(dt, field_name="datetime"):
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
        return result
    except Exception as e:
        logger.error(f"Failed to validate {field_name}: {e}")
        raise ValueError(f"Invalid {field_name}: {e}")

# Convenience functions for common operations
def now_for_db():
    """Get current time formatted for database insertion"""
    return utc_now()

def parse_user_datetime(user_input, default_timezone='UTC'):
    """
    Parse user-provided datetime string with timezone handling.
    
    Args:
        user_input: user-provided datetime string
        default_timezone: default timezone if none specified
        
    Returns:
        timezone-aware datetime in UTC
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
    'now_for_db',
    'parse_user_datetime'
]
