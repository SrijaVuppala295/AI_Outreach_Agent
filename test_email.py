from dotenv import load_dotenv
import os
import sys

load_dotenv()

print("\n" + "="*60)
print("🔍 EMAIL CONFIGURATION CHECK")
print("="*60 + "\n")

# Check each account
for i in range(1, 21):
    email = os.getenv(f"EMAIL_ADDRESS_{i}")
    password = os.getenv(f"EMAIL_PASSWORD_{i}")
    
    if not email and not password:
        continue
    
    print(f"Account {i}:")
    print(f"  Email: {email if email else '❌ NOT SET'}")
    
    if password:
        # Check for common issues
        issues = []
        if ' ' in password:
            issues.append("contains spaces")
        if '\xa0' in password:
            issues.append("contains non-breaking spaces")
        if len(password) != 16:
            issues.append(f"wrong length ({len(password)} chars, should be 16)")
        
        if issues:
            print(f"  Password: ⚠️ {', '.join(issues)}")
        else:
            print(f"  Password: ✅ Format looks good (16 chars)")
    else:
        print(f"  Password: ❌ NOT SET")
    
    print()

print("="*60)
print("\n💡 To fix authentication errors:")
print("1. Remove ALL spaces from passwords in .env")
print("2. Regenerate app passwords at: https://myaccount.google.com/apppasswords")
print("3. Use format: EMAIL_PASSWORD_1=abcdefghijklmnop (no spaces!)")
print("\n" + "="*60 + "\n")

# Now test connections
print("🔌 Testing SMTP connections...\n")

from utils.email_handler import EmailHandler
handler = EmailHandler()

working = []
failed = []

for i in range(1, 21):
    email = os.getenv(f"EMAIL_ADDRESS_{i}")
    password = os.getenv(f"EMAIL_PASSWORD_{i}")
    
    if email and password:
        print(f"Testing Account {i}: {email}")
        success, message = handler.test_connection(email, password)
        print(f"  {message}")
        
        if success:
            working.append(i)
        else:
            failed.append(i)
        print()

print("\n" + "="*60)
print(f"✅ Working accounts: {len(working)}")
print(f"❌ Failed accounts: {len(failed)}")
print("="*60 + "\n")

if len(working) == 0:
    print("⚠️ NO ACCOUNTS WORKING! Please:")
    print("1. Check your .env file has no extra spaces")
    print("2. Regenerate ALL app passwords")
    print("3. Ensure 2FA is enabled on all accounts")
    sys.exit(1)
elif len(working) < 20:
    print(f"⚠️ Only {len(working)}/20 accounts working")
    print(f"Fix accounts: {failed}")
else:
    print("🎉 All 20 accounts working!")