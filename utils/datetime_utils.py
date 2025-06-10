"""
Emergency datetime utilities - bulletproof timezone handling
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Union
import logging

logger = logging.getLogger(__name__)

def utc_now() -> datetime:
    """Get current UTC time as timezone-aware datetime"""
    return datetime.now(timezone.utc)

def ensure_timezone_aware(dt: Union[datetime, str, None]) -> datetime:
    """Ensure datetime is timezone-aware (UTC) - EMERGENCY VERSION"""
    if dt is None:
        return utc_now()
    
    if isinstance(dt, str):
        try:
            # Handle ISO format strings
            if dt.endswith('Z'):
                dt = dt[:-1] + '+00:00'
            dt = datetime.fromisoformat(dt)
        except (ValueError, TypeError):
            logger.warning(f"Failed to parse datetime string: {dt}")
            return utc_now()
    
    if not isinstance(dt, datetime):
        logger.warning(f"Invalid datetime type: {type(dt)}")
        return utc_now()
    
    # CRITICAL: Handle timezone conversion
    if dt.tzinfo is None:
        # Naive datetime - assume UTC
        return dt.replace(tzinfo=timezone.utc)
    
    # Already timezone-aware - convert to UTC
    return dt.astimezone(timezone.utc)

def format_for_database(dt: Union[datetime, str, None]) -> datetime:
    """Format datetime for database insertion - EMERGENCY VERSION"""
    aware_dt = ensure_timezone_aware(dt)
    # Return timezone-aware datetime for PostgreSQL
    return aware_dt

def format_for_discord(dt: Union[datetime, str, None], format_type: str = 'f') -> str:
    """Format datetime for Discord display"""
    aware_dt = ensure_timezone_aware(dt)
    timestamp = int(aware_dt.timestamp())
    return f"<t:{timestamp}:{format_type}>"

def get_relative_time(dt: Union[datetime, str, None]) -> str:
    """Get relative time for Discord"""
    return format_for_discord(dt, 'R')

def safe_datetime_subtract(dt: datetime, delta: timedelta) -> datetime:
    """Safely subtract timedelta from datetime - EMERGENCY FIX"""
    aware_dt = ensure_timezone_aware(dt)
    result = aware_dt - delta
    return ensure_timezone_aware(result)

def safe_datetime_add(dt: datetime, delta: timedelta) -> datetime:
    """Safely add timedelta to datetime - EMERGENCY FIX"""
    aware_dt = ensure_timezone_aware(dt)
    result = aware_dt + delta
    return ensure_timezone_aware(result)

def hours_ago(hours: int) -> datetime:
    """Get datetime N hours ago"""
    return safe_datetime_subtract(utc_now(), timedelta(hours=hours))

def parse_github_datetime(iso_string: str) -> datetime:
    """Parse GitHub API datetime string"""
    if not iso_string:
        return utc_now()
    
    try:
        if iso_string.endswith('Z'):
            iso_string = iso_string[:-1] + '+00:00'
        return datetime.fromisoformat(iso_string)
    except (ValueError, TypeError):
        logger.warning(f"Failed to parse GitHub datetime: {iso_string}")
        return utc_now()

def now_for_db() -> datetime:
    """Get current time for database insertion"""
    return utc_now()
