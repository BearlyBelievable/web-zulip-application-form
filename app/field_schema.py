FIELD_TYPES = {"text", "email", "textarea", "number", "select", "boolean", "multiselect"}
MAX_NESTING_DEPTH = 2

SCHEMA_ERRORS = {
    "missing_name": "Field schema is missing required key 'name': {field}",
    "duplicate_name": "Field name '{name}' is used more than once",
    "invalid_type": "Field '{name}' has an invalid or missing 'type'",
    "missing_label": "Field '{name}' is missing required key 'label'",
    "missing_required": "Field '{name}' is missing required key 'required'",
    "missing_note": "Field '{name}' is missing required key 'note'",
    "invalid_note": "Field '{name}' has a 'note' that isn't a dict",
    "incomplete_note": "Field '{name}' must set 'type', 'title', and 'text' together in 'note'",
    "missing_options": "Field '{name}' must have an 'options' dict",
    "too_few_options": "Field '{name}' must have at least {min_count} option(s) in 'options'",
    "invalid_boolean_options": "Field '{name}' has 'options' keys other than 'true'/'false'",
    "invalid_option_value": "Field '{name}' has an option whose value isn't a dict",
    "too_deeply_nested": "Field '{name}' is nested more than {max_depth} levels deep",
}


class SchemaError(RuntimeError):
    def __init__(self, key, **kwargs):
        super().__init__(SCHEMA_ERRORS[key].format(**kwargs))


def validate_fields_schema(fields):
    seen_names = set()
    pending = [(field, 1) for field in fields]
    while pending:
        field, depth = pending.pop()

        if "name" not in field:
            raise SchemaError("missing_name", field=field)
        name = field["name"]
        if name in seen_names:
            raise SchemaError("duplicate_name", name=name)
        seen_names.add(name)

        if depth > MAX_NESTING_DEPTH:
            raise SchemaError("too_deeply_nested", name=name, max_depth=MAX_NESTING_DEPTH)

        if field.get("type") not in FIELD_TYPES:
            raise SchemaError("invalid_type", name=name)
        if "label" not in field:
            raise SchemaError("missing_label", name=name)
        if "required" not in field:
            raise SchemaError("missing_required", name=name)

        if "note" not in field:
            raise SchemaError("missing_note", name=name)
        note = field["note"]
        if not isinstance(note, dict):
            raise SchemaError("invalid_note", name=name)
        if note and sorted(note.keys()) != ["text", "title", "type"]:
            raise SchemaError("incomplete_note", name=name)

        if field["type"] == "boolean":
            options = field.get("options")
            if options is None:
                continue
            if not isinstance(options, dict) or not set(options.keys()) <= {"true", "false"}:
                raise SchemaError("invalid_boolean_options", name=name)
        elif field["type"] in ("select", "multiselect"):
            options = field.get("options")
            if not isinstance(options, dict):
                raise SchemaError("missing_options", name=name)
            min_count = 2 if field["type"] == "select" else 1
            if len(options) < min_count:
                raise SchemaError("too_few_options", name=name, min_count=min_count)
        else:
            continue

        for nested_field in options.values():
            if not nested_field:
                continue
            if not isinstance(nested_field, dict):
                raise SchemaError("invalid_option_value", name=name)
            pending.append((nested_field, depth + 1))


def allowed_options(field):
    return list(field["options"].keys())
