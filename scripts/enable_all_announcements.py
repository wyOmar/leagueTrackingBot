"""
One-time migration: enable match announcements for every linked user in every
server the bot is in.

Background: until this fix, leaving a server deleted the user's guild_members
record, so rejoining silently reset them to opted-out. This script turns the
server master switch ON and marks every linked Riot account as visible for each
linked user who is currently a member of each guild.

Usage (from the project root, or inside the bot container):
    python scripts/enable_all_announcements.py --dry-run   # preview only
    python scripts/enable_all_announcements.py             # apply changes

Uses the Discord REST API only (no gateway connection), so it is safe to run
while the bot is online.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

import aiohttp

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
# Make project imports work and let pydantic-settings find .env when run from anywhere
sys.path.insert(0, ROOT_DIR)
os.chdir(ROOT_DIR)

from config import settings  # noqa: E402
from db.mongo import members_collection, users_collection  # noqa: E402

DISCORD_API_BASE = "https://discord.com/api/v10"


async def discord_get(session: aiohttp.ClientSession, url: str):
    """GET with rate-limit handling. Returns (status, json_or_None)."""
    while True:
        async with session.get(url) as resp:
            if resp.status == 429:
                data = await resp.json()
                retry_after = float(data.get("retry_after", 1.0))
                print(f"  Rate limited, sleeping {retry_after:.2f}s...")
                await asyncio.sleep(retry_after)
                continue
            if resp.status == 200:
                return resp.status, await resp.json()
            return resp.status, None


async def fetch_bot_guilds(session: aiohttp.ClientSession) -> list[dict]:
    """All guilds the bot is currently in (paginated, 200 per page)."""
    guilds: list[dict] = []
    after = "0"
    while True:
        status, page = await discord_get(
            session, f"{DISCORD_API_BASE}/users/@me/guilds?limit=200&after={after}"
        )
        if status != 200:
            raise RuntimeError(f"Failed to list bot guilds (HTTP {status}). Is DISCORD_TOKEN correct?")
        guilds.extend(page)
        if len(page) < 200:
            return guilds
        after = page[-1]["id"]


async def fetch_linked_members(
    session: aiohttp.ClientSession, guild_id: str, candidate_ids: set[str]
) -> set[str] | None:
    """Return which candidate user IDs are members of the guild, or None if inaccessible."""
    found: set[str] = set()
    after = "0"
    while True:
        status, page = await discord_get(
            session, f"{DISCORD_API_BASE}/guilds/{guild_id}/members?limit=1000&after={after}"
        )
        if status != 200:
            # 403 = missing Server Members intent / access; 404 = bot no longer in guild
            print(f"  Could not list members for guild {guild_id} (HTTP {status}); skipping.")
            return None
        for m in page:
            uid = str(m["user"]["id"])
            if uid in candidate_ids:
                found.add(uid)
        if len(page) < 1000:
            return found
        after = page[-1]["user"]["id"]


async def main(dry_run: bool):
    print("Loading linked users from MongoDB...")
    users_by_id: dict[str, list[dict]] = {}
    async for user_doc in users_collection.find({}):
        accounts = user_doc.get("accounts", [])
        if accounts:
            users_by_id[str(user_doc["_id"])] = accounts

    print(f"Found {len(users_by_id)} user(s) with linked Riot accounts.")
    if not users_by_id:
        return

    candidate_ids = set(users_by_id)
    now = datetime.now(timezone.utc)
    updated = 0
    already_ok = 0

    headers = {"Authorization": f"Bot {settings.DISCORD_TOKEN}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        bot_guilds = await fetch_bot_guilds(session)
        print(f"Bot is in {len(bot_guilds)} guild(s).\n")

        for g in bot_guilds:
            guild_id = str(g["id"])
            member_ids = await fetch_linked_members(session, guild_id, candidate_ids)
            if not member_ids:
                continue
            print(f"Guild {g.get('name', '?')} ({guild_id}): {len(member_ids)} linked member(s)")

            for discord_id in sorted(member_ids):
                visibility = {
                    acc["puuid"]: True for acc in users_by_id[discord_id] if acc.get("puuid")
                }
                doc_id = f"{guild_id}_{discord_id}"

                existing = await members_collection.find_one({"_id": doc_id})
                if (
                    existing
                    and existing.get("enabled") is True
                    and all(existing.get("account_visibility", {}).get(p, True) for p in visibility)
                ):
                    already_ok += 1
                    continue

                prev = "missing" if not existing else f"enabled={existing.get('enabled')}"
                print(f"  {'[dry-run] would enable' if dry_run else 'enabling'} {discord_id} ({prev}, {len(visibility)} account(s))")
                updated += 1

                if dry_run:
                    continue

                await members_collection.update_one(
                    {"_id": doc_id},
                    {
                        "$set": {
                            "guild_id": guild_id,
                            "discord_id": discord_id,
                            "enabled": True,
                            "account_visibility": visibility,
                            "updated_at": now,
                        },
                        "$setOnInsert": {"created_at": now},
                    },
                    upsert=True,
                )

    verb = "Would update" if dry_run else "Updated"
    print(f"\nDone. {verb} {updated} record(s); {already_ok} already enabled.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    asyncio.run(main(parser.parse_args().dry_run))
