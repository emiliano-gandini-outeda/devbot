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
    
    async def init_database(self):
        """Initialize database connection and create tables"""
        if self.is_postgresql:
            # Railway PostgreSQL connection
            try:
                self.connection = await asyncpg.connect(self.database_url)
                logger.info("Connected to Railway PostgreSQL database")
            except Exception as e:
                logger.error(f"Failed to connect to PostgreSQL: {e}")
                raise
        else:
            # Local SQLite fallback
            self.connection = await aiosqlite.connect("bot.db")
            logger.info("Connected to local SQLite database")
        
        await self.create_tables()
    
    async def create_tables(self):
        """Create all necessary database tables"""
        if self.is_postgresql:
            await self._create_postgresql_tables()
        else:
            await self._create_sqlite_tables()
    
    async def _create_postgresql_tables(self):
        """Create tables for PostgreSQL (Railway)"""
        tables = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                discord_id TEXT UNIQUE NOT NULL,
                username TEXT NOT NULL,
                google_token TEXT,
                notion_token TEXT,
                trello_token TEXT,
                preferences JSONB DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS workflows (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                creator_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_data JSONB,
                actions JSONB,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS user_data (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                data_type TEXT NOT NULL,
                data_content JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        ]
        
        for table_sql in tables:
            await self.connection.execute(table_sql)
        
        logger.info("PostgreSQL tables created successfully")
    
    async def _create_sqlite_tables(self):
        """Create tables for SQLite (local development)"""
        tables = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                discord_id TEXT UNIQUE NOT NULL,
                username TEXT NOT NULL,
                google_token TEXT,
                notion_token TEXT,
                trello_token TEXT,
                preferences TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                creator_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_data TEXT,
                actions TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS user_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                data_type TEXT NOT NULL,
                data_content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        ]
        
        for table_sql in tables:
            await self.connection.execute(table_sql)
        
        await self.connection.commit()
        logger.info("SQLite tables created successfully")
    
    async def get_user(self, discord_id: str) -> Optional[Dict[str, Any]]:
        """Get user from database"""
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
    
    async def create_user(self, discord_id: str, username: str) -> bool:
        """Create new user in database"""
        try:
            if self.is_postgresql:
                await self.connection.execute(
                    "INSERT INTO users (discord_id, username) VALUES ($1, $2)",
                    discord_id, username
                )
            else:
                await self.connection.execute(
                    "INSERT INTO users (discord_id, username) VALUES (?, ?)",
                    (discord_id, username)
                )
                await self.connection.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to create user: {e}")
            return False
    
    async def close(self):
        """Close database connection"""
        if self.connection:
            if self.is_postgresql:
                await self.connection.close()
            else:
                await self.connection.close()
            logger.info("Database connection closed")
