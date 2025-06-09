import asyncio
import aiosqlite
import asyncpg
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from config.settings import Settings
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.database_url = Settings.get_database_url()
        self.connection = None
        self.is_postgresql = self.database_url.startswith('postgresql')
        
        logger.info(f"Database type: {'PostgreSQL' if self.is_postgresql else 'SQLite'}")
        logger.info(f"Database URL: {self.database_url[:50]}...")  # Log partial URL for debugging
    
    async def init_database(self):
        """Initialize database connection and create tables"""
        if self.is_postgresql:
            # Railway PostgreSQL connection
            try:
                # Use the direct URL for Railway
                connection_url = "postgresql://postgres:QQCQuMDiLYyUhMLffEyUxizpDyYMxNxf@postgres.railway.internal:5432/railway"
                self.connection = await asyncpg.connect(connection_url)
                logger.info("✅ Connected to Railway PostgreSQL database")
                
                # Test the connection
                result = await self.connection.fetchval("SELECT version()")
                logger.info(f"PostgreSQL version: {result}")
                
            except Exception as e:
                logger.error(f"❌ Failed to connect to PostgreSQL: {e}")
                logger.info("Falling back to SQLite...")
                self.is_postgresql = False
                self.connection = await aiosqlite.connect("bot.db")
                logger.info("✅ Connected to local SQLite database")
        else:
            # Local SQLite fallback
            self.connection = await aiosqlite.connect("bot.db")
            logger.info("✅ Connected to local SQLite database")
        
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
        """Create tables for PostgreSQL (Railway)"""
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
                recurring TEXT,
                is_sent BOOLEAN DEFAULT FALSE,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            
            # Ticket configs table
            """
            CREATE TABLE IF NOT EXISTS ticket_configs (
                id SERIAL PRIMARY KEY,
                guild_id TEXT UNIQUE NOT NULL,
                category_id TEXT,
                support_role_id TEXT,
                log_channel_id TEXT,
                auto_close_hours INTEGER DEFAULT 72,
                max_tickets_per_user INTEGER DEFAULT 3,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # Log configs table
            """
            CREATE TABLE IF NOT EXISTS log_configs (
                id SERIAL PRIMARY KEY,
                guild_id TEXT UNIQUE NOT NULL,
                log_channel_id TEXT,
                log_types JSONB DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            """
        ]
        
        for i, table_sql in enumerate(tables, 1):
            try:
                await self.connection.execute(table_sql)
                table_name = table_sql.split("CREATE TABLE IF NOT EXISTS ")[1].split(" (")[0]
                logger.info(f"✅ Created PostgreSQL table {i}/{len(tables)}: {table_name}")
            except Exception as e:
                logger.error(f"❌ Failed to create table {i}: {e}")
                raise
        
        # Create indexes for better performance
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_guild_id ON tickets(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_reminders_user_id ON reminders(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at)",
            "CREATE INDEX IF NOT EXISTS idx_workflows_guild_id ON workflows(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_admin_roles_guild_id ON admin_roles(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_meetings_guild_id ON meetings(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id)"
        ]
        
        for index_sql in indexes:
            try:
                await self.connection.execute(index_sql)
            except Exception as e:
                logger.warning(f"Failed to create index: {e}")
        
        logger.info("✅ PostgreSQL tables and indexes created successfully")
    
    async def _create_sqlite_tables(self):
        """Create tables for SQLite (local development)"""
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
                recurring TEXT,
                is_sent INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # Workflows table
            """
            CREATE TABLE IF NOT EXISTS workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                creator_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_data TEXT DEFAULT '{}',
                actions TEXT DEFAULT '[]',
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # User data table
            """
            CREATE TABLE IF NOT EXISTS user_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                guild_id TEXT,
                data_type TEXT NOT NULL,
                data_content TEXT DEFAULT '{}',
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
            
            # Ticket configs table
            """
            CREATE TABLE IF NOT EXISTS ticket_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT UNIQUE NOT NULL,
                category_id TEXT,
                support_role_id TEXT,
                log_channel_id TEXT,
                auto_close_hours INTEGER DEFAULT 72,
                max_tickets_per_user INTEGER DEFAULT 3,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # Log configs table
            """
            CREATE TABLE IF NOT EXISTS log_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT UNIQUE NOT NULL,
                log_channel_id TEXT,
                log_types TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # Meetings table
            """
            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_id TEXT UNIQUE NOT NULL,
                guild_id TEXT NOT NULL,
                creator_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                scheduled_time TIMESTAMP NOT NULL,
                duration_minutes INTEGER DEFAULT 60,
                attendees TEXT DEFAULT '[]',
                status TEXT DEFAULT 'scheduled',
                meeting_link TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # Notifications table
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                guild_id TEXT,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        ]
        
        for i, table_sql in enumerate(tables, 1):
            try:
                await self.connection.execute(table_sql)
                table_name = table_sql.split("CREATE TABLE IF NOT EXISTS ")[1].split(" (")[0]
                logger.info(f"✅ Created SQLite table {i}/{len(tables)}: {table_name}")
            except Exception as e:
                logger.error(f"❌ Failed to create table {i}: {e}")
                raise
        
        await self.connection.commit()
        logger.info("✅ SQLite tables created successfully")
    
    async def verify_tables(self):
        """Verify that all required tables exist"""
        required_tables = [
            'users', 'tickets', 'reminders', 'workflows', 'user_data',
            'admin_roles', 'ticket_configs', 'log_configs', 'meetings', 'notifications'
        ]
        
        existing_tables = []
        
        try:
            if self.is_postgresql:
                result = await self.connection.fetch(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
                existing_tables = [row['table_name'] for row in result]
            else:
                cursor = await self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
                rows = await cursor.fetchall()
                existing_tables = [row[0] for row in rows]
            
            missing_tables = [table for table in required_tables if table not in existing_tables]
            
            if missing_tables:
                logger.warning(f"⚠️ Missing tables: {', '.join(missing_tables)}")
                return False
            else:
                logger.info(f"✅ All {len(required_tables)} required tables exist")
                logger.info(f"Existing tables: {', '.join(sorted(existing_tables))}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to verify tables: {e}")
            return False
    
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
        """Test database connection and basic operations"""
        try:
            if self.is_postgresql:
                # Test PostgreSQL connection
                result = await self.connection.fetchval("SELECT 1")
                logger.info(f"✅ PostgreSQL connection test successful: {result}")
                
                # Test table access
                count = await self.connection.fetchval("SELECT COUNT(*) FROM users")
                logger.info(f"✅ Users table accessible, contains {count} records")
                
            else:
                # Test SQLite connection
                cursor = await self.connection.execute("SELECT 1")
                result = await cursor.fetchone()
                logger.info(f"✅ SQLite connection test successful: {result[0]}")
                
                # Test table access
                cursor = await self.connection.execute("SELECT COUNT(*) FROM users")
                result = await cursor.fetchone()
                logger.info(f"✅ Users table accessible, contains {result[0]} records")
            
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
