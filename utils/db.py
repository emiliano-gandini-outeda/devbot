import asyncio
import asyncpg
import aiosqlite
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from config.settings import Settings
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.database_url = Settings.DATABASE_URL
        self.connection = None
        self._connection_lock = asyncio.Lock()
        self.is_postgresql = self.database_url.startswith('postgresql')
        
        logger.info(f"Database type: {'PostgreSQL' if self.is_postgresql else 'SQLite'}")
    
    async def init_database(self):
        """Initialize database connection and create tables"""
        async with self._connection_lock:
            try:
                if self.is_postgresql:
                    # Connect to PostgreSQL
                    self.connection = await asyncpg.connect(self.database_url)
                    logger.info("✅ Connected to PostgreSQL database")
                    
                    # Test connection
                    result = await self.connection.fetchval("SELECT version()")
                    logger.info(f"PostgreSQL version: {result}")
                else:
                    # Connect to SQLite
                    db_path = self.database_url.replace('sqlite:///', '')
                    self.connection = await aiosqlite.connect(db_path)
                    logger.info(f"✅ Connected to SQLite database: {db_path}")
                    
                    # Test connection
                    cursor = await self.connection.execute("SELECT sqlite_version()")
                    result = await cursor.fetchone()
                    logger.info(f"SQLite version: {result[0]}")
            
            except Exception as e:
                logger.error(f"❌ Failed to connect to database: {e}")
                raise
        
        await self.create_tables()
    
    async def create_tables(self):
        """Create all necessary database tables"""
        try:
            if self.is_postgresql:
                await self._create_postgresql_tables()
            else:
                await self._create_sqlite_tables()
            logger.info("✅ All database tables created successfully")
        except Exception as e:
            logger.error(f"❌ Failed to create database tables: {e}")
            raise
    
    async def _create_postgresql_tables(self):
        """Create tables for PostgreSQL"""
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
            
            # GitHub channels table
            """
            CREATE TABLE IF NOT EXISTS github_channels (
                id SERIAL PRIMARY KEY,
                guild_id TEXT UNIQUE NOT NULL,
                channel_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # GitHub repos table
            """
            CREATE TABLE IF NOT EXISTS github_repos (
                id SERIAL PRIMARY KEY,
                guild_id TEXT NOT NULL,
                repo_url TEXT NOT NULL,
                ping_users TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, repo_url)
            )
            """,
            
            # GitHub repo stats table
            """
            CREATE TABLE IF NOT EXISTS github_repo_stats (
                id SERIAL PRIMARY KEY,
                repo_url TEXT NOT NULL UNIQUE,
                stars INTEGER NOT NULL DEFAULT 0,
                forks INTEGER NOT NULL DEFAULT 0,
                issues INTEGER NOT NULL DEFAULT 0,
                last_updated TIMESTAMP NOT NULL DEFAULT NOW()
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
        ]

        for i, table_sql in enumerate(tables, 1):
            try:
                await self.connection.execute(table_sql)
                table_name = table_sql.split("CREATE TABLE IF NOT EXISTS ")[1].split(" (")[0]
                logger.info(f"✅ Created table {i}/{len(tables)}: {table_name}")
            except Exception as e:
                logger.error(f"❌ Failed to create table {i}: {e}")
                raise

        # Create indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id)",
            "CREATE INDEX IF NOT EXISTS idx_admin_roles_guild_id ON admin_roles(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_guild_id ON tickets(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_channels_guild ON github_channels(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_repos_guild ON github_repos(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_repo_stats_url ON github_repo_stats(repo_url)",
            "CREATE INDEX IF NOT EXISTS idx_log_configs_guild ON log_configs(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_data_lookup ON user_data(user_id, guild_id, data_type)"
        ]

        for index_sql in indexes:
            try:
                await self.connection.execute(index_sql)
            except Exception as e:
                logger.warning(f"Failed to create index: {e}")
    
    async def _create_sqlite_tables(self):
        """Create tables for SQLite"""
        tables = [
            # Users table
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT UNIQUE NOT NULL,
                username TEXT NOT NULL,
                google_token TEXT,
                notion_token TEXT,
                trello_token TEXT,
                preferences TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # Admin roles table
            """
            CREATE TABLE IF NOT EXISTS admin_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, role_id)
            )
            """,
            
            # Tickets table
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            
            # GitHub channels table
            """
            CREATE TABLE IF NOT EXISTS github_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT UNIQUE NOT NULL,
                channel_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # GitHub repos table
            """
            CREATE TABLE IF NOT EXISTS github_repos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                repo_url TEXT NOT NULL,
                ping_users TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, repo_url)
            )
            """,
            
            # GitHub repo stats table
            """
            CREATE TABLE IF NOT EXISTS github_repo_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_url TEXT NOT NULL UNIQUE,
                stars INTEGER NOT NULL DEFAULT 0,
                forks INTEGER NOT NULL DEFAULT 0,
                issues INTEGER NOT NULL DEFAULT 0,
                last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # Log configs table
            """
            CREATE TABLE IF NOT EXISTS log_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT UNIQUE NOT NULL,
                log_channel_id TEXT NOT NULL,
                log_types TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            # User data table for flexible storage
            """
            CREATE TABLE IF NOT EXISTS user_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                guild_id TEXT,
                data_type TEXT NOT NULL,
                data_content TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, guild_id, data_type)
            )
            """,
        ]

        for i, table_sql in enumerate(tables, 1):
            try:
                await self.connection.execute(table_sql)
                table_name = table_sql.split("CREATE TABLE IF NOT EXISTS ")[1].split(" (")[0]
                logger.info(f"✅ Created table {i}/{len(tables)}: {table_name}")
            except Exception as e:
                logger.error(f"❌ Failed to create table {i}: {e}")
                raise

        await self.connection.commit()

        # Create indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id)",
            "CREATE INDEX IF NOT EXISTS idx_admin_roles_guild_id ON admin_roles(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_guild_id ON tickets(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_channels_guild ON github_channels(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_repos_guild ON github_repos(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_repo_stats_url ON github_repo_stats(repo_url)",
            "CREATE INDEX IF NOT EXISTS idx_log_configs_guild ON log_configs(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_data_lookup ON user_data(user_id, guild_id, data_type)"
        ]

        for index_sql in indexes:
            try:
                await self.connection.execute(index_sql)
            except Exception as e:
                logger.warning(f"Failed to create index: {e}")
        
        await self.connection.commit()
    
    async def get_user(self, discord_id: str) -> Optional[Dict[str, Any]]:
        """Get user from database"""
        try:
            if self.is_postgresql:
                row = await self.connection.fetchrow(
                    "SELECT * FROM users WHERE discord_id = $1", discord_id
                )
                return dict(row) if row else None
            else:
                cursor = await self.connection.execute(
                    "SELECT * FROM users WHERE discord_id = ?", (discord_id,)
                )
                row = await cursor.fetchone()
                if row:
                    columns = [description[0] for description in cursor.description]
                    return dict(zip(columns, row))
                return None
        except Exception as e:
            logger.error(f"Failed to get user {discord_id}: {e}")
            return None
    
    async def create_user(self, discord_id: str, username: str) -> bool:
        """Create new user in database"""
        try:
            if self.is_postgresql:
                await self.connection.execute(
                    "INSERT INTO users (discord_id, username) VALUES ($1, $2) ON CONFLICT (discord_id) DO NOTHING",
                    discord_id, username
                )
            else:
                await self.connection.execute(
                    "INSERT OR IGNORE INTO users (discord_id, username) VALUES (?, ?)",
                    (discord_id, username)
                )
                await self.connection.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to create user {discord_id}: {e}")
            return False
    
    async def test_connection(self):
        """Test database connection"""
        try:
            if self.is_postgresql:
                result = await self.connection.fetchval("SELECT 1")
                count = await self.connection.fetchval("SELECT COUNT(*) FROM users")
            else:
                cursor = await self.connection.execute("SELECT 1")
                result = await cursor.fetchone()
                cursor = await self.connection.execute("SELECT COUNT(*) FROM users")
                count_row = await cursor.fetchone()
                count = count_row[0] if count_row else 0
            
            logger.info(f"✅ Database connection test successful")
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
