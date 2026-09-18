import configparser
import json
import os
from functools import lru_cache


APP_ROOT = os.path.dirname(os.path.dirname(__file__))


def app_path(*default_parts, env_var=None):
    default = os.path.join(APP_ROOT, *default_parts)
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


STRINGS_PATH = app_path("strings.json", env_var="APPLICATION_STRINGS_PATH")

with open(STRINGS_PATH) as f:
    STRINGS = json.load(f)
