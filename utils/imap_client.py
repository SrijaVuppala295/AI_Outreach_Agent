import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
import re

class GmailIMAP:
    """
    Handles IMAP connections to Gmail for checking replies.
    """
    def __init__(self, email_addr, password):
        self.email_addr = email_addr
        self.password = password
        self.imap_server = "imap.gmail.com"
        self.imap = None

    def connect(self):
        """Connect to Gmail IMAP"""
        try:
            self.imap = imaplib.IMAP4_SSL(self.imap_server)
            self.imap.login(self.email_addr, self.password)
            return True
        except Exception as e:
            print(f"❌ IMAP Connection failed for {self.email_addr}: {e}")
            return False

    def close(self):
        """Close connection"""
        if self.imap:
            try:
                self.imap.close()
                self.imap.logout()
            except:
                pass

    def get_replies(self, since_hours=24):
        """
        Fetch emails received in the last X hours.
        Returns list of sender emails.
        """
        if not self.imap:
            return []

        found_senders = []
        try:
            self.imap.select("INBOX")

            # Calculate date for search
            date_since = (datetime.now() - timedelta(hours=since_hours)).strftime("%d-%b-%Y")
            
            # Search for all emails since date
            status, messages = self.imap.search(None, f'(SINCE "{date_since}")')
            
            if status != "OK":
                return []

            email_ids = messages[0].split()
            
            for form_id in email_ids:
                try:
                    # Fetch email header
                    _, msg_data = self.imap.fetch(form_id, "(RFC822.HEADER)")
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            
                            # Extract sender
                            from_header = msg.get("From")
                            if from_header:
                                # Extract email from "Name <email@example.com>"
                                sender_email = ""
                                if "<" in from_header:
                                    sender_email = from_header.split("<")[1].split(">")[0]
                                else:
                                    sender_email = from_header.strip()
                                
                                if sender_email:
                                    sender_lower = sender_email.lower()
                                    # Filter out self (loops) and system messages
                                    if (sender_lower != self.email_addr.lower() and 
                                        "mailer-daemon" not in sender_lower and 
                                        "no-reply" not in sender_lower):
                                        found_senders.append(sender_lower)
                except Exception as e:
                    print(f"Error parsing email {form_id}: {e}")
                    continue
                    
        except Exception as e:
            print(f"Error fetching replies for {self.email_addr}: {e}")

        return found_senders
