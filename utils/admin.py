import discord
from discord.ext import commands
from typing import List, Optional
import json

class AdminManager:
    def __init__(self, bot):
        self.bot = bot
        self.admin_roles = {}  # guild_id -> [role_ids]
    
    async def load_admin_roles(self):
        """Load admin roles from database"""
        try:
            if self.bot.db.is_postgresql:
                rows = await self.bot.db.connection.fetch(
                    "SELECT guild_id, data_content FROM user_data WHERE data_type = 'admin_roles'"
                )
                for row in rows:
                    guild_id = row['guild_id']
                    role_ids = row['data_content'].get('role_ids', [])
                    self.admin_roles[guild_id] = role_ids
            else:
                cursor = await self.bot.db.connection.execute(
                    "SELECT guild_id, data_content FROM user_data WHERE data_type = 'admin_roles'"
                )
                rows = await cursor.fetchall()
                for row in rows:
                    guild_id = row[1]
                    role_ids = json.loads(row[2]).get('role_ids', [])
                    self.admin_roles[guild_id] = role_ids
        except Exception as e:
            print(f"Error loading admin roles: {e}")
    
    async def save_admin_roles(self, guild_id: str):
        """Save admin roles to database"""
        try:
            role_ids = self.admin_roles.get(guild_id, [])
            data = {"role_ids": role_ids}
            
            if self.bot.db.is_postgresql:
                await self.bot.db.connection.execute(
                    """INSERT INTO user_data (user_id, data_type, data_content) 
                       VALUES ($1, $2, $3) 
                       ON CONFLICT (user_id, data_type) DO UPDATE SET data_content = $3""",
                    guild_id, 'admin_roles', json.dumps(data)
                )
            else:
                await self.bot.db.connection.execute(
                    """INSERT OR REPLACE INTO user_data (user_id, data_type, data_content) 
                       VALUES (?, ?, ?)""",
                    (guild_id, 'admin_roles', json.dumps(data))
                )
                await self.bot.db.connection.commit()
        except Exception as e:
            print(f"Error saving admin roles: {e}")
    
    def is_admin(self, member: discord.Member) -> bool:
        """Check if member is admin"""
        # Server administrators always have admin access
        if member.guild_permissions.administrator:
            return True
        
        # Check if member has any admin roles
        guild_id = str(member.guild.id)
        admin_role_ids = self.admin_roles.get(guild_id, [])
        
        for role in member.roles:
            if str(role.id) in admin_role_ids:
                return True
        
        return False
    
    async def add_admin_role(self, guild_id: str, role_id: str) -> bool:
        """Add role to admin list"""
        if guild_id not in self.admin_roles:
            self.admin_roles[guild_id] = []
        
        if role_id not in self.admin_roles[guild_id]:
            self.admin_roles[guild_id].append(role_id)
            await self.save_admin_roles(guild_id)
            return True
        return False
    
    async def remove_admin_role(self, guild_id: str, role_id: str) -> bool:
        """Remove role from admin list"""
        if guild_id in self.admin_roles and role_id in self.admin_roles[guild_id]:
            self.admin_roles[guild_id].remove(role_id)
            await self.save_admin_roles(guild_id)
            return True
        return False
    
    def get_admin_roles(self, guild_id: str) -> List[str]:
        """Get list of admin role IDs for guild"""
        return self.admin_roles.get(guild_id, [])
