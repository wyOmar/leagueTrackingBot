import discord
from discord import app_commands
from discord.ext import commands
import logging
import time
import asyncio
import aiohttp
import urllib.parse

from utils.riot_client import riot_client
from db import users, verifications
from config import PLATFORM_MAP

logger = logging.getLogger("LinkingCog")

async def get_icon_name(icon_id: int) -> str:
    """Fetches the official in-client searchable name of the profile icon from CommunityDragon."""
    url = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/summoner-icons.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    for icon in data:
                        if icon["id"] == icon_id:
                            return icon.get("title", "Unknown Icon")
    except Exception as e:
        logger.error(f"Failed to fetch icon name: {e}")
    return "Unknown Icon"


class VerificationView(discord.ui.View):
    """Interactive button view to start the background verification."""
    def __init__(self, cog):
        super().__init__(timeout=600)  # 10 minute timeout
        self.cog = cog

    @discord.ui.button(label="Done - Start Verification", style=discord.ButtonStyle.success, emoji="✅")
    async def done_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.clear_items()
        
        embed = interaction.message.embeds[0]
        
        # Remove the old instructions once they click Done
        if "Once changed, click **Done**" in embed.description:
            embed.description = embed.description.split("Once changed, click **Done**")[0].strip()
            
        embed.color = discord.Color.gold()
        
        now = time.time()
        first_check_stamp = int(now + 30)
        
        embed.add_field(
            name="⏳ Verification Pending", 
            value=f"Waiting for Riot to update...\n\n🔄 **First check <t:{first_check_stamp}:R>... (Attempt 1/3)**", 
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        interaction.client.loop.create_task(
            self.cog.background_poll(interaction, interaction.user.id, embed)
        )


class Linking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ddragon_version = "14.5.1"  # Fallback just in case the API is down

    async def cog_load(self):
        """Fetches the latest DataDragon version when the cog starts."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://ddragon.leagueoflegends.com/api/versions.json") as resp:
                    if resp.status == 200:
                        versions = await resp.json()
                        self.ddragon_version = versions[0]
                        logger.info(f"Loaded DataDragon version for icons: {self.ddragon_version}")
        except Exception as e:
            logger.error(f"Failed to fetch DDragon version: {e}")

    account_group = app_commands.Group(name="account", description="Manage your linked League accounts")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏳ Please wait **{error.retry_after:.0f} seconds** before starting another verification.", 
                ephemeral=True
            )
        else:
            logger.error(f"Linking Cog Error: {error}")

    async def background_poll(self, interaction: discord.Interaction, user_id: int, embed: discord.Embed):
        """Background task that polls Riot 3 times."""
        challenge = await verifications.get_challenge(user_id)
        if not challenge:
            return 
            
        for attempt in range(1, 4):
            try:
                if attempt == 1:
                    await asyncio.sleep(30)
                    
                summoner_data = await riot_client.get_summoner_by_puuid(challenge["platform"], challenge["puuid"])
                current_icon = summoner_data.get("profileIconId")
                
                if current_icon == challenge["target_icon_id"]:
                    rank_str, lp = await riot_client.get_rank(challenge["platform"], challenge["puuid"])
                    
                    existing_owner = await users.get_user_by_puuid(challenge["puuid"])
                    if existing_owner and str(existing_owner["_id"]) != str(user_id):
                        old_owner_id = int(existing_owner["_id"])
                        await users.remove_account(old_owner_id, challenge["puuid"])
                        try:
                            old_user = await self.bot.fetch_user(old_owner_id)
                            if old_user:
                                steal_embed = discord.Embed(
                                    title="⚠️ Account Unlinked",
                                    description=(
                                        f"Your linked League of Legends account **{challenge['game_name']}#{challenge['tag_line']}** "
                                        f"was verified and claimed by another Discord user.\n\n"
                                        f"It has been removed from your profile."
                                    ),
                                    color=discord.Color.orange()
                                )
                                await old_user.send(embed=steal_embed)
                        except (discord.Forbidden, discord.HTTPException):
                            pass

                    display_str = f"{challenge['game_name']}#{challenge['tag_line']}"
                    account_data = {
                        "puuid": challenge["puuid"],
                        "game_name": challenge["game_name"],
                        "tag_line": challenge["tag_line"],
                        "region": challenge["region"],
                        "platform": challenge["platform"],
                        "display": display_str,
                        "last_rank": rank_str,
                        "last_lp": lp
                    }
                    
                    await users.add_account(user_id, account_data)
                    await verifications.delete_challenge(challenge["_id"])
                    
                    success_embed = discord.Embed(
                        title="Account Linked!",
                        description=(
                            f"✅ Successfully verified **{display_str}** ({rank_str})!\n\n"
                            f"Your account is now tracking globally.\n"
                            f"**Type `/accounts`** to view your linked profiles and manage your server-specific visibility dashboard."
                        ),
                        color=discord.Color.green()
                    )
                    return await interaction.edit_original_response(embed=success_embed)

                else:
                    if attempt == 3:
                        await verifications.delete_challenge(challenge["_id"])
                        fail_embed = discord.Embed(
                            title="Verification Failed",
                            description=(
                                f"❌ **Polling timeout.** We checked for 9 minutes but Riot's servers didn't update to the correct icon.\n\n"
                                f"Please ensure you saved the profile icon change in your client and try `/account link` again later."
                            ),
                            color=discord.Color.red()
                        )
                        return await interaction.edit_original_response(embed=fail_embed)
                    else:
                        now = time.time()
                        next_check_stamp = int((now + 180) // 60) * 60
                        sleep_duration = max(next_check_stamp - now, 60) 
                        
                        embed.color = discord.Color.orange()
                        embed.set_field_at(
                            index=len(embed.fields) - 1, 
                            name="⏳ Verification Pending",
                            value=(
                                f"⚠️ **Icon mismatch.**\n"
                                f"*Waiting for Riot's cache to clear.*\n\n"
                                f"🔄 **Checking again <t:{int(next_check_stamp)}:R>... (Attempt {attempt + 1}/3)**"
                            ),
                            inline=False
                        )
                        await interaction.edit_original_response(embed=embed)
                        
                        await asyncio.sleep(sleep_duration)
                        
            except Exception as e:
                logger.error(f"Background verify error: {e}")
                if attempt == 3:
                    error_embed = discord.Embed(
                        title="Error", 
                        description="❌ A network error occurred while talking to Riot's servers. Please try again later.", 
                        color=discord.Color.red()
                    )
                    return await interaction.edit_original_response(embed=error_embed)
                else:
                    await asyncio.sleep(180)

    @account_group.command(name="link", description="Link a League of Legends account to your Discord")
    @app_commands.describe(riot_id="Your Riot ID (e.g. Faker#SKT)", region="Your region")
    @app_commands.choices(region=[
        app_commands.Choice(name="NA (North America)", value="na"),
        app_commands.Choice(name="EUW (Europe West)", value="euw"),
        app_commands.Choice(name="EUNE (Europe Nordic & East)", value="eune"),
        app_commands.Choice(name="KR (Korea)", value="kr"),
        app_commands.Choice(name="JP (Japan)", value="jp"),
        app_commands.Choice(name="OCE (Oceania)", value="oce"),
        app_commands.Choice(name="BR (Brazil)", value="br"),
        app_commands.Choice(name="LAS (Latin America South)", value="las"),
        app_commands.Choice(name="LAN (Latin America North)", value="lan"),
        app_commands.Choice(name="TR (Turkey)", value="tr"),
        app_commands.Choice(name="RU (Russia)", value="ru"),
        app_commands.Choice(name="ME (Middle East)", value="me"),
        app_commands.Choice(name="PH (Philippines)", value="ph"),
        app_commands.Choice(name="SG (Singapore/Malaysia/Indonesia)", value="sg"),
        app_commands.Choice(name="TW (Taiwan/Hong Kong/Macao)", value="tw"),
        app_commands.Choice(name="TH (Thailand)", value="th"),
        app_commands.Choice(name="VN (Vietnam)", value="vn"),
    ])
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: i.user.id) 
    async def link(self, interaction: discord.Interaction, riot_id: str, region: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        
        if "#" not in riot_id:
            return await interaction.followup.send("❌ Invalid Riot ID format. Please use `Name#Tag`.")
            
        game_name, tag_line = riot_id.split("#", 1)
        game_name = game_name.strip()
        tag_line = tag_line.strip()
        
        reg_val = region.value
        platform = PLATFORM_MAP.get(reg_val)

        try:
            MAX_ACCOUNTS = 15
            user_doc = await users.get_user(interaction.user.id)
            if user_doc and len(user_doc.get("accounts", [])) >= MAX_ACCOUNTS:
                return await interaction.followup.send(
                    f"❌ You have reached the maximum limit of **{MAX_ACCOUNTS}** linked accounts. "
                    f"Please use `/account remove` to unbind an old account before adding a new one."
                )

            safe_game_name = urllib.parse.quote(game_name)
            safe_tag_line = urllib.parse.quote(tag_line)
            
            puuid = await riot_client.get_puuid("euw", safe_game_name, safe_tag_line)
            
            try:
                await riot_client.get_summoner_by_puuid(platform, puuid)
            except Exception as e:
                logger.warning(f"PUUID found, but 404 on regional platform {platform}: {e}")
                return await interaction.followup.send(
                    f"❌ We found **{game_name}#{tag_line}**, but they don't seem to have a League of Legends profile in the **{region.name}** region. "
                    f"Did you select the wrong region?"
                )
            
            if user_doc:
                for acc in user_doc.get("accounts", []):
                    if acc.get("puuid") == puuid:
                        return await interaction.followup.send("✅ You have already linked this account!")

            notice_text = ""
            existing_challenge = await verifications.get_challenge(interaction.user.id)
            if existing_challenge:
                await verifications.delete_challenge(existing_challenge["_id"])
                notice_text = "⚠️ *Your previous pending verification has been cancelled.*\n\n"

            target_icon = await verifications.create_challenge(
                interaction.user.id, puuid, reg_val, platform, game_name, tag_line
            )
            
            icon_name = await get_icon_name(target_icon)
            expire_time = int(time.time()) + 600
            
            embed = discord.Embed(
                title="Account Verification Required",
                description=(
                    f"{notice_text}"
                    f"To prove you own **{game_name}#{tag_line}**, please change your League profile icon to:\n\n"
                    f"🔍 **{icon_name}**\n\n"
                    f"Once changed, click **Done** below. The bot will automatically check for updates in the background. "
                    f"This challenge expires <t:{expire_time}:R>."
                ),
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url=f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}/img/profileicon/{target_icon}.png")
            
            view = VerificationView(self)
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"Link error for {riot_id}: {e}")
            await interaction.followup.send("❌ Could not find that Riot ID. Make sure it's spelled correctly and the region is right.")


    @account_group.command(name="remove", description="Remove a linked League account")
    @app_commands.describe(account="Select the account to remove")
    async def remove(self, interaction: discord.Interaction, account: str):
        await interaction.response.defer(ephemeral=True)
        
        user_doc = await users.get_user(interaction.user.id)
        if not user_doc or not user_doc.get("accounts"):
            return await interaction.followup.send("❌ You don't have any linked accounts.")
            
        target_acc = next((acc for acc in user_doc["accounts"] if acc.get("puuid") == account), None)
        
        if not target_acc:
            return await interaction.followup.send("❌ Could not find that account. Please select one from the autocomplete list.")
            
        await users.remove_account(interaction.user.id, account)
        
        embed = discord.Embed(
            title="Account Removed",
            description=f"✅ Successfully removed **{target_acc['display']}** from your linked accounts.",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed)

    @remove.autocomplete("account")
    async def autocomplete_account(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        user_doc = await users.get_user(interaction.user.id)
        if not user_doc or not user_doc.get("accounts"):
            return []
            
        choices = []
        for acc in user_doc["accounts"]:
            if current.lower() in acc["display"].lower():
                choices.append(app_commands.Choice(name=acc["display"], value=acc["puuid"]))
                
        return choices[:25]


async def setup(bot):
    await bot.add_cog(Linking(bot))