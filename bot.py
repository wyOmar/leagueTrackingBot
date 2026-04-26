import discord
from discord.ext import commands
import logging
import os
from config import settings
from utils.riot_client import riot_client
from db.mongo import setup_indexes

logger = logging.getLogger("LeagueBot")

class LeagueTrackerBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        logger.info("Setting up database indexes...")
        await setup_indexes()

        logger.info("Initializing Riot API Session...")
        await riot_client.init_session()

        logger.info("Auto-loading cogs...")
        # Look through all files in the /cogs folder
        for filename in os.listdir('./cogs'):
            # Only try to load Python files and ignore system files like __init__.py
            if filename.endswith('.py') and not filename.startswith('__'):
                # Slice off the '.py' from the end of the filename to format it as a module
                ext = f"cogs.{filename[:-3]}"
                try:
                    await self.load_extension(ext)
                    logger.info(f"Loaded extension: {ext}")
                except Exception as e:
                    logger.error(f"Failed to load extension {ext}: {e}")

        logger.info("Syncing slash commands...")
        
        # --- DEVELOPMENT SYNC (Instant) ---
        # When developing or testing, global command syncs can take up to an hour.
        # Uncomment the 3 lines below and replace the ID with your testing server ID 
        # to force commands to update instantly in your test server.
        #
        # MY_GUILD = discord.Object(id=123456789012345678) # <-- PLACEHOLDER: Replace with your Guild ID
        # self.tree.copy_global_to(guild=MY_GUILD)
        # await self.tree.sync(guild=MY_GUILD)
        
        # --- PRODUCTION SYNC (Global) ---
        # This syncs commands globally to all servers the bot is in.
        try:
            synced = await self.tree.sync()
            logger.info(f"Successfully synced {len(synced)} slash commands globally.")
        except Exception as e:
            logger.error(f"Failed to sync global commands: {e}")

    async def close(self):
        await riot_client.close()
        await super().close()

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")