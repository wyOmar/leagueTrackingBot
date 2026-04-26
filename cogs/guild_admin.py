import discord
from discord import app_commands
from discord.ext import commands
import logging

from db import guilds
from config import QUEUE_ID_MAP

logger = logging.getLogger("GuildAdminCog")

def build_config_embed(guild: discord.Guild, config: dict) -> discord.Embed:
    """Builds the real-time config embed, including the server icon."""
    dash_ch = f"<#{config['dashboard_channel_id']}>" if config.get('dashboard_channel_id') else "Not Set"
    ann_ch = f"<#{config['announcement_channel_id']}>" if config.get('announcement_channel_id') else "Not Set"
    
    queues = config.get('announced_queue_ids', [])
    queues_str = ", ".join([f"{qid} ({QUEUE_ID_MAP.get(qid, 'Unknown')})" for qid in queues]) if queues else "None"

    embed = discord.Embed(title=f"⚙️ Configuration for {guild.name}", color=discord.Color.blurple())
    
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
        
    embed.add_field(
        name="Dashboard Channel", 
        value=f"{dash_ch}\n*⚠️ Make sure this is a dedicated channel where the dashboard is the ONLY message!*", 
        inline=False
    )
    embed.add_field(name="Match Results Channel", value=ann_ch, inline=False)

    embed.add_field(name="Tracked Queues", value=queues_str, inline=False)
    return embed


class QueueSelect(discord.ui.Select):
    """A multi-select dropdown restricted to competitive League Queues."""
    def __init__(self, current_queues: list[int]):
        options = [
            discord.SelectOption(label="Ranked Solo/Duo", value="420", description="Queue ID: 420", emoji="🏆"),
            discord.SelectOption(label="Ranked Flex", value="440", description="Queue ID: 440", emoji="🤝"),
            discord.SelectOption(label="Clash", value="700", description="Queue ID: 700", emoji="🚩"),
        ]
        
        for opt in options:
            if int(opt.value) in current_queues:
                opt.default = True

        super().__init__(
            placeholder="Select Game Queues to Track...",
            min_values=0,
            max_values=len(options),
            options=options,
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        selected_ids = [int(v) for v in self.values]
        await guilds.update_config(self.view.guild_id, {"announced_queue_ids": selected_ids})
        await self.view.refresh_view(interaction)


class AdminConfigView(discord.ui.View):
    """The main interactive control panel."""
    def __init__(self, guild_id: int, initial_config: dict):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.config = initial_config
        
        current_queues = initial_config.get('announced_queue_ids', [])
        self.add_item(QueueSelect(current_queues))

    async def refresh_view(self, interaction: discord.Interaction):
        new_config = await guilds.get_config(self.guild_id)
        embed = build_config_embed(interaction.guild, new_config)
        new_view = AdminConfigView(self.guild_id, new_config)
        
        if interaction.response.is_done():
            await interaction.message.edit(embed=embed, view=new_view)
        else:
            await interaction.response.edit_message(embed=embed, view=new_view)

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Select Dashboard Channel...", channel_types=[discord.ChannelType.text], row=0)
    async def select_dash(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        await guilds.update_config(self.guild_id, {"dashboard_channel_id": select.values[0].id})
        await self.refresh_view(interaction)

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Select Match Results Channel...", channel_types=[discord.ChannelType.text], row=1)
    async def select_ann(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        await guilds.update_config(self.guild_id, {"announcement_channel_id": select.values[0].id})
        await self.refresh_view(interaction)


class OnboardingView(discord.ui.View):
    """Initial view shown if the guild has no channels configured yet."""
    def __init__(self, guild_id: int, initial_config: dict):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.config = initial_config

    @discord.ui.button(label="Create Channels For Me", style=discord.ButtonStyle.success, custom_id="setup_create", emoji="✨")
    async def btn_create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        guild = interaction.guild

        # Permissions: Everyone can view but not send. Bot can do both.
        dashboard_overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True)
        }

        try:
            # Attempt to create the channels
            dash_ch = await guild.create_text_channel('league-dashboard', overwrites=dashboard_overwrites, topic="Live tracked League of Legends matches.")
            ann_ch = await guild.create_text_channel('league-matches', topic="Post-game match results and scoreboards.")

            # Update DB with new channel IDs
            self.config["dashboard_channel_id"] = dash_ch.id
            self.config["announcement_channel_id"] = ann_ch.id
            await guilds.update_config(self.guild_id, {
                "dashboard_channel_id": dash_ch.id,
                "announcement_channel_id": ann_ch.id
            })

            # Transition directly into the main config view
            embed = build_config_embed(guild, self.config)
            view = AdminConfigView(self.guild_id, self.config)
            await interaction.edit_original_response(content="✅ **Setup Complete! Channels created.**", embed=embed, view=view)

        except discord.Forbidden:
            # FALLBACK: Bot lacks permissions. Drop them into the manual setup with a warning.
            embed = build_config_embed(guild, self.config)
            view = AdminConfigView(self.guild_id, self.config)
            await interaction.edit_original_response(
                content="⚠️ **I don't have the `Manage Channels` or `Manage Roles` permissions needed to create channels.**\nNo worries, you can manually select existing channels below!\n\n*(🚨 **Important:** Ensure I have `Send Messages`, `View Channel`, and `Embed Links` permissions in the channels you choose!)*", 
                embed=embed, 
                view=view
            )
            
        except Exception as e:
            logger.error(f"Failed to create channels for guild {guild.id}: {e}")
            embed = build_config_embed(guild, self.config)
            view = AdminConfigView(self.guild_id, self.config)
            await interaction.edit_original_response(
                content="❌ **An unexpected error occurred while creating channels.** Please select existing channels below instead.",
                embed=embed,
                view=view
            )

    @discord.ui.button(label="I'll Use Existing Channels", style=discord.ButtonStyle.secondary, custom_id="setup_manual", emoji="🛠️")
    async def btn_manual(self, interaction: discord.Interaction, button: discord.ui.Button):
        # User opted out of auto-creation; drop them into the standard panel
        embed = build_config_embed(interaction.guild, self.config)
        view = AdminConfigView(self.guild_id, self.config)
        await interaction.response.edit_message(
            content="✅ **Manual Setup**\nPlease select your existing channels below.\n\n*(🚨 **Important:** Ensure the bot has `Send Messages`, `View Channel`, and `Embed Links` permissions in the selected channels!)*", 
            embed=embed, 
            view=view
        )


@app_commands.default_permissions(manage_guild=True)
class GuildAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="admin", description="Open the FeedWatch Configuration Panel")
    async def admin_config(self, interaction: discord.Interaction):
        config = await guilds.get_config(interaction.guild_id)
        
        # Check if this is a first-time setup (no channels assigned)
        if not config.get('dashboard_channel_id') and not config.get('announcement_channel_id'):
            embed = discord.Embed(
                title="Welcome!",
                description="It looks like you haven't set up your channels yet.\n\n"
                            "I need a **Dashboard Channel** (for live game tracking) and a **Match Results Channel** (for post-game scoreboards).\n\n"
                            "Would you like me to automatically create and configure these channels for you, or do you want to assign existing ones?",
                color=discord.Color.brand_green()
            )
            view = OnboardingView(interaction.guild_id, config)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            # Drop straight into standard config panel
            embed = build_config_embed(interaction.guild, config)
            view = AdminConfigView(interaction.guild_id, config)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(GuildAdmin(bot))