"""
Main Entry Point - Discord Bot (PRODUCTION)
Run: python main.py
"""
import os
import sys
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# ======================== CONFIGURATION ========================
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MY_GUILD_ID = os.getenv("MY_GUILD_ID")

# Validation
if not DISCORD_BOT_TOKEN:
    print("\n❌ ERROR: DISCORD_BOT_TOKEN not found in .env")
    print("Add this line to .env:")
    print("DISCORD_BOT_TOKEN=your_token_here\n")
    sys.exit(1)

if not MY_GUILD_ID:
    print("\n❌ ERROR: MY_GUILD_ID not found in .env")
    print("Add this line to .env:")
    print("MY_GUILD_ID=your_server_id_here\n")
    sys.exit(1)

try:
    MY_GUILD_ID = int(MY_GUILD_ID)
except ValueError:
    print("\n❌ ERROR: MY_GUILD_ID must be a valid number\n")
    sys.exit(1)

# ======================== BOT SETUP ========================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True  # Added for better guild access

bot = commands.Bot(command_prefix="!", intents=intents)

# ======================== EVENTS ========================
@bot.event
async def on_ready():
    """Bot startup event"""
    print("\n" + "="*60)
    print("🤖 DISCORD BOT STARTED")
    print("="*60)
    print(f"Bot: {bot.user.name}#{bot.user.discriminator}")
    print(f"ID: {bot.user.id}")
    print(f"Servers: {len(bot.guilds)}")
    print(f"Guild ID: {MY_GUILD_ID}")
    
    # Set bot activity
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="for /send, /followup, /status, /quota"
        ),
        status=discord.Status.online
    )
    
    # Print Shared Status Dashboard
    try:
        from utils.shared_state import get_shared_limiter
        get_shared_limiter().print_status()
    except Exception as e:
        print(f"⚠️ Could not print shared status: {e}")
    
    # Sync commands to guild
    try:
        print("\n🔄 Syncing slash commands...")
        
        # Get the guild object
        guild = discord.Object(id=MY_GUILD_ID)
        
        # Clear existing commands first (optional but recommended)
        bot.tree.clear_commands(guild=guild)
        
        # Copy global commands to guild
        bot.tree.copy_global_to(guild=guild)
        
        # Sync to Discord
        synced = await bot.tree.sync(guild=guild)
        
        print(f"✅ Synced {len(synced)} commands to guild {MY_GUILD_ID}")
        print("\n📋 Commands Available:")
        for cmd in synced:
            print(f"   /{cmd.name} - {cmd.description}")
        
        print("\n💡 TIP: If commands don't appear:")
        print("   1. Wait 5-10 minutes")
        print("   2. Restart Discord app")
        print("   3. Check bot has 'applications.commands' scope")
        
    except discord.Forbidden:
        print("\n❌ Bot lacks permission to sync commands")
        print("Re-invite bot with 'applications.commands' scope")
        print(f"Invite URL: https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=2147485696&scope=bot%20applications.commands")
    except discord.HTTPException as e:
        print(f"\n❌ HTTP error syncing commands: {e}")
        print("Check bot token and guild ID")
    except Exception as e:
        print(f"\n❌ Error syncing commands: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*60)
    print("✅ Bot is online! Use commands in Discord")
    print("="*60 + "\n")

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"Command error: {error}")

@bot.event
async def on_guild_join(guild):
    """Sync commands when bot joins new guild"""
    print(f"\n✅ Joined guild: {guild.name} (ID: {guild.id})")
    if guild.id == MY_GUILD_ID:
        try:
            synced = await bot.tree.sync(guild=discord.Object(id=MY_GUILD_ID))
            print(f"✅ Synced {len(synced)} commands to {guild.name}")
        except Exception as e:
            print(f"❌ Failed to sync on join: {e}")

# ======================== LOAD EXTENSIONS ========================
async def load_extensions():
    """Load bot extensions/cogs"""
    extensions = ["discord_bot"]  # Your discord_bot.py file
    
    print("\n📦 Loading extensions...\n")
    
    for ext in extensions:
        try:
            await bot.load_extension(ext)
            print(f"✅ Loaded: {ext}")
        except commands.ExtensionNotFound:
            print(f"❌ Extension not found: {ext}.py")
            print(f"   Make sure {ext}.py exists in the same directory as main.py")
        except commands.NoEntryPointError:
            print(f"❌ {ext}.py is missing the 'setup' function")
            print(f"   Add this at the end of {ext}.py:")
            print(f"   async def setup(bot):")
            print(f"       await bot.add_cog(YourCog(bot))")
        except Exception as e:
            print(f"❌ Failed to load {ext}: {e}")
            import traceback
            traceback.print_exc()

# ======================== MANUAL SYNC COMMAND ========================
@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx):
    """Manually sync commands (owner only)"""
    try:
        guild = discord.Object(id=MY_GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        await ctx.send(f"✅ Synced {len(synced)} commands to guild")
    except Exception as e:
        await ctx.send(f"❌ Sync failed: {e}")

# ======================== MAIN ========================
async def main():
    """Main async entry point"""
    async with bot:
        print("🚀 Initializing bot...\n")
        await load_extensions()
        print("\n🔌 Connecting to Discord...\n")
        await bot.start(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Bot stopped by user\n")
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}\n")
        import traceback
        traceback.print_exc()




