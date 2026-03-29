"""
Email Handler - FIXED with Proper Threading Support
CRITICAL FIX: Proper Message-ID generation and reply threading
"""
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid, formatdate
from typing import Optional, Tuple, List, Dict
from datetime import datetime
import time
import random


def parse_email_content(email_text: str) -> Tuple[str, str]:
    """
    Parse email text into subject and body.
    
    Expected format:
    Subject: Your subject here
    
    Email body here...
    """
    if not email_text or not email_text.strip():
        return "Collaboration Opportunity", "Hello,\n\nI'd like to discuss a collaboration."
    
    lines = email_text.strip().split("\n")
    subject = "Collaboration Opportunity"
    body = email_text
    
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            # Body is everything after subject line (skip empty lines)
            remaining = lines[i+1:]
            body = "\n".join(line for line in remaining if line.strip())
            break
    
    return subject, body


def format_email_body(body: str, recipient_name: str = "") -> str:
    """
    Format email body with personalized greeting.
    CRITICAL: Returns FULL body without truncation
    """
    if not body or not body.strip():
        body = "I'd like to discuss a collaboration opportunity."
    
    # Split into lines but preserve ALL content
    lines = body.split("\n")
    formatted = []
    
    # Check if body already has a greeting
    has_greeting = False
    if lines:
        first_line_clean = lines[0].strip().lower()
        greetings = ["hi", "hello", "hey", "dear", "good morning", "good afternoon", "good evening"]
        
        for greeting in greetings:
            if first_line_clean.startswith(greeting):
                has_greeting = True
                break
    
    # Add greeting if missing
    if not has_greeting:
        if recipient_name and recipient_name.strip():
            first_name = recipient_name.split()[0]
            formatted.append(f"Hey {first_name},\n")
        else:
            formatted.append("Hey there,\n")
    
    # CRITICAL: Add ALL lines (no truncation)
    formatted.extend(lines)
    
    # Return complete body
    result = "\n".join(formatted)
    
    # Debug: Log length to catch truncation
    print(f"   📏 Formatted body: {len(result)} chars ({len(lines)} lines)")
    
    return result


def generate_html_content(text_body: str, image_url: str = "", email_type: str = "initial", image_cid: str = None) -> str:
    """
    OPTIMIZED: Faster loading, complete content, non-clickable images
    """
    # 1. Convert newlines to <br> (preserve all content)
    html_content = text_body.replace("\n", "<br>")
    
    # 2. Handle formatting tags
    html_content = html_content.replace("[bold]", "<b>").replace("[/bold]", "</b>")
    html_content = html_content.replace("[ul]", "<ul>").replace("[/ul]", "</ul>")
    html_content = html_content.replace("[li]", "<li>").replace("[/li]", "</li>")
    
    # 3. Email type specific links
    if email_type == "initial":
        html_content = html_content.replace(
            "Positioning Playbook", 
            '<a href="https://www.notion.so/The-Positioning-Playbook-3c5a0e17027d4fc9a72e68903f0a3be1?source=copy_link" style="color: #1a0dab; text-decoration: underline;">Positioning Playbook</a>'
        )
    elif email_type == "followup1":
        html_content = html_content.replace(
            "playbook", 
            '<a href="https://www.notion.so/The-Positioning-Playbook-3c5a0e17027d4fc9a72e68903f0a3be1?source=copy_link" style="color: #1a0dab; text-decoration: underline;">playbook</a>'
        )
        html_content = html_content.replace(
            "Fraser Briggs", 
            '<a href="https://sepia-beluga-17f.notion.site/Fraser-Briggs-2e7ae18e370580b2a489e8af152f6c07?source=copy_link" style="color: #1a0dab; text-decoration: underline;">Fraser Briggs</a>'
        )
    elif email_type == "followup2":
        html_content = html_content.replace(
            "Brent Richard", 
            '<a href="https://www.notion.so/Case-Study-The-Hybrid-Dad-Blueprint-Brent-Richard-6ba70e206664424591715617f87e2790?source=copy_link" style="color: #1a0dab; text-decoration: underline;">Brent Richard</a>'
        )
        import re
        html_content = re.sub(
            r'\\binfo!', 
            '<a href="https://calendly.com/sharkedge/30min" style="color: #1a0dab; text-decoration: underline;">info!</a>',
            html_content,
            flags=re.IGNORECASE
        )
    elif email_type == "breakup":
        html_content = html_content.replace(
            "Content Planner", 
            '<a href="https://sepia-beluga-17f.notion.site/Gemini-Guide-2e8ae18e370580f0b54ff9a5884587bc?source=copy_link" style="color: #1a0dab; text-decoration: underline;">Content Planner</a>'
        )
    
    # 4. NON-CLICKABLE, FAST-LOADING Image
    # CRITICAL: Inject AWS Image with NO attachment, NO clickability
    if "[Insert Image Here]" in html_content:
        if image_url and image_url.strip():
            clean_url = image_url.strip()
            
            # OPTIMIZATION: Add width hint for faster rendering
            img_html = f'''<div style="text-align: center; margin: 20px 0;">
    <img src="{clean_url}" 
         alt="Preview" 
         width="600"
         style="max-width: 100%; height: auto; display: block; margin: 0 auto; border-radius: 8px; border: 1px solid #ddd; pointer-events: none; user-select: none; cursor: default;"
         loading="eager"
         fetchpriority="high"
         draggable="false">
</div>'''
            html_content = html_content.replace("[Insert Image Here]", img_html)
            print(f"   🖼️ AWS Image: {clean_url[:50]}... (non-clickable, fast-load)")
        else:
            html_content = html_content.replace("[Insert Image Here]", "")
    
    # Remove leftover placeholders
    html_content = html_content.replace("[Add Button Here]", "")
    
    # 5. Signature for Follow-up 2
    if email_type == "followup2":
        html_content += """
<br>
<hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
<table cellpadding="0" cellspacing="0" border="0">
    <tr>
        <td style="padding-right: 15px; vertical-align: top;">
            <img src="https://res.cloudinary.com/dlliqtujb/image/upload/v1768382763/logo_jlqztm.png" 
                 width="50" height="50"
                 style="display: block; border-radius: 50%; pointer-events: none;"
                 loading="lazy" draggable="false">
        </td>
        <td style="vertical-align: top; font-family: 'Manrope', Arial, sans-serif;">
            <div style="font-size: 16px; font-weight: 700; color: #000;">Shark Edge</div>
            <div style="font-size: 14px; color: #666;">
                Visit our website <a href="https://sharkedge.media" style="color: #1a0dab; text-decoration: underline;">here</a>
            </div>
        </td>
    </tr>
</table>"""
    
    # 6. CRITICAL: Complete HTML with proper encoding
    final_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>Email</title>
    <style>
        body {{ 
            font-family: Helvetica, Arial, sans-serif; 
            font-size: 16px; 
            line-height: 1.6; 
            color: #333; 
            margin: 0; 
            padding: 0;
            -webkit-text-size-adjust: 100%;
            -ms-text-size-adjust: 100%;
        }}
        .container {{ 
            max-width: 600px; 
            margin: 0 auto; 
            padding: 20px; 
        }}
        img {{ 
            max-width: 100%; 
            height: auto; 
            display: block; 
        }}
        a {{ 
            color: #1a0dab; 
            text-decoration: underline; 
        }}
    </style>
</head>
<body>
    <div class="container">
        {html_content}
    </div>
</body>
</html>"""
    
    print(f"   📄 Final HTML: {len(final_html)} chars")
    return final_html


class EmailHandler:
    """
    Handles sending emails via Gmail SMTP
    CRITICAL FIX: Proper email threading with Message-ID storage
    """
    
    def __init__(self):
        self.smtp_host = "smtp.gmail.com"
        self.smtp_port = 587
        self.timeout = 20
        self.retry_attempts = 3
        self.retry_delay = 2
    
    def send_email(
        self,
        from_email: str,
        from_password: str,
        to_email: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        reply_to_message_id: Optional[str] = None
    ) -> str:
        """
        Send email via Gmail SMTP with optional threading.
        
        CRITICAL: Returns Message-ID that MUST be stored for follow-up threading
        
        Args:
            from_email: Sender email address
            from_password: App password for Gmail
            to_email: Recipient email address
            subject: Email subject line
            body: Email body (plain text)
            html_body: Email body (HTML)
            reply_to_message_id: Optional Message-ID for threading (follow-ups)
        
        Returns:
            Message-ID of sent email (STORE THIS IN GOOGLE SHEETS!)
        
        Raises:
            Exception: If email send fails after retries
        """
        for attempt in range(self.retry_attempts):
            try:
                # Create message
                msg = MIMEMultipart('alternative')
                msg['From'] = from_email
                msg['To'] = to_email
                
                # CRITICAL: Handle subject for threading
                if reply_to_message_id:
                    # Follow-up: Add "Re:" prefix if not already there
                    if not subject.lower().startswith("re:"):
                        msg['Subject'] = f"Re: {subject}"
                    else:
                        msg['Subject'] = subject
                else:
                    # Initial email: use subject as-is
                    msg['Subject'] = subject
                
                # Set proper date header
                msg['Date'] = formatdate(localtime=True)
                
                # CRITICAL: Generate unique Message-ID
                # Format: <unique-id@domain.com>
                domain = from_email.split('@')[1] if '@' in from_email else 'gmail.com'
                message_id = make_msgid(domain=domain)
                msg['Message-ID'] = message_id
                
                # CRITICAL: Threading headers for follow-ups
                if reply_to_message_id:
                    # Clean the Message-ID (ensure proper format)
                    clean_reply_id = reply_to_message_id.strip()
                    if not clean_reply_id.startswith('<'):
                        clean_reply_id = f"<{clean_reply_id}>"
                    if not clean_reply_id.endswith('>'):
                        clean_reply_id = f"{clean_reply_id}>"
                    
                    # Set threading headers
                    msg['In-Reply-To'] = clean_reply_id
                    msg['References'] = clean_reply_id
                    
                    print(f"   🔗 Threading: Reply-To={clean_reply_id}")
                
                # Attach body
                msg.attach(MIMEText(body, 'plain', 'utf-8'))

                if html_body:
                    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
                
                # Send via SMTP
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.timeout) as server:
                    server.set_debuglevel(0)
                    server.starttls()
                    server.login(from_email, from_password)
                    server.send_message(msg)
                
                print(f"   📧 Message-ID: {message_id}")
                return message_id
                
            except smtplib.SMTPAuthenticationError as e:
                raise Exception(f"Gmail auth failed for {from_email}: Check app password. Error: {e}")
            
            except smtplib.SMTPRecipientsRefused as e:
                raise Exception(f"Recipient {to_email} refused: {e}")
            
            except smtplib.SMTPServerDisconnected:
                if attempt < self.retry_attempts - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                    continue
                raise Exception("SMTP server disconnected after retries")
            
            except smtplib.SMTPException as e:
                if attempt < self.retry_attempts - 1:
                    time.sleep(self.retry_delay)
                    continue
                raise Exception(f"SMTP error: {str(e)}")
            
            except Exception as e:
                if attempt < self.retry_attempts - 1:
                    time.sleep(self.retry_delay)
                    continue
                raise Exception(f"Email send failed: {str(e)}")
    
    def send_bulk(
        self, 
        emails: List[Dict], 
        gmail_accounts: List[Dict],
        delay_seconds: int = 1,
        delay_variance: float = 0.2
    ) -> Tuple[int, int, List]:
        """
        Send bulk emails with account rotation, smart delays, and threading support.
        
        Args:
            emails: List of dicts with keys:
                - to_email: str
                - subject: str
                - body: str
                - reply_to_id: Optional[str] (for threading)
                - username: Optional[str] (for tracking)
            gmail_accounts: List of dicts with keys:
                - email: str
                - password: str
                - account_num: int
            delay_seconds: Base delay between emails (user-configurable)
            delay_variance: Random variance (e.g., 0.2 = ±20%)
            
        Returns:
            (success_count, error_count, results)
            results: List of dicts with:
                - status: "success" or "error"
                - to: recipient email
                - message_id: str (if success)
                - sender: sender email (if success)
                - error: str (if error)
                - username: str (if provided)
        """
        success_count = 0
        error_count = 0
        results = []
        
        print(f"\n📧 Sending {len(emails)} emails with {delay_seconds}s delay...")
        
        for i, email_data in enumerate(emails):
            # Rotate accounts (round-robin)
            account = gmail_accounts[i % len(gmail_accounts)]
            
            try:
                message_id = self.send_email(
                    from_email=account["email"],
                    from_password=account["password"],
                    to_email=email_data["to_email"],
                    subject=email_data["subject"],
                    body=email_data["body"],
                    reply_to_message_id=email_data.get("reply_to_id")
                )
                
                result = {
                    "status": "success",
                    "to": email_data["to_email"],
                    "message_id": message_id,
                    "sender": account["email"],
                    "account_num": account.get("account_num", 0)
                }
                
                if "username" in email_data:
                    result["username"] = email_data["username"]
                
                results.append(result)
                success_count += 1
                
                # Progress indicator
                if success_count % 10 == 0:
                    print(f"✅ Sent {success_count}/{len(emails)} emails...")
                
            except Exception as e:
                result = {
                    "status": "error",
                    "to": email_data["to_email"],
                    "error": str(e),
                    "account_num": account.get("account_num", 0)
                }
                
                if "username" in email_data:
                    result["username"] = email_data["username"]
                
                results.append(result)
                error_count += 1
                
                print(f"❌ Failed to send to {email_data['to_email']}: {e}")
            
            # Smart delay with variance
            if i < len(emails) - 1:
                variance = delay_seconds * delay_variance
                actual_delay = delay_seconds + random.uniform(-variance, variance)
                actual_delay = max(0.1, actual_delay)  # Minimum 0.1s
                time.sleep(actual_delay)
        
        print(f"\n✅ Bulk send complete: {success_count} sent, {error_count} failed")
        return success_count, error_count, results
    
    def test_connection(self, email: str, password: str) -> Tuple[bool, str]:
        """
        Test Gmail SMTP connection.
        
        Returns:
            (success, message)
        """
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(email, password)
            return True, "✅ Connection successful"
        except smtplib.SMTPAuthenticationError:
            return False, "❌ Authentication failed - check app password"
        except smtplib.SMTPConnectError:
            return False, "❌ Cannot connect to Gmail SMTP server"
        except Exception as e:
            return False, f"❌ Connection failed: {str(e)}"
    
    def test_all_accounts(self, accounts: List[Dict]) -> Dict[int, Tuple[bool, str]]:
        """
        Test all Gmail accounts.
        
        Args:
            accounts: List of dicts with 'email', 'password', 'account_num'
        
        Returns:
            Dict mapping account_num to (success, message)
        """
        results = {}
        
        print(f"\n🔍 Testing {len(accounts)} Gmail accounts...\n")
        
        for acc in accounts:
            account_num = acc.get("account_num", 0)
            email = acc["email"]
            password = acc["password"]
            
            success, message = self.test_connection(email, password)
            results[account_num] = (success, message)
            
            print(f"Account {account_num} ({email}): {message}")
        
        return results


# ======================== STANDALONE TESTING ========================
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    handler = EmailHandler()
    
    print("\n" + "="*60)
    print("EMAIL HANDLER TEST - WITH PROPER THREADING")
    print("="*60 + "\n")
    
    # Test first 3 accounts
    accounts = []
    for i in range(1, 4):
        email = os.getenv(f"EMAIL_ADDRESS_{i}")
        password = os.getenv(f"EMAIL_PASSWORD_{i}")
        
        if email and password:
            accounts.append({
                "email": email,
                "password": password,
                "account_num": i
            })
    
    if accounts:
        handler.test_all_accounts(accounts)
    else:
        print("❌ No Gmail accounts found in .env")
    
    print("\n" + "="*60)
    print("\n📖 CRITICAL: Message-ID Storage\n")
    print("""
When sending emails, you MUST store the returned Message-ID in Google Sheets!

Example workflow:

1. Send initial email:
   message_id = handler.send_email(...)
   
2. Store in Google Sheets:
   sheet.update({
       "SenderEmail": "account1@gmail.com",
       "InitialMessageID": message_id,  # ← STORE THIS!
       "EmailStatus": "Sent"
   })

3. Send follow-up (threaded):
   followup_message_id = handler.send_email(
       ...,
       reply_to_message_id=initial_message_id  # ← Use stored Message-ID
   )
   
4. Store follow-up Message-ID:
   sheet.update({
       "FollowUp1MessageID": followup_message_id,  # ← STORE THIS!
       "FollowUp1Status": "Sent"
   })

This ensures follow-ups appear as REPLIES to the initial email!
""")