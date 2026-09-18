import logging
import smtplib
from email.message import EmailMessage

from config import STRINGS, read_app_config, read_app_secret
from zulip_integration import read_zulip_setting

logger = logging.getLogger(__name__)


def send_email(smtp_host, smtp_port, to, subject, body):
    smtp_user = read_app_config("smtp_user")
    reply_to = read_app_config("reply_to_email", default="") or smtp_user
    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg["Reply-To"] = reply_to
    msg.set_content(body)
    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
        smtp.starttls()
        smtp.login(smtp_user, read_app_secret("smtp_password"))
        smtp.send_message(msg)


def notify_admin_of_failure(body):
    try:
        smtp_host = read_zulip_setting("EMAIL_HOST")
        smtp_port = read_zulip_setting("EMAIL_PORT")
        contact_email = read_app_config("contact_email")
        send_email(smtp_host, smtp_port, contact_email, STRINGS["admin_failure_email_subject"], body)
    except Exception:
        logger.exception("Failed to notify the admin of a failure")
