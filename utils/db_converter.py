"""
Database Type Converter - Fixes Unix timestamp to datetime conversion
Handles all database parameter type mismatches
"""

import asyncio
import asyncpg
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Union, Tuple
from config.settings import Settings
import logging

logger = logging.getLogger(__name__)

class DatabaseConverter:
    """Converts between Unix timestamps and datetime objects for database operations"""
    
    @staticmethod
    def unix_to_datetime(timestamp: Union[int, float]) -> datetime:
        """Convert Unix timestamp to timezone-aware datetime"""
        if isinstance(timestamp, (int, float)) and timestamp > 0:
            return datetime.fromtimestamp(timestamp, timezone.utc)
        return datetime.now(timezone.utc)
    
    @staticmethod
    def datetime_to_unix(dt: datetime) -> int:
        """Convert datetime to Unix timestamp"""
        if isinstance(dt, datetime):
            return int(dt.timestamp())
        return int(datetime.now(timezone.utc).timestamp())
    
    @staticmethod
    def convert_params_for_db(params: tuple) -> tuple:
        """Convert Unix timestamps in parameters to datetime objects for database"""
        if not params:
            return params
        
        converted = []
        for i, param in enumerate(params):
            if isinstance(param, (int, float)) and param > 1000000000:  # Unix timestamp
                # Convert to datetime for database
                converted_param = DatabaseConverter.unix_to_datetime(param)
                converted.append(converted_param)
                logger.debug(f"Parameter {i+1}: {param} (int) -> {converted_param} (datetime)")
            else:
                converted.append(param)
        
        return tuple(converted)
    
    @staticmethod
    def convert_row_from_db(row: dict) -> dict:
        """Convert datetime objects from database to Unix timestamps"""
        if not row:
            return row
        
        converted = {}
        for key, value in row.items():
            if isinstance(value, datetime):
                # Convert datetime to Unix timestamp
                converted[key] = int(value.timestamp())
            else:
                converted[key] = value
        
        return converted

class FixedDatabaseManager:
    """Database manager with automatic type conversion"""
    
    def __init__(self):
        self.database_url = Settings.DATABASE_URL
        self.connection = None
        self._connection_lock = asyncio.Lock()
        self.is_postgresql = True
        self.converter = DatabaseConverter()
        
        logger.info("🔧 Fixed Database Manager initialized with type conversion")
    
    async def init_database(self):
        """Initialize database connection"""
        async with self._connection_lock:
            try:
                # Connect to PostgreSQL with timezone setting
                async with asyncio.timeout(15):
                    self.connection = await asyncpg.connect(
                        self.database_url,
                        server_settings={'timezone': 'UTC'}
                    )
                
                logger.info("✅ Connected to PostgreSQL with timezone conversion")
                
                # Set session timezone
                await self.connection.execute("SET timezone = 'UTC'")
                
                # Test connection
                result = await self.connection.fetchval("SELECT version()")
                logger.info(f"PostgreSQL: {result[:50]}...")
                
            except Exception as e:
                logger.error(f"❌ Database connection failed: {e}")
                raise
        
        await self.create_tables()
    
    async def create_tables(self):
        """Create all necessary database tables with proper timestamp columns"""
        try:
            await self._create_postgresql_tables()
            logger.info("✅ All database tables created successfully")
        except Exception as e:
            logger.error(f"❌ Failed to create database tables: {e}")
            raise
    
    async def _create_postgresql_tables(self):
        """Create tables for PostgreSQL with TIMESTAMP columns"""
        
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
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # Admin roles table
            """
            CREATE TABLE IF NOT EXISTS admin_roles (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, role_id)
            )
            """,
            
            # FIXED Tickets table with proper TIMESTAMP columns
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
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, guild_id, data_type)
            )
            """,
            
            # FIXED GitHub tracked repositories table
            """
            CREATE TABLE IF NOT EXISTS github_tracked_repos (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                added_by TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, repo_name)
            )
            """,
            
            # FIXED GitHub repository state table
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
                last_checked TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, repo_name)
            )
            """,
            
            # FIXED GitHub user subscriptions table
            """
            CREATE TABLE IF NOT EXISTS github_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
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
                remind_at TIMESTAMP WITH TIME ZONE NOT NULL,
                type TEXT DEFAULT 'personal',
                recurring BOOLEAN DEFAULT FALSE,
                send_dm BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
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
                scheduled_time TIMESTAMP WITH TIME ZONE NOT NULL,
                duration_minutes INTEGER DEFAULT 60,
                attendees JSONB DEFAULT '[]',
                status TEXT DEFAULT 'scheduled',
                meeting_link TEXT,
                voice_channel_id TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # Keywords table
            """
            CREATE TABLE IF NOT EXISTS keywords (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                keyword TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, user_id, keyword)
            )
            """
        ]

        # Create tables
        for i, table_sql in enumerate(tables, 1):
            try:
                async with asyncio.timeout(10):
                    await self.connection.execute(table_sql)
                    table_name = table_sql.split("CREATE TABLE IF NOT EXISTS ")[1].split(" (")[0]
                    logger.info(f"✅ Table {i}/{len(tables)}: {table_name}")
            except Exception as e:
                logger.error(f"❌ Failed to create table {i}: {e}")
                raise

        # Create indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_guild_id ON tickets(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_ticket_id ON tickets(ticket_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)",
            "CREATE INDEX IF NOT EXISTS idx_github_repos_guild ON github_tracked_repos(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_state_guild_repo ON github_repo_state(guild_id, repo_name)",
            "CREATE INDEX IF NOT EXISTS idx_github_subs_user_guild ON github_subscriptions(user_id, guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_data_lookup ON user_data(user_id, guild_id, data_type)",
            "CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at)"
        ]

        for index_sql in indexes:
            try:
                await self.connection.execute(index_sql)
            except Exception as e:
                logger.warning(f"Index creation failed: {e}")

        logger.info("✅ PostgreSQL tables created with TIMESTAMP WITH TIME ZONE columns")
    
    async def execute_with_conversion(self, query: str, *params) -> str:
        """Execute query with automatic type conversion"""
        try:
            # Convert Unix timestamps to datetime objects
            converted_params = self.converter.convert_params_for_db(params)
            
            logger.debug(f"🔧 Query: {query}")
            logger.debug(f"🔧 Original params: {params}")
            logger.debug(f"🔧 Converted params: {converted_params}")
            
            async with self._connection_lock:
                if converted_params:
                    result = await self.connection.execute(query, *converted_params)
                else:
                    result = await self.connection.execute(query)
                
                logger.debug(f"✅ Query executed: {result}")
                return result
                
        except Exception as e:
            logger.error(f"❌ Query failed: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            raise
    
    async def fetch_with_conversion(self, query: str, *params) -> List[Dict[str, Any]]:
        """Fetch query with automatic type conversion"""
        try:
            converted_params = self.converter.convert_params_for_db(params)
            
            async with self._connection_lock:
                if converted_params:
                    rows = await self.connection.fetch(query, *converted_params)
                else:
                    rows = await self.connection.fetch(query)
                
                # Convert datetime objects back to Unix timestamps for consistency
                result = []
                for row in rows:
                    converted_row = self.converter.convert_row_from_db(dict(row))
                    result.append(converted_row)
                
                return result
                
        except Exception as e:
            logger.error(f"❌ Fetch failed: {e}")
            raise
    
    async def fetchrow_with_conversion(self, query: str, *params) -> Optional[Dict[str, Any]]:
        """Fetch single row with automatic type conversion"""
        try:
            converted_params = self.converter.convert_params_for_db(params)
            
            async with self._connection_lock:
                if converted_params:
                    row = await self.connection.fetchrow(query, *converted_params)
                else:
                    row = await self.connection.fetchrow(query)
                
                if row:
                    return self.converter.convert_row_from_db(dict(row))
                return None
                
        except Exception as e:
            logger.error(f"❌ Fetchrow failed: {e}")
            raise
    
    async def fetchval_with_conversion(self, query: str, *params) -> Any:
        """Fetch single value with automatic type conversion"""
        try:
            converted_params = self.converter.convert_params_for_db(params)
            
            async with self._connection_lock:
                if converted_params:
                    result = await self.connection.fetchval(query, *converted_params)
                else:
                    result = await self.connection.fetchval(query)
                
                return result
                
        except Exception as e:
            logger.error(f"❌ Fetchval failed: {e}")
            raise
    
    # Backward compatibility methods
    async def execute(self, query: str, *params):
        """Backward compatibility wrapper"""
        return await self.execute_with_conversion(query, *params)
    
    async def fetch(self, query: str, *params):
        """Backward compatibility wrapper"""
        return await self.fetch_with_conversion(query, *params)
    
    async def fetchrow(self, query: str, *params):
        """Backward compatibility wrapper"""
        return await self.fetchrow_with_conversion(query, *params)
    
    async def fetchval(self, query: str, *params):
        """Backward compatibility wrapper"""
        return await self.fetchval_with_conversion(query, *params)
    
    async def get_user(self, discord_id: str) -> Optional[Dict[str, Any]]:
        """Get user from database"""
        try:
            row = await self.fetchrow_with_conversion(
                "SELECT * FROM users WHERE discord_id = $1", discord_id
            )
            return row
        except Exception as e:
            logger.error(f"Failed to get user {discord_id}: {e}")
            return None
    
    async def create_user(self, discord_id: str, username: str) -> bool:
        """Create new user in database"""
        try:
            await self.execute_with_conversion(
                "INSERT INTO users (discord_id, username) VALUES ($1, $2) ON CONFLICT (discord_id) DO NOTHING",
                discord_id, username
            )
            return True
        except Exception as e:
            logger.error(f"Failed to create user {discord_id}: {e}")
            return False
    
    async def test_connection(self):
        """Test database connection and type conversion"""
        try:
            result = await self.fetchval_with_conversion("SELECT 1")
            logger.info(f"✅ Database connection test successful: {result}")
            
            # Test timestamp conversion
            current_time = int(datetime.now(timezone.utc).timestamp())
            logger.info(f"✅ Current Unix timestamp: {current_time}")
            
            converted_time = self.converter.unix_to_datetime(current_time)
            logger.info(f"✅ Converted to datetime: {converted_time}")
            
            # Test table access
            count = await self.fetchval_with_conversion("SELECT COUNT(*) FROM users")
            logger.info(f"✅ Users table accessible, contains {count} records")
            
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

# Replace the existing DatabaseManager
DatabaseManager = FixedDatabaseManager
