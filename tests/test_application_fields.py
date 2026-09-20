import json
import os

from field_schema import validate_fields_schema

FIELDS_PATH = os.path.join(os.path.dirname(__file__), "..", "application-fields.json")


def load_fields():
    with open(FIELDS_PATH) as f:
        return json.load(f)


def test_shipped_fields_are_valid():
    validate_fields_schema(load_fields())


def test_invite_email_field_present():
    names = {field["name"] for field in load_fields()}
    assert "invite_email" in names
