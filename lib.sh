APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_AS_USER=zulip
SECRETS_FILE="$APP_DIR/secrets.conf"
CONFIG_FILE="$APP_DIR/config.conf"
ZULIP_MANAGE_PY=/home/zulip/deployments/current/manage.py
VENV_PYTHON="$APP_DIR/.venv/bin/python"

conf_section() {
    [ "$1" = "$SECRETS_FILE" ] && echo secrets || echo config
}

get_conf_value() {
    local key="$1" file="$2"
    python3 "$APP_DIR/config_tool.py" get "$file" "$(conf_section "$file")" "$key"
}

set_conf_value() {
    local key="$1" value="$2" file="$3"
    python3 "$APP_DIR/config_tool.py" set "$file" "$key" "$value"
}

confirmed() {
    [ "$1" = "y" ] || [ "$1" = "Y" ]
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

ensure_venv() {
    if [ ! -d "$APP_DIR/.venv" ]; then
        python3 -m venv "$APP_DIR/.venv"
    fi
    "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
}

backup_before_upgrade() {
    local file="$1" backup
    mkdir -p "$APP_DIR/upgrade-backups"
    backup="$APP_DIR/upgrade-backups/$(basename "$file").bak.$(date +%s)"
    cp "$file" "$backup"
    echo "$backup"
}

upgrade_old_site() {
    local site_root="$1" template_overrides_dir="$2" backup start_line end_line confirm

    if [ -f "$site_root/data/application-limits.json" ]; then
        rm -f "$site_root/data/application-limits.json"
        echo "Removed $site_root/data/application-limits.json."
    fi

    if [ -n "$template_overrides_dir" ] && [ -f "$site_root/pelicanconf.py" ] \
        && grep -q "JINJA_GLOBALS = {'application_fields': APPLICATION_FIELDS}" "$site_root/pelicanconf.py"; then
        echo
        echo "$site_root/pelicanconf.py has an old application_fields JINJA_GLOBALS block:"
        echo
        grep -n -B2 "JINJA_GLOBALS = {'application_fields': APPLICATION_FIELDS}" "$site_root/pelicanconf.py"
        echo
        end_line=$(grep -n "JINJA_GLOBALS = {'application_fields': APPLICATION_FIELDS}" "$site_root/pelicanconf.py" | head -1 | cut -d: -f1)
        start_line=$(grep -n "^with open(os.path.join(os.path.dirname(__file__), 'data', 'application-fields.json')) as f:" "$site_root/pelicanconf.py" | head -1 | cut -d: -f1)
        if [ -n "$start_line" ] && [ -n "$end_line" ] && [ "$start_line" -le "$end_line" ]; then
            read -r -p "Remove those lines from pelicanconf.py? [y/N] " confirm
            if confirmed "$confirm"; then
                backup=$(backup_before_upgrade "$site_root/pelicanconf.py")
                sed -i "${start_line},${end_line}d" "$site_root/pelicanconf.py"
                echo "Removed. Backup kept at $backup."
            fi
        else
            echo "Couldn't find the exact block boundaries. Remove it by hand."
        fi
    fi

    if [ -n "$template_overrides_dir" ] && [ -f "$template_overrides_dir/application.html" ] \
        && grep -q "{% macro render_field" "$template_overrides_dir/application.html"; then
        echo
        echo "$template_overrides_dir/application.html is the old full-page template."
        echo "It won't work with the generated form."
        read -r -p "Replace it with the new starter template? [y/N] " confirm
        if confirmed "$confirm"; then
            backup=$(backup_before_upgrade "$template_overrides_dir/application.html")
            cp "$APP_DIR/examples/page-template.example.jinja" "$template_overrides_dir/application.html"
            chown "$RUN_AS_USER:$RUN_AS_USER" "$template_overrides_dir/application.html"
            echo "Replaced. Your old version is backed up at $backup. Customize"
            echo "the new starter for your theme."
        fi
    fi
}

write_form_files() {
    local js_file="$1" css_file="$2" form_file="$3" css_url="$4" js_url="$5"
    mkdir -p "$(dirname "$js_file")"
    cp "$APP_DIR/generator/application-form.js" "$js_file"
    mkdir -p "$(dirname "$css_file")"
    cp "$APP_DIR/generator/application-form.css" "$css_file"
    "$VENV_PYTHON" "$APP_DIR/generator/generate_form.py" "$fields_file" "$form_file" \
        --max-text-length "${max_text_length:-250}" --max-textarea-length "${max_textarea_length:-1000}" \
        --turnstile-site-key "$turnstile_site_key" --css-url "$css_url" --js-url "$js_url"
    chown "$RUN_AS_USER:$RUN_AS_USER" "$js_file" "$css_file" "$form_file"
}

regenerate_files() {
    local site_kind site_root fields_file template_overrides_dir

    site_kind=$(get_conf_value site_kind "$CONFIG_FILE")
    site_root=$(get_conf_value site_root "$CONFIG_FILE")

    upgrade_old_site "$site_root" ""

    fields_file="$site_root/data/application-fields.json"
    mkdir -p "$(dirname "$fields_file")"
    cp "$APP_DIR/application-fields.json" "$fields_file"
    chown "$RUN_AS_USER:$RUN_AS_USER" "$fields_file"
    echo "Wrote $fields_file from application-fields.json."

    max_text_length=$(get_conf_value max_text_length "$CONFIG_FILE")
    max_textarea_length=$(get_conf_value max_textarea_length "$CONFIG_FILE")
    turnstile_site_key=$(get_conf_value turnstile_site_key "$CONFIG_FILE")

    if [ "$site_kind" != "Pelican" ]; then
        js_file="$site_root/application-form.js"
        css_file="$site_root/application-form.css"
        form_file="$site_root/application-form.html"
        write_form_files "$js_file" "$css_file" "$form_file" /application-form.css /application-form.js
        echo "Wrote $js_file and $css_file."
        echo "Wrote $form_file. Embed its contents in your page."
        return
    fi

    if [ ! -f "$site_root/pelicanconf.py" ]; then
        echo "Error: $site_root/pelicanconf.py not found. $site_root doesn't" >&2
        echo "look like a Pelican site checkout anymore." >&2
        exit 1
    fi

    if grep -q "^STATIC_PATHS" "$site_root/pelicanconf.py"; then
        if ! grep -q "\"extra\"\|'extra'" "$site_root/pelicanconf.py"; then
            static_paths_line=$(grep -n "^STATIC_PATHS" "$site_root/pelicanconf.py" | head -1 | cut -d: -f1)
            echo "pelicanconf.py already defines STATIC_PATHS on line $static_paths_line. Add"
            echo "'extra' to it."
        fi
    else
        printf '\nSTATIC_PATHS = ["extra"]\n' >> "$site_root/pelicanconf.py"
        echo "Added STATIC_PATHS = [\"extra\"] to pelicanconf.py."
    fi

    template_overrides_dir=$(sed -n -E \
        "s/^THEME_TEMPLATES_OVERRIDES[[:space:]]*=[[:space:]]*\[[[:space:]]*['\"]([^'\"]+)['\"].*/\1/p" \
        "$site_root/pelicanconf.py" | head -1)

    if [ -z "$template_overrides_dir" ]; then
        template_overrides_dir="templates"
        printf '\nTHEME_TEMPLATES_OVERRIDES = ["templates"]\n' >> "$site_root/pelicanconf.py"
        echo "Added THEME_TEMPLATES_OVERRIDES = [\"templates\"] to pelicanconf.py."
    fi
    case "$template_overrides_dir" in
        /*) ;;
        *) template_overrides_dir="$site_root/$template_overrides_dir" ;;
    esac
    mkdir -p "$template_overrides_dir"

    upgrade_old_site "$site_root" "$template_overrides_dir"
    chown "$RUN_AS_USER:$RUN_AS_USER" "$site_root/pelicanconf.py"

    js_file="$site_root/content/extra/js/application-form.js"
    css_file="$site_root/content/extra/css/application-form.css"
    form_file="$template_overrides_dir/application-form.html"
    write_form_files "$js_file" "$css_file" "$form_file" /extra/css/application-form.css /extra/js/application-form.js
    echo "Wrote $js_file."
    echo "Wrote $css_file."
    echo "Wrote $form_file."

    page_template_file="$template_overrides_dir/application.html"
    if [ ! -f "$page_template_file" ]; then
        cp "$APP_DIR/examples/page-template.example.jinja" "$page_template_file"
        chown "$RUN_AS_USER:$RUN_AS_USER" "$page_template_file"
        echo "Wrote a starter $page_template_file. Customize it for your theme,"
        echo "then add 'Template: application' to the content page's metadata."
    fi
}
