from datetime import datetime, timezone
from db.mongo import members_collection

async def get_settings(guild_id: int, discord_id: int) -> dict:
    """Fetch user settings for a specific guild, defaulting to disabled."""
    doc_id = f"{guild_id}_{discord_id}"
    config = await members_collection.find_one({"_id": doc_id})
    if not config:
        return {
            "_id": doc_id,
            "guild_id": str(guild_id),
            "discord_id": str(discord_id),
            "enabled": False,           # Default: Opted OUT
            "account_visibility": {}    # Missing keys imply 'True' if 'enabled' is True
        }
    return config

async def set_global_toggle(guild_id: int, discord_id: int, enabled: bool):
    """Toggle a user's master visibility switch for this guild."""
    doc_id = f"{guild_id}_{discord_id}"
    await members_collection.update_one(
        {"_id": doc_id},
        {
            "$set": {
                "guild_id": str(guild_id),
                "discord_id": str(discord_id),
                "enabled": enabled,
                "updated_at": datetime.now(timezone.utc)
            },
            "$setOnInsert": {"created_at": datetime.now(timezone.utc), "account_visibility": {}}
        },
        upsert=True
    )

async def set_account_toggle(guild_id: int, discord_id: int, puuid: str, enabled: bool):
    """Toggle visibility for a specific account in this guild."""
    doc_id = f"{guild_id}_{discord_id}"
    await members_collection.update_one(
        {"_id": doc_id},
        {
            "$set": {
                "guild_id": str(guild_id),
                "discord_id": str(discord_id),
                f"account_visibility.{puuid}": enabled,
                "updated_at": datetime.now(timezone.utc)
            },
            "$setOnInsert": {"created_at": datetime.now(timezone.utc), "enabled": False}
        },
        upsert=True
    )

async def remove_member(guild_id: int, discord_id: int):
    """Deletes a user's local server settings when they leave the guild."""
    doc_id = f"{guild_id}_{discord_id}"
    await members_collection.delete_one({"_id": doc_id})