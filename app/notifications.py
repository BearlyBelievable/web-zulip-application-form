import logging
import smtplib
from email.message import EmailMessage

from config import STRINGS, read_app_config, read_app_secret
from zulip_integration import read_zulip_secret, read_zulip_setting

logger = logging.getLogger(__name__)


def send_email(to, subject, body):
    smtp_host = read_app_config("smtp_host", default="") or read_zulip_setting("EMAIL_HOST")
    smtp_port = read_app_config("smtp_port", default="") or read_zulip_setting("EMAIL_PORT")
    smtp_user = read_app_config("smtp_user", default="") or read_zulip_setting("EMAIL_HOST_USER")
    smtp_password = read_app_secret("smtp_password") or read_zulip_secret("email_password")
    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(smtp_host, int(smtp_port), timeout=10) as smtp:
        smtp.starttls()
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(msg)


def notify_admin_of_failure(body):
    if read_app_config("alert_emails_enabled", default="no") != "yes":
        logger.info("Alert emails disabled; skipping. %s", body)
        return
    try:
        contact_email = read_app_config("contact_email")
        send_email(contact_email, STRINGS["admin_failure_email_subject"], body)
    except Exception:
        logger.exception("Failed to notify the admin of a failure")
