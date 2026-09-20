import json
import os

from generate_form import generate

FIELDS_PATH = os.path.join(os.path.dirname(__file__), "..", "application-fields.json")


def load_fields():
    with open(FIELDS_PATH) as f:
        return json.load(f)


def render(fields):
    return generate(
        fields,
        action="/apply",
        css_url="/x.css",
        js_url="/x.js",
        max_text_length=250,
        max_textarea_length=1000,
        turnstile_site_key="",
    )


def test_shipped_fields_render_without_error():
    html = render(load_fields())
    assert "<form" in html
    assert "role_interest_details" in html


def test_note_renders_for_every_field_type():
    base = {"name": "n", "required": True, "label": "L"}
    fields_by_type = [
        {**base, "type": "text"},
        {**base, "type": "email"},
        {**base, "type": "textarea"},
        {**base, "type": "number"},
        {**base, "type": "boolean"},
        {**base, "type": "select", "options": {"A": {}, "B": {}}},
        {**base, "type": "multiselect", "options": {"A": {}}},
    ]
    for field in fields_by_type:
        field["note"] = {"type": "info", "title": "Heads up", "text": "check this"}
        html = render([field])
        assert "Heads up" in html, field["type"]


def test_stray_options_on_unsupported_type_produces_no_companion():
    field = {
        "name": "plain",
        "type": "text",
        "required": True,
        "label": "L",
        "note": {},
        "options": {"Other": {"name": "hidden", "type": "text", "required": True, "label": "L2", "note": {}}},
    }
    html = render([field])
    assert "data-companion-of" not in html


def test_single_checkbox_multiselect_renders_one_checkbox():
    field = {
        "name": "agree",
        "type": "multiselect",
        "required": True,
        "label": "Rules",
        "note": {},
        "options": {"I agree to follow the rules": {}},
    }
    html = render([field])
    assert html.count('type="checkbox"') == 1
    assert 'data-multiselect-required="true"' in html
