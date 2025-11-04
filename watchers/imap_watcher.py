"""
IMAP Watcher - Monitors email accounts for new messages
Sends notifications with optional LLM-based summarization

Version 0.3.3 (c) Kunologist
"""

import asyncio
import email
import imaplib
from email.header import decode_header
from typing import Any, Coroutine, Optional

from loguru import logger

from notifier import Notifier
from plugins.llm import query as llm_query


# Default configuration values
DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_SUMMARY_PROMPT = (
    "Please summarize the following email content into a brief notification. "
    "Ensure that your output is only one sentence long and captures the main idea effectively."
)


class EmailAccount:
    """Represents a single email account to monitor."""

    def __init__(self, account_config: dict):
        """
        Initialize an email account monitor.

        Args:
            account_config: Configuration dict for this specific account
        """
        self.server = account_config["server"]
        self.username = account_config["username"]
        self.password = account_config["password"]
        self.enabled = account_config.get("enabled", True)
        self.enable_summary = account_config.get("enable_summary", False)

        # Get summary configuration
        summary_config = account_config.get("summary", {})
        self.summary_prompt = summary_config.get("prompt", DEFAULT_SUMMARY_PROMPT)
        self.summary_model = summary_config.get("model_name")

        # Track seen message IDs to avoid duplicates
        self.seen_message_ids: set[str] = set()

        # Connection state
        self.mail: Optional[imaplib.IMAP4_SSL] = None

    def __str__(self) -> str:
        """String representation of the account."""
        return f"{self.username}@{self.server}"

    async def connect(self) -> bool:
        """
        Connect to the IMAP server.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info(f"Connecting to {self}")
            self.mail = await asyncio.to_thread(imaplib.IMAP4_SSL, self.server)
            await asyncio.to_thread(self.mail.login, self.username, self.password)
            logger.info(f"Successfully connected to {self}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {self}: {e}")
            self.mail = None
            return False

    async def disconnect(self) -> None:
        """Disconnect from the IMAP server."""
        if self.mail:
            try:
                await asyncio.to_thread(self.mail.logout)
                logger.debug(f"Disconnected from {self}")
            except Exception as e:
                logger.warning(f"Error disconnecting from {self}: {e}")
            finally:
                self.mail = None

    async def check_new_emails(self) -> list[dict[str, Any]]:
        """
        Check for new emails in the inbox.

        Returns:
            List of email data dictionaries
        """
        if not self.mail:
            if not await self.connect():
                return []

        try:
            # Select inbox
            await asyncio.to_thread(self.mail.select, "INBOX")

            # Search for unseen emails
            status, message_ids = await asyncio.to_thread(
                self.mail.search, None, "UNSEEN"
            )

            if status != "OK":
                logger.warning(f"Failed to search emails for {self}: {status}")
                return []

            # Parse message IDs
            message_id_list = message_ids[0].split()

            if not message_id_list:
                return []

            logger.info(f"Found {len(message_id_list)} new email(s) for {self}")

            # Fetch and parse emails
            new_emails = []
            for msg_id in message_id_list:
                email_data = await self.fetch_email(msg_id)
                if email_data:
                    new_emails.append(email_data)

            return new_emails

        except Exception as e:
            logger.error(f"Error checking emails for {self}: {e}", exc_info=True)
            # Disconnect on error to force reconnect next time
            await self.disconnect()
            return []

    async def fetch_email(self, msg_id: bytes) -> Optional[dict[str, Any]]:
        """
        Fetch and parse a single email.

        Args:
            msg_id: Email message ID

        Returns:
            Dictionary with email data or None if failed
        """
        try:
            # Fetch the email
            status, msg_data = await asyncio.to_thread(
                self.mail.fetch, msg_id, "(RFC822)"
            )

            if status != "OK":
                logger.warning(f"Failed to fetch email {msg_id} from {self}")
                return None

            # Parse the email
            raw_email = msg_data[0][1]
            email_message = email.message_from_bytes(raw_email)

            # Extract message ID (for deduplication)
            message_id = email_message.get("Message-ID", f"unknown-{msg_id.decode()}")

            # Skip if we've already seen this email
            if message_id in self.seen_message_ids:
                return None

            self.seen_message_ids.add(message_id)

            # Extract subject
            subject = self.decode_header_value(
                email_message.get("Subject", "No Subject")
            )

            # Extract sender
            from_header = self.decode_header_value(email_message.get("From", "Unknown"))

            # Extract body
            body = self.extract_body(email_message)

            return {
                "message_id": message_id,
                "subject": subject,
                "from": from_header,
                "body": body,
                "date": email_message.get("Date", "Unknown"),
            }

        except Exception as e:
            logger.error(
                f"Error fetching email {msg_id} from {self}: {e}", exc_info=True
            )
            return None

    @staticmethod
    def decode_header_value(header_value: Optional[str]) -> str:
        """
        Decode email header value (handles encoded subjects/names).

        Args:
            header_value: Raw header value

        Returns:
            Decoded string
        """
        if not header_value:
            return ""

        decoded_parts = []
        for part, encoding in decode_header(header_value):
            if isinstance(part, bytes):
                decoded_parts.append(part.decode(encoding or "utf-8", errors="ignore"))
            else:
                decoded_parts.append(part)

        return "".join(decoded_parts)

    @staticmethod
    def extract_body(email_message: email.message.Message) -> str:
        """
        Extract the email body text.

        Args:
            email_message: Parsed email message

        Returns:
            Email body as string
        """
        body = ""

        if email_message.is_multipart():
            # Iterate through email parts
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                # Extract text/plain or text/html
                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode(errors="ignore")
                            break  # Prefer plain text
                    except Exception:
                        continue
                elif content_type == "text/html" and not body:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode(errors="ignore")
                    except Exception:
                        continue
        else:
            # Simple email, not multipart
            try:
                payload = email_message.get_payload(decode=True)
                if payload:
                    body = payload.decode(errors="ignore")
            except Exception:
                body = str(email_message.get_payload())

        return body.strip()


class ImapMonitor:
    """Monitors multiple email accounts and sends notifications for new emails."""

    def __init__(self, notifier: Notifier, config: dict):
        """
        Initialize the IMAP monitor.

        Args:
            notifier: Notifier instance for sending alerts
            config: Configuration dictionary for the IMAP watcher
        """
        self.notifier = notifier
        self.config = config

        # Load configuration with defaults
        self.interval = config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)

        # Initialize email accounts
        self.accounts: list[EmailAccount] = []
        watching_configs = config.get("watching", [])

        for account_config in watching_configs:
            if not account_config.get("enabled", True):
                logger.info(
                    f"Skipping disabled account: {account_config.get('username')}@{account_config.get('server')}"
                )
                continue

            account = EmailAccount(account_config)
            self.accounts.append(account)
            logger.info(f"Added account to watch: {account}")

    async def process_email(
        self, account: EmailAccount, email_data: dict[str, Any]
    ) -> None:
        """
        Process a new email and send notification.

        Args:
            account: EmailAccount that received the email
            email_data: Dictionary with email data
        """
        subject = email_data["subject"]
        sender = email_data["from"]
        body = email_data["body"]

        # Prepare notification content in markdown
        if account.enable_summary and body:
            # Use LLM to summarize the email
            logger.info(f"Summarizing email from {sender}")
            try:
                summary = await llm_query(
                    message=f"Subject: {subject}\n\nBody:\n{body[:2000]}",  # Limit body length
                    model=account.summary_model,
                    system_message=account.summary_prompt,
                )
                # Format as markdown
                markdown_content = f"""# 📧 {subject}

**From:** {sender}

{summary}
"""
            except Exception as e:
                logger.error(f"Failed to summarize email: {e}")
                # Fallback to original content
                truncated_body = body[:500]
                if len(body) > 500:
                    truncated_body += "..."
                markdown_content = f"""# 📧 {subject}

**From:** {sender}

{truncated_body}
"""
        else:
            # Use original content (truncated)
            truncated_body = body[:500]
            if len(body) > 500:
                truncated_body += "..."
            markdown_content = f"""# 📧 {subject}

**From:** {sender}

{truncated_body}
"""

        # Send notification
        await self.notifier.send(markdown_content)

        logger.info(f"Sent notification for email from {sender}")

    async def check_all_accounts(self) -> None:
        """Check all configured email accounts for new messages."""
        for account in self.accounts:
            try:
                new_emails = await account.check_new_emails()

                for email_data in new_emails:
                    await self.process_email(account, email_data)

            except Exception as e:
                logger.error(f"Error checking account {account}: {e}", exc_info=True)

    async def monitor_loop(self) -> None:
        """Main monitoring loop that checks emails periodically."""
        if not self.accounts:
            logger.warning("No email accounts configured to watch")
            return

        logger.info(
            f"Starting IMAP watcher | "
            f"Interval: {self.interval}s | "
            f"Accounts: {len(self.accounts)}"
        )

        while True:
            try:
                await self.check_all_accounts()
                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                logger.info("IMAP watcher cancelled")
                break
            except Exception as e:
                logger.error(f"Error in IMAP watcher: {e}", exc_info=True)
                await asyncio.sleep(self.interval)

        # Cleanup: disconnect all accounts
        logger.info("Disconnecting all email accounts...")
        for account in self.accounts:
            await account.disconnect()

        logger.info("IMAP watcher stopped")


async def watch_imap(notifier: Notifier, config: dict) -> None:
    """
    Monitor IMAP email accounts for new messages.

    Args:
        notifier: Notifier instance for sending alerts
        config: Configuration dictionary for IMAP watcher
    """
    monitor = ImapMonitor(notifier, config)
    await monitor.monitor_loop()


def init(notifier: Notifier, config: dict) -> Optional[Coroutine[Any, Any, None]]:
    """
    Initialize the IMAP watcher.

    Args:
        notifier: Notifier instance for sending notifications
        config: Configuration dictionary for this watcher

    Returns:
        Async coroutine or None if disabled
    """
    if not config:
        logger.info("IMAP watcher is not configured")
        return None

    if not config.get("enabled", False):
        logger.info("IMAP watcher is disabled")
        return None

    return watch_imap(notifier, config)
