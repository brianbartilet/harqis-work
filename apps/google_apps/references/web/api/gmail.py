from __future__ import annotations

import base64
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from apps.google_apps.references.web.discovery import BaseGoogleDiscoveryService


def _decode_body(data: str) -> str:
    """Base64url-decode a Gmail message body part."""
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_header(headers: List[Dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _plain_text_from_payload(payload: Dict) -> str:
    """Recursively extract plain-text body from a message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return _decode_body(data) if data else ""
    for part in payload.get("parts", []):
        text = _plain_text_from_payload(part)
        if text:
            return text
    return ""


class ApiServiceGoogleGmail(BaseGoogleDiscoveryService):
    """
    Gmail service using the Google Discovery API.

    Wraps gmail.googleapis.com v1:
      - users().messages().list(...)
      - users().messages().get(...)

    Docs:
      - REST: https://developers.google.com/gmail/api/reference/rest/v1/users.messages
    """

    SERVICE_NAME = "gmail"
    SERVICE_VERSION = "v1"

    def __init__(self, config, user_id: str = "me", **kwargs) -> None:
        super().__init__(config, **kwargs)
        self.user_id = user_id

    # ------------------------------------------------------------------ #
    # Low-level wrappers
    # ------------------------------------------------------------------ #

    def list_messages(
        self,
        max_results: int = 10,
        query: Optional[str] = None,
        label_ids: Optional[List[str]] = None,
        page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List messages in the user's mailbox.

        Args:
            max_results: Maximum number of message stubs to return (default 10).
            query: Gmail search query string, e.g. 'is:unread', 'from:example.com'.
            label_ids: Only return messages with these label IDs, e.g. ['INBOX'].
            page_token: Token from a previous response to fetch the next page.

        Returns:
            ListMessagesResponse dict with 'messages' (stubs), 'nextPageToken', 'resultSizeEstimate'.
        """
        params: Dict[str, Any] = {
            "userId": self.user_id,
            "maxResults": max_results,
        }
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids
        if page_token:
            params["pageToken"] = page_token

        return self.service.users().messages().list(**params).execute()

    def get_message(
        self,
        message_id: str,
        msg_format: str = "full",
        metadata_headers: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Get a single message by ID.

        Args:
            message_id: The Gmail message ID.
            msg_format: 'full', 'metadata', 'minimal', or 'raw'.
            metadata_headers: When format='metadata', restrict which headers to return.

        Returns:
            Message resource dict.
        """
        params: Dict[str, Any] = {
            "userId": self.user_id,
            "id": message_id,
            "format": msg_format,
        }
        if metadata_headers:
            params["metadataHeaders"] = metadata_headers

        return self.service.users().messages().get(**params).execute()

    # ------------------------------------------------------------------ #
    # Convenience helpers
    # ------------------------------------------------------------------ #

    def get_recent_emails(
        self,
        max_results: int = 10,
        query: Optional[str] = None,
        label_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent emails with subject, sender, date, snippet, and plain-text body.

        Args:
            max_results: Number of emails to return (default 10).
            query: Optional Gmail search string.
            label_ids: Optional label filter, e.g. ['INBOX'].

        Returns:
            List of dicts with keys: id, threadId, subject, from, date, snippet, body.
        """
        stubs = self.list_messages(
            max_results=max_results,
            query=query,
            label_ids=label_ids,
        ).get("messages", [])

        emails = []
        for stub in stubs:
            msg = self.get_message(stub["id"], msg_format="full")
            headers = msg.get("payload", {}).get("headers", [])
            emails.append({
                "id": msg.get("id"),
                "threadId": msg.get("threadId"),
                "subject": _extract_header(headers, "Subject"),
                "from": _extract_header(headers, "From"),
                "to": _extract_header(headers, "To"),
                "date": _extract_header(headers, "Date"),
                "snippet": msg.get("snippet", ""),
                "body": _plain_text_from_payload(msg.get("payload", {})),
                "labelIds": msg.get("labelIds", []),
            })
        return emails

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        body_html: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an email via Gmail API.

        Requires the 'gmail.send' scope on the OAuth credential.

        Args:
            to:        Recipient email address.
            subject:   Email subject line.
            body:      Plain-text body.
            body_html: Optional HTML body (sends multipart/alternative when provided).

        Returns:
            Sent message resource dict with 'id', 'threadId', 'labelIds'.
        """
        if body_html:
            msg: MIMEMultipart | MIMEText = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "plain"))
            msg.attach(MIMEText(body_html, "html"))
        else:
            msg = MIMEText(body, "plain")

        msg["To"] = to
        msg["Subject"] = subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        return self.service.users().messages().send(
            userId=self.user_id,
            body={"raw": raw},
        ).execute()
