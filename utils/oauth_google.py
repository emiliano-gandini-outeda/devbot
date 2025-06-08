import aiohttp
import json
from typing import Optional, Dict, Any
from config.settings import Settings

class GoogleOAuthManager:
    def __init__(self):
        self.client_id = Settings.GOOGLE_CLIENT_ID
        self.client_secret = Settings.GOOGLE_CLIENT_SECRET
        self.redirect_uri = Settings.GOOGLE_REDIRECT_URI
        self.scope = "https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/drive"
    
    def get_auth_url(self, state: str) -> str:
        """Generate Google OAuth authorization URL"""
        base_url = "https://accounts.google.com/o/oauth2/v2/auth"
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scope,
            "response_type": "code",
            "access_type": "offline",
            "state": state
        }
        
        param_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{base_url}?{param_string}"
    
    async def exchange_code_for_token(self, code: str) -> Optional[Dict[str, Any]]:
        """Exchange authorization code for access token"""
        url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as response:
                if response.status == 200:
                    return await response.json()
                return None
    
    async def refresh_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """Refresh access token using refresh token"""
        url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as response:
                if response.status == 200:
                    return await response.json()
                return None
    
    async def get_calendar_events(self, access_token: str, max_results: int = 10) -> Optional[List[Dict]]:
        """Get upcoming calendar events"""
        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {
            "maxResults": max_results,
            "orderBy": "startTime",
            "singleEvents": True,
            "timeMin": "2024-01-01T00:00:00Z"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("items", [])
                return None
