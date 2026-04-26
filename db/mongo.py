from motor.motor_asyncio import AsyncIOMotorClient
from config import settings

# Initialize the async MongoDB client
client = AsyncIOMotorClient(settings.MONGO_URI)
db = client[settings.MONGO_DB_NAME]

# Collections
users_collection = db.users
guilds_collection = db.guild_configs
members_collection = db.guild_members
matches_collection = db.matches
verifications_collection = db.pending_verifications

async def setup_indexes():
    """Create necessary DB indexes on bot startup."""
    await users_collection.create_index("discord_id", unique=True)
    await users_collection.create_index("accounts.puuid")
    await matches_collection.create_index("match_id", unique=True)
    
    # TTL Index for pending verifications (expires after 600 seconds / 10 mins)
    await verifications_collection.create_index("expires_at", expireAfterSeconds=0)