import ast
import configparser
import json
import logging
import os
import re
import smtplib
from email.message import EmailMessage

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024
logger = logging.getLogger(__name__)

ZULIP_SETTINGS_PATH = "/etc/zulip/settings.py"
APP_SECRETS_PATH = os.environ.get(
    "APP_SECRETS_PATH",
    os.path.join(os.path.dirname(__file__), "secrets.conf"),
)
APP_CONFIG_PATH = os.environ.get(
    "APP_CONFIG_PATH",
    os.path.join(os.path.dirname(__file__), "config.conf"),
)
FIELDS_PATH = os.environ.get(
    "APPLICATION_FIELDS_PATH",
    os.path.join(os.path.dirname(__file__), "data", "application-fields.json"),
)
STRINGS_PATH = os.environ.get(
    "APPLICATION_STRINGS_PATH",
    os.path.join(os.path.dirname(__file__), "strings.json"),
)

if not os.path.exists(APP_SECRETS_PATH):
    raise RuntimeError(f"{APP_SECRETS_PATH} not found. Run install.sh to generate it.")

if not os.path.exists(APP_CONFIG_PATH):
    raise RuntimeError(f"{APP_CONFIG_PATH} not found. Run install.sh to generate it.")

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MAX_TEXT_LENGTH = 250
MAX_TEXTAREA_LENGTH = 1000

with open(STRINGS_PATH) as f:
    STRINGS = json.load(f)


def load_fields():
    with open(FIELDS_PATH) as f:
        return json.load(f)


def read_zulip_setting(name):
    with open(ZULIP_SETTINGS_PATH) as f:
        tree = ast.parse(f.read(), filename=ZULIP_SETTINGS_PATH)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise KeyError(f"{name} not found in {ZULIP_SETTINGS_PATH}")


def read_app_secret(name):
    parser = configparser.ConfigParser()
    parser.read(APP_SECRETS_PATH)
    return parser.get("secrets", name)


def read_app_config(name, default=None):
    parser = configparser.ConfigParser()
    parser.read(APP_CONFIG_PATH)
    if default is not None:
        return parser.get("config", name, fallback=default)
    return parser.get("config", name)


def verify_turnstile(token, remote_ip):
    secret = read_app_secret("turnstile_secret")
    if not secret:
        return True
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


def strip_control_chars(value):
    kept = []
    for ch in value:
        if ch in "\t\n\r" or (ord(ch) >= 0x20 and ord(ch) != 0x7F):
            kept.append(ch)
    return "".join(kept)


def is_field_active(form, field):
    show_when = field.get("show_when")
    if not show_when:
        return True
    if "includes" in show_when:
        return show_when["includes"] in form.getlist(show_when["field"])
    return form.get(show_when["field"], "").strip() == show_when["equals"]


def is_required(field):
    return bool(field.get("required"))


def validate_text(form, field):
    if not is_field_active(form, field):
        return None, None
    ftype = field["type"]
    raw = strip_control_chars(form.get(field["name"], "")).strip()
    if is_required(field) and not raw:
        return None, STRINGS["field_required"].format(label=field["label"])
    if not raw:
        return None, None
    if ftype != "textarea" and ("\n" in raw or "\r" in raw):
        return None, STRINGS["line_breaks_not_allowed"].format(label=field["label"])
    default_max = MAX_TEXTAREA_LENGTH if ftype == "textarea" else MAX_TEXT_LENGTH
    max_len = field.get("maxlength", default_max)
    min_len = field.get("minlength")
    if len(raw) > max_len:
        return None, STRINGS["too_long"].format(label=field["label"])
    if min_len is not None and len(raw) < min_len:
        return None, STRINGS["too_short"].format(label=field["label"])
    if ftype == "email" and not EMAIL_RE.match(raw):
        return None, STRINGS["invalid_email"].format(label=field["label"])
    return raw, None


def validate_number(form, field):
    if not is_field_active(form, field):
        return None, None
    raw = form.get(field["name"], "").strip()
    if is_required(field) and not raw:
        return None, STRINGS["field_required"].format(label=field["label"])
    if not raw:
        return None, None
    if not re.fullmatch(r"-?\d+", raw):
        return None, STRINGS["not_a_number"].format(label=field["label"])
    num = int(raw)
    if "min" in field and num < field["min"]:
        return None, STRINGS["below_minimum"].format(label=field["label"])
    if "max" in field and num > field["max"]:
        return None, STRINGS["above_maximum"].format(label=field["label"])
    return num, None


def validate_choice(form, field):
    if not is_field_active(form, field):
        return None, None
    ftype = field["type"]
    raw = form.get(field["name"], "").strip()
    if ftype == "select":
        allowed = field["options"]
    else:
        allowed = ["true", "false"]
    if is_required(field) and not raw:
        return None, STRINGS["field_required"].format(label=field["label"])
    if raw and raw not in allowed:
        return None, STRINGS["invalid_value"].format(label=field["label"])
    if not raw:
        return None, None
    if ftype == "boolean":
        return raw == "true", None
    return raw, None


def validate_multiselect(form, field):
    if not is_field_active(form, field):
        return None, None
    selected = []
    for v in form.getlist(field["name"]):
        v = v.strip()
        if v:
            selected.append(v)
    if any(v not in field["options"] for v in selected):
        return None, STRINGS["invalid_selection"].format(label=field["label"])
    if is_required(field) and not selected:
        return None, STRINGS["field_required"].format(label=field["label"])
    return selected, None


VALIDATORS = {
    "text": validate_text,
    "email": validate_text,
    "textarea": validate_text,
    "number": validate_number,
    "select": validate_choice,
    "boolean": validate_choice,
    "multiselect": validate_multiselect,
}


def validate_submission(form, fields):
    values, errors = {}, []
    for field in fields:
        value, error = VALIDATORS[field["type"]](form, field)
        if error:
            errors.append(error)
        elif value is not None:
            values[field["name"]] = value
    return values, errors


def format_value(value):
    if isinstance(value, bool):
        if value:
            return "Yes"
        return "No"
    if isinstance(value, list):
        if not value:
            return "(none selected)"
        return ", ".join(value)
    return str(value)


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


@app.route("/apply", methods=["POST"])
def apply():
    token = request.form.get("cf-turnstile-response", "")
    if not verify_turnstile(token, request.remote_addr):
        return jsonify(error=STRINGS["verification_failed"]), 400

    fields = load_fields()
    values, errors = validate_submission(request.form, fields)
    if errors:
        return jsonify(error=STRINGS["invalid_answers"]), 400

    applicant_email = values["invite_email"]
    body_lines = []
    for field in fields:
        if not is_field_active(request.form, field):
            continue
        if field["name"] in values:
            rendered = format_value(values[field["name"]])
        else:
            rendered = "(user did not specify)"
        body_lines.append(f"{field['label']}\n{rendered}")
    body = "\n\n".join(body_lines)

    try:
        smtp_host = read_zulip_setting("EMAIL_HOST")
        smtp_port = read_zulip_setting("EMAIL_PORT")
        recipient = read_app_config("application_recipient_email")
        subject = read_app_config("application_email_subject", default="New application")
        send_email(
            smtp_host,
            smtp_port,
            recipient,
            subject,
            body,
        )
    except Exception:
        logger.exception("Failed to deliver application email")
        try:
            smtp_host = read_zulip_setting("EMAIL_HOST")
            smtp_port = read_zulip_setting("EMAIL_PORT")
            send_email(
                smtp_host,
                smtp_port,
                applicant_email,
                STRINGS["failure_email_subject"],
                STRINGS["failure_email_body"],
            )
        except Exception:
            logger.exception("Failed to notify the applicant of the delivery failure")
        return jsonify(error=STRINGS["submission_failed"]), 502

    return jsonify(success=True)
