# Web Zulip application form

This is a small Flask back-end for hooking up an "Apply to join" form
to a Zulip server. It validates a submission, optionally checks a
Cloudflare Turnstile token, checks whether the email already has an
account or a pending invite, and posts the answers to a Zulip channel
using a bot account. If something goes wrong, such as a technical
failure posting to Zulip or checking the account status, the
submission is held locally and retried once the problem is fixed,
and the contact address gets an email about it.

This was built with a Pelican site in mind, but should work with any
site.

## Requirements

- Python 3, for the virtual environment `install.sh` creates.
- Zulip already installed on the same server this gets cloned to
  (Debian or Ubuntu, with systemd), as a standard production install
  with the usual `/home/zulip/deployments/current` layout. `install.sh`
  reuses the existing `zulip` system user, and the duplicate-application
  check runs `manage.py shell` from that deployment directly.
- A bot in Zulip (Personal settings > Bots), added to whatever
  channel should receive applications.
- A transactional email service provider, only needed if a technical
  failure needs to notify the contact address (the app reads SMTP
  host and port defaults from `/etc/zulip/settings.py`).
- (Optional) A Pelican site checkout on the same server, if you want
  the bundled application form template installed automatically.
- (Optional) A Cloudflare account and Turnstile key for spam
  protection.

## Deploying

### First-time setup

1. Clone this repo.
2. Run `sudo ./install.sh`. The first time, it walks through the full
   setup:
    - Asks whether you're using Pelican or a custom site and where
      the checkout lives, then writes the generated files.
    - Prompts for the sender address used only if a technical failure
      needs to notify the contact address, your SMTP password, and a
      reply-to address (leave it blank to reuse the sender address),
      storing them in `config.conf` and `secrets.conf`.
    - Prompts for your Zulip site URL, the ID of the channel to post
      applications to, the email and API key for the bot, and a
      contact address to show an applicant who's already applied and
      waiting on review.
    - Prompts for a Cloudflare Turnstile site key and secret. Leave
      both blank to skip Turnstile verification entirely.
    - Detects nginx, Apache, or Caddy and offers to wire up the
      `/apply` route for you, or skip it and use the examples in
      `deploy/reverse-proxy/` yourself.
    - Runs the duplicate-application check once against a throwaway
      email, to confirm the Zulip integration actually works before
      finishing.
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

## Detecting duplicate applications

Before posting a submission, the app checks the given email against
three things, in order, and stops at the first match:

- **Already has a Zulip account.** The applicant sees "That email
  address can't be used", with no further explanation, and nothing
  else happens.
- **Already has a pending invite that hasn't been used yet.** The
  applicant is told directly to check their inbox for the invite
  email.
- **Already submitted an application that's still waiting on manual
  review.** Kept as a local record in `applications.db` next to
  `app.py`. A record expires after 30 days and is deleted once the
  same email later shows up as registered or invited. The applicant
  is told their application is still pending and given a contact
  address for anything urgent.

Only a submission that matches none of these gets posted to Zulip and
recorded as pending. The check itself runs
[`check_application_email.py`](check_application_email.py) through
Zulip's `manage.py shell`.

A pending record is also cleared without waiting on a resubmission.
`install.sh` sets up a daily systemd timer that runs
[`check_pending_applications.py`](check_pending_applications.py),
which rechecks every pending email against Zulip the same way and
deletes any record that's since been invited or registered. If a
recheck itself fails, an alert is emailed to the contact address.

## Handling technical failures

If a technical failure happens while processing a submission, such as
a problem checking the account status or posting to Zulip, the
submission is held locally in `applications.db` instead of being
lost. The contact address gets an email about it, and the applicant
just sees a submission-failed message on the page since there's
nothing left for them to do.

Held submissions are retried automatically by the same daily systemd
timer that rechecks pending applications. Run
`check_pending_applications.py` manually to retry sooner, once
whatever caused the failure is fixed.

Both `web-zulip-application-form` and
`web-zulip-application-form-check-pending` log to the systemd
journal (`journalctl -u <unit name>`), since neither service redirects
its output elsewhere. A failure is logged with what went wrong and
how often, never the applicant's email address.

## Rate limiting

`/apply` enforces two independent limits, each 3 submissions per
rolling hour: one on the submitting IP address and one on the
submitted email address. Going over either one rejects the
submission immediately, before the duplicate-application check or
anything gets posted to Zulip.

## Advanced settings

A few settings have sensible defaults and `install.sh` never prompts
for them. Edit a value directly in `config.conf` to change it from
the default.

| Key | Default | Meaning |
|---|---|---|
| `max_attempts_per_ip` | `3` | Submissions allowed per rolling hour from one IP address. |
| `max_attempts_per_email` | `3` | Submissions allowed per rolling hour for one email address. |
| `rate_limit_window_minutes` | `60` | Length of the rolling window used for both limits above. |
| `application_expiry_days` | `30` | How long a pending-application record is kept before a resubmission is treated as new. |
| `max_body_bytes` | `8192` | Largest `/apply` request body accepted. Raise this if a large set of fields makes a legitimate submission exceed it. |
| `max_text_length` | `250` | Default character limit for a `text`/`email` field with no `maxlength` set. |
| `max_textarea_length` | `1000` | Default character limit for a `textarea` field with no `maxlength` set. |

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
rechecks the template wiring. No service restart is needed.

One field, `invite_email` (type `email`), must always be present. The
`apply()` route in `app.py` uses it for the duplicate-application
check and to address the application once it's posted to Zulip.

| Key | Required | Meaning |
|---|---|---|
| `name` | yes, except inside `conditional_options` | Form field name. Must be unique. A field nested inside another field's `conditional_options` gets its name generated automatically instead (see below), and doesn't take this key at all. |
| `type` | yes | One of `text`, `email`, `textarea`, `number`, `select`, `boolean`, `multiselect`. |
| `label` | yes | The question shown to the applicant. |
| `required` | yes | Whether the field must be filled in. |
| `options` | `select`/`multiselect` only | Array of choices. Don't list a choice here if it has a `conditional_options` entry; that choice is added to the list automatically. |
| `min`, `max` | `number` only | Optional value bounds. |
| `minlength`, `maxlength` | `text`/`email`/`textarea` only | Character-count bounds. Default `maxlength` comes from `max_text_length` (`text`/`email`) or `max_textarea_length` (`textarea`) in `config.conf`. No default `minlength`. |
| `conditional_options` | `select`/`multiselect` only | Extra fields shown and required only when a specific choice of this field is picked. Maps a choice to an array of field definitions, each without its own `name`: `{"Other": [{"type": "text", "required": true, "label": "..."}]}`. The choice itself (`"Other"` above) doesn't need to also appear in `options`, and each nested field's name is generated from the parent field's name and the choice (`role_interest` + `Other` becomes `role_interest_other`), so there's nothing to keep in sync by hand. A field inside `conditional_options` can have its own `conditional_options`, nested as deep as needed, but a form is easier to fill in with only a level or two of follow-up questions. |
| `note`, `note_title`, `note_type` | optional | A callout shown under the field. `note_type` is `info`, `caution`, or `warning`. |

## Hooking up your site

**Pelican:** The bundled template is a complete, working example
that reads `data/application-fields.json` and renders every field,
using CSS classes like `.application-form`, `.form-field`,
`.radio-group`, `.checkbox-group`, and `.form-message` (with an
`is-success` or `is-error` class added once a submission finishes)
that you can style yourself. It already disables the submit button
while a submission is in flight and shows the result inline. To
make Pelican actually build a page with that template, add
`Template: application` to the metadata of some
content page.

If you'd rather write your own markup than use `application.html`,
drop [`render-fields.example.jinja`](examples/render-fields.example.jinja)
into your template where the inputs go instead. It loops over
`application_fields` and renders every field type.

**Any other site:** Your site needs to serve
`data/application-fields.json` at some URL. Your form needs a
`submit` button, an element with `id="applicationFormMessage"` for
the result to appear in, and a Cloudflare Turnstile widget if you're
using one.
[`render-fields.example.js`](examples/render-fields.example.js) is a
drop-in script for a plain HTML/JS site with no build step. It
submits the form to `/apply` itself, disabling the submit button
while that's in flight and showing the result in the message
element. Point the `FIELDS_URL` constant in it at wherever you serve
the generated JSON, and include it after your form.
