
"""
Shared Rate Limiter implementation using Google Sheets (SheetDB).
Replaces the local JSON file to allow multi-user synchronization.
"""

from datetime import datetime
import os
import time
from typing import Optional, Dict, List

try:
    from .SheetDB import SheetDB, SheetDBConfig
except ImportError:
    from SheetDB import SheetDB, SheetDBConfig  # Fallback for standalone run

class SharedRateLimiter:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SharedRateLimiter, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
        if not spreadsheet_id:
             raise ValueError("GOOGLE_SHEETS_SPREADSHEET_ID not found in environment variables")

        # We need a dedicated tab for state
        self.config = SheetDBConfig(
            spreadsheet_id=spreadsheet_id,
            sheet_name="Bot_State",
            creds_json_path=None # Uses env vars by default in SheetDB
        )
        # Limits
        self.EMAIL_LIMIT_PER_ACCOUNT = 50
        self.ACCOUNTS_COUNT = 3  # mani, rupesh, vishwa (Indices 1, 2, 3)
        self.SCRAPE_LIMIT = 500

        self.db = None
        self._init_db()
        
        self._initialized = True

    def _init_db(self):
        try:
            self.db = SheetDB(self.config)
            # Ensure basic keys exist
            # Note: If the sheet doesn't exist, SheetDB might fail. 
            # We assume the user creates "Bot_State" tab.
            # But we can try to initialize rows if tab exists but is empty.
            if self.db.get_row_count() == 0:
                 self.db.bulk_insert([
                     {"key": "last_reset_date", "value": datetime.utcnow().date().isoformat(), "updated_at": datetime.utcnow().isoformat()},
                     {"key": "current_email_index", "value": "1", "updated_at": datetime.utcnow().isoformat()},
                     {"key": "scraping_count", "value": "0", "updated_at": datetime.utcnow().isoformat()}
                 ])
                 for i in range(1, self.ACCOUNTS_COUNT + 1):
                     self.db.insert({"key": f"gmail_{i}_used", "value": "0", "updated_at": datetime.utcnow().isoformat()})
                 self.db.commit()
            
            # Ensure specific keys exist if added later
            self._ensure_key("last_reset_date", datetime.utcnow().date().isoformat())
            self._ensure_key("current_email_index", "1")
            for i in range(1, self.ACCOUNTS_COUNT + 1):
                self._ensure_key(f"gmail_{i}_used", "0")
            self._ensure_key("scraping_count", "0")
            
        except Exception as e:
            print(f"[SharedState] Error connecting to Sheet: {e}")

    def _ensure_key(self, key: str, default_value: str):
        """Idempotent key creation"""
        if not self.db.row_exists({"key": key}):
            self.db.insert({"key": key, "value": default_value, "updated_at": datetime.utcnow().isoformat()})
            self.db.commit()

    def _check_daily_reset(self):
        """Resets counts if date changed (Checked on every access)"""
        self.db.refresh()
        stored_date = self._get_value("last_reset_date")
        today = datetime.utcnow().date().isoformat()
        
        if stored_date != today:
            print(f"[SharedState] Resetting daily quotas from {stored_date} to {today}...")
            # Reset all counts
            updates = []
            for i in range(1, self.ACCOUNTS_COUNT + 1):
                updates.append(({"value": "0", "updated_at": datetime.utcnow().isoformat()}, {"key": f"gmail_{i}_used"}))
            updates.append(({"value": "0", "updated_at": datetime.utcnow().isoformat()}, {"key": "scraping_count"}))
            updates.append(({"value": today, "updated_at": datetime.utcnow().isoformat()}, {"key": "last_reset_date"}))
            
            self.db.batch_update(updates)
            self.db.commit()

    def _get_value(self, key: str) -> str:
        rows = self.db.select(where={"key": key})
        if not rows.empty:
            return str(rows.iloc[0]["value"])
        return "0"

    def _set_value(self, key: str, value: str):
        self.db.update({"value": value, "updated_at": datetime.utcnow().isoformat()}, where={"key": key})

    def _safe_int(self, value) -> int:
        try:
            return int(float(str(value)))
        except (ValueError, TypeError):
            return 0

    # ================== PUBLIC API ==================

    def get_next_available_account(self) -> Optional[int]:
        """
        Rotational logic with REAL-TIME SHARED STATE:
        1. Fetch latest state from Google Sheets.
        2. Check daily reset.
        3. Check account starting from global 'current_email_index'.
        4. If found, increment global index so NEXT user starts from next account.
        """
        try:
            self._check_daily_reset()
            
            start_index_str = self._get_value("current_email_index")
            start_index = self._safe_int(start_index_str)
            if start_index < 1: start_index = 1
            
            # Check accounts starting from current index
            for i in range(self.ACCOUNTS_COUNT):
                # Calculate actual account number (1-based) handling wrap-around
                # Logic: (start_index - 1 + i) % total + 1
                curr_offset = (start_index - 1 + i) % self.ACCOUNTS_COUNT
                account_num = curr_offset + 1
                
                used_str = self._get_value(f"gmail_{account_num}_used")
                used = self._safe_int(used_str)
                
                if used < self.EMAIL_LIMIT_PER_ACCOUNT:
                    # Found a valid account.
                    # Update pointer to NEXT account for the next user (Rotation)
                    # For example, if we use 1, set index to 2.
                    next_index = ((curr_offset + 1) % self.ACCOUNTS_COUNT) + 1
                    
                    if next_index != start_index:
                         self._set_value("current_email_index", str(next_index))
                         self.db.commit()
                    return account_num
            
            return None # All full
        except Exception as e:
            print(f"[SharedState] Error getting account: {e}")
            return None

    def track_email_sent(self, account_num: int):
        """Increment usage for specific account"""
        try:
            self.db.refresh() # Anti-race
            key = f"gmail_{account_num}_used"
            current_str = self._get_value(key)
            current = self._safe_int(current_str)
            
            self._set_value(key, str(current + 1))
            self.db.commit()
            print(f"[SharedState] Tracked email count for Account {account_num}: {current+1}")
        except Exception as e:
            print(f"[SharedState] Error tracking email: {e}")

    def track_scraping(self, count: int = 1):
        """Increment global scraping count"""
        try:
            self.db.refresh()
            key = "scraping_count"
            current_str = self._get_value(key)
            current = self._safe_int(current_str)
            
            new_val = current + count
            self._set_value(key, str(new_val))
            self.db.commit()
            print(f"[SharedState] Tracked scraping: {new_val} (Limit: {self.SCRAPE_LIMIT})")
            return new_val < self.SCRAPE_LIMIT
        except Exception as e:
            print(f"[SharedState] Error tracking scraping: {e}")
            return True

    def get_scraping_status(self) -> Dict:
        try:
            self.db.refresh()
            current_str = self._get_value("scraping_count")
            current = self._safe_int(current_str)
            return {
                "used": current,
                "limit": self.SCRAPE_LIMIT,
                "remaining": max(0, self.SCRAPE_LIMIT - current)
            }
        except Exception as e:
             return {"used": 0, "limit": self.SCRAPE_LIMIT, "remaining": 0}

    def get_status(self, refresh: bool = True) -> Dict:
        try:
            if refresh:
                self.db.refresh()
            status = {}
            for i in range(1, self.ACCOUNTS_COUNT + 1):
                val = self._get_value(f"gmail_{i}_used")
                status[f"Account {i}"] = val
            status["Scraping"] = self._get_value("scraping_count")
            status["Index"] = self._get_value("current_email_index")
            status["Reset"] = self._get_value("last_reset_date")
            return status
        except Exception:
            return {}

    def print_status(self):
        """Prints a dashboard-style summary to the console"""
        try:
            status = self.get_status()
            reset_date = status.get("Reset", "Unknown")
            
            print("\n" + "="*50)
            print(f"📊 SHARED BOT STATUS (Date: {reset_date})")
            print("="*50)
            
            # Email Stats
            total_sent = 0
            # Increase width for email column
            print(f"{'ACCOUNT':<30} {'USED':<10} {'LIMIT':<10} {'STATUS'}")
            print("-" * 65)
            
            for i in range(1, self.ACCOUNTS_COUNT + 1):
                used = self._safe_int(status.get(f"Account {i}", 0))
                total_sent += used
                limit = self.EMAIL_LIMIT_PER_ACCOUNT
                remaining = limit - used
                
                # Get email from env
                email_addr = os.getenv(f"EMAIL_ADDRESS_{i}", f"Account {i}")
                # Truncate if too long (visual only)
                if len(email_addr) > 28:
                    email_addr = email_addr[:25] + "..."
                
                # Check status icon
                if remaining <= 0: icon = "🔴 FULL"
                elif remaining <= 5: icon = "⚠️ LOW"
                else: icon = "🟢 OK"
                
                print(f"{email_addr:<30} {used:<10} {limit:<10} {icon}")
                
            print("-" * 65)
            print(f"{'TOTAL EMAILS':<30} {total_sent:<10} {self.EMAIL_LIMIT_PER_ACCOUNT * self.ACCOUNTS_COUNT:<10}")
            
            # Rotation Info
            idx_str = status.get("Index", "1")
            idx = self._safe_int(idx_str)
            if idx < 1: idx = 1
            curr_email = os.getenv(f"EMAIL_ADDRESS_{idx}", f"Account {idx}")
            print(f"\n🔄 Current Rotation Pointer: {curr_email}")
            
            # Scraping Stats
            print("\n" + "-" * 50)
            scraped = self._safe_int(status.get("Scraping", 0))
            scrape_limit = self.SCRAPE_LIMIT
            scrape_rem = scrape_limit - scraped
            s_icon = "🔴 FULL" if scrape_rem <= 0 else "🟢 OK"
            
            print(f"🕷️  PROFILES SCRAPED: {scraped} / {scrape_limit}  {s_icon}")
            print("="*50 + "\n")
            
        except Exception as e:
            print(f"❌ Error printing status: {e}")

# Global instance
_shared_limiter = SharedRateLimiter()

def get_shared_limiter():
    return _shared_limiter

if __name__ == '__main__':
    print('[Test] Initializing Shared Rate Limiter...')
    sl = SharedRateLimiter()
    print(f'[Test] Status: {sl.get_status()}')
