import os
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
GENERATOR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "generator"))
sys.path.insert(0, APP_DIR)
sys.path.insert(0, GENERATOR_DIR)

_config_dir = tempfile.mkdtemp()
_config_path = os.path.join(_config_dir, "config.conf")
_secrets_path = os.path.join(_config_dir, "secrets.conf")

with open(_config_path, "w") as f:
    f.write("[config]\n")
with open(_secrets_path, "w") as f:
    f.write("[secrets]\n")

os.environ.setdefault("APP_CONFIG_PATH", _config_path)
os.environ.setdefault("APP_SECRETS_PATH", _secrets_path)
