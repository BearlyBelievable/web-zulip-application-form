#!/usr/bin/env bash
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root." >&2
    exit 1
fi

if ! command -v systemctl &>/dev/null; then
    echo "Error: systemctl not found. This requires a systemd-based Ubuntu or" >&2
    echo "Debian system with Zulip already installed." >&2
    exit 1
fi

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

SERVICE_NAME=web-zulip-application-form
SERVICE_UNIT_PATH=/etc/systemd/system/$SERVICE_NAME.service
CHECK_PENDING_UNIT_NAME=web-zulip-application-form-check-pending
CHECK_PENDING_SERVICE_UNIT_PATH=/etc/systemd/system/$CHECK_PENDING_UNIT_NAME.service
CHECK_PENDING_TIMER_UNIT_PATH=/etc/systemd/system/$CHECK_PENDING_UNIT_NAME.timer

if [ ! -f /etc/zulip/settings.py ]; then
    echo "Error: /etc/zulip/settings.py not found. This app requires Zulip to" >&2
    echo "already be installed on this server." >&2
    exit 1
fi

if ! id -u "$RUN_AS_USER" &>/dev/null; then
    echo "Error: the '$RUN_AS_USER' user doesn't exist, but /etc/zulip/settings.py" >&2
    echo "does. This requires a standard Zulip install." >&2
    exit 1
fi

echo "App root: $APP_DIR"

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

prompt_setting() {
    local mode="$1" key="$2" label="$3" silent="$4" file="$5"
    if [ "$mode" = "if_missing" ] && [ -n "$(get_conf_value "$key" "$file")" ]; then
        return
    fi
    prompt_for_key "$key" "$label" "$silent" yes "$file"
}

prompt_channel_id() {
    local mode="$1" current bot_email name channel_id options=() ids=() choice
    local page_size=15 start=0 total end page_options=() extra=()
    current=$(get_conf_value application_channel_id "$CONFIG_FILE")
    if [ -z "$current" ]; then
        bot_email=$(get_conf_value zulip_bot_email "$CONFIG_FILE")
        if [ -n "$bot_email" ]; then
            while IFS='|' read -r name channel_id; do
                [ -n "$channel_id" ] && options+=("$name") && ids+=("$channel_id")
            done < <(cd "$APP_DIR/app" && "$VENV_PYTHON" -c "
from zulip_integration import detect_channels
for name, channel_id in detect_channels('$bot_email'):
    print(f'{name}|{channel_id}')
" 2>/dev/null || true)

            total="${#ids[@]}"
            if [ "$total" -gt 0 ]; then
                echo "Found these channels the bot has access to:"
                while true; do
                    page_options=("${options[@]:$start:$page_size}")
                    end=$((start + ${#page_options[@]}))
                    extra=()
                    [ "$end" -lt "$total" ] && extra+=("show more")
                    extra+=("other (type a channel ID)")
                    PS3="Which channel should new applications post to? "
                    select choice in "${page_options[@]}" "${extra[@]}"; do
                        [ -n "$choice" ] && break
                        echo "Please choose a number 1-$((${#page_options[@]} + ${#extra[@]}))." >&2
                    done
                    if [ "$REPLY" -le "${#page_options[@]}" ]; then
                        set_conf_value application_channel_id "${ids[$((start + REPLY - 1))]}" "$CONFIG_FILE"
                        break
                    elif [ "$choice" = "show more" ]; then
                        start="$end"
                    else
                        break
                    fi
                done
            else
                echo "Couldn't find any channels the bot has access to yet."
            fi
            echo "If the channel you want isn't listed, add the bot to it in Zulip, then run install.sh again."
        fi
    fi
    prompt_setting "$mode" application_channel_id "Channel to post new applications to, by numeric ID (channel's ... menu > Copy link to channel > number after channel/)" no "$CONFIG_FILE"
    CHANNEL_ID=$(get_conf_value application_channel_id "$CONFIG_FILE")
    if ! [[ "$CHANNEL_ID" =~ ^[0-9]+$ ]]; then
        echo "Error: application_channel_id must be a number, the channel's ID, not its name." >&2
        exit 1
    fi
}

validate_turnstile_pair() {
    local site_key secret
    site_key=$(get_conf_value turnstile_site_key "$CONFIG_FILE")
    secret=$(get_conf_value turnstile_secret "$SECRETS_FILE")
    if [ -n "$site_key" ] && [ -z "$secret" ]; then
        echo "Error: turnstile_site_key is set but turnstile_secret is not. Set both or clear both." >&2
        exit 1
    fi
    if [ -z "$site_key" ] && [ -n "$secret" ]; then
        echo "Error: turnstile_secret is set but turnstile_site_key is not. Set both or clear both." >&2
        exit 1
    fi
}

prompt_zulip_site_url() {
    local mode="$1" current name url options=() urls=() choice
    current=$(get_conf_value zulip_site_url "$CONFIG_FILE")
    if [ "$mode" = "if_missing" ] && [ -n "$current" ]; then
        return
    fi
    if [ -z "$current" ]; then
        while IFS='|' read -r name url; do
            [ -n "$url" ] && options+=("$name ($url)") && urls+=("$url")
        done < <(cd "$APP_DIR/app" && "$VENV_PYTHON" -c "
from zulip_integration import detect_realms
for name, url in detect_realms():
    print(f'{name}|{url}')
" 2>/dev/null || true)

        if [ "${#urls[@]}" -eq 1 ]; then
            set_conf_value zulip_site_url "${urls[0]}" "$CONFIG_FILE"
        elif [ "${#urls[@]}" -gt 1 ]; then
            echo "Found multiple organizations on this server:"
            PS3="Which organization is this form for? "
            select choice in "${options[@]}" "other (type a URL)"; do
                [ -n "$choice" ] && break
                echo "Please choose a number 1-$((${#options[@]} + 1))." >&2
            done
            [ "$REPLY" -le "${#urls[@]}" ] && set_conf_value zulip_site_url "${urls[$((REPLY - 1))]}" "$CONFIG_FILE"
        fi
    fi
    prompt_for_key zulip_site_url "Zulip site URL" no yes "$CONFIG_FILE"
}

prompt_core_settings() {
    local mode="$1"
    prompt_setting "$mode" zulip_bot_email "Application bot's email, for Zulip API access (Personal settings > Bots)" no "$CONFIG_FILE"
    prompt_channel_id "$mode"
    prompt_setting "$mode" zulip_bot_api_key "Application bot's API key" yes "$SECRETS_FILE"
}

prompt_contact_email() {
    local mode="$1"
    prompt_setting "$mode" contact_email "Where alert emails are sent (technical failures, held applications), and the address shown to an applicant who's already applied and waiting on review" no "$CONFIG_FILE"
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
    local kind="$1" candidates=() override choice c

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
        PS3="Which $kind config should I use? "
        select choice in "${candidates[@]}" "other (type a path)"; do
            [ -n "$choice" ] && break
            echo "Please choose a number 1-$((${#candidates[@]} + 1))." >&2
        done
        if [ "$choice" = "other (type a path)" ]; then
            read -r -p "Path to your $kind site config file: " choice
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
    if ! confirmed "$confirm"; then
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

if [ ! -f "$SECRETS_FILE" ]; then
    cat > "$SECRETS_FILE" <<'EOF'
[secrets]
smtp_password =
turnstile_secret =
zulip_bot_api_key =
EOF
fi

if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" <<'EOF'
[config]
site_kind =
site_root =
zulip_site_url =
application_channel_id =
zulip_bot_email =
application_email_subject =
contact_email =
alert_emails_enabled =
smtp_host =
smtp_port =
smtp_user =
turnstile_site_key =

# Advanced settings, optional. Blank values use these defaults.
max_attempts_per_ip = 3
max_attempts_per_email = 3
rate_limit_window_minutes = 60
application_expiry_days = 30
max_body_bytes = 8192
max_text_length = 250
max_textarea_length = 1000
EOF
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
            if ! confirmed "$confirm"; then
                exit 1
            fi
        fi
    fi
fi

FIELDS_FILE="$SITE_ROOT/data/application-fields.json"

prompt_for_key turnstile_site_key "Turnstile site key (blank to skip Cloudflare Turnstile verification)" no no "$CONFIG_FILE"
prompt_for_key turnstile_secret "Turnstile secret key (blank to skip Cloudflare Turnstile verification)" yes no "$SECRETS_FILE"
validate_turnstile_pair

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

ensure_venv
regenerate_files

prompt_zulip_site_url always

prompt_core_settings always
prompt_for_key application_email_subject "Topic to post new applications under (blank uses 'New application')" no no "$CONFIG_FILE"

read -r -p "Send alert emails for technical failures and held applications? Recommended. [y/N] " confirm
if confirmed "$confirm"; then
    set_conf_value alert_emails_enabled yes "$CONFIG_FILE"
    if grep -q "^EMAIL_HOST" /etc/zulip/settings.py; then
        echo "These reuse Zulip's transactional email settings by default."
        echo "Set any of them to use a different account or server instead."
    else
        echo "Zulip doesn't have transactional email configured on this server,"
        echo "so set these yourself."
    fi
    prompt_for_key smtp_host "SMTP server" no no "$CONFIG_FILE"
    prompt_for_key smtp_port "SMTP port" no no "$CONFIG_FILE"
    prompt_for_key smtp_user "SMTP login and 'From' address" no no "$CONFIG_FILE"
    prompt_for_key smtp_password "SMTP password" yes no "$SECRETS_FILE"
else
    set_conf_value alert_emails_enabled no "$CONFIG_FILE"
fi

prompt_contact_email always

echo
echo "Checking the duplicate-application check against Zulip..."
if [ ! -f "$ZULIP_MANAGE_PY" ]; then
    echo "Error: $ZULIP_MANAGE_PY not found. This doesn't look like a" >&2
    echo "standard Zulip production install, so the duplicate-application" >&2
    echo "check won't work." >&2
    exit 1
fi
SMOKE_TEST_RESULT=$(cd "$APP_DIR/app" && "$VENV_PYTHON" -c "
from zulip_integration import check_application_email
print('RESULT:' + check_application_email('install-sh-smoke-test@example.com'))
" 2>&1 | grep "^RESULT:" || true)
if [ "$SMOKE_TEST_RESULT" != "RESULT:none" ]; then
    echo "Error: the duplicate-application check didn't produce the expected" >&2
    echo "result. Expected 'RESULT:none', got: '$SMOKE_TEST_RESULT'" >&2
    exit 1
fi
echo "Duplicate-application check is working."

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

if [ "$PROXY_CHOICE" = "I'll set this up manually" ]; then
    echo "Skipping reverse proxy setup. See $APP_DIR/deploy/reverse-proxy/ for example configs to add by hand."
else
    close_marker='}'
    [ "$PROXY_CHOICE" = "apache" ] && close_marker='</VirtualHost>'
    if apply_reverse_proxy_config "$PROXY_CHOICE" "$APP_DIR/deploy/reverse-proxy/$PROXY_CHOICE.conf" "$close_marker"; then
        echo "Reverse proxy configured."
    else
        echo "Reverse proxy not configured automatically. See $APP_DIR/deploy/reverse-proxy/$PROXY_CHOICE.conf to add it by hand."
    fi
fi
