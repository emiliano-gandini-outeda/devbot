import os
from typing import Optional

class Settings:
    # Discord Configuration
    DISCORD_TOKEN: str = os.getenv('DISCORD_TOKEN', '')
    PREFIX: str = os.getenv('BOT_PREFIX', '!')
    
    # Database Configuration - Railway provides DATABASE_URL for PostgreSQL
    DATABASE_URL: str = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
    
    # Railway-specific environment
    RAILWAY_ENVIRONMENT: str = os.getenv('RAILWAY_ENVIRONMENT', 'development')
    
    # Google Integration
    GOOGLE_CLIENT_ID: str = os.getenv('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET: str = os.getenv('GOOGLE_CLIENT_SECRET', '')
    GOOGLE_REDIRECT_URI: str = os.getenv('GOOGLE_REDIRECT_URI', '')
    
    # Notion Integration
    NOTION_TOKEN: str = os.getenv('NOTION_TOKEN', '')
    
    # Trello Integration
    TRELLO_API_KEY: str = os.getenv('TRELLO_API_KEY', '')
    TRELLO_TOKEN: str = os.getenv('TRELLO_TOKEN', '')
    
    # OpenAI Configuration
    OPENAI_API_KEY: str = os.getenv('OPENAI_API_KEY', '')
    
    # Redis Configuration (Railway Redis add-on)
    REDIS_URL: str = os.getenv('REDIS_URL', '')
    REDIS_PRIVATE_URL: str = os.getenv('REDIS_PRIVATE_URL', '')
    
    # Application Settings
    DEBUG: bool = os.getenv('DEBUG', 'False').lower() == 'true'
    MAX_REMINDERS_PER_USER: int = int(os.getenv('MAX_REMINDERS_PER_USER', '10'))
    MAX_TICKETS_PER_USER: int = int(os.getenv('MAX_TICKETS_PER_USER', '5'))
    
    @classmethod
    def validate_required_env_vars(cls):
        """Validate that required environment variables are set"""
        required_vars = ['DISCORD_TOKEN']
        missing_vars = []
        
        for var in required_vars:
            if not getattr(cls, var):
                missing_vars.append(var)
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    @classmethod
    def is_railway_production(cls) -> bool:
        """Check if running in Railway production environment"""
        return cls.RAILWAY_ENVIRONMENT == 'production'
    
    @classmethod
    def get_database_url(cls) -> str:
        """Get appropriate database URL for Railway"""
        if cls.DATABASE_URL.startswith('postgresql://'):
            # Railway provides PostgreSQL URLs, ensure they're properly formatted
            return cls.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://')
        return cls.DATABASE_URL
