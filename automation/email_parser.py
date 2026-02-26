#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
PrintFlow Pro — Email Parser & Auto Job Intake
File: automation/email_parser.py

PURPOSE:
  Monitors a dedicated inbox (jobs@printflowpro.in) via IMAP.
  Automatically creates a job record in Supabase for every
  valid client email received with attachments.

SCHEDULE:
  Run every 15 minutes via GitHub Actions cron or Render cron:
  */15 * * * * python3 automation/email_parser.py

INSTALL:
  pip install supabase python-dotenv requests imapclient
═══════════════════════════════════════════════════════════════
"""

import os
import imaplib
import email
import email.header
import json
import re
import time
import logging
import tempfile
from email.mime.text import MIMEText
import smtplib
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Logging setup ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/email_parser.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
IMAP_HOST    = os.getenv('IMAP_HOST', 'imap.gmail.com')
IMAP_PORT    = int(os.getenv('IMAP_PORT', 993))
EMAIL_USER   = os.getenv('SMTP_USER')           # jobs@printflowpro.in
EMAIL_PASS   = os.getenv('SMTP_PASS')           # Gmail App Password
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
API_BASE     = os.getenv('API_URL', 'https://printing-api.onrender.com')

ALLOWED_EXTENSIONS = {'.pdf', '.xlsx', '.xls', '.csv'}
MAX_FILE_SIZE_MB   = 50


# ══════════════════════════════════════════════════════════════
# IMAP CONNECTION
# ══════════════════════════════════════════════════════════════
def connect_imap():
    """Connect to Gmail IMAP and return mailbox object."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(EMAIL_USER, EMAIL_PASS)
        log.info(f"✓ IMAP connected as {EMAIL_USER}")
        return mail
    except Exception as e:
        log.error(f"✗ IMAP connection failed: {e}")
        raise


# ══════════════════════════════════════════════════════════════
# EMAIL PROCESSING
# ══════════════════════════════════════════════════════════════
def decode_header_value(value):
    """Safely decode email header (handles encoded subjects/names)."""
    if not value:
        return ''
    decoded_parts = email.header.decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or 'utf-8', errors='replace'))
        else:
            result.append(str(part))
    return ' '.join(result)


def extract_email_address(raw):
    """Extract clean email address from 'Name <email@domain.com>' format."""
    match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', raw or '')
    return match.group(0).lower() if match else ''


def get_attachments(msg):
    """Extract all valid attachments from an email message."""
    attachments = []
    for part in msg.walk():
        if part.get_content_disposition() != 'attachment':
            continue
        filename = decode_header_value(part.get_filename())
        if not filename:
            continue
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            log.warning(f"  Skipping {filename} — extension {ext} not allowed")
            continue
        payload = part.get_payload(decode=True)
        size_mb = len(payload) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            log.warning(f"  Skipping {filename} — size {size_mb:.1f}MB exceeds {MAX_FILE_SIZE_MB}MB limit")
            continue
        attachments.append({
            'filename': filename,
            'content':  payload,
            'size_mb':  round(size_mb, 2),
            'ext':      ext
        })
    return attachments


# ══════════════════════════════════════════════════════════════
# CLIENT LOOKUP
# ══════════════════════════════════════════════════════════════
def lookup_client(sender_email):
    """Look up client record by email address in Supabase."""
    try:
        headers = {
            'apikey':        SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type':  'application/json'
        }
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/clients",
            params={'email': f'eq.{sender_email}', 'select': '*'},
            headers=headers,
            timeout=10
        )
        data = resp.json()
        return data[0] if data else None
    except Exception as e:
        log.error(f"Client lookup failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# JOB CREATION
# ══════════════════════════════════════════════════════════════
def detect_job_type(subject, body, attachments):
    """
    Auto-detect job type from email subject/body keywords.
    Returns: simplex | duplex | multipage
    """
    text = (subject + ' ' + body).lower()
    if any(k in text for k in ['duplex', 'double side', 'both side']):
        return 'duplex'
    if any(k in text for k in ['multi', 'multipage', 'booklet', 'multiple page']):
        return 'multipage'
    return 'simplex'  # default


def detect_quantity(subject, body):
    """Extract quantity from subject or body if mentioned."""
    text = subject + ' ' + body
    # Match patterns like: "14820 pieces", "22,400 pcs", "5000 nos"
    patterns = [
        r'(\d[\d,]+)\s*(?:pieces?|pcs?|nos?|copies)',
        r'qty[:\s]+(\d[\d,]+)',
        r'quantity[:\s]+(\d[\d,]+)'
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(',', ''))
    return None


def detect_dispatch_mode(subject, body):
    """Detect dispatch mode from email content."""
    text = (subject + ' ' + body).lower()
    if 'speed post' in text and ('ack' in text or 'acknowledgement' in text):
        return 'speed_ack'
    if 'speed post' in text:
        return 'speed_no_ack'
    if 'inland' in text:
        return 'inland'
    return 'ordinary'


def create_job_via_api(client, subject, body, attachments):
    """
    POST to the PrintFlow API to create a job.
    Uploads attachments as multipart form data.
    """
    job_type      = detect_job_type(subject, body, attachments)
    quantity      = detect_quantity(subject, body) or 1000  # default if not found
    dispatch_mode = detect_dispatch_mode(subject, body)

    files  = {}
    fields = {
        'client_id':     client['id'],
        'job_type':      job_type,
        'quantity':      str(quantity),
        'dispatch_mode': dispatch_mode,
        'contact_name':  client.get('contact_name', ''),
        'contact_email': client.get('email', ''),
        'notes':         f"Auto-created from email. Subject: {subject}"
    }

    # Attach PDF as print_file, Excel/CSV as data_file
    temp_files = []
    for att in attachments:
        tmp = tempfile.NamedTemporaryFile(
            suffix=att['ext'], delete=False,
            dir='/tmp'
        )
        tmp.write(att['content'])
        tmp.flush()
        temp_files.append(tmp.name)

        if att['ext'] == '.pdf' and 'print_file' not in files:
            files['print_file'] = (att['filename'], open(tmp.name, 'rb'), 'application/pdf')
        elif att['ext'] in ('.xlsx', '.xls', '.csv') and 'data_file' not in files:
            files['data_file'] = (att['filename'], open(tmp.name, 'rb'), 'application/octet-stream')

    try:
        resp = requests.post(
            f"{API_BASE}/api/jobs",
            data=fields,
            files=files if files else None,
            timeout=30
        )
        result = resp.json()
        # Clean up temp files
        for path in temp_files:
            try:
                os.unlink(path)
            except Exception:
                pass
        return result
    except Exception as e:
        log.error(f"API job creation failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ══════════════════════════════════════════════════════════════
def send_ack_email(to_email, to_name, job_number, quantity, job_type):
    """Send acknowledgement email to client confirming job receipt."""
    subject = f"Job {job_number} Received — PrintFlow Pro"
    body = f"""Dear {to_name},

Thank you for sending your print job. It has been received and registered in our system.

Job Reference: {job_number}
Print Type:    {job_type.title()}
Quantity:      {quantity:,} pieces
Status:        Received — Processing Started

We will validate your file and send you a proof for approval shortly.
Expected turnaround: 2–4 hours.

Regards,
PrintFlow Pro Team
jobs@printflowpro.in
"""
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From']    = f"PrintFlow Pro <{EMAIL_USER}>"
        msg['To']      = to_email

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
        log.info(f"  ✓ Ack email sent to {to_email}")
    except Exception as e:
        log.warning(f"  ✗ Could not send ack email: {e}")


def send_unknown_sender_alert(sender_email, subject):
    """Alert admin about email from unknown sender."""
    try:
        msg = MIMEText(
            f"Received email from unknown sender.\n\n"
            f"From: {sender_email}\nSubject: {subject}\n\n"
            f"Please register this client in the system or reply manually."
        )
        msg['Subject'] = f"[ALERT] Unknown sender: {sender_email}"
        msg['From']    = EMAIL_USER
        msg['To']      = EMAIL_USER  # alert goes to admin (same inbox)

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
    except Exception as e:
        log.warning(f"Could not send unknown sender alert: {e}")


# ══════════════════════════════════════════════════════════════
# MAIN PROCESSING LOOP
# ══════════════════════════════════════════════════════════════
def process_inbox():
    """Main function — connect, scan unread emails, process each."""
    mail = connect_imap()
    mail.select('INBOX')

    # Search for unread emails
    _, msg_ids = mail.search(None, 'UNSEEN')
    ids = msg_ids[0].split()

    if not ids:
        log.info("No new emails to process.")
        mail.logout()
        return

    log.info(f"Found {len(ids)} unread email(s) to process.")
    processed = 0
    errors    = 0

    for msg_id in ids:
        try:
            _, msg_data = mail.fetch(msg_id, '(RFC822)')
            raw_email   = msg_data[0][1]
            msg         = email.message_from_bytes(raw_email)

            subject     = decode_header_value(msg.get('Subject', ''))
            sender_raw  = msg.get('From', '')
            sender_email = extract_email_address(sender_raw)
            date_str    = msg.get('Date', '')

            log.info(f"Processing: '{subject}' from {sender_email}")

            # Get email body
            body = ''
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == 'text/plain':
                        body = part.get_payload(decode=True).decode('utf-8', errors='replace')
                        break
            else:
                body = msg.get_payload(decode=True).decode('utf-8', errors='replace')

            # Get attachments
            attachments = get_attachments(msg)

            if not attachments:
                log.info(f"  No valid attachments — skipping (flagging for manual review)")
                mail.store(msg_id, '+FLAGS', '\\Flagged')
                continue

            # Look up client
            client = lookup_client(sender_email)

            if not client:
                log.warning(f"  Unknown sender: {sender_email}")
                send_unknown_sender_alert(sender_email, subject)
                # Move to manual review folder
                try:
                    mail.copy(msg_id, 'Manual Review')
                except Exception:
                    pass
                mail.store(msg_id, '+FLAGS', '\\Flagged')
                continue

            log.info(f"  Client matched: {client['company_name']}")
            log.info(f"  Attachments: {[a['filename'] for a in attachments]}")

            # Create job via API
            result = create_job_via_api(client, subject, body, attachments)

            if result and result.get('job'):
                job = result['job']
                log.info(f"  ✓ Job created: {job['job_number']}")

                # Send ack email
                send_ack_email(
                    to_email   = client['email'],
                    to_name    = client['contact_name'],
                    job_number = job['job_number'],
                    quantity   = job['quantity'],
                    job_type   = job['job_type']
                )

                # Mark email as read and move to Processed folder
                mail.store(msg_id, '+FLAGS', '\\Seen')
                try:
                    mail.copy(msg_id, 'Processed')
                    mail.store(msg_id, '+FLAGS', '\\Deleted')
                except Exception:
                    pass  # Processed folder may not exist yet
                processed += 1
            else:
                log.error(f"  ✗ Job creation failed for email from {sender_email}")
                errors += 1

        except Exception as e:
            log.error(f"Error processing message {msg_id}: {e}")
            errors += 1
            continue

    mail.expunge()
    mail.logout()
    log.info(f"Done. Processed: {processed}, Errors: {errors}")


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    log.info("═" * 60)
    log.info("PrintFlow Email Parser — Starting")
    log.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("═" * 60)

    # Create logs dir if not exists
    Path('logs').mkdir(exist_ok=True)

    process_inbox()
