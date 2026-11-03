import asyncio
import os
import discord
from discord.ext import commands
import server

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
OWNER_ID = 1456353767606849628

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"[bot] synced {len(synced)} slash commands")
    except Exception as e:
        print(f"[bot] sync failed: {e}")

async def main():
    runner = await server.start_server()
    async with bot:
        await bot.load_extension("cogs.panel")
        try:
            await bot.start(DISCORD_TOKEN)
        finally:
            await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
