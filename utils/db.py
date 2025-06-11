import asyncio
import asyncpg
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from config.settings import Settings
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.database_url = Settings.DATABASE_URL
        self.connection_pool = None
        self._pool_lock = asyncio.Lock()
        self.is_postgresql = True
        self._max_connections = 20
        self._min_connections = 5
        
        logger.info(f"Database URL: {self.database_url[:50]}...")
    
    async def init_database(self):
        """Initialize database connection pool and create tables"""
        async with self._pool_lock:
            try:
                # Create connection pool instead of single connection
                async with asyncio.timeout(30):
                    self.connection_pool = await asyncpg.create_pool(
                        self.database_url,
                        min_size=self._min_connections,
                        max_size=self._max_connections,
                        max_queries=50000,
                        max_inactive_connection_lifetime=300,
                        command_timeout=10
                    )
                logger.info(f"✅ Connected to PostgreSQL with pool ({self._min_connections}-{self._max_connections} connections)")
                
                # Test the pool
                async with asyncio.timeout(5):
                    async with self.connection_pool.acquire() as conn:
                        result = await conn.fetchval("SELECT version()")
                        logger.info(f"PostgreSQL version: {result}")
            
            except Exception as e:
                logger.error(f"❌ Failed to connect to PostgreSQL: {e}")
                raise
        
        await self.create_tables()
    
    async def get_connection(self):
        """Get a connection from the pool with proper error handling"""
        if not self.connection_pool:
            raise RuntimeError("Database pool not initialized")
        
        try:
            return self.connection_pool.acquire()
        except Exception as e:
            logger.error(f"Failed to acquire database connection: {e}")
            raise
    
    async def execute_query(self, query: str, *args, fetch_type: str = "execute"):
        """Execute query with proper connection management and retry logic"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                async with self.get_connection() as conn:
                    # Use a transaction for consistency
                    async with conn.transaction():
                        if fetch_type == "fetch":
                            return await conn.fetch(query, *args)
                        elif fetch_type == "fetchrow":
                            return await conn.fetchrow(query, *args)
                        elif fetch_type == "fetchval":
                            return await conn.fetchval(query, *args)
                        else:
                            return await conn.execute(query, *args)
                            
            except asyncpg.exceptions.InFailedSqlTransactionError:
                # Transaction failed, retry with new connection
                logger.warning(f"Transaction failed on attempt {attempt + 1}, retrying...")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                else:
                    raise
                    
            except Exception as e:
                logger.warning(f"Database query failed on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                else:
                    raise
    
    # Add a property for backward compatibility
    @property
    def connection(self):
        """Backward compatibility wrapper"""
        return DatabaseConnectionWrapper(self)
    
    async def create_tables(self):
        """Create all necessary database tables"""
        try:
            await self._create_postgresql_tables()
            logger.info("✅ All database tables created successfully")
        except Exception as e:
            logger.error(f"❌ Failed to create database tables: {e}")
            raise
    
    async def _create_postgresql_tables(self):
        """Create tables for PostgreSQL - only if they don't exist"""
    
        # Create new tables only if they don't exist (preserve existing data)
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        
            # Admin roles table
            """
            CREATE TABLE IF NOT EXISTS admin_roles (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, role_id)
            )
            """,
        
            # Tickets table
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                remind_at TIMESTAMP NOT NULL,
                type TEXT DEFAULT 'personal',
                recurring BOOLEAN DEFAULT FALSE,
                send_dm BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        
            # User data table for flexible storage
            """
            CREATE TABLE IF NOT EXISTS user_data (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                guild_id TEXT,
                data_type TEXT NOT NULL,
                data_content JSONB DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                scheduled_time TIMESTAMP NOT NULL,
                duration_minutes INTEGER DEFAULT 60,
                attendees JSONB DEFAULT '[]',
                status TEXT DEFAULT 'scheduled',
                meeting_link TEXT,
                voice_channel_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        
            # Keywords table for notifications
            """
            CREATE TABLE IF NOT EXISTS keywords (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                keyword TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, user_id, keyword)
            )
            """,
        
            # GitHub tracked repositories table
            """
            CREATE TABLE IF NOT EXISTS github_tracked_repos (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                added_by TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, repo_name, channel_id)
            )
            """,

            # GitHub user subscriptions table  
            """
            CREATE TABLE IF NOT EXISTS github_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, guild_id, repo_name)
            )
            """,

            # Log configs table
            """
            CREATE TABLE IF NOT EXISTS log_configs (
                id SERIAL PRIMARY KEY,
                guild_id TEXT UNIQUE NOT NULL,
                log_channel_id TEXT NOT NULL,
                log_types JSONB DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        ]

        # Create tables only if they don't exist
        for i, table_sql in enumerate(tables, 1):
            try:
                await self.execute_query(table_sql)
                table_name = table_sql.split("CREATE TABLE IF NOT EXISTS ")[1].split(" (")[0]
                logger.info(f"✅ Ensured table {i}/{len(tables)} exists: {table_name}")
            except Exception as e:
                logger.error(f"❌ Failed to ensure table {i} exists: {e}")
                raise

        # Create essential indexes (only if they don't exist)
        essential_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id)",
            "CREATE INDEX IF NOT EXISTS idx_admin_roles_guild_id ON admin_roles(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_guild_id ON tickets(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at)",
            "CREATE INDEX IF NOT EXISTS idx_workflows_guild_id ON workflows(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_meetings_guild_id ON meetings(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_keywords_guild_user ON keywords(guild_id, user_id)",
            "CREATE INDEX IF NOT EXISTS idx_keywords_guild_keyword ON keywords(guild_id, keyword)",
            "CREATE INDEX IF NOT EXISTS idx_github_repos_guild ON github_tracked_repos(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_data_lookup ON user_data(user_id, guild_id, data_type)",
            "CREATE INDEX IF NOT EXISTS idx_log_configs_guild ON log_configs(guild_id)"
        ]

        logger.info("Creating essential indexes (if not exists)...")
        for index_sql in essential_indexes:
            try:
                await self.execute_query(index_sql)
            except Exception as e:
                logger.warning(f"Failed to create index: {e}")

        logger.info("✅ PostgreSQL tables and indexes ensured (data preserved)")
    
    async def get_user(self, discord_id: str) -> Optional[Dict[str, Any]]:
        """Get user from database"""
        try:
            row = await self.execute_query(
                "SELECT * FROM users WHERE discord_id = $1", 
                discord_id, 
                fetch_type="fetchrow"
            )
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get user {discord_id}: {e}")
            return None
    
    async def create_user(self, discord_id: str, username: str) -> bool:
        """Create new user in database"""
        try:
            await self.execute_query(
                "INSERT INTO users (discord_id, username) VALUES ($1, $2) ON CONFLICT (discord_id) DO NOTHING",
                discord_id, username
            )
            return True
        except Exception as e:
            logger.error(f"Failed to create user {discord_id}: {e}")
            return False
    
    async def test_connection(self):
        """Test database connection and basic operations"""
        try:
            result = await self.execute_query("SELECT 1", fetch_type="fetchval")
            logger.info(f"✅ PostgreSQL connection test successful: {result}")
            
            # Test table access
            count = await self.execute_query("SELECT COUNT(*) FROM users", fetch_type="fetchval")
            logger.info(f"✅ Users table accessible, contains {count} records")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Database connection test failed: {e}")
            return False
    
    async def close(self):
        """Close database connection pool"""
        if self.connection_pool:
            try:
                await self.connection_pool.close()
                logger.info("✅ Database connection pool closed")
            except Exception as e:
                logger.error(f"Error closing database connection pool: {e}")


class DatabaseConnectionWrapper:
    """Wrapper to maintain backward compatibility with existing code"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    async def fetch(self, query: str, *args):
        """Fetch multiple rows"""
        return await self.db_manager.execute_query(query, *args, fetch_type="fetch")
    
    async def fetchrow(self, query: str, *args):
        """Fetch single row"""
        return await self.db_manager.execute_query(query, *args, fetch_type="fetchrow")
    
    async def fetchval(self, query: str, *args):
        """Fetch single value"""
        return await self.db_manager.execute_query(query, *args, fetch_type="fetchval")
    
    async def execute(self, query: str, *args):
        """Execute query"""
        return await self.db_manager.execute_query(query, *args, fetch_type="execute")
