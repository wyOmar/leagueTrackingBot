import aiohttp
import asyncio
import os
import json

# Define our directory paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
ASSETS_DIR = os.path.join(ROOT_DIR, "assets", "champion")
CHAMPION_JSON_PATH = os.path.join(ROOT_DIR, "champion.json")

async def update_champions():
    # Ensure the assets directory exists
    os.makedirs(ASSETS_DIR, exist_ok=True)
    
    async with aiohttp.ClientSession() as session:
        # 1. Fetch the latest DataDragon version
        print("Fetching latest DataDragon version...")
        async with session.get("https://ddragon.leagueoflegends.com/api/versions.json") as resp:
            versions = await resp.json()
            latest_version = versions[0]
            print(f"Latest patch detected: {latest_version}")

        # 2. Fetch and save the champion.json file
        print("Fetching champion roster...")
        champ_data_url = f"https://ddragon.leagueoflegends.com/cdn/{latest_version}/data/en_US/champion.json"
        async with session.get(champ_data_url) as resp:
            # Read the raw bytes so we can save it exactly as Riot sends it
            champ_data_bytes = await resp.read()
            
            # Save it to the root directory
            with open(CHAMPION_JSON_PATH, 'wb') as f:
                f.write(champ_data_bytes)
            print("Successfully saved champion.json to root directory.")

            # Parse it to get the list of champions for the image downloads
            champ_data = json.loads(champ_data_bytes)
            champions = champ_data['data'].keys()

        # 3. Check what we already have and download what's missing
        download_count = 0
        for champ in champions:
            file_path = os.path.join(ASSETS_DIR, f"{champ}.png")
            
            # If we already have the image, skip it to save time
            if os.path.exists(file_path):
                continue


            # Construct the direct image URL
            img_url = f"https://ddragon.leagueoflegends.com/cdn/{latest_version}/img/champion/{champ}.png"
            
            print(f"Downloading missing asset: {champ}.png...")
            async with session.get(img_url) as img_resp:
                if img_resp.status == 200:
                    image_bytes = await img_resp.read()
                    with open(file_path, 'wb') as f:
                        f.write(image_bytes)
                    download_count += 1
                else:
                    print(f"Failed to download {champ} (Status: {img_resp.status})")

        print(f"\nUpdate complete! Downloaded {download_count} new champion assets and updated champion.json.")

if __name__ == "__main__":
    asyncio.run(update_champions())