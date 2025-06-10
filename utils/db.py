"""
NUCLEAR DATABASE SOLUTION: Integer timestamps only
Zero datetime objects in any database operations
"""
import asyncio
import asyncpg
import json
from typing import Optional, List, Dict, Any, Union
from config.settings import Settings
from utils.timestamp_utils import now_timestamp, datetime_to_timestamp
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Nuclear database manager - ZERO datetime objects
    All timestamps stored as INTEGER Unix timestamps
    """
    
    def __init__(self):
        self.database_url = Settings.DATABASE_URL
        self.connection = None
        self._connection_lock = asyncio.Lock()
        self.is_postgresql = True
        
        logger.info("🚀 NUCLEAR DATABASE MANAGER INITIALIZED")
        logger.info("📊 All timestamps will be stored as INTEGER Unix timestamps")
    
    def _sanitize_params(self, params: tuple) -> tuple:
        """
        NUCLEAR: Convert any datetime objects to Unix timestamps
        """
        if not params:
            return params
            
        sanitized = []
        for i, param in enumerate(params):
            if hasattr(param, 'timestamp'):  # datetime object
                # Convert to Unix timestamp
                timestamp = datetime_to_timestamp(param)
                sanitized.append(timestamp)
                logger.debug(f"Parameter {i+1}: datetime -> {timestamp}")
            else:
                sanitized.append(param)
        
        return tuple(sanitized)
    
    async def init_database(self):
        """Initialize database with UTC timezone"""
        async with self._connection_lock:
            try:
                logger.info("🔌 Connecting to PostgreSQL...")
                
                async with asyncio.timeout(15):
                    self.connection = await asyncpg.connect(
                        self.database_url,
                        server_settings={'timezone': 'UTC'}
                    )
                
                logger.info("✅ Connected to PostgreSQL")
                
                # Set session timezone
                await self.connection.execute("SET timezone = 'UTC'")
                
                # Test connection
                result = await self.connection.fetchval("SELECT version()")
                logger.info(f"PostgreSQL: {result[:50]}...")
                
            except Exception as e:
                logger.error(f"❌ Database connection failed: {e}")
                raise
        
        await self.create_nuclear_tables()
    
    async def create_nuclear_tables(self):
        """Create tables with INTEGER timestamp columns only"""
        try:
            await self._create_nuclear_postgresql_tables()
            logger.info("✅ Nuclear database tables created")
        except Exception as e:
            logger.error(f"❌ Failed to create nuclear tables: {e}")
            raise
    
    async def _create_nuclear_postgresql_tables(self):
        """Create PostgreSQL tables with INTEGER timestamps"""
        
        # NUCLEAR TABLES: All timestamps are INTEGER Unix timestamps
        nuclear_tables = [
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
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW()),
                updated_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())
            )
            """,
            
            # Admin roles table
            """
            CREATE TABLE IF NOT EXISTS admin_roles (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW()),
                UNIQUE(guild_id, role_id)
            )
            """,
            
            # NUCLEAR TICKETS TABLE
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
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW()),
                updated_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())
            )
            """,
            
            # NUCLEAR TICKET CONFIGS TABLE
            """
            CREATE TABLE IF NOT EXISTS ticket_configs (
                id SERIAL PRIMARY KEY,
                guild_id TEXT UNIQUE NOT NULL,
                category_id TEXT,
                transcript_channel_id TEXT,
                support_role_id TEXT,
                auto_close_hours INTEGER DEFAULT 72,
                max_tickets_per_user INTEGER DEFAULT 3,
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW()),
                updated_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())
            )
            """,
            
            # NUCLEAR GITHUB REPOS TABLE
            """
            CREATE TABLE IF NOT EXISTS github_tracked_repos (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                added_by TEXT NOT NULL,
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW()),
                UNIQUE(guild_id, repo_name)
            )
            """,
            
            # NUCLEAR GITHUB STATE TABLE
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
                last_checked INTEGER DEFAULT EXTRACT(EPOCH FROM NOW()),
                UNIQUE(guild_id, repo_name)
            )
            """,
            
            # NUCLEAR GITHUB SUBSCRIPTIONS TABLE
            """
            CREATE TABLE IF NOT EXISTS github_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                enabled BOOLEAN DEFAULT TRUE,
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW()),
                UNIQUE(user_id, guild_id, repo_name, event_type)
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
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW()),
                updated_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW()),
                UNIQUE(user_id, guild_id, data_type)
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
                remind_at INTEGER NOT NULL,
                type TEXT DEFAULT 'personal',
                recurring BOOLEAN DEFAULT FALSE,
                send_dm BOOLEAN DEFAULT TRUE,
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())
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
                scheduled_time INTEGER NOT NULL,
                duration_minutes INTEGER DEFAULT 60,
                attendees JSONB DEFAULT '[]',
                status TEXT DEFAULT 'scheduled',
                meeting_link TEXT,
                voice_channel_id TEXT,
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW()),
                updated_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())
            )
            """,
            
            # Keywords table
            """
            CREATE TABLE IF NOT EXISTS keywords (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                guild_id TEXT,
                keyword TEXT NOT NULL,
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW()),
                UNIQUE(user_id, guild_id, keyword)
            )
            """,
            
            # Workflows table
            """
            CREATE TABLE IF NOT EXISTS workflows (
                id SERIAL PRIMARY KEY,
                workflow_id TEXT UNIQUE NOT NULL,
                guild_id TEXT NOT NULL,
                creator_id TEXT NOT NULL,
                name TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_data JSONB DEFAULT '{}',
                actions JSONB DEFAULT '[]',
                enabled BOOLEAN DEFAULT TRUE,
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW()),
                updated_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())
            )
            """
        ]

        # Create each table
        for i, table_sql in enumerate(nuclear_tables, 1):
            try:
                async with asyncio.timeout(10):
                    await self.connection.execute(table_sql)
                    table_name = table_sql.split("CREATE TABLE IF NOT EXISTS ")[1].split(" (")[0]
                    logger.info(f"✅ Nuclear table {i}/{len(nuclear_tables)}: {table_name}")
            except Exception as e:
                logger.error(f"❌ Failed to create nuclear table {i}: {e}")
                raise

        # Create indexes
        nuclear_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_guild_id ON tickets(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_ticket_id ON tickets(ticket_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)",
            "CREATE INDEX IF NOT EXISTS idx_ticket_configs_guild ON ticket_configs(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_repos_guild ON github_tracked_repos(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_state_guild_repo ON github_repo_state(guild_id, repo_name)",
            "CREATE INDEX IF NOT EXISTS idx_github_subs_user_guild ON github_subscriptions(user_id, guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_data_lookup ON user_data(user_id, guild_id, data_type)",
            "CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at)",
            "CREATE INDEX IF NOT EXISTS idx_meetings_guild_id ON meetings(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_keywords_user_guild ON keywords(user_id, guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_workflows_guild_id ON workflows(guild_id)"
        ]

        for index_sql in nuclear_indexes:
            try:
                await self.connection.execute(index_sql)
            except Exception as e:
                logger.warning(f"Index creation failed: {e}")

        logger.info("✅ Nuclear PostgreSQL tables created with INTEGER timestamps")
    
    async def execute(self, query: str, *params) -> str:
        """Execute query with nuclear parameter sanitization"""
        try:
            # Nuclear sanitization - convert all datetime to integers
            sanitized_params = self._sanitize_params(params)
            
            logger.debug(f"Nuclear query: {query}")
            logger.debug(f"Nuclear params: {sanitized_params}")
            
            async with self._connection_lock:
                if sanitized_params:
                    result = await self.connection.execute(query, *sanitized_params)
                else:
                    result = await self.connection.execute(query)
                
                logger.debug(f"Nuclear query executed: {result}")
                return result
                
        except Exception as e:
            logger.error(f"❌ Nuclear query failed: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            raise
    
    async def fetch(self, query: str, *params) -> List[Dict[str, Any]]:
        """Fetch query with nuclear parameter sanitization"""
        try:
            sanitized_params = self._sanitize_params(params)
            
            async with self._connection_lock:
                if sanitized_params:
                    rows = await self.connection.fetch(query, *sanitized_params)
                else:
                    rows = await self.connection.fetch(query)
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"❌ Nuclear fetch failed: {e}")
            raise
    
    async def fetchrow(self, query: str, *params) -> Optional[Dict[str, Any]]:
        """Fetch single row with nuclear parameter sanitization"""
        try:
            sanitized_params = self._sanitize_params(params)
            
            async with self._connection_lock:
                if sanitized_params:
                    row = await self.connection.fetchrow(query, *sanitized_params)
                else:
                    row = await self.connection.fetchrow(query)
                
                return dict(row) if row else None
                
        except Exception as e:
            logger.error(f"❌ Nuclear fetchrow failed: {e}")
            raise
    
    async def fetchval(self, query: str, *params) -> Any:
        """Fetch single value with nuclear parameter sanitization"""
        try:
            sanitized_params = self._sanitize_params(params)
            
            async with self._connection_lock:
                if sanitized_params:
                    result = await self.connection.fetchval(query, *sanitized_params)
                else:
                    result = await self.connection.fetchval(query)
                
                return result
                
        except Exception as e:
            logger.error(f"❌ Nuclear fetchval failed: {e}")
            raise
    
    async def test_connection(self):
        """Test nuclear database operations"""
        try:
            # Test basic query
            result = await self.fetchval("SELECT 1")
            logger.info(f"✅ Nuclear connection test: {result}")
            
            # Test timestamp handling
            current_timestamp = now_timestamp()
            logger.info(f"✅ Nuclear timestamp: {current_timestamp}")
            
            # Test table access
            count = await self.fetchval("SELECT COUNT(*) FROM users")
            logger.info(f"✅ Nuclear users table: {count} records")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Nuclear connection test failed: {e}")
            return False
    
    # Alias for compatibility
    async def test_nuclear_connection(self):
        """Alias for test_connection"""
        return await self.test_connection()
    
    async def close(self):
        """Close database connection"""
        if self.connection:
            try:
                await self.connection.close()
                logger.info("✅ Nuclear database connection closed")
            except Exception as e:
                logger.error(f"Error closing nuclear database: {e}")

# Backward compatibility
NuclearDatabaseManager = DatabaseManager
