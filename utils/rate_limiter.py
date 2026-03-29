"""
Production-Ready Rate Limiter - FIXED VERSION
- 36 API Keys Total (12x Gemini, 12x OpenRouter, 12x DeepSeek)
- 20 Gmail Accounts (25 emails/account = 500 total/day)
- Smart scraping limits with anti-spam delays
- Thread-safe with persistent daily state
- Automatic midnight UTC reset
"""
import json
import os
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import random


class RateLimiter:
    """Thread-safe rate limiter with intelligent resource management"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self.state_file = "logs/rate_limiter_state.json"
        self.state_lock = threading.Lock()
        
        # === LIMITS CONFIGURATION ===
        self.limits = {
            **{f"gmail_{i}": 50 for i in range(1, 4)},   # 3 accounts, 50 emails each
            **{f"gemini_{i}": 500 for i in range(1, 13)},        # Gemini API keys
            **{f"openrouter_{i}": 500 for i in range(1, 13)},    # OpenRouter API keys
            **{f"deepseek_{i}": 500 for i in range(1, 13)},      # DeepSeek API keys
            "instagram_profiles": 500,
            "instagram_reels": 5000,
            "web_scraping": 1000,
        }
        
        self.counts = {key: 0 for key in self.limits.keys()}
        self.last_usage = {key: 0.0 for key in self.limits.keys()}
        self.api_indices = {"gemini": 0, "openrouter": 0, "deepseek": 0}
        self.gmail_usage_counts = {f"gmail_{i}": 0 for i in range(1, 4)}
        self.last_reset_date = datetime.utcnow().date()
        
        self._load_state()
        
        print(f"[RateLimiter] Initialized - 3 Gmail accounts, 36 API keys (12 per provider)")
    
    # =================== STATE MANAGEMENT ===================
    def _load_state(self):
        try:
            os.makedirs("logs", exist_ok=True)
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    loaded_counts = data.get("counts", {})
                    for key in self.limits.keys():
                        self.counts[key] = loaded_counts.get(key, 0)
                    saved_date = data.get("last_reset_date")
                    if saved_date:
                        self.last_reset_date = datetime.fromisoformat(saved_date).date()
                    if "api_indices" in data:
                        self.api_indices.update(data["api_indices"])
                    if self.last_reset_date < datetime.utcnow().date():
                        self._reset_counts()
        except Exception as e:
            print(f"[RateLimiter] Warning: Could not load state: {e}")
    
    def _save_state(self):
        try:
            os.makedirs("logs", exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump({
                    "counts": self.counts,
                    "last_reset_date": self.last_reset_date.isoformat(),
                    "api_indices": self.api_indices,
                    "timestamp": datetime.utcnow().isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"[RateLimiter] Warning: Could not save state: {e}")
    
    def _reset_counts(self):
        for key in self.counts:
            self.counts[key] = 0
        self.last_reset_date = datetime.utcnow().date()
        self.last_usage = {key: 0.0 for key in self.limits.keys()}
        self.gmail_usage_counts = {f"gmail_{i}": 0 for i in range(1, 21)}
        self.api_indices = {"gemini": 0, "openrouter": 0, "deepseek": 0}
        self._save_state()
        print(f"[RateLimiter] Reset complete for {self.last_reset_date}")
    
    def _check_reset_needed(self):
        if self.last_reset_date < datetime.utcnow().date():
            self._reset_counts()
    
    def _apply_anti_spam_delay(self, resource: str, min_delay: float = 0.1):
        last_time = self.last_usage.get(resource, 0.0)
        current_time = time.time()
        elapsed = current_time - last_time
        if elapsed < min_delay:
            sleep_time = min_delay - elapsed + random.uniform(0.05, 0.15)
            time.sleep(sleep_time)
        self.last_usage[resource] = time.time()
    
    # =================== CORE RATE LIMITING ===================
    def check_and_increment(self, resource: str, amount: int = 1) -> bool:
        with self.state_lock:
            self._check_reset_needed()
            if resource not in self.counts:
                print(f"[RateLimiter] Warning: Unknown resource '{resource}'")
                return False
            if self.counts[resource] + amount > self.limits[resource]:
                return False
            self.counts[resource] += amount
            self._save_state()
            return True
    
    def get_remaining(self, resource: str) -> int:
        """Get remaining quota for a resource"""
        with self.state_lock:
            self._check_reset_needed()
            if resource not in self.counts:
                return 0
            return max(0, self.limits[resource] - self.counts[resource])
    
    # =================== GMAIL MANAGEMENT ===================
    def get_next_available_gmail(self) -> Optional[int]:
        with self.state_lock:
            self._check_reset_needed()
            best_account = None
            max_remaining = 0
            for i in range(1, 21):
                remaining = self.get_remaining(f"gmail_{i}")
                if remaining > max_remaining:
                    max_remaining = remaining
                    best_account = i
            return best_account if max_remaining > 0 else None
    
    def track_gmail_send(self, account_num: int) -> bool:
        if account_num < 1 or account_num > 20:
            print(f"[RateLimiter] Invalid account number: {account_num}")
            return False
        resource = f"gmail_{account_num}"
        self._apply_anti_spam_delay(resource, min_delay=random.uniform(1.5, 2.5))
        success = self.check_and_increment(resource, 1)
        if success:
            self.gmail_usage_counts[resource] += 1
        return success
    
    def get_available_gmail_accounts(self) -> List[int]:
        with self.state_lock:
            self._check_reset_needed()
            return [i for i in range(1, 21) if self.get_remaining(f"gmail_{i}") > 0]
    
    def get_gmail_status(self) -> Dict:
        with self.state_lock:
            self._check_reset_needed()
            return {
                i: {"used": self.counts[f"gmail_{i}"],
                    "remaining": self.get_remaining(f"gmail_{i}"),
                    "available": self.get_remaining(f"gmail_{i}") > 0
                } for i in range(1, 21)
            }
    
    # =================== API KEY MANAGEMENT ===================
    def get_next_api_key(self, provider: str) -> Optional[Tuple[int, str]]:
        if provider not in ["gemini", "openrouter", "deepseek"]:
            print(f"[RateLimiter] Invalid provider: {provider}")
            return None
        with self.state_lock:
            self._check_reset_needed()
            start_idx = self.api_indices[provider]
            for offset in range(12):
                idx = (start_idx + offset) % 12
                key_num = idx + 1
                resource = f"{provider}_{key_num}"
                if self.get_remaining(resource) > 0:
                    self.api_indices[provider] = (idx + 1) % 12
                    self._save_state()
                    return (key_num, resource)
            return None
    
    def track_api_call(self, provider: str, key_num: int, amount: int = 1) -> bool:
        if key_num < 1 or key_num > 12:
            print(f"[RateLimiter] Invalid key number: {key_num}")
            return False
        resource = f"{provider}_{key_num}"
        self._apply_anti_spam_delay(resource, min_delay=random.uniform(0.05, 0.15))
        return self.check_and_increment(resource, amount)
    
    def get_api_status(self, provider: str) -> Dict:
        with self.state_lock:
            self._check_reset_needed()
            return {
                i: {
                    "used": self.counts[f"{provider}_{i}"],
                    "remaining": self.get_remaining(f"{provider}_{i}"),
                    "healthy": self.get_remaining(f"{provider}_{i}") > 0
                } for i in range(1, 13)
            }
    
    def get_api_health_summary(self) -> Dict:
        with self.state_lock:
            self._check_reset_needed()
            summary = {}
            for provider in ["gemini", "openrouter", "deepseek"]:
                healthy = 0
                total_used = 0
                total_remaining = 0
                for i in range(1, 13):
                    used = self.counts[f"{provider}_{i}"]
                    remaining = self.get_remaining(f"{provider}_{i}")
                    total_used += used
                    total_remaining += remaining
                    if remaining > 0:
                        healthy += 1
                summary[provider] = {
                    "healthy": healthy,
                    "total": 12,
                    "used": total_used,
                    "limit": 6000,
                    "remaining": total_remaining
                }
            return summary
    
    # =================== SCRAPING ===================
    def track_scraping(self, scrape_type: str, count: int = 1) -> bool:
        valid_types = ["instagram_profiles", "instagram_reels", "web_scraping"]
        if scrape_type not in valid_types:
            print(f"[RateLimiter] Invalid scrape type: {scrape_type}")
            return False
        self._apply_anti_spam_delay(scrape_type, min_delay=random.uniform(2.0, 4.0))
        return self.check_and_increment(scrape_type, count)
    
    def track_instagram_profile(self) -> bool:
        return self.track_scraping("instagram_profiles", 1)
    
    def track_instagram_reels(self, count: int = 1) -> bool:
        return self.track_scraping("instagram_reels", count)
    
    def get_scraping_status(self) -> Dict:
        with self.state_lock:
            self._check_reset_needed()
            return {
                "instagram_profiles": {"used": self.counts["instagram_profiles"], "limit": 500, "remaining": self.get_remaining("instagram_profiles")},
                "instagram_reels": {"used": self.counts["instagram_reels"], "limit": 5000, "remaining": self.get_remaining("instagram_reels")},
                "web_scraping": {"used": self.counts["web_scraping"], "limit": 1000, "remaining": self.get_remaining("web_scraping")},
            }
    
    # =================== STATUS REPORT ===================
    def get_status_report(self) -> Dict:
        with self.state_lock:
            self._check_reset_needed()
            report = {
                "last_reset": self.last_reset_date.isoformat(),
                "next_reset": (datetime.utcnow().date() + timedelta(days=1)).isoformat(),
                "summary": {
                    "gmail": {"total_used": 0, "total_limit": 500, "total_remaining": 0, "accounts_available": 0},
                    "api_keys": {provider: {"used": 0, "limit": 6000, "remaining": 0, "healthy": 0} for provider in ["gemini","openrouter","deepseek"]},
                    "scraping": {"profiles": {"used":0,"limit":500,"remaining":0},
                                 "reels": {"used":0,"limit":5000,"remaining":0},
                                 "web": {"used":0,"limit":1000,"remaining":0}},
                },
                "details": {"gmail": {}, "api": {}, "scraping": {}}
            }
            
            # Gmail
            for i in range(1, 21):
                resource = f"gmail_{i}"
                used = self.counts[resource]
                remaining = self.get_remaining(resource)
                report["details"]["gmail"][i] = {"used": used, "remaining": remaining, "available": remaining>0}
                report["summary"]["gmail"]["total_used"] += used
                report["summary"]["gmail"]["total_remaining"] += remaining
                if remaining>0:
                    report["summary"]["gmail"]["accounts_available"] += 1
            
            # API
            for provider in ["gemini","openrouter","deepseek"]:
                report["details"]["api"][provider] = {}
                for i in range(1,13):
                    resource = f"{provider}_{i}"
                    used = self.counts[resource]
                    remaining = self.get_remaining(resource)
                    report["details"]["api"][provider][i] = {"used": used,"remaining": remaining,"healthy": remaining>0}
                    report["summary"]["api_keys"][provider]["used"] += used
                    report["summary"]["api_keys"][provider]["remaining"] += remaining
                    if remaining>0:
                        report["summary"]["api_keys"][provider]["healthy"] += 1
            
            # Scraping
            scraping_types = {"profiles":"instagram_profiles","reels":"instagram_reels","web":"web_scraping"}
            for key, resource in scraping_types.items():
                used = self.counts[resource]
                limit = self.limits[resource]
                remaining = limit-used
                report["details"]["scraping"][key] = {"used": used,"limit": limit,"remaining": remaining}
                report["summary"]["scraping"][key] = {"used": used,"limit": limit,"remaining": remaining}
            
            return report
    
    def print_status(self):
        status = self.get_status_report()
        print("\n" + "="*80)
        print("RATE LIMITER STATUS REPORT".center(80))
        print("="*80)
        print(f"Last Reset: {status['last_reset']} | Next Reset: {status['next_reset']}")
        gmail = status['summary']['gmail']
        print(f"\nEMAIL (Gmail): {gmail['total_used']}/{gmail['total_limit']} sent | {gmail['total_remaining']} remaining | {gmail['accounts_available']}/20 accounts available")
        print(f"\nAPI KEYS (36 total):")
        for provider in ["gemini","openrouter","deepseek"]:
            data = status['summary']['api_keys'][provider]
            print(f"  {provider.upper()}: {data['used']}/{data['limit']} | {data['remaining']} remaining | {data['healthy']}/12 keys healthy")
        scrape = status['summary']['scraping']
        print(f"\nSCRAPING LIMITS:")
        print(f"  Profiles: {scrape['profiles']['used']}/{scrape['profiles']['limit']} ({scrape['profiles']['remaining']} left)")
        print(f"  Reels: {scrape['reels']['used']}/{scrape['reels']['limit']} ({scrape['reels']['remaining']} left)")
        print(f"  Web: {scrape['web']['used']}/{scrape['web']['limit']} ({scrape['web']['remaining']} left)")
        print("="*80 + "\n")


# =================== GLOBAL INSTANCE ===================
_rate_limiter = RateLimiter()


# =================== CONVENIENCE FUNCTIONS ===================
def get_rate_limiter() -> RateLimiter:
    return _rate_limiter

def track_gmail_send(account_num: int) -> bool:
    return _rate_limiter.track_gmail_send(account_num)

def get_next_gmail_account() -> Optional[int]:
    return _rate_limiter.get_next_available_gmail()

def get_available_gmail_accounts() -> List[int]:
    return _rate_limiter.get_available_gmail_accounts()

def get_next_api_key(provider: str) -> Optional[Tuple[int, str]]:
    return _rate_limiter.get_next_api_key(provider)

def track_api_call(provider: str, key_num: int, amount: int = 1) -> bool:
    return _rate_limiter.track_api_call(provider, key_num, amount)

def track_scraping(scrape_type: str, count: int = 1) -> bool:
    return _rate_limiter.track_scraping(scrape_type, count)

def track_instagram_profile() -> bool:
    return _rate_limiter.track_instagram_profile()

def track_instagram_reels(count: int = 1) -> bool:
    return _rate_limiter.track_instagram_reels(count)

def get_status() -> Dict:
    return _rate_limiter.get_status_report()

def print_status():
    _rate_limiter.print_status()

def get_api_health() -> Dict:
    return _rate_limiter.get_api_health_summary()

def get_gmail_status() -> Dict:
    return _rate_limiter.get_gmail_status()


# =================== TEST ===================
if __name__ == "__main__":
    print("Testing Rate Limiter...\n")
    # Gmail
    print("Testing Gmail (sending 5 emails):")
    for i in range(5):
        account = get_next_gmail_account()
        if account:
            success = track_gmail_send(account)
            print(f"  Email {i+1}: Account {account} - {'SUCCESS' if success else 'FAILED'}")
    # API Keys
    print("\nTesting API Keys:")
    for provider in ["gemini","openrouter","deepseek"]:
        key_info = get_next_api_key(provider)
        if key_info:
            key_num, resource = key_info
            success = track_api_call(provider, key_num)
            print(f"  {provider.upper()}: Key {key_num} - {'SUCCESS' if success else 'FAILED'}")
    # Scraping
    print("\nTesting Scraping:")
    success = track_instagram_profile()
    print(f"  Instagram Profile: {'SUCCESS' if success else 'FAILED'}")
    # Print status
    print_status()
