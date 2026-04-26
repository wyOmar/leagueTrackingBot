import discord
from discord.ext import commands
import logging

from db import users, guilds, members
from db.mongo import guilds_collection

logger = logging.getLogger("NameTrackerCog")

class NameTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_league_name_change(self, discord_id: str, puuid: str, old_display: str, new_game_name: str, new_tag_line: str, new_display: str):
        """Listens for name changes dispatched by the dashboard spectator poll."""
        logger.info(f"Name change detected for {discord_id}: {old_display} -> {new_display}")
        
        # 1. Update the database globally
        await users.update_account_name(int(discord_id), puuid, new_game_name, new_tag_line, new_display)

        # 2. Fan out announcements to opted-in servers
        # We only want guilds that have an announcement channel AND have name changes turned on
        query = {
            "announcement_channel_id": {"$ne": None},
            "announce_name_changes": True
        }
        
        async for guild_config in guilds_collection.find(query):
            guild_id = int(guild_config["_id"])
            channel_id = guild_config["announcement_channel_id"]
            
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue
                
            # Check if this user is opted-in for this specific guild
            member_setting = await members.get_settings(guild_id, int(discord_id))
            if not member_setting.get("enabled", False):
                continue
                
            # Check if this specific account is visible
            if not member_setting.get("account_visibility", {}).get(puuid, True):
                continue
                
            # Fetch the Discord user object to ping/display them
            user = self.bot.get_user(int(discord_id))
            user_mention = user.mention if user else f"<@{discord_id}>"

            embed = discord.Embed(
                title="📝 Name Change Detected",
                description=f"{user_mention} has changed their League of Legends name!",
                color=discord.Color.gold()
            )
            embed.add_field(name="Old Name", value=f"~~{old_display}~~", inline=True)
            embed.add_field(name="New Name", value=f"**{new_display}**", inline=True)
            embed.set_footer(text="FeedWatch")

            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                logger.warning(f"NameTracker: Missing permissions to post in channel {channel_id}")

async def setup(bot: commands.Bot):
    await bot.add_cog(NameTracker(bot))