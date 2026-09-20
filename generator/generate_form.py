import argparse
import json
import os
import sys

import markdown as markdown_lib
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

GENERATOR_DIR = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(GENERATOR_DIR, "..", "app"))

from field_schema import validate_fields_schema  # noqa: E402


def generate(fields, action, css_url, js_url, max_text_length, max_textarea_length, turnstile_site_key):
    validate_fields_schema(fields)
    env = Environment(loader=FileSystemLoader(GENERATOR_DIR), autoescape=True)
    env.filters["markdown"] = lambda text: Markup(markdown_lib.markdown(text))
    template = env.get_template("template.jinja")
    return template.render(
        application_fields=fields,
        action=action,
        css_url=css_url,
        js_url=js_url,
        max_text_length=max_text_length,
        max_textarea_length=max_textarea_length,
        turnstile_site_key=turnstile_site_key,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fields_path")
    parser.add_argument("output_path")
    parser.add_argument("--action", default="/apply")
    parser.add_argument("--css-url", default="/application-form.css")
    parser.add_argument("--js-url", default="/application-form.js")
    parser.add_argument("--max-text-length", type=int, default=250)
    parser.add_argument("--max-textarea-length", type=int, default=1000)
    parser.add_argument("--turnstile-site-key", default="")
    args = parser.parse_args()

    with open(args.fields_path) as f:
        fields = json.load(f)

    html = generate(
        fields,
        action=args.action,
        css_url=args.css_url,
        js_url=args.js_url,
        max_text_length=args.max_text_length,
        max_textarea_length=args.max_textarea_length,
        turnstile_site_key=args.turnstile_site_key,
    )

    with open(args.output_path, "w") as f:
        f.write(html)


if __name__ == "__main__":
    main()
