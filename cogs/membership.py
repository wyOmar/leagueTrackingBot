import discord
from discord.ext import commands
import logging

from db import users, guilds, members

logger = logging.getLogger("MembershipCog")

class Membership(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        logger.info(f"Joined new guild: {guild.name} ({guild.id})")

        # 1. Initialize the database for this guild
        # Pushing default config immediately so the DB is ready for /admin
        default_config = {
            "dashboard_channel_id": None,
            "announcement_channel_id": None,
            "history_channel_id": None,
            "announced_queue_ids": [420, 440], # Default to Ranked Solo/Duo & Flex
            "announce_name_changes": True
        }
        await guilds.update_config(guild.id, default_config)

        # 2. Find a suitable channel to send the welcome message
        target_channel = None
        
        # First choice: The server's designated system messages channel
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            target_channel = guild.system_channel
        else:
            # Fallback: The first text channel we have permission to type in
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    target_channel = channel
                    break

        # If we somehow have zero permissions to speak anywhere, just silently abort
        if not target_channel:
            logger.warning(f"Joined {guild.name} but found no channel to send the welcome message.")
            return

        # 3. Build the Welcome Embed
        embed = discord.Embed(
            title="👋 Thanks for adding FeedWatch!",
            description=(
                "I'm a bot that tracks League of Legends matches for your server members in real-time!\n\n"
                "**⚠️ I need to be configured before I can do anything.**"
            ),
            color=discord.Color.blurple()
        )
        
        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        embed.add_field(
            name="👑 For Server Admins",
            value="Please run the `/admin` command to set up your dashboard and match announcement channels.",
            inline=False
        )
        embed.add_field(
            name="🎮 For Players",
            value="Type `/account link` to link your Riot username so that I can track your games.",
            inline=False
        )

        embed.add_field(
            name="🛠️ Beta & Support",
            value=(
                "I'm currently in active development! Join the Support Server below for:\n"
                "• **Patch Notes & Updates**\n"
                "• **Feature Requests & Feedback**\n"
                "• **Bug Reports**"
            ),
            inline=False
        )

        # 5. Send
        try:
            await target_channel.send(
                content="**Need help? Join the Support Server:** https://discord.gg/ghyTQPPqEP", 
                embed=embed
            )
        except Exception as e:
            logger.error(f"Failed to send welcome message in {guild.name}: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Ignore other bots
        if member.bot:
            return

        # Check if they have a global profile
        udata = await users.get_user(member.id)
        if not udata:
            return

        accounts = udata.get("accounts", [])
        if not accounts:
            return

        # Build account list for the DM
        lines = []
        for acc in accounts:
            disp = acc.get("display") or f"{acc.get('game_name', 'Unknown')}#{acc.get('tag_line', '')}"
            lines.append(f"• **{disp}**")

        embed = discord.Embed(
            title=f"Welcome to {member.guild.name}!",
            description=(
                f"We noticed you have linked Riot account(s) with **{self.bot.user.name}**!\n\n"
                f"Because we respect your privacy, your matches are **NOT** automatically announced in this new server. "
                f"If you'd like to show up on the dashboard and have your games announced here, you'll need to explicitly opt in."
            ),
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Your Linked Accounts", 
            value="\n".join(lines), 
            inline=False
        )
        embed.add_field(
            name="How to Opt-in",
            value=f"Type the `/accounts` command inside **{member.guild.name}** to open your dashboard and turn on Server Tracking.",
            inline=False
        )

        # Attempt to DM the user, silently ignore if their DMs are closed
        try:
            await member.send(embed=embed)
        except discord.Forbidden:
            logger.debug(f"Could not send join DM to {member.id} (Forbidden).")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return

        # Check if they had a global profile
        udata = await users.get_user(member.id)
        if not udata:
            return

        accounts = udata.get("accounts", [])
        if not accounts:
            return

        # 1. Announce departure in the guild's designated channel
        config = await guilds.get_config(member.guild.id)
        channel_id = config.get("announcement_channel_id")

        if channel_id:
            channel = member.guild.get_channel(channel_id)
            if channel:
                lines = []
                for acc in accounts:
                    disp = acc.get("display") or f"{acc.get('game_name', 'Unknown')}#{acc.get('tag_line', '')}"
                    rank = acc.get("last_rank", "Unranked")
                    lp = acc.get("last_lp", 0)
                    lines.append(f"• {disp} — {rank} {lp}LP")

                embed = discord.Embed(
                    title="Member Left",
                    description=(
                        f"User **{member.display_name}** (`{member.id}`) has left the server.\n"
                        f"They had the following linked Riot account{'s' if len(lines) > 1 else ''}:"
                    ),
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(
                    name="Linked Riot Accounts",
                    value="\n".join(lines),
                    inline=False
                )
                embed.set_footer(text="Member Tracker")

                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    logger.warning(f"MembershipCog: Lacking permissions to send leave message in channel {channel_id}.")

        # 2. Delete local guild_members config so they default to opted-out if they rejoin
        await members.remove_member(member.guild.id, member.id)

async def setup(bot: commands.Bot):
    await bot.add_cog(Membership(bot))