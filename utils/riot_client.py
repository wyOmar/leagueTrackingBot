import aiohttp
import asyncio
import logging
from typing import Optional, Dict, Any
from config import settings, MATCH_REGION_MAP, CLUSTER_MAP, PLATFORM_MAP

logger = logging.getLogger("RiotClient")

class StreamerModeException(Exception):
    """Raised when a player is in a game but has streamer-mode on."""
    pass

class RiotClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RiotClient, cls).__new__(cls)
            cls._instance.session = None
            # Cap concurrent requests to Riot API to prevent sudden spikes
            cls._instance.semaphore = asyncio.Semaphore(20) 
        return cls._instance

    async def init_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession(
                headers={"X-Riot-Token": settings.RIOT_API_KEY}
            )

    async def close(self):
        if self.session:
            await self.session.close()

    async def _request(self, url: str, max_retries: int = 3) -> aiohttp.ClientResponse:
        await self.init_session()
        
        for attempt in range(max_retries):
            async with self.semaphore:
                resp = await self.session.get(url)
                
                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", 1))
                    logger.warning(f"Rate limited (429). Retrying in {retry_after}s...")
                    await asyncio.sleep(retry_after)
                    continue
                
                return resp
        raise Exception(f"Max retries reached for {url}")

    async def get_puuid(self, region: str, game_name: str, tag_line: str) -> str:
        cluster = CLUSTER_MAP.get(region.lower(), "americas")
        url = f"https://{cluster}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
        
        resp = await self._request(url)
        if resp.status == 200:
            data = await resp.json()
            return data["puuid"]
        text = await resp.text()
        raise Exception(f"Failed to get PUUID: {resp.status} - {text}")

    async def check_active_game(self, platform: str, puuid: str, detect_streamer: bool = True) -> Optional[Dict[str, Any]]:
        url = f"https://{platform.lower()}.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}"
        resp = await self._request(url)
        
        if resp.status == 200:
            return await resp.json()
            
        if resp.status == 404:
            if detect_streamer:
                try:
                    err = await resp.json()
                    details = err.get("implementationDetails", "").lower()
                    if "spectator game info player" in details:
                        raise StreamerModeException(details)
                except Exception:
                    pass
            return None
            
        text = await resp.text()
        raise Exception(f"Failed to check active game: {resp.status} - {text}")
    
    async def get_summoner_by_puuid(self, platform: str, puuid: str) -> dict:
        url = f"https://{platform.lower()}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        resp = await self._request(url)
        if resp.status == 200:
            return await resp.json()
        text = await resp.text()
        raise Exception(f"Failed to get summoner: {resp.status} - {text}")
    
    async def get_recent_matches(self, platform: str, puuid: str, count: int = 5) -> list[str]:
        # Riot's match API requires the regional routing cluster (americas, europe, sea, asia)
        match_region = MATCH_REGION_MAP.get(platform.lower(), "americas")
        url = f"https://{match_region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count={count}"
        
        resp = await self._request(url)
        if resp.status == 200:
            return await resp.json()
        raise Exception(f"Failed to get matches: {resp.status} - {await resp.text()}")

    async def get_match(self, platform: str, match_id: str) -> dict:
        match_region = MATCH_REGION_MAP.get(platform.lower(), "americas")
        url = f"https://{match_region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
        
        resp = await self._request(url)
        if resp.status == 200:
            return await resp.json()
        raise Exception(f"Failed to get match: {resp.status} - {await resp.text()}")
    
    async def get_rank(self, platform: str, puuid: str) -> tuple[str, int]:
        """Fetch Ranked Solo/Duo stats for a given PUUID."""
        url = f"https://{platform.lower()}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
        try:
            resp = await self._request(url)
            if resp.status == 200:
                data = await resp.json()
                for entry in data:
                    if entry.get("queueType") == "RANKED_SOLO_5x5":
                        tier = entry.get("tier", "UNRANKED").title()
                        rank = entry.get("rank", "")
                        lp = entry.get("leaguePoints", 0)
                        return f"{tier} {rank}", lp
        except Exception as e:
            logger.warning(f"Failed to fetch rank for {puuid}: {e}")
            
        return "Unranked", 0
riot_client = RiotClient()