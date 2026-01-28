"""Gmail adapter for DevAssist.

Implements OAuth2-based Gmail integration for fetching emails.
"""

import base64
from collections.abc import AsyncIterator
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from devassist.adapters.base import ContextSourceAdapter
from devassist.adapters.errors import AuthenticationError, SourceUnavailableError
from devassist.models.context import ContextItem, SourceType

# Google API imports - these are optional and checked at runtime
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    InstalledAppFlow = None  # type: ignore
    build = None  # type: ignore
    Credentials = None  # type: ignore
    Request = None  # type: ignore


# Gmail API scopes - full access for read and write operations
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]


class GmailAdapter(ContextSourceAdapter):
    """Adapter for Gmail using OAuth2 authentication."""

    def __init__(self) -> None:
        """Initialize GmailAdapter."""
        self._creds: Any = None
        self._service: Any = None
        self._token_path: Path | None = None

    @property
    def source_type(self) -> SourceType:
        """Get source type."""
        return SourceType.GMAIL

    @property
    def display_name(self) -> str:
        """Get display name."""
        return "Gmail"

    @classmethod
    def get_required_config_fields(cls) -> list[str]:
        """Get required configuration fields."""
        return ["credentials_file"]

    async def authenticate(self, config: dict[str, Any]) -> bool:
        """Authenticate with Gmail using OAuth2.

        Args:
            config: Must contain 'credentials_file' path to OAuth client secrets.

        Returns:
            True if authentication succeeded.

        Raises:
            AuthenticationError: If OAuth flow fails.
        """
        if not GOOGLE_API_AVAILABLE:
            raise AuthenticationError(
                "Google API libraries not installed. Run: pip install google-auth-oauthlib google-api-python-client",
                source_type="gmail",
            )

        credentials_file = config.get("credentials_file")
        if not credentials_file:
            raise AuthenticationError(
                "credentials_file is required for Gmail OAuth",
                source_type="gmail",
            )

        credentials_path = Path(credentials_file)
        token_path = credentials_path.parent / "gmail_token.json"
        self._token_path = token_path

        creds = None

        # Try to load existing token
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
            except Exception:
                pass

        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    raise AuthenticationError(
                        f"Failed to refresh Gmail token: {e}",
                        source_type="gmail",
                    ) from e
            else:
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(credentials_path), GMAIL_SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    raise AuthenticationError(
                        f"Gmail OAuth flow failed: {e}",
                        source_type="gmail",
                    ) from e

            # Save credentials for next run
            with open(token_path, "w") as token_file:
                token_file.write(creds.to_json())

        self._creds = creds
        self._service = build("gmail", "v1", credentials=creds)
        return True

    async def test_connection(self) -> bool:
        """Test Gmail connection.

        Returns:
            True if connection is healthy.

        Raises:
            SourceUnavailableError: If not authenticated or connection fails.
        """
        if not self._creds:
            raise SourceUnavailableError(
                "Not authenticated. Call authenticate() first.",
                source_type="gmail",
            )

        try:
            if not self._service:
                self._service = build("gmail", "v1", credentials=self._creds)

            profile = self._service.users().getProfile(userId="me").execute()
            return "emailAddress" in profile
        except Exception as e:
            raise SourceUnavailableError(
                f"Gmail connection test failed: {e}",
                source_type="gmail",
            ) from e

    async def fetch_items(
        self,
        limit: int = 50,
        **kwargs: Any,
    ) -> AsyncIterator[ContextItem]:
        """Fetch recent emails from Gmail.

        Args:
            limit: Maximum number of emails to fetch.
            **kwargs: Additional options (e.g., query filter).

        Yields:
            ContextItem for each email.

        Raises:
            SourceUnavailableError: If fetch fails.
            AuthenticationError: If not authenticated.
        """
        if not self._creds or not self._service:
            raise AuthenticationError(
                "Not authenticated. Call authenticate() first.",
                source_type="gmail",
            )

        try:
            # Get message list
            query = kwargs.get("query", "is:unread OR newer_than:1d")
            results = (
                self._service.users()
                .messages()
                .list(userId="me", q=query, maxResults=limit)
                .execute()
            )

            messages = results.get("messages", [])

            for msg_meta in messages[:limit]:
                msg = (
                    self._service.users()
                    .messages()
                    .get(userId="me", id=msg_meta["id"], format="full")
                    .execute()
                )

                # Parse headers
                headers = {
                    h["name"].lower(): h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }

                subject = headers.get("subject", "(No Subject)")
                sender = headers.get("from", "Unknown")
                date_str = headers.get("date", "")

                # Parse timestamp
                try:
                    timestamp = parsedate_to_datetime(date_str)
                except Exception:
                    timestamp = datetime.now()

                # Get snippet as content
                content = msg.get("snippet", "")

                yield ContextItem(
                    id=msg["id"],
                    source_id="gmail",
                    source_type=SourceType.GMAIL,
                    timestamp=timestamp,
                    title=subject,
                    content=content,
                    author=sender,
                    url=f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}",
                    metadata={
                        "labels": msg.get("labelIds", []),
                        "thread_id": msg.get("threadId"),
                    },
                    is_read="UNREAD" not in msg.get("labelIds", []),
                )

        except Exception as e:
            raise SourceUnavailableError(
                f"Failed to fetch Gmail messages: {e}",
                source_type="gmail",
            ) from e

    # ==================== Tool Methods ====================
    # These methods can be called by the AI via function calling

    async def search_gmail(
        self, query: str, max_results: int = 10
    ) -> list[dict[str, Any]]:
        """Search Gmail messages.
        
        Args:
            query: Gmail search query.
            max_results: Maximum results to return.
            
        Returns:
            List of message summaries.
        """
        if not self._service:
            raise SourceUnavailableError(
                "Not authenticated", source_type="gmail"
            )

        results = (
            self._service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        messages = []
        for msg_meta in results.get("messages", [])[:max_results]:
            msg = (
                self._service.users()
                .messages()
                .get(userId="me", id=msg_meta["id"], format="metadata")
                .execute()
            )
            
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            
            messages.append({
                "id": msg["id"],
                "thread_id": msg.get("threadId"),
                "subject": headers.get("subject", "(No Subject)"),
                "from": headers.get("from", "Unknown"),
                "date": headers.get("date", ""),
                "snippet": msg.get("snippet", ""),
                "labels": msg.get("labelIds", []),
            })

        return messages

    async def get_gmail_message(self, message_id: str) -> dict[str, Any]:
        """Get full message content.
        
        Args:
            message_id: Gmail message ID.
            
        Returns:
            Full message details including body.
        """
        if not self._service:
            raise SourceUnavailableError(
                "Not authenticated", source_type="gmail"
            )

        msg = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        headers = {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }

        # Extract body
        body = self._extract_body(msg.get("payload", {}))

        return {
            "id": msg["id"],
            "thread_id": msg.get("threadId"),
            "subject": headers.get("subject", "(No Subject)"),
            "from": headers.get("from", "Unknown"),
            "to": headers.get("to", ""),
            "cc": headers.get("cc", ""),
            "date": headers.get("date", ""),
            "body": body,
            "labels": msg.get("labelIds", []),
            "url": f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}",
        }

    async def get_gmail_thread(self, thread_id: str) -> dict[str, Any]:
        """Get all messages in a thread.
        
        Args:
            thread_id: Gmail thread ID.
            
        Returns:
            Thread with all messages.
        """
        if not self._service:
            raise SourceUnavailableError(
                "Not authenticated", source_type="gmail"
            )

        thread = (
            self._service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )

        messages = []
        for msg in thread.get("messages", []):
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            body = self._extract_body(msg.get("payload", {}))
            
            messages.append({
                "id": msg["id"],
                "subject": headers.get("subject", "(No Subject)"),
                "from": headers.get("from", "Unknown"),
                "to": headers.get("to", ""),
                "date": headers.get("date", ""),
                "body": body,
            })

        return {
            "thread_id": thread_id,
            "messages": messages,
        }

    async def send_gmail(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
    ) -> dict[str, Any]:
        """Send an email.
        
        Args:
            to: Recipient(s).
            subject: Subject line.
            body: Email body.
            cc: CC recipients.
            bcc: BCC recipients.
            
        Returns:
            Sent message info.
        """
        if not self._service:
            raise SourceUnavailableError(
                "Not authenticated", source_type="gmail"
            )

        message = self._create_message(to, subject, body, cc, bcc)
        
        sent = (
            self._service.users()
            .messages()
            .send(userId="me", body=message)
            .execute()
        )

        return {
            "id": sent["id"],
            "thread_id": sent.get("threadId"),
            "status": "sent",
        }

    async def reply_gmail(
        self,
        message_id: str,
        body: str,
        reply_all: bool = False,
    ) -> dict[str, Any]:
        """Reply to a message.
        
        Args:
            message_id: Message ID to reply to.
            body: Reply body.
            reply_all: Whether to reply to all.
            
        Returns:
            Sent reply info.
        """
        if not self._service:
            raise SourceUnavailableError(
                "Not authenticated", source_type="gmail"
            )

        # Get original message
        original = await self.get_gmail_message(message_id)
        
        # Build reply
        to = original["from"]
        if reply_all and original.get("cc"):
            to = f"{to}, {original['cc']}"
        
        subject = original["subject"]
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        message = self._create_message(to, subject, body)
        message["threadId"] = original["thread_id"]
        
        # Add In-Reply-To header
        raw_msg = base64.urlsafe_b64decode(message["raw"]).decode()
        raw_msg = f"In-Reply-To: {message_id}\r\n{raw_msg}"
        message["raw"] = base64.urlsafe_b64encode(raw_msg.encode()).decode()

        sent = (
            self._service.users()
            .messages()
            .send(userId="me", body=message)
            .execute()
        )

        return {
            "id": sent["id"],
            "thread_id": sent.get("threadId"),
            "status": "sent",
            "in_reply_to": message_id,
        }

    async def draft_gmail(
        self,
        to: str,
        subject: str,
        body: str,
    ) -> dict[str, Any]:
        """Create a draft email.
        
        Args:
            to: Recipient(s).
            subject: Subject line.
            body: Email body.
            
        Returns:
            Draft info.
        """
        if not self._service:
            raise SourceUnavailableError(
                "Not authenticated", source_type="gmail"
            )

        message = self._create_message(to, subject, body)
        
        draft = (
            self._service.users()
            .drafts()
            .create(userId="me", body={"message": message})
            .execute()
        )

        return {
            "id": draft["id"],
            "message_id": draft["message"]["id"],
            "status": "draft_created",
        }

    async def modify_gmail_labels(
        self,
        message_id: str,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Modify labels on a message.
        
        Args:
            message_id: Message ID.
            add_labels: Labels to add.
            remove_labels: Labels to remove.
            
        Returns:
            Updated message info.
        """
        if not self._service:
            raise SourceUnavailableError(
                "Not authenticated", source_type="gmail"
            )

        body: dict[str, Any] = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels

        if not body:
            return {"id": message_id, "status": "no_changes"}

        msg = (
            self._service.users()
            .messages()
            .modify(userId="me", id=message_id, body=body)
            .execute()
        )

        return {
            "id": msg["id"],
            "labels": msg.get("labelIds", []),
            "status": "modified",
        }

    def _create_message(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
    ) -> dict[str, str]:
        """Create a message for sending.
        
        Args:
            to: Recipient(s).
            subject: Subject.
            body: Body text.
            cc: CC recipients.
            bcc: BCC recipients.
            
        Returns:
            Message dict with raw encoded content.
        """
        lines = [
            f"To: {to}",
            f"Subject: {subject}",
        ]
        if cc:
            lines.append(f"Cc: {cc}")
        if bcc:
            lines.append(f"Bcc: {bcc}")
        
        lines.extend([
            "Content-Type: text/plain; charset=utf-8",
            "",
            body,
        ])
        
        raw = "\r\n".join(lines)
        return {"raw": base64.urlsafe_b64encode(raw.encode()).decode()}

    def _extract_body(self, payload: dict[str, Any]) -> str:
        """Extract body text from message payload.
        
        Args:
            payload: Message payload.
            
        Returns:
            Body text.
        """
        # Check for plain text body
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        
        # Check parts
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            # Recurse into nested parts
            nested = self._extract_body(part)
            if nested:
                return nested
        
        return ""
