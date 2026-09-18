import logging

from app import process_application
from config import STRINGS
from db import delete_held_application, delete_pending_application, get_applications_db
from notifications import notify_admin_of_failure
from zulip_integration import check_application_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_pending_applications():
    with get_applications_db() as conn:
        emails = [row[0] for row in conn.execute("SELECT email FROM pending_applications")]

    purged = 0
    failed = 0
    for email in emails:
        try:
            status = check_application_email(email)
        except Exception:
            logger.exception("Failed to check status for a pending application")
            failed += 1
            continue
        if status in ("registered", "invited"):
            delete_pending_application(email)
            purged += 1

    logger.info("Checked %d pending application(s), purged %d.", len(emails), purged)

    if failed:
        notify_admin_of_failure(
            STRINGS["admin_pending_check_partial_failure"].format(
                failed_count=failed, total_count=len(emails)
            )
        )


def retry_held_applications():
    with get_applications_db() as conn:
        held = conn.execute("SELECT email, subject, body FROM held_applications").fetchall()

    resolved = 0
    for email, subject, body in held:
        try:
            process_application(email, subject, body)
        except Exception:
            logger.exception("Retry failed for a held application")
            continue
        delete_held_application(email)
        resolved += 1

    still_held = len(held) - resolved
    logger.info("Retried %d held application(s), resolved %d.", len(held), resolved)

    if still_held:
        notify_admin_of_failure(
            STRINGS["admin_held_applications_still_failing"].format(count=still_held)
        )


def main():
    check_pending_applications()
    retry_held_applications()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("The daily pending-application check crashed")
        notify_admin_of_failure(STRINGS["admin_pending_check_crashed"])
        raise
