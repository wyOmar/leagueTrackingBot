from datetime import datetime, timezone
from db.mongo import users_collection

async def get_user(discord_id: str):
    return await users_collection.find_one({"_id": str(discord_id)})

async def get_user_by_puuid(puuid: str):
    return await users_collection.find_one({"accounts.puuid": puuid})

async def add_account(discord_id: str, account_data: dict):
    account_data["verified_at"] = datetime.now(timezone.utc)
    result = await users_collection.update_one(
        {"_id": str(discord_id)},
        {
            "$push": {"accounts": account_data},
            "$setOnInsert": {"created_at": datetime.now(timezone.utc)}
        },
        upsert=True
    )
    return result.modified_count > 0 or result.upserted_id is not None

async def update_account_rank(discord_id: int, puuid: str, rank: str, lp: int):
    """Updates the last known rank and LP for a specific account."""
    await users_collection.update_one(
        {"_id": str(discord_id), "accounts.puuid": puuid},
        {"$set": {
            "accounts.$.last_rank": rank, 
            "accounts.$.last_lp": lp
        }}
    )

async def remove_account(discord_id: int, puuid: str):
    """Removes a specific account from a user's linked accounts list using its PUUID."""
    await users_collection.update_one(
        {"_id": str(discord_id)}, # Make sure _id is converted to a string!
        {"$pull": {"accounts": {"puuid": puuid}}}
    )

async def update_account_name(discord_id: int, puuid: str, game_name: str, tag_line: str, display: str):
    """Updates the Riot ID (Name#Tag) for a specific linked account."""
    await users_collection.update_one(
        {"_id": str(discord_id), "accounts.puuid": puuid},
        {"$set": {
            "accounts.$.game_name": game_name,
            "accounts.$.tag_line": tag_line,
            "accounts.$.display": display
        }}
    )