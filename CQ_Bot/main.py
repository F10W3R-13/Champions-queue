import discord
from discord.ext import commands
import logging
import os
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("CQ_Bot")

# Import core elements to expose them (important for _smoke_test.py and backwards compatibility)
from core import *
from core import _to_num, _clean, _extract_json, _learn_alias

# Setup bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Load cogs on startup
async def load_extensions():
    cogs_list = ["cogs.registration", "cogs.stats", "cogs.ingest", "cogs.season", "cogs.mmr", "cogs.decay", "cogs.selfroles", "cogs.verify", "cogs.queue"]
    for cog in cogs_list:
        try:
            await bot.load_extension(cog)
            logger.info("Loaded extension: %s", cog)
        except Exception as e:
            logger.error("Failed to load extension %s: %s", cog, e, exc_info=True)

@bot.event
async def on_ready():
    logger.info("Logged in as: %s (%s)", bot.user.name, bot.user.id)
    logger.info("CQ Stats Bot online (registration + stats + OCR ingestion).")
    
    # Sync Slash Commands
    try:
        logger.info("Syncing slash commands...")
        synced = await bot.tree.sync()
        logger.info("Synced %d slash command(s).", len(synced))
    except Exception as e:
        logger.error("Failed to sync slash commands: %s", e)

async def main():
    async with bot:
        await load_extensions()
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
