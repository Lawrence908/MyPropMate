"""Send email via Gmail SMTP (app password), with optional PDF attachment."""

from __future__ import annotations

import mimetypes
import os
import smtplib
from email.message import EmailMessage
from typing import Optional


class Mailer:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_name: str,
        from_address: str,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_name = from_name
        self.from_address = from_address or username

    def _send(self, msg: EmailMessage, to_addrs: Optional[list] = None) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=30) as server:
            server.starttls()
            server.login(self.username, self.password)
            # Explicit envelope recipients (so a Bcc address gets the message
            # without ever appearing in the transmitted headers).
            if to_addrs is not None:
                server.send_message(msg, to_addrs=to_addrs)
            else:
                server.send_message(msg)

    def send_receipt(
        self,
        to_address: str,
        tenant_name: str,
        period: str,
        pdf_path: Optional[str],
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
    ) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"Rent Receipt - {period}"
        msg["From"] = f"{self.from_name} <{self.from_address}>"
        msg["To"] = to_address
        if cc:
            msg["Cc"] = cc
        # Bcc is intentionally NOT set as a header; it goes in the envelope only.
        first_name = tenant_name.split()[0] if tenant_name else tenant_name
        sender_first = self.from_name.split()[0] if self.from_name else self.from_name
        msg.set_content(
            f"Hi {first_name},\n\n"
            f"Please find attached your rent receipt for {period}.\n\n"
            f"Thanks,\n{sender_first}\n"
        )
        if pdf_path and os.path.exists(pdf_path):
            ctype, _ = mimetypes.guess_type(pdf_path)
            maintype, subtype = (ctype or "application/pdf").split("/", 1)
            with open(pdf_path, "rb") as fh:
                msg.add_attachment(
                    fh.read(),
                    maintype=maintype,
                    subtype=subtype,
                    filename=os.path.basename(pdf_path),
                )
        recipients = [to_address]
        if cc:
            recipients.append(cc)
        if bcc:
            recipients.append(bcc)
        self._send(msg, to_addrs=recipients)

    def send_notice(self, to_address: str, subject: str, body: str) -> None:
        """Plain landlord notification (validation failures, errors)."""
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.from_address}>"
        msg["To"] = to_address
        msg.set_content(body)
        self._send(msg)
