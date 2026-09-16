import ast
import configparser
import json
import logging
import os
import re
import smtplib
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import lru_cache

import requests
from flask import Flask, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix


def app_path(*default_parts, env_var=None):
    default = os.path.join(os.path.dirname(__file__), *default_parts)
    if env_var is None:
        return default
    return os.environ.get(env_var, default)


APP_SECRETS_PATH = app_path("secrets.conf", env_var="APP_SECRETS_PATH")
APP_CONFIG_PATH = app_path("config.conf", env_var="APP_CONFIG_PATH")
if not os.path.exists(APP_SECRETS_PATH):
    raise RuntimeError(f"{APP_SECRETS_PATH} not found. Run install.sh to generate it.")

if not os.path.exists(APP_CONFIG_PATH):
    raise RuntimeError(f"{APP_CONFIG_PATH} not found. Run install.sh to generate it.")


@lru_cache(maxsize=None)
def _read_ini(path):
    parser = configparser.ConfigParser()
    parser.read(path)
    return parser


def read_app_secret(name):
    return _read_ini(APP_SECRETS_PATH).get("secrets", name)


def read_app_config(name, default=None, cast=str):
    parser = _read_ini(APP_CONFIG_PATH)
    if default is not None:
        value = parser.get("config", name, fallback=default)
    else:
        value = parser.get("config", name)
    return cast(value)


app = Flask(__name__)
# Trust one reverse-proxy hop so request.remote_addr reflects the real
# client IP, which per-IP rate limiting depends on.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
MAX_CONTENT_LENGTH = read_app_config("max_body_bytes", default=8192, cast=int)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ZULIP_SETTINGS_PATH = "/etc/zulip/settings.py"
ZULIP_MANAGE_PY_PATH = "/home/zulip/deployments/current/manage.py"

CHECK_APPLICATION_EMAIL_SCRIPT = app_path("check_application_email.py")
FIELDS_PATH = app_path("data", "application-fields.json", env_var="APPLICATION_FIELDS_PATH")
STRINGS_PATH = app_path("strings.json", env_var="APPLICATION_STRINGS_PATH")
APPLICATIONS_DB_PATH = app_path("applications.db", env_var="APPLICATIONS_DB_PATH")


def load_json(path):
    with open(path) as f:
        return json.load(f)


STRINGS = load_json(STRINGS_PATH)

FIELD_TYPES = {"text", "email", "textarea", "number", "select", "boolean", "multiselect"}

SCHEMA_ERRORS = {
    "missing_name": "Field schema is missing required key 'name': {field}",
    "invalid_type": "Field '{name}' has an invalid or missing 'type'",
    "missing_label": "Field '{name}' is missing required key 'label'",
    "missing_required": "Field '{name}' is missing required key 'required'",
    "missing_options": "Field '{name}' must have an 'options' list",
    "unexpected_conditional_options": "Field '{name}' has 'conditional_options' but isn't select/multiselect",
    "invalid_conditional_options": "Field '{name}' has a 'conditional_options' that isn't a dict",
}


class SchemaError(RuntimeError):
    def __init__(self, key, **kwargs):
        super().__init__(SCHEMA_ERRORS[key].format(**kwargs))


def validate_fields_schema(fields):
    """Validates every field, including nested conditional_options
    children, using an explicit stack instead of recursion so schema
    depth is never limited by the Python call stack.
    """
    pending = [(field, None) for field in fields]
    while pending:
        field, parent_name = pending.pop()
        if parent_name is None:
            if "name" not in field:
                raise SchemaError("missing_name", field=field)
            name = field["name"]
        else:
            name = parent_name

        if field.get("type") not in FIELD_TYPES:
            raise SchemaError("invalid_type", name=name)
        if "label" not in field:
            raise SchemaError("missing_label", name=name)
        if "required" not in field:
            raise SchemaError("missing_required", name=name)

        conditional_options = field.get("conditional_options")
        if field["type"] in ("select", "multiselect"):
            if not isinstance(field.get("options"), list):
                raise SchemaError("missing_options", name=name)
        elif conditional_options is not None:
            raise SchemaError("unexpected_conditional_options", name=name)

        if not conditional_options:
            continue
        if not isinstance(conditional_options, dict):
            raise SchemaError("invalid_conditional_options", name=name)
        for option, children in conditional_options.items():
            for child in children:
                pending.append((child, f"{name} > {option}"))


FIELDS = load_json(FIELDS_PATH)
validate_fields_schema(FIELDS)


def read_zulip_setting(name):
    """Reads a single setting from the Zulip settings.py file by parsing
    it as text, since this app runs without a Zulip Django environment.
    """
    with open(ZULIP_SETTINGS_PATH) as f:
        tree = ast.parse(f.read(), filename=ZULIP_SETTINGS_PATH)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    else:
        # The loop finished without finding an assignment to `name`.
        raise KeyError(f"{name} not found in {ZULIP_SETTINGS_PATH}")


def verify_turnstile(secret, token, remote_ip):
    resp = requests.post(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data={
            "secret": secret,
            "response": token,
            "remoteip": remote_ip,
        },
        timeout=5,
    )
    return resp.json().get("success", False)


def name_conditional_fields(fields, parent_name, option):
    slug = re.sub(r"[^a-z0-9]+", "_", option.lower()).strip("_")
    base_name = f"{parent_name}_{slug}"
    named_fields = []
    for index, field in enumerate(fields):
        if index == 0:
            name = base_name
        else:
            name = f"{base_name}_{index + 1}"
        named_fields.append({**field, "name": name})
    return named_fields


def flatten_active_fields(form, fields):
    active_fields = []
    for field in fields:
        active_fields.append(field)
        conditional_options = field.get("conditional_options")
        if not conditional_options:
            continue

        if field["type"] == "multiselect":
            selected_options = form.getlist(field["name"])
        else:
            selected_options = [form.get(field["name"], "")]

        for option, children in conditional_options.items():
            if option in selected_options:
                named_fields = name_conditional_fields(children, field["name"], option)
                active_fields.extend(flatten_active_fields(form, named_fields))

    return active_fields


def normalize_field_value(form, field):
    ftype = field["type"]
    match ftype:
        case "text" | "email" | "textarea":
            value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", form.get(field["name"], "")).strip()
            if ftype != "textarea":
                value = " ".join(value.split())
            return value
        case "number":
            return form.get(field["name"], "").strip()
        case "select" | "boolean":
            return form.get(field["name"], "")
        case "multiselect":
            # Drop only empty entries. Anything else is left for
            # has_invalid_option to reject as a real invalid selection.
            return [v for v in form.getlist(field["name"]) if v]
        case _:
            raise ValueError(f"Unknown field type: {ftype}")


def field_error(key, field):
    return STRINGS[key].format(label=field["label"])


class ValidationError(Exception):
    def __init__(self, key, field):
        super().__init__(field_error(key, field))


def validate_text_value(value, field):
    ftype = field["type"]
    if ftype == "textarea":
        default_max = read_app_config("max_textarea_length", default=1000, cast=int)
    else:
        default_max = read_app_config("max_text_length", default=250, cast=int)
    max_len = field.get("maxlength", default_max)
    min_len = field.get("minlength")
    if len(value) > max_len:
        raise ValidationError("too_long", field)
    if min_len is not None and len(value) < min_len:
        raise ValidationError("too_short", field)
    if ftype == "email" and not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", value):
        raise ValidationError("invalid_email", field)


def validate_number_value(value, field):
    if not re.fullmatch(r"-?\d+", value):
        raise ValidationError("not_a_number", field)
    num = int(value)
    if "min" in field and num < field["min"]:
        raise ValidationError("below_minimum", field)
    if "max" in field and num > field["max"]:
        raise ValidationError("above_maximum", field)


def allowed_options(field):
    conditional_options = field.get("conditional_options")
    if not conditional_options:
        return field["options"]
    return field["options"] + list(conditional_options.keys())


def has_invalid_option(values, field):
    return any(v not in allowed_options(field) for v in values)


def validate_select_value(value, field):
    if has_invalid_option([value], field):
        raise ValidationError("invalid_value", field)


def validate_multiselect_value(value, field):
    if has_invalid_option(value, field):
        raise ValidationError("invalid_selection", field)


def validate_boolean_value(value, field):
    if value not in ("true", "false"):
        raise ValidationError("invalid_value", field)


def validate_field_value(value, field):
    ftype = field["type"]
    match ftype:
        case "text" | "email" | "textarea":
            validate_text_value(value, field)
        case "number":
            validate_number_value(value, field)
        case "select":
            validate_select_value(value, field)
        case "multiselect":
            validate_multiselect_value(value, field)
        case "boolean":
            validate_boolean_value(value, field)
        case _:
            raise ValueError(f"Unknown field type: {ftype}")


def validate_submission(form, active_fields):
    values, errors = {}, []
    for field in active_fields:
        value = normalize_field_value(form, field)
        if not value:
            if field["required"]:
                errors.append(field_error("field_required", field))
            continue
        try:
            validate_field_value(value, field)
        except ValidationError as error:
            errors.append(str(error))
            continue

        match field["type"]:
            case "number":
                values[field["name"]] = int(value)
            case "boolean":
                values[field["name"]] = value == "true"
            case _:
                values[field["name"]] = value
    return values, errors


def escape_markdown(value):
    return re.sub(r"([\\`*_\[\]])", r"\\\1", value)


def format_value(value):
    match value:
        case bool():
            return "Yes" if value else "No"
        case list():
            if not value:
                return "_(none selected)_"
            if len(value) == 1:
                return escape_markdown(value[0])
            return "\n".join(f"- {escape_markdown(item)}" for item in value)
        case _:
            return escape_markdown(str(value))


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


def check_application_email(email):
    """Runs check_application_email.py inside the Zulip environment via
    `manage.py shell`, since this app has no direct access to the Zulip
    database or ORM.
    """
    with open(CHECK_APPLICATION_EMAIL_SCRIPT) as script:
        result = subprocess.run(
            [ZULIP_MANAGE_PY_PATH, "shell"],
            stdin=script,
            env={**os.environ, "CHECK_EMAIL": email},
            capture_output=True,
            text=True,
            timeout=30,
        )
    # manage.py shell may print other output before the script runs.
    # Only the RESULT: line is meaningful.
    for line in result.stdout.splitlines():
        if line.startswith("RESULT:"):
            return line[len("RESULT:") :]
    raise RuntimeError(
        f"check_application_email.py produced no RESULT line: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


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


def post_to_zulip(topic, body):
    site_url = read_app_config("zulip_site_url")
    channel = read_app_config("application_channel_id")
    bot_email = read_app_config("zulip_bot_email")
    bot_api_key = read_app_secret("zulip_bot_api_key")
    response = requests.post(
        f"{site_url}/api/v1/messages",
        auth=(bot_email, bot_api_key),
        data={
            "type": "stream",
            "to": channel,
            "topic": topic,
            "content": body,
        },
        timeout=10,
    )
    response.raise_for_status()


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
