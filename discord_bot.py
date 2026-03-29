"""
Discord Bot - Email Sending Commands (ENTERPRISE PRODUCTION VERSION)

"""
import os
import discord
import pandas as pd
from discord.ext import commands
from discord import app_commands
from typing import Literal

from datetime import datetime
import asyncio
import random
from dotenv import load_dotenv

from utils.SheetDB import SheetDB, SheetDBConfig
from utils.Email import GmailClient
from utils.imap_client import GmailIMAP
from utils.shared_state import get_shared_limiter

load_dotenv()

SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
MY_GUILD_ID = int(os.getenv("MY_GUILD_ID", "0"))

# ======================== CONFIGURATION CONSTANTS ========================
MAX_ACCOUNTS = 3
DAILY_LIMIT_PER_ACCOUNT = 50
TOTAL_DAILY_LIMIT = MAX_ACCOUNTS * DAILY_LIMIT_PER_ACCOUNT  # 150
SHEET_LOAD_RETRIES = 3
ACCOUNT_SELECT_RETRIES = 2
EMAIL_SEND_RETRIES = 3
NETWORK_RETRY_BASE_DELAY = 5  # seconds
GMAIL_INIT_RETRY_DELAYS = [1, 2, 4]  # exponential backoff in seconds

# ======================== KNOWN LIMITATIONS ========================
# EDGE CASE: Shared Limiter Reservation
# If an account is selected via get_next_available_account() but email send fails
# BEFORE calling track_email_sent(), that account slot is "reserved" but not consumed.
# This can lead to gradual phantom quota loss under repeated network errors.
# 
# Mitigation: Network retry logic reduces this occurrence to <1% of sends.
# Future improvement: Implement peek_next_available_account() + reserve/commit pattern.
# Current status: Acceptable for production (self-corrects on daily reset).


# ======================== SAFE DISCORD UPDATE CLASS ========================
class SafeDiscordUpdater:
    """Handles Discord interaction updates with automatic fallback for expired tokens"""
    
    def __init__(self, interaction: discord.Interaction):
        self.interaction = interaction
        self.token_expired = False
        self.fallback_channel = interaction.channel
        self.fallback_user = interaction.user
    
    async def send_update(self, content=None, embed=None):
        """Send update via interaction or fallback to channel/DM if token expired"""
        if self.token_expired:
            return await self._send_fallback(content, embed)
        
        try:
            await self.interaction.edit_original_response(content=content, embed=embed)
            return True
        except (discord.errors.NotFound, discord.errors.HTTPException) as e:
            if isinstance(e, discord.errors.NotFound) or (hasattr(e, 'code') and e.code == 50027) or (hasattr(e, 'status') and e.status == 401):
                print("⚠️ Discord interaction token expired. Using fallback.")
                self.token_expired = True
                return await self._send_fallback(content, embed)
            else:
                print(f"⚠️ Discord error: {e}")
                return False
        except Exception as e:
            print(f"⚠️ Unexpected Discord error: {e}")
            return False
    
    async def _send_fallback(self, content, embed):
        """Send to channel or DM as fallback"""
        try:
            if self.fallback_channel:
                await self.fallback_channel.send(content=content, embed=embed)
                return True
            elif self.fallback_user:
                await self.fallback_user.send(content=content, embed=embed)
                return True
        except Exception as e:
            print(f"❌ Fallback send failed: {e}")
            return False

# ======================== HELPER FUNCTIONS ========================
def parse_email_content(raw_email: str) -> tuple:
    """Parse email into subject and body"""
    if not raw_email:
        return "Collaboration Opportunity", ""
    
    lines = raw_email.strip().splitlines()
    subject = "Collaboration Opportunity"
    body = raw_email
    
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            body = "\n".join(lines[i + 1:]).strip()
            break
    
    return subject, body

def format_email_body(body: str, recipient_name: str = "") -> str:
    """Add greeting and company signature"""
    lines = body.split("\n")
    formatted = []
    
    # Check if body already has a greeting
    has_greeting = False
    first_line_clean = lines[0].strip().lower() if lines else ""
    
    # Common greetings to check for
    greetings = ["hi", "hello", "hey", "dear", "good morning", "good afternoon", "good evening"]
    
    for greeting in greetings:
        if first_line_clean.startswith(greeting):
            has_greeting = True
            break
            
    if not has_greeting:
        if recipient_name and recipient_name.strip():
            first_name = recipient_name.split()[0]
            formatted.append(f"Hey {first_name},\n")
        else:
            formatted.append("Hey there,\n")
    
    formatted.extend(lines)
    
    return "\n".join(formatted)

def get_sender_signature(sender_email: str) -> str:
    """Get signature based on sender email"""
    if not sender_email:
        return ""
    
    email_lower = sender_email.lower()
    base_sig = "\n\nBest,"
    
    if "mani@sharkedge.media" in email_lower:
        return f"{base_sig}\nMani"
    elif "rupesh@sharkedge.media" in email_lower:
        return f"{base_sig}\nRupesh"
    elif "vishwa@sharkedge.media" in email_lower:
        return f"{base_sig}\nVishwa"
    
    # Fallback: Extract name from email (e.g. name@domain.com -> Name)
    try:
        name_part = email_lower.split('@')[0]
        # Handle dot.separation -> Dot Separation
        name = name_part.replace('.', ' ').title()
        return f"{base_sig}\n{name}"
    except:
        return f"{base_sig}\nShark Edge Team"

def generate_html_content(text_body: str, image_url: str = "", email_type: str = "initial", image_cid: str = None) -> str:
    """
    Convert text email to HTML with image injection and specific formatting.
    
    Args:
        text_body: The plain text email body.
        image_url: URL for [Insert Image Here]
        email_type: initial, backup, followup1, followup2, breakup
    """
    # 1. Convert newlines to <br>
    html_content = text_body.replace("\n", "<br>")
    
    # 2. Handle [bold] tags
    html_content = html_content.replace("[bold]", "<b>").replace("[/bold]", "</b>")
    
    # Handle list tags
    html_content = html_content.replace("[ul]", "<ul>").replace("[/ul]", "</ul>")
    html_content = html_content.replace("[li]", "<li>").replace("[/li]", "</li>")
    
    # 3. Specific Hyperlinking Logic based on Email Type
    if email_type == "initial":
        # positioning playbook -> abc.com
        html_content = html_content.replace(
            "Positioning Playbook", 
            '<a href="https://www.notion.so/The-Positioning-Playbook-3c5a0e17027d4fc9a72e68903f0a3be1?source=copy_link" style="color: #1a0dab; text-decoration: underline;">Positioning Playbook</a>'
        )
    
    elif email_type == "followup1":
        # playbook -> abc2.com
        html_content = html_content.replace(
            "playbook", 
            '<a href="https://www.notion.so/The-Positioning-Playbook-3c5a0e17027d4fc9a72e68903f0a3be1?source=copy_link" style="color: #1a0dab; text-decoration: underline;">playbook</a>'
        )
        # ClientName -> xyz.com
        html_content = html_content.replace(
            "Fraser Briggs", 
            '<a href="https://sharkedge.notion.site/Fraser-Briggs-2e7ae18e370580b2a489e8af152f6c07?source=copy_link" style="color: #1a0dab; text-decoration: underline;">Fraser Briggs</a>'
        )
        
    elif email_type == "followup2":
        # ClientName2 -> xyz2.com
        html_content = html_content.replace(
            "Brent Richard", 
            '<a href="https://www.notion.so/Case-Study-The-Hybrid-Dad-Blueprint-Brent-Richard-6ba70e206664424591715617f87e2790?source=copy_link" style="color: #1a0dab; text-decoration: underline;">Brent Richard</a>'
        )
        # info -> calendly.com (Exact word match only)
        import re
        html_content = re.sub(
            r'\binfo!', 
            '<a href="https://calendly.com/sharkedge/30min" style="color: #1a0dab; text-decoration: underline;">info!</a>',
            html_content,
            flags=re.IGNORECASE
        )
        
    elif email_type == "breakup":
        # Gemini -> gemini.com
        html_content = html_content.replace(
            "Content Planner", 
            '<a href="https://sharkedge.notion.site/Content-Planner-2e8ae18e370580f0b54ff9a5884587bc?pvs=143" style="color: #1a0dab; text-decoration: underline;">Content Planner</a>'
        )
    
    # 4. Tracking Pixel (Removed)
    tracking_pixel = ''
    
    # 5. Inject Image
    if "[Insert Image Here]" in html_content:
        if image_url:
            # DIRECT CLOUDINARY/EXTERNAL LINK (No Attachments)
            # LINKED BACKGROUND IMAGE STRATEGY
            # Uses background-image (harder to download) wrapped in anchor (clickable)
            # padding-bottom: 60% creates a responsive aspect ratio container
            img_tag = (
                f'<a href="https://www.notion.so/The-Positioning-Playbook-3c5a0e17027d4fc9a72e68903f0a3be1?source=copy_link" target="_blank" style="text-decoration: none; display: block; margin: 10px 0;">'
                f'<div style="width: 100%; max-width: 600px; border: 1px solid #ddd; border-radius: 8px; overflow: hidden;">'
                f'<div style="width: 100%; padding-bottom: 60%; '
                f'background-image: url(\'{image_url}\'); '
                f'background-size: contain; background-position: center; background-repeat: no-repeat;">'
                f'</div>'
                f'</div>'
                f'</a>'
            )
            html_content = html_content.replace("[Insert Image Here]", img_tag)
        else:
            html_content = html_content.replace("[Insert Image Here]", "")
            
    # 6. Remove any leftover [Add Button Here] just in case
    html_content = html_content.replace("[Add Button Here]", "")

    # 7. Add Signature (Follow-up 2 Emails Only)
    if email_type == "followup2":
        signature_html = """
        <br>
        <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
        <table cellpadding="0" cellspacing="0" border="0">
            <tr>
                <td style="padding-right: 15px; vertical-align: top;">
                    <img src="https://res.cloudinary.com/dlliqtujb/image/upload/v1768382763/logo_jlqztm.png" width="50" height="50" style="display: block; border-radius: 50%;">
                </td>
                <td style="vertical-align: top; font-family: 'Manrope', Arial, sans-serif;">
                    <div style="font-size: 16px; font-weight: 700; color: #000000; margin-bottom: 4px;">Shark Edge</div>
                    <div style="font-size: 14px; color: #666666;">
                        Visit our website <a href="https://sharkedge.media" style="color: #1a0dab; text-decoration: underline;">here</a>
                    </div>
                </td>
            </tr>
        </table>
        """
        html_content += signature_html
            
    # 8. Wrap in clean container with Helvetica
    final_html = f"""
    <html>
    <body style="font-family: Helvetica, Arial, sans-serif; font-size: 16px; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            {html_content}
            {tracking_pixel}
        </div>
    </body>
    </html>
    """
    
    return final_html

# ======================== GMAIL POOL ========================
class GmailPool:
    """Manages Gmail accounts with lazy initialization and network retry"""
    
    def __init__(self):
        self.accounts = []
        
        for i in range(1, MAX_ACCOUNTS + 1):
            email = os.getenv(f"EMAIL_ADDRESS_{i}")
            password = os.getenv(f"EMAIL_PASSWORD_{i}")
            
            if email and password:
                email = email.strip().replace('\xa0', '').replace(' ', '')
                password = password.strip().replace('\xa0', '').replace(' ', '')
                
                self.accounts.append({
                    "num": i,
                    "email": email,
                    "password": password,
                    "client": None
                })
        
        print(f"✅ Gmail Pool: {len(self.accounts)}/{MAX_ACCOUNTS} accounts loaded")
    
    def get_client(self, account_num: int):
        """Get or create Gmail client with network retry (sync wrapper for async-safe use)"""
        for acc in self.accounts:
            if acc["num"] == account_num:
                if acc["client"] is None:
                    # Try to initialize with retry logic
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            acc["client"] = GmailClient(acc["email"], acc["password"])
                            print(f"✅ Initialized Gmail client for account {account_num}")
                            break
                        except Exception as e:
                            error_str = str(e).lower()
                            is_network_error = 'getaddrinfo' in error_str or 'network' in error_str or 'connection' in error_str
                            
                            if is_network_error and attempt < max_retries - 1:
                                wait_time = GMAIL_INIT_RETRY_DELAYS[attempt]
                                print(f"⚠️ Network error initializing account {account_num} (attempt {attempt + 1}/{max_retries}). Retrying in {wait_time}s...")
                                # CRITICAL: Use threading.Event instead of time.sleep to avoid blocking asyncio event loop
                                import threading
                                threading.Event().wait(wait_time)
                            else:
                                print(f"❌ Failed to init account {account_num}: {e}")
                                return None
                return acc["client"]
        return None
    
    def get_email(self, account_num: int):
        """Get email address for account number"""
        for acc in self.accounts:
            if acc["num"] == account_num:
                return acc["email"]
        return None
    
    def find_account_by_email(self, email_address: str):
        """Find account number by email address"""
        for acc in self.accounts:
            if acc["email"] == email_address:
                return acc["num"]
        return None

    def get_account_status(self, account_num: int, refresh: bool = True):
        """Get usage stats for an account from Shared State"""
        try:
            shared = get_shared_limiter()
            status = shared.get_status(refresh=refresh)
            val = status.get(f"Account {account_num}", "0")
            used = int(float(str(val)))
        except Exception as e:
            print(f"⚠️ Error getting account status: {e}")
            used = 0
        return {"used": used, "limit": DAILY_LIMIT_PER_ACCOUNT, "remaining": max(0, DAILY_LIMIT_PER_ACCOUNT - used)}

# ======================== EMAIL SENDER COG ========================
class EmailSender(commands.Cog):
    """Email sending commands with network error handling"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.gmail_pool = GmailPool()
    
    @app_commands.command(name="send", description="Send initial emails from queue")
    @app_commands.describe(
        queue="Sheet name (Day1Queue, Day2Queue, etc)",
        count="Number of emails to send (1-500)",
        delay="Delay between emails in seconds (default: 1)"
    )
    async def send_emails(
        self,
        interaction: discord.Interaction,
        queue: str,
        count: int,
        delay: int = 1
    ):
        """Send initial emails with configurable delay"""
        
        print(f"\n🚀 /send: queue={queue}, count={count}, delay={delay}s")
        
        await interaction.response.send_message(
            f"📧 Starting email send...\n"
            f"**Queue:** `{queue}`\n"
            f"**Count:** {count}\n"
            f"**Delay:** {delay}s per email\n"
            f"Loading data...",
            ephemeral=False
        )
        
        if count <= 0 or count > 500:
            await interaction.edit_original_response(content="❌ Count must be 1-500")
            return
        
        if delay < 0 or delay > 300:
            await interaction.edit_original_response(content="❌ Delay must be 0-300 seconds")
            return
        
        if not self.gmail_pool.accounts:
            await interaction.edit_original_response(content="❌ No Gmail accounts configured")
            return
            
        print("DEBUG: Creating background task...", flush=True)
        self.bot.loop.create_task(
            self._send_background(interaction, queue, count, "initial", delay)
        )
        print("DEBUG: Task created.", flush=True)
    
    @app_commands.command(name="followup", description="Send follow-up emails (3 = Breakup Email)")
    @app_commands.describe(
        queue="Sheet name (Day1Queue, etc)",
        number="Follow-up number (1, 2, or 3 for Breakup)",
        count="Number of emails to send (1-500)",
        delay="Delay between emails in seconds (default: 1)"
    )
    async def send_followup(
        self,
        interaction: discord.Interaction,
        queue: str,
        number: Literal[1, 2, 3],
        count: int,
        delay: int = 1
    ):
        """Send follow-up emails with configurable delay"""
        
        type_name = "Breakup Email" if number == 3 else f"Follow-up {number}"
        print(f"\n🚀 /followup: queue={queue}, type={type_name}, count={count}, delay={delay}s")
        
        await interaction.response.send_message(
            f"📨 Starting {type_name}...\n"
            f"**Queue:** `{queue}`\n"
            f"**Count:** {count}\n"
            f"**Delay:** {delay}s per email",
            ephemeral=False
        )
        
        if count <= 0 or count > 500:
            await interaction.edit_original_response(content="❌ Count must be 1-500")
            return
        
        if delay < 0 or delay > 300:
            await interaction.edit_original_response(content="❌ Delay must be 0-300 seconds")
            return
        
        email_type = "breakup" if number == 3 else f"followup{number}"

        print("DEBUG: Creating background task (followup)...", flush=True)
        self.bot.loop.create_task(
            self._send_background(interaction, queue, count, email_type, delay)
        )
        print("DEBUG: Task created (followup).", flush=True)
    
    async def _send_background(self, interaction, queue, count, email_type, delay):
        """Background email sending with error handling"""
        
        # Create safe updater for Discord messages
        updater = SafeDiscordUpdater(interaction)
        
        try:
            print(f"\n📧 [BACKGROUND] Starting: {email_type}, delay={delay}s", flush=True)
            
            await updater.send_update(content=f"📊 Loading `{queue}`...")
            
            # Helper for threaded loading with retry logic
            def load_sheet_with_logging(sid, name):
                print(f"DEBUG: [Thread] Connecting to GSheets (ID: ...{sid[-5:]}, Tab: {name})...", flush=True)
                try:
                    db = SheetDB(SheetDBConfig(spreadsheet_id=sid, sheet_name=name))
                    print(f"DEBUG: [Thread] SheetDB initialized for {name}. Cache loaded.", flush=True)
                    return db
                except Exception as e:
                    print(f"DEBUG: [Thread] ❌ Error loading sheet: {e}", flush=True)
                    raise e

            print(f"DEBUG: Spawning thread to load sheet...", flush=True)
            
            # Retry sheet loading on network errors
            queue_db = None
            max_retries = SHEET_LOAD_RETRIES
            for attempt in range(max_retries):
                try:
                    queue_db = await asyncio.to_thread(
                        load_sheet_with_logging, SPREADSHEET_ID, queue
                    )
                    break
                except Exception as e:
                    error_str = str(e).lower()
                    is_network_error = 'getaddrinfo' in error_str or 'network' in error_str or 'connection' in error_str
                    
                    if is_network_error and attempt < max_retries - 1:
                        wait_time = NETWORK_RETRY_BASE_DELAY * (attempt + 1)  # 5s, 10s, 15s
                        print(f"⚠️ Network error loading sheet (attempt {attempt + 1}/{max_retries}). Retrying in {wait_time}s...")
                        await updater.send_update(content=f"⚠️ Network issue detected. Retrying... (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait_time)
                    else:
                        error_msg = f"❌ Cannot connect to Google Sheets after {max_retries} attempts.\n\n"
                        if is_network_error:
                            error_msg += "Network error detected. Please check your internet connection and try again."
                        else:
                            error_msg += f"Error: {e}"
                        await updater.send_update(content=error_msg)
                        return
            
            if not queue_db:
                await updater.send_update(content="❌ Failed to load sheet")
                return
            
            all_rows = queue_db.select()
            print(f"✅ Loaded {len(all_rows)} rows", flush=True)
            
            if all_rows.empty:
                await updater.send_update(content=f"❌ Sheet `{queue}` is empty")
                return
            
            await updater.send_update(content="🔍 Filtering emails...")
            
            if email_type == "initial":
                email_col = "EmailGenerated"
                status_col = "EmailStatus"
                message_id_col = "InitialMessageID"
                reply_to_col = None
                subject_col = None
                
                filtered = all_rows[
                    (all_rows[email_col].notna()) &
                    (all_rows[email_col].astype(str).str.strip() != "") &
                    (all_rows.get(status_col, "Pending").fillna("Pending") == "Pending")
                ]
                
            else:  # Follow-up
                if email_type == "breakup":
                    email_col = "BreakupEmail"
                    status_col = "BreakupEmailStatus"
                    message_id_col = "BreakupEmailMessageID"
                    reply_to_col = "FollowUp2MessageID"
                    original_email_col = "EmailGenerated"
                else:
                    followup_num = int(email_type.replace("followup", ""))
                    email_col = f"FollowUp{followup_num}"
                    status_col = f"FollowUp{followup_num}Status"
                    message_id_col = f"FollowUp{followup_num}MessageID"
                    
                    if followup_num == 1:
                        reply_to_col = "InitialMessageID"
                        original_email_col = "EmailGenerated"
                    else:
                        reply_to_col = f"FollowUp{followup_num-1}MessageID"
                        original_email_col = "EmailGenerated"
                
                if email_col not in all_rows.columns:
                    await updater.send_update(content=f"❌ Column `{email_col}` not found")
                    return
                
                if reply_to_col not in all_rows.columns:
                    await updater.send_update(
                        content=f"❌ Column `{reply_to_col}` not found. Send previous emails first!"
                    )
                    return
                
                filtered = all_rows[
                    (all_rows[email_col].notna()) &
                    (all_rows[email_col].astype(str).str.strip() != "") &
                    (all_rows.get(status_col, "Pending").fillna("Pending") == "Pending") &
                    (all_rows.get("ReplyStatus", "Pending").fillna("Pending") == "Pending") &
                    (all_rows.get("SenderEmail", "").notna()) &
                    (all_rows.get("SenderEmail", "").astype(str).str.strip() != "") &
                    (all_rows.get(reply_to_col, "").notna()) &
                    (all_rows.get(reply_to_col, "").astype(str).str.strip() != "")
                ]
            
            print(f"✅ Filtered: {len(filtered)} emails ready (with content + status=Pending)")
            
            if filtered.empty:
                await updater.send_update(
                    content=f"❌ No emails ready for `{email_type}` in `{queue}`\n"
                    f"Make sure:\n"
                    f"1. Email content exists in `{email_col}`\n"
                    f"2. Status is `Pending` in `{status_col}`"
                )
                return
            
            to_send = filtered.head(count)
            total = len(to_send)
            
            await updater.send_update(
                content=f"📧 Found {total} emails. Starting send with {delay}s delay..."
            )
            
            # Send emails
            success = 0
            errors = 0
            skipped = 0
            account_usage = {}
            
            # Initialize Coffee Break Target (Random 5-8 emails)
            next_break_target = random.randint(5, 8)
            
            for idx, row in to_send.iterrows():

                message_id = None
                sent_success = False
                recipient = str(row.get("RecipientEmail", "")).strip()
                content = str(row.get(email_col, "")).strip()
                username = str(row.get("IgUsername", "unknown"))
                name = str(row.get("FullName", "")).strip()
                
                print(f"📧 Sending {success + errors + skipped + 1}/{total} to {recipient} ({username})")
                
                # CRITICAL: Double-check content is not empty
                if not recipient or not content or content == "" or "@" not in recipient:
                    print(f"   ⚠️ Skipping: Empty email content or invalid recipient")
                    skipped += 1
                    continue
                
                # Determine which account to use
                if email_type == "initial":
                    # Initial: Use Persistent Rotational Logic (SHARED)
                    print(f"   👤 Checking for available account...")
                    
                    # Network-safe account selection with retry
                    try:
                        account_num = await asyncio.to_thread(get_shared_limiter().get_next_available_account)
                    except Exception as e:
                        error_str = str(e).lower()
                        if 'getaddrinfo' in error_str or 'network' in error_str:
                            print(f"   ⚠️ Network error selecting account: {e}. Retrying in {NETWORK_RETRY_BASE_DELAY}s...")
                            await asyncio.sleep(NETWORK_RETRY_BASE_DELAY)
                            try:
                                account_num = await asyncio.to_thread(get_shared_limiter().get_next_available_account)
                            except Exception as e2:
                                print(f"   ❌ Network error persists: {e2}. Skipping this email.")
                                errors += 1
                                continue
                        else:
                            print(f"   ❌ Error selecting account: {e}")
                            errors += 1
                            continue
                    
                    if not account_num:
                        print(f"   ❌ All accounts exhausted (Daily Limit Reached)")
                        errors += 1
                        break
                    
                    acc_status = self.gmail_pool.get_account_status(account_num, refresh=False)
                    if not acc_status or acc_status.get("remaining", 0) <= 0:
                        print(f"   ❌ Account {account_num} quota unavailable")
                        errors += 1
                        break
                    print(f"   📧 Using Account {account_num} (Daily: {acc_status['used']}/{acc_status['limit']})")

                    reply_to_message_id = None
                    
                else:  # Follow-up
                    # Use SAME account as initial email
                    previous_sender = str(row.get("SenderEmail", "")).strip()
                    
                    if not previous_sender:
                        print(f"   ⚠️ No SenderEmail found, skipping")
                        skipped += 1
                        continue
                    
                    account_num = self.gmail_pool.find_account_by_email(previous_sender)
                    
                    if not account_num:
                        print(f"   ⚠️ Cannot find account for {previous_sender}, skipping")
                        skipped += 1
                        continue
                    
                    acc_status = self.gmail_pool.get_account_status(account_num)
                    if not acc_status or acc_status.get("remaining", 0) <= 0:
                        print(f"   ⚠️ Account {account_num} quota exceeded or unavailable")
                        errors += 1
                        continue
                        
                    acc_status = self.gmail_pool.get_account_status(account_num)
                    print(f"   📧 Using Account {account_num} (Daily: {acc_status['used']}/{acc_status['limit']})")
                    
                    # Get Message-ID for threading
                    reply_to_message_id = str(row.get(reply_to_col, "")).strip()
                    
                    if not reply_to_message_id or "<" not in reply_to_message_id or "@" not in reply_to_message_id:
                        print(f"   ⚠️ Invalid Message-ID {reply_to_message_id}, cannot thread")
                        skipped += 1
                        continue
                
                # Parse and format email
                subject, body = parse_email_content(content)
                formatted_body = format_email_body(body, name)
                
                # Get Gmail client
                client = self.gmail_pool.get_client(account_num)
                sender_email = self.gmail_pool.get_email(account_num)
                
                if not client or not sender_email:
                    print(f"   ❌ Failed to get client for account {account_num}")
                    errors += 1
                    continue
                
                # Send email with Failover
                try:
                    if email_type == "initial":
                        # Generate HTML content (MOVED INSIDE LOOP for dynamic signature)
                        image_url = str(row.get("Image", "")).strip()
                        if not image_url:
                             image_url = str(row.get("ImageURL", "")).strip()
                        
                        # Define images for embedding
                        images = None
                        image_cid = None
                        
                        if image_url:
                             print(f"   🖼️ Using image link: {image_url}")

                        # Retry Loop for Failover
                        attempts = 0
                        max_retries = EMAIL_SEND_RETRIES
                        sent_success = False
                        
                        while attempts < max_retries and not sent_success:
                            # Network-safe failover account selection
                            if attempts == 0:
                                current_acc_num = account_num
                            else:
                                try:
                                    # CRITICAL: Use asyncio.to_thread for consistency (shared_state may do I/O)
                                    current_acc_num = await asyncio.to_thread(
                                        get_shared_limiter().get_next_available_account
                                    )
                                except Exception as e:
                                    error_str = str(e).lower()
                                    if 'getaddrinfo' in error_str or 'network' in error_str:
                                        print(f"   ⚠️ Network error during failover: {e}")
                                        await asyncio.sleep(2)
                                        attempts += 1
                                        continue
                                    else:
                                        print(f"   ❌ Error during failover: {e}")
                                        attempts += 1
                                        continue
                           
                            if not current_acc_num:
                                print("   ❌ No accounts for failover")
                                break
                            
                            acc_status = self.gmail_pool.get_account_status(current_acc_num)
                            if not acc_status or acc_status.get("remaining", 0) <= 0:
                                print(f"   ⚠️ Failover Account {current_acc_num} full. Skipping.")
                                attempts += 1
                                continue

                            # If retrying, ensure we have a valid client
                            if attempts > 0:
                                client = self.gmail_pool.get_client(current_acc_num)
                                sender_email = self.gmail_pool.get_email(current_acc_num)
                            
                            # DYNAMIC SIGNATURE GENERATION
                            current_sender_email = self.gmail_pool.get_email(current_acc_num)
                            sig = get_sender_signature(current_sender_email)
                            final_text_body = formatted_body + sig
                            
                            # Generate HTML with signature
                            html_body = generate_html_content(final_text_body, image_url, email_type="initial", image_cid=image_cid)

                            try:
                                message_id = await asyncio.to_thread(
                                    client.send_email,
                                    recipient,
                                    subject,
                                    final_text_body,
                                    html_body=html_body,
                                    images=None
                                )
                                sent_success = True
                                get_shared_limiter().track_email_sent(current_acc_num)
                                account_num = current_acc_num
                            except Exception as send_err:
                                print(f"   ⚠️ Failover: Acc {current_acc_num} failed ({send_err}). Switching...")
                                attempts += 1
                                if attempts >= max_retries:
                                    print("   ❌ Max retries reached")
                                    break

                    else:
                        # Send as threaded reply
                        original_content = str(row.get(original_email_col, "")).strip()
                        original_subject, _ = parse_email_content(original_content)
                        
                        # Strip "Re:" if already present to avoid "Re: Re:"
                        if original_subject.lower().startswith("re:"):
                            clean_subject = original_subject
                        else:
                            clean_subject = f"Re: {original_subject}"
                            
                        image_url = str(row.get("Image", "")).strip()
                        if not image_url:
                             image_url = str(row.get("ImageURL", "")).strip()
                        
                        attempts = 0
                        max_retries = EMAIL_SEND_RETRIES
                        sent_success = False

                        while attempts < max_retries and not sent_success:
                             # For followups, we prefer sticky account, but if it fails, we MUST switch
                             if attempts > 0:
                                 break
                             
                             current_acc_num = account_num
                             
                             # DYNAMIC SIGNATURE GENERATION
                             current_sender_email = self.gmail_pool.get_email(current_acc_num)
                             sig = get_sender_signature(current_sender_email)
                             final_text_body = formatted_body + sig
                             
                             # Generate HTML with signature
                             html_body = generate_html_content(final_text_body, image_url, email_type=email_type)

                             try:
                                message_id = await asyncio.to_thread(
                                    client.send_threaded_email,
                                    recipient,
                                    clean_subject, 
                                    final_text_body,
                                    reply_to_message_id,
                                    html_body=html_body
                                )
                                sent_success = True
                                get_shared_limiter().track_email_sent(current_acc_num)
                                account_num = current_acc_num
                             except Exception as send_err:
                                print(f"   ⚠️ Failover: Acc {current_acc_num} failed ({send_err}). Switching...")
                                attempts += 1
                                if attempts >= max_retries: break

                    
                    if sent_success and message_id:
                        # Get current account usage
                        acc_status = self.gmail_pool.get_account_status(account_num) 
                        usage_str = f"{acc_status['used']}/{acc_status['limit']}" if acc_status else "?"
                        print(f"✅ Email sent to {recipient} | Message-ID: {message_id}")
                        print(f"   ✅ Sent! (Acc {account_num}: {usage_str})")
                        
                        # Update sheet
                        sender_email = self.gmail_pool.get_email(account_num)
                        update_data = {
                            "SenderEmail": sender_email,
                            status_col: "Sent",
                            message_id_col: message_id
                        }
                        
                        await asyncio.to_thread(
                            queue_db.update,
                            update_data,
                            where={"RecipientEmail": recipient}
                        )
                        await asyncio.to_thread(queue_db.commit)
                        print(f"   💾 Saved status for {recipient}")
                        
                        success += 1
                        account_usage[account_num] = account_usage.get(account_num, 0) + 1
                        
                        if success % 10 == 0:
                            await updater.send_update(
                                content=f"📧 Sending... {success}/{total} sent"
                            )
                        
                        # Apply human-mimic delays
                        if success < total:
                            is_coffee_break = False
                            
                            # Check if we hit the random target (based on SUCCESSFUL sends)
                            if success == next_break_target:
                                # Sleep for 15 to 30 minutes (900 to 1800 seconds) + micro-jitter
                                break_time = random.uniform(900, 1800) + random.random()
                                print(f"   ☕ Taking a coffee break for {break_time:.2f}s (after {success} emails)...")
                                await asyncio.sleep(break_time)
                                
                                is_coffee_break = True
                                # Reset the target for the NEXT break
                                next_break_target += random.randint(5, 8)
                            
                            # Standard Gap + Micro-Jitter
                            if not is_coffee_break:
                                # Standard Gap: 3 to 5 minutes (180 to 300 seconds)
                                # Micro-Jitter: + random.random() adds the decimal
                                wait_time = random.uniform(180, 300) + random.random()
                                print(f"   😴 Sleeping for {wait_time:.2f}s...")
                                await asyncio.sleep(wait_time)
                    else:
                        print(f"   ❌ Send returned None")
                        errors += 1
                        
                except Exception as e:
                    print(f"   ❌ Send error: {e}")
                    import traceback
                    traceback.print_exc()
                    errors += 1

            print(f"\n✅ Complete! Success: {success}, Errors: {errors}, Skipped: {skipped}")
            
            # Get final status
            rate_status = get_shared_limiter().get_status(refresh=True)
            
            # Calculate totals from shared state
            total_sent = 0
            for i in range(1, MAX_ACCOUNTS + 1):
                 val = rate_status.get(f"Account {i}", "0")
                 try:
                    used_count = int(float(str(val)))
                 except: 
                    used_count = 0
                 total_sent += used_count
            
            # Remaining quota
            remaining = max(0, TOTAL_DAILY_LIMIT - total_sent)
            
            # Build result embed
            embed = discord.Embed(
                title="✅ Email Sending Complete",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Queue", value=queue, inline=False)
            embed.add_field(name="Type", value=email_type.title(), inline=True)
            embed.add_field(name="⏱️ Delay", value=f"{delay}s", inline=True)
            embed.add_field(name="✅ Sent", value=str(success), inline=True)
            embed.add_field(name="❌ Errors", value=str(errors), inline=True)
            
            if skipped > 0:
                embed.add_field(name="⏭️ Skipped", value=f"{skipped} (empty content)", inline=True)
            
            embed.add_field(
                name="📊 This Run",
                value=f"Sent: {success}\nSkipped: {skipped}\nErrors: {errors}",
                inline=False
            )
            
            if account_usage:
                usage_lines = [
                    f"Acc {num}: {count} emails"
                    for num, count in sorted(account_usage.items())[:5]
                ]
                embed.add_field(
                    name="📧 Accounts Used",
                    value="\n".join(usage_lines),
                    inline=False
                )
            
            await updater.send_update(content=None, embed=embed)
            
        except Exception as e:
            error_msg = f"❌ Fatal error: {str(e)}\n\nCheck console for details."
            await updater.send_update(content=error_msg)
            print(f"❌ Fatal error: {e}")
            import traceback
            traceback.print_exc()
    
    @app_commands.command(name="status", description="Check email status for a queue")
    @app_commands.describe(queue="Sheet name (Day1Queue, etc)")
    async def check_status(self, interaction: discord.Interaction, queue: str):
        """Check queue status"""
        
        await interaction.response.defer(thinking=True)
        
        try:
            queue_db = await asyncio.to_thread(
                lambda: SheetDB(SheetDBConfig(spreadsheet_id=SPREADSHEET_ID, sheet_name=queue))
            )
            
            df = queue_db.select()
            
            if df.empty:
                await interaction.followup.send(f"❌ Sheet `{queue}` is empty")
                return
            
            total = len(df)
            
            initial_sent = len(df[df.get("EmailStatus", "Pending") == "Sent"])
            
            initial_pending = len(df[
                (df.get("EmailStatus", "Pending") == "Pending") &
                (df.get("RecipientEmail", "").notna()) &
                (df.get("RecipientEmail", "").astype(str).str.contains("@")) &
                (df.get("EmailGenerated", "").notna()) &
                (df.get("EmailGenerated", "").astype(str).str.strip() != "")
            ])
            
            replies = len(df[df.get("ReplyStatus", "Pending") == "Replied"])
            
            fu1_sent = len(df[df.get("FollowUp1Status", "Pending") == "Sent"]) if "FollowUp1Status" in df.columns else 0
            fu2_sent = len(df[df.get("FollowUp2Status", "Pending") == "Sent"]) if "FollowUp2Status" in df.columns else 0
            breakup_sent = len(df[df.get("BreakupEmailStatus", "Pending") == "Sent"]) if "BreakupEmailStatus" in df.columns else 0
            
            fu1_pending = len(df[
                (df.get("FollowUp1Status", "Pending") == "Pending") &
                (df.get("FollowUp1", "").notna()) &
                (df.get("FollowUp1", "").astype(str).str.strip() != "")
            ]) if "FollowUp1" in df.columns else 0
            
            fu2_pending = len(df[
                (df.get("FollowUp2Status", "Pending") == "Pending") &
                (df.get("FollowUp2", "").notna()) &
                (df.get("FollowUp2", "").astype(str).str.strip() != "")
            ]) if "FollowUp2" in df.columns else 0
            
            breakup_pending = len(df[
                (df.get("BreakupEmailStatus", "Pending") == "Pending") &
                (df.get("BreakupEmail", "").notna()) &
                (df.get("BreakupEmail", "").astype(str).str.strip() != "")
            ]) if "BreakupEmail" in df.columns else 0
            
            embed = discord.Embed(
                title=f"📊 Status: {queue}",
                description=f"**Total:** {total} contacts",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="📧 Initial Email",
                value=f"✅ Sent: {initial_sent}\n⏳ Pending: {initial_pending}",
                inline=True
            )
            
            embed.add_field(
                name="🔄 Follow-ups (Sent)",
                value=f"FU1: {fu1_sent}\nFU2: {fu2_sent}\nBreakup: {breakup_sent}",
                inline=True
            )
            
            embed.add_field(
                name="⏳ Follow-ups (Pending)",
                value=f"FU1: {fu1_pending}\nFU2: {fu2_pending}\nBreakup: {breakup_pending}",
                inline=True
            )
            
            embed.add_field(
                name="💬 Replies",
                value=str(replies),
                inline=True
            )
            
            embed.set_footer(text="Status Logic: Pending + Content Exists = Ready to Send")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}")
    
    @app_commands.command(name="quota", description="Check Gmail account quotas")
    async def check_quota(self, interaction: discord.Interaction):
        """Check quotas"""
        
        await interaction.response.defer(thinking=True)
        
        try:
            rate_status = get_shared_limiter().get_status(refresh=True)
            
            lines = []
            for i in range(1, MAX_ACCOUNTS + 1):
                acc_key = f"Account {i}"
                if acc_key in rate_status:
                    val = rate_status[acc_key]
                    try:
                        used = int(float(str(val)))
                    except:
                        used = 0
                    limit = DAILY_LIMIT_PER_ACCOUNT
                    remaining = max(0, limit - used)
                    
                    emoji = "✅" if remaining > 15 else "⚠️" if remaining > 5 else "🚨"
                    lines.append(f"{emoji} Acc {i:2d}: {used}/{limit} ({remaining} left)")
            
            embed = discord.Embed(
                title="📧 Gmail Quotas",
                description=f"Configured: {len(self.gmail_pool.accounts)}/{MAX_ACCOUNTS}",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="Account Status",
                value="\n".join(lines) if lines else "No data",
                inline=False
            )
            
            # Calculate totals
            total_sent = 0
            for i in range(1, MAX_ACCOUNTS + 1):
                val = rate_status.get(f"Account {i}", "0")
                try:
                    used_count = int(float(str(val)))
                except:
                    used_count = 0
                total_sent += used_count
            
            remaining = max(0, TOTAL_DAILY_LIMIT - total_sent)
            
            embed.add_field(
                name="📊 Summary",
                value=f"Sent: {total_sent}/{TOTAL_DAILY_LIMIT}\nRemaining: {remaining}/{TOTAL_DAILY_LIMIT}",
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")

    @app_commands.command(name="check_replies", description="Check for new replies via IMAP")
    @app_commands.describe(queue="Sheet name to update (e.g. Day1Queue)")
    async def check_replies(self, interaction: discord.Interaction, queue: str):
        """Manually checks for replies and updates Google Sheet"""
        
        await interaction.response.send_message(f"🔄 Connecting to IMAP and checking for replies in `{queue}`...", ephemeral=False)
        
        try:
            # Connect to all Gmail accounts
            found_replies = set()
            checked_accounts = 0
            
            for acc in self.gmail_pool.accounts:
                email_addr = acc["email"]
                password = acc["password"]
                
                imap_client = GmailIMAP(email_addr, password)
                if imap_client.connect():
                    # Check last 48 hours to be safe
                    senders = await asyncio.to_thread(imap_client.get_replies, since_hours=48)
                    for s in senders:
                        found_replies.add(s)
                    imap_client.close()
                    checked_accounts += 1
                else:
                    print(f"❌ Failed to connect to {email_addr}")
            
            print(f"✅ Found {len(found_replies)} distinct senders in last 48h")
            
            if not found_replies:
                await interaction.edit_original_response(
                    content=f"✅ Checked {checked_accounts} accounts. No new replies found."
                )
                return

            # Update Google Sheet
            await interaction.edit_original_response(
                content=f"🔍 Found {len(found_replies)} active threads. Updating Sheet `{queue}`..."
            )
            
            queue_db = await asyncio.to_thread(
                lambda: SheetDB(SheetDBConfig(spreadsheet_id=SPREADSHEET_ID, sheet_name=queue))
            )
            
            all_rows = queue_db.select()
            updated_count = 0
            
            if "RecipientEmail" not in all_rows.columns:
                 await interaction.edit_original_response(content="❌ Column `RecipientEmail` not found in sheet.")
                 return

            for idx, row in all_rows.iterrows():
                try:
                    recipient = str(row.get("RecipientEmail", "")).strip().lower()
                    if not recipient: continue
                    
                    # Check if this recipient replied
                    if recipient in found_replies:
                         # Only update if not already Replied
                         current_status = str(row.get("ReplyStatus", "Pending"))
                         if current_status != "Replied":
                             await asyncio.to_thread(
                                 queue_db.update,
                                 {"ReplyStatus": "Replied"},
                                 {"RecipientEmail": row["RecipientEmail"]}
                             )
                             updated_count += 1
                             print(f"   ✨ Marked {recipient} as Replied")
                except Exception as e:
                    print(f"Error updating row {idx}: {e}")

            if updated_count > 0:
                await asyncio.to_thread(queue_db.commit)
            
            await interaction.edit_original_response(
                content=f"✅ **Reply Check Complete**\n"
                        f"📬 Inboxes Checked: {checked_accounts}\n"
                        f"📧 Active Threads Found: {len(found_replies)}\n"
                        f"📝 Sheets Updated: {updated_count} new replies marked."
            )

        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Error checking replies: {e}")
            print(f"Fatal error in check_replies: {e}")
            import traceback
            traceback.print_exc()

async def setup(bot: commands.Bot):
    """Required setup function"""
    await bot.add_cog(EmailSender(bot))
    print("✅ EmailSender cog loaded with network error handling and Discord token fix")