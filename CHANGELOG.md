# Changelog

## 1.0.0

- Replaced `conditional_options` with nested field definitions directly
  in `options`, also supported on `boolean` fields via `true`/`false`
  keys, capped at 2 levels deep. `select` now requires at least 2
  options and `multiselect` at least 1.
- Collapsed `note_title`/`note_text`/`note_type` into `note`, `min`/`max`
  into `range`, and `minlength`/`maxlength` into `length`. `note` is now
  required on every field (`{}` for none).
- Fixed `note` only rendering on `text`/`email` fields.
- Split form generation out of `install.sh` into a standalone
  `generate-form.sh`.
- Zulip site URL and channel detection during install now use
  `manage.py shell`, scoped to what the bot can access.
- Added `uninstall.sh`, which stops the services, removes the generated
  site files, and offers to clean up reverse proxy wiring, `.venv`, and
  local data. `install.sh` also detects and cleans up leftovers from
  older versions when updating a deployment: a dead
  `data/application-limits.json`, the old `pelicanconf.py`
  `application_fields` wiring, and the old full-page template.
- Added a pytest test suite.
- Added `.gitattributes` so every file stays LF regardless of what
  platform edits it.

## 0.5.0

- Reorganized the app's source into `app/` and `generator/`, and
  `install.sh` now generates `application-form.html` directly from
  `application-fields.json`, replacing the separate Pelican and
  vanilla-JS implementations.
- Renamed `application-fields.template.json` to `application-fields.json`.
- Renamed the note field's `note` key to `note_text`. `note_title`,
  `note_text`, and `note_type` had to be set together or not at all.
- Added a `LICENSE` (PolyForm Internal Use 1.0.0).

## 0.4.0

- Extracted the application form's script and stylesheet into their
  own files instead of embedding them in the site theme.

## 0.3.0

- Text length limits now come from `config.conf` instead of being
  hardcoded.

## 0.2.1

- Fixed conditional companion fields not syncing and validating
  correctly before submitting.

## 0.2.0

- Submissions now post to a Zulip channel instead of being emailed
  directly.

## 0.1.1

- Fixed reverse-proxy config backups being stored in the wrong
  location.

## 0.1.0

- Initial release.
