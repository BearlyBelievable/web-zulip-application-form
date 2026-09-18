# Web Zulip application form

![Python](https://img.shields.io/badge/python-3-blue)
![Flask](https://img.shields.io/badge/flask-3.1-black)
![Last commit](https://img.shields.io/github/last-commit/BearlyBelievable/web-zulip-application-form)
[![License](https://img.shields.io/badge/license-PolyForm%20Internal%20Use%201.0.0-orange)](LICENSE)

This is a small Flask back-end for hooking up an "Apply to join" form
to post in a [Zulip](https://zulip.com/) server via a bot account. It
validates a submission on both the front-end and back-end, performs
rate-limit and duplicate submission checks, and can optionally be
hooked to a Cloudflare Turnstile token for automated spam and bot
protection.

This was built with a [Pelican](https://getpelican.com/) site in mind
but should hopefully work with any site.

## Requirements

- A standard production deployment of Zulip installed on the same
  server as this app. The app reuses the existing `zulip` system
  user and runs a `manage.py shell` from that deployment directly.
- A bot user in Zulip that's been added to whatever channel
  should receive the applications.
- A transactional email service provider set up in Zulip for
  sending technical failure notices (the app reads SMTP host and
  port defaults from `/etc/zulip/settings.py`).
- (Optional) A Pelican site on the same server.
- (Optional) A Cloudflare account and Turnstile key for spam
  protection.

## Deploying

### First-time setup

1. Clone this repo.
2. Run `sudo ./install.sh`. It walks through the full setup the first
   time:
    - Asks whether you're using Pelican or a custom site and where
      the site lives.
    - Prompts for the sender address (used for technical failure
      notifications), your SMTP password, and a reply-to address (leave
      it blank to reuse the sender address).
    - Prompts for your Zulip site URL, the ID of the channel to post
      applications to, the email and API key for the bot, and an email
      address that applicants can reach out to for issues.
    - Prompts for a Cloudflare Turnstile site key and secret.
    - Detects nginx, Apache, or Caddy and offers to wire up the
      `/apply` route for you. Skip that and use the examples in
      `deploy/reverse-proxy/` if you'd rather set it up by hand.
    - Runs a check against a throwaway email to confirm the Zulip
      integration actually works before finishing.
3. Once install is complete, you can check if it's live by running
   `curl -i http://127.0.0.1:8793/apply`. It should return a non-502
   response.

**Pelican:** `install.sh` wires up `pelicanconf.py` for you where it
safely can:

- Adds `STATIC_PATHS = ["extra"]` and
  `THEME_TEMPLATES_OVERRIDES = ["templates"]` if `pelicanconf.py`
  doesn't already set them.
- On first run, it writes a starter page template, and then
  generates a complete `application-form.html` that's included in
  it. The template and form are placed into the templates
  directory.

### Cloudflare Turnstile (optional)

During install, you'll be asked to enter your Turnstile secret and
site keys. The site key will be baked directly into the generated
Turnstile widget in the `application-form.html`, so there's nothing
you'll need to manually configure.

### Changing settings

If you need to update any settings, run `sudo ./install.sh` again
and choose "Change configuration" to go through the full setup
again.

## Configuring the form fields

`application-fields.json` includes a full template showing how form
fields can be added and defined. Every top-level field needs a
unique `name`, a `type`, a `label`, and a `required` flag. `select`
and `multiselect` fields can add `conditional_options` to show extra
fields when a specific choice is picked. `text`, `email`, `textarea`,
and `number` fields can set a min/max. Any field can add a `note`
for a callout shown underneath it. The full list of options is as
follows:

| Key | Required | Meaning |
|---|---|---|
| `name` | yes, except inside `conditional_options` | Form field name. Must be unique. |
| `type` | yes | One of `text`, `email`, `textarea`, `number`, `select`, `boolean`, `multiselect`. |
| `label` | yes | The question shown to the applicant. |
| `required` | yes | Whether the field must be filled in. |
| `note_type`, `note_title`, `note_text` | optional, but all three must be filled | A callout shown under the field: `note_type` is `info`, `caution`, or `warning`, `note_title` is its heading, and `note_text` is its body. |
| `min`, `max` | `number` only | Optional value bounds. |
| `minlength`, `maxlength` | `text`/`textarea`/`email` only | Character-count bounds. Default `maxlength` comes from `max_text_length` (`text`/`email`) or `max_textarea_length` (`textarea`) in `config.conf`. No default `minlength`. |
| `options` | `select`/`multiselect` only | A list of options to select. |
| `conditional_options` | `select`/`multiselect` only | Extra fields shown only when a specific choice is picked. |

On `conditional_options`: a `name` key is not required, and the
choice itself doesn't need to appear in `options` directly. Each
nested field's name is generated from the parent field's name and
the option it's shown under (`role_interest` + `Other` becomes
`role_interest_other`). A `conditional_options` field can itself have
`conditional_options` nested as deep as needed.

To change the fields, just edit `application-fields.json` and then
run `sudo ./install.sh`. Select "Just update the deployed files" to
skip the setup questions and regenerate the embeddable
`application-form.html`. No service restart is needed.

**To note:** The field `invite_email` (type `email`) must always be
present, as the `apply()` route in `app.py` uses it for the
duplicate-application check and to address the application once
it's posted to Zulip.

## Hooking up your site

The generated `application-form.html` includes the `<form>`
element, every defined field, the message element, the submit
button (disabled until every required field validates), and the
`<link>`/`<script>` tags for its CSS and JS. It should be
essentially ready to drop into any site as-is.

**For Pelican sites:** `application-form.html` and the starter page
template
([`examples/page-template.example.jinja`](examples/page-template.example.jinja))
are written into your `THEME_TEMPLATES_OVERRIDES` directory. The
template extends your theme's `base.html` and is yours to customize
(it won't be overwritten again). From there, just add
`Template: application` to the meta-data of whichever content page
you want the form to appear on.

**Any other site:** `application-form.html`, `application-form.js`,
and `application-form.css` are written straight into your site's
root directory. The generated HTML file's contents can go wherever
you want the form to appear on your page.

### Styling the components

The form uses CSS classes that you can style directly, like
`.application-form`, `.form-field`, `.radio-group`,
`.checkbox-group`, and `.form-message` (with `is-success` or
`is-error` once a submission finishes). The form highlights an
invalid field with a `.has-error`, and shows a live `used / max`
count in a `.char-counter` element once a text field is close to
its length limit. Both use normalized default colors that you can
replace by setting the `--zulip-apply-error-color` and
`--zulip-apply-warn-color` CSS custom properties in your
stylesheet.

## Handling technical failures

If a technical failure happens while processing a submission, the
application is held locally in `applications.db` instead of being
lost. Your contact address will get an automated email about it, and
the applicant will be shown a submission-failed message on the page.
Both `web-zulip-application-form` and
`web-zulip-application-form-check-pending` log to the systemd
journal (`journalctl -u <unit name>`) with what went wrong and how
often the failure happened.

Held submissions are retried automatically by the same timer that
rechecks pending applications. You can run
`check_pending_applications.py` manually to retry sooner once
whatever caused the failure is fixed.

## Rate limiting

`/apply` enforces two independent rate limits: one on the submitting
IP address and one on the submitted email address. Going over either
one rejects the submission immediately before the
duplicate-application check or anything gets posted to Zulip.

## Detecting duplicate applications

Before posting a submission, the app runs through Zulip's
`manage.py shell` using `check_application_email()` in
[`zulip_integration.py`](app/zulip_integration.py) and checks the
given email against your server for current status:

- **Already has a Zulip account:** The applicant sees a simple
  "That email address can't be used" message.
- **Already has a pending invite they haven't used yet:** Applicant
  is told to check their inbox for the invite.
- **An application was submitted but no invite sent yet:** The
  application is kept as a local record in `applications.db` until
  it expires (per `application_expiry_days`). The applicant is told
  it's still pending and given the configured contact address for
  anything urgent.

A submission is only posted to Zulip and recorded as pending once it
clears all three checks.

`install.sh` sets up a daily systemd timer that runs
[`check_pending_applications.py`](app/check_pending_applications.py),
so that a pending record can clear on its own automatically.

## Advanced settings

These settings already have sensible defaults, but you can edit the
value in `config.conf` if you want something different.

| Key | Default | Meaning |
|---|---|---|
| `max_attempts_per_ip` | `3` | Submissions allowed per rolling hour from one IP address. |
| `max_attempts_per_email` | `3` | Submissions allowed per rolling hour for one email address. |
| `rate_limit_window_minutes` | `60` | Length of the rolling window used for both limits above. |
| `application_expiry_days` | `30` | How long a pending-application record is kept before a resubmission is treated as new. |
| `max_body_bytes` | `8192` | Largest `/apply` request body accepted. Raise this if a large set of fields makes a legitimate submission exceed it. |
| `max_text_length` | `250` | Default character limit for a `text`/`email` field with no `maxlength` set. |
| `max_textarea_length` | `1000` | Default character limit for a `textarea` field with no `maxlength` set. |
