"""Parse Interac e-Transfer 'auto-deposit' notification emails.

Grounded in a real notification body:

    Hi CHRISTOPHER LAWRENCE,
    Funds Deposited!
    $650.00
    ...
    Transfer Details
    Message:
    August 2026 rent
    Date: Aug 1, 2026
    Reference Number: C1AXGnKDMmqz
    Sent From: RICK HILSENDEGER
    Amount: $650.00 (CAD)

Subject line:
    Interac e-Transfer: You've received $650.00 from RICK HILSENDEGER
    and it has been automatically deposited.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


# The sender address Interac uses for auto-deposit notifications.
INTERAC_FROM_DOMAIN = "payments.interac.ca"

_AMOUNT_RE = re.compile(r"Amount:\s*\$?([\d,]+\.\d{2})", re.IGNORECASE)
_SUBJECT_AMOUNT_RE = re.compile(r"received\s+\$?([\d,]+\.\d{2})", re.IGNORECASE)
_REF_RE = re.compile(r"Reference\s*Number:\s*([A-Za-z0-9]+)", re.IGNORECASE)
_SENTFROM_RE = re.compile(r"Sent\s*From:\s*(.+)", re.IGNORECASE)
_SUBJECT_SENDER_RE = re.compile(r"from\s+(.+?)\s+and\s+it", re.IGNORECASE)
_DATE_RE = re.compile(r"^\s*Date:\s*([A-Za-z]{3}\s+\d{1,2},\s*\d{4})", re.IGNORECASE | re.MULTILINE)
# "Message:" then the content on the following non-empty line.
_MESSAGE_RE = re.compile(r"Message:\s*\r?\n\s*(.+)", re.IGNORECASE)


class ParseError(ValueError):
    """Raised when a notification email cannot be parsed into a payment."""


@dataclass
class ParsedPayment:
    sender_name: str          # as printed, e.g. "RICK HILSENDEGER"
    amount: float             # 650.00
    reference_number: str     # "C1AXGnKDMmqz" -- idempotency key
    message: Optional[str]    # "August 2026 rent" (transfer memo), may be None
    deposit_date: Optional[date]  # Aug 1, 2026

    @property
    def match_name(self) -> str:
        """Normalized name for tenant lookup (lowercase, collapsed spaces)."""
        return normalize_name(self.sender_name)


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def is_interac_deposit(from_header: str, subject: str) -> bool:
    """Cheap filter: an Interac auto-deposit 'you've received' notification."""
    from_ok = INTERAC_FROM_DOMAIN in (from_header or "").lower()
    subj = (subject or "").lower()
    subj_ok = "e-transfer" in subj and "received" in subj
    return from_ok and subj_ok


def _clean_amount(raw: str) -> float:
    return float(raw.replace(",", ""))


def parse_interac_email(subject: str, plaintext_body: str) -> ParsedPayment:
    """Extract a ParsedPayment from an Interac notification.

    Prefers the labelled fields in the body; falls back to the subject line.
    """
    body = plaintext_body or ""

    # Amount: body "Amount:" first, else subject "received $X".
    amount = None
    m = _AMOUNT_RE.search(body)
    if m:
        amount = _clean_amount(m.group(1))
    else:
        m = _SUBJECT_AMOUNT_RE.search(subject or "")
        if m:
            amount = _clean_amount(m.group(1))
    if amount is None:
        raise ParseError("Could not find transfer amount")

    # Sender: body "Sent From:" first, else subject "from X and it".
    sender = None
    m = _SENTFROM_RE.search(body)
    if m:
        sender = m.group(1).strip()
    else:
        m = _SUBJECT_SENDER_RE.search(subject or "")
        if m:
            sender = m.group(1).strip()
    if not sender:
        raise ParseError("Could not find sender name")

    # Reference number (idempotency key). Required for dedup.
    m = _REF_RE.search(body)
    if not m:
        raise ParseError("Could not find reference number")
    reference_number = m.group(1).strip()

    # Optional message / date.
    message = None
    m = _MESSAGE_RE.search(body)
    if m:
        candidate = m.group(1).strip()
        # Guard against grabbing the next labelled field if memo was blank.
        if candidate and not re.match(r"^(Date|Reference|Sent From|Amount):", candidate, re.IGNORECASE):
            message = candidate

    deposit_date = None
    m = _DATE_RE.search(body)
    if m:
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                deposit_date = datetime.strptime(m.group(1).strip(), fmt).date()
                break
            except ValueError:
                continue

    return ParsedPayment(
        sender_name=sender,
        amount=amount,
        reference_number=reference_number,
        message=message,
        deposit_date=deposit_date,
    )


# Month lookup: full names ("august") and abbreviations ("aug", "sept").
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9


def _find_month(text: str) -> Optional[int]:
    """First recognisable month word in `text` (exact token match), else None."""
    for token in re.findall(r"[A-Za-z]+", text or ""):
        month = _MONTHS.get(token.lower())
        if month:
            return month
    return None


def _find_year(text: str) -> Optional[int]:
    m = re.search(r"\b(20\d{2})\b", text or "")
    return int(m.group(1)) if m else None


def derive_period(payment: ParsedPayment) -> str:
    """Normalized rental period, always 'Month YYYY' (e.g. 'August 2026').

    Prefers the month/year named in the transfer memo ('Aug', 'August 2026 rent',
    'rent for August'), so a payment made late still maps to the stated month.
    Falls back to the deposit date, then to today.
    """
    text = payment.message or ""
    month = _find_month(text)
    year = _find_year(text)
    if month is None:
        month = payment.deposit_date.month if payment.deposit_date else datetime.now().month
    if year is None:
        year = payment.deposit_date.year if payment.deposit_date else datetime.now().year
    return f"{calendar.month_name[month]} {year}"
