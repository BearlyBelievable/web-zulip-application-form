import json
import logging
import sqlite3

from flask import Flask, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

from config import STRINGS, app_path, read_app_config, read_app_secret
from db import (
    check_and_record_attempt,
    claim_pending_application,
    delete_pending_application,
    hold_application,
    is_ip_rate_limited,
)
from field_schema import validate_fields_schema
from notifications import notify_admin_of_failure
from turnstile import verify_turnstile
from validation import flatten_active_fields, validate_submission
from zulip_integration import check_application_email, format_value, post_to_zulip

app = Flask(__name__)
# Trust one reverse-proxy hop so request.remote_addr reflects the real
# client IP, which per-IP rate limiting depends on.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
app.config["MAX_CONTENT_LENGTH"] = read_app_config("max_body_bytes", default=8192, cast=int)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FIELDS_PATH = app_path("data", "application-fields.json", env_var="APPLICATION_FIELDS_PATH")
with open(FIELDS_PATH) as f:
    FIELDS = json.load(f)
validate_fields_schema(FIELDS)


def process_application(email, subject, body):
    status = check_application_email(email)

    match status:
        case "registered":
            delete_pending_application(email)
            logger.info("Application submitted with an email that already has an account")
            return "registered"
        case "invited":
            delete_pending_application(email)
            return "invited"

    if not claim_pending_application(email):
        return "already_pending"

    try:
        post_to_zulip(subject, body)
    except Exception:
        delete_pending_application(email)
        raise

    return "posted"


@app.route("/apply", methods=["POST"])
def apply():
    try:
        if is_ip_rate_limited(request.remote_addr):
            return jsonify(error=STRINGS["rate_limited"]), 429
    except sqlite3.OperationalError:
        logger.exception("Rate limit check failed")
        return jsonify(error=STRINGS["server_busy"]), 503

    turnstile_secret = read_app_secret("turnstile_secret")
    if turnstile_secret:
        token = request.form.get("cf-turnstile-response", "")
        if not verify_turnstile(turnstile_secret, token, request.remote_addr):
            return jsonify(error=STRINGS["verification_failed"]), 400

    active_fields = flatten_active_fields(request.form, FIELDS)
    values, errors = validate_submission(request.form, active_fields)
    if errors:
        return jsonify(error=STRINGS["invalid_answers"]), 400

    email = values["invite_email"]
    email_key = email.lower()

    try:
        if check_and_record_attempt(request.remote_addr, email_key):
            return jsonify(error=STRINGS["rate_limited"]), 429
    except sqlite3.OperationalError:
        logger.exception("Rate limit check failed")
        return jsonify(error=STRINGS["server_busy"]), 503

    body_lines = []
    for field in active_fields:
        if field["name"] in values:
            rendered = format_value(values[field["name"]])
        else:
            rendered = "_(user did not specify)_"
        body_lines.append(f"**{field['label']}**\n{rendered}")
    body = "\n\n".join(body_lines)
    subject = read_app_config("application_email_subject", default="New application")

    try:
        outcome = process_application(email_key, subject, body)
    except Exception:
        logger.exception("Failed to process an application")
        hold_application(email_key, subject, body)
        notify_admin_of_failure(STRINGS["admin_application_held"].format(email=email))
        return jsonify(error=STRINGS["submission_failed"]), 502

    match outcome:
        case "registered":
            return jsonify(error=STRINGS["email_already_registered"]), 400
        case "invited":
            return jsonify(error=STRINGS["email_already_invited"]), 400
        case "already_pending":
            contact_email = read_app_config("contact_email")
            message = STRINGS["application_already_pending"].format(contact_email=contact_email)
            return jsonify(error=message), 400

    return jsonify(success=True)
