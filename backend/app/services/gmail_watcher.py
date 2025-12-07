"""Gmail API watcher for detecting Interac e-Transfer payments.

This module ports the email detection and parsing logic from the n8n workflow.
It polls Gmail for new Interac e-transfer notifications and parses payment details.
"""

import re
import base64
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.config import Settings
from app.models.schemas import ParsedInteracEmail


# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 
          'https://www.googleapis.com/auth/gmail.modify']

# Label used to mark processed emails
PROCESSED_LABEL = "MyPropMate_Processed"


class GmailWatcher:
    """Watch Gmail for Interac e-Transfer notifications."""
    
    # Search query for Interac e-transfer emails (from n8n flow)
    INTERAC_QUERY = (
        'subject:"Interac e-Transfer: You\'ve received" '
        '(from:notify@payments.interac.ca OR from:cibc.com) '
        '-label:MyPropMate_Processed'
    )
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.service = None
        self.processed_label_id = None
    
    def _get_credentials(self) -> Credentials:
        """Get or refresh Gmail API credentials."""
        creds = None
        token_path = Path(self.settings.gmail_token_path)
        creds_path = Path(self.settings.gmail_credentials_path)
        
        # Load existing token
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        
        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not creds_path.exists():
                    raise FileNotFoundError(
                        f"Gmail credentials file not found: {creds_path}\n"
                        "Download from Google Cloud Console and save to this path."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(creds_path), SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # Save refreshed token
            token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(token_path, 'w') as f:
                f.write(creds.to_json())
        
        return creds
    
    def _get_service(self):
        """Get Gmail API service instance."""
        if self.service is None:
            creds = self._get_credentials()
            self.service = build('gmail', 'v1', credentials=creds)
        return self.service
    
    async def _ensure_processed_label(self) -> str:
        """Ensure the processed label exists and return its ID."""
        if self.processed_label_id:
            return self.processed_label_id
        
        service = self._get_service()
        
        # Check if label exists
        results = service.users().labels().list(userId='me').execute()
        labels = results.get('labels', [])
        
        for label in labels:
            if label['name'] == PROCESSED_LABEL:
                self.processed_label_id = label['id']
                return self.processed_label_id
        
        # Create label if it doesn't exist
        label_body = {
            'name': PROCESSED_LABEL,
            'labelListVisibility': 'labelShow',
            'messageListVisibility': 'show'
        }
        created = service.users().labels().create(
            userId='me', body=label_body
        ).execute()
        
        self.processed_label_id = created['id']
        return self.processed_label_id
    
    def _parse_interac_email(
        self,
        message_id: str,
        subject: str,
        body: str,
        email_date: datetime
    ) -> Optional[ParsedInteracEmail]:
        """
        Parse an Interac e-Transfer email to extract payment details.
        
        This logic is ported from the n8n "Parse CIBC Email" function node.
        """
        # Clean body text (strip HTML)
        body_clean = re.sub(r'<[^>]+>', ' ', body)
        body_clean = re.sub(r'\s+', ' ', body_clean).strip()
        
        # Extract amount from subject
        # Pattern: "You've received $1,234.56"
        amount_match = re.search(
            r"You've received \$([0-9,]+\.[0-9]{2})",
            subject,
            re.IGNORECASE
        )
        if not amount_match:
            return None
        
        amount_str = amount_match.group(1).replace(',', '')
        amount = float(amount_str)
        
        # Extract sender name from subject
        # Pattern: "from John Doe"
        from_match = re.search(r'from\s+(.+)$', subject, re.IGNORECASE)
        if not from_match:
            return None
        
        # Title case the sender name
        sender_name = from_match.group(1).strip()
        sender_name = ' '.join(word.capitalize() for word in sender_name.split())
        
        # Extract message line from body (optional)
        msg_match = re.search(
            r'Message:\s*([^D]+?)\s*(?:Date:|Reference|Sent From:|Amount:)',
            body_clean,
            re.IGNORECASE
        )
        message_line = msg_match.group(1).strip() if msg_match else None
        
        # Extract date from body (more accurate than email date)
        date_match = re.search(
            r'Date:\s*([A-Za-z]{3,}\s*\d{1,2},\s*\d{4})',
            body_clean,
            re.IGNORECASE
        )
        if date_match:
            try:
                parsed_date = datetime.strptime(
                    date_match.group(1), '%B %d, %Y'
                ).date()
            except ValueError:
                try:
                    parsed_date = datetime.strptime(
                        date_match.group(1), '%b %d, %Y'
                    ).date()
                except ValueError:
                    parsed_date = email_date.date()
        else:
            parsed_date = email_date.date()
        
        return ParsedInteracEmail(
            email_id=message_id,
            sender_name=sender_name,
            amount=amount,
            payment_date=parsed_date,
            message_line=message_line,
            raw_subject=subject
        )
    
    async def fetch_new_payments(self) -> List[ParsedInteracEmail]:
        """
        Fetch and parse new Interac e-Transfer emails.
        
        Returns a list of parsed payment details from unprocessed emails.
        """
        service = self._get_service()
        payments = []
        
        # Search for matching emails
        results = service.users().messages().list(
            userId='me',
            q=self.INTERAC_QUERY,
            maxResults=20
        ).execute()
        
        messages = results.get('messages', [])
        
        for msg_ref in messages:
            msg_id = msg_ref['id']
            
            # Get full message
            message = service.users().messages().get(
                userId='me',
                id=msg_id,
                format='full'
            ).execute()
            
            # Extract headers
            headers = {h['name']: h['value'] for h in message['payload']['headers']}
            subject = headers.get('Subject', '')
            date_str = headers.get('Date', '')
            
            # Parse email date
            try:
                # Handle common email date format
                email_date = datetime.strptime(
                    date_str.split(' (')[0].strip(),
                    '%a, %d %b %Y %H:%M:%S %z'
                )
            except ValueError:
                email_date = datetime.now()
            
            # Get body
            body = self._extract_body(message['payload'])
            
            # Parse the email
            parsed = self._parse_interac_email(
                message_id=msg_id,
                subject=subject,
                body=body,
                email_date=email_date
            )
            
            if parsed:
                payments.append(parsed)
        
        return payments
    
    def _extract_body(self, payload: Dict[str, Any]) -> str:
        """Extract email body from payload."""
        body = ""
        
        if 'body' in payload and payload['body'].get('data'):
            body = base64.urlsafe_b64decode(
                payload['body']['data']
            ).decode('utf-8', errors='ignore')
        
        if 'parts' in payload:
            for part in payload['parts']:
                mime_type = part.get('mimeType', '')
                
                if mime_type == 'text/html':
                    if part['body'].get('data'):
                        body = base64.urlsafe_b64decode(
                            part['body']['data']
                        ).decode('utf-8', errors='ignore')
                        break
                elif mime_type == 'text/plain':
                    if part['body'].get('data'):
                        body = base64.urlsafe_b64decode(
                            part['body']['data']
                        ).decode('utf-8', errors='ignore')
                elif 'parts' in part:
                    # Nested multipart
                    body = self._extract_body(part)
                    if body:
                        break
        
        return body
    
    async def mark_as_processed(self, email_id: str) -> None:
        """Mark an email as processed by adding the processed label."""
        service = self._get_service()
        label_id = await self._ensure_processed_label()
        
        service.users().messages().modify(
            userId='me',
            id=email_id,
            body={'addLabelIds': [label_id]}
        ).execute()



