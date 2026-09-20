import ast
import configparser
import os
import re
import subprocess

import requests

from config import read_app_config, read_app_secret

ZULIP_SETTINGS_PATH = "/etc/zulip/settings.py"
ZULIP_SECRETS_PATH = "/etc/zulip/zulip-secrets.conf"
ZULIP_MANAGE_PY_PATH = "/home/zulip/deployments/current/manage.py"

CHECK_APPLICATION_EMAIL_SCRIPT = """
import os

from zerver.models import PreregistrationUser, UserProfile
from zerver.models.prereg_users import filter_to_valid_prereg_users

email = os.environ["CHECK_EMAIL"]

if UserProfile.objects.filter(delivery_email__iexact=email, is_active=True).exists():
    print("RESULT:registered")
elif filter_to_valid_prereg_users(
    PreregistrationUser.objects.filter(email__iexact=email), invitations_only=True
).exists():
    print("RESULT:invited")
else:
    print("RESULT:none")
"""


def read_zulip_setting(name):
    with open(ZULIP_SETTINGS_PATH) as f:
        tree = ast.parse(f.read(), filename=ZULIP_SETTINGS_PATH)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    else:
        raise KeyError(f"{name} not found in {ZULIP_SETTINGS_PATH}")


def read_zulip_secret(name):
    parser = configparser.ConfigParser()
    parser.read(ZULIP_SECRETS_PATH)
    return parser.get("secrets", name, fallback="")


def check_application_email(email):
    result = subprocess.run(
        [ZULIP_MANAGE_PY_PATH, "shell"],
        input=CHECK_APPLICATION_EMAIL_SCRIPT,
        env={**os.environ, "CHECK_EMAIL": email},
        capture_output=True,
        text=True,
        timeout=30,
    )
    for line in result.stdout.splitlines():
        if line.startswith("RESULT:"):
            return line[len("RESULT:") :]
    raise RuntimeError(
        f"check_application_email.py produced no RESULT line: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


DETECT_REALMS_SCRIPT = """
from django.conf import settings

from zerver.models import Realm

for realm in Realm.objects.exclude(string_id=settings.SYSTEM_BOT_REALM):
    print(f"REALM:{realm.name}|{realm.url}")
"""


def detect_realms():
    result = subprocess.run(
        [ZULIP_MANAGE_PY_PATH, "shell"],
        input=DETECT_REALMS_SCRIPT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    realms = []
    for line in result.stdout.splitlines():
        if line.startswith("REALM:"):
            name, _, url = line[len("REALM:") :].partition("|")
            realms.append((name, url))
    return realms


DETECT_CHANNELS_SCRIPT = """
import os

from zerver.models import Recipient, Stream, Subscription, get_user_profile_by_email

bot_email = os.environ["BOT_EMAIL"]

try:
    bot = get_user_profile_by_email(bot_email)
except Exception:
    bot = None

if bot is not None:
    stream_ids = Subscription.objects.filter(
        user_profile=bot, active=True, recipient__type=Recipient.STREAM
    ).values_list("recipient__type_id", flat=True)
    for stream in Stream.objects.filter(id__in=stream_ids, deactivated=False).order_by("name"):
        label = stream.name + (" (private)" if stream.invite_only else "")
        print(f"CHANNEL:{label}|{stream.id}")
"""


def detect_channels(bot_email):
    result = subprocess.run(
        [ZULIP_MANAGE_PY_PATH, "shell"],
        input=DETECT_CHANNELS_SCRIPT,
        env={**os.environ, "BOT_EMAIL": bot_email},
        capture_output=True,
        text=True,
        timeout=30,
    )
    channels = []
    for line in result.stdout.splitlines():
        if line.startswith("CHANNEL:"):
            label, _, channel_id = line[len("CHANNEL:") :].rpartition("|")
            channels.append((label, channel_id))
    return channels


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
