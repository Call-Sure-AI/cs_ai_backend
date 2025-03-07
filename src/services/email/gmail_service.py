# services/email/gmail_service.py
from typing import List, Dict, Any, Optional
import asyncio
import base64
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
from pathlib import Path

logger = logging.getLogger(__name__)

class EmailConfig:
    def __init__(
        self,
        service_account_json: str,
        sender_email: str,
    ):
        self.service_account_json = service_account_json
        self.sender_email = sender_email


class GmailService:
    def __init__(self, config: EmailConfig):
        """Initialize Gmail service"""
        self.config = config
        self.service = None
        self._setup_lock = asyncio.Lock()
    
    async def setup(self):
        """Initialize and authenticate Gmail API connection"""
        async with self._setup_lock:
            try:
                if self.service:
                    return
                    
                if not self.config.service_account_json:
                    logger.error("Missing Service Account JSON file path.")
                    raise ValueError("Service Account JSON path is required")
                if not self.config.sender_email:
                    logger.error("Missing sender email.")
                    raise ValueError("Sender email is required")
                
                # Make sure the service account file exists
                if not os.path.isfile(self.config.service_account_json):
                    logger.error(f"Service account file not found: {self.config.service_account_json}")
                    raise ValueError(f"Service account file not found: {self.config.service_account_json}")

                SCOPES = ['https://www.googleapis.com/auth/gmail.send']
                
                # Log service account details (without sensitive info)
                logger.info(f"Setting up Gmail service with service account: {self.config.service_account_json}")
                logger.info(f"Sender email: {self.config.sender_email}")
                
                credentials = await asyncio.to_thread(
                    service_account.Credentials.from_service_account_file,
                    self.config.service_account_json,
                    scopes=SCOPES,
                    subject=self.config.sender_email  # Impersonating the email sender
                )

                self.service = await asyncio.to_thread(
                    build,
                    'gmail',
                    'v1',
                    credentials=credentials
                )
                
                logger.info("Successfully connected to Gmail API via Service Account")

            except Exception as e:
                logger.error(f"Failed to setup Gmail service: {e}", exc_info=True)
                raise
    
    async def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        html_body: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send an email through Gmail API"""
        try:
            await self.setup()
            
            # Validate required parameters
            if not to:
                raise ValueError("Recipient (to) is required")
            if not subject:
                subject = "(No Subject)"
            if not body:
                body = "(No Content)"
                
            logger.info(f"Preparing to send email to {to} with subject: {subject}")
            
            message = MIMEMultipart('alternative')
            message['Subject'] = subject
            message['From'] = self.config.sender_email
            message['To'] = ','.join(to)
            
            if cc:
                message['Cc'] = ','.join(cc)
            
            if bcc:
                message['Bcc'] = ','.join(bcc)
            
            if reply_to:
                message['Reply-To'] = reply_to
                
            # Attach plain text and HTML parts
            text_part = MIMEText(body, 'plain')
            message.attach(text_part)
            
            if html_body:
                html_part = MIMEText(html_body, 'html')
                message.attach(html_part)
            
            # Encode the message for Gmail API
            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            
            # Create the request
            send_request = self.service.users().messages().send(
                userId='me',
                body={'raw': encoded_message}
            )
            
            # Execute the request
            result = await asyncio.to_thread(send_request.execute)
            
            logger.info(f"Successfully sent email with message ID: {result.get('id')}")
            return result
                
        except Exception as e:
            logger.error(f"Error sending email: {e}", exc_info=True)
            raise
    
    async def cleanup(self):
        """Cleanup resources"""
        try:
            if self.service:
                self.service = None
            logger.info("Cleaned up Gmail resources")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            raise