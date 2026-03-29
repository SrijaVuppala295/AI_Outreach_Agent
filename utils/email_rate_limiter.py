"""
Email-Specific Rate Limiter for Discord Bot
Separate from main rate_limiter.py to avoid conflicts
Tracks 20 Gmail accounts with 25 emails/day per account
"""
import json
import os
from datetime import datetime
from typing import Dict, List

# Configuration
EMAIL_RATE_LIMIT_FILE = "logs/email_rate_limits.json"
DAILY_LIMIT_PER_ACCOUNT = 50
TOTAL_GMAIL_ACCOUNTS = 3


def _get_today_key() -> str:
    """Get today's date key (YYYY-MM-DD)"""
    return datetime.utcnow().strftime("%Y-%m-%d")


def _load_email_limits() -> Dict:
    """Load email rate limits from file"""
    if not os.path.exists(EMAIL_RATE_LIMIT_FILE):
        return {"date": _get_today_key(), "next_account_index": 0, "accounts": {}}
    
    try:
        with open(EMAIL_RATE_LIMIT_FILE, 'r') as f:
            data = json.load(f)
            
        # Reset if new day
        if data.get("date") != _get_today_key():
            print(f"📅 [EmailRateLimiter] New day detected! Resetting email limits.")
            # Keep the rotation index? User asked for "1st mani, 2nd rupesh" per day maybe?
            # Actually, usually it resets to 0 or keeps going. 
            # If the user wants strict rotation "even if different batch is sent also", 
            # likely they want to continue rotation to ensure even spread?
            # But limits reset daily. Let's reset pointer to 0 for a fresh start each day 
            # OR keep it to minimize same-sender spam if the previous day ended on 1?
            # "1st mani, 2nd rupesh... everyday" implies a reset or consistent order.
            # Let's reset index to 0 daily for consistency.
            new_data = {"date": _get_today_key(), "next_account_index": 0, "accounts": {}}
            _save_email_limits(new_data)
            return new_data
        
        # Ensure next_account_index exists for backward compatibility
        if "next_account_index" not in data:
            data["next_account_index"] = 0
            
        return data
    except Exception as e:
        print(f"❌ [EmailRateLimiter] Error loading limits: {e}")
        return {"date": _get_today_key(), "next_account_index": 0, "accounts": {}}


def _save_email_limits(data: Dict) -> None:
    """Save email rate limits to file"""
    try:
        os.makedirs("logs", exist_ok=True)
        with open(EMAIL_RATE_LIMIT_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"❌ [EmailRateLimiter] Error saving limits: {e}")


def track_gmail_send(account_num: int) -> bool:
    """
    Track a Gmail send for an account.
    
    Args:
        account_num: Account number (1-20)
    
    Returns:
        True if send allowed, False if quota exceeded
    """
    if account_num < 1 or account_num > TOTAL_GMAIL_ACCOUNTS:
        print(f"❌ [EmailRateLimiter] Invalid account number: {account_num}")
        return False
    
    data = _load_email_limits()
    
    # Initialize account if needed
    account_key = f"gmail_account_{account_num}"
    if account_key not in data["accounts"]:
        data["accounts"][account_key] = {
            "used": 0,
            "limit": DAILY_LIMIT_PER_ACCOUNT,
            "last_reset": _get_today_key()
        }
    
    account_data = data["accounts"][account_key]
    
    # Check if quota exceeded
    if account_data["used"] >= account_data["limit"]:
        print(f"⚠️ [EmailRateLimiter] Account {account_num} quota exceeded ({account_data['used']}/{account_data['limit']})")
        return False
    
    # Increment counter
    account_data["used"] += 1
    data["accounts"][account_key] = account_data
    
    _save_email_limits(data)
    # print(f"✅ [EmailRateLimiter] Tracked send for account {account_num}: {account_data['used']}/{account_data['limit']}")
    return True


def get_rate_limit_status() -> Dict:
    """
    Get current rate limit status for all email accounts.
    
    Returns:
        Dict with 'resources' and 'summary' keys matching discord_bot.py expectations
    """
    data = _load_email_limits()
    
    # Ensure all accounts are initialized
    for i in range(1, TOTAL_GMAIL_ACCOUNTS + 1):
        account_key = f"gmail_account_{i}"
        if account_key not in data["accounts"]:
            data["accounts"][account_key] = {
                "used": 0,
                "limit": DAILY_LIMIT_PER_ACCOUNT,
                "last_reset": _get_today_key()
            }
    
    # Calculate summary
    total_used = sum(acc["used"] for acc in data["accounts"].values())
    total_limit = TOTAL_GMAIL_ACCOUNTS * DAILY_LIMIT_PER_ACCOUNT
    total_remaining = total_limit - total_used
    
    return {
        "date": data["date"],
        "next_account_index": data.get("next_account_index", 0),
        "resources": {
            key: {
                "used": val["used"],
                "limit": val["limit"],
                "remaining": val["limit"] - val["used"]
            }
            for key, val in data["accounts"].items()
        },
        "summary": {
            "gmail": {
                "total_used": total_used,
                "total_limit": total_limit,
                "total_remaining": total_remaining
            }
        }
    }


def get_available_gmail_accounts() -> List[int]:
    """
    Get list of account numbers that still have quota remaining.
    
    Returns:
        List of account numbers (1-20) with remaining quota
    """
    data = _load_email_limits()
    available = []
    
    for i in range(1, TOTAL_GMAIL_ACCOUNTS + 1):
        account_key = f"gmail_account_{i}"
        if account_key not in data["accounts"]:
            available.append(i)
        else:
            account_data = data["accounts"][account_key]
            if account_data["used"] < account_data["limit"]:
                available.append(i)
    
    return available


def get_next_rotational_account() -> int:
    """
    Get the next available account number using persistent round-robin logic.
    Updates the persistent pointer automatically.
    
    Returns:
        Account number (1-3) or None if all exhausted
    """
    data = _load_email_limits()
    start_index = data.get("next_account_index", 0)
    
    # Try finding an available account starting from current index
    # Loop N times to check all accounts once
    for i in range(TOTAL_GMAIL_ACCOUNTS):
        # Calculate current account index (0-based)
        current_idx = (start_index + i) % TOTAL_GMAIL_ACCOUNTS
        account_num = current_idx + 1  # 1-based account number
        
        # Check if valid
        account_key = f"gmail_account_{account_num}"
        
        # Initialize if missing
        if account_key not in data["accounts"]:
            data["accounts"][account_key] = {
                "used": 0,
                "limit": DAILY_LIMIT_PER_ACCOUNT,
                "last_reset": _get_today_key()
            }
            
        account_data = data["accounts"][account_key]
        
        # If available
        if account_data["used"] < account_data["limit"]:
            # Found one! Update pointer to NEXT one for future
            next_start = (current_idx + 1) % TOTAL_GMAIL_ACCOUNTS
            data["next_account_index"] = next_start
            _save_email_limits(data)
            return account_num
            
    # If we get here, no accounts are available
    return None


def reset_email_limits() -> None:
    """Manually reset all email rate limits (admin function)"""
    data = {"date": _get_today_key(), "accounts": {}}
    _save_email_limits(data)
    print("✅ [EmailRateLimiter] Email rate limits reset")


def get_gmail_account_status(account_num: int) -> Dict:
    """Get status for a specific Gmail account"""
    if account_num < 1 or account_num > TOTAL_GMAIL_ACCOUNTS:
        return {"error": "Invalid account number"}
    
    data = _load_email_limits()
    account_key = f"gmail_account_{account_num}"
    
    if account_key not in data["accounts"]:
        return {
            "account_num": account_num,
            "used": 0,
            "limit": DAILY_LIMIT_PER_ACCOUNT,
            "remaining": DAILY_LIMIT_PER_ACCOUNT,
            "available": True
        }
    
    account_data = data["accounts"][account_key]
    return {
        "account_num": account_num,
        "used": account_data["used"],
        "limit": account_data["limit"],
        "remaining": account_data["limit"] - account_data["used"],
        "available": account_data["used"] < account_data["limit"]
    }


# CLI test
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        reset_email_limits()
        sys.exit(0)
    
    print("\n📧 Email Rate Limiter Status\n")
    print("=" * 60)
    
    status = get_rate_limit_status()
    
    print(f"Date: {status['date']}")
    print(f"\nTotal: {status['summary']['gmail']['total_used']}/{status['summary']['gmail']['total_limit']} emails sent")
    print(f"Remaining: {status['summary']['gmail']['total_remaining']}")
    
    print("\n📧 Account Status:")
    for i in range(1, 21):
        key = f"gmail_account_{i}"
        if key in status['resources']:
            data = status['resources'][key]
            used = data['used']
            limit = data['limit']
            remaining = data['remaining']
            
            emoji = "✅" if remaining > 15 else "⚠️" if remaining > 5 else "🚨"
            print(f"{emoji} Account {i:2d}: {used:2d}/{limit} ({remaining:2d} left)")
    
    print("\n" + "=" * 60)
    print("\nAvailable accounts:", get_available_gmail_accounts())
    print("\nTo reset: python utils/email_rate_limiter.py reset")