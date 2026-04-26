import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import logging
from urllib.parse import quote

from utils.riot_client import riot_client
from db.mongo import users_collection, guilds_collection, members_collection
from db import matches as db_matches
from db import users
from config import QUEUE_ID_MAP, PLATFORM_MAP

from utils.image_generator import make_grouped_champion_images
from utils.helpers import format_rank_string

logger = logging.getLogger("MatchesCog")

def parse_mongo_number(val) -> int:
    """Helper to safely parse numbers that might be in MongoDB Extended JSON format."""
    if isinstance(val, dict):
        return int(val.get("$numberLong", val.get("$numberInt", 0)))
    return int(val)

def format_names(names: list[str]) -> str:
    """Formats a list of names with proper English commas and 'and'."""
    if len(names) == 1:
        return names[0]
    elif len(names) == 2:
        return f"{names[0]} and {names[1]}"
    else:
        return ", ".join(names[:-1]) + f", and {names[-1]}"

class Matches(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}
        self.streamer_games = {}
        self.announced_matches = set()
        
        self.match_history_poll.start()

    def cog_unload(self):
        self.match_history_poll.cancel()

    def add_active_game(self, puuid, game_data):
        self.active_games[puuid] = game_data

    def add_streamer_game(self, puuid, game_data):
        self.streamer_games[puuid] = game_data

    @tasks.loop(seconds=45)
    async def match_history_poll(self):
        to_remove_active = []
        
        for puuid, info in list(self.active_games.items()):
            try:
                recent_matches = await riot_client.get_recent_matches(info["platform"], puuid, count=3)
                
                for match_id in recent_matches:
                    if match_id in self.announced_matches:
                        continue
                        
                    match_data = await riot_client.get_match(info["platform"], match_id)
                    
                    if str(match_data["info"]["gameId"]) == str(info["game_id"]):
                        to_remove_active.append(puuid)
                        
                        game_duration = parse_mongo_number(match_data["info"].get("gameDuration", 0))
                        if game_duration < 210:
                            logger.info(f"Match {match_id} was a remake. Skipping announcement.")
                            self.announced_matches.add(match_id)
                            break
                            
                        await self.process_and_announce_match(match_id, match_data)
                        break
                        
            except Exception as e:
                logger.error(f"Error polling match history for {puuid}: {e}")
                
            await asyncio.sleep(0.5) 

        for puuid in to_remove_active:
            self.active_games.pop(puuid, None)

    async def process_and_announce_match(self, match_id: str, match_data: dict):
        self.announced_matches.add(match_id)
        queue_id = match_data["info"]["queueId"]
        tracked_participants = []
        tracked_puuids = []
        
        participants = match_data["info"]["participants"]
        for p in participants:
            puuid = p["puuid"]
            user = await users_collection.find_one({"accounts.puuid": puuid})
            if user:
                tracked_puuids.append(puuid)
                account_info = next(a for a in user["accounts"] if a["puuid"] == puuid)
                tracked_participants.append({
                    "discord_id": user["_id"],
                    "puuid": puuid,
                    "account_info": account_info, 
                    "stats": p
                })

        if not tracked_participants:
            return

        await db_matches.save_match(match_data, tracked_puuids)

        async for guild_config in guilds_collection.find({"announcement_channel_id": {"$ne": None}}):
            guild_id = int(guild_config["_id"])
            channel_id = guild_config["announcement_channel_id"]
            allowed_queues = guild_config.get("announced_queue_ids", [])
            
            if queue_id not in allowed_queues:
                continue
                
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue

            visible_participants = []
            for tp in tracked_participants:
                member_setting = await members_collection.find_one({"_id": f"{guild_id}_{tp['discord_id']}"})
                if not member_setting or not member_setting.get("enabled", False):
                    continue
                if not member_setting.get("account_visibility", {}).get(tp["puuid"], True):
                    continue
                visible_participants.append(tp)

            if visible_participants:
                teams = {}
                for tp in visible_participants:
                    team_id = tp["stats"]["teamId"]
                    teams.setdefault(team_id, []).append(tp)
                
                if len(teams) == 1:
                    team_players = list(teams.values())[0]
                    if len(team_players) == 1:
                        await self.send_solo_announcement(channel, match_id, match_data, team_players[0])
                    else:
                        await self.send_grouped_announcement(channel, match_id, match_data, team_players)
                elif len(teams) == 2:
                    team_a, team_b = list(teams.values())
                    await self.send_showdown_announcement(channel, match_id, match_data, team_a, team_b)

    async def _format_player_stats(self, channel: discord.TextChannel, p: dict, game_info: dict, show_emojis: bool = True) -> tuple[str, str, str, tuple]:
        stats = p["stats"]
        acc_info = p["account_info"]
        discord_id = int(p["discord_id"])

        member = channel.guild.get_member(discord_id)
        if not member:
            try:
                member = await channel.guild.fetch_member(discord_id)
            except (discord.NotFound, discord.HTTPException):
                member = None
        display_name = member.display_name if member else acc_info.get("display", "Summoner")

        champ_name = stats["championName"]
        role = stats.get("individualPosition", "UNKNOWN")
        image_data = (champ_name, role)

        emoji_map = getattr(self.bot, "app_emojis", {})
        
        champ_key = champ_name.replace(" ", "").replace("'", "")
        champ_emoji = emoji_map.get(champ_key, f"*{champ_name}*")
        
        role_emoji_map = {"TOP": "Top_icon", "JUNGLE": "Jungle_icon", "MIDDLE": "Middle_icon", "BOTTOM": "Bottom_icon", "UTILITY": "Support_icon"}
        role_emoji_name = role_emoji_map.get(role, "")
        role_emoji = emoji_map.get(role_emoji_name, "")

        if show_emojis:
            emoji_prefix = f"{champ_emoji} {role_emoji} "
        else:
            emoji_prefix = ""

        kills, deaths, assists = stats["kills"], stats["deaths"], stats["assists"]

        rank_str, lp = await riot_client.get_rank(acc_info["platform"], p["puuid"])
        await users.update_account_rank(p["discord_id"], p["puuid"], rank_str, lp)

        formatted_rank = format_rank_string(rank_str, lp, emoji_map, include_lp_for_non_apex=True)

        region = acc_info.get("region", "na")
        gn = acc_info.get("game_name", "")
        tl = acc_info.get("tag_line", "")
        slug = f"{quote(gn)}-{quote(tl)}" if tl else quote(gn)
        
        riot_name_short = f"{gn}#{tl}"
        opgg_url = f"https://op.gg/summoners/{region}/{slug}"
        riot_name_long = f"[{riot_name_short}]({opgg_url})"

        line_long = (
            f"{emoji_prefix}**{display_name}** {riot_name_long}\n"
            f"└ `{kills}/{deaths}/{assists}` | {formatted_rank}"
        )
        
        line_short = (
            f"{emoji_prefix}**{display_name}** {riot_name_short}\n"
            f"└ `{kills}/{deaths}/{assists}` | {formatted_rank}"
        )
        
        return line_long, line_short, display_name, image_data

    def _get_log_link(self, match_id: str, base_p: dict, is_clash: bool) -> str:
        if is_clash:
            return ""
        try:
            reverse_platform_map = {v: k for k, v in PLATFORM_MAP.items()}
            role_map = {
                (100, "TOP"): 1, (100, "JUNGLE"): 2, (100, "MIDDLE"): 3, (100, "BOTTOM"): 4, (100, "UTILITY"): 5,
                (200, "TOP"): 6, (200, "JUNGLE"): 7, (200, "MIDDLE"): 8, (200, "BOTTOM"): 9, (200, "UTILITY"): 10
            }
            team_val = base_p["stats"].get("teamId")
            position_val = base_p["stats"].get("teamPosition")
            log_participant = role_map.get((team_val, position_val), base_p["stats"].get("participantId", 1))

            platform_part, game_id_part = match_id.split('_')
            log_region = reverse_platform_map.get(platform_part.lower(), platform_part.lower())
            
            log_url = f"https://www.leagueofgraphs.com/match/{log_region}/{game_id_part}#participant{log_participant}"
            return f"[League of Graphs]({log_url})"
        except Exception as e:
            logger.error(f"Failed to generate LoG link for {match_id}: {e}")
            return ""

    async def send_solo_announcement(self, channel: discord.TextChannel, match_id: str, match_data: dict, p: dict):
        game_info = match_data["info"]
        duration_s = parse_mongo_number(game_info.get("gameDuration", 0))
        duration_str = f"{duration_s // 60}m {duration_s % 60}s"
        start_ts = parse_mongo_number(game_info.get("gameStartTimestamp", 0)) // 1000
        is_clash = game_info.get("queueId") == 700

        stats = p["stats"]
        acc_info = p["account_info"]
        discord_id = int(p["discord_id"])

        member = channel.guild.get_member(discord_id)
        if not member:
            try:
                member = await channel.guild.fetch_member(discord_id)
            except (discord.NotFound, discord.HTTPException):
                member = None
        display_name = member.display_name if member else acc_info.get("display", "Summoner")
        
        team_id = stats["teamId"]
        team_members = [player for player in game_info["participants"] if player["teamId"] == team_id]
        team_kills = sum(player["kills"] for player in team_members)
        
        kills, deaths, assists = stats["kills"], stats["deaths"], stats["assists"]
        kp = ((kills + assists) / max(1, team_kills)) * 100 if team_kills > 0 else 0.0
        
        win = stats["win"]

        emoji_map = getattr(self.bot, "app_emojis", {})
        
        rank_str, lp = await riot_client.get_rank(acc_info["platform"], p["puuid"])
        await users.update_account_rank(p["discord_id"], p["puuid"], rank_str, lp)

        formatted_rank = format_rank_string(rank_str, lp, emoji_map, include_lp_for_non_apex=True)

        region = acc_info.get("region", "na")
        gn = acc_info.get("game_name", "")
        tl = acc_info.get("tag_line", "")
        slug = f"{quote(gn)}-{quote(tl)}" if tl else quote(gn)
        
        riot_name_short = f"{gn}#{tl}"
        opgg_url = f"https://op.gg/summoners/{region}/{slug}"
        log_link_md = self._get_log_link(match_id, p, is_clash)

        if is_clash:
            title = f"{display_name} has just {'won 🎉' if win else 'lost 😢'} in Clash!"
        else:
            title = f"{display_name} has just {'won 🎉' if win else 'lost 😢'}!"
            
        color = discord.Color.green() if win else discord.Color.red()

        desc = (
            f"**KDA:** `{kills}/{deaths}/{assists}`  |  **KP:** `{kp:.1f}%`\n"
            f"**Rank:** {formatted_rank}\n"
            f"**Duration:** {duration_str}\n"
            f"**Started:** <t:{start_ts}:R>\n"
        )
        
        embed = discord.Embed(title=title, description=desc, color=color)
        
        links_value = f"[{riot_name_short}]({opgg_url})"
        if log_link_md:
            links_value += f" • {log_link_md}"
            
        embed.add_field(name="", value=links_value, inline=False)
        
        champ_name = stats["championName"]
        role = stats.get("individualPosition", "UNKNOWN")
        
        img_bytes = await asyncio.to_thread(make_grouped_champion_images, [(champ_name, role)])
        file = discord.File(img_bytes, filename="grouped_champs.png")
        embed.set_thumbnail(url="attachment://grouped_champs.png")
        
        await channel.send(embed=embed, file=file)

    async def send_grouped_announcement(self, channel: discord.TextChannel, match_id: str, match_data: dict, participants: list):
        game_info = match_data["info"]
        
        duration_s = parse_mongo_number(game_info.get("gameDuration", 0))
        duration_str = f"{duration_s // 60}m {duration_s % 60}s"
        start_ts = parse_mongo_number(game_info.get("gameStartTimestamp", 0)) // 1000
        is_clash = game_info.get("queueId") == 700

        player_lines_long, player_lines_short, image_data, display_names = [], [], [], []
        win = participants[0]["stats"]["win"]

        for p in participants:
            l_long, l_short, name, img_tuple = await self._format_player_stats(channel, p, game_info, show_emojis=False)
            player_lines_long.append(l_long)
            player_lines_short.append(l_short)
            display_names.append(name)
            image_data.append(img_tuple)

        title_names = format_names(display_names)
        if is_clash:
            title = f"{title_names} have just {'won 🎉' if win else 'lost'} in Clash!"
        else:
            title = f"{title_names} {'has' if len(display_names)==1 else 'have'} just {'won 🎉' if win else 'lost'}!"
            
        color = discord.Color.green() if win else discord.Color.red()
        log_link_md = self._get_log_link(match_id, participants[0], is_clash)

        embed = discord.Embed(title=title, color=color)
        
        desc = "\n".join(player_lines_long)
        if len(desc) > 4096:
            desc = "\n".join(player_lines_short)
        embed.description = desc
        
        footer_val = f"**Duration:** {duration_str}\n**Started:** <t:{start_ts}:R>"
        if log_link_md: footer_val += f"\n{log_link_md}"
        embed.add_field(name="", value=footer_val, inline=False)
        
        img_bytes = await asyncio.to_thread(make_grouped_champion_images, image_data)
        file = discord.File(img_bytes, filename="grouped_champs.png")
        embed.set_thumbnail(url="attachment://grouped_champs.png")
        
        await channel.send(embed=embed, file=file)

    async def send_showdown_announcement(self, channel: discord.TextChannel, match_id: str, match_data: dict, team_a: list, team_b: list):
        game_info = match_data["info"]
        
        duration_s = parse_mongo_number(game_info.get("gameDuration", 0))
        duration_str = f"{duration_s // 60}m {duration_s % 60}s"
        start_ts = parse_mongo_number(game_info.get("gameStartTimestamp", 0)) // 1000
        is_clash = game_info.get("queueId") == 700

        win_team = team_a if team_a[0]["stats"]["win"] else team_b
        lose_team = team_b if team_a[0]["stats"]["win"] else team_a

        win_lines_long, win_lines_short = [], []
        lose_lines_long, lose_lines_short = [], []
        win_names, lose_names = [], []
        winner_images = []

        for p in win_team:
            l_long, l_short, name, img_tuple = await self._format_player_stats(channel, p, game_info, show_emojis=True)
            win_lines_long.append(l_long)
            win_lines_short.append(l_short)
            win_names.append(name)
            winner_images.append(img_tuple)

        for p in lose_team:
            l_long, l_short, name, _ = await self._format_player_stats(channel, p, game_info, show_emojis=True)
            lose_lines_long.append(l_long)
            lose_lines_short.append(l_short)
            lose_names.append(name)

        win_str = format_names(win_names)
        lose_str = format_names(lose_names)
        verb = "has" if len(win_names) == 1 else "have"
        
        if is_clash:
            title = f"{win_str} {verb} just beat {lose_str} in Clash!"
        else:
            title = f"{win_str} {verb} just beat {lose_str}!"

        embed = discord.Embed(title=title, color=discord.Color.gold())
        
        win_val = "\n".join(win_lines_long)
        if len(win_val) > 1024:
            win_val = "\n".join(win_lines_short)
            
        lose_val = "\n".join(lose_lines_long)
        if len(lose_val) > 1024:
            lose_val = "\n".join(lose_lines_short)
        
        embed.add_field(name="🏆 Winners", value=win_val, inline=False)
        embed.add_field(name="💀 Losers", value=lose_val, inline=False)

        log_link_md = self._get_log_link(match_id, win_team[0], is_clash)
        footer_val = f"**Duration:** {duration_str}\n**Started:** <t:{start_ts}:R>"
        if log_link_md: footer_val += f"\n{log_link_md}"
        embed.add_field(name="", value=footer_val, inline=False)

        img_bytes = await asyncio.to_thread(make_grouped_champion_images, winner_images)
        file = discord.File(img_bytes, filename="grouped_champs.png")
        embed.set_thumbnail(url="attachment://grouped_champs.png")
        
        await channel.send(embed=embed, file=file)

    @match_history_poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Matches(bot))