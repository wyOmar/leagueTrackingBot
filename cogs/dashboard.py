import discord
from discord.ext import commands, tasks
import asyncio
import logging
from datetime import datetime, timezone
import json
import urllib.parse

from db.guilds import update_config 
from utils.riot_client import riot_client, StreamerModeException
from db.mongo import users_collection, guilds_collection, members_collection
from config import QUEUE_ID_MAP, PLATFORM_MAP
from utils.helpers import get_rank_value, format_rank_string

logger = logging.getLogger("DashboardCog")

class Dashboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {} 
        self.streamer_mode_games = {} 
        self.champion_data = self.load_champion_data()
        
        self.spectator_poll.start()

    def cog_unload(self):
        self.spectator_poll.cancel()

    def load_champion_data(self):
        try:
            with open("champion.json", "r", encoding="utf-8") as f:
                champ_data = json.load(f)
            return {
                int(v["key"]): {"name": v["name"], "id": v["id"]} 
                for v in champ_data["data"].values()
            }
        except Exception as e:
            logger.warning(f"Could not load champion.json. Error: {e}")
            return {}

    async def check_single_account(self, puuid: str, info: dict) -> tuple[str, str, dict]:
        """Worker function to check a single account concurrently."""
        platform = info["platform"]
        try:
            game_data = await riot_client.check_active_game(platform, puuid, detect_streamer=True)
            if game_data is None:
                return "none", puuid, {}
                
            participant = next((p for p in game_data["participants"] if p.get("puuid") == puuid), None)
            if not participant:
                return "none", puuid, {}
                
            # --- NAME CHANGE DETECTION ---
            new_game_name = participant.get("riotIdGameName")
            new_tag_line = participant.get("riotIdTagline")
            
            if new_game_name and new_tag_line:
                new_display = f"{new_game_name}#{new_tag_line}"
                old_display = info.get("display")
                
                # If we have a valid old name, and it differs from the new one, trigger the event
                if old_display and old_display != "Unknown#" and old_display != new_display:
                    self.bot.dispatch(
                        "league_name_change", 
                        info["discord_id"], 
                        puuid, 
                        old_display, 
                        new_game_name, 
                        new_tag_line, 
                        new_display
                    )
                    info["display"] = new_display 
                
            champ_info = self.champion_data.get(participant["championId"], {"name": "Unknown", "id": "Unknown"})
            
            active_data = {
                "discord_id": info["discord_id"],
                "display": info["display"],
                "last_rank": info["last_rank"],
                "last_lp": info["last_lp"],
                "game_id": game_data["gameId"],
                "champion_name": champ_info["name"], 
                "champion_id": champ_info["id"],
                "platform": platform,
                "queue_id": game_data["gameQueueConfigId"],
                "start_time": game_data["gameStartTime"],
                "raw_data": game_data 
            }
            return "active", puuid, active_data
        except StreamerModeException:
            streamer_data = {
                "discord_id": info["discord_id"],
                "display": info["display"],
                "platform": platform,
                "start_time": int(datetime.now(timezone.utc).timestamp() * 1000)
            }
            return "streamer", puuid, streamer_data
        except Exception as e:
            logger.error(f"Failed to check active game for {puuid}: {e}")
            return "error", puuid, {}

    @tasks.loop(minutes=2)
    async def spectator_poll(self):
        logger.info("Running scalable spectator heartbeat...")
        
        all_accounts = {}
        async for user in users_collection.find({}):
            discord_id = user["_id"]
            for acc in user.get("accounts", []):
                puuid = acc.get("puuid")
                if puuid:
                    all_accounts[puuid] = {
                        "discord_id": discord_id,
                        "platform": acc.get("platform"),
                        "display": acc.get("display"),
                        "last_rank": acc.get("last_rank", "Unranked"),
                        "last_lp": acc.get("last_lp", 0)
                    }

        new_active_games = {}
        
        tasks_list = [self.check_single_account(puuid, info) for puuid, info in all_accounts.items()]
        
        chunk_size = 20
        matches_cog = self.bot.get_cog("Matches")
        
        for i in range(0, len(tasks_list), chunk_size):
            chunk = tasks_list[i:i + chunk_size]
            results = await asyncio.gather(*chunk)
            
            for status, puuid, data in results:
                if status == "active":
                    new_active_games[puuid] = data
                    if matches_cog:
                        matches_cog.add_active_game(puuid, data)
                elif status == "streamer":
                    if puuid not in self.streamer_mode_games:
                        self.streamer_mode_games[puuid] = data
                        if matches_cog:
                            matches_cog.add_streamer_game(puuid, data)
                            
            await asyncio.sleep(0.5)

        self.active_games = new_active_games
        await self.update_all_dashboards()

    async def update_all_dashboards(self):
        async for guild_config in guilds_collection.find({"dashboard_channel_id": {"$ne": None}}):
            guild_id = int(guild_config["_id"])
            channel_id = guild_config["dashboard_channel_id"]
            dashboard_message_id = guild_config.get("dashboard_message_id")
            
            channel = self.bot.get_channel(channel_id)
            if not channel: continue

            visible_games = []
            visible_streamers = []
            
            for puuid, game in self.active_games.items():
                member_setting = await members_collection.find_one({"_id": f"{guild_id}_{game['discord_id']}"})
                if member_setting and member_setting.get("enabled", False) and member_setting.get("account_visibility", {}).get(puuid, True):
                    visible_games.append(game)

            for puuid, streamer in self.streamer_mode_games.items():
                member_setting = await members_collection.find_one({"_id": f"{guild_id}_{streamer['discord_id']}"})
                if member_setting and member_setting.get("enabled", False) and member_setting.get("account_visibility", {}).get(puuid, True):
                    visible_streamers.append(streamer)

            await self.send_or_update_dashboard(guild_id, channel, dashboard_message_id, visible_games, visible_streamers)

    async def send_or_update_dashboard(self, guild_id, channel, dashboard_message_id, games, streamers):
        emoji_map = getattr(self.bot, "app_emojis", {})
        
        marker = "**Active Games**"
        now_unix = int(datetime.now(timezone.utc).timestamp())
        footer = f"\n\n**Last Updated:** <t:{now_unix}:R>"
        
        MAX_DESC_LENGTH = 3900 
        
        if not games and not streamers:
            description = f"_No tracked accounts are currently in a game._{footer}"
        else:
            reverse_platform_map = {v: k for k, v in PLATFORM_MAP.items()}
            
            grouped_games_dict = {}
            for g in games:
                grouped_games_dict.setdefault(g["game_id"], []).append(g)
                
            def get_queue_priority(players):
                qid = players[0].get("queue_id")
                if qid == 420: return 1
                if qid == 440: return 2
                if qid in (400, 430, 408): return 3
                if qid == 450: return 4
                return 5
                
            sorted_games = sorted(grouped_games_dict.values(), key=get_queue_priority)
            
            current_desc = ""
            omitted_count = 0
            
            for players in sorted_games:
                queue_id = players[0]["queue_id"]
                start_ms = players[0]["start_time"]
                queue_str = QUEUE_ID_MAP.get(queue_id, f"Queue {queue_id}")
                
                if queue_id == 420:
                    best_rank, best_val, best_lp = "Unranked", -1, 0
                    for p in players:
                        val = get_rank_value(p["last_rank"], p["last_lp"])
                        if val > best_val:
                            best_val, best_rank, best_lp = val, p["last_rank"], p["last_lp"]
                            
                    if best_rank != "Unranked":
                        formatted_rank = format_rank_string(best_rank, best_lp, emoji_map, include_lp_for_non_apex=False)
                        header = f"**{queue_str} — {formatted_rank}**"
                    else:
                        header = f"**{queue_str} — Unranked**"
                else:
                    header = f"**{queue_str}**"
                
                player_lines = []
                for p in players:
                    champ_id = p.get('champion_id', 'Unknown')
                    champ_emoji = emoji_map.get(champ_id, p['champion_name'])
                    
                    poro_region = reverse_platform_map.get(p['platform'], p['platform'])
                    encoded_id = urllib.parse.quote(p['display'].replace('#', '-'))
                    poro_url = f"https://porofessor.gg/live/{poro_region}/{encoded_id}"
                    player_lines.append(f"<@{p['discord_id']}> ([{p['display']}]({poro_url})) — {champ_emoji}")
                    
                time_str = f"Started <t:{int(start_ms // 1000)}:R>" if start_ms else "Start time unknown"
                
                block = f"\n{header}\n" + "\n".join(player_lines) + f"\n{time_str}\n"
                
                if len(current_desc) + len(block) > MAX_DESC_LENGTH:
                    omitted_count += len(players)
                else:
                    current_desc += block

            for s in streamers:
                start_ms = s["start_time"]
                time_str = f"Started <t:{int(start_ms // 1000)}:R>" if start_ms else "Start time unknown"
                poro_region = reverse_platform_map.get(s['platform'], s['platform'])
                encoded_id = urllib.parse.quote(s['display'].replace('#', '-'))
                poro_url = f"https://porofessor.gg/live/{poro_region}/{encoded_id}"
                
                block = f"\n**Streamer Mode (Hidden Game)**\n<@{s['discord_id']}> ([{s['display']}]({poro_url}))\n{time_str}\n"
                
                if len(current_desc) + len(block) > MAX_DESC_LENGTH:
                    omitted_count += 1
                else:
                    current_desc += block
                    
            if omitted_count > 0:
                current_desc += f"\n*...and {omitted_count} more tracked player(s) currently in-game.*"
                
            description = current_desc + footer

        embed = discord.Embed(
            title="Dashboard",
            description=description,
            color=discord.Color.blue()
        )

        if dashboard_message_id:
            try:
                partial_msg = channel.get_partial_message(dashboard_message_id)
                await partial_msg.edit(content=marker, embed=embed)
                return  
            except discord.NotFound:
                logger.info(f"Dashboard message {dashboard_message_id} not found in {channel.id}. Sending new one.")
            except discord.Forbidden:
                logger.warning(f"Bot lacks permissions to edit the dashboard in channel {channel.id}.")
                return
            except discord.HTTPException as e:
                logger.error(f"HTTP error editing dashboard in channel {channel.id}: {e}")
                return

        try:
            new_msg = await channel.send(content=marker, embed=embed)
            await update_config(guild_id, {"dashboard_message_id": new_msg.id})
        except discord.Forbidden:
            logger.warning(f"Bot lacks permissions to send the dashboard in channel {channel.id}.")
        except Exception as e:
            logger.error(f"Failed to send new dashboard in channel {channel.id}: {e}")

    @spectator_poll.before_loop
    async def before_spectator_poll(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Dashboard(bot))