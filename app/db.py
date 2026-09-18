import sqlite3
from datetime import datetime, timedelta, timezone

from config import app_path, read_app_config

APPLICATIONS_DB_PATH = app_path("applications.db", env_var="APPLICATIONS_DB_PATH")


def get_applications_db():
    conn = sqlite3.connect(APPLICATIONS_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pending_applications ("
        "email TEXT PRIMARY KEY, submitted_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS submission_attempts ("
        "ip TEXT NOT NULL, email TEXT NOT NULL, attempted_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS held_applications ("
        "email TEXT PRIMARY KEY, subject TEXT NOT NULL, body TEXT NOT NULL, "
        "failed_at TEXT NOT NULL)"
    )
    return conn


def hold_application(email, subject, body):
    with get_applications_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO held_applications (email, subject, body, failed_at) "
            "VALUES (?, ?, ?, ?)",
            (email, subject, body, datetime.now(tz=timezone.utc).isoformat()),
        )


def delete_held_application(email):
    with get_applications_db() as conn:
        conn.execute("DELETE FROM held_applications WHERE email = ?", (email,))


def claim_pending_application(email):
    expiry_days = read_app_config("application_expiry_days", default=30, cast=int)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=expiry_days)
    now = datetime.now(tz=timezone.utc).isoformat()
    with get_applications_db() as conn:
        # BEGIN IMMEDIATE takes the write lock up front. Without it, two
        # concurrent submissions for the same email could each find no
        # existing row and each get rowcount == 1, both believing they
        # claimed the application.
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM pending_applications WHERE email = ? AND submitted_at < ?",
            (email, cutoff.isoformat()),
        )
        cursor = conn.execute(
            "INSERT OR IGNORE INTO pending_applications (email, submitted_at) VALUES (?, ?)",
            (email, now),
        )
        return cursor.rowcount == 1


def delete_pending_application(email):
    with get_applications_db() as conn:
        conn.execute("DELETE FROM pending_applications WHERE email = ?", (email,))


def expire_old_attempts(conn):
    window_minutes = read_app_config("rate_limit_window_minutes", default=60, cast=int)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=window_minutes)
    conn.execute("DELETE FROM submission_attempts WHERE attempted_at < ?", (cutoff.isoformat(),))


def count_attempts_by_ip(conn, ip):
    return conn.execute(
        "SELECT COUNT(*) FROM submission_attempts WHERE ip = ?", (ip,)
    ).fetchone()[0]


def is_ip_rate_limited(ip):
    with get_applications_db() as conn:
        expire_old_attempts(conn)
        ip_count = count_attempts_by_ip(conn, ip)
        return ip_count >= read_app_config("max_attempts_per_ip", default=3, cast=int)


def check_and_record_attempt(ip, email):
    now = datetime.now(tz=timezone.utc).isoformat()
    with get_applications_db() as conn:
        # BEGIN IMMEDIATE takes the write lock up front. Without it, two
        # concurrent requests could each count the same attempts as
        # under the limit and both insert, letting more attempts through
        # than the limit allows.
        conn.execute("BEGIN IMMEDIATE")
        expire_old_attempts(conn)
        ip_count = count_attempts_by_ip(conn, ip)
        if ip_count >= read_app_config("max_attempts_per_ip", default=3, cast=int):
            return True
        email_count = conn.execute(
            "SELECT COUNT(*) FROM submission_attempts WHERE email = ?", (email,)
        ).fetchone()[0]
        if email_count >= read_app_config("max_attempts_per_email", default=3, cast=int):
            return True
        conn.execute(
            "INSERT INTO submission_attempts (ip, email, attempted_at) VALUES (?, ?, ?)",
            (ip, email, now),
        )
        return False
