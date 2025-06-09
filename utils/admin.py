import discord
from typing import List, Set
import logging

logger = logging.getLogger(__name__)

class AdminManager:
    def __init__(self, bot):
        self.bot = bot
        self.admin_roles: dict = {}  # guild_id -> set of role_ids
    
    async def load_admin_roles(self):
        """Load admin roles from database"""
        try:
            rows = await self.bot.db.connection.fetch("SELECT * FROM admin_roles")
            
            for row in rows:
                guild_id = row['guild_id']
                role_id = row['role_id']
                
                if guild_id not in self.admin_roles:
                    self.admin_roles[guild_id] = set()
                
                self.admin_roles[guild_id].add(role_id)
            
            logger.info(f"✅ Loaded admin roles for {len(self.admin_roles)} guilds")
            
        except Exception as e:
            logger.error(f"Failed to load admin roles: {e}")
    
    async def add_admin_role(self, guild_id: str, role_id: str) -> bool:
        """Add a role to admin list"""
        try:
            await self.bot.db.connection.execute(
                "INSERT INTO admin_roles (guild_id, role_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                guild_id, role_id
            )
            
            if guild_id not in self.admin_roles:
                self.admin_roles[guild_id] = set()
            
            self.admin_roles[guild_id].add(role_id)
            return True
            
        except Exception as e:
            logger.error(f"Failed to add admin role: {e}")
            return False
    
    async def remove_admin_role(self, guild_id: str, role_id: str) -> bool:
        """Remove a role from admin list"""
        try:
            result = await self.bot.db.connection.execute(
                "DELETE FROM admin_roles WHERE guild_id = $1 AND role_id = $2",
                guild_id, role_id
            )
            
            if guild_id in self.admin_roles:
                self.admin_roles[guild_id].discard(role_id)
            
            return "DELETE 1" in str(result)
            
        except Exception as e:
            logger.error(f"Failed to remove admin role: {e}")
            return False
    
    def get_admin_roles(self, guild_id: str) -> Set[str]:
        """Get admin roles for a guild"""
        return self.admin_roles.get(guild_id, set())
    
    def is_admin(self, user: discord.Member) -> bool:
        """Check if user is an admin"""
        # Server administrators are always admins
        if user.guild_permissions.administrator:
            return True
        
        # Check if user has any admin roles
        guild_id = str(user.guild.id)
        admin_role_ids = self.get_admin_roles(guild_id)
        
        user_role_ids = {str(role.id) for role in user.roles}
        
        return bool(admin_role_ids.intersection(user_role_ids))
