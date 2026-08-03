"""Minimal IMAP reader for the watched inbox.

Uses a Gmail app password (no OAuth). Fetches recent messages, keeps only
Interac auto-deposit notifications, and returns their subject + plaintext body.
Dedup is handled downstream by the payment reference number, so this layer does
not need to write labels or flags back to the mailbox.
"""

from __future__ import annotations

import email
import imaplib
from dataclasses import dataclass
from email.header import decode_header
from typing import List, Optional

from app.pipeline.parser import is_interac_deposit


@dataclass
class RawEmail:
    uid: str
    from_header: str
    subject: str
    plaintext: str


def _decode(value: Optional[str]) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", "replace"))
        else:
            out.append(chunk)
    return "".join(out)


def _plaintext_body(msg: email.message.Message) -> str:
    """Prefer text/plain; fall back to a crude strip of text/html."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition", "")
            ):
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", "replace")
        # Fallback: first text/html, tags stripped.
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    import re

                    html = payload.decode(part.get_content_charset() or "utf-8", "replace")
                    text = re.sub(r"<[^>]+>", " ", html)
                    return re.sub(r"[ \t]+", " ", text)
        return ""
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8", "replace") if payload else ""


class ImapClient:
    def __init__(self, host: str, email_addr: str, password: str):
        self.host = host
        self.email_addr = email_addr
        self.password = password

    def fetch_new_payments(self, lookback: int = 40) -> List[RawEmail]:
        """Return recent Interac auto-deposit notifications from the inbox.

        `lookback` bounds how many of the most recent inbox messages we scan.
        """
        conn = imaplib.IMAP4_SSL(self.host)
        try:
            conn.login(self.email_addr, self.password)
            conn.select("INBOX")
            typ, data = conn.search(None, "ALL")
            if typ != "OK":
                return []
            ids = data[0].split()
            results: List[RawEmail] = []
            for msg_id in ids[-lookback:]:
                typ, msg_data = conn.fetch(msg_id, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                subject = _decode(msg.get("Subject"))
                from_header = _decode(msg.get("From"))
                if not is_interac_deposit(from_header, subject):
                    continue
                results.append(
                    RawEmail(
                        uid=msg_id.decode(),
                        from_header=from_header,
                        subject=subject,
                        plaintext=_plaintext_body(msg),
                    )
                )
            return results
        finally:
            try:
                conn.logout()
            except Exception:
                pass
