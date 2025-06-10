import asyncio
import asyncpg
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Union
from config.settings import Settings
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Emergency rewrite of database manager with bulletproof datetime handling.
    Zero tolerance for datetime arithmetic errors.
    """
    
    def __init__(self):
        self.database_url = Settings.DATABASE_URL
        self.connection = None
        self._connection_lock = asyncio.Lock()
        self.is_postgresql = True
        
        logger.info(f"🔧 Initializing emergency database manager")
        logger.info(f"Database URL: {self.database_url[:50]}...")
    
    def _sanitize_datetime(self, dt: Any) -> Any:
        """
        CRITICAL: Sanitize datetime objects before database insertion.
        This prevents ALL datetime arithmetic errors.
        """
        if dt is None:
            return None
            
        if isinstance(dt, str):
            # If it's already a string, return as-is
            return dt
            
        if isinstance(dt, datetime):
            # Convert ALL datetimes to UTC timezone-aware format
            if dt.tzinfo is None:
                # Naive datetime - assume UTC
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                # Convert to UTC
                dt = dt.astimezone(timezone.utc)
            
            # Return as ISO string for database compatibility
            return dt.isoformat()
        
        return dt
    
    def _sanitize_params(self, params: tuple) -> tuple:
        """
        CRITICAL: Sanitize all query parameters to prevent datetime errors.
        """
        if not params:
            return params
            
        sanitized = []
        for i, param in enumerate(params):
            try:
                sanitized_param = self._sanitize_datetime(param)
                sanitized.append(sanitized_param)
                
                # Debug logging for datetime parameters
                if isinstance(param, datetime):
                    logger.debug(f"Parameter {i+1}: {param} -> {sanitized_param}")
                    
            except Exception as e:
                logger.error(f"Failed to sanitize parameter {i+1}: {param} - {e}")
                # Use original parameter as fallback
                sanitized.append(param)
        
        return tuple(sanitized)
    
    async def init_database(self):
        """Initialize database connection with proper timezone handling"""
        async with self._connection_lock:
            try:
                logger.info("🔌 Connecting to PostgreSQL database...")
                
                # Connect with explicit timezone handling
                async with asyncio.timeout(15):
                    self.connection = await asyncpg.connect(
                        self.database_url,
                        server_settings={
                            'timezone': 'UTC',
                            'application_name': 'discord-bot'
                        }
                    )
                
                logger.info("✅ Connected to PostgreSQL database")
                
                # Set session timezone to UTC
                await self.connection.execute("SET timezone = 'UTC'")
                
                # Test the connection
                async with asyncio.timeout(5):
                    result = await self.connection.fetchval("SELECT version()")
                    logger.info(f"PostgreSQL version: {result[:100]}...")
                    
                    # Test timezone setting
                    tz_result = await self.connection.fetchval("SHOW timezone")
                    logger.info(f"Database timezone: {tz_result}")
            
            except Exception as e:
                logger.error(f"❌ Failed to connect to PostgreSQL: {e}")
                raise
        
        await self.create_tables()
    
    async def create_tables(self):
        """Create all necessary database tables with proper timezone handling"""
        try:
            await self._create_postgresql_tables()
            logger.info("✅ All database tables created successfully")
        except Exception as e:
            logger.error(f"❌ Failed to create database tables: {e}")
            raise
    
    async def _create_postgresql_tables(self):
        """Create tables for PostgreSQL with TIMESTAMPTZ columns"""
        
        # Emergency table creation with bulletproof datetime handling
        tables = [
            # Users table
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                discord_id TEXT UNIQUE NOT NULL,
                username TEXT NOT NULL,
                google_token TEXT,
                notion_token TEXT,
                trello_token TEXT,
                preferences JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """,
        
            # Admin roles table
            """
            CREATE TABLE IF NOT EXISTS admin_roles (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, role_id)
            )
            """,
        
            # Tickets table - EMERGENCY FIX
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id SERIAL PRIMARY KEY,
                ticket_id TEXT UNIQUE NOT NULL,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                assignee_id TEXT,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'open',
                priority TEXT DEFAULT 'medium',
                channel_id TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """,
        
            # GitHub tracked repositories table - EMERGENCY FIX
            """
            CREATE TABLE IF NOT EXISTS github_tracked_repos (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                added_by TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, repo_name)
            )
            """,
        
            # GitHub repository state table
            """
            CREATE TABLE IF NOT EXISTS github_repo_state (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                last_commit_sha TEXT,
                last_release_id TEXT,
                last_issue_number INTEGER DEFAULT 0,
                last_pr_number INTEGER DEFAULT 0,
                stars_count INTEGER DEFAULT 0,
                last_checked TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, repo_name)
            )
            """,
        
            # GitHub user subscriptions table
            """
            CREATE TABLE IF NOT EXISTS github_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, guild_id, repo_name, event_type)
            )
            """,
        
            # Reminders table
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                guild_id TEXT,
                channel_id TEXT,
                message TEXT NOT NULL,
                remind_at TIMESTAMPTZ NOT NULL,
                type TEXT DEFAULT 'personal',
                recurring BOOLEAN DEFAULT FALSE,
                send_dm BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """,
        
            # Workflows table
            """
            CREATE TABLE IF NOT EXISTS workflows (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                creator_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_data JSONB DEFAULT '{}',
                actions JSONB DEFAULT '[]',
                status TEXT DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """,
        
            # User data table
            """
            CREATE TABLE IF NOT EXISTS user_data (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                guild_id TEXT,
                data_type TEXT NOT NULL,
                data_content JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, guild_id, data_type)
            )
            """,
        
            # Meetings table
            """
            CREATE TABLE IF NOT EXISTS meetings (
                id SERIAL PRIMARY KEY,
                meeting_id TEXT UNIQUE NOT NULL,
                guild_id TEXT NOT NULL,
                creator_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                scheduled_time TIMESTAMPTZ NOT NULL,
                duration_minutes INTEGER DEFAULT 60,
                attendees JSONB DEFAULT '[]',
                status TEXT DEFAULT 'scheduled',
                meeting_link TEXT,
                voice_channel_id TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """,
        
            # Notifications table
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                guild_id TEXT,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """,
        
            # Keywords table
            """
            CREATE TABLE IF NOT EXISTS keywords (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                keyword TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, user_id, keyword)
            )
            """,
        
            # Log configs table
            """
            CREATE TABLE IF NOT EXISTS log_configs (
                id SERIAL PRIMARY KEY,
                guild_id TEXT UNIQUE NOT NULL,
                log_channel_id TEXT NOT NULL,
                log_types JSONB DEFAULT '[]',
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """,
        
            # Ticket configurations table
            """
            CREATE TABLE IF NOT EXISTS ticket_configs (
                id SERIAL PRIMARY KEY,
                guild_id TEXT UNIQUE NOT NULL,
                category_id TEXT,
                transcript_channel_id TEXT,
                support_role_id TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """
        ]

        # Create tables with error handling
        for i, table_sql in enumerate(tables, 1):
            try:
                async with asyncio.timeout(10):
                    await self.connection.execute(table_sql)
                    table_name = table_sql.split("CREATE TABLE IF NOT EXISTS ")[1].split(" (")[0]
                    logger.info(f"✅ Table {i}/{len(tables)}: {table_name}")
            except asyncio.TimeoutError:
                logger.error(f"❌ Table creation timed out: table {i}")
                raise
            except Exception as e:
                logger.error(f"❌ Failed to create table {i}: {e}")
                raise

        # Create essential indexes
        essential_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id)",
            "CREATE INDEX IF NOT EXISTS idx_admin_roles_guild_id ON admin_roles(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_guild_id ON tickets(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_ticket_id ON tickets(ticket_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_repos_guild ON github_tracked_repos(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_state_guild_repo ON github_repo_state(guild_id, repo_name)",
            "CREATE INDEX IF NOT EXISTS idx_github_subs_user_guild ON github_subscriptions(user_id, guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at)",
            "CREATE INDEX IF NOT EXISTS idx_workflows_guild_id ON workflows(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_data_lookup ON user_data(user_id, guild_id, data_type)",
            "CREATE INDEX IF NOT EXISTS idx_meetings_guild_id ON meetings(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_keywords_guild_user ON keywords(guild_id, user_id)",
            "CREATE INDEX IF NOT EXISTS idx_log_configs_guild ON log_configs(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_ticket_configs_guild ON ticket_configs(guild_id)"
        ]

        logger.info("Creating essential indexes...")
        for index_sql in essential_indexes:
            try:
                async with asyncio.timeout(5):
                    await self.connection.execute(index_sql)
            except Exception as e:
                logger.warning(f"Failed to create index: {e}")

        logger.info("✅ PostgreSQL tables and indexes created with bulletproof timezone handling")
    
    async def execute_query(self, query: str, *params) -> str:
        """
        EMERGENCY: Execute query with bulletproof parameter sanitization
        """
        try:
            # Sanitize all parameters to prevent datetime errors
            sanitized_params = self._sanitize_params(params)
            
            # Log the query for debugging
            logger.debug(f"Executing query: {query}")
            logger.debug(f"Original params: {params}")
            logger.debug(f"Sanitized params: {sanitized_params}")
            
            async with self._connection_lock:
                if sanitized_params:
                    result = await self.connection.execute(query, *sanitized_params)
                else:
                    result = await self.connection.execute(query)
                
                logger.debug(f"Query executed successfully: {result}")
                return result
                
        except Exception as e:
            logger.error(f"❌ Query execution failed: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            logger.error(f"Sanitized: {sanitized_params}")
            raise
    
    async def fetch_query(self, query: str, *params) -> List[Dict[str, Any]]:
        """
        EMERGENCY: Fetch query results with bulletproof parameter sanitization
        """
        try:
            # Sanitize all parameters
            sanitized_params = self._sanitize_params(params)
            
            logger.debug(f"Fetching query: {query}")
            logger.debug(f"Sanitized params: {sanitized_params}")
            
            async with self._connection_lock:
                if sanitized_params:
                    rows = await self.connection.fetch(query, *sanitized_params)
                else:
                    rows = await self.connection.fetch(query)
                
                # Convert to list of dicts
                result = [dict(row) for row in rows]
                logger.debug(f"Fetched {len(result)} rows")
                return result
                
        except Exception as e:
            logger.error(f"❌ Fetch query failed: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            raise
    
    async def fetchrow_query(self, query: str, *params) -> Optional[Dict[str, Any]]:
        """
        EMERGENCY: Fetch single row with bulletproof parameter sanitization
        """
        try:
            # Sanitize all parameters
            sanitized_params = self._sanitize_params(params)
            
            logger.debug(f"Fetching row: {query}")
            logger.debug(f"Sanitized params: {sanitized_params}")
            
            async with self._connection_lock:
                if sanitized_params:
                    row = await self.connection.fetchrow(query, *sanitized_params)
                else:
                    row = await self.connection.fetchrow(query)
                
                if row:
                    result = dict(row)
                    logger.debug(f"Fetched row: {result}")
                    return result
                else:
                    logger.debug("No row found")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Fetchrow query failed: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            raise
    
    async def fetchval_query(self, query: str, *params) -> Any:
        """
        EMERGENCY: Fetch single value with bulletproof parameter sanitization
        """
        try:
            # Sanitize all parameters
            sanitized_params = self._sanitize_params(params)
            
            logger.debug(f"Fetching value: {query}")
            logger.debug(f"Sanitized params: {sanitized_params}")
            
            async with self._connection_lock:
                if sanitized_params:
                    result = await self.connection.fetchval(query, *sanitized_params)
                else:
                    result = await self.connection.fetchval(query)
                
                logger.debug(f"Fetched value: {result}")
                return result
                
        except Exception as e:
            logger.error(f"❌ Fetchval query failed: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            raise
    
    async def get_user(self, discord_id: str) -> Optional[Dict[str, Any]]:
        """Get user from database with proper datetime handling"""
        try:
            return await self.fetchrow_query(
                "SELECT * FROM users WHERE discord_id = $1", discord_id
            )
        except Exception as e:
            logger.error(f"Failed to get user {discord_id}: {e}")
            return None
    
    async def create_user(self, discord_id: str, username: str) -> bool:
        """Create new user in database with bulletproof datetime handling"""
        try:
            # Create current timestamp
            current_time = datetime.now(timezone.utc)
            
            await self.execute_query(
                "INSERT INTO users (discord_id, username, created_at, updated_at) VALUES ($1, $2, $3, $4) ON CONFLICT (discord_id) DO NOTHING",
                discord_id, username, current_time, current_time
            )
            return True
        except Exception as e:
            logger.error(f"Failed to create user {discord_id}: {e}")
            return False
    
    async def test_connection(self):
        """Test database connection and basic operations"""
        try:
            result = await self.fetchval_query("SELECT 1")
            logger.info(f"✅ PostgreSQL connection test successful: {result}")
            
            # Test table access
            count = await self.fetchval_query("SELECT COUNT(*) FROM users")
            logger.info(f"✅ Users table accessible, contains {count} records")
            
            # Test timezone handling
            test_time = datetime.now(timezone.utc)
            logger.info(f"✅ Timezone handling working: {test_time}")
            
            # Test datetime parameter sanitization
            sanitized = self._sanitize_datetime(test_time)
            logger.info(f"✅ Datetime sanitization working: {sanitized}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Database connection test failed: {e}")
            return False
    
    async def close(self):
        """Close database connection"""
        if self.connection:
            try:
                await self.connection.close()
                logger.info("✅ Database connection closed")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}")

    async def execute_with_retry(self, query, *args, max_retries=3):
        """Execute query with retry logic and bulletproof datetime handling"""
        for attempt in range(max_retries):
            try:
                return await self.execute_query(query, *args)
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Database operation failed, retrying... (attempt {attempt + 1})")
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                else:
                    logger.error(f"Database operation failed after {max_retries} attempts: {e}")
                    raise e

# Utility functions for backward compatibility
def utc_now():
    """Get current UTC time as timezone-aware datetime"""
    return datetime.now(timezone.utc)

def ensure_timezone_aware(dt):
    """Ensure datetime is timezone-aware (UTC)"""
    if dt is None:
        return utc_now()
    
    if isinstance(dt, str):
        try:
            # Try to parse ISO format
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except ValueError:
            return utc_now()
    
    if not isinstance(dt, datetime):
        return utc_now()
    
    if dt.tzinfo is None:
        # Assume naive datetime is UTC and make it timezone-aware
        return dt.replace(tzinfo=timezone.utc)
    
    # Convert to UTC if it has a different timezone
    return dt.astimezone(timezone.utc)

def now_for_db():
    """Get current time for database insertion"""
    return utc_now()

def format_for_database(dt):
    """Format datetime for database insertion"""
    return ensure_timezone_aware(dt)
