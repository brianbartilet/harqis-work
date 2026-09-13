from __future__ import annotations

import base64
import re
import hashlib
import json
import mimetypes
import os
import sqlite3
from pathlib import Path
from email.message import EmailMessage
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
        attachments: Optional[List[str]] = None,
        operation_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an email via Gmail API.

        Requires the 'gmail.send' scope on the OAuth credential.

        Args:
            to:        Recipient email address.
            subject:   Email subject line.
            body:      Plain-text body.
            body_html: Optional HTML body (sends multipart/alternative when provided).
            attachments: Verified host file paths, at most 20 MB total.
            operation_key: Stable retry key; uncertain sends require reconciliation.

        Returns:
            Sent message resource dict with 'id', 'threadId', 'labelIds'.
        """
        if any('\r' in value or '\n' in value for value in (to, subject)):
            raise ValueError('Email headers cannot contain newlines.')
        msg = EmailMessage()
        msg.set_content(body)
        if body_html:
            msg.add_alternative(body_html, subtype='html')
        msg["To"] = to
        msg["Subject"] = subject
        files = []
        size = 0
        if len(attachments or []) > 30:
            raise ValueError('At most 30 attachments are allowed.')
        for filename in attachments or []:
            path = Path(filename).expanduser()
            if path.is_symlink() or not path.is_file():
                raise ValueError('Attachment must be a regular file, not a symlink.')
            if path.stat().st_size + size > 20 * 1024 * 1024:
                raise ValueError('Attachments exceed the 20 MB total limit.')
            data = path.read_bytes()
            size += len(data)
            if size > 20 * 1024 * 1024:
                raise ValueError('Attachments exceed the 20 MB total limit.')
            mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            major, minor = mime.split('/', 1)
            msg.add_attachment(data, maintype=major, subtype=minor, filename=path.name)
            files.append({'name': path.name, 'sha256': hashlib.sha256(data).hexdigest()})
        ledger = None
        if operation_key:
            if len(operation_key) > 500:
                raise ValueError('Operation key is too long.')
            key = hashlib.sha256(operation_key.encode()).hexdigest()
            message_id = f'<harqis-{key}@agent.harqis.local>'
            msg['Message-ID'] = message_id
            fingerprint = hashlib.sha256(json.dumps([self.user_id, to, subject, body, body_html, files], sort_keys=True).encode()).hexdigest()
            root = Path(os.environ.get('HARQIS_DATA_ROOT') or Path(__file__).resolve().parents[5] / '.harqis-data')
            root = root / 'runtime'
            root.mkdir(parents=True, exist_ok=True)
            ledger = root / 'gmail-send-receipts.sqlite3'
            with sqlite3.connect(ledger, timeout=30) as db:
                db.execute('CREATE TABLE IF NOT EXISTS sends (key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT)')
                db.execute('BEGIN IMMEDIATE')
                previous = db.execute('SELECT fingerprint,result FROM sends WHERE key=?', (key,)).fetchone()
                if previous:
                    if previous[0] != fingerprint:
                        raise ValueError('Operation key already used for different email content.')
                    if previous[1]:
                        return json.loads(previous[1])
                    raise RuntimeError(f'Send outcome uncertain; do not resend. Search Gmail for rfc822msgid:{message_id[1:-1]} and reconcile the operation.')
                db.execute('INSERT INTO sends VALUES (?,?,NULL)', (key, fingerprint))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        result = self.service.users().messages().send(
            userId=self.user_id,
            body={"raw": raw},
        ).execute()
        if not result.get('id'):
            raise RuntimeError('Gmail returned no message ID; verify the send before retrying.')
        if ledger:
            result = {**result, 'recipient': to, 'attachments': files, 'rfc822_message_id': message_id}
            with sqlite3.connect(ledger, timeout=30) as db:
                db.execute('UPDATE sends SET result=? WHERE key=?', (json.dumps(result), key))
        return result
