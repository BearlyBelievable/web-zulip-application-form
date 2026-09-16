#!/usr/bin/env bash
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root." >&2
    exit 1
fi

if ! command -v systemctl &>/dev/null; then
    echo "Error: systemctl not found. This script assumes a systemd-based" >&2
    echo "Ubuntu or Debian system, matching the officially supported platforms" >&2
    echo "for Zulip" >&2
    echo "(this app requires Zulip to already be installed on this server)." >&2
    exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME=web-zulip-application-form
SERVICE_UNIT_PATH=/etc/systemd/system/$SERVICE_NAME.service
CHECK_PENDING_UNIT_NAME=web-zulip-application-form-check-pending
CHECK_PENDING_SERVICE_UNIT_PATH=/etc/systemd/system/$CHECK_PENDING_UNIT_NAME.service
CHECK_PENDING_TIMER_UNIT_PATH=/etc/systemd/system/$CHECK_PENDING_UNIT_NAME.timer
RUN_AS_USER=zulip
SECRETS_FILE="$APP_DIR/secrets.conf"
CONFIG_FILE="$APP_DIR/config.conf"
ZULIP_MANAGE_PY=/home/zulip/deployments/current/manage.py

if [ ! -f /etc/zulip/settings.py ]; then
    echo "Error: /etc/zulip/settings.py not found. This app requires Zulip to" >&2
    echo "already be installed on this server." >&2
    exit 1
fi

if ! id -u "$RUN_AS_USER" &>/dev/null; then
    echo "Error: the '$RUN_AS_USER' user doesn't exist, but /etc/zulip/settings.py" >&2
    echo "does. This script expects a standard Zulip install. It reuses the" >&2
    echo "existing Zulip system user, since this app already needs read access" >&2
    echo "to that file." >&2
    exit 1
fi

echo "App root: $APP_DIR"

get_conf_value() {
    local key="$1" file="$2"
    grep -E "^${key}[[:space:]]*=" "$file" | head -1 | cut -d= -f2- | sed 's/^[[:space:]]*//'
}

set_conf_value() {
    local key="$1" value="$2" file="$3" escaped
    escaped=$(printf '%s' "$value" | sed -e 's/[\&|]/\\&/g')
    sed -i "s|^${key}[[:space:]]*=.*|$key = $escaped|" "$file"
}

require_absolute_path() {
    case "$1" in
        /*) ;;
        *)
            echo "Error: $1 must be an absolute path." >&2
            exit 1
            ;;
    esac
}

prompt_for_key() {
    local key="$1" label="$2" silent="$3" required="$4" file="$5" current new_value
    current=$(get_conf_value "$key" "$file")
    if [ "$silent" = "yes" ]; then
        if [ -n "$current" ]; then
            read -r -s -p "$label is already set. Press Enter to keep it, or type a new value to replace it: " new_value
        else
            read -r -s -p "$label: " new_value
        fi
        echo
    else
        if [ -n "$current" ]; then
            read -r -p "$label is already set to '$current'. Press Enter to keep it, or type a new value: " new_value
        else
            read -r -p "$label: " new_value
        fi
    fi
    if [ -n "$new_value" ]; then
        set_conf_value "$key" "$new_value" "$file"
    elif [ -z "$current" ] && [ "$required" = "yes" ]; then
        echo "Error: $key is required." >&2
        exit 1
    fi
}

detect_site_confs() {
    local kind="$1" f
    case "$kind" in
        nginx)
            for f in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
                [ -f "$f" ] && grep -q -E 'server[[:space:]]*\{' "$f" && echo "$f"
            done
            ;;
        apache)
            for f in /etc/apache2/sites-enabled/*.conf; do
                [ -f "$f" ] && grep -q -i '<VirtualHost' "$f" && echo "$f"
            done
            ;;
        caddy)
            [ -f /etc/caddy/Caddyfile ] && echo /etc/caddy/Caddyfile
            ;;
    esac
}

resolve_site_conf() {
    local kind="$1" candidates=() override choice i c

    while IFS= read -r c; do
        [ -n "$c" ] && candidates+=("$c")
    done < <(detect_site_confs "$kind")

    if [ "${#candidates[@]}" -eq 1 ]; then
        echo "Detected $kind site config: ${candidates[0]}" >&2
        read -r -p "Press Enter to use it, or type a different path: " override
        if [ -n "$override" ]; then
            echo "$override"
        else
            echo "${candidates[0]}"
        fi
        return
    fi

    if [ "${#candidates[@]}" -gt 1 ]; then
        echo "Found multiple $kind site configs:" >&2
        i=1
        for c in "${candidates[@]}"; do
            echo "  $i) $c" >&2
            i=$((i + 1))
        done
        echo "  $i) other (type a path)" >&2
        read -r -p "Which one? " choice
        if [ "$choice" = "$i" ] || [ -z "$choice" ]; then
            read -r -p "Path to your $kind site config file: " choice
        else
            choice="${candidates[$((choice - 1))]}"
        fi
        echo "$choice"
        return
    fi

    read -r -p "Path to your $kind site config file: " choice
    echo "$choice"
}

apply_reverse_proxy_config() {
    local kind="$1" snippet_file="$2" close_marker="$3" site_conf backup line_no confirm

    site_conf=$(resolve_site_conf "$kind")
    if [ ! -f "$site_conf" ]; then
        echo "Error: $site_conf not found." >&2
        return 1
    fi

    if grep -qF "127.0.0.1:8793" "$site_conf"; then
        echo "$site_conf already proxies to 127.0.0.1:8793. Skipping."
        return 0
    fi

    mkdir -p "$APP_DIR/reverse-proxy-backups"
    backup="$APP_DIR/reverse-proxy-backups/$(basename "$site_conf").bak.$(date +%s)"
    cp "$site_conf" "$backup"

    line_no=$(grep -n -F "$close_marker" "$site_conf" | tail -1 | cut -d: -f1)
    if [ -z "$line_no" ]; then
        echo "Error: couldn't find '$close_marker' in $site_conf." >&2
        return 1
    fi

    awk -v n="$line_no" -v snippet="$snippet_file" '
        NR==n { while ((getline line < snippet) > 0) print line }
        { print }
    ' "$site_conf" >"${site_conf}.tmp" && mv "${site_conf}.tmp" "$site_conf"

    echo "--- Proposed change to $site_conf ---"
    diff -u "$backup" "$site_conf" || true
    echo "--------------------------------------"
    read -r -p "Apply this change and reload $kind? [y/N] " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        cp "$backup" "$site_conf"
        echo "Reverted. $site_conf left unchanged. Backup kept at $backup."
        return 1
    fi

    case "$kind" in
        nginx)
            if ! nginx -t; then
                cp "$backup" "$site_conf"
                echo "nginx config test failed. Restored $site_conf from backup." >&2
                return 1
            fi
            systemctl reload nginx
            ;;
        apache)
            if ! apache2ctl configtest; then
                cp "$backup" "$site_conf"
                echo "Apache config test failed. Restored $site_conf from backup." >&2
                return 1
            fi
            systemctl reload apache2
            ;;
        caddy)
            if ! caddy validate --config "$site_conf" --adapter caddyfile; then
                cp "$backup" "$site_conf"
                echo "Caddy config validation failed. Restored $site_conf from backup." >&2
                return 1
            fi
            systemctl reload caddy
            ;;
    esac

    echo "$kind reloaded. Backup of the original file kept at $backup."
}

regenerate_files() {
    local site_kind site_root fields_file template_overrides_dir
    local install_template needs_overrides_setting template_file confirm

    site_kind=$(get_conf_value site_kind "$CONFIG_FILE")
    site_root=$(get_conf_value site_root "$CONFIG_FILE")

    fields_file="$site_root/data/application-fields.json"
    mkdir -p "$(dirname "$fields_file")"
    cp "$APP_DIR/application-fields.template.json" "$fields_file"
    echo "Wrote $fields_file from application-fields.template.json."

    if [ "$site_kind" != "Pelican" ]; then
        echo "Your own site needs to read/serve this file itself. See README.md."
        return
    fi

    if [ ! -f "$site_root/pelicanconf.py" ]; then
        echo "Error: $site_root/pelicanconf.py not found. $site_root doesn't" >&2
        echo "look like a Pelican site checkout anymore." >&2
        exit 1
    fi

    if grep -q "application_fields" "$site_root/pelicanconf.py"; then
        :
    elif grep -q "^JINJA_GLOBALS[[:space:]]*=" "$site_root/pelicanconf.py"; then
        globals_line=$(grep -n "^JINJA_GLOBALS[[:space:]]*=" "$site_root/pelicanconf.py" | head -1 | cut -d: -f1)
        echo "pelicanconf.py already defines JINJA_GLOBALS on line $globals_line. Add"
        echo "this yourself to expose the field list to templates:"
        echo
        echo "    import re"
        echo
        echo "    OPTION_SLUG_RE = re.compile(r'[^a-z0-9]+')"
        echo
        echo "    def resolve_conditional_names(fields, parent_name=None, option=None):"
        echo "        resolved = []"
        echo "        for index, field in enumerate(fields):"
        echo "            if parent_name is not None:"
        echo "                slug = OPTION_SLUG_RE.sub('_', option.lower()).strip('_')"
        echo "                base_name = f'{parent_name}_{slug}'"
        echo "                name = base_name if index == 0 else f'{base_name}_{index + 1}'"
        echo "                field = {**field, 'name': name}"
        echo "            conditional_options = field.get('conditional_options')"
        echo "            if conditional_options:"
        echo "                field = {**field, 'conditional_options': {"
        echo "                    opt: resolve_conditional_names(children, parent_name=field['name'], option=opt)"
        echo "                    for opt, children in conditional_options.items()"
        echo "                }}"
        echo "            resolved.append(field)"
        echo "        return resolved"
        echo
        echo "    with open(os.path.join(os.path.dirname(__file__), 'data', 'application-fields.json')) as f:"
        echo "        APPLICATION_FIELDS = resolve_conditional_names(json.load(f))"
        echo
        echo "and add 'application_fields': APPLICATION_FIELDS as a key in that"
        echo "existing JINJA_GLOBALS dict."
    else
        cat >> "$site_root/pelicanconf.py" <<'PYEOF'

import re

OPTION_SLUG_RE = re.compile(r'[^a-z0-9]+')


def resolve_conditional_names(fields, parent_name=None, option=None):
    resolved = []
    for index, field in enumerate(fields):
        if parent_name is not None:
            slug = OPTION_SLUG_RE.sub('_', option.lower()).strip('_')
            base_name = f'{parent_name}_{slug}'
            name = base_name if index == 0 else f'{base_name}_{index + 1}'
            field = {**field, 'name': name}
        conditional_options = field.get('conditional_options')
        if conditional_options:
            field = {**field, 'conditional_options': {
                opt: resolve_conditional_names(children, parent_name=field['name'], option=opt)
                for opt, children in conditional_options.items()
            }}
        resolved.append(field)
    return resolved


with open(os.path.join(os.path.dirname(__file__), 'data', 'application-fields.json')) as f:
    APPLICATION_FIELDS = resolve_conditional_names(json.load(f))

JINJA_GLOBALS = {'application_fields': APPLICATION_FIELDS}
PYEOF
        echo "Added the application_fields JINJA_GLOBALS wiring to pelicanconf.py."
    fi

    template_overrides_dir=$(sed -n -E \
        "s/^THEME_TEMPLATES_OVERRIDES[[:space:]]*=[[:space:]]*\[[[:space:]]*['\"]([^'\"]+)['\"].*/\1/p" \
        "$site_root/pelicanconf.py" | head -1)

    install_template=y
    if [ -z "$template_overrides_dir" ]; then
        template_overrides_dir="templates"
        printf '\nTHEME_TEMPLATES_OVERRIDES = ["templates"]\n' >> "$site_root/pelicanconf.py"
        echo "Added THEME_TEMPLATES_OVERRIDES = [\"templates\"] to pelicanconf.py."
    else
        read -r -p "pelicanconf.py already sets THEME_TEMPLATES_OVERRIDES to '$template_overrides_dir'. Install the application form template there? [y/N] " install_template
    fi

    if [ "$install_template" = "y" ] || [ "$install_template" = "Y" ]; then
        case "$template_overrides_dir" in
            /*) ;;
            *) template_overrides_dir="$site_root/$template_overrides_dir" ;;
        esac
        template_file="$template_overrides_dir/application.html"
        mkdir -p "$template_overrides_dir"

        confirm=y
        if [ -f "$template_file" ]; then
            read -r -p "$template_file already exists. Overwrite with the bundled template? [y/N] " confirm
        fi
        if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
            cp "$APP_DIR/examples/application.html" "$template_file"
            echo "Wrote $template_file."
        else
            echo "Left $template_file unchanged."
        fi

        echo "See README.md for the content page it still needs."
    else
        echo "Skipped installing the application form template. See README.md for what to add."
    fi
}

if [ ! -f "$SECRETS_FILE" ]; then
    cat > "$SECRETS_FILE" <<'EOF'
[secrets]
smtp_password =
turnstile_secret =
zulip_bot_api_key =
EOF
fi

FIRST_RUN=no
if [ ! -f "$CONFIG_FILE" ]; then
    FIRST_RUN=yes
    cat > "$CONFIG_FILE" <<'EOF'
[config]
site_kind =
site_root =
zulip_site_url =
application_channel_id =
zulip_bot_email =
application_email_subject =
contact_email =
smtp_user =
reply_to_email =
turnstile_site_key =

# Advanced settings below, all optional. install.sh never prompts for
# these, and the defaults shown here are what the app uses if a
# setting is missing entirely. Edit a value directly to change it.
max_attempts_per_ip = 3
max_attempts_per_email = 3
rate_limit_window_minutes = 60
application_expiry_days = 30
max_body_bytes = 8192
max_text_length = 250
max_textarea_length = 1000
EOF
fi

MODE=setup
if [ "$FIRST_RUN" = "no" ]; then
    PS3="What do you want to do? "
    select MODE_CHOICE in "Change configuration" "Just update the deployed files"; do
        if [ -n "$MODE_CHOICE" ]; then
            break
        fi
        echo "Please choose a number 1-2."
    done
    if [ "$MODE_CHOICE" = "Just update the deployed files" ]; then
        MODE=update
    fi
fi

if [ "$MODE" = "update" ]; then
    if [ -z "$(get_conf_value site_kind "$CONFIG_FILE")" ] || [ -z "$(get_conf_value site_root "$CONFIG_FILE")" ]; then
        echo "Error: no site configured yet. Choose \"Change configuration\" first." >&2
        exit 1
    fi

    if [ -z "$(get_conf_value smtp_user "$CONFIG_FILE")" ]; then
        prompt_for_key smtp_user "SMTP from address, used only if a technical failure needs to notify an applicant" no yes "$CONFIG_FILE"
    fi
    if [ -z "$(get_conf_value smtp_password "$SECRETS_FILE")" ]; then
        prompt_for_key smtp_password "SMTP password" yes yes "$SECRETS_FILE"
    fi
    if [ -z "$(get_conf_value zulip_site_url "$CONFIG_FILE")" ]; then
        prompt_for_key zulip_site_url "Zulip site URL (e.g. https://miatsu.co)" no yes "$CONFIG_FILE"
    fi
    if [ -z "$(get_conf_value application_channel_id "$CONFIG_FILE")" ]; then
        prompt_for_key application_channel_id "Channel to post new applications to, by its numeric ID rather than its name, so a later rename doesn't break it (in the left sidebar, click the channel's ... menu, choose Copy link to channel, and use the number right after channel/ in that link)" no yes "$CONFIG_FILE"
        CHANNEL_ID=$(get_conf_value application_channel_id "$CONFIG_FILE")
        if ! [[ "$CHANNEL_ID" =~ ^[0-9]+$ ]]; then
            echo "Error: application_channel_id must be a number, the channel's ID, not its name." >&2
            exit 1
        fi
    fi
    if [ -z "$(get_conf_value zulip_bot_email "$CONFIG_FILE")" ]; then
        prompt_for_key zulip_bot_email "Application bot's email address (Personal settings > Bots)" no yes "$CONFIG_FILE"
    fi
    if [ -z "$(get_conf_value zulip_bot_api_key "$SECRETS_FILE")" ]; then
        prompt_for_key zulip_bot_api_key "Application bot's API key" yes yes "$SECRETS_FILE"
    fi
    if [ -z "$(get_conf_value contact_email "$CONFIG_FILE")" ]; then
        prompt_for_key contact_email "Contact address shown to an applicant who's already applied and waiting on review" no yes "$CONFIG_FILE"
    fi

    regenerate_files
    echo
    echo "Rebuild your Pelican site to pick up the changes."
    exit 0
fi

PS3="Are you using Pelican for your site, or is it custom? "
select SITE_KIND in "Pelican" "Other"; do
    if [ -n "$SITE_KIND" ]; then
        break
    fi
    echo "Please choose a number 1-2."
done
set_conf_value site_kind "$SITE_KIND" "$CONFIG_FILE"

if [ "$SITE_KIND" = "Pelican" ]; then
    prompt_for_key site_root "Checkout path for the Pelican site" no yes "$CONFIG_FILE"
    SITE_ROOT=$(get_conf_value site_root "$CONFIG_FILE")
    require_absolute_path "$SITE_ROOT"

    if [ ! -f "$SITE_ROOT/pelicanconf.py" ]; then
        echo "Error: $SITE_ROOT/pelicanconf.py not found. This doesn't" >&2
        echo "look like a Pelican site checkout." >&2
        exit 1
    fi
else
    prompt_for_key site_root "Directory holding the files that make up your site (blank to use the directory for this app)" no no "$CONFIG_FILE"
    SITE_ROOT=$(get_conf_value site_root "$CONFIG_FILE")
    if [ -z "$SITE_ROOT" ]; then
        SITE_ROOT="$APP_DIR"
        set_conf_value site_root "$SITE_ROOT" "$CONFIG_FILE"
    else
        require_absolute_path "$SITE_ROOT"
        if [ ! -d "$SITE_ROOT" ]; then
            read -r -p "$SITE_ROOT doesn't exist yet. Create it? [y/N] " confirm
            if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
                exit 1
            fi
        fi
    fi
fi

FIELDS_FILE="$SITE_ROOT/data/application-fields.json"

regenerate_files

prompt_for_key smtp_user "SMTP from address, used only if a technical failure needs to notify an applicant" no yes "$CONFIG_FILE"
prompt_for_key smtp_password "SMTP password" yes yes "$SECRETS_FILE"
prompt_for_key reply_to_email "Reply-to address for emails this app sends (blank to use the SMTP from address)" no no "$CONFIG_FILE"

prompt_for_key zulip_site_url "Zulip site URL (e.g. https://miatsu.co)" no yes "$CONFIG_FILE"
prompt_for_key application_channel_id "Channel to post new applications to, by its numeric ID rather than its name, so a later rename doesn't break it (in the left sidebar, click the channel's ... menu, choose Copy link to channel, and use the number right after channel/ in that link)" no yes "$CONFIG_FILE"
CHANNEL_ID=$(get_conf_value application_channel_id "$CONFIG_FILE")
if ! [[ "$CHANNEL_ID" =~ ^[0-9]+$ ]]; then
    echo "Error: application_channel_id must be a number, the channel's ID, not its name." >&2
    exit 1
fi
prompt_for_key zulip_bot_email "Application bot's email address (Personal settings > Bots)" no yes "$CONFIG_FILE"
prompt_for_key zulip_bot_api_key "Application bot's API key" yes yes "$SECRETS_FILE"
prompt_for_key application_email_subject "Topic to post new applications under (blank uses 'New application')" no no "$CONFIG_FILE"
prompt_for_key contact_email "Contact address shown to an applicant who's already applied and waiting on review" no yes "$CONFIG_FILE"

prompt_for_key turnstile_site_key "Turnstile site key (blank to skip Cloudflare Turnstile verification)" no no "$CONFIG_FILE"
prompt_for_key turnstile_secret "Turnstile secret key (blank to skip Cloudflare Turnstile verification)" yes no "$SECRETS_FILE"

TURNSTILE_SITE_KEY=$(get_conf_value turnstile_site_key "$CONFIG_FILE")
if [ -n "$TURNSTILE_SITE_KEY" ]; then
    echo
    echo "Turnstile site key: $TURNSTILE_SITE_KEY"
    if [ "$SITE_KIND" = "Pelican" ]; then
        echo "Set the TURNSTILE_SITE_KEY environment variable to this before"
        echo "building the Pelican site, or change the default in pelicanconf.py."
    else
        echo "Put this in the data-sitekey attribute of your Turnstile widget."
    fi
fi

echo
echo "Checking the duplicate-application check against Zulip..."
if [ ! -f "$ZULIP_MANAGE_PY" ]; then
    echo "Error: $ZULIP_MANAGE_PY not found. This doesn't look like a" >&2
    echo "standard Zulip production install, so the duplicate-application" >&2
    echo "check won't work." >&2
    exit 1
fi
SMOKE_TEST_RESULT=$(CHECK_EMAIL="install-sh-smoke-test@example.com" "$ZULIP_MANAGE_PY" shell < "$APP_DIR/check_application_email.py" 2>&1 | grep "^RESULT:" || true)
if [ "$SMOKE_TEST_RESULT" != "RESULT:none" ]; then
    echo "Error: the duplicate-application check didn't produce the expected" >&2
    echo "result. Expected 'RESULT:none', got: '$SMOKE_TEST_RESULT'" >&2
    exit 1
fi
echo "Duplicate-application check is working."

if [ ! -d "$APP_DIR/.venv" ]; then
    python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

chown -R $RUN_AS_USER:$RUN_AS_USER "$APP_DIR"

sed -e "s|__APP_ROOT__|$APP_DIR|g" -e "s|__FIELDS_FILE__|$FIELDS_FILE|g" \
    "$APP_DIR/deploy/$SERVICE_NAME.service" > "$SERVICE_UNIT_PATH"
sed -e "s|__APP_ROOT__|$APP_DIR|g" \
    "$APP_DIR/deploy/$CHECK_PENDING_UNIT_NAME.service" > "$CHECK_PENDING_SERVICE_UNIT_PATH"
cp "$APP_DIR/deploy/$CHECK_PENDING_UNIT_NAME.timer" "$CHECK_PENDING_TIMER_UNIT_PATH"
systemctl daemon-reload
systemctl enable --now $SERVICE_NAME
systemctl enable --now "$CHECK_PENDING_UNIT_NAME.timer"

echo "$SERVICE_NAME is running on 127.0.0.1:8793."
echo "$CHECK_PENDING_UNIT_NAME.timer will check pending applications against Zulip daily."
echo

PS3="Which reverse proxy are you using? "
select PROXY_CHOICE in nginx apache caddy "I'll set this up manually"; do
    if [ -n "$PROXY_CHOICE" ]; then
        break
    fi
    echo "Please choose a number 1-4."
done

case "$PROXY_CHOICE" in
    nginx)
        if apply_reverse_proxy_config nginx "$APP_DIR/deploy/reverse-proxy/nginx.conf" '}'; then
            echo "Reverse proxy configured."
        else
            echo "Reverse proxy not configured automatically. See $APP_DIR/deploy/reverse-proxy/nginx.conf to add it yourself."
        fi
        ;;
    apache)
        if apply_reverse_proxy_config apache "$APP_DIR/deploy/reverse-proxy/apache.conf" '</VirtualHost>'; then
            echo "Reverse proxy configured."
        else
            echo "Reverse proxy not configured automatically. See $APP_DIR/deploy/reverse-proxy/apache.conf to add it yourself."
        fi
        ;;
    caddy)
        if apply_reverse_proxy_config caddy "$APP_DIR/deploy/reverse-proxy/caddy.conf" '}'; then
            echo "Reverse proxy configured."
        else
            echo "Reverse proxy not configured automatically. See $APP_DIR/deploy/reverse-proxy/caddy.conf to add it yourself."
        fi
        ;;
    *)
        echo "Skipping reverse proxy setup. See $APP_DIR/deploy/reverse-proxy/ for example configs to add yourself."
        ;;
esac
