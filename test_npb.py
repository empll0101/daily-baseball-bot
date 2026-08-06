import asyncio
import aiohttp
from bs4 import BeautifulSoup

async def main():
    base_url = "https://baseball.yahoo.co.jp"
    timeout = aiohttp.ClientTimeout(total=20)
    headers = {"User-Agent": "TaiwanBaseballTracker/0.1 (personal MVP)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        print("Fetching /npb/")
        async with session.get(f"{base_url}/npb/") as resp:
            print(f"Home status: {resp.status}")
            html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")
            
        paths = {a.get("href") for a in soup.select('a[href*="/npb/game/"][href$="/index"]')}
        print(f"Found {len(paths)} game paths: {paths}")
        
        for path in list(paths)[:2]:
            url = path if path.startswith("http") else f"{base_url}{path}"
            print(f"Fetching game index: {url}")
            async with session.get(url) as resp:
                print(f"  {resp.status} {resp.url}")
            
            game_id = path.split("/")[-2]
            
            url_text = f"{base_url}/npb/game/{game_id}/text"
            print(f"Fetching game text: {url_text}")
            async with session.get(url_text) as resp:
                print(f"  {resp.status} {resp.url}")

            url_stats = f"{base_url}/npb/game/{game_id}/stats"
            print(f"Fetching game stats: {url_stats}")
            async with session.get(url_stats) as resp:
                print(f"  {resp.status} {resp.url}")

if __name__ == "__main__":
    asyncio.run(main())
