"""
Gmail Client - Updated with Email Threading Support
Supports sending threaded emails (follow-ups as replies)
"""
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid
from datetime import datetime
from typing import Optional


class GmailClient:
    """Gmail SMTP client with threading support"""
    
    def __init__(self, email: str, password: str):
        """
        Initialize Gmail client
        
        Args:
            email: Gmail address
            password: App password (not regular password)
        """
        self.email = email
        self.password = password
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.timeout = 30
        
        # Test connection on init
        self._test_connection()
    
    def _test_connection(self):
        """Test SMTP connection"""
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.email, self.password)
            # print(f"✅ Gmail connection OK: {self.email}")
        except smtplib.SMTPAuthenticationError:
            raise Exception(f"❌ Gmail auth failed for {self.email}. Check app password!")
        except Exception as e:
            raise Exception(f"❌ Gmail connection failed: {e}")
    
    def send_email(
        self, 
        to_email: str, 
        subject: str, 
        body: str,
        html_body: Optional[str] = None,
        images: Optional[dict] = None,  # {cid: filepath}
        max_retries: int = 3
    ) -> Optional[str]:
        """
        Send a regular email (Text + HTML)
        
        Args:
            to_email: Recipient email
            subject: Email subject
            body: Email body (plain text fallback)
            html_body: Email body (HTML)
            images: Dict of {cid: filepath} for inline images
            max_retries: Number of retry attempts
        
        Returns:
            Message-ID if successful, None otherwise
        """
        for attempt in range(max_retries):
            try:
                # Create message
                # Always use 'alternative' (text + HTML, NO attachments)
                msg = MIMEMultipart('alternative')
                msg['From'] = self.email
                msg['To'] = to_email
                msg['Subject'] = subject
                msg['Date'] = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
                
                # Generate Message-ID (for threading)
                domain = self.email.split('@')[1]
                message_id = make_msgid(domain=domain)
                msg['Message-ID'] = message_id
                
                # Attach parts (Text first, then HTML)
                if body:
                    msg.attach(MIMEText(body, 'plain', 'utf-8'))
                
                if html_body:
                    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
                
                # NEVER attach images - they are now embedded via external URLs
                if images:
                    print(f"   ⚠️ Images ignored (using direct URLs)")

                # Send via SMTP
                with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=self.timeout) as server:
                    server.set_debuglevel(0)
                    server.starttls()
                    server.login(self.email, self.password)
                    server.send_message(msg)
                
                print(f"✅ Email sent to {to_email} | Message-ID: {message_id}")
                return message_id
                
            except smtplib.SMTPAuthenticationError as e:
                raise Exception(f"Gmail auth failed: {e}")
            
            except smtplib.SMTPRecipientsRefused as e:
                print(f"❌ Recipient {to_email} refused: {e}")
                return None
            
            except smtplib.SMTPServerDisconnected:
                if attempt < max_retries - 1:
                    print(f"⚠️ SMTP disconnected, retrying... ({attempt + 1}/{max_retries})")
                    time.sleep(2 * (attempt + 1))
                    continue
                print(f"❌ SMTP disconnected after {max_retries} attempts")
                return None
            
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"⚠️ Send failed, retrying... ({attempt + 1}/{max_retries}): {e}")
                    time.sleep(2)
                    continue
                print(f"❌ Email send failed: {e}")
                return None
        
        return None
    
    def send_threaded_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        reply_to_message_id: str,
        html_body: Optional[str] = None,
        max_retries: int = 3
    ) -> Optional[str]:
        """
        Send a threaded email (reply to previous email)
        
        Args:
            to_email: Recipient email
            subject: Email subject (should match or start with "Re:")
            body: Email body
            reply_to_message_id: Message-ID of the email to reply to
            html_body: HTML body
            max_retries: Number of retry attempts
        
        Returns:
            Message-ID if successful, None otherwise
        """
        for attempt in range(max_retries):
            try:
                # Create message
                msg = MIMEMultipart('alternative')
                msg['From'] = self.email
                msg['To'] = to_email
                
                # Add "Re:" prefix if not present (standard email convention)
                if not subject.lower().startswith("re:"):
                    msg['Subject'] = f"Re: {subject}"
                else:
                    msg['Subject'] = subject
                
                msg['Date'] = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
                
                # Generate new Message-ID
                domain = self.email.split('@')[1]
                message_id = make_msgid(domain=domain)
                msg['Message-ID'] = message_id
                
                # CRITICAL: Threading headers
                # In-Reply-To: Points to the immediate parent message
                # References: Contains the full thread history
                msg['In-Reply-To'] = reply_to_message_id
                msg['References'] = reply_to_message_id
                
                # Attach parts
                msg.attach(MIMEText(body, 'plain', 'utf-8'))
                if html_body:
                    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
                
                # Send via SMTP
                with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=self.timeout) as server:
                    server.set_debuglevel(0)
                    server.starttls()
                    server.login(self.email, self.password)
                    server.send_message(msg)
                
                print(f"✅ Threaded email sent to {to_email}")
                print(f"   Reply-To: {reply_to_message_id}")
                print(f"   Message-ID: {message_id}")
                return message_id
                
            except smtplib.SMTPAuthenticationError as e:
                raise Exception(f"Gmail auth failed: {e}")
            
            except smtplib.SMTPRecipientsRefused as e:
                print(f"❌ Recipient {to_email} refused: {e}")
                return None
            
            except smtplib.SMTPServerDisconnected:
                if attempt < max_retries - 1:
                    print(f"⚠️ SMTP disconnected, retrying... ({attempt + 1}/{max_retries})")
                    time.sleep(2 * (attempt + 1))
                    continue
                print(f"❌ SMTP disconnected after {max_retries} attempts")
                return None
            
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"⚠️ Send failed, retrying... ({attempt + 1}/{max_retries}): {e}")
                    time.sleep(2)
                    continue
                print(f"❌ Threaded email send failed: {e}")
                return None
        
        return None
    
    def test_send(self, to_email: str) -> bool:
        """
        Send a test email to verify configuration
        
        Args:
            to_email: Test recipient email
        
        Returns:
            True if successful, False otherwise
        """
        subject = "Test Email from Shark Edge Media"
        body = """
Hi,

This is a test email to verify Gmail configuration.

If you receive this, the email system is working correctly!

Best regards,
Shark Edge Media
"""
        
        message_id = self.send_email(to_email, subject, body)
        return message_id is not None


# ======================== TESTING ========================
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    print("\n" + "="*60)
    print("GMAIL CLIENT TEST")
    print("="*60 + "\n")
    
    # Test first account
    email = os.getenv("EMAIL_ADDRESS_1")
    password = os.getenv("EMAIL_PASSWORD_1")
    
    if not email or not password:
        print("❌ EMAIL_ADDRESS_1 or EMAIL_PASSWORD_1 not found in .env")
        exit(1)
    
    try:
        print(f"Testing account: {email}\n")
        
        client = GmailClient(email, password)
        
        print("\n✅ Client initialized successfully")
        print(f"   Email: {client.email}")
        print(f"   SMTP: {client.smtp_server}:{client.smtp_port}")
        
        print("\n" + "="*60)
        print("\n📖 USAGE EXAMPLES:\n")
        
        print("""
# Send regular email
client = GmailClient("your_email@gmail.com", "your_app_password")
message_id = client.send_email(
    to_email="recipient@example.com",
    subject="Collaboration Opportunity",
    body="Hi, I'd like to discuss..."
)

# Send threaded follow-up (appears as reply)
followup_message_id = client.send_threaded_email(
    to_email="recipient@example.com",
    subject="Collaboration Opportunity",  # Will add "Re:" prefix
    body="Following up on my previous email...",
    reply_to_message_id=message_id  # From initial email
)

# Test connection
success = client.test_send("your_test_email@example.com")
""")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()