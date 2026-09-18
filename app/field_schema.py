import re

FIELD_TYPES = {"text", "email", "textarea", "number", "select", "boolean", "multiselect"}

SCHEMA_ERRORS = {
    "missing_name": "Field schema is missing required key 'name': {field}",
    "invalid_type": "Field '{name}' has an invalid or missing 'type'",
    "missing_label": "Field '{name}' is missing required key 'label'",
    "missing_required": "Field '{name}' is missing required key 'required'",
    "incomplete_note": "Field '{name}' must set 'note_title', 'note_text', and 'note_type' together, or not at all",
    "missing_options": "Field '{name}' must have an 'options' list",
    "unexpected_conditional_options": "Field '{name}' has 'conditional_options' but isn't select/multiselect",
    "invalid_conditional_options": "Field '{name}' has a 'conditional_options' that isn't a dict",
}


class SchemaError(RuntimeError):
    def __init__(self, key, **kwargs):
        super().__init__(SCHEMA_ERRORS[key].format(**kwargs))


def validate_fields_schema(fields):
    """Validates every field, including nested conditional_options
    children, using an explicit stack instead of recursion so schema
    depth is never limited by the Python call stack.
    """
    pending = [(field, None) for field in fields]
    while pending:
        field, parent_name = pending.pop()
        if parent_name is None:
            if "name" not in field:
                raise SchemaError("missing_name", field=field)
            name = field["name"]
        else:
            name = parent_name

        if field.get("type") not in FIELD_TYPES:
            raise SchemaError("invalid_type", name=name)
        if "label" not in field:
            raise SchemaError("missing_label", name=name)
        if "required" not in field:
            raise SchemaError("missing_required", name=name)

        note_keys = ("note_title", "note_text", "note_type")
        present_note_keys = [key for key in note_keys if key in field]
        if present_note_keys and len(present_note_keys) != len(note_keys):
            raise SchemaError("incomplete_note", name=name)

        conditional_options = field.get("conditional_options")
        if field["type"] in ("select", "multiselect"):
            if not isinstance(field.get("options"), list):
                raise SchemaError("missing_options", name=name)
        elif conditional_options is not None:
            raise SchemaError("unexpected_conditional_options", name=name)

        if not conditional_options:
            continue
        if not isinstance(conditional_options, dict):
            raise SchemaError("invalid_conditional_options", name=name)
        for option, children in conditional_options.items():
            for child in children:
                pending.append((child, f"{name} > {option}"))


def name_conditional_fields(fields, parent_name, option):
    slug = re.sub(r"[^a-z0-9]+", "_", option.lower()).strip("_")
    base_name = f"{parent_name}_{slug}"
    named_fields = []
    for index, field in enumerate(fields):
        if index == 0:
            name = base_name
        else:
            name = f"{base_name}_{index + 1}"
        named_fields.append({**field, "name": name})
    return named_fields


def resolve_conditional_names(fields):
    resolved = []
    for field in fields:
        conditional_options = field.get("conditional_options")
        if conditional_options:
            field = {**field, "conditional_options": {
                option: resolve_conditional_names(name_conditional_fields(children, field["name"], option))
                for option, children in conditional_options.items()
            }}
        resolved.append(field)
    return resolved


def allowed_options(field):
    conditional_options = field.get("conditional_options")
    if not conditional_options:
        return field["options"]
    return field["options"] + list(conditional_options.keys())
