# Web Zulip application form

This is a small Flask back-end for hooking up an "Apply to join" form
to a Zulip server. It validates a submission, optionally checks a
Cloudflare Turnstile token, and emails the answers to your team by
sending them to the email address of a Zulip channel (no Zulip API
calls involved). If delivery fails, it emails the applicant instead
so they know to try again.

This was built with a Pelican site in mind, but should work with any
site.

## Requirements

- Python 3, for the virtual environment `install.sh` creates.
- Zulip already installed on the same server this gets cloned to
  (Debian or Ubuntu, with systemd). `install.sh` reuses the existing
  `zulip` system user.
- A transactional email service provider (the app reads SMTP host
  and port defaults from `/etc/zulip/settings.py`).
- (Optional) A Pelican site checkout on the same server, if you want
  the bundled application form template installed automatically.
- (Optional) A Cloudflare account and Turnstile key for spam
  protection.

## Deploying

### First-time setup

1. Clone this repo.
2. Run `sudo ./install.sh`. The first time, it walks through the full
   setup:
    - Asks whether you're using Pelican or a custom site, and where
      its checkout lives, then writes the generated files.
    - Prompts for the sender address applications get emailed from,
      your SMTP password, and a reply-to address (leave it blank
      to reuse the sender address), storing them in `config.conf` and
      `secrets.conf`.
    - Prompts for the recipient address and a subject line (blank
      uses "New application").
    - Prompts for a Cloudflare Turnstile site key and secret. Leave
      both blank to skip Turnstile verification entirely.
    - Detects nginx, Apache, or Caddy and offers to wire up the
      `/apply` route for you, or skip it and use the examples in
      `deploy/reverse-proxy/` yourself.
3. Check it's live: `curl -i http://127.0.0.1:8793/apply` should
   return a non-502 response.

**Pelican:** `install.sh` wires up `pelicanconf.py` for you where it
safely can:

- If `pelicanconf.py` doesn't already define `JINJA_GLOBALS`, it
  appends the block that loads `data/application-fields.json` and
  exposes it as the `application_fields` template global. If
  `JINJA_GLOBALS` already exists, it won't touch it and instead tells
  you the line number and what to add.
- If `pelicanconf.py` doesn't already set `THEME_TEMPLATES_OVERRIDES`,
  it adds `THEME_TEMPLATES_OVERRIDES = ["templates"]` and installs
  [`examples/application.html`](examples/application.html) into that
  new `templates` directory. If the setting already exists, it asks
  before installing the template there.

### Changing configuration

Run `sudo ./install.sh` again and choose "Change configuration" to go
through the full setup again, for example to update your SMTP or
Turnstile settings, or move to a different site checkout. You can
also edit the config and secrets files directly.

## Cloudflare Turnstile (optional)

Skip both the site key and secret prompts in `install.sh` to disable
Turnstile entirely. No widget is needed on your form, and every
submission is treated as verified.

If you do use it, `secrets.conf` gets the secret and `config.conf`
gets the site key. `install.sh` prints where the site key needs to go
once you enter it:

- **Pelican:** set it as the `TURNSTILE_SITE_KEY` environment
  variable before building the Pelican site, or change the default in
  `pelicanconf.py`.
- **Any other site:** put it in the `data-sitekey` attribute of your
  Turnstile widget.

## Configuring the form fields

Edit `application-fields.template.json` to change the fields, then
run `sudo ./install.sh` again and choose "Just update the deployed
files". This skips every setup question and just regenerates
`data/application-fields.json` from
`application-fields.template.json`, then, for a Pelican site,
rechecks its template wiring. No service restart needed, the app
reads that file fresh on every request.

One field, `invite_email` (type `email`), must always be present. The
`apply()` route in `app.py` uses it to notify the applicant if
delivering their application fails.

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | Form field name. Must be unique. |
| `type` | yes | One of `text`, `email`, `textarea`, `number`, `select`, `boolean`, `multiselect`. |
| `label` | yes | The question shown to the applicant. |
| `required` | yes | Whether the field must be filled in. |
| `options` | `select`/`multiselect` only | Array of choices. |
| `min`, `max` | `number` only | Optional value bounds. |
| `minlength`, `maxlength` | `text`/`email`/`textarea` only | Character-count bounds. Default `maxlength` is 250 (`text`/`email`) or 1000 (`textarea`). No default `minlength`. |
| `show_when` | optional | Only show and require this field when another field has a value: `{"field": "role", "equals": "Other"}`, or for a `multiselect` value, `{"field": "interests", "includes": "Other"}`. |
| `note`, `note_title`, `note_type` | optional | A callout shown under the field. `note_type` is `info`, `caution`, or `warning`. |

## Hooking up your site

**Pelican:** The bundled template is a complete, working example
that reads `data/application-fields.json` and renders every field,
using CSS classes like `.application-form`, `.form-field`,
`.radio-group`, and `.checkbox-group` that you can style yourself. To
make Pelican actually build a page with that template, give some
content page `Template: application` in its metadata.

If you'd rather write your own markup than use `application.html`,
drop [`render-fields.example.jinja`](examples/render-fields.example.jinja)
into your template where the inputs go instead. It loops over
`application_fields` and renders every field type, so there's no need
to write that logic from scratch.

**Any other site:** Your site needs to serve
`data/application-fields.json` at some URL. Your form needs to
`POST` to `/apply`, with one input per field (`name` matching), plus
a Cloudflare Turnstile widget if you're using one.
[`render-fields.example.js`](examples/render-fields.example.js) is a
drop-in script for a plain HTML/JS site with no build step: point the
`FIELDS_URL` constant in it at wherever you serve the generated JSON,
and include it after your form.
