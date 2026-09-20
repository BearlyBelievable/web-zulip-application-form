# Web Zulip application form

[![License](https://img.shields.io/badge/license-PolyForm%20Internal%20Use%201.0.0-orange)](LICENSE)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Flask](https://img.shields.io/badge/flask-3.1-black)
[![Version](https://img.shields.io/badge/version-1.0.0-informational)](CHANGELOG.md)
![Last commit](https://img.shields.io/github/last-commit/BearlyBelievable/web-zulip-application-form)
[![Tests](https://github.com/BearlyBelievable/web-zulip-application-form/actions/workflows/tests.yml/badge.svg)](https://github.com/BearlyBelievable/web-zulip-application-form/actions/workflows/tests.yml)

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
- (Optional, but recommended) A transactional email service provider
  set up in Zulip, or SMTP settings of your own, for alert emails
  about technical failures or held applications.
- (Optional) A Pelican site on the same server.
- (Optional) A Cloudflare account and Turnstile key for spam
  protection.

## Installing and uninstalling

### First-time setup

1. Clone this repo to the same server that your Zulip instance and
   website are served from.
2. Run `sudo ./install.sh` and fill in the
   [configuration options](#configuration-options).
3. Customize your [form fields](#building-your-form-fields) to fit
   your application.
4. Run `sudo ./generate-form.sh` to generate `application-form.html`
   from them.
5. [Hook up your site](#hooking-up-your-site) to serve the generated
   form.
6. Once everything's wired up, you can check if it's live by running
   `curl -i http://127.0.0.1:8793/apply`. It should return a non-502
   response.

### Changing settings

If you need to update any settings, run `sudo ./install.sh` again to
go through the full setup again.

### Uninstalling

Run `sudo ./uninstall.sh`. It stops and removes the services, removes
the generated form files from your site, and offers to clean up the
reverse proxy wiring, `.venv`, local data, and any leftovers from
older versions of this app.

## Configuration options

### Site setup

Asks whether you're using Pelican or a custom site, and where the
site lives. For Pelican, it also adds `STATIC_PATHS = ["extra"]` and
`THEME_TEMPLATES_OVERRIDES = ["templates"]` to `pelicanconf.py`, if
it doesn't already set them.

### Cloudflare Turnstile (optional)

`/apply` already enforces two independent rate limits, one on the
submitting IP address and one on the submitted email address, so a
single source can't spam submissions. Turnstile adds protection
against distributed or automated abuse that rate limiting alone
doesn't catch.

Prompts for your Turnstile secret and site key. The site key is
baked directly into the generated Turnstile widget in
`application-form.html`. There's nothing else to configure manually.

### Zulip connection

Prompts for:

- Your Zulip site URL, detecting it automatically where possible.
- The bot's email and API key.
- The channel to post applications to. Options come from what the
  bot can already access, so add it to the desired channel in Zulip
  first if it isn't listed.
- The topic to post new applications under.

Before finishing, install.sh runs a check against a throwaway email
to confirm the integration actually works. See
[Troubleshooting](#troubleshooting) if that check fails.

### Alert emails (optional)

Asks whether to send alert emails for technical failures and held
applications, then prompts for SMTP settings if enabled. If Zulip
already has transactional email configured on this server, you can
leave any of these blank to reuse its settings, or only set the
ones you want to override.

### Contact address

Prompts for a contact address for applicants to reach out to for
issues, and for failure alert emails if enabled.

### Reverse proxy (optional)

Detects nginx, Apache, or Caddy and offers to wire up the `/apply`
route for you. If you'd rather set it up by hand, skip this and use
the examples in `deploy/reverse-proxy/`.

## Building your form fields

`application-fields.json` includes a full template showing how form
fields can be added and defined. To change the fields, just edit
`application-fields.json` and then run `sudo ./generate-form.sh` to
regenerate the embeddable `application-form.html`. No service
restart is needed.

### Every field must have these

| Key | Value | Meaning |
|---|---|---|
| `name` | `string` | Form field name. Must be unique across the whole file. |
| `type` | `number`, `text`, `email`, `textarea`, `select`, `multiselect`, or `boolean` | The kind of field. |
| `label` | `string` | The question shown to the applicant. |
| `required` | `boolean` | Whether the field must be filled in. |
| `note` | `dict` | A callout shown under the field. |

A `note` can be left as an empty dict (`{}`) if you don't want one
shown. To show a callout, fill it out with all three of:

| Key | Value | Meaning |
|---|---|---|
| `type` | `info`, `caution`, or `warning` | The callout's style. |
| `title` | `string` | The callout's heading. |
| `text` | `string` | The callout's body. |

### `number` fields can have a `range` field

| Key | Value | Meaning |
|---|---|---|
| `range` | `dict` | Value bounds. |

`range` takes `min` and/or `max`. There's no default for either.

### `text`, `email`, and `textarea` fields can have a `length` field

| Key | Value | Meaning |
|---|---|---|
| `length` | `dict` | Character-count bounds. |

`length` takes `min` and/or `max`. Default `max` comes from
`max_text_length` (`text`/`email`) or `max_textarea_length`
(`textarea`) in `config.conf` when omitted. There's no default
`min`.

### `select` and `multiselect` fields must have an `options` field

| Key | Value | Meaning |
|---|---|---|
| `options` | `dict` | The selectable choices. |

Each option in `options` is structured as a key/value pair to
support extended functionality. The form will use the key as the
choice's exact text, and if you
want just a plain option, you can leave the choice's value as an
empty dict (`{}`). If you want to show a follow-up field when a
specific choice is picked (like gathering more details when "Other"
is selected), then fill out that value dict as a full sub-field. If
you use a select or multi-select field again, it can reveal
follow-up fields of its own the same way, but only up to 2 levels
deep. See the `role_interest` field in `application-fields.json` for
a working example.

### `boolean` fields can have an `options` field

| Key | Value | Meaning |
|---|---|---|
| `options` | `dict` | Follow-up fields for `true` and/or `false`. |

Works the same as `select`/`multiselect`, except the only keys
`options` can use are `"true"` and `"false"`, since those are the
only two values this field can take (shown to the applicant as Yes
and No). Leave `options` out entirely for a plain Yes/No field with
no follow-up.

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
you want the form to appear on. Rebuild your site any time
`install.sh` or `generate-form.sh` updates these files.

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

## Troubleshooting

### Zulip connection check fails during install

Before finishing, install.sh runs a check against a throwaway email
to confirm the integration actually works. It calls
`check_application_email()` through `manage.py shell` and expects a
"no match" result back, since a fabricated address shouldn't already
have an account, invite, or pending application. If it gets anything
else, install.sh stops there without deploying anything. That usually
means `manage.py shell` isn't running cleanly for this app, most
often from wrong permissions on the Zulip deployment or a broken
`.venv`. Fix that, then run `sudo ./install.sh` again.

### Handling technical failures

If a technical failure happens while processing a submission, the
application is held locally in `applications.db` instead of being
lost, and the applicant is shown a submission-failed message on the
page. Both `web-zulip-application-form` and
`web-zulip-application-form-check-pending` log to the systemd
journal (`journalctl -u <unit name>`) with what went wrong and how
often the failure happened.

If alert emails are enabled, your contact address also gets an
automated email about it. It's the only proactive notice you'll
get, since otherwise you'd only find out by checking the logs or
the pending count yourself.

Held submissions are retried automatically by the same timer that
rechecks pending applications. You can run
`check_pending_applications.py` manually to retry sooner once
whatever caused the failure is fixed.

### Detecting duplicate applications

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
| `max_text_length` | `250` | Default character limit for a `text`/`email` field with no `length.max` set. |
| `max_textarea_length` | `1000` | Default character limit for a `textarea` field with no `length.max` set. |
