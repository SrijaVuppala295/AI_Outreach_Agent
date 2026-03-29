# scrapper.py - Complete Enhanced Version with Status Column
import os
import json
import time
import logging
import traceback
import random
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

from utils.Instagram import InstagramScraper
from utils.SheetDB import SheetDB, SheetDBConfig
from utils.Ai import generate_email, generate_followup_email, get_ai_status
from utils.shared_state import get_shared_limiter
import gspread

load_dotenv()

# ======================== CONFIGURATION ========================
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
LEADS_SHEET = "Leads"
DAILY_QUEUE_PREFIX = "Day"
QUEUE_SUFFIX = "Queue"
MAX_PROFILES_PER_DAY = 500
MAX_ROWS_PER_QUEUE = 500

# SAFE DELAYS: 30-40 seconds between profiles
DELAY_BETWEEN_PROFILES = 35.0
DELAY_VARIANCE_SECONDS = 5.0
MAX_RETRIES = 3
RETRY_DELAY = 10

rate_limiter = get_shared_limiter()

# ======================== LOGGING SETUP ========================
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/scraper.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("scraper")
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(console)

# ======================== GOOGLE SHEETS SETUP ========================
def build_gspread_client():
    service_account_info = {
        "type": os.getenv("GOOGLE_SHEETS_TYPE"),
        "project_id": os.getenv("GOOGLE_SHEETS_PROJECT_ID"),
        "private_key_id": os.getenv("GOOGLE_SHEETS_PRIVATE_KEY_ID"),
        "private_key": os.getenv("GOOGLE_SHEETS_PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": os.getenv("GOOGLE_SHEETS_CLIENT_EMAIL"),
        "client_id": os.getenv("GOOGLE_SHEETS_CLIENT_ID"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": os.getenv("GOOGLE_SHEETS_CLIENT_X509_CERT_URL"),
        "universe_domain": "googleapis.com"
    }
    return gspread.service_account_from_dict(service_account_info)

def get_or_create_worksheet(gc, spreadsheet_id: str, sheet_name: str, rows: int = 1000, cols: int = 50):
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(sheet_name)
        logger.info(f"Found existing worksheet: {sheet_name}")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows=rows, cols=cols)
        logger.info(f"Created new worksheet: {sheet_name}")
    return ws

try:
    gc = build_gspread_client()
    leads_db = SheetDB(SheetDBConfig(spreadsheet_id=SPREADSHEET_ID, sheet_name=LEADS_SHEET))
    logger.info("✅ Connected to Google Sheets")
except Exception as e:
    logger.error(f"❌ Failed to connect to Google Sheets: {e}")
    print(f"\n❌ ERROR: Could not connect to Google Sheets\n")
    exit(1)

try:
    scraper = InstagramScraper()
    if not scraper.is_token_valid():
        logger.warning("⚠️ Meta API token validation failed")
    else:
        logger.info("✅ Instagram scraper initialized")
except Exception as e:
    logger.error(f"❌ Failed to initialize Instagram scraper: {e}")
    print(f"\n❌ ERROR: Instagram scraper initialization failed\n")
    exit(1)

# ======================== HELPER FUNCTIONS ========================
def smart_delay(base_seconds: float, variance_seconds: float = DELAY_VARIANCE_SECONDS):
    delay = base_seconds + random.uniform(-variance_seconds, variance_seconds)
    actual_delay = max(1.0, delay)
    logger.info(f"⏳ Waiting {actual_delay:.1f}s before next operation...")
    time.sleep(actual_delay)

def extract_username(url: str) -> Optional[str]:
    if not url:
        return None
    if "instagram.com" not in url:
        clean = url.strip().lstrip("@")
        if clean and "/" not in clean and " " not in clean:
            return clean
        return None
    url = url.split("?")[0].strip().rstrip("/")
    parts = url.split("/")
    for i, part in enumerate(parts):
        if "instagram.com" in part and i + 1 < len(parts):
            username = parts[i + 1]
            if username and username not in ["p", "reel", "tv", "stories", "explore"]:
                return username
    return parts[-1] if parts[-1] else None

def extract_pain_points(profile: Dict, reels: List[Dict]) -> str:
    pain_points = []
    bio_text = profile.get("biography", "").lower()
    bio_keywords = {
        "struggle": "Content consistency struggles",
        "help": "Seeking growth support",
        "grow": "Growth challenges",
        "engagement": "Low engagement concerns",
        "reach": "Limited reach issues",
        "algorithm": "Algorithm challenges",
        "views": "View count concerns",
        "monetize": "Monetization barriers",
        "brand": "Brand deal difficulties",
        "collab": "Collaboration seeking"
    }
    for keyword, pain in bio_keywords.items():
        if keyword in bio_text:
            pain_points.append(pain)
    if reels:
        avg_engagement = sum(r.get("likes_count", 0) + r.get("comments_count", 0) for r in reels) / len(reels)
        followers = profile.get("followers_count", 1)
        engagement_rate = (avg_engagement / followers) * 100 if followers > 0 else 0
        if engagement_rate < 2:
            pain_points.append("Low engagement rate (<2%)")
        if profile.get("followers_count", 0) < 5000:
            pain_points.append("Growing follower base")
    return ", ".join(pain_points[:5]) if pain_points else "No specific pain points detected"

def extract_keywords(reels: List[Dict]) -> str:
    if not reels:
        return ""
    all_hashtags = []
    for reel in reels:
        all_hashtags.extend(reel.get("hashtags", []))
    if not all_hashtags:
        return ""
    hashtag_counts = {}
    for tag in all_hashtags:
        hashtag_counts[tag] = hashtag_counts.get(tag, 0) + 1
    top_hashtags = sorted(hashtag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    return ", ".join([f"#{tag}" for tag, count in top_hashtags])

def safe_fetch_instagram_data(username: str) -> Tuple[Optional[Dict], List[Dict], Optional[Dict]]:
    stats = rate_limiter.get_scraping_status()
    remaining = stats['remaining']
    if remaining <= 0:
        raise Exception("Daily Instagram profile scraping limit reached (500/day)")
    
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Fetching data for @{username} (attempt {attempt + 1}/{MAX_RETRIES})")
            profile = scraper.get_profile_info(username)
            if not profile:
                raise Exception("Profile data is None")
            smart_delay(0.5, 0.2)
            reels = scraper.get_reels_metadata(username, limit=10) or []
            smart_delay(0.5, 0.2)
            insights = scraper.generate_insights(profile, reels)
            if not rate_limiter.track_scraping():
                logger.warning("Instagram rate limit reached during tracking")
            logger.info(f"✅ Successfully fetched data for @{username}")
            return profile, reels, insights
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed for @{username}: {e}")
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (attempt + 1)
                logger.info(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
            else:
                logger.error(f"❌ All attempts failed for @{username}")
                raise

def get_current_queue_sheet(gc) -> Tuple[str, SheetDB, bool]:
    sh = gc.open_by_key(SPREADSHEET_ID)
    existing_queues = [ws.title for ws in sh.worksheets() 
                       if ws.title.startswith(DAILY_QUEUE_PREFIX) and ws.title.endswith(QUEUE_SUFFIX)]
    
    if not existing_queues:
        queue_name = f"{DAILY_QUEUE_PREFIX}1{QUEUE_SUFFIX}"
        get_or_create_worksheet(gc, SPREADSHEET_ID, queue_name)
        queue_db = SheetDB(SheetDBConfig(spreadsheet_id=SPREADSHEET_ID, sheet_name=queue_name))
        logger.info(f"📋 Created first queue: {queue_name}")
        return queue_name, queue_db, True
    
    queue_numbers = []
    for name in existing_queues:
        try:
            num_str = name.replace(DAILY_QUEUE_PREFIX, "").replace(QUEUE_SUFFIX, "")
            queue_numbers.append((int(num_str), name))
        except ValueError:
            continue
    
    queue_numbers.sort(reverse=True)
    latest_queue_name = queue_numbers[0][1]
    
    try:
        queue_db = SheetDB(SheetDBConfig(spreadsheet_id=SPREADSHEET_ID, sheet_name=latest_queue_name))
        row_count = len(queue_db._df)
        logger.info(f"📊 Current queue: {latest_queue_name} ({row_count}/{MAX_ROWS_PER_QUEUE} rows)")
        
        if row_count >= MAX_ROWS_PER_QUEUE:
            next_num = queue_numbers[0][0] + 1
            new_queue_name = f"{DAILY_QUEUE_PREFIX}{next_num}{QUEUE_SUFFIX}"
            get_or_create_worksheet(gc, SPREADSHEET_ID, new_queue_name)
            new_queue_db = SheetDB(SheetDBConfig(spreadsheet_id=SPREADSHEET_ID, sheet_name=new_queue_name))
            logger.info(f"🆕 Queue full! Created new queue: {new_queue_name}")
            return new_queue_name, new_queue_db, True
        
        return latest_queue_name, queue_db, False
    except Exception as e:
        logger.error(f"Error checking queue: {e}")
        raise

# ======================== MODE 1: SCRAPING ONLY (NO DELETE + STATUS COLUMN) ========================
def run_scraper_only():
    logger.info("=" * 60)
    logger.info("🚀 MODE 1: SCRAPING ONLY (NO EMAIL GENERATION)")
    logger.info("=" * 60)
    logger.info(f"⏱️ SAFE delays: {DELAY_BETWEEN_PROFILES-DELAY_VARIANCE_SECONDS:.0f}-{DELAY_BETWEEN_PROFILES+DELAY_VARIANCE_SECONDS:.0f} seconds between profiles")
    
    # Print Dashboard
    get_shared_limiter().print_status()
    
    stats = rate_limiter.get_scraping_status()
    remaining = stats['remaining']
    logger.info(f"📊 Instagram profiles remaining today: {remaining}/500")
    
    if remaining == 0:
        print("\n❌ Daily Instagram scraping limit reached (500/day). Try again tomorrow.\n")
        return
    
    try:
        leads_db.refresh()
        # Select Email, Link, and Status columns
        all_leads = leads_db.select(columns=["Email", "Link", "Status"] if "Status" in leads_db._df.columns else ["Email", "Link"])
    except Exception as e:
        logger.error(f"Error reading Leads sheet: {e}")
        print(f"\n❌ ERROR: Could not read Leads sheet: {e}\n")
        return
    
    if all_leads.empty:
        logger.warning("⚠️ No leads to process in Leads sheet")
        print("\n❌ No leads found in the Leads sheet. Please add leads first.\n")
        return
    
    # Ensure Status column exists
    if "Status" not in all_leads.columns:
        logger.info("📝 Status column not found - creating it and marking all as empty")
        all_leads["Status"] = ""
        # Update the sheet to add Status column
        try:
            leads_db._df = all_leads
            leads_db.commit()
            logger.info("✅ Status column added to Leads sheet")
        except Exception as e:
            logger.error(f"Failed to add Status column: {e}")
            print(f"\n❌ ERROR: Could not add Status column: {e}\n")
            return
    
    # Filter leads where Status is empty or NaN
    leads = all_leads[(all_leads["Status"].isna()) | (all_leads["Status"].astype(str).str.strip() == "")]
    
    if leads.empty:
        logger.warning("⚠️ No unprocessed leads (all have Status filled)")
        print("\n✅ All leads have been processed! Status column is filled for all rows.\n")
        return
    
    total_leads = len(leads)
    logger.info(f"📝 Found {total_leads} unprocessed leads (empty Status)")
    
    max_processable = min(remaining, MAX_PROFILES_PER_DAY)
    leads_to_process = leads.head(max_processable)
    actual_count = len(leads_to_process)
    logger.info(f"📊 Processing {actual_count} leads (daily limit: {max_processable})")
    
    try:
        queue_name, queue_db, is_new = get_current_queue_sheet(gc)
    except Exception as e:
        logger.error(f"Error setting up queue: {e}")
        print(f"\n❌ ERROR: Could not setup queue sheet: {e}\n")
        return
    
    success_count = 0
    error_count = 0
    skipped_count = 0
    rows_to_update = []  # Changed from rows_to_delete
    start_time = time.time()
    
    for idx, row in leads_to_process.iterrows():
        try:
            email = str(row.get("Email", "")).strip()
            link = str(row.get("Link", "")).strip()
            
            if not email or not link:
                logger.warning(f"Row {idx}: Missing email or link, skipping")
                skipped_count += 1
                continue
            
            stats = rate_limiter.get_scraping_status()
            remaining = stats['remaining']
            username = extract_username(link)
            if not username:
                logger.warning(f"Row {idx}: Could not extract username from {link}")
                skipped_count += 1
                # Mark as "Error" in Status
                rows_to_update.append((idx, "Error: Invalid username"))
                continue
            
            logger.info(f"\n{'='*50}")
            logger.info(f"Processing {success_count + 1}/{actual_count}: @{username} | Daily Limit: {remaining}/500")
            logger.info(f"{'='*50}")
            
            try:
                profile, reels, insights = safe_fetch_instagram_data(username)
            except Exception as e:
                logger.error(f"Failed to fetch data for @{username}: {e}")
                error_count += 1
                rows_to_update.append((idx, "Error: Scraping failed"))
                continue
            
            pain_points = extract_pain_points(profile, reels)
            top_keywords = extract_keywords(reels)
            # logger.info(f"📊 Pain Points: {pain_points}")
            # logger.info(f"🏷️ Top Keywords: {top_keywords}")
            
            if len(queue_db._df) >= MAX_ROWS_PER_QUEUE:
                queue_db.commit()
                queue_name, queue_db, is_new = get_current_queue_sheet(gc)
            
            current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            profile_link = f"https://www.instagram.com/{username}/"
            
            # Construct formatted Data object for new column
            data_object = {
                "username": username,
                "profile": profile,
                "pain_points": pain_points,
                "keywords": top_keywords,
                "metrics": insights.get("engagement_metrics", {}),
                "reels": reels,
                "insights": insights
            }
            
            queue_data = {
                "RowId": username,
                "IgUsername": username,
                "ProfileLink": profile_link,
                "Data": json.dumps(data_object, default=str),
                "FullName": profile.get("full_name", ""),
                "Followers": profile.get("followers_count", 0),
                "Following": profile.get("following_count", 0),
                "Bio": profile.get("biography", ""),
                "PainPoints": pain_points,
                "TopKeywords": top_keywords,
                "RecentReels": json.dumps(reels, default=str),
                "Insights": json.dumps(insights, default=str),
                "RecipientEmail": email,
                "SenderEmail": "",
                "Image": "",
                "EmailGenerated": "",
                "FollowUp1": "",
                "FollowUp2": "",
                "BreakupEmail": "",
                "EmailStatus": "Pending",
                "EmailOpened": "No",
                "FollowUp1Status": "Pending",
                "FollowUp1Opened": "No",
                "FollowUp2Status": "Pending",
                "FollowUp2Opened": "No",
                "BreakupEmailStatus": "Pending",
                "BreakupEmailOpened": "No",
                "ReplyStatus": "Pending",
                "ProcessedAt": current_timestamp,
                "Notes": f"Scraped on {current_timestamp}"
            }
            
            queue_db.insert(queue_data)
            queue_db.commit() # Commit IMMEDIATELY to save data
            logger.info(f"✅ Added to {queue_name} (Saved)")
            
            # Mark as "Scraped" in Status column (DON'T DELETE)
            # Update Leads sheet immediately too
            try:
                 leads_db.update(
                    {"Status": f"Scraped: {current_timestamp}"},
                    where={"Email": email, "Link": link}
                 )
                 leads_db.commit()
                 logger.info(f"📝 Marked as Scraped in Leads sheet")
            except Exception as e:
                logger.error(f"Failed to update Status for {email}: {e}")

            success_count += 1
            
            if success_count < actual_count:
                # Random delay between 45-90 seconds + micro-jitter
                delay = random.uniform(45, 90) + random.random()
                logger.info(f"⏳ Sleeping for {delay:.2f}s...")
                time.sleep(delay)
        
        except Exception as e:
            logger.error(f"Unexpected error processing row {idx}: {e}\n{traceback.format_exc()}")
            error_count += 1
            rows_to_update.append((idx, "Error: Processing failed"))
            continue
    
    logger.info(f"\n💾 Committing {success_count} rows to {queue_name}...")
    try:
        queue_db.commit()
    except Exception as e:
        logger.error(f"Error committing queue: {e}")
    
    # Final cleanup (if any updates failed inline)
    pass
    
    elapsed = time.time() - start_time
    logger.info("\n" + "=" * 60)
    logger.info("📊 SCRAPING SUMMARY (NO EMAIL GENERATION)")
    logger.info("=" * 60)
    logger.info(f"✅ Successful: {success_count}")
    logger.info(f"❌ Errors: {error_count}")
    logger.info(f"⏭️ Skipped: {skipped_count}")
    logger.info(f"📋 Written to: {queue_name}")
    logger.info(f"📝 Leads Status: Updated (NOT deleted)")
    logger.info(f"⏱️ Time taken: {elapsed:.2f}s ({elapsed/60:.1f} minutes)")
    logger.info(f"⚡ Avg per profile: {elapsed/max(success_count, 1):.2f}s")
    logger.info("=" * 60)
    
    print(f"\n✅ Scraping completed! {success_count} profiles processed into {queue_name}")
    print(f"📝 Leads sheet: Status column updated (rows NOT deleted)\n")

# ======================== MODE 2: EMAIL GENERATION ========================
def run_email_generation():
    logger.info("=" * 60)
    logger.info("📧 MODE 2: INITIAL EMAIL GENERATION (AUTO-SELECT PROVIDER)")
    logger.info("=" * 60)
    
    ai_status = get_ai_status()
    logger.info(f"🤖 AI Keys: {ai_status['healthy']}/{ai_status['total_keys']} healthy")
    
    if ai_status['healthy'] == 0:
        print("\n❌ ERROR: No healthy AI keys available!\n")
        return
    
    sh = gc.open_by_key(SPREADSHEET_ID)
    queue_sheets = [ws.title for ws in sh.worksheets() 
                    if ws.title.startswith(DAILY_QUEUE_PREFIX) and ws.title.endswith(QUEUE_SUFFIX)]
    
    if not queue_sheets:
        logger.warning("⚠️ No queue sheets found")
        print("\n❌ No queue sheets found. Run scraper first.\n")
        return
    
    print("\n" + "="*60)
    print("📋 AVAILABLE QUEUE SHEETS")
    print("="*60)
    for i, sheet in enumerate(queue_sheets, 1):
        print(f"  {i}. {sheet}")
    print("="*60 + "\n")
    
    try:
        selection = input("Enter sheet number to process (or 'all' for all sheets): ").strip().lower()
        if selection == 'all':
            selected_sheets = queue_sheets
        else:
            sheet_num = int(selection)
            if 1 <= sheet_num <= len(queue_sheets):
                selected_sheets = [queue_sheets[sheet_num - 1]]
            else:
                print(f"\n❌ Invalid selection. Please enter 1-{len(queue_sheets)} or 'all'\n")
                return
    except ValueError:
        print("\n❌ Invalid input. Please enter a number or 'all'\n")
        return
    
    print(f"\n✅ Will process: {', '.join(selected_sheets)}\n")
    
    total_processed = 0
    total_errors = 0
    total_skipped = 0
    
    for sheet_name in selected_sheets:
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing: {sheet_name}")
        logger.info(f"{'='*50}")
        
        try:
            queue_db = SheetDB(SheetDBConfig(spreadsheet_id=SPREADSHEET_ID, sheet_name=sheet_name))
        except Exception as e:
            logger.error(f"Failed to open {sheet_name}: {e}")
            continue
        
        queue_db.refresh()
        rows = queue_db.select()
        
        if rows.empty:
            logger.info(f"Sheet {sheet_name} is empty, skipping")
            continue
        
        logger.info(f"Found {len(rows)} rows in {sheet_name}")
        processed_in_sheet = 0
        
        for idx, row in rows.iterrows():
            username = row.get("IgUsername")
            existing_email = row.get("EmailGenerated", "").strip()
            
            if existing_email:
                logger.info(f"⏭️ Email already exists for @{username}, skipping")
                total_skipped += 1
                continue
            
            logger.info(f"\n📧 Generating email for @{username}")
            
            try:
                profile_data = {
                    "username": username,
                    "bio": row.get("Bio", ""),
                    "followers": row.get("Followers", 0),
                    "pain_points": row.get("PainPoints", ""),
                    "keywords": row.get("TopKeywords", ""),
                    "reels": row.get("RecentReels", "[]"),
                    "insights": row.get("Insights", "{}")
                }
                
                ai_prompt = f"""
Generate a personalized cold email for Instagram creator @{username}.

PROFILE:
{json.dumps(profile_data, indent=2)}

Generate a compelling email that:
1. References specific content
2. Addresses their pain points
3. Offers clear value proposition
4. Has a strong call-to-action
5. Keeps it concise (150-200 words)
"""
                
                ai_email = generate_email(ai_prompt, run_style=None)
                
                queue_db.update(
                    {
                        "EmailGenerated": ai_email,
                        "EmailStatus": "Pending"
                    },
                    where={"IgUsername": username}
                )
                
                queue_db.commit() # Save immediately
                logger.info(f"✅ Generated email for @{username} (Saved)")
                processed_in_sheet += 1
                total_processed += 1
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Failed to generate email for @{username}: {e}")
                total_errors += 1
                continue
        
        # (Optional) Final commit just in case
        pass
    
    logger.info("\n" + "=" * 60)
    logger.info("📊 EMAIL GENERATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"✅ Emails generated: {total_processed}")
    logger.info(f"⏭️ Skipped (already exists): {total_skipped}")
    logger.info(f"❌ Errors: {total_errors}")
    logger.info(f"📋 Sheets processed: {len(selected_sheets)}")
    logger.info("=" * 60)
    
    ai_status = get_ai_status()
    logger.info(f"🤖 AI Keys remaining: {ai_status['healthy']}/{ai_status['total_keys']}")
    
    print(f"\n✅ Email generation completed!")
    print(f"   Generated: {total_processed} emails")
    print(f"   Skipped: {total_skipped}")
    print(f"   Errors: {total_errors}")
    print(f"   Healthy AI keys: {ai_status['healthy']}/{ai_status['total_keys']}\n")

# ======================== MODE 3: FOLLOW-UP GENERATION ========================
def run_followup_generation():
    logger.info("=" * 60)
    logger.info("🔄 MODE 3: FOLLOW-UP EMAIL GENERATION (AUTO-SELECT PROVIDER)")
    logger.info("=" * 60)
    
    ai_status = get_ai_status()
    logger.info(f"🤖 AI Keys: {ai_status['healthy']}/{ai_status['total_keys']} healthy")
    
    if ai_status['healthy'] == 0:
        print("\n❌ ERROR: No healthy AI keys available!\n")
        return
    
    sh = gc.open_by_key(SPREADSHEET_ID)
    queue_sheets = [ws.title for ws in sh.worksheets() 
                    if ws.title.startswith(DAILY_QUEUE_PREFIX) and ws.title.endswith(QUEUE_SUFFIX)]
    
    if not queue_sheets:
        logger.warning("⚠️ No queue sheets found")
        print("\n❌ No queue sheets found. Run scraper first.\n")
        return
    
    print("\n" + "="*60)
    print("📋 AVAILABLE QUEUE SHEETS")
    print("="*60)
    for i, sheet in enumerate(queue_sheets, 1):
        print(f"  {i}. {sheet}")
    print("="*60 + "\n")
    
    try:
        selection = input("Enter sheet number to process (or 'all' for all sheets): ").strip().lower()
        if selection == 'all':
            selected_sheets = queue_sheets
        else:
            sheet_num = int(selection)
            if 1 <= sheet_num <= len(queue_sheets):
                selected_sheets = [queue_sheets[sheet_num - 1]]
            else:
                print(f"\n❌ Invalid selection. Please enter 1-{len(queue_sheets)} or 'all'\n")
                return
    except ValueError:
        print("\n❌ Invalid input. Please enter a number or 'all'\n")
        return
    
    print(f"\n✅ Will process: {', '.join(selected_sheets)}\n")
    print("Which follow-up to generate?")
    print("  1 - FollowUp1 (first follow-up)")
    print("  2 - FollowUp2 (second follow-up)")
    print("  3 - Breakup Email (final email)")
    
    try:
        followup_num = int(input("\nEnter selection (1-3): ").strip())
        if followup_num not in [1, 2, 3]:
            print("\n❌ Invalid selection. Please enter 1, 2, or 3\n")
            return
    except ValueError:
        print("\n❌ Invalid input. Please enter 1, 2, or 3\n")
        return
    
    if followup_num == 3:
        followup_column = "BreakupEmail"
        is_breakup = True
    else:
        followup_column = f"FollowUp{followup_num}"
        is_breakup = False
    logger.info(f"🎯 Generating {followup_column} for selected sheets")
    
    total_processed = 0
    total_errors = 0
    total_skipped = 0
    
    for sheet_name in selected_sheets:
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing: {sheet_name}")
        logger.info(f"{'='*50}")
        
        try:
            queue_db = SheetDB(SheetDBConfig(spreadsheet_id=SPREADSHEET_ID, sheet_name=sheet_name))
        except Exception as e:
            logger.error(f"Failed to open {sheet_name}: {e}")
            continue
        
        queue_db.refresh()
        rows = queue_db.select()
        
        if rows.empty:
            logger.info(f"Sheet {sheet_name} is empty, skipping")
            continue
        
        logger.info(f"Found {len(rows)} rows in {sheet_name}")
        processed_in_sheet = 0
        
        for idx, row in rows.iterrows():
            username = row.get("IgUsername")
            original_email = row.get("EmailGenerated", "")
            reply_status = row.get("ReplyStatus", "").strip().lower()
            
            if reply_status != "pending":
                continue
            
            existing_followup = row.get(followup_column, "").strip()
            if existing_followup:
                logger.info(f"⏭️ {followup_column} already exists for @{username}, skipping")
                total_skipped += 1
                continue
            
            if not original_email:
                logger.info(f"⏭️ No initial email for @{username}, skipping")
                total_skipped += 1
                continue
            
            if followup_num == 1:
                # FollowUp1 needs Initial Email
                pass # Already checked original_email above
            elif followup_num == 2:
                # FollowUp2 needs FollowUp1
                prev_column = "FollowUp1"
                prev_followup = row.get(prev_column, "").strip()
                if not prev_followup:
                    logger.info(f"⏭️ {prev_column} not generated yet for @{username}, skipping")
                    total_skipped += 1
                    continue
            elif followup_num == 3:
                # Breakup Email needs FollowUp2
                prev_column = "FollowUp2"
                prev_followup = row.get(prev_column, "").strip()
                if not prev_followup:
                    logger.info(f"⏭️ {prev_column} not generated yet for @{username}, skipping")
                    total_skipped += 1
                    continue
            
            logger.info(f"\n🔄 Generating {followup_column} for @{username}")
            
            try:
                profile_data = row.get("Bio", "")
                pain_points = row.get("PainPoints", "")
                
                context = f"""
USERNAME: @{username}
BIO: {profile_data}
PAIN POINTS: {pain_points}

ORIGINAL EMAIL:
{original_email}
"""
                
                followup_email = generate_followup_email(
                    original_email=original_email,
                    profile_data=context,
                    run_style=None,
                    is_breakup=is_breakup
                )
                
                queue_db.update(
                    {
                        followup_column: followup_email,
                        f"{followup_column}Status": "Pending"
                    },
                    where={"IgUsername": username}
                )
                
                queue_db.commit() # Save immediately
                logger.info(f"✅ Generated {followup_column} for @{username} (Saved)")
                processed_in_sheet += 1
                total_processed += 1
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Failed to generate {followup_column} for @{username}: {e}")
                total_errors += 1
                continue
        
        # (Optional) Final cleanup
        pass
    
    logger.info("\n" + "=" * 60)
    logger.info("📊 FOLLOW-UP GENERATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"✅ Follow-ups generated: {total_processed}")
    logger.info(f"⏭️ Skipped (already exists/no previous): {total_skipped}")
    logger.info(f"❌ Errors: {total_errors}")
    logger.info(f"📋 Sheets processed: {len(selected_sheets)}")
    logger.info(f"📝 Follow-up type: {followup_column}")
    logger.info("=" * 60)
    
    ai_status = get_ai_status()
    logger.info(f"🤖 AI Keys remaining: {ai_status['healthy']}/{ai_status['total_keys']}")
    
    print(f"\n✅ Follow-up generation completed!")
    print(f"   Generated: {total_processed} {followup_column} emails")
    print(f"   Skipped: {total_skipped}")
    print(f"   Errors: {total_errors}")
    print(f"   Healthy AI keys: {ai_status['healthy']}/{ai_status['total_keys']}\n")

# ======================== MAIN ENTRY POINT ========================
if __name__ == "__main__":
    print("\n" + "="*60)
    print("🤖 INSTAGRAM LEAD AUTOMATION SYSTEM")
    print("="*60)
    print("\nFeatures:")
    print("  1 - Scrape Instagram Profiles ONLY (30-40s delays)")
    print("      • Updates Status column in Leads sheet")
    print("      • Does NOT delete rows from Leads sheet")
    print("  2 - Generate Initial Emails (for scraped profiles)")
    print("  3 - Generate Follow-up Emails")
    print("\n" + "="*60 + "\n")
    
    try:
        mode = input("Select mode (1, 2, or 3): ").strip()
        
        if mode not in ["1", "2", "3"]:
            print("❌ Invalid mode. Please select 1, 2, or 3.")
            exit(1)
        
        if mode in ["2", "3"]:
            print("\n🤖 AI Provider: AUTO-SELECT (system chooses healthiest provider)")
        
        print("\n" + "="*60 + "\n")
        
        if mode == "1":
            run_scraper_only()
        elif mode == "2":
            run_email_generation()
        elif mode == "3":
            run_followup_generation()
        
        print("\n👋 Exiting...")
        sys.exit(0)
            
    except KeyboardInterrupt:
        print("\n\n⚠️ Operation cancelled by user\n")
        logger.info("Operation cancelled by user")
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}\n")
        logger.error(f"Fatal error: {e}\n{traceback.format_exc()}")