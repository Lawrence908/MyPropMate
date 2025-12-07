"""Payment processor that orchestrates the full rent receipt flow.

This module implements the core business logic:
1. Poll Gmail for new Interac e-Transfer emails
2. Match sender to tenant in database
3. Validate payment amount
4. Create invoice in Invoice Ninja and send receipt
5. Log payment and update tenant status
6. Notify landlord of any issues
"""

import smtplib
from email.mime.text import MIMEText
from datetime import date
from typing import Dict, Any, List, Optional
from dateutil.relativedelta import relativedelta

from app.config import Settings
from app.db.supabase import SupabaseClient, get_supabase
from app.services.gmail_watcher import GmailWatcher
from app.services.invoice_ninja import InvoiceNinjaClient
from app.models.schemas import ParsedInteracEmail


class PaymentProcessor:
    """Orchestrates the payment detection and receipt sending flow."""
    
    # Tolerance for amount matching (from n8n flow)
    AMOUNT_TOLERANCE = 0.01
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.gmail = GmailWatcher(settings)
        self.ninja = InvoiceNinjaClient(settings)
        self.db = get_supabase()
    
    async def process_new_payments(self) -> Dict[str, Any]:
        """
        Main entry point: process all new payment emails.
        
        Returns summary of processed payments and any errors.
        """
        results = {
            "processed": [],
            "errors": [],
            "skipped": []
        }
        
        try:
            # Fetch new payment emails
            payments = await self.gmail.fetch_new_payments()
            print(f"Found {len(payments)} new payment email(s)")
            
            for payment in payments:
                try:
                    result = await self._process_single_payment(payment)
                    results["processed"].append(result)
                    
                    # Mark email as processed
                    await self.gmail.mark_as_processed(payment.email_id)
                    
                except ValidationError as e:
                    # Payment validation failed - notify landlord
                    error_info = {
                        "email_id": payment.email_id,
                        "sender": payment.sender_name,
                        "amount": payment.amount,
                        "error": str(e)
                    }
                    results["errors"].append(error_info)
                    
                    # Send notification email
                    await self._notify_landlord_error(payment, str(e))
                    
                    # Still mark as processed to avoid reprocessing
                    await self.gmail.mark_as_processed(payment.email_id)
                    
                except Exception as e:
                    # Unexpected error - log but don't mark as processed
                    results["errors"].append({
                        "email_id": payment.email_id,
                        "sender": payment.sender_name,
                        "error": f"Unexpected error: {str(e)}"
                    })
                    print(f"Error processing payment from {payment.sender_name}: {e}")
        
        except Exception as e:
            results["errors"].append({
                "error": f"Failed to fetch payments: {str(e)}"
            })
            print(f"Error fetching payments: {e}")
        
        return results
    
    async def _process_single_payment(
        self,
        payment: ParsedInteracEmail
    ) -> Dict[str, Any]:
        """
        Process a single payment email through the full flow.
        
        Raises ValidationError if payment doesn't match expectations.
        """
        # Check for duplicate
        is_duplicate = await self.db.check_duplicate_payment(payment.email_id)
        if is_duplicate:
            return {
                "status": "skipped",
                "reason": "duplicate",
                "email_id": payment.email_id
            }
        
        # Find tenant by sender name
        tenant = await self.db.get_tenant_by_name(payment.sender_name)
        if not tenant:
            raise ValidationError(
                f"Tenant not found in database: {payment.sender_name}"
            )
        
        # Calculate expected amount
        monthly_rent = float(tenant.get("monthly_rent", 0))
        parking_fee = float(tenant.get("parking_fee", 0) or 0)
        expected_amount = monthly_rent + parking_fee
        
        # Validate amount
        if abs(payment.amount - expected_amount) > self.AMOUNT_TOLERANCE:
            raise ValidationError(
                f"Amount mismatch: received ${payment.amount:.2f}, "
                f"expected ${expected_amount:.2f} "
                f"(rent: ${monthly_rent:.2f} + parking: ${parking_fee:.2f})"
            )
        
        # Determine period from message or next_due_month
        period = self._determine_period(payment, tenant)
        
        # Create invoice in Invoice Ninja and send receipt
        invoice_result = await self.ninja.create_and_send_invoice(
            tenant=tenant,
            amount=payment.amount,
            period=period,
            payment_date=payment.payment_date
        )
        
        # Calculate next invoice number and due month
        last_invoice_no = tenant.get("last_invoice_no", 0) or 0
        new_invoice_no = last_invoice_no + 1
        new_next_due = self._bump_month(tenant.get("next_due_month"))
        
        # Record payment in database
        db_payment = await self.db.create_payment(
            tenant_id=tenant["id"],
            amount=payment.amount,
            payment_date=payment.payment_date,
            period=period,
            email_id=payment.email_id,
            invoice_ninja_invoice_id=invoice_result.get("invoice_id"),
            notes=f"Auto-processed from email. Message: {payment.message_line or 'N/A'}"
        )
        
        # Update tenant status
        await self.db.update_tenant_after_payment(
            tenant_id=tenant["id"],
            new_invoice_no=new_invoice_no,
            new_next_due=new_next_due,
            invoice_ninja_client_id=invoice_result.get("client_id")
        )
        
        # Mark payment as emailed
        await self.db.mark_payment_emailed(db_payment["id"])
        
        return {
            "status": "success",
            "tenant": tenant["name"],
            "amount": payment.amount,
            "period": period,
            "invoice_number": invoice_result.get("invoice_number"),
            "payment_id": db_payment["id"]
        }
    
    def _determine_period(
        self,
        payment: ParsedInteracEmail,
        tenant: Dict[str, Any]
    ) -> str:
        """Determine the rental period for this payment."""
        # Try to extract from message line first
        if payment.message_line:
            # Clean up message - remove "rent" prefix if present
            period = payment.message_line
            period = period.replace("rent", "").replace("Rent", "").strip()
            if period:
                return period
        
        # Fall back to next_due_month from tenant record
        next_due = tenant.get("next_due_month")
        if next_due:
            try:
                # Convert YYYY-MM to month name
                year, month = next_due.split("-")
                dt = date(int(year), int(month), 1)
                return dt.strftime("%B %Y")
            except (ValueError, AttributeError):
                pass
        
        # Last resort: use payment date
        return payment.payment_date.strftime("%B %Y")
    
    def _bump_month(self, year_month: str) -> str:
        """Increment a YYYY-MM string by one month."""
        if not year_month:
            # Default to next month from today
            next_month = date.today() + relativedelta(months=1)
            return next_month.strftime("%Y-%m")
        
        try:
            year, month = year_month.split("-")
            current = date(int(year), int(month), 1)
            next_month = current + relativedelta(months=1)
            return next_month.strftime("%Y-%m")
        except (ValueError, AttributeError):
            next_month = date.today() + relativedelta(months=1)
            return next_month.strftime("%Y-%m")
    
    async def _notify_landlord_error(
        self,
        payment: ParsedInteracEmail,
        error_message: str
    ) -> None:
        """Send email notification to landlord about a payment issue."""
        try:
            subject = "MyPropMate: Rent receipt flow needs review"
            body = f"""
A payment email could not be automatically processed.

Sender: {payment.sender_name}
Amount: ${payment.amount:.2f}
Date: {payment.payment_date}
Subject: {payment.raw_subject}

Issue: {error_message}

Please review and process manually if needed.
"""
            
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = self.settings.gmail_watch_email
            msg['To'] = self.settings.landlord_email
            
            # Note: For production, you'd want to use async email
            # or delegate to Invoice Ninja / external service
            print(f"Would notify landlord about error: {error_message}")
            print(f"Payment from: {payment.sender_name}, Amount: ${payment.amount}")
            
        except Exception as e:
            print(f"Failed to send landlord notification: {e}")


class ValidationError(Exception):
    """Raised when payment validation fails."""
    pass



