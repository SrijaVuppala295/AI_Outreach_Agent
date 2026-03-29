from utils.shared_state import get_shared_limiter

def reset_quotas():
    print("🔄 Connecting to Shared State...")
    shared = get_shared_limiter()
    
    print("⚡ Resetting all counts to 0...")
    # Reset Emails
    for i in range(1, 4):
        shared._set_value(f"gmail_{i}_used", "0")
    
    # Reset Scraping
    shared._set_value("scraping_count", "0")
    
    # Force commit
    shared.db.commit()
    
    print("\n✅ RESET COMPLETE")
    print("=" * 30)
    print(shared.get_status())
    print("=" * 30)

if __name__ == "__main__":
    reset_quotas()
