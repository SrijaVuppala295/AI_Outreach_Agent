import os
import requests
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("META_APP_ID")
APP_SECRET = os.getenv("META_APP_SECRET")
SHORT_TOKEN = os.getenv("META_TOKEN")

print(f"App ID: {APP_ID}")
print(f"App Secret: {APP_SECRET[:10]}...")
print(f"Current Token: {SHORT_TOKEN[:20]}...\n")

# Exchange for long-lived token (60 days)
url = f"https://graph.facebook.com/v18.0/oauth/access_token"
params = {
    "grant_type": "fb_exchange_token",
    "client_id": APP_ID,
    "client_secret": APP_SECRET,
    "fb_exchange_token": SHORT_TOKEN
}

print("Requesting new token...")
response = requests.get(url, params=params)
data = response.json()

if "access_token" in data:
    new_token = data["access_token"]
    print(f"\n✅ SUCCESS! New 60-day token generated:")
    print(f"\n{new_token}\n")
    print(f"📝 Update your .env file with:")
    print(f"META_TOKEN={new_token}")
else:
    print(f"\n❌ ERROR: {data}")
    print(f"\nGo to https://developers.facebook.com/tools/explorer")
    print(f"1. Select your app")
    print(f"2. Click 'Generate Access Token'")
    print(f"3. Copy the new token")
    print(f"4. Update .env file")