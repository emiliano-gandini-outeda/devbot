import os
from typing import Optional

class Settings:
    """Application settings loaded from environment variables"""
    
    # Discord Bot Settings
    DISCORD_TOKEN: str = os.getenv('DISCORD_TOKEN', '')
    PREFIX: str = os.getenv('BOT_PREFIX', '!')
    
    # Database Settings
    DATABASE_URL: str = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
    
    # Google Integration Settings
    GOOGLE_CLIENT_ID: Optional[str] = os.getenv('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET: Optional[str] = os.getenv('GOOGLE_CLIENT_SECRET')
    GOOGLE_REDIRECT_URI: Optional[str] = os.getenv('GOOGLE_REDIRECT_URI')
    
    # Notion Integration Settings
    NOTION_CLIENT_ID: Optional[str] = os.getenv('NOTION_CLIENT_ID')
    NOTION_CLIENT_SECRET: Optional[str] = os.getenv('NOTION_CLIENT_SECRET')
    NOTION_REDIRECT_URI: Optional[str] = os.getenv('NOTION_REDIRECT_URI')
    
    # Trello Integration Settings
    TRELLO_API_KEY: Optional[str] = os.getenv('TRELLO_API_KEY')
    TRELLO_API_SECRET: Optional[str] = os.getenv('TRELLO_API_SECRET')
    
    # GitHub Integration Settings
    GITHUB_TOKEN: Optional[str] = os.getenv('GITHUB_TOKEN')
    
    # OpenAI Settings
    OPENAI_API_KEY: Optional[str] = os.getenv('OPENAI_API_KEY')
    
    # Bot Configuration
    MAX_REMINDERS_PER_USER: int = int(os.getenv('MAX_REMINDERS_PER_USER', '10'))
    MAX_WORKFLOWS_PER_GUILD: int = int(os.getenv('MAX_WORKFLOWS_PER_GUILD', '20'))
    
    # Logging Settings
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE: str = os.getenv('LOG_FILE', 'bot.log')
    
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
    def get_database_config(cls) -> dict:
        """Get database configuration"""
        return {
            'url': cls.DATABASE_URL,
            'is_postgresql': cls.DATABASE_URL.startswith('postgresql')
        }
    
    @classmethod
    def get_google_config(cls) -> dict:
        """Get Google integration configuration"""
        return {
            'client_id': cls.GOOGLE_CLIENT_ID,
            'client_secret': cls.GOOGLE_CLIENT_SECRET,
            'redirect_uri': cls.GOOGLE_REDIRECT_URI,
            'enabled': all([cls.GOOGLE_CLIENT_ID, cls.GOOGLE_CLIENT_SECRET, cls.GOOGLE_REDIRECT_URI])
        }
    
    @classmethod
    def get_notion_config(cls) -> dict:
        """Get Notion integration configuration"""
        return {
            'client_id': cls.NOTION_CLIENT_ID,
            'client_secret': cls.NOTION_CLIENT_SECRET,
            'redirect_uri': cls.NOTION_REDIRECT_URI,
            'enabled': all([cls.NOTION_CLIENT_ID, cls.NOTION_CLIENT_SECRET, cls.NOTION_REDIRECT_URI])
        }
    
    @classmethod
    def get_trello_config(cls) -> dict:
        """Get Trello integration configuration"""
        return {
            'api_key': cls.TRELLO_API_KEY,
            'api_secret': cls.TRELLO_API_SECRET,
            'enabled': all([cls.TRELLO_API_KEY, cls.TRELLO_API_SECRET])
        }
    
    @classmethod
    def get_github_config(cls) -> dict:
        """Get GitHub integration configuration"""
        return {
            'token': cls.GITHUB_TOKEN,
            'enabled': bool(cls.GITHUB_TOKEN)
        }
    
    @classmethod
    def get_openai_config(cls) -> dict:
        """Get OpenAI configuration"""
        return {
            'api_key': cls.OPENAI_API_KEY,
            'enabled': bool(cls.OPENAI_API_KEY)
        }
