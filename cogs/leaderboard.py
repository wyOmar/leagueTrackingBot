import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio

from db.mongo import users_collection, members_collection
from db import users
from utils.riot_client import riot_client


class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_leaderboard.start()

    def cog_unload(self):
        self.update_leaderboard.cancel()

    @tasks.loop(hours=12)
    async def update_leaderboard(self):
        """Update user ranks and LP in the database."""
        # Iterate asynchronously over all users in the collection
        async for user in users_collection.find({}):
            discord_id_str = user["_id"]

            for acc in user.get("accounts", []):
                puuid = acc.get("puuid")
                platform = acc.get("platform")

                if not puuid or not platform:
                    continue

                # Check if the Riot ID has changed (isolated so failures don't block rank updates)
                try:
                    account_data = await riot_client.get_account_by_puuid(platform, puuid)
                    if account_data:
                        new_game_name = account_data.get("gameName")
                        new_tag_line = account_data.get("tagLine")
                        if new_game_name and new_tag_line:
                            new_display = f"{new_game_name}#{new_tag_line}"
                            old_display = acc.get("display") or (
                                f"{acc.get('game_name')}#{acc.get('tag_line')}"
                                if acc.get("game_name") and acc.get("tag_line")
                                else None
                            )
                            if old_display and old_display != "Unknown#" and old_display != new_display:
                                self.bot.dispatch(
                                    "league_name_change",
                                    discord_id_str,
                                    puuid,
                                    old_display,
                                    new_game_name,
                                    new_tag_line,
                                    new_display
                                )
                except Exception as e:
                    print(f"Error checking Riot ID for {puuid}: {e}")

                try:
                    # get_rank returns a tuple of (rank, lp)
                    rank, lp = await riot_client.get_rank(platform, puuid)

                    # Update the specific account's rank using the new db method
                    await users.update_account_rank(
                        int(discord_id_str), 
                        puuid, 
                        rank, 
                        lp
                    )

                except Exception as e:
                    print(f"Error updating rank for {puuid}: {e}")

                await asyncio.sleep(0.5)  # Rate limiting

    @update_leaderboard.before_loop
    async def before_update_leaderboard(self):
        await self.bot.wait_until_ready()

    class RankPaginationView(discord.ui.View):
        def __init__(
            self,
            cog: "Leaderboard",
            rank_data: list[dict],
            current_page: int,
            total_pages: int,
        ):
            super().__init__(timeout=60)
            self.cog = cog
            self.rank_data = rank_data
            self.current_page = current_page
            self.total_pages = total_pages
            self.message: discord.Message | None = None

            self.prev_button = discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                label="◀️ Previous",
                custom_id="prev",
                disabled=(current_page == 0),
            )
            self.next_button = discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                label="Next ▶️",
                custom_id="next",
                disabled=(current_page >= total_pages - 1),
            )

            self.prev_button.callback = self.on_prev
            self.next_button.callback = self.on_next

            self.add_item(self.prev_button)
            self.add_item(self.next_button)

        async def interaction_check(
            self, interaction: discord.Interaction
        ) -> bool:
            return True

        async def on_prev(self, interaction: discord.Interaction):
            if self.current_page <= 0:
                return
            self.current_page -= 1
            await self._update(interaction)

        async def on_next(self, interaction: discord.Interaction):
            if self.current_page >= self.total_pages - 1:
                return
            self.current_page += 1
            await self._update(interaction)

        async def _update(self, interaction: discord.Interaction):
            embed, new_view = self.cog.create_rank_page(
                interaction, self.rank_data, self.current_page
            )
            new_view.message = self.message
            await interaction.response.edit_message(embed=embed, view=new_view)

    # ───────────────────────── Rank leaderboard ─────────────────────────

    @app_commands.command(name="leaderboard", description="Show the rank leaderboard for this server.")
    async def leaderboard(self, interaction: discord.Interaction):
        """Show rank leaderboard."""
        await interaction.response.defer(thinking=True)

        if not interaction.guild:
            return await interaction.followup.send("This command can only be used in a server.")

        guild_id_str = str(interaction.guild.id)

        # 1. Fetch only members who have explicitly opted-in to THIS server
        server_members_cursor = members_collection.find({
            "guild_id": guild_id_str,
            "enabled": True
        })
        server_members = await server_members_cursor.to_list(length=None)

        if not server_members:
            return await interaction.followup.send("No ranked players have opted into tracking for this server.")

        # 2. Build a lookup map for visibility and a list of Discord IDs
        # Format: { "discord_id_str": { "puuid1": True, "puuid2": False } }
        member_visibility_map = {
            m["discord_id"]: m.get("account_visibility", {}) 
            for m in server_members
        }
        valid_discord_ids = list(member_visibility_map.keys())

        # 3. Fetch ONLY the global user profiles that match the opted-in IDs
        all_users = await users_collection.find({"_id": {"$in": valid_discord_ids}}).to_list(length=None)
        
        rank_data: list[dict] = []

        for user in all_users:
            discord_id = user["_id"]
            
            # Skip users who are not currently in this guild
            member = interaction.guild.get_member(int(discord_id))
            if not member:
                continue
            display_name = member.display_name

            account_visibility = member_visibility_map.get(discord_id, {})

            highest_rank = None
            highest_value = -1
            highest_acc = None

            for acc in user.get("accounts", []):
                puuid = acc.get("puuid")
                
                # Check if this specific account is hidden in this server.
                # Per db/members.py: "Missing keys imply 'True' if 'enabled' is True"
                is_visible = account_visibility.get(puuid, True)
                if not is_visible:
                    continue

                rank = acc.get("last_rank", "Unranked")
                lp = acc.get("last_lp", 0)
                value = self.rank_to_value(rank, lp)
                if value > highest_value:
                    highest_value = value
                    highest_rank = rank
                    highest_acc = acc

            if highest_acc:
                tier = (
                    highest_rank.split()[0]
                    if highest_rank and highest_rank != "Unranked"
                    else "Unranked"
                )

                rank_data.append(
                    {
                        "discord_id": discord_id,
                        "display_name": display_name,
                        "rank": highest_rank,
                        "tier": tier,
                        "lp": highest_acc.get("last_lp", 0),
                        "rank_value": highest_value,
                        "region": highest_acc.get("region", "").upper(),
                        "display": highest_acc.get("display", "Unknown"),
                    }
                )

        if not rank_data:
            return await interaction.followup.send("No valid ranked accounts found to display.")

        rank_data.sort(key=lambda x: x["rank_value"], reverse=True)

        page = 0
        embed, view = self.create_rank_page(interaction, rank_data, page)

        message = await interaction.followup.send(embed=embed, view=view)
        view.message = message

    def create_rank_page(
        self,
        interaction: discord.Interaction,
        rank_data: list[dict],
        page: int = 0,
    ):
        """Create a page of the rank leaderboard."""
        items_per_page = 10
        total_pages = max(
            1, (len(rank_data) + items_per_page - 1) // items_per_page
        )

        page = max(0, min(page, total_pages - 1))
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(rank_data))
        page_items = rank_data[start_idx:end_idx]

        emoji_map = getattr(self.bot, "app_emojis", {})

        embed = discord.Embed(
            title="Rank Leaderboard",
            description=f"Highest ranked accounts\nPage {page + 1}/{total_pages}",
            color=discord.Color.blue(),
        )

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        current_tier = None

        for i, data in enumerate(page_items):
            position = start_idx + i + 1

            # Convert stored string ID back to integer to fetch the guild member
            member = (
                interaction.guild.get_member(int(data["discord_id"]))
                if interaction.guild
                else None
            )
            name = member.display_name if member else data["display_name"]

            tier = data["tier"]
            tier_emoji = emoji_map.get(tier, "")

            if tier != current_tier:
                header_emoji = tier_emoji or "•"
                embed.add_field(
                    name=f"{header_emoji} {tier} {header_emoji}",
                    value="",
                    inline=False,
                )
                current_tier = tier

            medal = medals.get(position, "")
            rank_str = data["rank"]
            lp = data["lp"]
            region = data["region"]
            display = data["display"]

            name_line = (
                f"{medal} **{position}. {name}**"
                if medal
                else f"**{position}. {name}**"
            )
            detail_line = (
                f"{tier_emoji + ' ' if tier_emoji else ''}"
                f"{rank_str} {lp}LP • {display} ({region})"
            )

            embed.add_field(
                name=name_line,
                value=detail_line,
                inline=False,
            )

        embed.set_footer(text="Use the buttons below to navigate pages.")

        view = self.RankPaginationView(
            self, rank_data, page, total_pages
        )
        return embed, view

    def rank_to_value(self, rank: str, lp: int) -> int:
        """Convert rank string to numeric value for sorting."""
        if rank == "Unranked":
            return -1

        tier_values = {
            "Iron": 0,
            "Bronze": 400,
            "Silver": 800,
            "Gold": 1200,
            "Platinum": 1600,
            "Emerald": 2000,
            "Diamond": 2400,
            "Master": 2800,
            "Grandmaster": 3200,
            "Challenger": 3600,
        }

        division_values = {
            "IV": 0,
            "III": 100,
            "II": 200,
            "I": 300,
        }

        parts = rank.split()
        if len(parts) != 2:
            return -1

        tier, division = parts
        tier_value = tier_values.get(tier, 0)
        division_value = division_values.get(division, 0)

        if tier in ["Master", "Grandmaster", "Challenger"]:
            return tier_value + lp

        return tier_value + division_value + lp


async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))