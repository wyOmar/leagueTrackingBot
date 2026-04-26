import discord
from discord.ext import commands
import logging

logger = logging.getLogger("AppEmojis")

class AppEmojis(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.app_emojis = {}
        # Start the background task to load emojis on boot
        self.bot.loop.create_task(self.load_emojis_safely())

    async def load_emojis_safely(self):
        await self.bot.wait_until_ready()
        await self.update_emojis()

    async def update_emojis(self):
        self.bot.app_emojis = {}
        try:
            # Fetch emojis uploaded directly to the bot application via Developer Portal
            app_emojis = await self.bot.fetch_application_emojis()
            for emoji in app_emojis:
                self.bot.app_emojis[emoji.name] = str(emoji)
                        
            logger.info(f"Loaded {len(self.bot.app_emojis)} emojis into cache.")
            
        except AttributeError:
            logger.error("Your discord.py version is outdated. Please run: pip install -U discord.py")
        except Exception as e:
            logger.error(f"Error fetching application emojis: {e}")

async def setup(bot):
    await bot.add_cog(AppEmojis(bot))