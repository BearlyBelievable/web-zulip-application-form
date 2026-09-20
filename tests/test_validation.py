import pytest

from validation import (
    ValidationError,
    flatten_active_fields,
    normalize_field_value,
    validate_boolean_value,
    validate_multiselect_value,
    validate_number_value,
    validate_select_value,
    validate_submission,
    validate_text_value,
)

from helpers import FakeForm, make_field


def test_plain_fields_are_all_active():
    fields = [make_field(name="a"), make_field(name="b")]
    active = flatten_active_fields(FakeForm(), fields)
    assert [f["name"] for f in active] == ["a", "b"]


def test_select_reveals_matching_nested_field():
    nested = make_field(name="details", type="text")
    select = make_field(name="choice", type="select", options={"Other": nested, "Plain": {}})
    active = flatten_active_fields(FakeForm(choice="Other"), [select])
    assert [f["name"] for f in active] == ["choice", "details"]


def test_select_does_not_reveal_field_for_unselected_option():
    nested = make_field(name="details", type="text")
    select = make_field(name="choice", type="select", options={"Other": nested, "Plain": {}})
    active = flatten_active_fields(FakeForm(choice="Plain"), [select])
    assert [f["name"] for f in active] == ["choice"]


def test_multiselect_can_reveal_multiple_nested_fields():
    nested_a = make_field(name="a_details", type="text")
    nested_b = make_field(name="b_details", type="text")
    multi = make_field(
        name="picks",
        type="multiselect",
        required=False,
        options={"A": nested_a, "B": nested_b, "C": {}},
    )
    active = flatten_active_fields(FakeForm(picks=["A", "B"]), [multi])
    assert [f["name"] for f in active] == ["picks", "a_details", "b_details"]


def test_boolean_reveals_nested_field_for_true():
    nested = make_field(name="details", type="text")
    boolean = make_field(name="agree", type="boolean", options={"true": nested})
    active = flatten_active_fields(FakeForm(agree="true"), [boolean])
    assert [f["name"] for f in active] == ["agree", "details"]


def test_options_on_unsupported_type_is_ignored():
    field = make_field(
        name="plain_text",
        type="text",
        options={"Other": make_field(name="should_not_appear", type="text")},
    )
    active = flatten_active_fields(FakeForm(plain_text="Other"), [field])
    assert [f["name"] for f in active] == ["plain_text"]


def test_text_value_strips_and_collapses_whitespace():
    field = make_field(type="text")
    assert normalize_field_value(FakeForm(field_a="  a   b  "), field) == "a b"


def test_textarea_value_preserves_internal_whitespace():
    field = make_field(type="textarea")
    assert normalize_field_value(FakeForm(field_a="a\n\nb"), field) == "a\n\nb"


def test_multiselect_value_drops_empty_entries():
    field = make_field(type="multiselect", required=False)
    assert normalize_field_value(FakeForm(field_a=["a", "", "b"]), field) == ["a", "b"]


def test_text_too_long_raises():
    field = make_field(length={"max": 3})
    with pytest.raises(ValidationError):
        validate_text_value("abcd", field)


def test_text_too_short_raises():
    field = make_field(length={"min": 3})
    with pytest.raises(ValidationError):
        validate_text_value("ab", field)


def test_invalid_email_raises():
    field = make_field(type="email")
    with pytest.raises(ValidationError):
        validate_text_value("not-an-email", field)


def test_number_out_of_range_raises():
    field = make_field(type="number", range={"min": 1, "max": 5})
    with pytest.raises(ValidationError):
        validate_number_value("6", field)


def test_number_non_numeric_raises():
    field = make_field(type="number")
    with pytest.raises(ValidationError):
        validate_number_value("abc", field)


def test_select_rejects_value_outside_options():
    field = make_field(type="select", options={"A": {}, "B": {}})
    with pytest.raises(ValidationError):
        validate_select_value("C", field)


def test_multiselect_rejects_value_outside_options():
    field = make_field(type="multiselect", options={"A": {}})
    with pytest.raises(ValidationError):
        validate_multiselect_value(["A", "C"], field)


def test_boolean_rejects_non_true_false():
    field = make_field(type="boolean")
    with pytest.raises(ValidationError):
        validate_boolean_value("maybe", field)


def test_required_field_missing_produces_error():
    field = make_field(required=True)
    values, errors = validate_submission(FakeForm(), [field])
    assert values == {}
    assert len(errors) == 1


def test_valid_submission_collects_values():
    text_field = make_field(name="full_name", type="text")
    number_field = make_field(name="age", type="number", range={"min": 1, "max": 120})
    form = FakeForm(full_name="Ada", age="30")
    values, errors = validate_submission(form, [text_field, number_field])
    assert errors == []
    assert values == {"full_name": "Ada", "age": 30}


def test_optional_field_left_blank_is_skipped_without_error():
    field = make_field(required=False)
    values, errors = validate_submission(FakeForm(), [field])
    assert values == {}
    assert errors == []


def test_single_checkbox_multiselect_required_when_unchecked():
    field = make_field(name="agree", type="multiselect", required=True, options={"I agree": {}})
    values, errors = validate_submission(FakeForm(), [field])
    assert values == {}
    assert len(errors) == 1


def test_single_checkbox_multiselect_passes_when_checked():
    field = make_field(name="agree", type="multiselect", required=True, options={"I agree": {}})
    values, errors = validate_submission(FakeForm(agree=["I agree"]), [field])
    assert errors == []
    assert values == {"agree": ["I agree"]}
