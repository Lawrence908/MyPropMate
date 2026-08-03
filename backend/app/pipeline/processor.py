"""Orchestrates the receipt pipeline: one method, mirroring the old design.

    IMAP fetch -> parse -> match tenant -> validate amount -> dedup(ref#)
    -> render receipt (xlsx + PDF) -> email -> record payment (+bump invoice#)

Failure policy:
  * Validation failures (unknown tenant, wrong amount) are recorded via the
    reference number and the landlord is notified, so they are not retried.
  * Unexpected errors (render/email/DB) are NOT recorded, so the email is
    picked up again on the next poll. No invoice number is consumed on failure.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

from app.config import Settings
from app.pipeline.imap_client import ImapClient
from app.pipeline.mailer import Mailer
from app.pipeline.parser import (
    ParseError,
    ParsedPayment,
    derive_period,
    parse_interac_email,
)
from app.pipeline.receipt import render_receipt
from app.pipeline.store import Store, Tenant, seed_from_json


class ValidationError(Exception):
    """A payment that cannot be turned into a receipt (recorded, not retried)."""


class PaymentProcessor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.imap = ImapClient(
            settings.imap_host, settings.imap_email, settings.imap_password
        )
        self.mailer = Mailer(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_username,
            settings.smtp_password,
            settings.smtp_from_name,
            settings.smtp_from_address,
        )

    def _open_store(self) -> Store:
        store = Store(self.settings.db_path)
        seed_from_json(store, self.settings.tenants_seed_path)
        return store

    def process_new_payments(self, send_email: bool = True) -> Dict[str, Any]:
        """Fetch and process new payments.

        With ``send_email=False`` (the "prep" phase) receipts are rendered and
        recorded but not emailed, so they can be reviewed first. Use
        :meth:`send_pending_receipts` afterwards to send them.
        """
        store = self._open_store()
        summary = {"scanned": 0, "processed": 0, "skipped": 0, "failed": 0, "details": []}
        try:
            emails = self.imap.fetch_new_payments()
            summary["scanned"] = len(emails)
            for raw in emails:
                try:
                    payment = parse_interac_email(raw.subject, raw.plaintext)
                except ParseError as exc:
                    summary["skipped"] += 1
                    summary["details"].append({"uid": raw.uid, "skip": str(exc)})
                    continue

                if store.payment_exists(payment.reference_number):
                    summary["skipped"] += 1
                    summary["details"].append(
                        {"ref": payment.reference_number, "skip": "duplicate"}
                    )
                    continue

                try:
                    result = self._process_single(store, payment, send_email=send_email)
                    summary["processed"] += 1
                    summary["details"].append(result)
                except ValidationError as exc:
                    store.record_failed(
                        payment.reference_number,
                        payment.sender_name,
                        payment.amount,
                        str(exc),
                    )
                    self._notify_landlord(payment, str(exc))
                    summary["failed"] += 1
                    summary["details"].append(
                        {"ref": payment.reference_number, "failed": str(exc)}
                    )
                # Unexpected exceptions propagate to the caller and are left
                # unrecorded so the email is retried on the next poll.
            return summary
        finally:
            store.close()

    def _process_single(
        self, store: Store, payment: ParsedPayment, send_email: bool = True
    ) -> Dict[str, Any]:
        tenant = store.get_tenant_by_name(payment.sender_name)
        if tenant is None:
            raise ValidationError(
                f"No tenant matches sender '{payment.sender_name}'"
            )

        if abs(payment.amount - tenant.expected_amount) > self.settings.amount_tolerance:
            raise ValidationError(
                f"Amount ${payment.amount:.2f} != expected ${tenant.expected_amount:.2f} "
                f"(rent ${tenant.monthly_rent:.2f} + parking ${tenant.parking_fee:.2f}) "
                f"for {tenant.display_name}"
            )

        period = derive_period(payment)
        payment_date = payment.deposit_date or date.today()
        invoice_no = tenant.last_invoice_no + 1

        rendered = render_receipt(
            template_path=self.settings.template_path,
            receipts_dir=self.settings.receipts_dir,
            tenant=tenant,
            invoice_no=invoice_no,
            period=period,
            payment_date=payment_date,
            soffice_bin=self.settings.soffice_bin,
        )
        attachment = rendered["pdf"] or rendered["xlsx"]

        emailed = False
        if send_email and tenant.email:
            self.mailer.send_receipt(
                to_address=tenant.email,
                tenant_name=tenant.display_name,
                period=period,
                pdf_path=attachment,
                bcc=self.settings.landlord_email or None,
            )
            emailed = True

        # Persist last: invoice number is only consumed on success.
        store.record_payment(
            reference_number=payment.reference_number,
            tenant_id=tenant.id,
            sender_name=payment.sender_name,
            amount=payment.amount,
            period=period,
            payment_date=payment_date,
            invoice_no=invoice_no,
            receipt_path=attachment,
            emailed=emailed,
        )
        return {
            "ref": payment.reference_number,
            "tenant": tenant.display_name,
            "period": period,
            "invoice_no": invoice_no,
            "amount": payment.amount,
            "receipt": attachment,
            "emailed": emailed,
        }

    def send_pending_receipts(self) -> Dict[str, Any]:
        """Email every prepped-but-unsent receipt (emailed=0 with an invoice).

        This is the second phase after a ``prep`` run: review the receipts on
        disk, then send them.
        """
        store = self._open_store()
        summary = {"sent": 0, "skipped": 0, "details": []}
        try:
            rows = store.conn.execute(
                """
                SELECT p.id, p.reference_number, p.period, p.receipt_path,
                       t.display_name, t.email
                FROM payments p JOIN tenants t ON t.id = p.tenant_id
                WHERE p.emailed = 0 AND p.invoice_no IS NOT NULL
                ORDER BY p.id
                """
            ).fetchall()
            # Bcc the landlord on every receipt so they get a filed copy.
            bcc = self.settings.landlord_email or None
            for r in rows:
                if not r["email"]:
                    summary["skipped"] += 1
                    summary["details"].append(
                        {"ref": r["reference_number"], "skip": "tenant has no email"}
                    )
                    continue
                self.mailer.send_receipt(
                    to_address=r["email"],
                    tenant_name=r["display_name"],
                    period=r["period"],
                    pdf_path=r["receipt_path"],
                    bcc=bcc,
                )
                store.mark_emailed(r["id"], r["receipt_path"])
                summary["sent"] += 1
                summary["details"].append(
                    {"ref": r["reference_number"], "to": r["email"], "period": r["period"]}
                )
            return summary
        finally:
            store.close()

    def send_one(self, reference_number: str) -> Dict[str, Any]:
        """Email a single prepped-but-unsent receipt by reference number.

        Used by the Telegram Confirm button. Idempotent: a reference that is
        already emailed or unknown returns a status without re-sending.
        """
        store = self._open_store()
        try:
            row = store.conn.execute(
                """
                SELECT p.id, p.period, p.receipt_path, p.emailed,
                       t.display_name, t.email
                FROM payments p JOIN tenants t ON t.id = p.tenant_id
                WHERE p.reference_number = ? AND p.invoice_no IS NOT NULL
                """,
                (reference_number,),
            ).fetchone()
            if row is None:
                return {"ref": reference_number, "status": "not-pending"}
            if row["emailed"]:
                return {"ref": reference_number, "status": "already-sent", "to": row["email"]}
            if not row["email"]:
                return {"ref": reference_number, "status": "no-email"}
            self.mailer.send_receipt(
                to_address=row["email"],
                tenant_name=row["display_name"],
                period=row["period"],
                pdf_path=row["receipt_path"],
                bcc=self.settings.landlord_email or None,
            )
            store.mark_emailed(row["id"], row["receipt_path"])
            return {"ref": reference_number, "status": "sent", "to": row["email"]}
        finally:
            store.close()

    def _notify_landlord(self, payment: ParsedPayment, reason: str) -> None:
        """Best-effort landlord alert. Never blocks the pipeline."""
        if not (self.settings.landlord_email and self.settings.smtp_password):
            print(f"[notify-landlord] {reason} (ref {payment.reference_number})")
            return
        try:
            self.mailer.send_notice(
                to_address=self.settings.landlord_email,
                subject="MyPropMate: payment needs attention",
                body=(
                    f"A payment could not be processed automatically.\n\n"
                    f"Sender:    {payment.sender_name}\n"
                    f"Amount:    ${payment.amount:.2f}\n"
                    f"Reference: {payment.reference_number}\n"
                    f"Reason:    {reason}\n"
                ),
            )
        except Exception as exc:  # pragma: no cover - notification is best-effort
            print(f"[notify-landlord] failed to send: {exc}")
