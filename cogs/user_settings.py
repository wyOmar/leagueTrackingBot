import discord
from discord import app_commands
from discord.ext import commands
import logging
from urllib.parse import quote

from db import users, members, guilds 
from utils.helpers import get_rank_value, format_rank_string

logger = logging.getLogger("UserSettingsCog")


def build_settings_embed(user: discord.User, guild_name: str, is_tracked: bool, user_accounts: list, account_visibility: dict, guild_config: dict, emoji_map: dict) -> discord.Embed:
    """Builds the user's personal settings dashboard, including their profile picture."""
    
    dash_id = guild_config.get('dashboard_channel_id')
    ann_id = guild_config.get('announcement_channel_id')
    
    dash_str = f"<#{dash_id}>" if dash_id else "the dashboard channel"
    ann_str = f"<#{ann_id}>" if ann_id else "the announcements channel"
    
    if is_tracked:
        global_status = f"🟢 **ACTIVE**\n*Your visible accounts below will be announced in {ann_str} and shown in {dash_str}.*"
        embed_color = discord.Color.green()
    else:
        global_status = "🔴 **PAUSED (Hidden)**\n*Master switch is OFF. None of your matches will be announced in this server, regardless of your account settings below.*"
        embed_color = discord.Color.red()
    
    embed = discord.Embed(
        title=f"{user.display_name}'s Settings for {guild_name}",
        description=f"Your League of Legends tracking preferences for this specific server, **{guild_name}**.\n\n",
        color=embed_color
    )
    
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Server Tracking Status", value=global_status, inline=False)

    if not user_accounts:
        embed.add_field(name="Linked Accounts", value="*You haven't linked any accounts yet.*", inline=False)
    else:

        sorted_accounts = sorted(
            user_accounts, 
            key=lambda x: get_rank_value(x.get("last_rank", "Unranked"), x.get("last_lp", 0)), 
            reverse=True
        )

        current_chunk = ""
        field_index = 1
        
        for acc in sorted_accounts:
            display = acc.get("display", "Unknown Account")
            puuid = acc.get("puuid")
            
            region_str = acc.get("region", "na").upper()
            gn = acc.get("game_name", "")
            tl = acc.get("tag_line", "")
            
            if gn:
                slug = f"{quote(gn)}-{quote(tl)}" if tl else quote(gn)
                opgg_url = f"https://op.gg/summoners/{acc.get('region', 'na')}/{slug}"
                display_link = f"[{display}]({opgg_url})"
            else:
                display_link = display
                
            rank_str = acc.get("last_rank", "Unranked")
            lp = acc.get("last_lp", 0)
            
            formatted_rank = format_rank_string(rank_str, lp, emoji_map, include_lp_for_non_apex=False)
            
            is_visible = account_visibility.get(puuid, True) 
            status = "👁️ Visible" if is_visible else "👻 Hidden"
            
            line_content = f"**{display_link}** ({region_str}) | {formatted_rank} — {status}"
            
            line = f"~~{line_content}~~\n" if not is_tracked else f"{line_content}\n"
            
            if len(current_chunk) + len(line) > 1000:
                field_name = "Linked Accounts" if field_index == 1 else "\u200b"
                embed.add_field(name=field_name, value=current_chunk, inline=False)
                current_chunk = line
                field_index += 1
            else:
                current_chunk += line
            
        if current_chunk:
            field_name = "Linked Accounts" if field_index == 1 else "\u200b"
            embed.add_field(name=field_name, value=current_chunk, inline=False)
        
    return embed


class AccountVisibilitySelect(discord.ui.Select):
    """Multi-select dropdown to quickly toggle specific accounts."""
    def __init__(self, user_accounts: list, account_visibility: dict):
        options = []
        
        sorted_accounts = sorted(
            user_accounts, 
            key=lambda x: get_rank_value(x.get("last_rank", "Unranked"), x.get("last_lp", 0)), 
            reverse=True
        )
        
        for acc in sorted_accounts:
            puuid = acc.get("puuid")
            is_visible = account_visibility.get(puuid, True)
            
            options.append(discord.SelectOption(
                label=acc.get("display", "Unknown"),
                value=puuid,
                description=f"Region: {acc.get('region', 'na').upper()} | Rank: {acc.get('last_rank', 'Unranked')}",
                emoji="🎮",
                default=is_visible  
            ))

        super().__init__(
            placeholder="Select which accounts to show...",
            min_values=0,
            max_values=len(options),
            options=options,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        visible_puuids = self.values
        
        for opt in self.options:
            puuid = opt.value
            is_enabled = puuid in visible_puuids
            await members.set_account_toggle(interaction.guild_id, interaction.user.id, puuid, is_enabled)
            
        await self.view.refresh_view(interaction)


class UserSettingsView(discord.ui.View):
    """The interactive dashboard for user settings."""
    def __init__(self, user: discord.User, guild_id: int, guild_name: str, user_accounts: list, member_config: dict, client: discord.Client):
        super().__init__(timeout=None)
        self.user = user
        self.guild_id = guild_id
        self.guild_name = guild_name
        self.user_accounts = user_accounts
        self.client = client
        
        self.is_tracked = member_config.get("enabled", False)
        self.account_visibility = member_config.get("account_visibility", {})
        
        self.update_global_button()
        
        if self.user_accounts:
            self.add_item(AccountVisibilitySelect(self.user_accounts, self.account_visibility))

    def update_global_button(self):
        if self.is_tracked:
            self.toggle_global.label = "Server Tracking: ON"
            self.toggle_global.style = discord.ButtonStyle.green
        else:
            self.toggle_global.label = "Server Tracking: PAUSED"
            self.toggle_global.style = discord.ButtonStyle.secondary

    async def refresh_view(self, interaction: discord.Interaction):
        member_config = await members.get_settings(self.guild_id, self.user.id)
        guild_config = await guilds.get_config(self.guild_id)
        emoji_map = getattr(self.client, "app_emojis", {})
        
        new_view = UserSettingsView(self.user, self.guild_id, self.guild_name, self.user_accounts, member_config, self.client)
        
        embed = build_settings_embed(
            self.user,
            self.guild_name, 
            new_view.is_tracked, 
            self.user_accounts, 
            new_view.account_visibility,
            guild_config,
            emoji_map
        )
        
        if interaction.response.is_done():
            await interaction.message.edit(embed=embed, view=new_view)
        else:
            await interaction.response.edit_message(embed=embed, view=new_view)

    @discord.ui.button(custom_id="toggle_global_tracking", row=0)
    async def toggle_global(self, interaction: discord.Interaction, button: discord.ui.Button):
        new_state = not self.is_tracked
        await members.set_global_toggle(self.guild_id, self.user.id, new_state)
        await self.refresh_view(interaction)


class UserSettings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="accounts", description="Open your personal accounts and tracking dashboard")
    async def accounts_dashboard(self, interaction: discord.Interaction):
        user_doc = await users.get_user(interaction.user.id)
        user_accounts = user_doc.get("accounts", []) if user_doc else []
        
        member_config = await members.get_settings(interaction.guild_id, interaction.user.id)
        guild_config = await guilds.get_config(interaction.guild_id)
        emoji_map = getattr(self.bot, "app_emojis", {})
        
        embed = build_settings_embed(
            interaction.user,
            interaction.guild.name,
            member_config.get("enabled", False),
            user_accounts,
            member_config.get("account_visibility", {}),
            guild_config,
            emoji_map 
        )
        
        view = UserSettingsView(interaction.user, interaction.guild_id, interaction.guild.name, user_accounts, member_config, interaction.client)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(UserSettings(bot))