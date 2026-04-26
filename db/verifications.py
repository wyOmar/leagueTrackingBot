from datetime import datetime, timezone, timedelta
import random
from db.mongo import verifications_collection

async def create_challenge(discord_id: str, puuid: str, region: str, platform: str, game_name: str, tag_line: str):
    # Pick a random basic profile icon (1-28 are usually safe starter icons)
    # Possible future issue where players using 1-28 can have account stolen
    target_icon = random.randint(1, 28)
    
    doc = {
        "_id": f"{discord_id}_{puuid}",
        "discord_id": str(discord_id),
        "puuid": puuid,
        "region": region,
        "platform": platform,
        "game_name": game_name,
        "tag_line": tag_line,
        "target_icon_id": target_icon,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "attempts": 0
    }
    
    await verifications_collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return target_icon

async def get_challenge(discord_id: str):
    # Just grab the most recent pending challenge for this user
    return await verifications_collection.find_one({"discord_id": str(discord_id)})

async def delete_challenge(challenge_id: str):
    await verifications_collection.delete_one({"_id": challenge_id})

async def increment_attempts(challenge_id: str):
    await verifications_collection.update_one(
        {"_id": challenge_id},
        {"$inc": {"attempts": 1}}
    )