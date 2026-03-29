"""
Setup Verification Script
Run: python verify_setup.py
"""
import os
from dotenv import load_dotenv

load_dotenv()

print("\n" + "="*60)
print("CONFIGURATION VERIFICATION")
print("="*60 + "\n")

# Check Discord
print("🤖 DISCORD:")
discord_token = os.getenv("DISCORD_BOT_TOKEN")
guild_id = os.getenv("MY_GUILD_ID")

if discord_token:
    print(f"  ✅ Bot Token: {discord_token[:20]}...")
else:
    print("  ❌ Bot Token: MISSING")

if guild_id:
    print(f"  ✅ Guild ID: {guild_id}")
else:
    print("  ❌ Guild ID: MISSING")

# Check Google Sheets
print("\n📊 GOOGLE SHEETS:")
sheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
if sheet_id:
    print(f"  ✅ Spreadsheet ID: {sheet_id[:20]}...")
else:
    print("  ❌ Spreadsheet ID: MISSING")

# Check Gmail accounts
print("\n📧 GMAIL ACCOUNTS:")
gmail_count = 0
for i in range(1, 21):
    email = os.getenv(f"EMAIL_ADDRESS_{i}")
    password = os.getenv(f"EMAIL_PASSWORD_{i}")
    if email and password:
        gmail_count += 1
        if i <= 3:  # Show first 3
            print(f"  ✅ Account {i}: {email}")

if gmail_count > 3:
    print(f"  ... and {gmail_count - 3} more accounts")

print(f"\n  Total: {gmail_count}/20 Gmail accounts")

# Check AI Keys
print("\n🤖 AI KEYS:")
gemini_count = sum(1 for i in range(1, 13) if os.getenv(f'GEMINI_API_KEY_{i}'))
openrouter_count = sum(1 for i in range(1, 13) if os.getenv(f'OPENROUTER_API_KEY_{i}'))
deepseek_count = sum(1 for i in range(1, 13) if os.getenv(f'DEEPSEEK_API_KEY_{i}'))

print(f"  Gemini: {gemini_count}/12")
print(f"  OpenRouter: {openrouter_count}/12")
print(f"  DeepSeek: {deepseek_count}/12")
print(f"  Total: {gemini_count + openrouter_count + deepseek_count}/36")

# Summary
print("\n" + "="*60)
print("SUMMARY")
print("="*60)

issues = []

if not discord_token:
    issues.append("Missing DISCORD_BOT_TOKEN")
if not guild_id:
    issues.append("Missing MY_GUILD_ID")
if not sheet_id:
    issues.append("Missing GOOGLE_SHEETS_SPREADSHEET_ID")
if gmail_count == 0:
    issues.append("No Gmail accounts configured")
if gemini_count == 0 and openrouter_count == 0:
    issues.append("No AI keys configured")

if issues:
    print("❌ ISSUES FOUND:")
    for issue in issues:
        print(f"   - {issue}")
    print("\nFix these issues in your .env file")
else:
    print("✅ ALL CONFIGURATIONS VALID!")
    print(f"\nReady to run:")
    print("  python main.py")

print("\n" + "="*60 + "\n")