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
        self._connection_timeout = 10.0  # Connection timeout in seconds
        self._query_timeout = 5.0  # Query timeout in seconds
        
        logger.info(f"Database type: {'PostgreSQL' if self.is_postgresql else 'SQLite'}")
    
    async def init_database(self):
        """Initialize database connection and create tables"""
        async with self._connection_lock:
            try:
                if self.is_postgresql:
                    # Connect to PostgreSQL with timeout
                    try:
                        self.connection = await asyncio.wait_for(
                            asyncpg.connect(self.database_url), 
                            timeout=self._connection_timeout
                        )
                        logger.info("✅ Connected to PostgreSQL database")
                        
                        # Test connection
                        result = await asyncio.wait_for(
                            self.connection.fetchval("SELECT version()"),
                            timeout=self._query_timeout
                        )
                        logger.info(f"PostgreSQL version: {result}")
                    except asyncio.TimeoutError:
                        logger.error(f"❌ PostgreSQL connection timed out after {self._connection_timeout} seconds")
                        raise
                else:
                    # Connect to SQLite with timeout
                    db_path = self.database_url.replace('sqlite:///', '')
                    try:
                        self.connection = await asyncio.wait_for(
                            aiosqlite.connect(db_path),
                            timeout=self._connection_timeout
                        )
                        logger.info(f"✅ Connected to SQLite database: {db_path}")
                        
                        # Test connection
                        cursor = await asyncio.wait_for(
                            self.connection.execute("SELECT sqlite_version()"),
                            timeout=self._query_timeout
                        )
                        result = await cursor.fetchone()
                        logger.info(f"SQLite version: {result[0]}")
                    except asyncio.TimeoutError:
                        logger.error(f"❌ SQLite connection timed out after {self._connection_timeout} seconds")
                        raise
            
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
            """
        ]

        for i, table_sql in enumerate(tables, 1):
            try:
                # Execute with timeout
                await asyncio.wait_for(
                    self.connection.execute(table_sql),
                    timeout=self._query_timeout
                )
                table_name = table_sql.split("CREATE TABLE IF NOT EXISTS ")[1].split(" (")[0]
                logger.info(f"✅ Created table {i}/{len(tables)}: {table_name}")
            except asyncio.TimeoutError:
                logger.error(f"❌ Table creation timed out for table {i}")
                raise
            except Exception as e:
                logger.error(f"❌ Failed to create table {i}: {e}")
                raise

        # Create indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id)",
            "CREATE INDEX IF NOT EXISTS idx_admin_roles_guild_id ON admin_roles(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_guild_id ON tickets(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at)",
            "CREATE INDEX IF NOT EXISTS idx_github_channels_guild ON github_channels(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_repos_guild ON github_repos(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_repo_stats_url ON github_repo_stats(repo_url)",
            "CREATE INDEX IF NOT EXISTS idx_log_configs_guild ON log_configs(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_data_lookup ON user_data(user_id, guild_id, data_type)"
        ]

        for index_sql in indexes:
            try:
                # Execute with timeout
                await asyncio.wait_for(
                    self.connection.execute(index_sql),
                    timeout=self._query_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"Index creation timed out: {index_sql}")
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
            
            # Reminders table
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            """
        ]

        for i, table_sql in enumerate(tables, 1):
            try:
                # Execute with timeout
                await asyncio.wait_for(
                    self.connection.execute(table_sql),
                    timeout=self._query_timeout
                )
                table_name = table_sql.split("CREATE TABLE IF NOT EXISTS ")[1].split(" (")[0]
                logger.info(f"✅ Created table {i}/{len(tables)}: {table_name}")
            except asyncio.TimeoutError:
                logger.error(f"❌ Table creation timed out for table {i}")
                raise
            except Exception as e:
                logger.error(f"❌ Failed to create table {i}: {e}")
                raise

        # Commit changes
        try:
            await asyncio.wait_for(
                self.connection.commit(),
                timeout=self._query_timeout
            )
        except asyncio.TimeoutError:
            logger.error("❌ Commit operation timed out")
            raise
        except Exception as e:
            logger.error(f"❌ Failed to commit changes: {e}")
            raise

        # Create indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id)",
            "CREATE INDEX IF NOT EXISTS idx_admin_roles_guild_id ON admin_roles(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_guild_id ON tickets(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at)",
            "CREATE INDEX IF NOT EXISTS idx_github_channels_guild ON github_channels(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_repos_guild ON github_repos(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_github_repo_stats_url ON github_repo_stats(repo_url)",
            "CREATE INDEX IF NOT EXISTS idx_log_configs_guild ON log_configs(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_data_lookup ON user_data(user_id, guild_id, data_type)"
        ]

        for index_sql in indexes:
            try:
                # Execute with timeout
                await asyncio.wait_for(
                    self.connection.execute(index_sql),
                    timeout=self._query_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"Index creation timed out: {index_sql}")
            except Exception as e:
                logger.warning(f"Failed to create index: {e}")
        
        # Commit changes
        try:
            await asyncio.wait_for(
                self.connection.commit(),
                timeout=self._query_timeout
            )
        except asyncio.TimeoutError:
            logger.error("❌ Commit operation timed out")
        except Exception as e:
            logger.error(f"❌ Failed to commit changes: {e}")
    
    async def execute_query(self, query, params=None, fetch_type=None, timeout=None):
        """Execute a database query with proper error handling and timeouts"""
        if timeout is None:
            timeout = self._query_timeout
            
        try:
            if self.is_postgresql:
                if fetch_type == 'one':
                    return await asyncio.wait_for(
                        self.connection.fetchrow(query, *(params or [])),
                        timeout=timeout
                    )
                elif fetch_type == 'all':
                    return await asyncio.wait_for(
                        self.connection.fetch(query, *(params or [])),
                        timeout=timeout
                    )
                elif fetch_type == 'val':
                    return await asyncio.wait_for(
                        self.connection.fetchval(query, *(params or [])),
                        timeout=timeout
                    )
                else:
                    return await asyncio.wait_for(
                        self.connection.execute(query, *(params or [])),
                        timeout=timeout
                    )
            else:
                cursor = await asyncio.wait_for(
                    self.connection.execute(query, params or ()),
                    timeout=timeout
                )
                
                if fetch_type == 'one':
                    row = await cursor.fetchone()
                    if row:
                        columns = [description[0] for description in cursor.description]
                        return dict(zip(columns, row))
                    return None
                elif fetch_type == 'all':
                    rows = await cursor.fetchall()
                    if rows:
                        columns = [description[0] for description in cursor.description]
                        return [dict(zip(columns, row)) for row in rows]
                    return []
                elif fetch_type == 'val':
                    row = await cursor.fetchone()
                    return row[0] if row else None
                else:
                    if query.strip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                        await self.connection.commit()
                    return cursor
                    
        except asyncio.TimeoutError:
            logger.error(f"❌ Database query timed out after {timeout} seconds: {query}")
            raise
        except Exception as e:
            logger.error(f"❌ Database query error: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            raise
    
    async def get_user(self, discord_id: str) -> Optional[Dict[str, Any]]:
        """Get user from database"""
        try:
            query = "SELECT * FROM users WHERE discord_id = ?"
            params = (discord_id,) if not self.is_postgresql else [discord_id]
            
            if self.is_postgresql:
                query = query.replace('?', '$1')
                
            return await self.execute_query(query, params, fetch_type='one')
        except Exception as e:
            logger.error(f"Failed to get user {discord_id}: {e}")
            return None
    
    async def create_user(self, discord_id: str, username: str) -> bool:
        """Create new user in database"""
        try:
            if self.is_postgresql:
                query = "INSERT INTO users (discord_id, username) VALUES ($1, $2) ON CONFLICT (discord_id) DO NOTHING"
                params = [discord_id, username]
            else:
                query = "INSERT OR IGNORE INTO users (discord_id, username) VALUES (?, ?)"
                params = (discord_id, username)
                
            await self.execute_query(query, params)
            return True
        except Exception as e:
            logger.error(f"Failed to create user {discord_id}: {e}")
            return False
    
    async def test_connection(self):
        """Test database connection"""
        try:
            # Test basic query
            if self.is_postgresql:
                result = await self.execute_query("SELECT 1", fetch_type='val')
            else:
                result = await self.execute_query("SELECT 1", fetch_type='val')
                
            # Test users table
            if self.is_postgresql:
                count = await self.execute_query("SELECT COUNT(*) FROM users", fetch_type='val')
            else:
                count = await self.execute_query("SELECT COUNT(*) FROM users", fetch_type='val')
            
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
                if self.is_postgresql:
                    await self.connection.close()
                else:
                    await self.connection.close()
                logger.info("✅ Database connection closed")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}")
