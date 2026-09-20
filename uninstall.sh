#!/usr/bin/env bash
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root." >&2
    exit 1
fi

if ! command -v systemctl &>/dev/null; then
    echo "Error: systemctl not found. This requires a systemd-based Ubuntu or" >&2
    echo "Debian system." >&2
    exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME=web-zulip-application-form
SERVICE_UNIT_PATH=/etc/systemd/system/$SERVICE_NAME.service
CHECK_PENDING_UNIT_NAME=web-zulip-application-form-check-pending
CHECK_PENDING_SERVICE_UNIT_PATH=/etc/systemd/system/$CHECK_PENDING_UNIT_NAME.service
CHECK_PENDING_TIMER_UNIT_PATH=/etc/systemd/system/$CHECK_PENDING_UNIT_NAME.timer
SECRETS_FILE="$APP_DIR/secrets.conf"
CONFIG_FILE="$APP_DIR/config.conf"

echo "App root: $APP_DIR"

get_conf_value() {
    local key="$1" file="$2" section
    [ -f "$file" ] || return 0
    section=$([ "$file" = "$SECRETS_FILE" ] && echo secrets || echo config)
    python3 "$APP_DIR/config_tool.py" get "$file" "$section" "$key"
}

confirmed() {
    [ "$1" = "y" ] || [ "$1" = "Y" ]
}

confirm_then() {
    local prompt="$1" confirm
    shift
    read -r -p "$prompt " confirm
    confirmed "$confirm" && "$@"
}

detect_site_confs() {
    local kind="$1" f
    case "$kind" in
        nginx)
            for f in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
                [ -f "$f" ] && grep -qF "127.0.0.1:8793" "$f" && echo "$f"
            done
            ;;
        apache)
            for f in /etc/apache2/sites-enabled/*.conf; do
                [ -f "$f" ] && grep -qF "127.0.0.1:8793" "$f" && echo "$f"
            done
            ;;
        caddy)
            [ -f /etc/caddy/Caddyfile ] && grep -qF "127.0.0.1:8793" /etc/caddy/Caddyfile && echo /etc/caddy/Caddyfile
            ;;
    esac
}

remove_snippet_block() {
    local kind="$1" snippet_file="$2" site_conf="$3" backup start_line snippet_lines confirm

    snippet_lines=$(wc -l < "$snippet_file")
    start_line=$(grep -n -F -x -f "$snippet_file" "$site_conf" | head -1 | cut -d: -f1)
    if [ -z "$start_line" ]; then
        echo "Couldn't find an exact match for the $kind snippet in $site_conf."
        echo "Remove the /apply block from it if it's still there."
        return
    fi

    mkdir -p "$APP_DIR/reverse-proxy-backups"
    backup="$APP_DIR/reverse-proxy-backups/$(basename "$site_conf").bak.$(date +%s)"
    cp "$site_conf" "$backup"

    sed -i "${start_line},$((start_line + snippet_lines - 1))d" "$site_conf"

    echo "--- Proposed change to $site_conf ---"
    diff -u "$backup" "$site_conf" || true
    echo "--------------------------------------"
    read -r -p "Apply this change and reload $kind? [y/N] " confirm
    if ! confirmed "$confirm"; then
        cp "$backup" "$site_conf"
        echo "Reverted. $site_conf left unchanged. Backup kept at $backup."
        return
    fi

    case "$kind" in
        nginx)
            if ! nginx -t; then
                cp "$backup" "$site_conf"
                echo "nginx config test failed. Restored $site_conf from backup." >&2
                return
            fi
            systemctl reload nginx
            ;;
        apache)
            if ! apache2ctl configtest; then
                cp "$backup" "$site_conf"
                echo "Apache config test failed. Restored $site_conf from backup." >&2
                return
            fi
            systemctl reload apache2
            ;;
        caddy)
            if ! caddy validate --config "$site_conf" --adapter caddyfile; then
                cp "$backup" "$site_conf"
                echo "Caddy config validation failed. Restored $site_conf from backup." >&2
                return
            fi
            systemctl reload caddy
            ;;
    esac
    echo "$kind reloaded. Backup of the original file kept at $backup."
}

if [ ! -f "$CONFIG_FILE" ]; then
    echo "No config.conf found here. Nothing looks installed from this checkout."
    exit 0
fi

SITE_KIND=$(get_conf_value site_kind "$CONFIG_FILE")
SITE_ROOT=$(get_conf_value site_root "$CONFIG_FILE")

echo
echo "This will:"
echo "  - Stop and remove the $SERVICE_NAME and $CHECK_PENDING_UNIT_NAME systemd units."
echo "  - Remove the generated application form files from $SITE_ROOT."
echo "  - Look for and offer to remove reverse proxy wiring and leftovers from"
echo "    older versions of this app."
echo "  - Remove this app's .venv."
echo "It will ask separately before touching config.conf, secrets.conf,"
echo "applications.db, or the checkout itself."
read -r -p "Continue? [y/N] " confirm
if ! confirmed "$confirm"; then
    exit 0
fi

echo
echo "Stopping services..."
for unit in "$SERVICE_NAME" "$CHECK_PENDING_UNIT_NAME.timer" "$CHECK_PENDING_UNIT_NAME.service"; do
    systemctl disable --now "$unit" 2>/dev/null || true
done
rm -f "$SERVICE_UNIT_PATH" "$CHECK_PENDING_SERVICE_UNIT_PATH" "$CHECK_PENDING_TIMER_UNIT_PATH"
systemctl daemon-reload
echo "Services stopped and unit files removed."

if [ -n "$SITE_ROOT" ]; then
    echo
    echo "Removing generated files from $SITE_ROOT..."
    rm -f "$SITE_ROOT/data/application-fields.json"

    if [ "$SITE_KIND" = "Pelican" ] && [ -f "$SITE_ROOT/pelicanconf.py" ]; then
        TEMPLATE_OVERRIDES_DIR=$(sed -n -E \
            "s/^THEME_TEMPLATES_OVERRIDES[[:space:]]*=[[:space:]]*\[[[:space:]]*['\"]([^'\"]+)['\"].*/\1/p" \
            "$SITE_ROOT/pelicanconf.py" | head -1)
        case "$TEMPLATE_OVERRIDES_DIR" in
            /*) ;;
            *) TEMPLATE_OVERRIDES_DIR="$SITE_ROOT/${TEMPLATE_OVERRIDES_DIR:-templates}" ;;
        esac

        rm -f "$SITE_ROOT/content/extra/js/application-form.js"
        rm -f "$SITE_ROOT/content/extra/css/application-form.css"
        rm -f "$TEMPLATE_OVERRIDES_DIR/application-form.html"

        if [ -f "$TEMPLATE_OVERRIDES_DIR/application.html" ]; then
            read -r -p "Remove $TEMPLATE_OVERRIDES_DIR/application.html too? It may have your own theme customizations. [y/N] " confirm
            if confirmed "$confirm"; then
                rm -f "$TEMPLATE_OVERRIDES_DIR/application.html"
            fi
        fi
    else
        rm -f "$SITE_ROOT/application-form.html" "$SITE_ROOT/application-form.js" "$SITE_ROOT/application-form.css"
    fi
    echo "Done."

    echo
    echo "Checking for leftovers from older versions of this app..."

    if [ -f "$SITE_ROOT/data/application-limits.json" ]; then
        rm -f "$SITE_ROOT/data/application-limits.json"
        echo "Removed $SITE_ROOT/data/application-limits.json."
    fi

    if [ "$SITE_KIND" = "Pelican" ] && [ -f "$SITE_ROOT/pelicanconf.py" ] \
        && grep -q "JINJA_GLOBALS = {'application_fields': APPLICATION_FIELDS}" "$SITE_ROOT/pelicanconf.py"; then
        echo
        echo "$SITE_ROOT/pelicanconf.py has an old application_fields JINJA_GLOBALS"
        echo "block. It will crash your next Pelican build:"
        echo
        grep -n -B2 "JINJA_GLOBALS = {'application_fields': APPLICATION_FIELDS}" "$SITE_ROOT/pelicanconf.py"
        echo
        read -r -p "Remove those lines from pelicanconf.py? [y/N] " confirm
        if confirmed "$confirm"; then
            mkdir -p "$APP_DIR/upgrade-backups"
            backup="$APP_DIR/upgrade-backups/pelicanconf.py.bak.$(date +%s)"
            cp "$SITE_ROOT/pelicanconf.py" "$backup"
            end_line=$(grep -n "JINJA_GLOBALS = {'application_fields': APPLICATION_FIELDS}" "$SITE_ROOT/pelicanconf.py" | head -1 | cut -d: -f1)
            start_line=$(grep -n "^with open(os.path.join(os.path.dirname(__file__), 'data', 'application-fields.json')) as f:" "$SITE_ROOT/pelicanconf.py" | head -1 | cut -d: -f1)
            if [ -n "$start_line" ] && [ -n "$end_line" ] && [ "$start_line" -le "$end_line" ]; then
                sed -i "${start_line},${end_line}d" "$SITE_ROOT/pelicanconf.py"
                echo "Removed. Backup kept at $backup."
            else
                echo "Couldn't find the exact block boundaries. Remove it by hand," \
                     "backup kept at $backup for reference." >&2
            fi
        fi
    fi
fi

echo
echo "Checking for reverse proxy wiring..."
for kind in nginx apache caddy; do
    while IFS= read -r site_conf; do
        [ -z "$site_conf" ] && continue
        echo "Found a $kind config still proxying to 127.0.0.1:8793: $site_conf"
        remove_snippet_block "$kind" "$APP_DIR/deploy/reverse-proxy/$kind.conf" "$site_conf"
    done < <(detect_site_confs "$kind")
done

rm -rf "$APP_DIR/.venv"
echo
echo "Removed .venv."

echo
confirm_then "Delete applications.db? This is your local record of pending and held applications. [y/N]" \
    rm -f "$APP_DIR/applications.db"

confirm_then "Delete config.conf and secrets.conf? [y/N]" \
    rm -f "$CONFIG_FILE" "$SECRETS_FILE"

confirm_then "Delete $APP_DIR/reverse-proxy-backups/ and $APP_DIR/upgrade-backups/? [y/N]" \
    rm -rf "$APP_DIR/reverse-proxy-backups" "$APP_DIR/upgrade-backups"

echo
echo "Uninstall complete. The checkout at $APP_DIR itself is left in place."
