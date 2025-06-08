import aiohttp
import json
from typing import Optional, Dict, Any, List
from config.settings import Settings

class NotionAPI:
    def __init__(self, token: str = None):
        self.token = token or Settings.NOTION_TOKEN
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }
    
    async def create_page(self, parent_id: str, title: str, content: str = "") -> Optional[Dict[str, Any]]:
        """Create a new page in Notion"""
        url = f"{self.base_url}/pages"
        data = {
            "parent": {"database_id": parent_id},
            "properties": {
                "title": {
                    "title": [
                        {
                            "text": {
                                "content": title
                            }
                        }
                    ]
                }
            },
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": content
                                }
                            }
                        ]
                    }
                }
            ] if content else []
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, json=data) as response:
                if response.status == 200:
                    return await response.json()
                return None
    
    async def get_databases(self) -> Optional[List[Dict[str, Any]]]:
        """Get list of databases"""
        url = f"{self.base_url}/search"
        data = {
            "filter": {
                "value": "database",
                "property": "object"
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("results", [])
                return None
