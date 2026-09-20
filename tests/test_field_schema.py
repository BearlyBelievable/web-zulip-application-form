import pytest

from field_schema import SchemaError, allowed_options, validate_fields_schema

from helpers import make_field


def test_valid_minimal_field_passes():
    validate_fields_schema([make_field()])


def test_missing_name_raises():
    field = make_field()
    del field["name"]
    with pytest.raises(SchemaError, match="missing required key 'name'"):
        validate_fields_schema([field])


def test_duplicate_name_raises():
    with pytest.raises(SchemaError, match="used more than once"):
        validate_fields_schema([make_field(name="dup"), make_field(name="dup")])


def test_invalid_type_raises():
    with pytest.raises(SchemaError, match="invalid or missing 'type'"):
        validate_fields_schema([make_field(type="bogus")])


def test_missing_label_raises():
    field = make_field()
    del field["label"]
    with pytest.raises(SchemaError, match="missing required key 'label'"):
        validate_fields_schema([field])


def test_missing_required_raises():
    field = make_field()
    del field["required"]
    with pytest.raises(SchemaError, match="missing required key 'required'"):
        validate_fields_schema([field])


def test_missing_note_raises():
    field = make_field()
    del field["note"]
    with pytest.raises(SchemaError, match="missing required key 'note'"):
        validate_fields_schema([field])


def test_note_that_is_not_a_dict_raises():
    with pytest.raises(SchemaError, match="isn't a dict"):
        validate_fields_schema([make_field(note="oops")])


def test_incomplete_note_raises():
    with pytest.raises(SchemaError, match="must set 'type', 'title', and 'text'"):
        validate_fields_schema([make_field(note={"type": "info"})])


def test_full_note_passes():
    validate_fields_schema([make_field(note={"type": "info", "title": "T", "text": "X"})])


def test_select_without_options_raises():
    with pytest.raises(SchemaError, match="must have an 'options' dict"):
        validate_fields_schema([make_field(type="select")])


def test_select_requires_at_least_two_options():
    with pytest.raises(SchemaError, match="at least 2 option"):
        validate_fields_schema([make_field(type="select", options={"A": {}})])


def test_select_with_two_options_passes():
    validate_fields_schema([make_field(type="select", options={"A": {}, "B": {}})])


def test_multiselect_requires_at_least_one_option():
    with pytest.raises(SchemaError, match="at least 1 option"):
        validate_fields_schema([make_field(type="multiselect", options={})])


def test_multiselect_with_one_option_passes():
    validate_fields_schema([make_field(type="multiselect", options={"A": {}})])


def test_boolean_without_options_passes():
    validate_fields_schema([make_field(type="boolean")])


def test_boolean_with_true_false_options_passes():
    nested = make_field(name="details", type="text")
    validate_fields_schema([make_field(type="boolean", options={"true": nested})])


def test_boolean_with_invalid_option_key_raises():
    nested = make_field(name="details", type="text")
    with pytest.raises(SchemaError, match="'true'/'false'"):
        validate_fields_schema([make_field(type="boolean", options={"Other": nested})])


def test_nested_field_missing_own_name_raises():
    nested = {"type": "text", "required": True, "label": "L", "note": {}}
    with pytest.raises(SchemaError, match="missing required key 'name'"):
        validate_fields_schema([make_field(type="select", options={"A": nested, "B": {}})])


def test_nested_field_name_colliding_with_a_sibling_raises():
    nested = make_field(name="field_a", type="text")
    with pytest.raises(SchemaError, match="used more than once"):
        validate_fields_schema([make_field(type="select", options={"A": nested, "B": {}})])


def test_nesting_one_level_deep_passes():
    nested = make_field(name="nested_field", type="text")
    validate_fields_schema([make_field(type="select", options={"A": nested, "B": {}})])


def test_nesting_two_levels_deep_raises():
    depth2 = make_field(name="depth2", type="text")
    depth1 = make_field(name="depth1", type="select", options={"A": depth2, "B": {}})
    with pytest.raises(SchemaError, match="nested more than"):
        validate_fields_schema([make_field(type="select", options={"X": depth1, "Y": {}})])


def test_invalid_option_value_raises():
    with pytest.raises(SchemaError, match="isn't a dict"):
        validate_fields_schema([make_field(type="select", options={"A": "oops", "B": {}})])


def test_allowed_options_returns_keys_in_order():
    field = make_field(type="select", options={"A": {}, "B": {}})
    assert allowed_options(field) == ["A", "B"]
