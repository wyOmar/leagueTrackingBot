from datetime import datetime, timezone, timedelta
from db.mongo import matches_collection

async def save_match(match_data: dict, tracked_puuids: list[str]):
    """Save a match globally to avoid duplicate processing."""
    match_data["tracked_puuids"] = tracked_puuids
    match_data["created_at"] = datetime.now(timezone.utc)
    match_id = match_data["metadata"]["matchId"]

    match_data["match_id"] = match_id  
    
    result = await matches_collection.update_one(
        {"_id": match_id},
        {"$set": match_data},
        upsert=True
    )
    return result.upserted_id is not None or result.modified_count > 0
async def get_match(match_id: str):
    return await matches_collection.find_one({"_id": match_id})

async def get_user_matches(puuids: list[str], limit: int = 5):
    """Fetch recent matches involving any of the user's PUUIDs."""
    cursor = matches_collection.find(
        {"tracked_puuids": {"$in": puuids}}
    ).sort("info.gameEndTimestamp", -1).limit(limit)
    return await cursor.to_list(length=limit)

async def get_user_stats(puuids: list[str], queue_id: int = None, days: int = 30):
    """Run an aggregation pipeline to get win rates and KDA over time."""
    cutoff_timestamp = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    
    match_filter = {
        "tracked_puuids": {"$in": puuids},
        "info.gameEndTimestamp": {"$gte": cutoff_timestamp}
    }
    if queue_id is not None:
        match_filter["info.queueId"] = queue_id
        
    pipeline = [
        {"$match": match_filter},
        {"$unwind": "$info.participants"},
        {"$match": {"info.participants.puuid": {"$in": puuids}}},
        {"$group": {
            "_id": None,
            "total_games": {"$sum": 1},
            "wins": {"$sum": {"$cond": ["$info.participants.win", 1, 0]}},
            "kills": {"$sum": "$info.participants.kills"},
            "deaths": {"$sum": "$info.participants.deaths"},
            "assists": {"$sum": "$info.participants.assists"},
        }},
        {"$project": {
            "_id": 0,
            "total_games": 1,
            "wins": 1,
            "losses": {"$subtract": ["$total_games", "$wins"]},
            "win_rate": {"$multiply": [{"$divide": ["$wins", "$total_games"]}, 100]},
            "kda": {"$divide": [{"$add": ["$kills", "$assists"]}, {"$max": ["$deaths", 1]}]},
        }}
    ]
    
    result = await matches_collection.aggregate(pipeline).to_list(length=1)
    return result[0] if result else None