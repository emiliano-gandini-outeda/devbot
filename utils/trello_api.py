import aiohttp
from typing import Optional, Dict, Any, List
from config.settings import Settings

class TrelloAPI:
    def __init__(self, api_key: str = None, token: str = None):
        self.api_key = api_key or Settings.TRELLO_API_KEY
        self.token = token or Settings.TRELLO_TOKEN
        self.base_url = "https://api.trello.com/1"
    
    def _get_auth_params(self) -> Dict[str, str]:
        return {"key": self.api_key, "token": self.token}
    
    async def get_boards(self) -> Optional[List[Dict[str, Any]]]:
        """Get user's Trello boards"""
        url = f"{self.base_url}/members/me/boards"
        params = self._get_auth_params()
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                return None
    
    async def create_card(self, list_id: str, name: str, desc: str = "") -> Optional[Dict[str, Any]]:
        """Create a new card in Trello"""
        url = f"{self.base_url}/cards"
        data = self._get_auth_params()
        data.update({
            "idList": list_id,
            "name": name,
            "desc": desc
        })
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as response:
                if response.status == 200:
                    return await response.json()
                return None
    
    async def get_lists(self, board_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get lists from a Trello board"""
        url = f"{self.base_url}/boards/{board_id}/lists"
        params = self._get_auth_params()
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                return None
