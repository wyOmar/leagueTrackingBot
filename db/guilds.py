from datetime import datetime, timezone
from db.mongo import guilds_collection

async def get_config(guild_id: int) -> dict:
    """Fetch guild config, returning defaults if not found."""
    config = await guilds_collection.find_one({"_id": str(guild_id)})
    if not config:
        return {
            "_id": str(guild_id),
            "dashboard_channel_id": None,
            "dashboard_message_id": None,
            "announcement_channel_id": None,
            "history_channel_id": None,
            "announced_queue_ids": [420], # Default to Ranked Solo/Duo
            "announce_name_changes": True
        }
    return config

async def update_config(guild_id: int, update_data: dict):
    """Update general config settings."""
    update_data["updated_at"] = datetime.now(timezone.utc)
    await guilds_collection.update_one(
        {"_id": str(guild_id)},
        {
            "$set": update_data,
            "$setOnInsert": {"created_at": datetime.now(timezone.utc)}
        },
        upsert=True
    )

async def add_queue(guild_id: int, queue_id: int):
    """Add a queue ID to the announced list without duplicates."""
    await guilds_collection.update_one(
        {"_id": str(guild_id)},
        {
            "$addToSet": {"announced_queue_ids": queue_id},
            "$set": {"updated_at": datetime.now(timezone.utc)},
            "$setOnInsert": {"created_at": datetime.now(timezone.utc)}
        },
        upsert=True
    )

async def remove_queue(guild_id: int, queue_id: int):
    """Remove a queue ID from the announced list."""
    await guilds_collection.update_one(
        {"_id": str(guild_id)},
        {
            "$pull": {"announced_queue_ids": queue_id},
            "$set": {"updated_at": datetime.now(timezone.utc)}
        }
    )