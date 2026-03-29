"""
Discord Email Sender Commands - Updated with Threading & Time Delays
Uses utils/email_handler.EmailHandler for real email sending
Supports unified threading and user-configurable delays
"""
import os
import time
import asyncio
from datetime import datetime
from typing import Literal

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

from utils.SheetDB import SheetDB, SheetDBConfig
from utils.email_handler import EmailHandler, parse_email_content, format_email_body, generate_html_content
from utils.email_rate_limiter import track_gmail_send, get_rate_limit_status, get_available_gmail_accounts

load_dotenv()
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
MY_GUILD_ID = int(os.getenv("MY_GUILD_ID", "0"))


class EmailSenderAlt(commands.Cog):
    """Email sending commands with unified threading"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.email_handler = EmailHandler()

        # Load Gmail accounts
        self.gmail_accounts = []
        for i in range(1, 4):  # Updated to 3 accounts
            email = os.getenv(f"EMAIL_ADDRESS_{i}")
            password = os.getenv(f"EMAIL_PASSWORD_{i}")
            if email and password:
                self.gmail_accounts.append({
                    "email": email,
                    "password": password,
                    "account_num": i
                })

        print(f"✅ Loaded {len(self.gmail_accounts)}/3 Gmail accounts")
        if not self.gmail_accounts:
            print("⚠️ WARNING: No Gmail accounts configured!")
        
        # Sender mapping for unified threading
        self.sender_mapping = {}

    @app_commands.command(name="send", description="Send initial emails from queue")
    @app_commands.describe(
        queue="Sheet name (e.g. Day1Queue)", 
        count="Number of emails to send (1–500)",
        delay="Delay between emails in seconds (0-300)"
    )
    @app_commands.guilds(MY_GUILD_ID)
    async def send_emails(self, interaction: discord.Interaction, queue: str, count: int, delay: int = 1):
        if count <= 0 or count > 500:
            await interaction.response.send_message("❌ Count must be between 1 and 500", ephemeral=True)
            return
        
        if delay < 0 or delay > 300:
            await interaction.response.send_message("❌ Delay must be between 0 and 300 seconds", ephemeral=True)
            return

        await interaction.response.send_message(
            f"📧 Starting email send from `{queue}` (count={count}, delay={delay}s)…",
            ephemeral=False
        )
        self.bot.loop.create_task(self._send_emails_background(interaction, queue, count, "initial", delay))

    @app_commands.command(name="sendfollow", description="Send follow-up emails")
    @app_commands.describe(
        queue="Sheet name (Day1Queue, etc.)",
        followup="Follow-up number (1–3)",
        count="Number of emails to send (1–500)",
        delay="Delay between emails in seconds (0-300)"
    )
    @app_commands.guilds(MY_GUILD_ID)
    async def send_followup(
        self,
        interaction: discord.Interaction,
        queue: str,
        followup: Literal[1, 2, 3],
        count: int,
        delay: int = 1
    ):
        if count <= 0 or count > 500:
            await interaction.response.send_message("❌ Count must be 1–500", ephemeral=True)
            return
        
        if delay < 0 or delay > 300:
            await interaction.response.send_message("❌ Delay must be 0-300 seconds", ephemeral=True)
            return

        await interaction.response.send_message(
            f"📨 Starting Follow-up {followup} send from `{queue}` (count={count}, delay={delay}s)…",
            ephemeral=False
        )
        self.bot.loop.create_task(self._send_emails_background(interaction, queue, count, f"followup{followup}", delay))

    async def _send_emails_background(self, interaction, queue, count, email_type, delay):
        """Runs in background with unified threading"""
        try:
            print(f"\n🚀 [DEBUG] Background started → queue={queue}, type={email_type}, count={count}, delay={delay}s")
            await interaction.edit_original_response(content=f"📊 Loading sheet `{queue}`…")

            queue_db = await asyncio.to_thread(lambda: SheetDB(SheetDBConfig(spreadsheet_id=SPREADSHEET_ID, sheet_name=queue)))
            all_rows = await asyncio.to_thread(queue_db.select)
            print(f"🔁 [DEBUG] Loaded {len(all_rows)} rows from '{queue}'")

            if all_rows.empty:
                await interaction.edit_original_response(content=f"❌ Sheet `{queue}` is empty")
                return

            # Filter data based on email type
            await interaction.edit_original_response(content="🔍 Filtering emails…")
            
            if email_type == "initial":
                email_col = "EmailGenerated" if "EmailGenerated" in all_rows.columns else "Email"
                status_col = "EmailStatus"
                message_id_col = "InitialMessageID"
                reply_col = None
                
                # SIMPLIFIED: Check content exists AND status is Pending
                filtered = all_rows[
                    (all_rows[email_col].notna()) & 
                    (all_rows[email_col].astype(str).str.strip() != "") &
                    (all_rows.get(status_col, "Pending").fillna("Pending") == "Pending")
                ]
                
            else:  # Follow-up
                fu_num = email_type[-1]
                email_col = f"FollowUp{fu_num}"
                status_col = f"FollowUp{fu_num}Status"
                message_id_col = f"FollowUp{fu_num}MessageID"
                
                # Get reply-to Message-ID
                if fu_num == "1":
                    reply_col = "InitialMessageID"
                else:
                    reply_col = f"FollowUp{int(fu_num)-1}MessageID"
                
                # SIMPLIFIED: Check content exists, status is Pending, and has threading info
                filtered = all_rows[
                    (all_rows[email_col].notna()) & 
                    (all_rows[email_col].astype(str).str.strip() != "") &
                    (all_rows.get(status_col, "Pending").fillna("Pending") == "Pending") & 
                    (all_rows.get("ReplyStatus", "Pending").fillna("Pending") == "Pending") &
                    (all_rows.get("SenderEmail", "").notna()) &
                    (all_rows.get("SenderEmail", "").astype(str).str.strip() != "") &
                    (all_rows.get(reply_col, "").notna()) &
                    (all_rows.get(reply_col, "").astype(str).str.strip() != "")
                ]

            if filtered.empty:
                await interaction.edit_original_response(content=f"❌ No `{email_type}` emails ready in `{queue}`")
                return

            to_send = filtered.head(count)
            print(f"📋 [DEBUG] Ready to send {len(to_send)} emails.")
            await interaction.edit_original_response(content=f"📧 Sending {len(to_send)} emails with {delay}s delay…")

            # Prepare email list with threading
            emails_to_send = []
            username_map = {}
            sender_map = {}  # Track sender per username
            
            for _, row in to_send.iterrows():
                recipient = row.get("RecipientEmail", "").strip()
                content = row.get(email_col, "").strip()
                username = row.get("IgUsername", "unknown")
                
                if not recipient or not content:
                    continue
                
                subject, body = parse_email_content(content)
                # UNIFIED THREADING: Get reply-to Message-ID and FORCE SUBJECT
                reply_id = None
                assigned_account = None
                final_subject = subject  # Default to parsed subject
                
                if email_type == "initial":
                    pass  # Subject is fine as-is
                else:
                    # For follow-ups:
                    # 1. Use SAME sender as initial
                    # 2. Use SAME subject as initial (prefixed with Re:)
                    previous_sender = row.get("SenderEmail", "").strip()
                    
                    # Force Subject Consistency
                    original_content = str(row.get("EmailGenerated", "")).strip()
                    if original_content:
                        orig_sub, _ = parse_email_content(original_content)
                        if not orig_sub.lower().startswith("re:"):
                            final_subject = f"Re: {orig_sub}"
                        else:
                            final_subject = orig_sub
                    
                    if not previous_sender:
                        print(f"⚠️ No SenderEmail for {username}, skipping")
                        continue
                        
                    # Find account number from email
                    for acc in self.gmail_accounts:
                        if acc["email"] == previous_sender:
                            assigned_account = acc
                            break
                    
                    if not assigned_account:
                        print(f"⚠️ Cannot find account for {previous_sender}, skipping")
                        continue
                    
                    # Get Message-ID for threading
                    if reply_col and reply_col in row:
                        reply_id = row.get(reply_col, "").strip()
                        if not reply_id:
                            print(f"⚠️ No {reply_col} for {username}, skipping")
                            continue
                
                # VALIDATION & GENERATION
                # -----------------------
                if len(content) < 100:
                    print(f"   ⚠️ WARNING: Content suspiciously short for {username}: {len(content)} chars")
                
                # Get Image URL
                image_url = row.get("Image", "").strip()

                # Format Body (Text)
                formatted_body = format_email_body(body, username)
                
                # CRITICAL: Check for truncation
                if len(formatted_body) < len(body) * 0.8:
                    print(f"   🚨 TRUNCATION DETECTED: {len(body)} -> {len(formatted_body)} chars")

                # Generate HTML
                # Note: format_email_body adds signature, so we use formatted_body directly
                html_body = generate_html_content(formatted_body, image_url, email_type=email_type)
                
                if len(html_body) < 500:
                    print(f"   🚨 HTML TOO SHORT: {len(html_body)} chars - possible truncation!")

                email_data = {
                    "to_email": recipient,
                    "subject": final_subject,
                    "body": formatted_body,
                    "html_body": html_body,
                    "reply_to_id": reply_id,
                    "username": username,
                    "assigned_account": assigned_account 
                }
                
                emails_to_send.append(email_data)
                username_map[recipient] = username
                
                if assigned_account:
                    sender_map[username] = assigned_account["email"]

            # Send emails with tracking
            success, error = 0, 0
            results = []
            account_idx = 0
            available = get_available_gmail_accounts()
            
            for i, email_data in enumerate(emails_to_send):
                # Select account
                if email_data["assigned_account"]:
                    # Follow-up: use assigned account (same as initial)
                    acc = email_data["assigned_account"]
                    acc_num = acc["account_num"]
                else:
                    # Initial: use round-robin from available accounts
                    if not available:
                        print("❌ All accounts exhausted")
                        break
                    
                    # STRICT ROTATION: Use (i) % available to rotate for EACH email
                    acc_num = available[(account_idx + i) % len(available)]
                    acc = self.gmail_accounts[acc_num - 1]
                
                # Track quota
                if not track_gmail_send(acc_num):
                    print(f"⚠️ Account {acc_num} quota exceeded")
                    if email_type == "initial":
                        available = get_available_gmail_accounts()
                        if not available:
                            break
                        account_idx += 1
                        continue
                    else:
                        error += 1
                        continue

                try:
                    msg_id = self.email_handler.send_email(
                        from_email=acc["email"],
                        from_password=acc["password"],
                        to_email=email_data["to_email"],
                        subject=email_data["subject"],
                        body=email_data["body"],
                        html_body=email_data["html_body"],
                        reply_to_message_id=email_data.get("reply_to_id")
                    )
                    
                    results.append({
                        "status": "success",
                        "to": email_data["to_email"],
                        "sender": acc["email"],
                        "message_id": msg_id,
                        "username": email_data["username"]
                    })
                    
                    print(f"📨 [DEBUG] Sent → {email_data['to_email']} via {acc['email']}")
                    success += 1
                    
                    # Store sender mapping for follow-ups
                    if email_type == "initial":
                        sender_map[email_data["username"]] = acc["email"]
                    
                    # Apply user-specified delay
                    if i < len(emails_to_send) - 1:
                        await asyncio.sleep(delay)
                    
                    if email_type == "initial":
                        account_idx += 1
                    
                except Exception as e:
                    results.append({
                        "status": "error",
                        "to": email_data["to_email"],
                        "error": str(e),
                        "username": email_data["username"]
                    })
                    print(f"⚠️ [DEBUG] Send failed → {email_data['to_email']} : {e}")
                    error += 1

            print(f"✅ [DEBUG] Sending complete. Success={success}, Errors={error}")

            # Update SheetDB - SIMPLIFIED: No date column
            for r in results:
                if r["status"] == "success":
                    uname = r["username"]
                    update = {
                        "SenderEmail": r["sender"],
                        status_col: "Sent",
                        message_id_col: r["message_id"]
                    }
                    queue_db.update(update, where={"IgUsername": uname})
            
            await asyncio.to_thread(queue_db.commit)

            # Build embed summary
            rate = get_rate_limit_status()
            summary = rate.get("summary", {}).get("gmail", {})
            
            embed = discord.Embed(
                title="✅ Email Sending Complete",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Queue", value=queue, inline=False)
            embed.add_field(name="Type", value=email_type.title(), inline=True)
            embed.add_field(name="⏱️ Delay", value=f"{delay}s", inline=True)
            embed.add_field(name="✅ Sent", value=str(success), inline=True)
            embed.add_field(name="❌ Errors", value=str(error), inline=True)
            embed.add_field(
                name="📊 Gmail Used",
                value=f"{summary.get('total_used', 0)}/500 ({summary.get('total_remaining', 0)} remaining)",
                inline=False
            )
            
            await interaction.edit_original_response(content=None, embed=embed)

        except Exception as e:
            print(f"❌ [DEBUG] Background send exception: {e}")
            import traceback
            traceback.print_exc()
            await interaction.edit_original_response(content=f"❌ Error: {str(e)}\nCheck logs for details.")


async def setup(bot: commands.Bot):
    await bot.add_cog(EmailSenderAlt(bot))
    print("✅ EmailSenderAlt cog loaded with threading support")